from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncIterator, Mapping

import pytest
from sqlalchemy import select

from app.core.crypto import TokenEncryptor
from app.core.utils.time import utcnow
from app.db.models import Account, AccountStatus, UsageHistory
from app.db.session import SessionLocal
from app.modules.anthropic_proxy import api as anthropic_api_module
from app.modules.anthropic_proxy import service as anthropic_service_module
from app.modules.settings.repository import SettingsRepository

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def _bypass_proxy_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _allow(authorization, *, request=None):
        del authorization, request
        return None

    monkeypatch.setattr(anthropic_api_module, "validate_proxy_api_key_authorization", _allow)


class _FakeUpstreamResponse:
    def __init__(
        self,
        status: int,
        *,
        headers: Mapping[str, str] | None = None,
        body: bytes = b"",
        chunks: list[bytes] | None = None,
    ) -> None:
        self.status = status
        self.headers = dict(headers or {})
        self._body = body
        self._chunks = chunks or []
        self.closed = False

    async def read(self) -> bytes:
        return self._body

    async def aiter_chunked(self, chunk_size: int) -> AsyncIterator[bytes]:
        for chunk in self._chunks:
            yield chunk

    async def aclose(self) -> None:
        self.closed = True


async def _import_claude_account(async_client, email: str) -> None:
    payload = {
        "email": email,
        "claudeAiOauth": {
            "accessToken": f"sk-ant-oat01-{email}",
            "refreshToken": f"sk-ant-ort01-{email}",
            "expiresAt": (int(time.time()) + 8 * 3600) * 1000,
            "subscriptionType": "max",
        },
    }
    files = {"auth_json": ("keychain.json", json.dumps(payload), "application/json")}
    response = await async_client.post("/api/accounts/import", files=files)
    assert response.status_code == 200
    data = response.json()
    assert data["planType"] == "claude_max"


@pytest.mark.asyncio
async def test_import_creates_anthropic_account(async_client):
    await _import_claude_account(async_client, "one@example.com")

    list_response = await async_client.get("/api/accounts")
    assert list_response.status_code == 200
    accounts = list_response.json()["accounts"]
    claude = [a for a in accounts if a["email"] == "one@example.com"]
    assert len(claude) == 1
    assert claude[0]["provider"] == "anthropic"

    async with SessionLocal() as session:
        rows = (await session.execute(select(Account).where(Account.email == "one@example.com"))).scalars().all()
    assert len(rows) == 1
    assert rows[0].provider == "anthropic"
    assert rows[0].id_token_encrypted is None
    assert rows[0].access_token_expires_at is not None


@pytest.mark.asyncio
async def test_reimport_updates_account_in_place(async_client):
    """Re-importing a credential (the reauth repair flow) must update the
    existing row, not insert a duplicate whose sibling holds a dead token."""
    await _import_claude_account(async_client, "repair@example.com")

    async with SessionLocal() as session:
        account = (await session.execute(select(Account).where(Account.email == "repair@example.com"))).scalar_one()
        original_id = account.id
        account.status = AccountStatus.REAUTH_REQUIRED
        account.deactivation_reason = "account_auth_invalidated"
        await session.commit()

    payload = {
        "email": "repair@example.com",
        "claudeAiOauth": {
            "accessToken": "sk-ant-oat01-rotated",
            "refreshToken": "sk-ant-ort01-rotated",
            "expiresAt": (int(time.time()) + 8 * 3600) * 1000,
            "subscriptionType": "max",
        },
    }
    files = {"auth_json": ("keychain.json", json.dumps(payload), "application/json")}
    response = await async_client.post("/api/accounts/import", files=files)
    assert response.status_code == 200
    assert response.json()["accountId"] == original_id

    async with SessionLocal() as session:
        rows = (await session.execute(select(Account).where(Account.email == "repair@example.com"))).scalars().all()
    assert len(rows) == 1
    assert rows[0].id == original_id
    assert rows[0].status == AccountStatus.ACTIVE
    assert rows[0].deactivation_reason is None
    assert TokenEncryptor().decrypt(rows[0].access_token_encrypted) == "sk-ant-oat01-rotated"


@pytest.mark.asyncio
async def test_anthropic_import_never_merges_into_openai_row(async_client):
    """Even with merge-by-email enabled, providers never merge on a shared email."""
    encryptor = TokenEncryptor()
    async with SessionLocal() as session:
        settings_row = await SettingsRepository(session).get_or_create()
        settings_row.import_without_overwrite = False
        session.add(
            Account(
                id="openai-shared",
                email="shared@example.com",
                plan_type="plus",
                access_token_encrypted=encryptor.encrypt("openai-access"),
                refresh_token_encrypted=encryptor.encrypt("openai-refresh"),
                id_token_encrypted=encryptor.encrypt("openai-id"),
                last_refresh=utcnow(),
                status=AccountStatus.ACTIVE,
            )
        )
        await session.commit()

    await _import_claude_account(async_client, "shared@example.com")

    async with SessionLocal() as session:
        rows = (await session.execute(select(Account).where(Account.email == "shared@example.com"))).scalars().all()
    providers = sorted((row.provider or "openai") for row in rows)
    assert providers == ["anthropic", "openai"]
    openai_row = next(row for row in rows if (row.provider or "openai") == "openai")
    assert TokenEncryptor().decrypt(openai_row.access_token_encrypted) == "openai-access"


@pytest.mark.asyncio
async def test_relay_streams_and_fails_over(async_client, monkeypatch):
    await _import_claude_account(async_client, "primary@example.com")
    await _import_claude_account(async_client, "secondary@example.com")

    outcomes = [
        _FakeUpstreamResponse(
            429,
            headers={"anthropic-ratelimit-unified-reset": str(int(time.time()) + 300)},
            body=b'{"type":"error","error":{"type":"rate_limit_error","message":"slow down"}}',
        ),
        _FakeUpstreamResponse(
            200,
            headers={"content-type": "text/event-stream", "anthropic-ratelimit-unified-5h-remaining": "77"},
            chunks=[b"event: message_start\n\n", b"event: message_stop\n\n"],
        ),
    ]
    injected_auth: list[str | None] = []

    async def _fake_open_messages(url: str, *, body: bytes, headers: Mapping[str, str], idle_timeout_seconds: float):
        assert url == "https://api.anthropic.com/v1/messages"
        injected_auth.append(headers.get("Authorization"))
        return outcomes.pop(0)

    monkeypatch.setattr(anthropic_service_module, "open_messages", _fake_open_messages)

    async with async_client.stream(
        "POST",
        "/v1/messages",
        headers={"content-type": "application/json", "authorization": "Bearer client-proxy-key"},
        content=b'{"model":"claude-sonnet-5","stream":true}',
    ) as response:
        assert response.status_code == 200
        assert response.headers["anthropic-ratelimit-unified-5h-remaining"] == "77"
        collected = b""
        async for chunk in response.aiter_bytes():
            collected += chunk

    assert collected == b"event: message_start\n\nevent: message_stop\n\n"
    # Two upstream attempts: 429 then success. Client key never forwarded.
    assert len(injected_auth) == 2
    assert all(auth is not None and auth.startswith("Bearer sk-ant-oat01-") for auth in injected_auth)
    assert not any("client-proxy-key" in (auth or "") for auth in injected_auth)

    # The rate-limited account is persisted as such.
    async with SessionLocal() as session:
        rows = (await session.execute(select(Account).where(Account.provider == "anthropic"))).scalars().all()
    statuses = {row.email: row.status for row in rows}
    assert AccountStatus.RATE_LIMITED in statuses.values()


@pytest.mark.asyncio
async def test_relay_passes_client_error_through_verbatim(async_client, monkeypatch):
    await _import_claude_account(async_client, "validate@example.com")

    error_body = b'{"type":"error","error":{"type":"invalid_request_error","message":"bad model"}}'

    async def _fake_open_messages(url: str, *, body: bytes, headers: Mapping[str, str], idle_timeout_seconds: float):
        del body
        return _FakeUpstreamResponse(400, headers={"content-type": "application/json"}, body=error_body)

    monkeypatch.setattr(anthropic_service_module, "open_messages", _fake_open_messages)

    response = await async_client.post(
        "/v1/messages",
        headers={"content-type": "application/json", "authorization": "Bearer client-proxy-key"},
        content=b'{"model":"nope"}',
    )
    assert response.status_code == 400
    assert response.json()["error"]["type"] == "invalid_request_error"


@pytest.mark.asyncio
async def test_relay_ingests_usage_from_response_headers(async_client, app_instance, monkeypatch):
    await _import_claude_account(async_client, "usage@example.com")

    reset_at = int(time.time()) + 4 * 3600

    async def _fake_open_messages(url: str, *, body: bytes, headers: Mapping[str, str], idle_timeout_seconds: float):
        return _FakeUpstreamResponse(
            200,
            headers={
                "content-type": "application/json",
                "anthropic-ratelimit-unified-5h-utilization": "0.35",
                "anthropic-ratelimit-unified-5h-reset": str(reset_at),
            },
            body=b'{"id":"msg_usage"}',
        )

    monkeypatch.setattr(anthropic_service_module, "open_messages", _fake_open_messages)

    response = await async_client.post(
        "/v1/messages",
        headers={"content-type": "application/json", "authorization": "Bearer client-proxy-key"},
        content=b'{"model":"claude-sonnet-5"}',
    )
    assert response.status_code == 200

    # Usage is written on a background task; await the tracked tasks to settle.
    service = app_instance.state.anthropic_proxy_service
    for _ in range(50):
        if not service._usage_tasks:
            break
        await asyncio.gather(*list(service._usage_tasks))

    async with SessionLocal() as session:
        account = (await session.execute(select(Account).where(Account.email == "usage@example.com"))).scalar_one()
        rows = (
            (
                await session.execute(
                    select(UsageHistory).where(UsageHistory.account_id == account.id, UsageHistory.window == "primary")
                )
            )
            .scalars()
            .all()
        )
    assert len(rows) == 1
    assert rows[0].used_percent == 35.0
    assert rows[0].reset_at == reset_at


@pytest.mark.asyncio
async def test_relay_no_accounts_returns_anthropic_429(async_client, monkeypatch):
    async def _fail(*args, **kwargs):
        raise AssertionError("upstream must not be called with no accounts")

    monkeypatch.setattr(anthropic_service_module, "open_messages", _fail)

    response = await async_client.post(
        "/v1/messages",
        headers={"content-type": "application/json", "authorization": "Bearer client-proxy-key"},
        content=b'{"model":"claude-sonnet-5"}',
    )
    assert response.status_code == 429
    assert response.json()["type"] == "error"

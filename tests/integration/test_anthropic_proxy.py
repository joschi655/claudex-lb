from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Mapping

import pytest
from sqlalchemy import select

from app.core.crypto import TokenEncryptor
from app.core.providers import (
    CREDENTIAL_ANTHROPIC_API_KEY,
    CREDENTIAL_LEGACY_ANTHROPIC_OAUTH,
    PROVIDER_ANTHROPIC,
)
from app.core.utils.time import utcnow
from app.db.models import (
    Account,
    AccountStatus,
    AdditionalUsageHistory,
    ApiKeyUsageReservation,
    RequestLog,
    UsageHistory,
)
from app.db.session import SessionLocal
from app.modules.anthropic_proxy import api as anthropic_api_module
from app.modules.anthropic_proxy import service as anthropic_service_module

pytestmark = pytest.mark.integration


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
        del chunk_size
        for chunk in self._chunks:
            yield chunk

    async def aclose(self) -> None:
        self.closed = True


async def _create_claude_account(async_client, label: str, api_key: str) -> str:
    response = await async_client.post(
        "/api/accounts/anthropic-api-key",
        json={"label": label, "apiKey": api_key},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["provider"] == PROVIDER_ANTHROPIC
    assert payload["credentialKind"] == CREDENTIAL_ANTHROPIC_API_KEY
    assert api_key not in response.text
    assert response.headers["cache-control"].startswith("no-store")
    return payload["accountId"]


async def _enable_api_key_auth(async_client) -> None:
    response = await async_client.put(
        "/api/settings",
        json={
            "stickyThreadsEnabled": False,
            "preferEarlierResetAccounts": False,
            "apiKeyAuthEnabled": True,
        },
    )
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_console_key_onboarding_creates_distinct_encrypted_accounts(async_client):
    first_id = await _create_claude_account(async_client, "Production", "sk-ant-api-first")
    second_id = await _create_claude_account(async_client, "Production", "sk-ant-api-second")

    assert first_id != second_id
    response = await async_client.get("/api/accounts?provider=anthropic")
    assert response.status_code == 200
    accounts = response.json()["accounts"]
    assert {account["accountId"] for account in accounts} == {first_id, second_id}
    assert all(account["provider"] == PROVIDER_ANTHROPIC for account in accounts)
    assert all(account["credentialKind"] == CREDENTIAL_ANTHROPIC_API_KEY for account in accounts)

    async with SessionLocal() as session:
        rows = (await session.execute(select(Account).where(Account.id.in_([first_id, second_id])))).scalars().all()
    decrypted = {TokenEncryptor().decrypt(row.access_token_encrypted) for row in rows}
    assert decrypted == {"sk-ant-api-first", "sk-ant-api-second"}
    assert all(row.refresh_token_encrypted != b"" for row in rows)


@pytest.mark.asyncio
async def test_console_key_onboarding_rejects_blank_values(async_client):
    create_response = await async_client.post(
        "/api/accounts/anthropic-api-key",
        json={"label": "   ", "apiKey": "sk-ant-api-value"},
    )
    assert create_response.status_code == 422
    assert create_response.json()["error"]["code"] == "validation_error"

    account_id = await _create_claude_account(async_client, "Production", "sk-ant-api-original")
    replace_response = await async_client.put(
        f"/api/accounts/{account_id}/anthropic-api-key",
        json={"label": "Production", "apiKey": " \t "},
    )
    assert replace_response.status_code == 422
    assert replace_response.json()["error"]["code"] == "validation_error"


@pytest.mark.asyncio
async def test_messages_method_error_uses_anthropic_envelope(async_client):
    response = await async_client.get("/v1/messages")

    assert response.status_code == 404
    assert response.json()["type"] == "error"
    assert response.json()["error"]["type"] == "not_found_error"


@pytest.mark.asyncio
async def test_consumer_oauth_import_is_rejected(async_client):
    payload = {
        "email": "consumer@example.com",
        "claudeAiOauth": {
            "accessToken": "sk-ant-oat01-consumer",
            "refreshToken": "sk-ant-ort01-consumer",
            "expiresAt": 1_900_000_000_000,
        },
    }
    files = {"auth_json": ("claude-keychain.json", json.dumps(payload), "application/json")}

    response = await async_client.post("/api/accounts/import", files=files)

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_auth_json"


@pytest.mark.asyncio
async def test_replace_console_key_updates_exact_legacy_row(async_client):
    encryptor = TokenEncryptor()
    async with SessionLocal() as session:
        session.add(
            Account(
                id="legacy-claude-row",
                provider=PROVIDER_ANTHROPIC,
                credential_kind=CREDENTIAL_LEGACY_ANTHROPIC_OAUTH,
                email="legacy@anthropic.invalid",
                alias="Legacy Claude",
                plan_type="claude_max",
                access_token_encrypted=encryptor.encrypt("legacy-access"),
                refresh_token_encrypted=encryptor.encrypt("legacy-refresh"),
                id_token_encrypted=None,
                last_refresh=utcnow(),
                status=AccountStatus.DEACTIVATED,
                deactivation_reason="unsupported_anthropic_oauth",
            )
        )
        await session.commit()

    response = await async_client.put(
        "/api/accounts/legacy-claude-row/anthropic-api-key",
        json={"label": "Claude Production", "apiKey": "sk-ant-api-replacement"},
    )

    assert response.status_code == 200
    assert response.json()["accountId"] == "legacy-claude-row"
    assert "sk-ant-api-replacement" not in response.text
    async with SessionLocal() as session:
        row = await session.get(Account, "legacy-claude-row")
    assert row is not None
    assert row.credential_kind == CREDENTIAL_ANTHROPIC_API_KEY
    assert row.status == AccountStatus.ACTIVE
    assert row.deactivation_reason is None
    assert row.alias == "Claude Production"
    assert encryptor.decrypt(row.access_token_encrypted) == "sk-ant-api-replacement"


@pytest.mark.asyncio
async def test_relay_streams_with_console_key_and_fails_over_before_commit(async_client, monkeypatch):
    await _create_claude_account(async_client, "Primary", "sk-ant-api-primary")
    await _create_claude_account(async_client, "Secondary", "sk-ant-api-secondary")
    outcomes = [
        _FakeUpstreamResponse(
            429,
            headers={"anthropic-ratelimit-requests-reset": "2030-01-02T03:04:05Z"},
            body=b'{"type":"error","error":{"type":"rate_limit_error","message":"slow down"}}',
        ),
        _FakeUpstreamResponse(
            200,
            headers={"content-type": "text/event-stream"},
            chunks=[
                b'event: message_start\ndata: {"message":{"usage":{"input_tokens":12}}}\n\n',
                b'event: message_delta\ndata: {"usage":{"output_tokens":5}}\n\n',
            ],
        ),
    ]
    sent_headers: list[dict[str, str]] = []

    async def _fake_open_messages(url: str, *, body: bytes, headers: Mapping[str, str], idle_timeout_seconds: float):
        del body, idle_timeout_seconds
        assert url == "https://api.anthropic.com/v1/messages"
        sent_headers.append(dict(headers))
        return outcomes.pop(0)

    monkeypatch.setattr(anthropic_service_module, "open_messages", _fake_open_messages)

    async with async_client.stream(
        "POST",
        "/v1/messages",
        headers={"content-type": "application/json", "authorization": "Bearer client-proxy-key"},
        content=b'{"model":"claude-sonnet-5","stream":true}',
    ) as response:
        assert response.status_code == 200
        body = b"".join([chunk async for chunk in response.aiter_bytes()])

    assert b"message_delta" in body
    assert len(sent_headers) == 2
    assert all("Authorization" not in headers and "authorization" not in headers for headers in sent_headers)
    assert {headers["x-api-key"] for headers in sent_headers} == {
        "sk-ant-api-primary",
        "sk-ant-api-secondary",
    }
    async with SessionLocal() as session:
        log = (await session.execute(select(RequestLog).order_by(RequestLog.id.desc()))).scalars().first()
    assert log is not None
    assert log.provider == PROVIDER_ANTHROPIC
    assert log.input_tokens == 12
    assert log.output_tokens == 5
    assert log.cost_usd is None


@pytest.mark.asyncio
async def test_relay_persists_standard_rate_limits_not_openai_usage(async_client, app_instance, monkeypatch):
    account_id = await _create_claude_account(async_client, "Throughput", "sk-ant-api-throughput")

    async def _fake_open_messages(url: str, *, body: bytes, headers: Mapping[str, str], idle_timeout_seconds: float):
        del url, body, headers, idle_timeout_seconds
        return _FakeUpstreamResponse(
            200,
            headers={
                "content-type": "application/json",
                "anthropic-ratelimit-requests-limit": "1000",
                "anthropic-ratelimit-requests-remaining": "750",
                "anthropic-ratelimit-requests-reset": "2030-01-02T03:04:05Z",
            },
            body=b'{"id":"msg_usage","usage":{"input_tokens":9,"output_tokens":4,"cache_read_input_tokens":2}}',
        )

    monkeypatch.setattr(anthropic_service_module, "open_messages", _fake_open_messages)
    response = await async_client.post(
        "/v1/messages",
        headers={"content-type": "application/json"},
        content=b'{"model":"claude-sonnet-5"}',
    )
    assert response.status_code == 200

    service = app_instance.state.anthropic_proxy_service
    while service._usage_tasks:
        await asyncio.gather(*list(service._usage_tasks))

    async with SessionLocal() as session:
        additional = (
            (
                await session.execute(
                    select(AdditionalUsageHistory).where(AdditionalUsageHistory.account_id == account_id)
                )
            )
            .scalars()
            .all()
        )
        openai_usage = (
            (await session.execute(select(UsageHistory).where(UsageHistory.account_id == account_id))).scalars().all()
        )
        log = (await session.execute(select(RequestLog).where(RequestLog.account_id == account_id))).scalar_one()

    assert len(additional) == 1
    assert additional[0].quota_key == "anthropic_requests"
    assert additional[0].used_percent == 25.0
    assert additional[0].reset_at == 1_893_553_445
    assert openai_usage == []
    assert (log.input_tokens, log.output_tokens, log.cached_input_tokens) == (9, 4, 2)


@pytest.mark.asyncio
async def test_api_key_assignment_is_hard_boundary_and_usage_settles(async_client, monkeypatch):
    assigned_id = await _create_claude_account(async_client, "Assigned", "sk-ant-api-assigned")
    await _create_claude_account(async_client, "Unassigned", "sk-ant-api-unassigned")
    await _enable_api_key_auth(async_client)
    created = await async_client.post(
        "/api/api-keys/",
        json={
            "name": "claude-scoped",
            "assignedAccountIds": [assigned_id],
            "limits": [{"limitType": "total_tokens", "limitWindow": "daily", "maxValue": 1000}],
        },
    )
    assert created.status_code == 200
    client_key = created.json()["key"]
    api_key_id = created.json()["id"]
    upstream_keys: list[str] = []

    async def _fake_open_messages(url: str, *, body: bytes, headers: Mapping[str, str], idle_timeout_seconds: float):
        del url, body, idle_timeout_seconds
        upstream_keys.append(headers["x-api-key"])
        return _FakeUpstreamResponse(
            200,
            headers={"content-type": "application/json"},
            body=b'{"id":"assigned","usage":{"input_tokens":8,"output_tokens":3}}',
        )

    monkeypatch.setattr(anthropic_service_module, "open_messages", _fake_open_messages)
    response = await async_client.post(
        "/v1/messages",
        headers={"authorization": f"Bearer {client_key}", "content-type": "application/json"},
        content=b'{"model":"claude-sonnet-5","max_tokens":32}',
    )

    assert response.status_code == 200
    assert upstream_keys == ["sk-ant-api-assigned"]
    async with SessionLocal() as session:
        reservation = (
            await session.execute(select(ApiKeyUsageReservation).where(ApiKeyUsageReservation.api_key_id == api_key_id))
        ).scalar_one()
        log = (await session.execute(select(RequestLog).where(RequestLog.api_key_id == api_key_id))).scalar_one()
    assert reservation.status == "finalized"
    assert (reservation.input_tokens, reservation.output_tokens) == (8, 3)
    assert log.account_id == assigned_id
    assert log.provider == PROVIDER_ANTHROPIC


@pytest.mark.asyncio
async def test_alias_route_is_not_registered(async_client):
    response = await async_client.post(
        "/anthropic/v1/messages",
        headers={"content-type": "application/json"},
        content=b'{"model":"claude-sonnet-5"}',
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_oversized_chunked_body_stops_before_upstream(async_client, monkeypatch):
    await _create_claude_account(async_client, "Body Limit", "sk-ant-api-body-limit")
    monkeypatch.setattr(anthropic_api_module, "_MAX_BODY_BYTES", 32)

    async def _fail(*args, **kwargs):
        raise AssertionError("oversized body must not reach Anthropic")

    monkeypatch.setattr(anthropic_service_module, "open_messages", _fail)
    response = await async_client.post(
        "/v1/messages",
        headers={"content-type": "application/json"},
        content=b'{"model":"claude-sonnet-5","padding":"too-large"}',
    )

    assert response.status_code == 413
    assert response.json()["error"]["type"] == "invalid_request_error"


@pytest.mark.asyncio
async def test_openai_only_account_actions_reject_claude_before_dispatch(async_client):
    account_id = await _create_claude_account(async_client, "No OpenAI Actions", "sk-ant-api-actions")

    warmup = await async_client.put(
        f"/api/accounts/{account_id}/limit-warmup",
        json={"enabled": True},
    )
    reset = await async_client.post(f"/api/accounts/{account_id}/rate-limit-reset-credits/consume")
    usage_reset = await async_client.post(f"/api/accounts/{account_id}/usage-reset-credits/consume")

    assert warmup.status_code == 400
    assert warmup.json()["error"]["code"] == "provider_action_unsupported"
    assert reset.status_code == 400
    assert reset.json()["error"]["code"] == "provider_action_unsupported"
    assert usage_reset.status_code == 409
    assert usage_reset.json()["error"]["code"] == "account_usage_reset_consume_unavailable"


@pytest.mark.asyncio
async def test_relay_without_claude_accounts_returns_anthropic_error(async_client, monkeypatch):
    async def _fail(*args, **kwargs):
        raise AssertionError("upstream must not be called with no Claude accounts")

    monkeypatch.setattr(anthropic_service_module, "open_messages", _fail)
    response = await async_client.post(
        "/v1/messages",
        headers={"content-type": "application/json"},
        content=b'{"model":"claude-sonnet-5"}',
    )
    assert response.status_code == 429
    assert response.json()["type"] == "error"

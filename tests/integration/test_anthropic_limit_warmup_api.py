"""On-demand Claude limit warmup through the accounts router.

Contract: openspec/changes/add-anthropic-limit-warmup/specs/anthropic-provider/spec.md.
"""

from __future__ import annotations

import base64
import json
import time
from collections.abc import Mapping

import pytest

from app.core.anthropic import warmup as warmup_module
from app.core.auth import generate_unique_account_id
from app.core.utils.time import naive_utc_to_epoch, utcnow
from app.db.session import SessionLocal
from app.modules.usage.repository import UsageRepository

pytestmark = pytest.mark.integration


class _FakeUpstreamResponse:
    def __init__(self, status: int, *, headers: Mapping[str, str] | None = None, body: bytes = b"{}") -> None:
        self.status = status
        self.headers = dict(headers or {})
        self._body = body
        self.closed = False

    async def read(self) -> bytes:
        return self._body

    async def aclose(self) -> None:
        self.closed = True


def _queue_warmup_upstream(
    monkeypatch: pytest.MonkeyPatch, response: _FakeUpstreamResponse
) -> list[dict[str, object]]:
    sent: list[dict[str, object]] = []

    async def _fake_open_messages(url: str, *, body: bytes, headers: Mapping[str, str], idle_timeout_seconds: float):
        sent.append({"url": url, "body": body, "headers": dict(headers)})
        return response

    monkeypatch.setattr(warmup_module, "open_messages", _fake_open_messages)
    return sent


async def _import_claude_account(async_client, email: str) -> str:
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
    assert response.status_code == 200, response.text
    return response.json()["accountId"]


async def _import_openai_account(async_client, *, email: str, account_id: str) -> str:
    claims = {
        "email": email,
        "chatgpt_account_id": account_id,
        "https://api.openai.com/auth": {"chatgpt_plan_type": "pro"},
    }
    raw = json.dumps(claims, separators=(",", ":")).encode()
    id_token = f"header.{base64.urlsafe_b64encode(raw).rstrip(b'=').decode()}.sig"
    auth_json = {
        "tokens": {
            "idToken": id_token,
            "accessToken": "access-token-not-a-real-secret",
            "refreshToken": "refresh",
            "accountId": account_id,
        },
    }
    files = {"auth_json": ("auth.json", json.dumps(auth_json), "application/json")}
    response = await async_client.post("/api/accounts/import", files=files)
    assert response.status_code == 200, response.text
    return generate_unique_account_id(account_id, email)


async def _record_primary_window(account_id: str, *, reset_at: int | None, used_percent: float = 94.0) -> None:
    async with SessionLocal() as session:
        await UsageRepository(session).add_entry(
            account_id,
            used_percent=used_percent,
            window="primary",
            reset_at=reset_at,
            window_minutes=300,
        )
        await session.commit()


async def _record_weekly_window(account_id: str, *, reset_at: int | None, used_percent: float = 0.0) -> None:
    async with SessionLocal() as session:
        await UsageRepository(session).add_entry(
            account_id,
            used_percent=used_percent,
            window="secondary",
            reset_at=reset_at,
            window_minutes=10080,
        )
        await session.commit()


async def _latest_primary(account_id: str):
    async with SessionLocal() as session:
        latest = await UsageRepository(session).latest_by_account(window="primary", account_ids=[account_id])
        return latest.get(account_id)


@pytest.mark.asyncio
async def test_trigger_opens_a_window_and_records_the_new_one(async_client, monkeypatch):
    account_id = await _import_claude_account(async_client, "warmup-trigger@example.com")
    elapsed_reset = naive_utc_to_epoch(utcnow()) - 300
    await _record_primary_window(account_id, reset_at=elapsed_reset)
    new_reset = naive_utc_to_epoch(utcnow()) + 5 * 3600
    sent = _queue_warmup_upstream(
        monkeypatch,
        _FakeUpstreamResponse(
            200,
            headers={
                "anthropic-ratelimit-unified-5h-utilization": "0.01",
                "anthropic-ratelimit-unified-5h-reset": str(new_reset),
            },
            body=json.dumps({"usage": {"input_tokens": 11, "output_tokens": 1}}).encode(),
        ),
    )

    response = await async_client.post(f"/api/accounts/{account_id}/limit-warmup/trigger")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["sent"] is True
    assert body["success"] is True
    assert body["model"] == warmup_module.ANTHROPIC_WARMUP_MODEL

    assert len(sent) == 1
    upstream_body = json.loads(sent[0]["body"])
    assert upstream_body["max_tokens"] == 1
    assert upstream_body["model"] == warmup_module.ANTHROPIC_WARMUP_MODEL
    assert sent[0]["headers"]["Authorization"].startswith("Bearer sk-ant-oat01-")

    # The window the ping just opened is visible without serving a real request.
    entry = await _latest_primary(account_id)
    assert entry is not None
    assert entry.reset_at == new_reset
    assert entry.used_percent == pytest.approx(1.0)


@pytest.mark.asyncio
async def test_trigger_works_while_scheduled_warmup_is_disabled(async_client, monkeypatch):
    account_id = await _import_claude_account(async_client, "warmup-scheduler-off@example.com")
    await _record_primary_window(account_id, reset_at=naive_utc_to_epoch(utcnow()) - 300)
    settings_response = await async_client.get("/api/settings")
    assert settings_response.status_code == 200
    assert settings_response.json()["limitWarmupEnabled"] is False

    sent = _queue_warmup_upstream(monkeypatch, _FakeUpstreamResponse(200))

    response = await async_client.post(f"/api/accounts/{account_id}/limit-warmup/trigger")

    assert response.status_code == 200, response.text
    assert response.json()["sent"] is True
    assert len(sent) == 1


@pytest.mark.asyncio
async def test_trigger_reports_an_upstream_failure_without_pausing_the_account(async_client, monkeypatch):
    account_id = await _import_claude_account(async_client, "warmup-upstream-error@example.com")
    await _record_primary_window(account_id, reset_at=naive_utc_to_epoch(utcnow()) - 300)
    _queue_warmup_upstream(
        monkeypatch,
        _FakeUpstreamResponse(
            529,
            body=json.dumps({"error": {"type": "overloaded_error", "message": "upstream busy"}}).encode(),
        ),
    )

    response = await async_client.post(f"/api/accounts/{account_id}/limit-warmup/trigger")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["sent"] is True
    assert body["success"] is False
    assert body["errorCode"] == "overloaded_error"

    accounts = await async_client.get("/api/accounts")
    account = next(item for item in accounts.json()["accounts"] if item["accountId"] == account_id)
    assert account["status"] == "active"


@pytest.mark.asyncio
async def test_trigger_refuses_an_account_with_no_rolling_window(async_client, monkeypatch):
    account_id = await _import_claude_account(async_client, "warmup-no-window@example.com")
    sent = _queue_warmup_upstream(monkeypatch, _FakeUpstreamResponse(200))

    response = await async_client.post(f"/api/accounts/{account_id}/limit-warmup/trigger")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "account_not_warmable"
    assert sent == []


@pytest.mark.asyncio
async def test_trigger_warms_an_account_whose_window_has_run_out(async_client, monkeypatch):
    """A window with no reset has run out; that is what warm-up is for.

    The gate reads the row's presence, not its reset timestamp — otherwise the
    trigger switches itself off in exactly the state an operator reaches for it.
    """
    account_id = await _import_claude_account(async_client, "warmup-window-spent@example.com")
    await _record_primary_window(account_id, reset_at=None, used_percent=0.0)
    sent = _queue_warmup_upstream(monkeypatch, _FakeUpstreamResponse(200))

    response = await async_client.post(f"/api/accounts/{account_id}/limit-warmup/trigger")

    assert response.status_code == 200, response.text
    assert response.json()["sent"] is True
    assert len(sent) == 1


@pytest.mark.asyncio
async def test_trigger_warms_an_account_that_only_reports_a_weekly_window(async_client, monkeypatch):
    account_id = await _import_claude_account(async_client, "warmup-weekly-only@example.com")
    await _record_weekly_window(account_id, reset_at=naive_utc_to_epoch(utcnow()) + 86_400, used_percent=12.0)
    sent = _queue_warmup_upstream(monkeypatch, _FakeUpstreamResponse(200))

    response = await async_client.post(f"/api/accounts/{account_id}/limit-warmup/trigger")

    assert response.status_code == 200, response.text
    assert response.json()["sent"] is True
    assert len(sent) == 1


@pytest.mark.asyncio
async def test_trigger_warms_a_paused_account(async_client, monkeypatch):
    """Paused keeps an account out of routing, not out of warm-up: its window
    still ages, and the operator expects it live when they switch back."""
    account_id = await _import_claude_account(async_client, "warmup-paused@example.com")
    await _record_primary_window(account_id, reset_at=naive_utc_to_epoch(utcnow()) - 300)
    pause = await async_client.post(f"/api/accounts/{account_id}/pause")
    assert pause.status_code == 200
    sent = _queue_warmup_upstream(monkeypatch, _FakeUpstreamResponse(200))

    response = await async_client.post(f"/api/accounts/{account_id}/limit-warmup/trigger")

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert len(sent) == 1
    # Still parked afterwards -- a warm-up must not quietly rejoin the pool.
    listing = await async_client.get("/api/accounts?provider=all")
    entry = next(a for a in listing.json()["accounts"] if a["accountId"] == account_id)
    assert entry["status"] == "paused"


@pytest.mark.asyncio
async def test_trigger_refuses_a_non_anthropic_account(async_client, monkeypatch):
    account_id = await _import_openai_account(
        async_client,
        email="warmup-openai@example.com",
        account_id="acc_warmup_openai",
    )
    sent = _queue_warmup_upstream(monkeypatch, _FakeUpstreamResponse(200))

    response = await async_client.post(f"/api/accounts/{account_id}/limit-warmup/trigger")

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "account_provider_unsupported"
    assert sent == []


@pytest.mark.asyncio
async def test_trigger_on_a_missing_account_is_a_404(async_client):
    response = await async_client.post("/api/accounts/missing/limit-warmup/trigger")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "account_not_found"

"""``GET /api/accounts/next-up`` over the real route.

Contract: openspec/changes/show-the-next-serving-account/specs/account-routing/spec.md.

The unit tests next door drive the pure selector. These drive the endpoint: the
route itself, the per-provider fan-out, the failure isolation, and the promise
that asking leaves no trace on the pool.
"""

from __future__ import annotations

import base64
import json
import time

import pytest

from app.core.auth import generate_unique_account_id
from app.core.providers import PROVIDER_ANTHROPIC, PROVIDER_OPENAI
from app.dependencies import (
    get_anthropic_proxy_service_for_app,
    get_proxy_service_for_app,
)
from app.modules.proxy.load_balancer import RuntimeState

pytestmark = pytest.mark.integration


def _encode_jwt(payload: dict) -> str:
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    body = base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")
    return f"header.{body}.sig"


async def _import_codex_account(async_client, email: str, raw_account_id: str) -> str:
    auth_json = {
        "tokens": {
            "idToken": _encode_jwt(
                {
                    "email": email,
                    "chatgpt_account_id": raw_account_id,
                    "https://api.openai.com/auth": {"chatgpt_plan_type": "plus"},
                }
            ),
            "accessToken": "access",
            "refreshToken": "refresh",
            "accountId": raw_account_id,
        },
    }
    files = {"auth_json": ("auth.json", json.dumps(auth_json), "application/json")}
    response = await async_client.post("/api/accounts/import", files=files)
    assert response.status_code == 200, response.text
    return generate_unique_account_id(raw_account_id, email)


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


async def _next_up(async_client) -> dict[str, dict]:
    response = await async_client.get("/api/accounts/next-up")
    assert response.status_code == 200, response.text
    return {entry["provider"]: entry for entry in response.json()["nextUp"]}


async def test_the_route_answers_for_both_providers(async_client):
    await _import_codex_account(async_client, "codex@example.com", "codex-acct")
    await _import_claude_account(async_client, "claude@example.com")

    entries = await _next_up(async_client)

    assert set(entries) == {PROVIDER_OPENAI, PROVIDER_ANTHROPIC}


async def test_the_literal_path_is_not_read_as_an_account_id(async_client):
    """``/next-up`` sits next to ``/{account_id}/...`` routes on the same router."""
    await _import_codex_account(async_client, "codex@example.com", "codex-acct")

    response = await async_client.get("/api/accounts/next-up")

    assert response.status_code == 200
    assert "nextUp" in response.json()


async def test_the_account_named_is_one_of_the_pool(async_client):
    codex_id = await _import_codex_account(async_client, "codex@example.com", "codex-acct")

    entries = await _next_up(async_client)

    assert entries[PROVIDER_OPENAI]["accountId"] == codex_id


async def test_a_pinned_account_is_named_and_the_answer_is_certain(async_client):
    await _import_claude_account(async_client, "first@example.com")
    held = await _import_claude_account(async_client, "held@example.com")
    assert (await async_client.put(f"/api/accounts/{held}/pin", json={"pinned": True})).status_code == 200

    entry = (await _next_up(async_client))[PROVIDER_ANTHROPIC]

    assert entry["accountId"] == held
    assert entry["certain"] is True


async def test_a_paused_account_is_not_named(async_client):
    """The case a last-served view gets wrong: it keeps naming the account that
    just stopped being eligible."""
    paused = await _import_claude_account(async_client, "paused@example.com")
    live = await _import_claude_account(async_client, "live@example.com")
    assert (await async_client.post(f"/api/accounts/{paused}/pause")).status_code == 200

    entry = (await _next_up(async_client))[PROVIDER_ANTHROPIC]

    assert entry["accountId"] == live


async def test_a_provider_with_no_accounts_names_nobody_and_says_why(async_client):
    await _import_codex_account(async_client, "codex@example.com", "codex-acct")

    entry = (await _next_up(async_client))[PROVIDER_ANTHROPIC]

    assert entry["accountId"] is None
    assert entry["errorMessage"]


async def test_one_provider_failing_does_not_hide_the_other(async_client, monkeypatch, app_instance):
    """The per-provider try/except is the whole implementation of this promise."""
    await _import_codex_account(async_client, "codex@example.com", "codex-acct")
    claude_id = await _import_claude_account(async_client, "claude@example.com")

    async def _boom():
        raise RuntimeError("upstream preview exploded")

    monkeypatch.setattr(get_proxy_service_for_app(app_instance), "preview_next_account", _boom)

    entries = await _next_up(async_client)

    assert entries[PROVIDER_OPENAI]["accountId"] is None
    assert entries[PROVIDER_OPENAI]["errorMessage"] == "Preview unavailable"
    assert entries[PROVIDER_ANTHROPIC]["accountId"] == claude_id


async def test_asking_leaves_no_trace_on_the_pool(async_client, app_instance):
    """Read-only in the way that matters.

    ``_build_states`` writes health-tier bookkeeping back into whatever runtime
    it is handed, so a preview sharing the live runtime could latch an account
    into ``draining`` from a dashboard poll and steer real traffic. Compared as a
    whole-runtime snapshot rather than field by field, so a field added later is
    covered without anybody remembering to extend this test.
    """
    await _import_claude_account(async_client, "one@example.com")
    await _import_claude_account(async_client, "two@example.com")

    balancer = get_anthropic_proxy_service_for_app(app_instance)._load_balancer
    accounts = (await async_client.get("/api/accounts")).json()["accounts"]
    # Seed the runtime the way served traffic leaves it. An empty-to-empty
    # comparison would pass vacuously, and the regression this guards is a
    # *write into an existing entry* — the recent-error shape below is the one
    # that latches an account into `draining` when a poll ticks the health
    # machine that no request asked it to tick.
    for account in accounts:
        balancer._runtime[account["accountId"]] = RuntimeState(
            error_count=3,
            # Wall clock, matching what the serving path writes: seeding this
            # from time.monotonic() reads as an ancient error and the health
            # machine stays quiet, which would make this test pass vacuously.
            last_error_at=time.time(),
            last_selected_at=time.time(),
        )
    before = {account_id: vars(state).copy() for account_id, state in balancer._runtime.items()}
    assert before

    for _ in range(5):
        await _next_up(async_client)

    after = {account_id: vars(state).copy() for account_id, state in balancer._runtime.items()}
    assert after == before
    # It adds no entries either: the preview builds its states from a copy.
    assert set(after) == {account["accountId"] for account in accounts}


async def test_asking_writes_no_sticky_session(async_client):
    """A session mapping written by a status poll would pin an operator's browser
    to whichever account the dashboard happened to name."""
    await _import_claude_account(async_client, "one@example.com")
    await _import_claude_account(async_client, "two@example.com")

    def _rows(payload: dict) -> list:
        return payload.get("sessions", payload.get("items", []))

    before = _rows((await async_client.get("/api/sticky-sessions")).json())

    for _ in range(5):
        await _next_up(async_client)

    assert _rows((await async_client.get("/api/sticky-sessions")).json()) == before


async def test_repeated_asks_give_the_same_answer(async_client):
    """A preview that moved on every poll would be worse than no preview."""
    await _import_claude_account(async_client, "one@example.com")
    await _import_claude_account(async_client, "two@example.com")

    answers = set()
    for _ in range(8):
        answers.add((await _next_up(async_client))[PROVIDER_ANTHROPIC]["accountId"])

    assert len(answers) == 1

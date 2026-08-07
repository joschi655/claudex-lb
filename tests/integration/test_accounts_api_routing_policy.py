"""Routing policy writes over the dashboard account API.

Contract: openspec/specs/account-routing/spec.md.
"""

from __future__ import annotations

import base64
import json
import time

import pytest

from app.core.auth import generate_unique_account_id

pytestmark = pytest.mark.integration


def _encode_jwt(payload: dict) -> str:
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    body = base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")
    return f"header.{body}.sig"


async def _import_account(async_client, email: str, raw_account_id: str) -> str:
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


async def _set_policy(async_client, account_id: str, policy: str):
    return await async_client.put(
        f"/api/accounts/{account_id}/routing-policy",
        json={"routingPolicy": policy},
    )


async def _policies(async_client) -> dict[str, str]:
    response = await async_client.get("/api/accounts")
    assert response.status_code == 200, response.text
    return {account["accountId"]: account["routingPolicy"] for account in response.json()["accounts"]}


@pytest.mark.asyncio
async def test_pin_is_accepted_and_reported(async_client):
    account_id = await _import_account(async_client, "pin-one@example.com", "acct-pin-1")

    response = await _set_policy(async_client, account_id, "pinned")

    assert response.status_code == 200, response.text
    assert response.json()["routingPolicy"] == "pinned"
    assert (await _policies(async_client))[account_id] == "pinned"


@pytest.mark.asyncio
async def test_pinning_demotes_the_previous_pin(async_client):
    first = await _import_account(async_client, "pin-a@example.com", "acct-pin-a")
    second = await _import_account(async_client, "pin-b@example.com", "acct-pin-b")

    assert (await _set_policy(async_client, first, "pinned")).status_code == 200
    assert (await _set_policy(async_client, second, "pinned")).status_code == 200

    policies = await _policies(async_client)
    assert policies[second] == "pinned"
    assert policies[first] == "normal"


@pytest.mark.asyncio
async def test_pinning_leaves_other_routing_policies_alone(async_client):
    kept = await _import_account(async_client, "pin-keep@example.com", "acct-pin-keep")
    target = await _import_account(async_client, "pin-target@example.com", "acct-pin-target")

    assert (await _set_policy(async_client, kept, "preserve")).status_code == 200
    assert (await _set_policy(async_client, target, "pinned")).status_code == 200

    policies = await _policies(async_client)
    assert policies[kept] == "preserve"
    assert policies[target] == "pinned"


@pytest.mark.asyncio
async def test_pinning_is_scoped_to_one_provider(async_client):
    codex = await _import_account(async_client, "pin-codex@example.com", "acct-pin-codex")
    claude = await _import_claude_account(async_client, "pin-claude@example.com")

    assert (await _set_policy(async_client, codex, "pinned")).status_code == 200
    assert (await _set_policy(async_client, claude, "pinned")).status_code == 200

    policies = await _policies(async_client)
    assert policies[claude] == "pinned"
    assert policies[codex] == "pinned"


@pytest.mark.asyncio
async def test_unpinning_is_an_ordinary_policy_write(async_client):
    account_id = await _import_account(async_client, "pin-off@example.com", "acct-pin-off")

    assert (await _set_policy(async_client, account_id, "pinned")).status_code == 200
    assert (await _set_policy(async_client, account_id, "normal")).status_code == 200

    assert (await _policies(async_client))[account_id] == "normal"


@pytest.mark.asyncio
async def test_pinning_an_unknown_account_is_not_found(async_client):
    response = await _set_policy(async_client, "does-not-exist", "pinned")

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_an_unknown_policy_is_rejected(async_client):
    account_id = await _import_account(async_client, "pin-bad@example.com", "acct-pin-bad")

    response = await _set_policy(async_client, account_id, "pin")

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_pace_gates_round_trip_through_the_account_listing(async_client):
    account_id = await _import_account(async_client, "gates@example.com", "acct-gates")

    response = await async_client.put(
        f"/api/accounts/{account_id}/pace-gates",
        json={"paceMarginPrimaryPct": 20, "preResetWindowMinutes": 120},
    )
    assert response.status_code == 200, response.text

    listing = await async_client.get("/api/accounts")
    account = next(a for a in listing.json()["accounts"] if a["accountId"] == account_id)
    assert account["paceMarginPrimaryPct"] == 20
    assert account["preResetWindowMinutes"] == 120
    # Untouched gates stay unset — the dashboard must not read "off" as zero.
    assert account["paceMarginSecondaryPct"] is None


@pytest.mark.asyncio
async def test_an_idle_account_reports_no_serving_time(async_client):
    account_id = await _import_account(async_client, "idle@example.com", "acct-idle")

    listing = await async_client.get("/api/accounts")
    account = next(a for a in listing.json()["accounts"] if a["accountId"] == account_id)

    assert account["lastServedAt"] is None

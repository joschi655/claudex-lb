"""Pace gate configuration over the dashboard account API.

Contract: openspec/specs/account-routing/spec.md.
"""

from __future__ import annotations

import base64
import json

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


async def _summary(async_client, account_id: str) -> dict:
    response = await async_client.get("/api/accounts")
    assert response.status_code == 200, response.text
    accounts = response.json()["accounts"]
    matching = [account for account in accounts if account["accountId"] == account_id]
    assert matching, f"account {account_id} missing from listing"
    return matching[0]


@pytest.mark.asyncio
async def test_gates_default_to_unset(async_client):
    account_id = await _import_account(async_client, "gates-default@example.com", "acc_gates_default")
    summary = await _summary(async_client, account_id)
    assert summary["paceMarginPrimaryPct"] is None
    assert summary["paceMarginSecondaryPct"] is None
    assert summary["preResetWindowMinutes"] is None


@pytest.mark.asyncio
async def test_set_and_read_back_gates(async_client):
    account_id = await _import_account(async_client, "gates-set@example.com", "acc_gates_set")
    response = await async_client.put(
        f"/api/accounts/{account_id}/pace-gates",
        json={
            "paceMarginPrimaryPct": 10.0,
            "paceMarginSecondaryPct": 20.0,
            "preResetWindowMinutes": 120,
        },
    )
    assert response.status_code == 200, response.text
    assert response.json() == {
        "accountId": account_id,
        "paceMarginPrimaryPct": 10.0,
        "paceMarginSecondaryPct": 20.0,
        "preResetWindowMinutes": 120,
    }

    summary = await _summary(async_client, account_id)
    assert summary["paceMarginPrimaryPct"] == 10.0
    assert summary["paceMarginSecondaryPct"] == 20.0
    assert summary["preResetWindowMinutes"] == 120


@pytest.mark.asyncio
async def test_omitted_field_is_left_unchanged(async_client):
    account_id = await _import_account(async_client, "gates-partial@example.com", "acc_gates_partial")
    await async_client.put(
        f"/api/accounts/{account_id}/pace-gates",
        json={"pace_margin_primary_pct": 10.0, "pre_reset_window_minutes": 120},
    )
    response = await async_client.put(
        f"/api/accounts/{account_id}/pace-gates",
        json={"pace_margin_secondary_pct": 20.0},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["paceMarginPrimaryPct"] == 10.0
    assert body["preResetWindowMinutes"] == 120
    assert body["paceMarginSecondaryPct"] == 20.0


@pytest.mark.asyncio
async def test_explicit_null_clears_a_gate(async_client):
    account_id = await _import_account(async_client, "gates-clear@example.com", "acc_gates_clear")
    await async_client.put(
        f"/api/accounts/{account_id}/pace-gates",
        json={"pace_margin_primary_pct": 10.0, "pace_margin_secondary_pct": 20.0},
    )
    response = await async_client.put(
        f"/api/accounts/{account_id}/pace-gates",
        json={"pace_margin_primary_pct": None},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["paceMarginPrimaryPct"] is None
    assert body["paceMarginSecondaryPct"] == 20.0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        {"pace_margin_primary_pct": -1.0},
        {"pace_margin_primary_pct": 101.0},
        {"pace_margin_secondary_pct": 100.5},
        {"pre_reset_window_minutes": -5},
    ],
)
async def test_out_of_range_values_are_rejected(async_client, payload: dict):
    account_id = await _import_account(
        async_client,
        f"gates-invalid-{abs(hash(tuple(sorted(payload.items()))))}@example.com",
        f"acc_gates_invalid_{abs(hash(tuple(sorted(payload.items()))))}",
    )
    response = await async_client.put(f"/api/accounts/{account_id}/pace-gates", json=payload)
    assert response.status_code == 422, response.text

    summary = await _summary(async_client, account_id)
    assert summary["paceMarginPrimaryPct"] is None
    assert summary["paceMarginSecondaryPct"] is None
    assert summary["preResetWindowMinutes"] is None


@pytest.mark.asyncio
async def test_unknown_account_is_not_found(async_client):
    response = await async_client.put(
        "/api/accounts/does-not-exist/pace-gates",
        json={"pace_margin_primary_pct": 10.0},
    )
    assert response.status_code == 404, response.text

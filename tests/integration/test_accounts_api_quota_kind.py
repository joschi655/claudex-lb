"""The per-account quota-kind setting.

Contract: openspec/changes/declare-account-quota-kind/specs/account-quota-presentation/spec.md.

The setting is presentation only, so the tests that matter most are the ones
proving it leaves everything else alone.
"""

from __future__ import annotations

import json
import time

import pytest
from sqlalchemy import select, update

from app.db.models import Account
from app.db.session import SessionLocal

pytestmark = pytest.mark.integration


async def _import_account(async_client, email: str) -> str:
    """A Claude seat: the shape whose presentation this setting governs."""
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


async def _summary(async_client, account_id: str) -> dict:
    accounts = (await async_client.get("/api/accounts")).json()["accounts"]
    return next(a for a in accounts if a["accountId"] == account_id)


@pytest.mark.asyncio
async def test_an_account_defaults_to_auto(async_client, db_setup):
    account_id = await _import_account(async_client, "kind-default@example.com")

    assert (await _summary(async_client, account_id))["quotaKind"] == "auto"


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["subscription", "usage_based", "auto"])
async def test_the_kind_round_trips(async_client, db_setup, kind):
    account_id = await _import_account(async_client, f"kind-{kind}@example.com")

    response = await async_client.put(f"/api/accounts/{account_id}/quota-kind", json={"quotaKind": kind})

    assert response.status_code == 200, response.text
    assert response.json()["quotaKind"] == kind
    assert (await _summary(async_client, account_id))["quotaKind"] == kind


@pytest.mark.asyncio
async def test_an_unknown_kind_is_rejected(async_client, db_setup):
    account_id = await _import_account(async_client, "kind-bogus@example.com")

    response = await async_client.put(f"/api/accounts/{account_id}/quota-kind", json={"quotaKind": "pay_as_you_go"})

    assert response.status_code == 422
    assert (await _summary(async_client, account_id))["quotaKind"] == "auto"


@pytest.mark.asyncio
async def test_an_unknown_stored_value_reads_as_auto(async_client, db_setup):
    """A row written by a newer version must not hide a surface the account has."""
    account_id = await _import_account(async_client, "kind-stored@example.com")
    async with SessionLocal() as session:
        await session.execute(update(Account).where(Account.id == account_id).values(quota_kind="prepaid"))
        await session.commit()

    assert (await _summary(async_client, account_id))["quotaKind"] == "auto"


@pytest.mark.asyncio
async def test_setting_the_kind_leaves_routing_alone(async_client, db_setup):
    """Presentation only: the field must not become a back door into selection."""
    account_id = await _import_account(async_client, "kind-routing@example.com")
    assert (
        await async_client.put(f"/api/accounts/{account_id}/routing-policy", json={"routingPolicy": "preserve"})
    ).status_code == 200
    assert (await async_client.put(f"/api/accounts/{account_id}/pin", json={"pinned": True})).status_code == 200

    assert (
        await async_client.put(f"/api/accounts/{account_id}/quota-kind", json={"quotaKind": "usage_based"})
    ).status_code == 200

    summary = await _summary(async_client, account_id)
    assert summary["routingPolicy"] == "preserve"
    assert summary["pinned"] is True


@pytest.mark.asyncio
async def test_changing_routing_leaves_the_kind_alone(async_client, db_setup):
    account_id = await _import_account(async_client, "kind-routing-back@example.com")
    assert (
        await async_client.put(f"/api/accounts/{account_id}/quota-kind", json={"quotaKind": "usage_based"})
    ).status_code == 200

    assert (
        await async_client.put(f"/api/accounts/{account_id}/routing-policy", json={"routingPolicy": "burn_first"})
    ).status_code == 200

    summary = await _summary(async_client, account_id)
    assert summary["quotaKind"] == "usage_based"
    assert summary["routingPolicy"] == "burn_first"


@pytest.mark.asyncio
async def test_an_unknown_account_is_not_found(async_client, db_setup):
    response = await async_client.put("/api/accounts/does-not-exist/quota-kind", json={"quotaKind": "usage_based"})

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_only_the_named_account_changes(async_client, db_setup):
    first = await _import_account(async_client, "kind-one@example.com")
    second = await _import_account(async_client, "kind-two@example.com")

    assert (
        await async_client.put(f"/api/accounts/{first}/quota-kind", json={"quotaKind": "usage_based"})
    ).status_code == 200

    async with SessionLocal() as session:
        kinds = {row.id: row.quota_kind for row in (await session.execute(select(Account))).scalars()}
    assert kinds[first] == "usage_based"
    assert kinds[second] == "auto"

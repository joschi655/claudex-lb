"""Per-API-key account routing rules: openspec/specs/account-routing/spec.md."""

from __future__ import annotations

import base64
import json

import pytest

import app.modules.proxy.load_balancer as load_balancer_module
import app.modules.proxy.service as proxy_module
from app.core.auth import generate_unique_account_id
from app.core.openai.model_registry import ReasoningLevel, UpstreamModel, get_model_registry
from app.core.openai.models import OpenAIResponsePayload
from app.db.models import UsageHistory
from app.db.session import SessionLocal

pytestmark = pytest.mark.integration

_MODEL = "model-alpha"


def _encode_jwt(payload: dict) -> str:
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    return f"header.{base64.urlsafe_b64encode(raw).rstrip(b'=').decode('ascii')}.sig"


async def _import_account(async_client, raw_account_id: str, email: str) -> str:
    auth_json = {
        "tokens": {
            "idToken": _encode_jwt(
                {
                    "email": email,
                    "chatgpt_account_id": raw_account_id,
                    "https://api.openai.com/auth": {"chatgpt_plan_type": "plus"},
                }
            ),
            "accessToken": "access-token",
            "refreshToken": "refresh-token",
            "accountId": raw_account_id,
        },
    }
    files = {"auth_json": ("auth.json", json.dumps(auth_json), "application/json")}
    response = await async_client.post("/api/accounts/import", files=files)
    assert response.status_code == 200, response.text
    return generate_unique_account_id(raw_account_id, email)


async def _create_key(async_client, name: str) -> tuple[str, str]:
    response = await async_client.post("/api/api-keys/", json={"name": name})
    assert response.status_code == 200, response.text
    return response.json()["id"], response.json()["key"]


async def _enable_api_key_auth(async_client) -> None:
    response = await async_client.put(
        "/api/settings",
        json={
            "stickyThreadsEnabled": False,
            "preferEarlierResetAccounts": False,
            "totpRequiredOnLogin": False,
            "apiKeyAuthEnabled": True,
        },
    )
    assert response.status_code == 200, response.text


async def _register_model() -> None:
    model = UpstreamModel(
        slug=_MODEL,
        display_name=_MODEL,
        description="test",
        context_window=128000,
        input_modalities=("text",),
        supported_reasoning_levels=(ReasoningLevel(effort="medium", description="default"),),
        default_reasoning_level="medium",
        supports_reasoning_summaries=False,
        support_verbosity=False,
        default_verbosity=None,
        prefer_websockets=False,
        supports_parallel_tool_calls=True,
        supported_in_api=True,
        minimal_client_version=None,
        priority=0,
        available_in_plans=frozenset({"plus", "pro"}),
        raw={},
    )
    await get_model_registry().update({"plus": [model], "pro": [model]})


@pytest.mark.asyncio
async def test_rules_round_trip_and_inherit_everything_rules_are_dropped(async_client):
    first = await _import_account(async_client, "acc-rule-a", "rule-a@example.com")
    second = await _import_account(async_client, "acc-rule-b", "rule-b@example.com")
    key_id, _ = await _create_key(async_client, "rules-key")

    response = await async_client.put(
        f"/api/api-keys/{key_id}/account-routing-rules",
        json={
            "rules": [
                {"accountId": first, "routingPolicy": "burn_first"},
                {"accountId": second, "overrideGates": True, "usageCeilingSecondaryPct": 70.0},
            ]
        },
    )
    assert response.status_code == 200, response.text
    rules = {rule["accountId"]: rule for rule in response.json()["accountRoutingRules"]}
    assert rules[first]["routingPolicy"] == "burn_first"
    assert rules[first]["overrideGates"] is False
    assert rules[second]["overrideGates"] is True
    assert rules[second]["usageCeilingSecondaryPct"] == 70.0
    assert rules[second]["usageCeilingPrimaryPct"] is None

    # A rule that inherits everything is the same as no rule, so it is not stored.
    response = await async_client.put(
        f"/api/api-keys/{key_id}/account-routing-rules",
        json={"rules": [{"accountId": first}]},
    )
    assert response.status_code == 200, response.text
    assert response.json()["accountRoutingRules"] == []

    listed = await async_client.get("/api/api-keys/")
    assert listed.json()[0]["accountRoutingRules"] == []


@pytest.mark.asyncio
async def test_rules_reject_unknown_accounts_and_duplicates(async_client):
    account_id = await _import_account(async_client, "acc-rule-c", "rule-c@example.com")
    key_id, _ = await _create_key(async_client, "rules-invalid")

    unknown = await async_client.put(
        f"/api/api-keys/{key_id}/account-routing-rules",
        json={"rules": [{"accountId": "nope", "routingPolicy": "preserve"}]},
    )
    assert unknown.status_code == 400, unknown.text

    duplicate = await async_client.put(
        f"/api/api-keys/{key_id}/account-routing-rules",
        json={
            "rules": [
                {"accountId": account_id, "routingPolicy": "preserve"},
                {"accountId": account_id, "routingPolicy": "burn_first"},
            ]
        },
    )
    assert duplicate.status_code == 400, duplicate.text

    bad_policy = await async_client.put(
        f"/api/api-keys/{key_id}/account-routing-rules",
        json={"rules": [{"accountId": account_id, "routingPolicy": "drain"}]},
    )
    assert bad_policy.status_code in (400, 422), bad_policy.text


@pytest.mark.asyncio
async def test_two_keys_draw_the_same_pool_differently(async_client, monkeypatch):
    await _register_model()
    monkeypatch.setattr(
        load_balancer_module,
        "_filter_accounts_for_model",
        lambda accounts, model, *, service_tier=None: accounts,
    )
    owner_seat = await _import_account(async_client, "acc-owner-seat", "owner@example.com")
    own_seat = await _import_account(async_client, "acc-own-seat", "own@example.com")
    await _enable_api_key_auth(async_client)

    # The owner's seat is at 85% of its week and carries an 80% ceiling.
    response = await async_client.put(f"/api/accounts/{owner_seat}/pace-gates", json={"usageCeilingSecondaryPct": 80.0})
    assert response.status_code == 200, response.text
    async with SessionLocal() as session:
        session.add_all(
            [
                UsageHistory(account_id=owner_seat, window="primary", used_percent=10.0, window_minutes=300),
                UsageHistory(account_id=owner_seat, window="secondary", used_percent=85.0, window_minutes=10080),
                UsageHistory(account_id=own_seat, window="primary", used_percent=10.0, window_minutes=300),
                UsageHistory(account_id=own_seat, window="secondary", used_percent=20.0, window_minutes=10080),
            ]
        )
        await session.commit()

    _, respectful_key = await _create_key(async_client, "laptop")
    greedy_id, greedy_key = await _create_key(async_client, "desktop")
    # The desktop is allowed to finish the owner's seat and prefers it.
    response = await async_client.put(
        f"/api/api-keys/{greedy_id}/account-routing-rules",
        json={"rules": [{"accountId": owner_seat, "routingPolicy": "burn_first", "overrideGates": True}]},
    )
    assert response.status_code == 200, response.text

    served: list[str] = []

    async def fake_compact(payload, headers, access_token, account_id):
        del payload, headers, access_token
        served.append(account_id)
        return OpenAIResponsePayload.model_validate({"output": []})

    monkeypatch.setattr(proxy_module, "core_compact_responses", fake_compact)

    for key in (respectful_key, greedy_key):
        response = await async_client.post(
            "/backend-api/codex/responses/compact",
            headers={"Authorization": f"Bearer {key}"},
            json={"model": _MODEL, "instructions": "hi", "input": []},
        )
        assert response.status_code == 200, response.text

    assert served == ["acc-own-seat", "acc-owner-seat"]

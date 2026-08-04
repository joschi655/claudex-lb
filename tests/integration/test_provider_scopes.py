from __future__ import annotations

import pytest

from app.core.crypto import TokenEncryptor
from app.core.providers import (
    CREDENTIAL_ANTHROPIC_API_KEY,
    CREDENTIAL_OPENAI_OAUTH,
    PROVIDER_ANTHROPIC,
    PROVIDER_OPENAI,
)
from app.core.utils.time import utcnow
from app.db.models import Account, AccountStatus
from app.db.session import SessionLocal
from app.modules.accounts.repository import AccountsRepository
from app.modules.request_logs.repository import RequestLogsRepository
from app.modules.usage.repository import AdditionalUsageRepository, UsageRepository

pytestmark = pytest.mark.integration


def _account(account_id: str, provider: str) -> Account:
    encryptor = TokenEncryptor()
    is_anthropic = provider == PROVIDER_ANTHROPIC
    return Account(
        id=account_id,
        provider=provider,
        credential_kind=CREDENTIAL_ANTHROPIC_API_KEY if is_anthropic else CREDENTIAL_OPENAI_OAUTH,
        email=f"{account_id}@example.com",
        alias="Claude Production" if is_anthropic else "Codex Production",
        plan_type="claude_api" if is_anthropic else "plus",
        access_token_encrypted=encryptor.encrypt(f"access-{account_id}"),
        refresh_token_encrypted=encryptor.encrypt("" if is_anthropic else f"refresh-{account_id}"),
        id_token_encrypted=None if is_anthropic else encryptor.encrypt(f"id-{account_id}"),
        last_refresh=utcnow(),
        status=AccountStatus.ACTIVE,
    )


@pytest.mark.asyncio
async def test_provider_scopes_filter_accounts_traffic_capacity_and_log_facets(async_client):
    async with SessionLocal() as session:
        accounts = AccountsRepository(session)
        usage = UsageRepository(session)
        additional_usage = AdditionalUsageRepository(session)
        logs = RequestLogsRepository(session)
        await accounts.upsert(_account("provider-openai", PROVIDER_OPENAI))
        await accounts.upsert(_account("provider-anthropic", PROVIDER_ANTHROPIC))
        await usage.add_entry("provider-openai", 25.0, window="primary", window_minutes=300)
        await additional_usage.add_entry(
            "provider-anthropic",
            limit_name="requests",
            metered_feature="requests",
            window="primary",
            used_percent=40.0,
            reset_at=2_000_000_000,
            window_minutes=1,
            quota_key="anthropic_requests",
        )
        await logs.add_log(
            account_id="provider-openai",
            request_id="provider-openai-request",
            provider=PROVIDER_OPENAI,
            model="gpt-5.1",
            input_tokens=100,
            output_tokens=20,
            latency_ms=50,
            status="success",
            error_code=None,
        )
        await logs.add_log(
            account_id="provider-anthropic",
            request_id="provider-anthropic-request",
            provider=PROVIDER_ANTHROPIC,
            model="claude-sonnet-5",
            input_tokens=40,
            output_tokens=10,
            latency_ms=60,
            status="success",
            error_code=None,
        )

    all_accounts = await async_client.get("/api/accounts?provider=all")
    openai_accounts = await async_client.get("/api/accounts?provider=openai")
    anthropic_accounts = await async_client.get("/api/accounts?provider=anthropic")
    assert {row["provider"] for row in all_accounts.json()["accounts"]} == {
        PROVIDER_OPENAI,
        PROVIDER_ANTHROPIC,
    }
    assert [row["accountId"] for row in openai_accounts.json()["accounts"]] == ["provider-openai"]
    assert [row["accountId"] for row in anthropic_accounts.json()["accounts"]] == ["provider-anthropic"]

    all_overview = (await async_client.get("/api/dashboard/overview?provider=all")).json()
    openai_overview = (await async_client.get("/api/dashboard/overview?provider=openai")).json()
    anthropic_overview = (await async_client.get("/api/dashboard/overview?provider=anthropic")).json()

    assert all_overview["summary"]["metrics"]["requests"] == 2
    assert all_overview["summary"]["metrics"]["tokens"] == 170
    assert all_overview["summary"]["cost"]["isPartial"] is True
    assert len(all_overview["windows"]["primary"]["accounts"]) == 1
    assert openai_overview["summary"]["metrics"]["requests"] == 1
    assert openai_overview["summary"]["cost"]["isPartial"] is False
    assert anthropic_overview["summary"]["metrics"]["requests"] == 1
    assert anthropic_overview["summary"]["metrics"]["tokens"] == 50
    assert anthropic_overview["summary"]["cost"] == {
        "currency": "USD",
        "totalUsd": 0.0,
        "isPartial": True,
    }
    assert anthropic_overview["windows"]["primary"]["accounts"] == []
    assert anthropic_overview["accounts"][0]["additionalQuotas"] == [
        {
            "quotaKey": "anthropic_requests",
            "limitName": "requests",
            "meteredFeature": "requests",
            "displayLabel": "requests",
            "routingPolicy": "inherit",
            "primaryWindow": {
                "usedPercent": 40.0,
                "resetAt": 2_000_000_000,
                "windowMinutes": 1,
            },
            "secondaryWindow": None,
        }
    ]

    projections = (await async_client.get("/api/dashboard/projections?provider=anthropic")).json()
    assert projections == {
        "depletionPrimary": None,
        "depletionSecondary": None,
        "weeklyCreditPace": None,
    }

    logs_response = (await async_client.get("/api/request-logs?provider=anthropic")).json()
    assert logs_response["total"] == 1
    assert logs_response["requests"][0]["provider"] == PROVIDER_ANTHROPIC
    assert logs_response["requests"][0]["costUsd"] is None
    options = (await async_client.get("/api/request-logs/options?provider=anthropic")).json()
    assert options["accountIds"] == ["provider-anthropic"]
    assert options["modelOptions"] == [{"model": "claude-sonnet-5", "reasoningEffort": None}]

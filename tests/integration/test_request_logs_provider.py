from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import delete

from app.core.crypto import TokenEncryptor
from app.core.providers import PROVIDER_ANTHROPIC, PROVIDER_OPENAI
from app.core.utils.time import utcnow
from app.db.models import Account, AccountStatus, RequestLog
from app.db.session import SessionLocal
from app.modules.accounts.repository import AccountsRepository
from app.modules.request_logs.repository import RequestLogsRepository

pytestmark = pytest.mark.integration


def _make_account(account_id: str, email: str, provider: str) -> Account:
    encryptor = TokenEncryptor()
    return Account(
        id=account_id,
        email=email,
        plan_type="pro",
        provider=provider,
        access_token_encrypted=encryptor.encrypt("access"),
        refresh_token_encrypted=encryptor.encrypt("refresh"),
        id_token_encrypted=encryptor.encrypt("id"),
        last_refresh=utcnow(),
        status=AccountStatus.ACTIVE,
        deactivation_reason=None,
    )


async def _seed_both_providers() -> None:
    async with SessionLocal() as session:
        accounts_repo = AccountsRepository(session)
        logs_repo = RequestLogsRepository(session)
        await accounts_repo.upsert(_make_account("acc_codex", "codex@example.com", PROVIDER_OPENAI))
        await accounts_repo.upsert(_make_account("acc_claude", "claude@example.com", PROVIDER_ANTHROPIC))
        await session.commit()

        now = utcnow()
        await logs_repo.add_log(
            account_id="acc_codex",
            request_id="req_codex",
            model="gpt-5.6-sol",
            input_tokens=100,
            output_tokens=200,
            latency_ms=900,
            status="success",
            error_code=None,
            requested_at=now - timedelta(minutes=2),
        )
        await logs_repo.add_log(
            account_id="acc_claude",
            request_id="req_claude",
            model="claude-sonnet-4-5",
            input_tokens=105,
            output_tokens=42,
            latency_ms=1100,
            status="success",
            error_code=None,
            requested_at=now - timedelta(minutes=1),
        )


class TestProviderPersistence:
    @pytest.mark.asyncio
    async def test_provider_is_resolved_from_the_serving_account(self, db_setup):
        await _seed_both_providers()

        async with SessionLocal() as session:
            logs, _ = await RequestLogsRepository(session).list_recent(limit=10)

        provider_by_request = {log.request_id: log.provider for log in logs}
        assert provider_by_request["req_claude"] == PROVIDER_ANTHROPIC
        assert provider_by_request["req_codex"] == PROVIDER_OPENAI

    @pytest.mark.asyncio
    async def test_row_without_an_account_has_no_provider(self, db_setup):
        async with SessionLocal() as session:
            await RequestLogsRepository(session).add_log(
                account_id=None,
                request_id="req_unassigned",
                model="gpt-5.6-sol",
                input_tokens=None,
                output_tokens=None,
                latency_ms=10,
                status="error",
                error_code="no_account_available",
            )

        async with SessionLocal() as session:
            logs, _ = await RequestLogsRepository(session).list_recent(limit=10)

        assert [log.provider for log in logs] == [None]

    @pytest.mark.asyncio
    async def test_provider_survives_deletion_of_the_serving_account(self, db_setup):
        await _seed_both_providers()

        async with SessionLocal() as session:
            await session.execute(delete(Account).where(Account.id == "acc_claude"))
            await session.commit()

        async with SessionLocal() as session:
            logs, _ = await RequestLogsRepository(session).list_recent(limit=10, providers=[PROVIDER_ANTHROPIC])

        assert len(logs) == 1
        # The account is gone and the foreign key is ON DELETE SET NULL, so the
        # denormalized column is the only thing left that knows what served this.
        assert logs[0].account_id is None
        assert logs[0].provider == PROVIDER_ANTHROPIC

    @pytest.mark.asyncio
    async def test_explicit_provider_argument_is_not_overwritten(self, db_setup):
        async with SessionLocal() as session:
            accounts_repo = AccountsRepository(session)
            await accounts_repo.upsert(_make_account("acc_codex", "codex@example.com", PROVIDER_OPENAI))
            await session.commit()
            await RequestLogsRepository(session).add_log(
                account_id="acc_codex",
                request_id="req_explicit",
                model="claude-sonnet-4-5",
                input_tokens=1,
                output_tokens=1,
                latency_ms=5,
                status="success",
                error_code=None,
                provider=PROVIDER_ANTHROPIC,
            )

        async with SessionLocal() as session:
            logs, _ = await RequestLogsRepository(session).list_recent(limit=10)

        assert logs[0].provider == PROVIDER_ANTHROPIC


class TestProviderFiltering:
    @pytest.mark.asyncio
    async def test_filtering_to_one_provider_excludes_the_other(self, db_setup):
        await _seed_both_providers()

        async with SessionLocal() as session:
            repo = RequestLogsRepository(session)
            anthropic_logs, anthropic_total = await repo.list_recent(limit=10, providers=[PROVIDER_ANTHROPIC])
            openai_logs, openai_total = await repo.list_recent(limit=10, providers=[PROVIDER_OPENAI])

        assert [log.request_id for log in anthropic_logs] == ["req_claude"]
        assert anthropic_total == 1
        assert [log.request_id for log in openai_logs] == ["req_codex"]
        assert openai_total == 1

    @pytest.mark.asyncio
    async def test_unfiltered_listing_returns_every_provider(self, db_setup):
        await _seed_both_providers()

        async with SessionLocal() as session:
            logs, total = await RequestLogsRepository(session).list_recent(limit=10)

        assert {log.request_id for log in logs} == {"req_codex", "req_claude"}
        assert total == 2

    @pytest.mark.asyncio
    async def test_filter_options_report_every_provider_regardless_of_selection(self, db_setup):
        await _seed_both_providers()

        async with SessionLocal() as session:
            repo = RequestLogsRepository(session)
            unfiltered = await repo.list_filter_options()
            scoped = await repo.list_filter_options(providers=[PROVIDER_ANTHROPIC])

        assert sorted(unfiltered.providers) == [PROVIDER_ANTHROPIC, PROVIDER_OPENAI]
        # Selecting a provider must not remove the others from the control that
        # set it, so the facet ignores its own filter.
        assert sorted(scoped.providers) == [PROVIDER_ANTHROPIC, PROVIDER_OPENAI]
        assert scoped.account_ids == ["acc_claude"]

    @pytest.mark.asyncio
    async def test_api_filters_by_provider_and_exposes_it(self, async_client, db_setup):
        await _seed_both_providers()

        response = await async_client.get("/api/request-logs?limit=10&provider=anthropic")
        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 1
        assert [entry["requestId"] for entry in body["requests"]] == ["req_claude"]
        assert body["requests"][0]["provider"] == PROVIDER_ANTHROPIC

        unfiltered = await async_client.get("/api/request-logs?limit=10")
        assert unfiltered.json()["total"] == 2

    @pytest.mark.asyncio
    async def test_options_api_reports_providers(self, async_client, db_setup):
        await _seed_both_providers()

        response = await async_client.get("/api/request-logs/options")
        assert response.status_code == 200
        assert sorted(response.json()["providers"]) == [PROVIDER_ANTHROPIC, PROVIDER_OPENAI]

    @pytest.mark.asyncio
    async def test_reports_api_aggregates_one_provider_at_a_time(self, async_client, db_setup):
        await _seed_both_providers()

        response = await async_client.get("/api/reports?provider=anthropic")
        assert response.status_code == 200
        body = response.json()
        assert body["summary"]["totalRequests"] == 1
        assert [entry["model"] for entry in body["byModel"]] == ["claude-sonnet-4-5"]

        unfiltered = await async_client.get("/api/reports")
        assert unfiltered.json()["summary"]["totalRequests"] == 2

    @pytest.mark.asyncio
    async def test_reports_daily_rows_respect_the_provider_filter(self, async_client, db_setup):
        await _seed_both_providers()

        response = await async_client.get("/api/reports?provider=anthropic")
        assert response.status_code == 200
        daily = response.json()["daily"]
        assert sum(row["requests"] for row in daily) == 1
        assert sum(row["outputTokens"] for row in daily) == 42


@pytest.mark.asyncio
async def test_provider_filter_does_not_leak_through_the_count_cache(db_setup):
    """The cached total is keyed per filter signature; provider must be part of it."""
    await _seed_both_providers()

    async with SessionLocal() as session:
        repo = RequestLogsRepository(session)
        _, all_total = await repo.list_recent(limit=10)
        _, anthropic_total = await repo.list_recent(limit=10, providers=[PROVIDER_ANTHROPIC])

    assert all_total == 2
    assert anthropic_total == 1


@pytest.mark.asyncio
async def test_soft_deleted_rows_stay_out_of_provider_filtered_listings(db_setup):
    await _seed_both_providers()

    async with SessionLocal() as session:
        logs, _ = await RequestLogsRepository(session).list_recent(limit=10, providers=[PROVIDER_ANTHROPIC])
        target = logs[0]
        row = await session.get(RequestLog, target.id)
        assert row is not None
        row.deleted_at = utcnow()
        await session.commit()

    async with SessionLocal() as session:
        logs, total = await RequestLogsRepository(session).list_recent(limit=10, providers=[PROVIDER_ANTHROPIC])

    assert logs == []
    assert total == 0

from __future__ import annotations

from collections.abc import Collection
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.providers import AccountProvider
from app.core.usage.types import BucketModelAggregate, RequestActivityAggregate
from app.db.models import (
    Account,
    AccountLimitWarmup,
    AdditionalUsageHistory,
    DashboardSettings,
    RequestLog,
    UsageHistory,
)
from app.modules.accounts.repository import AccountsRepository
from app.modules.limit_warmup.repository import LimitWarmupRepository
from app.modules.request_logs.repository import RequestLogsRepository
from app.modules.settings.repository import SettingsRepository
from app.modules.usage.repository import AdditionalUsageRepository, UsageHistorySnapshot, UsageRepository


class DashboardRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._accounts_repo = AccountsRepository(session)
        self._usage_repo = UsageRepository(session)
        self._logs_repo = RequestLogsRepository(session)
        self._additional_usage_repo = AdditionalUsageRepository(session)
        self._limit_warmup_repo = LimitWarmupRepository(session)
        self._settings_repo = SettingsRepository(session)

    async def list_accounts(self) -> list[Account]:
        return await self._accounts_repo.list_accounts()

    async def latest_usage_by_account(
        self,
        window: str,
        *,
        account_ids: Collection[str] | None = None,
    ) -> dict[str, UsageHistory]:
        return await self._usage_repo.latest_by_account(window=window, account_ids=account_ids)

    async def usage_history_since(
        self,
        account_id: str,
        window: str,
        since: datetime,
    ) -> list[UsageHistory]:
        return await self._usage_repo.history_since(account_id, window, since)

    async def bulk_usage_history_since(
        self,
        account_ids: list[str],
        window: str,
        since: datetime,
    ) -> dict[str, list[UsageHistorySnapshot]]:
        return await self._usage_repo.bulk_history_since(account_ids, window, since)

    async def latest_window_minutes(self, window: str) -> int | None:
        return await self._usage_repo.latest_window_minutes(window)

    async def list_logs_since(self, since: datetime) -> list[RequestLog]:
        return await self._logs_repo.list_since(since)

    async def aggregate_logs_by_bucket(
        self,
        since: datetime,
        bucket_seconds: int = 21600,
        *,
        provider: AccountProvider | None = None,
    ) -> list[BucketModelAggregate]:
        return await self._logs_repo.aggregate_by_bucket(since, bucket_seconds, provider=provider)

    async def aggregate_activity_since(
        self,
        since: datetime,
        *,
        provider: AccountProvider | None = None,
    ) -> RequestActivityAggregate:
        return await self._logs_repo.aggregate_activity_since(since, provider=provider)

    async def aggregate_activity_between(
        self,
        since: datetime,
        until: datetime,
        *,
        provider: AccountProvider | None = None,
    ) -> RequestActivityAggregate:
        return await self._logs_repo.aggregate_activity_between(since, until, provider=provider)

    async def top_error_since(self, since: datetime, *, provider: AccountProvider | None = None) -> str | None:
        return await self._logs_repo.top_error_since(since, provider=provider)

    async def top_error_between(
        self,
        since: datetime,
        until: datetime,
        *,
        provider: AccountProvider | None = None,
    ) -> str | None:
        return await self._logs_repo.top_error_between(since, until, provider=provider)

    async def earliest_activity_at(self, *, provider: AccountProvider | None = None) -> datetime | None:
        return await self._logs_repo.earliest_activity_at(provider=provider)

    async def list_additional_quota_keys(
        self,
        *,
        account_ids: Collection[str] | None = None,
        since: datetime | None = None,
    ) -> list[str]:
        return await self._additional_usage_repo.list_quota_keys(account_ids=account_ids, since=since)

    async def latest_additional_usage_by_account(
        self,
        quota_key: str,
        window: str,
        *,
        account_ids: Collection[str] | None = None,
    ) -> dict[str, AdditionalUsageHistory]:
        return await self._additional_usage_repo.latest_by_account(
            quota_key,
            window,
            account_ids=account_ids,
        )

    async def additional_quota_routing_policy_overrides(self) -> dict[str, str]:
        return await self._accounts_repo.additional_quota_routing_policy_overrides()

    async def latest_additional_recorded_at(self) -> datetime | None:
        return await self._additional_usage_repo.latest_recorded_at()

    async def latest_limit_warmups_by_account(self, account_ids: list[str]) -> dict[str, AccountLimitWarmup]:
        return await self._limit_warmup_repo.latest_by_account(account_ids)

    async def get_settings(self) -> DashboardSettings:
        return await self._settings_repo.get_or_create()

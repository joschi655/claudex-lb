from __future__ import annotations

from collections.abc import Collection, Iterable, Mapping

from app.db.models import AdditionalUsageHistory
from app.modules.accounts.schemas import AccountAdditionalQuota, AccountAdditionalWindow
from app.modules.usage.additional_quota_keys import (
    get_additional_display_label_for_quota_key,
    get_additional_quota_routing_policy,
)

AdditionalQuotaEntries = tuple[
    str,
    Mapping[str, AdditionalUsageHistory],
    Mapping[str, AdditionalUsageHistory],
]


def build_additional_quotas_by_account(
    entries_by_quota: Iterable[AdditionalQuotaEntries],
    *,
    account_ids: Collection[str],
    routing_overrides: Mapping[str, str],
) -> dict[str, list[AccountAdditionalQuota]]:
    visible_account_ids = set(account_ids)
    quotas_by_account: dict[str, list[AccountAdditionalQuota]] = {}

    for quota_key, primary_entries, secondary_entries in entries_by_quota:
        entry_account_ids = (set(primary_entries) | set(secondary_entries)) & visible_account_ids
        for account_id in entry_account_ids:
            primary_entry = primary_entries.get(account_id)
            secondary_entry = secondary_entries.get(account_id)
            reference_entry = primary_entry or secondary_entry
            if reference_entry is None:
                continue
            quotas_by_account.setdefault(account_id, []).append(
                AccountAdditionalQuota(
                    quota_key=quota_key,
                    limit_name=reference_entry.limit_name,
                    metered_feature=reference_entry.metered_feature,
                    display_label=get_additional_display_label_for_quota_key(quota_key) or reference_entry.limit_name,
                    routing_policy=get_additional_quota_routing_policy(
                        quota_key,
                        overrides=dict(routing_overrides),
                    ),
                    primary_window=_window_from_entry(primary_entry),
                    secondary_window=_window_from_entry(secondary_entry),
                )
            )

    for account_quotas in quotas_by_account.values():
        account_quotas.sort(key=lambda quota: quota.display_label or quota.quota_key or quota.limit_name)
    return quotas_by_account


def _window_from_entry(entry: AdditionalUsageHistory | None) -> AccountAdditionalWindow | None:
    if entry is None:
        return None
    return AccountAdditionalWindow(
        used_percent=entry.used_percent,
        reset_at=entry.reset_at,
        window_minutes=entry.window_minutes,
    )

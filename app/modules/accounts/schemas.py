from __future__ import annotations

from datetime import datetime
from typing import List

from pydantic import Field, field_validator

from app.modules.shared.schemas import DashboardModel


class UsageTrendPoint(DashboardModel):
    t: datetime
    v: float


class AccountUsageTrend(DashboardModel):
    primary: list[UsageTrendPoint] = Field(default_factory=list)
    secondary: list[UsageTrendPoint] = Field(default_factory=list)
    secondary_scheduled: list[UsageTrendPoint] = Field(default_factory=list)


class AccountUsage(DashboardModel):
    primary_remaining_percent: float | None = None
    secondary_remaining_percent: float | None = None
    monthly_remaining_percent: float | None = None


class AccountRequestUsage(DashboardModel):
    request_count: int = 0
    total_tokens: int = 0
    cached_input_tokens: int = 0
    total_cost_usd: float = 0.0


class AccountUsageResetCredits(DashboardModel):
    available_count: int = Field(ge=0)


class AccountUsageResetCreditsResponse(DashboardModel):
    account_id: str
    rate_limit_reset_credits: AccountUsageResetCredits


class AccountTokenStatus(DashboardModel):
    expires_at: datetime | None = None
    state: str | None = None


class AccountAuthStatus(DashboardModel):
    access: AccountTokenStatus | None = None
    refresh: AccountTokenStatus | None = None
    id_token: AccountTokenStatus | None = None


class AccountLimitWarmupStatus(DashboardModel):
    window: str
    reset_at: int
    status: str
    model: str
    attempted_at: datetime
    completed_at: datetime | None = None
    error_code: str | None = None
    error_message: str | None = None


class AccountAdditionalWindow(DashboardModel):
    used_percent: float
    reset_at: int | None = None
    window_minutes: int | None = None


class AccountAdditionalQuota(DashboardModel):
    quota_key: str | None = None
    limit_name: str
    metered_feature: str
    display_label: str | None = None
    routing_policy: str = Field(default="inherit", pattern=r"^(inherit|normal|burn_first|preserve)$")
    primary_window: AccountAdditionalWindow | None = None
    secondary_window: AccountAdditionalWindow | None = None


class AccountSpendBudget(DashboardModel):
    """A dollar-denominated quota, for seats that bill against a budget.

    Present only for accounts that actually report one — a subscription seat's
    quota is its rolling windows and carries no budget.
    """

    used_percent: float
    used: float | None = None
    limit: float | None = None
    remaining: float | None = None
    currency: str | None = None
    reset_at: datetime | None = None


class AccountExtraCredits(DashboardModel):
    """The top-up pool that covers spend past a plan's own limits.

    Distinct from ``AccountSpendBudget``: that is the seat's own quota, this is
    the overflow behind it. Present whenever the account reports the facility at
    all, including when it is switched off — ``enabled`` carries that, and a
    disabled pool is exactly what an operator needs to see before turning it on.
    """

    enabled: bool
    used_percent: float
    used: float | None = None
    limit: float | None = None
    remaining: float | None = None
    currency: str | None = None


class AccountSummary(DashboardModel):
    account_id: str
    provider: str = "openai"
    chatgpt_account_id: str | None = None
    email: str
    alias: str | None = None
    display_name: str
    workspace_id: str | None = None
    workspace_label: str | None = None
    seat_type: str | None = None
    plan_type: str
    routing_policy: str = Field(default="normal", pattern=r"^(normal|burn_first|preserve)$")
    # Presentation only, and independent of everything around it: which quota
    # surface to show. ``auto`` reads it from the account's own usage rows.
    quota_kind: str = Field(default="auto", pattern=r"^(auto|subscription|usage_based)$")
    # Sits above the routing policy rather than inside it: a pinned account is
    # the pool's only route while the pin holds, and returns to its own policy
    # the moment it is lifted.
    pinned: bool = False
    pace_margin_primary_pct: float | None = None
    pace_margin_secondary_pct: float | None = None
    pre_reset_window_minutes: int | None = None
    status: str
    security_work_authorized: bool = False
    usage: AccountUsage | None = None
    reset_at_primary: datetime | None = None
    reset_at_secondary: datetime | None = None
    reset_at_monthly: datetime | None = None
    window_minutes_primary: int | None = None
    window_minutes_secondary: int | None = None
    window_minutes_monthly: int | None = None
    last_refresh_at: datetime | None = None
    # When this account most recently carried a request, within the recent
    # window the service asks for. Absent means "not recently", never "never":
    # the lookup is time-bounded so it can answer who is serving *now* without
    # scanning the whole request log.
    last_served_at: datetime | None = None
    capacity_credits_primary: float | None = None
    remaining_credits_primary: float | None = None
    capacity_credits_secondary: float | None = None
    remaining_credits_secondary: float | None = None
    capacity_credits_monthly: float | None = None
    remaining_credits_monthly: float | None = None
    request_usage: AccountRequestUsage | None = None
    additional_quotas: list[AccountAdditionalQuota] = Field(default_factory=list)
    credits_has: bool | None = None
    credits_unlimited: bool | None = None
    credits_balance: float | None = None
    spend_budget: AccountSpendBudget | None = None
    extra_credits: AccountExtraCredits | None = None
    deactivation_reason: str | None = None
    auth: AccountAuthStatus | None = None
    limit_warmup_enabled: bool = False
    limit_warmup: AccountLimitWarmupStatus | None = None
    # True when another account row in the same response shares this real email,
    # ChatGPT account identity, and workspace slot.
    # Operators see this after a token-invalidation cascade where re-adding
    # via OAuth creates a side-by-side row with a fresh refresh token; the
    # older row keeps a revoked token and keeps generating 401s through the
    # load balancer. Flagging the dupes in /accounts lets the dashboard
    # surface a "delete older" action without requiring the operator to
    # group rows by email themselves. See codex-lb #787 (B).
    is_email_duplicate: bool = False
    # Banked rate-limit reset credits from the in-memory snapshot when cached,
    # otherwise the latest persisted primary usage_history count from /wham/usage.
    available_reset_credits: int = 0
    reset_credit_nearest_expires_at: datetime | None = None


class AccountsResponse(DashboardModel):
    accounts: List[AccountSummary] = Field(default_factory=list)


class AccountImportResponse(DashboardModel):
    account_id: str
    email: str
    workspace_id: str | None = None
    workspace_label: str | None = None
    seat_type: str | None = None
    plan_type: str
    status: str


class OpenCodeOAuthAuth(DashboardModel):
    type: str = "oauth"
    refresh: str
    access: str
    expires: int = Field(ge=0)
    account_id: str | None = None


class OpenCodeAuthJson(DashboardModel):
    openai: OpenCodeOAuthAuth


class AccountOpenCodeAuthExportAccount(DashboardModel):
    account_id: str
    chatgpt_account_id: str | None = None
    email: str


class AccountOpenCodeAuthExportResponse(DashboardModel):
    filename: str
    account: AccountOpenCodeAuthExportAccount
    auth_json: OpenCodeAuthJson


class AccountUpdateRequest(DashboardModel):
    security_work_authorized: bool | None = None


class AccountUpdateResponse(DashboardModel):
    status: str


class AccountPauseResponse(DashboardModel):
    status: str


class AccountReactivateResponse(DashboardModel):
    status: str


class AccountLimitWarmupUpdateRequest(DashboardModel):
    enabled: bool


class AccountLimitWarmupUpdateResponse(DashboardModel):
    status: str
    enabled: bool


class AccountLimitWarmupTriggerResponse(DashboardModel):
    account_id: str
    # False only when another warm-up for this account is already in flight;
    # a request that went out and failed reports sent=True, success=False.
    sent: bool
    success: bool
    model: str
    latency_ms: int | None = None
    error_code: str | None = None
    error_message: str | None = None


class AccountRoutingPolicyUpdateRequest(DashboardModel):
    routing_policy: str = Field(pattern=r"^(normal|burn_first|preserve)$")


class AccountRoutingPolicyUpdateResponse(DashboardModel):
    account_id: str
    routing_policy: str


class NextAccountEntry(DashboardModel):
    """Who serves next for one provider, and how firm that answer is."""

    provider: str
    account_id: str | None = None
    # False when the configured strategy draws at random among weighted
    # candidates: the account named is the front-runner, not a promise.
    certain: bool = True
    # Why nothing would be selected — an empty pool, every account gated, and so
    # on. Present only when ``account_id`` is null.
    error_message: str | None = None


class NextAccountsResponse(DashboardModel):
    next_up: List[NextAccountEntry] = Field(default_factory=list)


class AccountQuotaKindUpdateRequest(DashboardModel):
    quota_kind: str = Field(pattern=r"^(auto|subscription|usage_based)$")


class AccountQuotaKindUpdateResponse(DashboardModel):
    account_id: str
    quota_kind: str


class AccountPinUpdateRequest(DashboardModel):
    pinned: bool


class AccountPinUpdateResponse(DashboardModel):
    account_id: str
    pinned: bool
    # Echoed back so a caller that just lifted a pin can see which policy the
    # account fell back to without a second read.
    routing_policy: str


class AccountPaceGatesUpdateRequest(DashboardModel):
    """Pace gates for one account.

    Every field is nullable. Omitting a field leaves the stored value untouched;
    sending an explicit null clears that gate. Callers must therefore consult
    ``model_fields_set`` rather than testing for ``None``.
    """

    pace_margin_primary_pct: float | None = Field(default=None, ge=0.0, le=100.0)
    pace_margin_secondary_pct: float | None = Field(default=None, ge=0.0, le=100.0)
    pre_reset_window_minutes: int | None = Field(default=None, ge=0)


class AccountPaceGatesUpdateResponse(DashboardModel):
    account_id: str
    pace_margin_primary_pct: float | None = None
    pace_margin_secondary_pct: float | None = None
    pre_reset_window_minutes: int | None = None


class AccountDeleteResponse(DashboardModel):
    status: str


class AccountExportResponse(DashboardModel):
    account_id: str
    email: str
    workspace_id: str | None = None
    workspace_label: str | None = None
    seat_type: str | None = None
    plan_type: str
    status: str
    auth_json: str


class AccountProbeRequest(DashboardModel):
    model: str | None = Field(
        default=None,
        description=(
            "Optional model slug for the probe request. Defaults to the service's configured fallback when omitted."
        ),
    )


class AccountProbeResponse(DashboardModel):
    status: str
    account_id: str
    probe_status_code: int
    primary_used_percent_before: float | None = None
    primary_used_percent_after: float | None = None
    secondary_used_percent_before: float | None = None
    secondary_used_percent_after: float | None = None
    account_status_before: str
    account_status_after: str


class AccountUsageResetConsumeRequest(DashboardModel):
    redeem_request_id: str | None = None

    @field_validator("redeem_request_id")
    @classmethod
    def normalize_redeem_request_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("redeem_request_id must not be empty")
        return normalized


class AccountUsageResetConsumeResponse(DashboardModel):
    status: str
    account_id: str
    code: str
    windows_reset: int = 0
    usage_written: bool
    primary_used_percent_before: float | None = None
    primary_used_percent_after: float | None = None
    secondary_used_percent_before: float | None = None
    secondary_used_percent_after: float | None = None
    account_status_before: str
    account_status_after: str


class AccountTrendsResponse(DashboardModel):
    account_id: str
    primary: list[UsageTrendPoint] = Field(default_factory=list)
    secondary: list[UsageTrendPoint] = Field(default_factory=list)
    secondary_scheduled: list[UsageTrendPoint] = Field(default_factory=list)


class CodexAuthTokens(DashboardModel):
    id_token: str = Field(serialization_alias="id_token", validation_alias="id_token")
    access_token: str = Field(serialization_alias="access_token", validation_alias="access_token")
    refresh_token: str = Field(serialization_alias="refresh_token", validation_alias="refresh_token")
    account_id: str | None = Field(
        default=None,
        serialization_alias="account_id",
        validation_alias="account_id",
    )


class CodexAuthJson(DashboardModel):
    auth_mode: str = Field(default="chatgpt", serialization_alias="auth_mode", validation_alias="auth_mode")
    openai_api_key: str | None = Field(
        default=None,
        serialization_alias="OPENAI_API_KEY",
        validation_alias="OPENAI_API_KEY",
    )
    tokens: CodexAuthTokens
    last_refresh: str = Field(serialization_alias="last_refresh", validation_alias="last_refresh")


class AccountAuthExportTokens(DashboardModel):
    id_token: str
    access_token: str
    refresh_token: str
    expires_at_ms: int = Field(ge=0)


class AccountAuthExportResponse(DashboardModel):
    filename: str
    account: AccountOpenCodeAuthExportAccount
    tokens: AccountAuthExportTokens
    codex_auth_json: CodexAuthJson
    opencode_auth_json: OpenCodeAuthJson


class AccountAliasRequest(DashboardModel):
    alias: str | None = Field(default=None, max_length=255)


class AccountAliasResponse(DashboardModel):
    account_id: str
    alias: str | None = None

from __future__ import annotations

from datetime import datetime

from pydantic import Field

from app.modules.shared.schemas import DashboardModel


class LimitRuleCreate(DashboardModel):
    limit_type: str = Field(pattern=r"^(total_tokens|input_tokens|output_tokens|cost_usd|credits)$")
    limit_window: str = Field(pattern=r"^(daily|weekly|monthly|5h|7d)$")
    max_value: int = Field(ge=1)
    model_filter: str | None = None


class LimitRuleResponse(DashboardModel):
    id: int
    limit_type: str
    limit_window: str
    max_value: int
    current_value: int
    model_filter: str | None
    reset_at: datetime


class ApiKeyCreateRequest(DashboardModel):
    name: str = Field(min_length=1, max_length=128)
    allowed_models: list[str] | None = None
    apply_to_codex_model: bool = False
    enforced_model: str | None = Field(default=None, min_length=1)
    enforced_reasoning_effort: str | None = Field(
        default=None, pattern=r"(?i)^(none|minimal|low|medium|high|xhigh|max|ultra)$"
    )
    enforced_service_tier: str | None = Field(default=None, pattern=r"(?i)^(auto|default|priority|flex|fast)$")
    traffic_class: str | None = Field(default=None, pattern=r"(?i)^(foreground|opportunistic)$")
    transport_policy_override: str | None = None
    usage_sections: str | None = None
    weekly_token_limit: int | None = Field(default=None, ge=1)
    expires_at: datetime | None = None
    assigned_account_ids: list[str] | None = None
    assigned_source_ids: list[str] | None = None
    limits: list[LimitRuleCreate] | None = None


class ApiKeyUpdateRequest(DashboardModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    allowed_models: list[str] | None = None
    apply_to_codex_model: bool | None = None
    enforced_model: str | None = Field(default=None, min_length=1)
    enforced_reasoning_effort: str | None = Field(
        default=None, pattern=r"(?i)^(none|minimal|low|medium|high|xhigh|max|ultra)$"
    )
    enforced_service_tier: str | None = Field(default=None, pattern=r"(?i)^(auto|default|priority|flex|fast)$")
    traffic_class: str | None = Field(default=None, pattern=r"(?i)^(foreground|opportunistic)$")
    transport_policy_override: str | None = None
    usage_sections: str | None = None
    weekly_token_limit: int | None = Field(default=None, ge=1)
    expires_at: datetime | None = None
    is_active: bool | None = None
    assigned_account_ids: list[str] | None = None
    assigned_source_ids: list[str] | None = None
    limits: list[LimitRuleCreate] | None = None
    reset_usage: bool | None = None


class ApiKeyUsageSummaryResponse(DashboardModel):
    request_count: int
    total_tokens: int
    cached_input_tokens: int
    total_cost_usd: float


class ApiKeyAccountRoutingRuleSchema(DashboardModel):
    """How this key ranks and gates one account; omitted accounts inherit everything."""

    account_id: str = Field(min_length=1)
    # None inherits the account's own policy.
    routing_policy: str | None = Field(default=None, pattern=r"^(normal|burn_first|preserve)$")
    # False inherits the account's ceilings and pace gates; True replaces all five
    # with the values below, where None switches that gate off for this key.
    override_gates: bool = False
    usage_ceiling_primary_pct: float | None = Field(default=None, gt=0.0, le=100.0)
    usage_ceiling_secondary_pct: float | None = Field(default=None, gt=0.0, le=100.0)
    pace_margin_primary_pct: float | None = Field(default=None, ge=0.0, le=100.0)
    pace_margin_secondary_pct: float | None = Field(default=None, ge=0.0, le=100.0)
    pre_reset_window_minutes: int | None = Field(default=None, ge=0)


class ApiKeyAccountRoutingRulesUpdateRequest(DashboardModel):
    rules: list[ApiKeyAccountRoutingRuleSchema] = Field(default_factory=list)


class ApiKeyResponse(DashboardModel):
    id: str
    name: str
    key_prefix: str
    allowed_models: list[str] | None
    apply_to_codex_model: bool = False
    enforced_model: str | None
    enforced_reasoning_effort: str | None
    enforced_service_tier: str | None
    traffic_class: str
    transport_policy_override: str | None = None
    usage_sections: str = "upstream_limits,account_pool_usage"
    expires_at: datetime | None
    is_active: bool
    account_assignment_scope_enabled: bool = False
    source_assignment_scope_enabled: bool = False
    assigned_account_ids: list[str] = Field(default_factory=list)
    assigned_source_ids: list[str] = Field(default_factory=list)
    created_at: datetime
    last_used_at: datetime | None
    limits: list[LimitRuleResponse] = Field(default_factory=list)
    usage_summary: ApiKeyUsageSummaryResponse | None = None
    pooled_remaining_percent_primary: float | None = None
    pooled_remaining_percent_secondary: float | None = None
    pooled_capacity_credits_primary: float = 0.0
    account_routing_rules: list[ApiKeyAccountRoutingRuleSchema] = Field(default_factory=list)


class ApiKeyCreateResponse(ApiKeyResponse):
    key: str


class ApiKeyTrendPoint(DashboardModel):
    t: datetime
    v: float


class ApiKeyTrendsResponse(DashboardModel):
    key_id: str
    cost: list[ApiKeyTrendPoint] = Field(default_factory=list)
    tokens: list[ApiKeyTrendPoint] = Field(default_factory=list)


class ApiKeyAccountCostResponse(DashboardModel):
    account_id: str | None = None
    email: str | None = None
    cost_usd: float = 0
    is_deleted: bool = False


class ApiKeyUsage7DayResponse(DashboardModel):
    key_id: str
    total_tokens: int = 0
    total_cost_usd: float = 0
    total_requests: int = 0
    cached_input_tokens: int = 0
    account_costs: list[ApiKeyAccountCostResponse] = Field(default_factory=list)

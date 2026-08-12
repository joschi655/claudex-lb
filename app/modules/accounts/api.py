from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, File, Request, Response, UploadFile

from app.core.audit.service import AuditService
from app.core.auth.dependencies import (
    require_dashboard_write_access,
    set_dashboard_error_format,
    validate_dashboard_session,
)
from app.core.auth.refresh import RefreshError
from app.core.clients.usage import UsageFetchError
from app.core.exceptions import (
    DashboardBadRequestError,
    DashboardConflictError,
    DashboardNotFoundError,
    DashboardUpstreamError,
)
from app.core.providers import PROVIDER_ANTHROPIC, PROVIDER_OPENAI
from app.core.upstream_proxy import UpstreamProxyRouteError
from app.dependencies import (
    AccountsContext,
    get_accounts_context,
    get_anthropic_proxy_service_for_app,
    get_proxy_service_for_app,
)
from app.modules.accounts.mappers import normalize_account_quota_kind, normalize_account_routing_policy
from app.modules.accounts.repository import AccountIdentityConflictError, PaceGateUpdate
from app.modules.accounts.schemas import (
    AccountAliasRequest,
    AccountAliasResponse,
    AccountAuthExportResponse,
    AccountDeleteResponse,
    AccountExportResponse,
    AccountImportResponse,
    AccountLimitWarmupTriggerResponse,
    AccountLimitWarmupUpdateRequest,
    AccountLimitWarmupUpdateResponse,
    AccountOpenCodeAuthExportResponse,
    AccountPaceGatesUpdateRequest,
    AccountPaceGatesUpdateResponse,
    AccountPauseResponse,
    AccountPinUpdateRequest,
    AccountPinUpdateResponse,
    AccountProbeRequest,
    AccountProbeResponse,
    AccountQuotaKindUpdateRequest,
    AccountQuotaKindUpdateResponse,
    AccountReactivateResponse,
    AccountRoutingPolicyUpdateRequest,
    AccountRoutingPolicyUpdateResponse,
    AccountsResponse,
    AccountTrendsResponse,
    AccountUpdateRequest,
    AccountUpdateResponse,
    AccountUsageResetConsumeRequest,
    AccountUsageResetConsumeResponse,
    AccountUsageResetCreditsResponse,
    NextAccountEntry,
    NextAccountsResponse,
)
from app.modules.accounts.service import (
    AccountNotProbableError,
    AccountNotWarmableError,
    AccountStateTransitionError,
    AccountUsageResetConsumeUnavailableError,
    AccountUsageResetCreditsUnavailableError,
    InvalidAuthJsonError,
    ProviderActionUnsupportedError,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/accounts",
    tags=["dashboard"],
    dependencies=[Depends(validate_dashboard_session), Depends(set_dashboard_error_format)],
)


@router.get("", response_model=AccountsResponse)
async def list_accounts(
    context: AccountsContext = Depends(get_accounts_context),
) -> AccountsResponse:
    accounts = await context.service.list_accounts()
    return AccountsResponse(accounts=accounts)


@router.get("/next-up", response_model=NextAccountsResponse)
async def get_next_accounts(request: Request) -> NextAccountsResponse:
    """Which account each provider would route a new request to.

    Asked of the running proxy services rather than recomputed here: the answer
    turns on runtime state — leases, cooldowns, health tiers — that only the
    instances actually serving traffic hold. Each provider is answered
    independently, and one provider failing to answer does not hide the other.

    Declared above ``/{account_id}/trends`` so the literal path is not captured
    as an account id.
    """
    entries: list[NextAccountEntry] = []
    for provider, resolve in (
        (PROVIDER_OPENAI, get_proxy_service_for_app(request.app).preview_next_account),
        (PROVIDER_ANTHROPIC, get_anthropic_proxy_service_for_app(request.app).preview_next_account),
    ):
        try:
            preview = await resolve()
        except Exception:
            logger.warning("Next-account preview failed provider=%s", provider, exc_info=True)
            entries.append(NextAccountEntry(provider=provider, account_id=None, error_message="Preview unavailable"))
            continue
        entries.append(
            NextAccountEntry(
                provider=provider,
                account_id=preview.account_id,
                certain=preview.certain,
                error_message=preview.error_message,
            )
        )
    return NextAccountsResponse(next_up=entries)


@router.get("/{account_id}/trends", response_model=AccountTrendsResponse)
async def get_account_trends(
    account_id: str,
    context: AccountsContext = Depends(get_accounts_context),
) -> AccountTrendsResponse:
    result = await context.service.get_account_trends(account_id)
    if not result:
        raise DashboardNotFoundError("Account not found", code="account_not_found")
    return result


@router.get("/{account_id}/usage-reset-credits", response_model=AccountUsageResetCreditsResponse)
async def get_account_usage_reset_credits(
    account_id: str,
    context: AccountsContext = Depends(get_accounts_context),
) -> AccountUsageResetCreditsResponse:
    try:
        result = await context.service.get_usage_reset_credits(account_id)
    except AccountUsageResetCreditsUnavailableError as exc:
        raise DashboardConflictError(str(exc), code="account_usage_reset_credits_unavailable") from exc
    except UpstreamProxyRouteError as exc:
        raise DashboardUpstreamError(
            f"Unable to resolve upstream proxy route for usage reset credits: {exc.reason}",
            code="upstream_proxy_unavailable",
        ) from exc
    except UsageFetchError as exc:
        raise DashboardUpstreamError(
            f"Usage reset credits fetch failed: {exc.message}",
            code="usage_reset_credits_fetch_failed",
        ) from exc
    if not result:
        raise DashboardNotFoundError("Account not found", code="account_not_found")
    return result


@router.post("/{account_id}/usage-reset-credits/consume", response_model=AccountUsageResetConsumeResponse)
async def consume_account_usage_reset_credit(
    request: Request,
    account_id: str,
    payload: AccountUsageResetConsumeRequest | None = None,
    _write_access=Depends(require_dashboard_write_access),
    context: AccountsContext = Depends(get_accounts_context),
) -> AccountUsageResetConsumeResponse:
    try:
        result = await context.service.consume_usage_reset_credit(
            account_id,
            redeem_request_id=payload.redeem_request_id if payload is not None else None,
        )
    except AccountUsageResetConsumeUnavailableError as exc:
        raise DashboardConflictError(str(exc), code="account_usage_reset_consume_unavailable") from exc
    except UpstreamProxyRouteError as exc:
        raise DashboardUpstreamError(
            f"Unable to resolve upstream proxy route for usage reset: {exc.reason}",
            code="upstream_proxy_unavailable",
        ) from exc
    except UsageFetchError as exc:
        raise DashboardUpstreamError(
            f"Usage reset consume failed: {exc.message}",
            code="usage_reset_consume_failed",
        ) from exc
    if result is None:
        raise DashboardNotFoundError("Account not found", code="account_not_found")
    AuditService.log_async(
        "account_usage_reset_consumed",
        actor_ip=request.client.host if request.client else None,
        details={
            "account_id": result.account_id,
            "code": result.code,
            "windows_reset": result.windows_reset,
            "usage_written": result.usage_written,
        },
    )
    return result


@router.post("/{account_id}/export", response_model=AccountExportResponse, deprecated=True)
async def export_account(
    request: Request,
    response: Response,
    account_id: str,
    _write_access=Depends(require_dashboard_write_access),
    context: AccountsContext = Depends(get_accounts_context),
) -> AccountExportResponse:
    try:
        result = await context.service.export_account(account_id)
    except ProviderActionUnsupportedError as exc:
        raise DashboardBadRequestError(str(exc), code="provider_action_unsupported") from exc
    if not result:
        raise DashboardNotFoundError("Account not found", code="account_not_found")
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, private"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    AuditService.log_async(
        "account_exported",
        actor_ip=request.client.host if request.client else None,
        details={"account_id": result.account_id},
    )
    return result


@router.post("/{account_id}/export/auth", response_model=AccountAuthExportResponse)
async def export_account_auth(
    request: Request,
    response: Response,
    account_id: str,
    _write_access=Depends(require_dashboard_write_access),
    context: AccountsContext = Depends(get_accounts_context),
) -> AccountAuthExportResponse:
    try:
        result = await context.service.export_auth(account_id)
    except ProviderActionUnsupportedError as exc:
        raise DashboardBadRequestError(str(exc), code="provider_action_unsupported") from exc
    if not result:
        raise DashboardNotFoundError("Account not found", code="account_not_found")
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, private"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    AuditService.log_async(
        "account_auth_exported",
        actor_ip=request.client.host if request.client else None,
        details={"account_id": account_id},
    )
    return result


@router.post("/{account_id}/export/opencode-auth", response_model=AccountOpenCodeAuthExportResponse, deprecated=True)
async def export_account_opencode_auth(
    request: Request,
    response: Response,
    account_id: str,
    _write_access=Depends(require_dashboard_write_access),
    context: AccountsContext = Depends(get_accounts_context),
) -> AccountOpenCodeAuthExportResponse:
    try:
        result = await context.service.export_opencode_auth(account_id)
    except ProviderActionUnsupportedError as exc:
        raise DashboardBadRequestError(str(exc), code="provider_action_unsupported") from exc
    if not result:
        raise DashboardNotFoundError("Account not found", code="account_not_found")
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, private"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    AuditService.log_async(
        "account_auth_exported",
        actor_ip=request.client.host if request.client else None,
        details={"account_id": account_id},
    )
    return result


@router.post("/import", response_model=AccountImportResponse)
async def import_account(
    request: Request,
    auth_json: UploadFile = File(...),
    _write_access=Depends(require_dashboard_write_access),
    context: AccountsContext = Depends(get_accounts_context),
) -> AccountImportResponse:
    raw = await auth_json.read()
    try:
        response = await context.service.import_account(raw)
        AuditService.log_async(
            "account_created",
            actor_ip=request.client.host if request.client else None,
            details={"account_id": response.account_id},
        )
        return response
    except InvalidAuthJsonError as exc:
        raise DashboardBadRequestError("Invalid auth.json payload", code="invalid_auth_json") from exc
    except AccountIdentityConflictError as exc:
        raise DashboardConflictError(str(exc), code="duplicate_identity_conflict") from exc


@router.post("/{account_id}/reactivate", response_model=AccountReactivateResponse)
async def reactivate_account(
    account_id: str,
    _write_access=Depends(require_dashboard_write_access),
    context: AccountsContext = Depends(get_accounts_context),
) -> AccountReactivateResponse:
    try:
        success = await context.service.reactivate_account(account_id)
    except AccountStateTransitionError as exc:
        raise DashboardConflictError(str(exc), code="account_state_transition_invalid") from exc
    if not success:
        raise DashboardNotFoundError("Account not found", code="account_not_found")
    return AccountReactivateResponse(status="reactivated")


@router.patch("/{account_id}", response_model=AccountUpdateResponse)
async def update_account(
    account_id: str,
    payload: AccountUpdateRequest,
    request: Request,
    _write_access=Depends(require_dashboard_write_access),
    context: AccountsContext = Depends(get_accounts_context),
) -> AccountUpdateResponse:
    changed_fields = [field for field, value in payload.model_dump(exclude_unset=True).items() if value is not None]
    if not changed_fields:
        raise DashboardBadRequestError("No supported account fields to update", code="empty_account_update")
    success = await context.service.update_account(
        account_id,
        security_work_authorized=payload.security_work_authorized,
    )
    if not success:
        raise DashboardNotFoundError("Account not found", code="account_not_found")
    AuditService.log_async(
        "account_updated",
        actor_ip=request.client.host if request.client else None,
        details={
            "account_id": account_id,
            "changed_fields": changed_fields,
        },
    )
    return AccountUpdateResponse(status="updated")


@router.post("/{account_id}/probe", response_model=AccountProbeResponse)
async def probe_account(
    request: Request,
    account_id: str,
    body: AccountProbeRequest | None = None,
    _write_access=Depends(require_dashboard_write_access),
    context: AccountsContext = Depends(get_accounts_context),
) -> AccountProbeResponse:
    requested_model = body.model if body is not None else None
    try:
        result = await context.service.probe_account(account_id, model=requested_model)
    except ProviderActionUnsupportedError as exc:
        raise DashboardBadRequestError(str(exc), code="provider_action_unsupported") from exc
    except AccountNotProbableError as exc:
        raise DashboardConflictError(str(exc), code="account_not_probable") from exc
    except RefreshError as exc:
        raise DashboardConflictError(
            f"Probe could not refresh account credentials: {exc.message}",
            code="account_probe_refresh_failed",
        ) from exc
    if result is None:
        raise DashboardNotFoundError("Account not found", code="account_not_found")
    AuditService.log_async(
        "account_probed",
        actor_ip=request.client.host if request.client else None,
        details={
            "account_id": result.account_id,
            "probe_status_code": result.probe_status_code,
            "model": requested_model,
        },
    )
    return result


@router.post("/{account_id}/pause", response_model=AccountPauseResponse)
async def pause_account(
    account_id: str,
    _write_access=Depends(require_dashboard_write_access),
    context: AccountsContext = Depends(get_accounts_context),
) -> AccountPauseResponse:
    try:
        success = await context.service.pause_account(account_id)
    except AccountStateTransitionError as exc:
        raise DashboardConflictError(str(exc), code="account_state_transition_invalid") from exc
    if not success:
        raise DashboardNotFoundError("Account not found", code="account_not_found")
    return AccountPauseResponse(status="paused")


@router.put("/{account_id}/alias", response_model=AccountAliasResponse)
async def set_account_alias(
    account_id: str,
    payload: AccountAliasRequest,
    _write_access=Depends(require_dashboard_write_access),
    context: AccountsContext = Depends(get_accounts_context),
) -> AccountAliasResponse:
    success = await context.service.set_account_alias(account_id, payload.alias)
    if not success:
        raise DashboardNotFoundError("Account not found", code="account_not_found")
    normalized = payload.alias.strip() if isinstance(payload.alias, str) else None
    if normalized == "":
        normalized = None
    return AccountAliasResponse(account_id=account_id, alias=normalized)


@router.put("/{account_id}/limit-warmup", response_model=AccountLimitWarmupUpdateResponse)
async def update_account_limit_warmup(
    account_id: str,
    payload: AccountLimitWarmupUpdateRequest,
    _write_access=Depends(require_dashboard_write_access),
    context: AccountsContext = Depends(get_accounts_context),
) -> AccountLimitWarmupUpdateResponse:
    success = await context.service.set_limit_warmup_enabled(account_id, payload.enabled)
    if not success:
        raise DashboardNotFoundError("Account not found", code="account_not_found")
    return AccountLimitWarmupUpdateResponse(
        status="enabled" if payload.enabled else "disabled",
        enabled=payload.enabled,
    )


@router.post("/{account_id}/limit-warmup/trigger", response_model=AccountLimitWarmupTriggerResponse)
async def trigger_account_limit_warmup(
    account_id: str,
    _write_access=Depends(require_dashboard_write_access),
    context: AccountsContext = Depends(get_accounts_context),
) -> AccountLimitWarmupTriggerResponse:
    try:
        result = await context.service.trigger_limit_warmup(account_id)
    except ProviderActionUnsupportedError as exc:
        raise DashboardBadRequestError(str(exc), code="account_provider_unsupported") from exc
    except AccountNotWarmableError as exc:
        raise DashboardConflictError(str(exc), code="account_not_warmable") from exc
    if result is None:
        raise DashboardNotFoundError("Account not found", code="account_not_found")
    return AccountLimitWarmupTriggerResponse(
        account_id=account_id,
        sent=result.sent,
        success=result.success,
        model=result.model,
        latency_ms=result.latency_ms,
        error_code=result.error_code,
        error_message=result.error_message,
    )


@router.put("/{account_id}/routing-policy", response_model=AccountRoutingPolicyUpdateResponse)
async def update_account_routing_policy(
    account_id: str,
    payload: AccountRoutingPolicyUpdateRequest,
    _write_access=Depends(require_dashboard_write_access),
    context: AccountsContext = Depends(get_accounts_context),
) -> AccountRoutingPolicyUpdateResponse:
    success = await context.service.set_routing_policy(account_id, payload.routing_policy)
    if not success:
        raise DashboardNotFoundError("Account not found", code="account_not_found")
    return AccountRoutingPolicyUpdateResponse(account_id=account_id, routing_policy=payload.routing_policy)


@router.put("/{account_id}/pin", response_model=AccountPinUpdateResponse)
async def update_account_pin(
    account_id: str,
    payload: AccountPinUpdateRequest,
    _write_access=Depends(require_dashboard_write_access),
    context: AccountsContext = Depends(get_accounts_context),
) -> AccountPinUpdateResponse:
    account = await context.service.set_pinned(account_id, payload.pinned)
    if account is None:
        raise DashboardNotFoundError("Account not found", code="account_not_found")
    return AccountPinUpdateResponse(
        account_id=account_id,
        pinned=bool(account.pinned),
        # Normalized like the account summary's copy: a row still carrying the
        # legacy "pinned" value would otherwise reach a client that no longer
        # accepts it as a policy.
        routing_policy=normalize_account_routing_policy(account.routing_policy),
    )


@router.put("/{account_id}/quota-kind", response_model=AccountQuotaKindUpdateResponse)
async def update_account_quota_kind(
    account_id: str,
    payload: AccountQuotaKindUpdateRequest,
    _write_access=Depends(require_dashboard_write_access),
    context: AccountsContext = Depends(get_accounts_context),
) -> AccountQuotaKindUpdateResponse:
    account = await context.service.set_quota_kind(account_id, payload.quota_kind)
    if account is None:
        raise DashboardNotFoundError("Account not found", code="account_not_found")
    return AccountQuotaKindUpdateResponse(
        account_id=account_id,
        quota_kind=normalize_account_quota_kind(account.quota_kind),
    )


@router.put("/{account_id}/pace-gates", response_model=AccountPaceGatesUpdateResponse)
async def update_account_pace_gates(
    account_id: str,
    payload: AccountPaceGatesUpdateRequest,
    _write_access=Depends(require_dashboard_write_access),
    context: AccountsContext = Depends(get_accounts_context),
) -> AccountPaceGatesUpdateResponse:
    # An omitted field must leave the stored gate alone while an explicit null
    # clears it, so the supplied set comes from the payload rather than from
    # testing values against None.
    supplied = payload.model_fields_set
    account = await context.service.set_pace_gates(
        account_id,
        PaceGateUpdate(
            pace_margin_primary_pct=(
                (payload.pace_margin_primary_pct,) if "pace_margin_primary_pct" in supplied else None
            ),
            pace_margin_secondary_pct=(
                (payload.pace_margin_secondary_pct,) if "pace_margin_secondary_pct" in supplied else None
            ),
            pre_reset_window_minutes=(
                (payload.pre_reset_window_minutes,) if "pre_reset_window_minutes" in supplied else None
            ),
        ),
    )
    if account is None:
        raise DashboardNotFoundError("Account not found", code="account_not_found")
    return AccountPaceGatesUpdateResponse(
        account_id=account_id,
        pace_margin_primary_pct=account.pace_margin_primary_pct,
        pace_margin_secondary_pct=account.pace_margin_secondary_pct,
        pre_reset_window_minutes=account.pre_reset_window_minutes,
    )


@router.delete("/{account_id}", response_model=AccountDeleteResponse)
async def delete_account(
    request: Request,
    account_id: str,
    delete_history: bool = False,
    _write_access=Depends(require_dashboard_write_access),
    context: AccountsContext = Depends(get_accounts_context),
) -> AccountDeleteResponse:
    success = await context.service.delete_account(account_id, delete_history=delete_history)
    if not success:
        raise DashboardNotFoundError("Account not found", code="account_not_found")
    AuditService.log_async(
        "account_deleted",
        actor_ip=request.client.host if request.client else None,
        details={"account_id": account_id, "delete_history": delete_history},
    )
    return AccountDeleteResponse(status="deleted")

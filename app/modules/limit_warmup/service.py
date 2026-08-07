from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections.abc import Awaitable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import AsyncContextManager, Callable, Protocol

from app.core import usage as usage_core
from app.core.anthropic.warmup import ANTHROPIC_WARMUP_MODEL, send_warmup
from app.core.auth.refresh import RefreshError
from app.core.clients.proxy import UpstreamProxyRouteTrace, override_stream_timeouts, stream_responses
from app.core.crypto import TokenEncryptor
from app.core.openai.model_registry import get_model_registry
from app.core.openai.models import OpenAIError, ResponseUsage
from app.core.openai.parsing import parse_sse_event
from app.core.openai.requests import ResponsesRequest
from app.core.plan_types import account_plan_matches_allowed
from app.core.providers import is_anthropic_provider
from app.core.upstream_proxy import ResolvedUpstreamRoute, UpstreamProxyRouteError, resolve_upstream_route
from app.core.usage.pricing import get_pricing_for_model
from app.core.utils.time import naive_utc_to_epoch, utcnow
from app.db.models import Account, AccountLimitWarmup, AccountStatus, DashboardSettings, UsageHistory
from app.modules.accounts.auth_manager import AuthManager
from app.modules.accounts.repository import AccountsRepository
from app.modules.usage.mappers import usage_history_to_window_row

logger = logging.getLogger(__name__)

LIMIT_WARMUP_SOURCE = "limit_warmup"
LIMIT_WARMUP_REQUEST_KIND = "warmup"
LIMIT_WARMUP_HEADER = "x-codex-lb-limit-warmup"
_DEFAULT_WARMUP_INSTRUCTIONS = "Reply with OK only."
_TERMINAL_ERROR_EVENTS = {"response.failed", "response.incomplete", "error"}
_QUOTA_ERROR_CODES = {"insufficient_quota", "quota_exceeded", "rate_limit_exceeded", "usage_limit_reached"}
_MAX_CONCURRENT_WARMUP_SENDS = 4
_ROLLING_WINDOW_SECONDS = 300 * 60
_SHORT_WINDOW_MAX_MINUTES = 24 * 60
_STAGGER_SLOT_GRACE_SECONDS = 60
_IDLE_PRIMARY_WINDOW = "primary_idle"
_MANUAL_PRIMARY_WINDOW = "primary_manual"
# Claude statuses a warm-up may target. Paused is included on purpose; see
# ``_account_is_safe_candidate``.
_WARMABLE_ANTHROPIC_STATUSES = (AccountStatus.ACTIVE, AccountStatus.PAUSED)
# Minimum reset_at forward jump (in seconds) to confirm a real quota window reset.
# Upstream timestamp jitter of ~1 second must not trigger a warm-up.
_RESET_CONFIRMED_MIN_JUMP_SECONDS = 60
# Persist the upstream value, but treat nearby values as the same staggered-idle
# cycle. This avoids every boundary inherent in stateless timestamp bucketing.
_IDLE_RESET_AT_JITTER_TOLERANCE_SECONDS = 5
# Stands in for the reset timestamp of a window that is not running, so an
# attempt against that state has a stable dedupe key.
_NO_WINDOW_RESET_AT = 0


@dataclass(frozen=True, slots=True)
class LimitWarmupSendResult:
    request_id: str
    success: bool
    latency_ms: int
    usage: ResponseUsage | None = None
    error_code: str | None = None
    error_message: str | None = None
    upstream_proxy_route_mode: str | None = None
    upstream_proxy_pool_id: str | None = None
    upstream_proxy_endpoint_id: str | None = None
    upstream_proxy_fallback_used: bool | None = None
    upstream_proxy_fail_closed_reason: str | None = None
    # Anthropic only: the warmed account's window state travels back in response
    # headers, so the caller can ingest the window this ping just opened. The
    # ChatGPT path leaves it None -- its usage arrives through the poller.
    usage_headers: Mapping[str, str] | None = None


@dataclass(frozen=True, slots=True)
class LimitWarmupSendOutcome:
    attempt: AccountLimitWarmup
    account: Account
    model: str
    result: LimitWarmupSendResult | None
    error_message: str | None = None


class LimitWarmupSender(Protocol):
    async def send(self, account: Account, *, model: str, prompt: str) -> LimitWarmupSendResult: ...


# Writes back the window a Claude warmup opened, from the response's rate-limit
# headers. Optional because the ChatGPT path reports usage through the poller.
AnthropicWindowIngestor = Callable[[str, Mapping[str, str]], Awaitable[None]]


class LimitWarmupAttemptsRepository(Protocol):
    async def latest_by_account(self, account_ids: list[str]) -> dict[str, AccountLimitWarmup]: ...

    async def try_create_attempt(
        self,
        *,
        account_id: str,
        window: str,
        reset_at: int,
        model: str,
        attempted_at,
        status: str = "pending",
        reset_at_tolerance_seconds: int = 0,
    ) -> AccountLimitWarmup | None: ...

    async def complete_attempt(
        self,
        attempt_id: int,
        *,
        status: str,
        completed_at,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> AccountLimitWarmup | None: ...


class LimitWarmupRequestLogRepository(Protocol):
    async def add_log(
        self,
        account_id: str | None,
        request_id: str,
        model: str,
        input_tokens: int | None,
        output_tokens: int | None,
        latency_ms: int | None,
        status: str,
        error_code: str | None,
        latency_first_token_ms: int | None = None,
        error_message: str | None = None,
        requested_at: datetime | None = None,
        cached_input_tokens: int | None = None,
        reasoning_tokens: int | None = None,
        reasoning_effort: str | None = None,
        service_tier: str | None = None,
        requested_service_tier: str | None = None,
        actual_service_tier: str | None = None,
        transport: str | None = None,
        upstream_transport: str | None = None,
        api_key_id: str | None = None,
        session_id: str | None = None,
        plan_type: str | None = None,
        source: str | None = None,
        useragent: str | None = None,
        useragent_group: str | None = None,
        client_ip: str | None = None,
        failure_phase: str | None = None,
        failure_detail: str | None = None,
        failure_exception_type: str | None = None,
        upstream_status_code: int | None = None,
        upstream_error_code: str | None = None,
        bridge_stage: str | None = None,
        request_kind: str = "normal",
        upstream_proxy_route_mode: str | None = None,
        upstream_proxy_pool_id: str | None = None,
        upstream_proxy_endpoint_id: str | None = None,
        upstream_proxy_fallback_used: bool | None = None,
        upstream_proxy_fail_closed_reason: str | None = None,
    ) -> object: ...


class StreamingLimitWarmupSender:
    def __init__(
        self,
        accounts_repo: AccountsRepository,
        *,
        accounts_repo_factory: Callable[[], AsyncContextManager[AccountsRepository]] | None = None,
    ) -> None:
        self._accounts_repo = accounts_repo
        self._accounts_repo_factory = accounts_repo_factory
        self._auth_manager = AuthManager(accounts_repo)
        self._encryptor = TokenEncryptor()
        self._auth_lock = asyncio.Lock()

    async def send(self, account: Account, *, model: str, prompt: str) -> LimitWarmupSendResult:
        request_id = f"limit-warmup-{uuid.uuid4().hex}"
        started = time.monotonic()
        try:
            async with self._auth_lock:
                fresh_account = await self._ensure_fresh(account)
                access_token = self._encryptor.decrypt(fresh_account.access_token_encrypted)
                chatgpt_account_id = fresh_account.chatgpt_account_id
        except RefreshError as exc:
            return LimitWarmupSendResult(
                request_id=request_id,
                success=False,
                latency_ms=_elapsed_ms(started),
                error_code=f"auth_refresh_{exc.code}",
                error_message=exc.message,
            )

        if fresh_account.status != AccountStatus.ACTIVE:
            return LimitWarmupSendResult(
                request_id=request_id,
                success=False,
                latency_ms=_elapsed_ms(started),
                error_code="account_not_active",
                error_message=f"Account status is {fresh_account.status.value}",
            )
        try:
            route = await self._resolve_upstream_route(fresh_account)
        except UpstreamProxyRouteError as exc:
            return LimitWarmupSendResult(
                request_id=request_id,
                success=False,
                latency_ms=_elapsed_ms(started),
                error_code="upstream_proxy_unavailable",
                error_message=f"Upstream proxy route unavailable: {exc.reason}",
                upstream_proxy_fail_closed_reason=exc.reason,
            )

        payload = ResponsesRequest.model_validate(
            {
                "model": model,
                "instructions": _DEFAULT_WARMUP_INSTRUCTIONS,
                "input": prompt,
                "tools": [],
                "parallel_tool_calls": False,
                "stream": True,
                "store": False,
                "max_output_tokens": 4,
            }
        )
        headers = {
            "x-request-id": request_id,
            LIMIT_WARMUP_HEADER: "1",
            "user-agent": "codex-lb-limit-warmup",
        }
        usage: ResponseUsage | None = None
        route_trace = UpstreamProxyRouteTrace()
        with override_stream_timeouts(
            connect_timeout_seconds=5.0,
            idle_timeout_seconds=10.0,
            total_timeout_seconds=30.0,
        ):
            async for event_block in stream_responses(
                payload,
                headers,
                access_token,
                chatgpt_account_id,
                upstream_stream_transport_override="http",
                route=route,
                route_trace=route_trace,
                allow_direct_egress=route is None,
                codex_lb_account_id=fresh_account.id,
            ):
                event = parse_sse_event(event_block)
                if event is None:
                    continue
                if event.response is not None and event.response.usage is not None:
                    usage = event.response.usage
                if event.type == "response.completed":
                    return LimitWarmupSendResult(
                        request_id=request_id,
                        success=True,
                        latency_ms=_elapsed_ms(started),
                        usage=usage,
                        upstream_proxy_route_mode=route_trace.mode,
                        upstream_proxy_pool_id=route_trace.pool_id,
                        upstream_proxy_endpoint_id=route_trace.endpoint_id,
                        upstream_proxy_fallback_used=route_trace.fallback_used,
                    )
                if event.type in _TERMINAL_ERROR_EVENTS:
                    error = _event_error(event.error, event.response.error if event.response is not None else None)
                    return LimitWarmupSendResult(
                        request_id=request_id,
                        success=False,
                        latency_ms=_elapsed_ms(started),
                        usage=usage,
                        error_code=error.code or event.type,
                        error_message=error.message or event.type,
                        upstream_proxy_route_mode=route_trace.mode,
                        upstream_proxy_pool_id=route_trace.pool_id,
                        upstream_proxy_endpoint_id=route_trace.endpoint_id,
                        upstream_proxy_fallback_used=route_trace.fallback_used,
                    )

        return LimitWarmupSendResult(
            request_id=request_id,
            success=False,
            latency_ms=_elapsed_ms(started),
            usage=usage,
            error_code="stream_incomplete",
            error_message="Warm-up stream ended without a terminal event",
            upstream_proxy_route_mode=route_trace.mode,
            upstream_proxy_pool_id=route_trace.pool_id,
            upstream_proxy_endpoint_id=route_trace.endpoint_id,
            upstream_proxy_fallback_used=route_trace.fallback_used,
        )

    async def _ensure_fresh(self, account: Account) -> Account:
        if self._accounts_repo_factory is None:
            return await self._auth_manager.ensure_fresh(account)
        async with self._accounts_repo_factory() as accounts_repo:
            return await AuthManager(
                accounts_repo,
                refresh_repo_factory=self._accounts_repo_factory,
            ).ensure_fresh(account)

    async def _resolve_upstream_route(self, account: Account) -> ResolvedUpstreamRoute | None:
        if self._accounts_repo_factory is not None:
            async with self._accounts_repo_factory() as accounts_repo:
                return await resolve_upstream_route(
                    accounts_repo.session,
                    account_id=account.id,
                    operation="limit_warmup",
                    scope="account",
                    encryptor=self._encryptor,
                )
        return await resolve_upstream_route(
            self._accounts_repo.session,
            account_id=account.id,
            operation="limit_warmup",
            scope="account",
            encryptor=self._encryptor,
        )


class AnthropicLimitWarmupSender:
    """Open a Claude five-hour window with a one-token Messages request.

    Deliberately narrower than the ChatGPT sender: no streaming, no upstream
    proxy route, no plan gating. A warmup here is one short POST whose only job
    is to land, and whose response headers describe the window it just opened.
    """

    def __init__(
        self,
        accounts_repo: AccountsRepository,
        *,
        accounts_repo_factory: Callable[[], AsyncContextManager[AccountsRepository]] | None = None,
    ) -> None:
        self._accounts_repo = accounts_repo
        self._accounts_repo_factory = accounts_repo_factory
        self._auth_manager = AuthManager(accounts_repo)
        self._encryptor = TokenEncryptor()
        self._auth_lock = asyncio.Lock()

    async def send(self, account: Account, *, model: str, prompt: str) -> LimitWarmupSendResult:
        request_id = f"limit-warmup-{uuid.uuid4().hex}"
        started = time.monotonic()
        try:
            async with self._auth_lock:
                fresh_account = await self._ensure_fresh(account)
                credential = self._encryptor.decrypt(fresh_account.access_token_encrypted)
        except RefreshError as exc:
            return LimitWarmupSendResult(
                request_id=request_id,
                success=False,
                latency_ms=_elapsed_ms(started),
                error_code=f"auth_refresh_{exc.code}",
                error_message=exc.message,
            )

        if fresh_account.status not in _WARMABLE_ANTHROPIC_STATUSES:
            return LimitWarmupSendResult(
                request_id=request_id,
                success=False,
                latency_ms=_elapsed_ms(started),
                error_code="account_not_active",
                error_message=f"Account status is {fresh_account.status.value}",
            )

        result = await send_warmup(credential, model=model, prompt=prompt)
        return LimitWarmupSendResult(
            request_id=request_id,
            success=result.success,
            latency_ms=result.latency_ms,
            usage=_anthropic_usage(result.input_tokens, result.output_tokens),
            error_code=result.error_code or (None if result.success else f"http_{result.status_code}"),
            error_message=result.error_message,
            usage_headers=result.headers or None,
        )

    async def _ensure_fresh(self, account: Account) -> Account:
        if self._accounts_repo_factory is None:
            return await self._auth_manager.ensure_fresh(account)
        async with self._accounts_repo_factory() as accounts_repo:
            return await AuthManager(
                accounts_repo,
                refresh_repo_factory=self._accounts_repo_factory,
            ).ensure_fresh(account)


def _anthropic_usage(input_tokens: int | None, output_tokens: int | None) -> ResponseUsage | None:
    if input_tokens is None and output_tokens is None:
        return None
    total = (input_tokens or 0) + (output_tokens or 0)
    return ResponseUsage(input_tokens=input_tokens, output_tokens=output_tokens, total_tokens=total)


class ProviderLimitWarmupSender:
    """Route a warmup to the sender that speaks the account's protocol.

    Selection is on the account's own provider field, so a Claude credential can
    never reach the Responses API and vice versa.
    """

    def __init__(self, openai_sender: LimitWarmupSender, anthropic_sender: LimitWarmupSender) -> None:
        self._openai = openai_sender
        self._anthropic = anthropic_sender

    async def send(self, account: Account, *, model: str, prompt: str) -> LimitWarmupSendResult:
        if is_anthropic_provider(account.provider or ""):
            return await self._anthropic.send(account, model=ANTHROPIC_WARMUP_MODEL, prompt=prompt)
        return await self._openai.send(account, model=model, prompt=prompt)


def build_provider_warmup_sender(
    accounts_repo: AccountsRepository,
    *,
    accounts_repo_factory: Callable[[], AsyncContextManager[AccountsRepository]] | None = None,
) -> ProviderLimitWarmupSender:
    return ProviderLimitWarmupSender(
        StreamingLimitWarmupSender(accounts_repo, accounts_repo_factory=accounts_repo_factory),
        AnthropicLimitWarmupSender(accounts_repo, accounts_repo_factory=accounts_repo_factory),
    )


class LimitWarmupService:
    def __init__(
        self,
        warmup_repo: LimitWarmupAttemptsRepository,
        request_logs_repo: LimitWarmupRequestLogRepository,
        *,
        sender: LimitWarmupSender | None = None,
        window_ingestor: AnthropicWindowIngestor | None = None,
    ) -> None:
        self._warmup_repo = warmup_repo
        self._request_logs_repo = request_logs_repo
        self._sender = sender
        self._window_ingestor = window_ingestor

    async def run_after_usage_refresh(
        self,
        *,
        accounts: list[Account],
        settings: DashboardSettings,
        before_primary: dict[str, UsageHistory],
        before_secondary: dict[str, UsageHistory],
        after_primary: dict[str, UsageHistory],
        after_secondary: dict[str, UsageHistory],
        refresh_started_at: datetime | None = None,
        usage_refresh_interval_seconds: int = _STAGGER_SLOT_GRACE_SECONDS,
    ) -> None:
        if not settings.limit_warmup_enabled:
            return
        selected_windows = _selected_windows(settings.limit_warmup_windows)
        if not selected_windows:
            return

        account_ids = [account.id for account in accounts]
        latest_attempts = await self._warmup_repo.latest_by_account(account_ids)
        sender = self._sender
        if sender is None:
            raise RuntimeError("LimitWarmupService requires a sender")
        send_tasks: dict[asyncio.Task[LimitWarmupSendOutcome], AccountLimitWarmup] = {}
        send_semaphore = asyncio.Semaphore(_MAX_CONCURRENT_WARMUP_SENDS)
        staggered_accounts = [
            account for account in accounts if _account_is_safe_candidate(account) and account.limit_warmup_enabled
        ]
        now = utcnow()

        for account in accounts:
            if not _account_is_safe_candidate(account):
                continue
            if not account.limit_warmup_enabled:
                continue
            latest_attempt = latest_attempts.get(account.id)
            if _in_cooldown(
                latest_attempt,
                cooldown_seconds=settings.limit_warmup_cooldown_seconds,
            ):
                continue

            windows_to_evaluate = list(selected_windows)
            if settings.limit_warmup_staggered_idle_enabled and "primary" not in windows_to_evaluate:
                windows_to_evaluate.append("primary")
            for window in windows_to_evaluate:
                candidate = None
                if window in selected_windows:
                    candidate = _build_candidate(
                        account=account,
                        window=window,
                        before_primary=before_primary,
                        before_secondary=before_secondary,
                        after_primary=after_primary,
                        after_secondary=after_secondary,
                        exhausted_threshold_percent=settings.limit_warmup_exhausted_threshold_percent,
                        min_available_percent=settings.limit_warmup_min_available_percent,
                    )
                if candidate is None and settings.limit_warmup_staggered_idle_enabled and window == "primary":
                    candidate = _build_staggered_idle_candidate(
                        account=account,
                        accounts=staggered_accounts,
                        now=now,
                        after_primary=after_primary,
                        refresh_started_at=refresh_started_at,
                        usage_refresh_interval_seconds=usage_refresh_interval_seconds,
                        idle_threshold_percent=settings.limit_warmup_idle_threshold_percent,
                    )
                if candidate is None:
                    continue

                model = self._resolve_model(settings.limit_warmup_model, account)
                if model is None:
                    skipped = await self._warmup_repo.try_create_attempt(
                        account_id=account.id,
                        window=candidate.window,
                        reset_at=candidate.reset_at,
                        model="auto",
                        attempted_at=utcnow(),
                        reset_at_tolerance_seconds=_attempt_reset_at_tolerance(candidate),
                    )
                    if skipped is not None:
                        completed = await self._warmup_repo.complete_attempt(
                            skipped.id,
                            status="skipped",
                            completed_at=utcnow(),
                            error_code="model_unavailable",
                            error_message="No eligible priced text model was available for warm-up",
                        )
                        latest_attempts[account.id] = completed or skipped
                    continue

                attempt = await self._warmup_repo.try_create_attempt(
                    account_id=account.id,
                    window=candidate.window,
                    reset_at=candidate.reset_at,
                    model=model,
                    attempted_at=utcnow(),
                    reset_at_tolerance_seconds=_attempt_reset_at_tolerance(candidate),
                )
                if attempt is None:
                    continue

                send_task = asyncio.create_task(
                    self._send_warmup(
                        attempt,
                        account=account,
                        model=model,
                        prompt=settings.limit_warmup_prompt,
                        sender=sender,
                        semaphore=send_semaphore,
                    ),
                    name=f"limit-warmup:{attempt.id}",
                )
                send_tasks[send_task] = attempt

        pending_send_tasks = set(send_tasks)
        try:
            while pending_send_tasks:
                completed_send_tasks, pending_send_tasks = await asyncio.wait(
                    pending_send_tasks,
                    return_when=asyncio.FIRST_COMPLETED,
                )
                completion_error: BaseException | None = None
                for send_task in completed_send_tasks:
                    outcome = await send_task
                    try:
                        completed = await self._complete_warmup(outcome)
                    except Exception as exc:
                        completion_error = completion_error or exc
                        await self._mark_aborted_warmup(
                            outcome.attempt,
                            error_code="warmup_completion_failed",
                            error_message="Limit warm-up completion failed",
                        )
                        continue
                    latest_attempts[outcome.account.id] = completed or outcome.attempt
                if completion_error is not None:
                    raise completion_error
        finally:
            if pending_send_tasks:
                for send_task in pending_send_tasks:
                    send_task.cancel()
                drained_results = await asyncio.gather(*pending_send_tasks, return_exceptions=True)
                for send_task, drained_result in zip(pending_send_tasks, drained_results, strict=True):
                    if isinstance(drained_result, LimitWarmupSendOutcome):
                        try:
                            completed = await self._complete_warmup(drained_result)
                        except Exception:
                            await self._mark_aborted_warmup(
                                drained_result.attempt,
                                error_code="warmup_completion_failed",
                                error_message="Limit warm-up completion failed",
                            )
                            continue
                        latest_attempts[drained_result.account.id] = completed or drained_result.attempt
                        continue
                    await self._mark_aborted_warmup(
                        send_tasks[send_task],
                        error_code=(
                            "warmup_cancelled"
                            if isinstance(drained_result, asyncio.CancelledError)
                            else "warmup_send_failed"
                        ),
                        error_message=(
                            "Limit warm-up cancelled after another warm-up completion failed"
                            if isinstance(drained_result, asyncio.CancelledError)
                            else (_truncate(str(drained_result)) or "Limit warm-up send failed")
                        ),
                    )

    async def run_anthropic_window_refresh(
        self,
        *,
        accounts: list[Account],
        settings: DashboardSettings,
        latest_primary: dict[str, UsageHistory],
        latest_secondary: dict[str, UsageHistory] | None = None,
    ) -> None:
        """Warm Claude accounts whose five-hour or weekly window has closed.

        Deliberately not routed through ``run_after_usage_refresh``: that method
        reasons about before/after snapshots produced by polling ChatGPT's usage
        API, whose shape Anthropic's endpoint does not share. This path works
        from stored window state instead -- the reset timestamp recorded from the
        last response or usage poll says when the window ends, and each warmup
        response rewrites it forward, so the trigger re-arms itself.

        ``latest_secondary`` is optional so a caller that only knows about the
        five-hour window keeps its old behaviour rather than silently losing the
        weekly trigger.
        """
        if not settings.limit_warmup_enabled:
            return
        sender = self._sender
        if sender is None:
            raise RuntimeError("LimitWarmupService requires a sender")

        candidates = [
            account
            for account in accounts
            if is_anthropic_provider(account.provider or "")
            and _account_is_safe_candidate(account)
            and account.limit_warmup_enabled
        ]
        if not candidates:
            return

        latest_attempts = await self._warmup_repo.latest_by_account([account.id for account in candidates])
        secondary_by_account = latest_secondary or {}
        now_epoch = naive_utc_to_epoch(utcnow())
        semaphore = asyncio.Semaphore(_MAX_CONCURRENT_WARMUP_SENDS)

        for account in candidates:
            if _in_cooldown(
                latest_attempts.get(account.id),
                cooldown_seconds=settings.limit_warmup_cooldown_seconds,
            ):
                continue
            candidate = _anthropic_warmup_candidate(
                primary=latest_primary.get(account.id),
                secondary=secondary_by_account.get(account.id),
                now=now_epoch,
            )
            if candidate is None:
                continue
            attempt = await self._warmup_repo.try_create_attempt(
                account_id=account.id,
                window=candidate.window,
                reset_at=candidate.reset_at,
                model=ANTHROPIC_WARMUP_MODEL,
                attempted_at=utcnow(),
                reset_at_tolerance_seconds=_attempt_reset_at_tolerance(candidate),
            )
            if attempt is None:
                continue
            outcome = await self._send_warmup(
                attempt,
                account=account,
                model=ANTHROPIC_WARMUP_MODEL,
                prompt=settings.limit_warmup_prompt,
                sender=sender,
                semaphore=semaphore,
            )
            try:
                await self._complete_warmup(outcome)
            except Exception:
                await self._mark_aborted_warmup(
                    attempt,
                    error_code="warmup_completion_failed",
                    error_message="Limit warm-up completion failed",
                )

    async def warm_account_now(
        self,
        *,
        account: Account,
        settings: DashboardSettings,
    ) -> ManualWarmupResult:
        """Send one Claude warmup immediately, regardless of the scheduler's switch.

        The operator asking for a window is a different decision from asking the
        scheduler to manage windows, so ``limit_warmup_enabled`` is not consulted
        here. Eligibility that protects the upstream -- Anthropic provider,
        servable status, an actual five-hour window -- is enforced by the caller.

        The attempt is filed under its own window name so it can never collide
        with, or be mistaken for, a scheduled elapsed-window attempt; its
        ``reset_at`` records the moment the window was opened by hand.
        """
        sender = self._sender
        if sender is None:
            raise RuntimeError("LimitWarmupService requires a sender")
        model = ANTHROPIC_WARMUP_MODEL
        attempt = await self._warmup_repo.try_create_attempt(
            account_id=account.id,
            window=_MANUAL_PRIMARY_WINDOW,
            reset_at=naive_utc_to_epoch(utcnow()),
            model=model,
            attempted_at=utcnow(),
            reset_at_tolerance_seconds=0,
        )
        if attempt is None:
            # Another warmup for this account already holds the window; sending a
            # second one would spend a request to open a window that is opening.
            return ManualWarmupResult(
                sent=False,
                success=False,
                model=model,
                error_code="warmup_already_in_flight",
                error_message="A warm-up for this account is already in progress",
            )
        outcome = await self._send_warmup(
            attempt,
            account=account,
            model=model,
            prompt=settings.limit_warmup_prompt,
            sender=sender,
            semaphore=asyncio.Semaphore(1),
        )
        try:
            await self._complete_warmup(outcome)
        except Exception:
            await self._mark_aborted_warmup(
                attempt,
                error_code="warmup_completion_failed",
                error_message="Limit warm-up completion failed",
            )
        result = outcome.result
        if result is None:
            return ManualWarmupResult(
                sent=True,
                success=False,
                model=model,
                error_code="warmup_send_failed",
                error_message=_truncate(outcome.error_message),
            )
        return ManualWarmupResult(
            sent=True,
            success=result.success,
            model=model,
            latency_ms=result.latency_ms,
            error_code=result.error_code,
            error_message=_truncate(result.error_message),
        )

    def _resolve_model(self, configured_model: str, account: Account) -> str | None:
        normalized = configured_model.strip()
        if normalized and normalized.lower() != "auto":
            return normalized

        candidates: list[tuple[float, str]] = []
        for model in get_model_registry().get_models_with_fallback().values():
            if not model.supported_in_api:
                continue
            if model.input_modalities and "text" not in {modality.lower() for modality in model.input_modalities}:
                continue
            if model.available_in_plans and not account_plan_matches_allowed(
                account.plan_type, model.available_in_plans
            ):
                continue
            resolved_price = get_pricing_for_model(model.slug)
            if resolved_price is None:
                continue
            _, price = resolved_price
            candidates.append((price.input_per_1m + price.output_per_1m, model.slug))
        if not candidates:
            return None
        return min(candidates, key=lambda item: (item[0], item[1]))[1]

    async def _send_warmup(
        self,
        attempt: AccountLimitWarmup,
        *,
        account: Account,
        model: str,
        prompt: str,
        sender: LimitWarmupSender,
        semaphore: asyncio.Semaphore,
    ) -> LimitWarmupSendOutcome:
        try:
            async with semaphore:
                result = await sender.send(account, model=model, prompt=prompt)
        except Exception as exc:
            logger.warning(
                "Limit warm-up send failed account_id=%s window=%s", account.id, attempt.window, exc_info=True
            )
            return LimitWarmupSendOutcome(
                attempt=attempt,
                account=account,
                model=model,
                result=None,
                error_message=str(exc),
            )

        return LimitWarmupSendOutcome(attempt=attempt, account=account, model=model, result=result)

    async def _complete_warmup(self, outcome: LimitWarmupSendOutcome) -> AccountLimitWarmup | None:
        if outcome.result is None:
            return await self._warmup_repo.complete_attempt(
                outcome.attempt.id,
                status="failed",
                completed_at=utcnow(),
                error_code="warmup_send_failed",
                error_message=_truncate(outcome.error_message),
            )

        result = outcome.result
        await self._record_request_log(
            account=outcome.account,
            model=outcome.model,
            result=result,
        )
        # Ingested regardless of outcome: a 429 describes the account's window as
        # accurately as a 200 does, and headers absent from an error response
        # simply parse to nothing.
        if self._window_ingestor is not None and result.usage_headers is not None:
            await self._window_ingestor(outcome.account.id, result.usage_headers)
        status = "succeeded" if result.success else "failed"
        error_code = result.error_code
        if error_code in _QUOTA_ERROR_CODES:
            error_code = "quota_still_exhausted"
        return await self._warmup_repo.complete_attempt(
            outcome.attempt.id,
            status=status,
            completed_at=utcnow(),
            error_code=error_code,
            error_message=_truncate(result.error_message),
        )

    async def _mark_aborted_warmup(
        self,
        attempt: AccountLimitWarmup,
        *,
        error_code: str,
        error_message: str,
    ) -> None:
        try:
            await self._warmup_repo.complete_attempt(
                attempt.id,
                status="failed",
                completed_at=utcnow(),
                error_code=error_code,
                error_message=error_message,
            )
        except Exception:
            logger.warning(
                "Failed to mark aborted limit warm-up attempt_id=%s error_code=%s",
                attempt.id,
                error_code,
                exc_info=True,
            )

    async def _record_request_log(
        self,
        *,
        account: Account,
        model: str,
        result: LimitWarmupSendResult,
    ) -> None:
        usage = result.usage
        input_tokens = usage.input_tokens if usage is not None else None
        output_tokens = usage.output_tokens if usage is not None else None
        cached_input_tokens = (
            usage.input_tokens_details.cached_tokens
            if usage is not None and usage.input_tokens_details is not None
            else None
        )
        reasoning_tokens = (
            usage.output_tokens_details.reasoning_tokens
            if usage is not None and usage.output_tokens_details is not None
            else None
        )
        await self._request_logs_repo.add_log(
            account_id=account.id,
            request_id=result.request_id,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cached_input_tokens=cached_input_tokens,
            reasoning_tokens=reasoning_tokens,
            latency_ms=result.latency_ms,
            status="success" if result.success else "error",
            error_code=result.error_code,
            error_message=_truncate(result.error_message),
            transport="http",
            plan_type=account.plan_type,
            source=LIMIT_WARMUP_SOURCE,
            request_kind=LIMIT_WARMUP_REQUEST_KIND,
            upstream_proxy_route_mode=result.upstream_proxy_route_mode,
            upstream_proxy_pool_id=result.upstream_proxy_pool_id,
            upstream_proxy_endpoint_id=result.upstream_proxy_endpoint_id,
            upstream_proxy_fallback_used=result.upstream_proxy_fallback_used,
            upstream_proxy_fail_closed_reason=result.upstream_proxy_fail_closed_reason,
        )


@dataclass(frozen=True, slots=True)
class ManualWarmupResult:
    """Outcome of an operator-triggered warmup, shaped for the API layer."""

    sent: bool
    success: bool
    model: str
    latency_ms: int | None = None
    error_code: str | None = None
    error_message: str | None = None


@dataclass(frozen=True, slots=True)
class _WarmupCandidate:
    reset_at: int
    window: str


def _anthropic_elapsed_window_candidate(
    entry: UsageHistory | None,
    *,
    now: int,
    window: str = "primary",
) -> _WarmupCandidate | None:
    """A candidate iff the account has this window and it is not running.

    ``entry is None`` -- "never recorded a window" -- is what excludes
    usage-based seats: they bill against a budget, report no window either in
    response headers or from the usage API, so no row is ever written and there
    is no window a ping could open.

    A row with **no reset** is the opposite case and is a candidate. The usage
    API answers ``five_hour: {utilization: 0, resets_at: null}`` for an account
    whose five hours have run out, which is exactly the state warmup exists to
    leave. Before the usage poll existed this state was invisible -- the stored
    row kept the spent window's old reset timestamp, and an elapsed timestamp
    was the only available signal.

    ``seven_day`` answers in the same shape and is anchored the same way, so the
    test is the window's own, not the five-hour one's.
    """
    if entry is None:
        return None
    if entry.reset_at is None:
        # Zero rather than a missing timestamp so the attempt record dedupes on
        # "the closed-window state", which is what is being acted on.
        return _WarmupCandidate(reset_at=_NO_WINDOW_RESET_AT, window=window)
    if entry.reset_at > now:
        return None
    return _WarmupCandidate(reset_at=entry.reset_at, window=window)


def _anthropic_warmup_candidate(
    *,
    primary: UsageHistory | None,
    secondary: UsageHistory | None,
    now: int,
) -> _WarmupCandidate | None:
    """The window this account needs opened, five-hour first.

    Both of a Claude seat's rolling windows start at the account's first request
    rather than on a calendar, so either can sit closed while the account is
    idle -- and a weekly window left unstarted pushes the *next* weekly reset out
    by however long the account stayed quiet. That is the whole reason warmup
    exists, and it was only ever applied to the five hours.

    One ping opens every closed window at once, so when both have run out the
    five-hour attempt already covers the weekly one and a second request would
    buy nothing. The weekly window earns its own ping only in the case the
    five-hour trigger cannot see: the short window still running while the
    weekly one has run out.
    """
    elapsed_primary = _anthropic_elapsed_window_candidate(primary, now=now, window="primary")
    if elapsed_primary is not None:
        return elapsed_primary
    return _anthropic_elapsed_window_candidate(secondary, now=now, window="secondary")


def _selected_windows(value: str) -> tuple[str, ...]:
    normalized = value.strip().lower()
    if normalized == "both":
        return ("primary", "secondary")
    if normalized in {"primary", "secondary"}:
        return (normalized,)
    return ()


def _account_is_safe_candidate(account: Account) -> bool:
    # A paused Claude account is one deliberately kept out of the serving pool,
    # not a broken one: its five-hour window still ages, and keeping that window
    # rolling is the whole point of the warm-up, so it is ready the moment the
    # operator switches back to it. The ChatGPT path keeps the stricter rule --
    # a paused account there is not expected to emit traffic at all.
    if is_anthropic_provider(account.provider):
        return account.status in _WARMABLE_ANTHROPIC_STATUSES
    return account.status == AccountStatus.ACTIVE


def _in_cooldown(attempt: AccountLimitWarmup | None, *, cooldown_seconds: int) -> bool:
    if attempt is None:
        return False
    return utcnow() - attempt.attempted_at < timedelta(seconds=cooldown_seconds)


def _build_candidate(
    *,
    account: Account,
    window: str,
    before_primary: dict[str, UsageHistory],
    before_secondary: dict[str, UsageHistory],
    after_primary: dict[str, UsageHistory],
    after_secondary: dict[str, UsageHistory],
    exhausted_threshold_percent: float,
    min_available_percent: float,
) -> _WarmupCandidate | None:
    before = _effective_usage_entry(
        account.id,
        window=window,
        primary=before_primary,
        secondary=before_secondary,
    )
    after = _effective_usage_entry(
        account.id,
        window=window,
        primary=after_primary,
        secondary=after_secondary,
    )
    if before is None or after is None:
        return None
    if before.reset_at is None or after.reset_at is None:
        return None
    if before.used_percent < exhausted_threshold_percent:
        return None
    if after.used_percent >= 100.0:
        return None
    available_percent = 100.0 - after.used_percent
    if min_available_percent < 100.0 and available_percent < min_available_percent:
        return None
    # Require a meaningful reset_at forward jump (not just upstream timestamp jitter).
    # Upstream can report reset_at values that fluctuate by ~1 second between
    # refresh cycles; only treat a jump of at least 60 seconds as a real reset.
    if after.reset_at - before.reset_at < _RESET_CONFIRMED_MIN_JUMP_SECONDS:
        return None
    return _WarmupCandidate(reset_at=after.reset_at, window=window)


def _build_staggered_idle_candidate(
    *,
    account: Account,
    accounts: list[Account],
    now: datetime,
    after_primary: dict[str, UsageHistory],
    refresh_started_at: datetime | None,
    usage_refresh_interval_seconds: int,
    idle_threshold_percent: float = 1.0,
) -> _WarmupCandidate | None:
    after = after_primary.get(account.id)
    if after is None:
        return None
    if after.reset_at is None:
        return None
    if after.window_minutes is not None and after.window_minutes > _SHORT_WINDOW_MAX_MINUTES:
        # Any long window (weekly, monthly, or a nonstandard duration over
        # 24h) has no short phase to pre-start.
        return None
    if after.used_percent > idle_threshold_percent:
        return None

    window_seconds = _rolling_window_seconds(after)
    due = _staggered_idle_due(
        account.id,
        [candidate.id for candidate in accounts],
        now=now,
        reset_at=after.reset_at,
        interval_started_at=refresh_started_at,
        usage_refresh_interval_seconds=usage_refresh_interval_seconds,
        window_seconds=window_seconds,
    )
    if due is None:
        return None
    if not _usage_entry_refreshed_for_cycle(
        after,
        refresh_started_at=refresh_started_at,
        cycle_end=due.cycle_end,
        window_seconds=window_seconds,
    ):
        return None
    return _WarmupCandidate(reset_at=after.reset_at, window=_IDLE_PRIMARY_WINDOW)


@dataclass(frozen=True, slots=True)
class _StaggeredIdleDue:
    cycle_end: int
    slot_offset_seconds: int


def _rolling_window_seconds(entry: UsageHistory) -> int:
    # Derive the rolling cycle from the observed primary window duration so
    # the stagger tracks whatever short window upstream reports; 300 minutes
    # remains the fallback when duration metadata is missing.
    if entry.window_minutes is not None and entry.window_minutes > 0:
        return int(entry.window_minutes) * 60
    return _ROLLING_WINDOW_SECONDS


def _staggered_idle_due(
    account_id: str,
    account_ids: list[str],
    *,
    now: datetime,
    reset_at: int,
    interval_started_at: datetime | None = None,
    usage_refresh_interval_seconds: int = _STAGGER_SLOT_GRACE_SECONDS,
    window_seconds: int = _ROLLING_WINDOW_SECONDS,
) -> _StaggeredIdleDue | None:
    if not account_ids:
        return None
    ordered_account_ids = sorted(set(account_ids))
    try:
        account_index = ordered_account_ids.index(account_id)
    except ValueError:
        return None

    now_epoch = naive_utc_to_epoch(now)
    cycle_start = reset_at - window_seconds
    if now_epoch < cycle_start or now_epoch >= reset_at:
        return None
    elapsed = now_epoch - cycle_start
    slot_offset = int(account_index * window_seconds / len(ordered_account_ids))
    grace_seconds = max(_STAGGER_SLOT_GRACE_SECONDS, usage_refresh_interval_seconds)
    interval_start_epoch = naive_utc_to_epoch(interval_started_at) if interval_started_at is not None else now_epoch
    interval_start_epoch = min(interval_start_epoch, now_epoch)
    interval_start_elapsed = max(0, interval_start_epoch - cycle_start)
    if not slot_offset <= elapsed:
        return None
    if slot_offset + grace_seconds <= interval_start_elapsed:
        return None
    return _StaggeredIdleDue(
        cycle_end=cycle_start + window_seconds,
        slot_offset_seconds=slot_offset,
    )


def _usage_entry_refreshed_for_cycle(
    entry: UsageHistory,
    *,
    refresh_started_at: datetime | None,
    cycle_end: int | None,
    window_seconds: int = _ROLLING_WINDOW_SECONDS,
) -> bool:
    if entry.recorded_at is None:
        return False
    if cycle_end is not None:
        cycle_start = cycle_end - window_seconds
        if entry.recorded_at < datetime.fromtimestamp(cycle_start, tz=timezone.utc).replace(tzinfo=None):
            return False
        if entry.reset_at is not None and entry.reset_at <= cycle_start:
            return False
    if refresh_started_at is None:
        return True
    return entry.recorded_at >= refresh_started_at


def _effective_usage_entry(
    account_id: str,
    *,
    window: str,
    primary: dict[str, UsageHistory],
    secondary: dict[str, UsageHistory],
) -> UsageHistory | None:
    if window == "primary":
        primary_entry = primary.get(account_id)
        if primary_entry is None or usage_core.is_weekly_window_minutes(primary_entry.window_minutes):
            return None
        return primary_entry

    primary_entry = primary.get(account_id)
    secondary_entry = secondary.get(account_id)
    if primary_entry is not None and usage_core.is_weekly_window_minutes(primary_entry.window_minutes):
        if secondary_entry is None:
            return primary_entry
        if usage_core.should_use_weekly_primary(
            usage_history_to_window_row(primary_entry),
            usage_history_to_window_row(secondary_entry),
        ):
            return primary_entry
    return secondary_entry


def _event_error(*errors: OpenAIError | None) -> OpenAIError:
    for error in errors:
        if error is not None:
            return error
    return OpenAIError(message=None, code=None)


def _elapsed_ms(started: float) -> int:
    return max(0, int((time.monotonic() - started) * 1000))


def _truncate(value: str | None, limit: int = 1000) -> str | None:
    if value is None:
        return None
    if len(value) <= limit:
        return value
    return value[: limit - 1] + "..."


def _attempt_reset_at_tolerance(candidate: _WarmupCandidate) -> int:
    if candidate.window == _IDLE_PRIMARY_WINDOW:
        return _IDLE_RESET_AT_JITTER_TOLERANCE_SECONDS
    return 0

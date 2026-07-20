from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncIterator, Callable, Mapping
from contextlib import AbstractAsyncContextManager

from starlette.responses import Response, StreamingResponse

from app.core.anthropic.upstream import (
    ANTHROPIC_API_BASE,
    AnthropicUpstreamResponse,
    build_upstream_headers,
    credential_is_static_api_key,
    filter_response_headers,
    open_messages,
)
from app.core.anthropic.usage_headers import AnthropicUsageSnapshot, parse_unified_usage
from app.core.auth.refresh import (
    RefreshError,
    is_transient_refresh_contention,
    pop_token_refresh_timeout_override,
    push_token_refresh_timeout_override,
)
from app.core.balancer.types import UpstreamError
from app.core.config.settings import get_settings
from app.core.config.settings_cache import get_settings_cache
from app.core.crypto import TokenEncryptor
from app.core.providers import PROVIDER_ANTHROPIC
from app.db.models import Account
from app.db.session import get_background_session
from app.modules.accounts.auth_manager import AccountsRepositoryPort, AuthManager
from app.modules.anthropic_proxy.schemas import anthropic_error_body, error_type_for_status
from app.modules.proxy.account_cache import get_account_selection_cache
from app.modules.proxy.load_balancer import LoadBalancer
from app.modules.proxy.service import _routing_strategy as resolve_routing_strategy
from app.modules.usage.repository import UsageRepository

logger = logging.getLogger(__name__)

AccountsRepoContextFactory = Callable[[], AbstractAsyncContextManager[AccountsRepositoryPort]]

_MAX_ACCOUNT_ATTEMPTS = 3
_STREAM_CHUNK_SIZE = 8192
_SSE_CONTENT_TYPE = "text/event-stream"
# 403 bodies whose error text names a revoked/expired OAuth grant are permanent.
_REVOCATION_MARKERS = ("oauth", "revoked", "token has expired", "authentication_error")

# Usage-ingest throttle: write a fresh usage row only when the utilization moved
# by at least this many points or at least this many seconds have passed, so a
# burst of requests does not flood usage_history.
_USAGE_WRITE_MIN_DELTA_PCT = 1.0
_USAGE_WRITE_MIN_INTERVAL_SECONDS = 60.0
_PRIMARY_WINDOW_MINUTES = 5 * 60
_SECONDARY_WINDOW_MINUTES = 7 * 24 * 60


class AnthropicProxyService:
    """Selects a Claude account per request and relays the Messages API call.

    Self-contained failover loop (not the OpenAI streaming-retry machinery):
    transparent body pass-through, one forced token refresh per account per
    request on 401, rate-limit failover on 429, and no cross-account replay
    once the first byte has reached the client.
    """

    def __init__(
        self,
        load_balancer: LoadBalancer,
        accounts_repo_factory: AccountsRepoContextFactory,
    ) -> None:
        self._load_balancer = load_balancer
        self._accounts_repo_factory = accounts_repo_factory
        self._encryptor = TokenEncryptor()
        # Fire-and-forget usage writes, tracked so they are not GC'd mid-flight.
        self._usage_tasks: set[asyncio.Task[None]] = set()
        # account_id -> (last write monotonic, last primary used pct).
        self._usage_write_state: dict[str, tuple[float, float]] = {}

    async def relay(self, *, upstream_path: str, client_headers: Mapping[str, str], body: bytes) -> Response:
        settings = get_settings()
        routing_strategy = resolve_routing_strategy(await get_settings_cache().get())
        url = f"{ANTHROPIC_API_BASE}{upstream_path}"
        tried: set[str] = set()
        last_error: tuple[int, bytes, list[tuple[str, str]]] | None = None

        for _ in range(_MAX_ACCOUNT_ATTEMPTS):
            selection = await self._load_balancer.select_account(
                provider=PROVIDER_ANTHROPIC,
                exclude_account_ids=tried,
                routing_strategy=routing_strategy,
            )
            account = selection.account
            if account is None:
                if last_error is not None:
                    return _passthrough_response(*last_error)
                return _no_account_response(selection.error_message)
            tried.add(account.id)

            fresh = await self._ensure_fresh_or_degrade(account)
            if fresh is None:
                continue
            account = fresh

            is_static = credential_is_static_api_key(self._encryptor.decrypt(account.access_token_encrypted))
            forced_refresh_done = False
            while True:
                credential = self._encryptor.decrypt(account.access_token_encrypted)
                headers = build_upstream_headers(client_headers, credential)
                upstream = await open_messages(
                    url,
                    body=body,
                    headers=headers,
                    idle_timeout_seconds=settings.stream_idle_timeout_seconds,
                )
                status = upstream.status

                if status < 300:
                    await self._load_balancer.record_success(account)
                    self._ingest_usage_headers(account.id, upstream.headers)
                    return await self._success_response(upstream)

                error_body = await upstream.read()
                error_headers = dict(upstream.headers)
                await upstream.aclose()

                if status == 401 and not is_static and not forced_refresh_done:
                    refreshed = await self._force_refresh_or_degrade(account)
                    if refreshed is None:
                        break  # -> next account
                    account = refreshed
                    forced_refresh_done = True
                    continue  # retry same account once

                if status == 401:
                    await self._load_balancer.mark_permanent_failure(account, "account_auth_invalidated")
                    last_error = (status, error_body, filter_response_headers(error_headers))
                    break

                if status == 429:
                    await self._load_balancer.mark_rate_limit(account, _rate_limit_error(error_headers))
                    # 429s carry the unified rate-limit headers (utilization at
                    # the cap) -- exactly the saturation signal the balancer
                    # wants, so ingest them like a success response.
                    self._ingest_usage_headers(account.id, error_headers)
                    last_error = (status, error_body, filter_response_headers(error_headers))
                    break

                if status == 403 and _looks_like_revocation(error_body):
                    await self._load_balancer.mark_permanent_failure(account, "account_auth_invalidated")
                    last_error = (status, error_body, filter_response_headers(error_headers))
                    break

                if 400 <= status < 500:
                    # Client-side error (validation, payload too large, ...):
                    # return verbatim, no health write, no failover.
                    return _passthrough_response(status, error_body, filter_response_headers(error_headers))

                # 5xx / unexpected: record an error and try the next account.
                await self._load_balancer.record_error(account)
                last_error = (status, error_body, filter_response_headers(error_headers))
                break

        if last_error is not None:
            return _passthrough_response(*last_error)
        return _anthropic_error_response(503, "No Claude account is currently available")

    async def _ensure_fresh_or_degrade(self, account: Account) -> Account | None:
        try:
            return await self._ensure_fresh(account)
        except RefreshError as exc:
            await self._apply_refresh_failure(account, exc)
            return None

    async def _force_refresh_or_degrade(self, account: Account) -> Account | None:
        try:
            return await self._ensure_fresh(account, force=True)
        except RefreshError as exc:
            code = exc.code if exc.is_permanent else "account_auth_invalidated"
            await self._load_balancer.mark_permanent_failure(account, code)
            return None

    async def _apply_refresh_failure(self, account: Account, exc: RefreshError) -> None:
        if exc.is_permanent:
            await self._load_balancer.mark_permanent_failure(account, exc.code)
        elif is_transient_refresh_contention(exc):
            # Healthy account, contended refresh claim: no health penalty.
            return
        else:
            await self._load_balancer.record_error(account)

    async def _ensure_fresh(self, account: Account, *, force: bool = False) -> Account:
        settings = get_settings()
        token = push_token_refresh_timeout_override(settings.token_refresh_timeout_seconds)
        try:
            async with self._accounts_repo_factory() as repo:
                auth_manager = AuthManager(
                    repo,
                    refresh_repo_factory=self._accounts_repo_factory,
                )
                return await auth_manager.ensure_fresh(account, force=force)
        finally:
            pop_token_refresh_timeout_override(token)

    async def _success_response(self, upstream: AnthropicUpstreamResponse) -> Response:
        headers = filter_response_headers(upstream.headers)
        content_type = upstream.headers.get("content-type", "")
        if _SSE_CONTENT_TYPE in content_type.lower():
            return StreamingResponse(
                _stream_upstream(upstream),
                status_code=upstream.status,
                headers=dict(headers),
                media_type=content_type,
            )
        body = await upstream.read()
        await upstream.aclose()
        return Response(content=body, status_code=upstream.status, headers=dict(headers))

    def _ingest_usage_headers(self, account_id: str, response_headers: Mapping[str, str]) -> None:
        """Passively record 5h/7d utilization from relay response headers.

        Throttled per account and written on a background task so the response
        path is never blocked. Feeds the same primary/secondary usage windows
        the balancer already reads, so capacity-weighted selection reflects real
        Claude utilization with zero balancer changes.
        """
        snapshot = parse_unified_usage(response_headers)
        if not snapshot.has_any:
            return
        if not self._should_write_usage(account_id, snapshot):
            return
        task = asyncio.create_task(self._write_usage(account_id, snapshot))
        self._usage_tasks.add(task)
        task.add_done_callback(self._usage_tasks.discard)

    def _should_write_usage(self, account_id: str, snapshot: AnthropicUsageSnapshot) -> bool:
        now = time.monotonic()
        previous = self._usage_write_state.get(account_id)
        primary = snapshot.primary_used_percent
        if previous is None or primary is None:
            self._usage_write_state[account_id] = (now, primary if primary is not None else 0.0)
            return True
        last_time, last_pct = previous
        elapsed_enough = now - last_time >= _USAGE_WRITE_MIN_INTERVAL_SECONDS
        moved_enough = abs(primary - last_pct) >= _USAGE_WRITE_MIN_DELTA_PCT
        if elapsed_enough or moved_enough:
            self._usage_write_state[account_id] = (now, primary)
            return True
        return False

    async def _write_usage(self, account_id: str, snapshot: AnthropicUsageSnapshot) -> None:
        try:
            async with get_background_session() as session:
                repo = UsageRepository(session)
                if snapshot.primary_used_percent is not None:
                    await repo.add_entry(
                        account_id,
                        used_percent=snapshot.primary_used_percent,
                        window="primary",
                        reset_at=snapshot.primary_reset_at,
                        window_minutes=_PRIMARY_WINDOW_MINUTES,
                    )
                if snapshot.secondary_used_percent is not None:
                    await repo.add_entry(
                        account_id,
                        used_percent=snapshot.secondary_used_percent,
                        window="secondary",
                        reset_at=snapshot.secondary_reset_at,
                        window_minutes=_SECONDARY_WINDOW_MINUTES,
                    )
            get_account_selection_cache().invalidate()
        except Exception:
            logger.warning("Failed to ingest anthropic usage for account_id=%s", account_id, exc_info=True)


async def _stream_upstream(upstream: AnthropicUpstreamResponse) -> AsyncIterator[bytes]:
    # A client disconnect cancels this generator; the finally releases the
    # upstream lease WITHOUT a health write (idle disconnects never mark an
    # account unhealthy). No cross-account replay happens after the first byte.
    try:
        async for chunk in upstream.aiter_chunked(_STREAM_CHUNK_SIZE):
            yield chunk
    finally:
        await upstream.aclose()


def _rate_limit_error(headers: Mapping[str, str]) -> UpstreamError:
    error: UpstreamError = {"message": "Anthropic rate limit reached"}
    reset_epoch = _first_int(
        headers,
        ("anthropic-ratelimit-unified-reset", "anthropic-ratelimit-unified-5h-reset"),
    )
    if reset_epoch is not None:
        error["resets_at"] = reset_epoch
        return error
    retry_after = _first_int(headers, ("retry-after",))
    if retry_after is not None:
        error["resets_in_seconds"] = retry_after
    return error


def _first_int(headers: Mapping[str, str], names: tuple[str, ...]) -> int | None:
    for name in names:
        raw = headers.get(name)
        if raw is None:
            continue
        try:
            return int(float(raw))
        except (TypeError, ValueError):
            continue
    return None


def _looks_like_revocation(body: bytes) -> bool:
    text = body.decode("utf-8", errors="replace").lower()
    return any(marker in text for marker in _REVOCATION_MARKERS)


def _passthrough_response(status: int, body: bytes, headers: list[tuple[str, str]]) -> Response:
    return Response(content=body, status_code=status, headers=dict(headers))


def _no_account_response(error_message: str | None) -> Response:
    message = error_message or "No Claude account is currently available"
    # A modest retry hint so clients back off instead of hot-retrying.
    return _anthropic_error_response(429, message, headers={"retry-after": "30"})


def _anthropic_error_response(status: int, message: str, *, headers: dict[str, str] | None = None) -> Response:
    return Response(
        content=anthropic_error_body(error_type_for_status(status), message),
        status_code=status,
        media_type="application/json",
        headers=headers,
    )

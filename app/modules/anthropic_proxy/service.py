from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from collections.abc import AsyncIterator, Callable, Mapping
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass

from starlette.responses import Response, StreamingResponse

from app.core.anthropic.client_identity import NormalizedRelayRequest, normalize_claude_code_request
from app.core.anthropic.messages_usage import (
    AnthropicMessageUsage,
    SseUsageAccumulator,
    parse_message_usage,
)
from app.core.anthropic.upstream import (
    ANTHROPIC_API_BASE,
    AnthropicUpstreamResponse,
    build_upstream_headers,
    credential_is_static_api_key,
    filter_response_headers,
    open_messages,
)
from app.core.anthropic.usage_headers import AnthropicUsageSnapshot, parse_unified_usage
from app.core.anthropic.usage_ingest import persist_usage_snapshot
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
from app.core.usage.useragent import request_log_useragent_fields
from app.db.models import Account
from app.db.session import get_background_session
from app.modules.accounts.auth_manager import AccountsRepositoryPort, AuthManager
from app.modules.anthropic_proxy.schemas import anthropic_error_body, error_type_for_status
from app.modules.proxy.account_cache import get_account_selection_cache
from app.modules.proxy.load_balancer import LoadBalancer
from app.modules.proxy.service import _routing_strategy as resolve_routing_strategy
from app.modules.request_logs.repository import RequestLogsRepository
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

# Only completions are logged. count_tokens returns no completion and burns no
# quota, and Claude Code issues it constantly, so logging it would swamp the
# request list and skew every per-request average against the Codex baseline.
_LOGGED_UPSTREAM_PATH = "/v1/messages"
_ERROR_MESSAGE_MAX_CHARS = 500
_TRANSPORT_HTTP = "http"


@dataclass(frozen=True, slots=True)
class _RelayLogContext:
    """Per-request fields that stay constant across failover attempts."""

    enabled: bool
    api_key_id: str | None
    model: str
    useragent: str | None
    useragent_group: str | None
    client_ip: str | None


@dataclass(frozen=True, slots=True)
class _PendingRequestLog:
    """One `request_logs` row, assembled on the request path, written off it."""

    context: _RelayLogContext
    account_id: str
    request_id: str
    model: str
    status: str
    latency_ms: int
    error_code: str | None = None
    error_message: str | None = None
    upstream_status_code: int | None = None
    latency_first_token_ms: int | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    cached_input_tokens: int | None = None


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
        # Same contract for request-log writes: off the response path, tracked.
        self._log_tasks: set[asyncio.Task[None]] = set()
        # account_id -> (last write monotonic, last primary used pct).
        self._usage_write_state: dict[str, tuple[float, float]] = {}

    async def relay(
        self,
        *,
        upstream_path: str,
        client_headers: Mapping[str, str],
        body: bytes,
        api_key_id: str | None = None,
        client_ip: str | None = None,
    ) -> Response:
        settings = get_settings()
        routing_strategy = resolve_routing_strategy(await get_settings_cache().get())
        url = f"{ANTHROPIC_API_BASE}{upstream_path}"
        tried: set[str] = set()
        last_error: tuple[int, bytes, list[tuple[str, str]]] | None = None
        # Read from the CLIENT headers, before any upstream identity rewrite: the
        # upstream leg is normalized to Claude Code for OAuth credentials, but the
        # log records who actually called so reports can still tell callers apart.
        useragent, useragent_group = request_log_useragent_fields(client_headers)
        # Normalizing re-serializes the body, so it is done at most once per relay
        # and only if an OAuth account is actually selected.
        normalized: NormalizedRelayRequest | None = None
        log_context = _RelayLogContext(
            enabled=upstream_path == _LOGGED_UPSTREAM_PATH,
            api_key_id=api_key_id,
            model=_requested_model(body),
            useragent=useragent,
            useragent_group=useragent_group,
            client_ip=client_ip,
        )

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
            if is_static:
                upstream_body = body
                attribution: str | None = None
            else:
                if normalized is None:
                    normalized = normalize_claude_code_request(body)
                upstream_body = normalized.body
                attribution = normalized.attribution
            forced_refresh_done = False
            while True:
                credential = self._encryptor.decrypt(account.access_token_encrypted)
                headers = build_upstream_headers(client_headers, credential, attribution=attribution)
                attempt_started = time.perf_counter()
                upstream = await open_messages(
                    url,
                    body=upstream_body,
                    headers=headers,
                    idle_timeout_seconds=settings.stream_idle_timeout_seconds,
                )
                status = upstream.status

                if status < 300:
                    await self._load_balancer.record_success(account)
                    self._ingest_usage_headers(account.id, upstream.headers)
                    return await self._success_response(
                        upstream,
                        log_context=log_context,
                        account_id=account.id,
                        started=attempt_started,
                    )

                error_body = await upstream.read()
                error_headers = dict(upstream.headers)
                await upstream.aclose()
                # Every branch below reached an upstream response, so each one
                # is a real attempt against this account and gets its own row.
                record_attempt = self._attempt_recorder(
                    log_context,
                    account_id=account.id,
                    started=attempt_started,
                    upstream_status=status,
                    upstream_headers=error_headers,
                    error_body=error_body,
                )

                if status == 401 and not is_static and not forced_refresh_done:
                    record_attempt("account_auth_invalidated")
                    refreshed = await self._force_refresh_or_degrade(account)
                    if refreshed is None:
                        break  # -> next account
                    account = refreshed
                    forced_refresh_done = True
                    continue  # retry same account once

                if status == 401:
                    record_attempt("account_auth_invalidated")
                    await self._load_balancer.mark_permanent_failure(account, "account_auth_invalidated")
                    last_error = (status, error_body, filter_response_headers(error_headers))
                    break

                if status == 429:
                    record_attempt("rate_limit_exceeded")
                    await self._load_balancer.mark_rate_limit(account, _rate_limit_error(error_headers))
                    # 429s carry the unified rate-limit headers (utilization at
                    # the cap) -- exactly the saturation signal the balancer
                    # wants, so ingest them like a success response.
                    self._ingest_usage_headers(account.id, error_headers)
                    last_error = (status, error_body, filter_response_headers(error_headers))
                    break

                if status == 403 and _looks_like_revocation(error_body):
                    record_attempt("account_auth_invalidated")
                    await self._load_balancer.mark_permanent_failure(account, "account_auth_invalidated")
                    last_error = (status, error_body, filter_response_headers(error_headers))
                    break

                if 400 <= status < 500:
                    # Client-side error (validation, payload too large, ...):
                    # return verbatim, no health write, no failover.
                    record_attempt("invalid_request")
                    return _passthrough_response(status, error_body, filter_response_headers(error_headers))

                # 5xx / unexpected: record an error and try the next account.
                record_attempt("upstream_error")
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

    async def _success_response(
        self,
        upstream: AnthropicUpstreamResponse,
        *,
        log_context: _RelayLogContext,
        account_id: str,
        started: float,
    ) -> Response:
        headers = filter_response_headers(upstream.headers)
        content_type = upstream.headers.get("content-type", "")
        request_id = _upstream_request_id(upstream.headers)
        if _SSE_CONTENT_TYPE in content_type.lower():
            return StreamingResponse(
                self._stream_and_log(
                    upstream,
                    log_context=log_context,
                    account_id=account_id,
                    started=started,
                    request_id=request_id,
                ),
                status_code=upstream.status,
                headers=dict(headers),
                media_type=content_type,
            )
        body = await upstream.read()
        await upstream.aclose()
        self._record_success(
            log_context,
            account_id=account_id,
            request_id=request_id,
            usage=parse_message_usage(body),
            latency_ms=_elapsed_ms(started),
            latency_first_token_ms=None,
        )
        return Response(content=body, status_code=upstream.status, headers=dict(headers))

    async def _stream_and_log(
        self,
        upstream: AnthropicUpstreamResponse,
        *,
        log_context: _RelayLogContext,
        account_id: str,
        started: float,
        request_id: str,
    ) -> AsyncIterator[bytes]:
        # Usage is read off the bytes as they pass; nothing is buffered and no
        # chunk is held back. A client disconnect cancels this generator, and
        # the finally still logs what was served up to that point.
        accumulator = SseUsageAccumulator()
        first_token_ms: int | None = None
        try:
            async for chunk in upstream.aiter_chunked(_STREAM_CHUNK_SIZE):
                if first_token_ms is None:
                    first_token_ms = _elapsed_ms(started)
                accumulator.feed(chunk)
                yield chunk
        finally:
            await upstream.aclose()
            self._record_success(
                log_context,
                account_id=account_id,
                request_id=request_id,
                usage=accumulator.usage,
                latency_ms=_elapsed_ms(started),
                latency_first_token_ms=first_token_ms,
            )

    def _record_success(
        self,
        log_context: _RelayLogContext,
        *,
        account_id: str,
        request_id: str,
        usage: AnthropicMessageUsage,
        latency_ms: int,
        latency_first_token_ms: int | None,
    ) -> None:
        if not log_context.enabled:
            return
        self._spawn_log_write(
            _PendingRequestLog(
                context=log_context,
                account_id=account_id,
                request_id=request_id,
                # The response names the model actually served, which can differ
                # from the request's alias; fall back to what was asked for.
                model=usage.model or log_context.model,
                status="success",
                latency_ms=latency_ms,
                latency_first_token_ms=latency_first_token_ms,
                input_tokens=usage.input_tokens,
                output_tokens=usage.output_tokens,
                cached_input_tokens=usage.cached_input_tokens,
            )
        )

    def _attempt_recorder(
        self,
        log_context: _RelayLogContext,
        *,
        account_id: str,
        started: float,
        upstream_status: int,
        upstream_headers: Mapping[str, str],
        error_body: bytes,
    ) -> Callable[[str], None]:
        """Bind one failed attempt so each branch only names its error code."""

        def record(error_code: str) -> None:
            if not log_context.enabled:
                return
            self._spawn_log_write(
                _PendingRequestLog(
                    context=log_context,
                    account_id=account_id,
                    request_id=_upstream_request_id(upstream_headers),
                    model=log_context.model,
                    status="error",
                    error_code=error_code,
                    error_message=_error_message(error_body),
                    upstream_status_code=upstream_status,
                    latency_ms=_elapsed_ms(started),
                )
            )

        return record

    def _spawn_log_write(self, row: _PendingRequestLog) -> None:
        task = asyncio.create_task(self._write_request_log(row))
        self._log_tasks.add(task)
        task.add_done_callback(self._log_tasks.discard)

    async def _write_request_log(self, row: _PendingRequestLog) -> None:
        try:
            async with get_background_session() as session:
                await RequestLogsRepository(session).add_log(
                    account_id=row.account_id,
                    api_key_id=row.context.api_key_id,
                    request_id=row.request_id,
                    model=row.model,
                    input_tokens=row.input_tokens,
                    output_tokens=row.output_tokens,
                    cached_input_tokens=row.cached_input_tokens,
                    latency_ms=row.latency_ms,
                    latency_first_token_ms=row.latency_first_token_ms,
                    status=row.status,
                    error_code=row.error_code,
                    error_message=row.error_message,
                    upstream_status_code=row.upstream_status_code,
                    transport=_TRANSPORT_HTTP,
                    useragent=row.context.useragent,
                    useragent_group=row.context.useragent_group,
                    client_ip=row.context.client_ip,
                )
        except Exception:
            # A lost log row must never change what the client received.
            logger.warning("Failed to write anthropic request log account_id=%s", row.account_id, exc_info=True)

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
                await persist_usage_snapshot(UsageRepository(session), account_id, snapshot)
            get_account_selection_cache().invalidate()
        except Exception:
            logger.warning("Failed to ingest anthropic usage for account_id=%s", account_id, exc_info=True)


def _elapsed_ms(started: float) -> int:
    return max(0, int((time.perf_counter() - started) * 1000))


def _requested_model(body: bytes) -> str:
    """The model named in the client request, used when no response names one.

    Empty rather than None: `request_logs.model` is NOT NULL, and an error
    attempt that never got a response still belongs in the log.
    """
    try:
        payload = json.loads(body)
    except (ValueError, UnicodeDecodeError):
        return ""
    if not isinstance(payload, dict):
        return ""
    model = payload.get("model")
    return model if isinstance(model, str) else ""


def _upstream_request_id(headers: Mapping[str, str]) -> str:
    for name in ("request-id", "x-request-id"):
        value = headers.get(name)
        if value:
            return value
    return str(uuid.uuid4())


def _error_message(body: bytes) -> str | None:
    """The upstream's own error text, kept short enough to store inline."""
    text: str | None = None
    try:
        payload = json.loads(body)
    except (ValueError, UnicodeDecodeError):
        payload = None
    if isinstance(payload, dict):
        error = payload.get("error")
        if isinstance(error, dict):
            message = error.get("message")
            if isinstance(message, str):
                text = message
    if text is None:
        text = body.decode("utf-8", errors="replace")
    text = text.strip()
    if not text:
        return None
    return text[:_ERROR_MESSAGE_MAX_CHARS]


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

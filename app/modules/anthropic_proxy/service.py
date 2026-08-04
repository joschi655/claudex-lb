from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from math import isfinite
from typing import Any

import aiohttp
from starlette.responses import Response, StreamingResponse

from app.core.anthropic.upstream import (
    ANTHROPIC_API_BASE,
    AnthropicUpstreamResponse,
    build_upstream_headers,
    filter_response_headers,
    open_messages,
)
from app.core.anthropic.usage_headers import AnthropicRateLimit, parse_rate_limits, parse_reset_at
from app.core.balancer.types import UpstreamError
from app.core.config.settings import get_settings
from app.core.config.settings_cache import get_settings_cache
from app.core.crypto import TokenEncryptor
from app.core.exceptions import ProxyModelNotAllowed
from app.core.providers import PROVIDER_ANTHROPIC
from app.core.utils.request_id import ensure_request_id
from app.db.models import Account
from app.modules.anthropic_proxy.schemas import anthropic_error_body, error_type_for_status
from app.modules.api_keys.service import (
    API_KEY_USAGE_RESERVATION_MAX_TOKEN_BUDGET,
    ApiKeyData,
    ApiKeyInvalidError,
    ApiKeyRateLimitExceededError,
    ApiKeyRequestUsageBudget,
    ApiKeysService,
)
from app.modules.proxy._service.support import _request_log_useragent_fields
from app.modules.proxy.account_cache import get_account_selection_cache
from app.modules.proxy.load_balancer import LoadBalancer
from app.modules.proxy.repo_bundle import ProxyRepoFactory
from app.modules.proxy.request_policy import validate_model_access
from app.modules.proxy.service import _routing_strategy as resolve_routing_strategy

logger = logging.getLogger(__name__)

_MAX_ACCOUNT_ATTEMPTS = 3
_STREAM_CHUNK_SIZE = 8192
_SSE_CONTENT_TYPE = "text/event-stream"
_SSE_USAGE_BUFFER_LIMIT = 1024 * 1024
_REVOCATION_MARKERS = ("api key has been revoked", "api key is revoked", "expired api key")
_USAGE_WRITE_MIN_INTERVAL_SECONDS = 60.0


@dataclass(frozen=True, slots=True)
class _RequestMetadata:
    model: str
    max_tokens: int | None


@dataclass(slots=True)
class _TokenUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    cached_input_tokens: int = 0


@dataclass(frozen=True, slots=True)
class _Reservation:
    reservation_id: str


class _SseUsageParser:
    def __init__(self) -> None:
        self.usage = _TokenUsage()
        self.error_code: str | None = None
        self.error_message: str | None = None
        self._buffer = b""

    def feed(self, chunk: bytes) -> None:
        self._buffer += chunk
        while True:
            delimiters = (
                (position, delimiter)
                for delimiter in (b"\n\n", b"\r\n\r\n")
                if (position := self._buffer.find(delimiter)) >= 0
            )
            match = min(delimiters, default=None, key=lambda item: item[0])
            if match is None:
                break
            position, delimiter = match
            block = self._buffer[:position]
            self._buffer = self._buffer[position + len(delimiter) :]
            event_name: bytes | None = None
            data_lines: list[bytes] = []
            for line in block.splitlines():
                if line.startswith(b"event:"):
                    event_name = line[6:].strip()
                elif line.startswith(b"data:"):
                    data_lines.append(line[5:].strip())
            payload = b"\n".join(data_lines)
            data: Any = None
            if payload and payload != b"[DONE]":
                try:
                    data = json.loads(payload)
                except (json.JSONDecodeError, UnicodeDecodeError):
                    pass
            if event_name == b"error":
                self.error_code = "api_error"
                self.error_message = "Anthropic stream returned an error event"
                error = data.get("error") if isinstance(data, dict) else None
                if isinstance(error, dict):
                    error_type = error.get("type")
                    message = error.get("message")
                    if isinstance(error_type, str) and error_type:
                        self.error_code = error_type
                    if isinstance(message, str) and message:
                        self.error_message = message
            elif isinstance(data, dict):
                _merge_stream_usage(self.usage, data)
        if len(self._buffer) > _SSE_USAGE_BUFFER_LIMIT:
            self._buffer = b""


class AnthropicProxyService:
    def __init__(self, load_balancer: LoadBalancer, repo_factory: ProxyRepoFactory | None = None, **_: Any) -> None:
        self._load_balancer = load_balancer
        self._repo_factory = repo_factory
        self._encryptor = TokenEncryptor()
        self._usage_tasks: set[asyncio.Task[None]] = set()
        self._usage_write_state: dict[tuple[str, str], float] = {}

    async def relay(
        self,
        *,
        upstream_path: str,
        client_headers: Mapping[str, str],
        body: bytes,
        api_key: ApiKeyData | None = None,
        client_ip: str | None = None,
    ) -> Response:
        started = time.monotonic()
        request_id = ensure_request_id(client_headers.get("x-request-id") or client_headers.get("request-id"))
        try:
            metadata = _parse_request_metadata(body)
        except ValueError as exc:
            return _anthropic_error_response(400, str(exc))

        policy_error = _validate_client_key_policy(api_key, metadata.model)
        if policy_error is not None:
            await self._write_log(
                request_id=request_id,
                account=None,
                api_key=api_key,
                metadata=metadata,
                usage=_TokenUsage(),
                started=started,
                status="error",
                error_code="model_not_allowed",
                error_message=policy_error,
                client_headers=client_headers,
                client_ip=client_ip,
            )
            return _anthropic_error_response(403, policy_error)

        if _has_applicable_cost_limit(api_key, metadata.model):
            cost_limit_error = (
                "Claude requests cannot use an API key with an applicable cost_usd limit "
                "because Anthropic pricing is unavailable"
            )
            await self._write_log(
                request_id=request_id,
                account=None,
                api_key=api_key,
                metadata=metadata,
                usage=_TokenUsage(),
                started=started,
                status="error",
                error_code="cost_limit_unavailable",
                error_message=cost_limit_error,
                client_headers=client_headers,
                client_ip=client_ip,
            )
            return _anthropic_error_response(403, cost_limit_error)

        reservation_or_response = await self._reserve(api_key, metadata, body, upstream_path=upstream_path)
        if isinstance(reservation_or_response, Response):
            return reservation_or_response
        reservation = reservation_or_response

        try:
            settings = await get_settings_cache().get()
            routing_strategy = resolve_routing_strategy(settings)
            scoped_account_ids = _scoped_account_ids(api_key)
        except BaseException:
            await self._settle(reservation, metadata.model, _TokenUsage(), success=False)
            raise
        if routing_strategy == "single_account":
            selected_account_id = (settings.single_account_id or "").strip()
            if not selected_account_id or (
                scoped_account_ids is not None and selected_account_id not in scoped_account_ids
            ):
                return await self._terminal_error(
                    status_code=429,
                    message="Configured Claude account is unavailable for this API key",
                    request_id=request_id,
                    account=None,
                    api_key=api_key,
                    reservation=reservation,
                    metadata=metadata,
                    usage=_TokenUsage(),
                    started=started,
                    client_headers=client_headers,
                    client_ip=client_ip,
                    error_code="no_available_accounts",
                )
            scoped_account_ids = {selected_account_id}

        url = f"{ANTHROPIC_API_BASE}{upstream_path}"
        tried: set[str] = set()
        last_error: tuple[int, bytes, list[tuple[str, str]], Account | None, str] | None = None

        try:
            for _ in range(_MAX_ACCOUNT_ATTEMPTS):
                selection = await self._load_balancer.select_account(
                    provider=PROVIDER_ANTHROPIC,
                    account_ids=scoped_account_ids,
                    exclude_account_ids=tried,
                    routing_strategy=routing_strategy,
                    model=metadata.model,
                )
                account = selection.account
                if account is None:
                    break
                tried.add(account.id)
                credential = self._encryptor.decrypt(account.access_token_encrypted)
                headers = build_upstream_headers(client_headers, credential)
                try:
                    upstream = await open_messages(
                        url,
                        body=body,
                        headers=headers,
                        idle_timeout_seconds=get_settings().stream_idle_timeout_seconds,
                    )
                except asyncio.CancelledError:
                    raise
                except (aiohttp.ClientError, asyncio.TimeoutError, OSError) as exc:
                    await self._load_balancer.record_error(account)
                    last_error = (
                        503,
                        anthropic_error_body("overloaded_error", "Unable to connect to Anthropic"),
                        [],
                        account,
                        type(exc).__name__,
                    )
                    await self._write_failed_attempt(
                        last_error=last_error,
                        request_id=request_id,
                        api_key=api_key,
                        metadata=metadata,
                        started=started,
                        client_headers=client_headers,
                        client_ip=client_ip,
                    )
                    continue

                status = upstream.status
                response_headers = dict(upstream.headers)
                self._ingest_rate_limit_headers(account.id, response_headers)

                if status < 300:
                    content_type = _response_header(response_headers, "content-type") or ""
                    if _SSE_CONTENT_TYPE in content_type.lower():
                        iterator = upstream.aiter_chunked(_STREAM_CHUNK_SIZE).__aiter__()
                        try:
                            first_chunk = await _first_non_empty_chunk(iterator)
                        except asyncio.CancelledError:
                            await upstream.aclose()
                            raise
                        except (aiohttp.ClientError, asyncio.TimeoutError, OSError, StopAsyncIteration) as exc:
                            await upstream.aclose()
                            await self._load_balancer.record_error(account)
                            last_error = (
                                503,
                                anthropic_error_body("overloaded_error", "Anthropic stream ended before data"),
                                [],
                                account,
                                type(exc).__name__,
                            )
                            await self._write_failed_attempt(
                                last_error=last_error,
                                request_id=request_id,
                                api_key=api_key,
                                metadata=metadata,
                                started=started,
                                client_headers=client_headers,
                                client_ip=client_ip,
                            )
                            continue
                        await self._load_balancer.record_success(account)
                        return StreamingResponse(
                            self._stream_with_settlement(
                                first_chunk=first_chunk,
                                iterator=iterator,
                                upstream=upstream,
                                request_id=request_id,
                                account=account,
                                api_key=api_key,
                                reservation=reservation,
                                metadata=metadata,
                                started=started,
                                client_headers=client_headers,
                                client_ip=client_ip,
                            ),
                            status_code=status,
                            headers=dict(filter_response_headers(response_headers)),
                            media_type=content_type,
                        )

                    try:
                        response_body = await upstream.read()
                    except asyncio.CancelledError:
                        await upstream.aclose()
                        raise
                    except (aiohttp.ClientError, asyncio.TimeoutError, OSError) as exc:
                        await upstream.aclose()
                        await self._load_balancer.record_error(account)
                        last_error = (
                            503,
                            anthropic_error_body("overloaded_error", "Anthropic response ended before data"),
                            [],
                            account,
                            type(exc).__name__,
                        )
                        await self._write_failed_attempt(
                            last_error=last_error,
                            request_id=request_id,
                            api_key=api_key,
                            metadata=metadata,
                            started=started,
                            client_headers=client_headers,
                            client_ip=client_ip,
                        )
                        continue
                    await upstream.aclose()
                    await self._load_balancer.record_success(account)
                    usage = _parse_json_usage(response_body, count_tokens=upstream_path.endswith("/count_tokens"))
                    await self._settle(reservation, metadata.model, usage, success=True)
                    await self._write_log(
                        request_id=request_id,
                        account=account,
                        api_key=api_key,
                        metadata=metadata,
                        usage=usage,
                        started=started,
                        status="success",
                        error_code=None,
                        error_message=None,
                        client_headers=client_headers,
                        client_ip=client_ip,
                    )
                    return Response(
                        content=response_body,
                        status_code=status,
                        headers=dict(filter_response_headers(response_headers)),
                    )

                try:
                    error_body = await upstream.read()
                except asyncio.CancelledError:
                    await upstream.aclose()
                    raise
                except (aiohttp.ClientError, asyncio.TimeoutError, OSError) as exc:
                    await upstream.aclose()
                    await self._load_balancer.record_error(account)
                    last_error = (
                        503,
                        anthropic_error_body("overloaded_error", "Anthropic error response ended before data"),
                        [],
                        account,
                        type(exc).__name__,
                    )
                    await self._write_failed_attempt(
                        last_error=last_error,
                        request_id=request_id,
                        api_key=api_key,
                        metadata=metadata,
                        started=started,
                        client_headers=client_headers,
                        client_ip=client_ip,
                    )
                    continue
                await upstream.aclose()
                filtered_headers = filter_response_headers(response_headers)
                if status == 401:
                    await self._load_balancer.mark_permanent_failure(account, "account_auth_invalidated")
                    last_error = (status, error_body, filtered_headers, account, "account_auth_invalidated")
                    await self._write_failed_attempt(
                        last_error=last_error,
                        request_id=request_id,
                        api_key=api_key,
                        metadata=metadata,
                        started=started,
                        client_headers=client_headers,
                        client_ip=client_ip,
                    )
                    continue
                if status == 429:
                    await self._load_balancer.mark_rate_limit(account, _rate_limit_error(response_headers))
                    last_error = (status, error_body, filtered_headers, account, "rate_limit_error")
                    await self._write_failed_attempt(
                        last_error=last_error,
                        request_id=request_id,
                        api_key=api_key,
                        metadata=metadata,
                        started=started,
                        client_headers=client_headers,
                        client_ip=client_ip,
                    )
                    continue
                if status == 403 and _looks_like_revocation(error_body):
                    await self._load_balancer.mark_permanent_failure(account, "account_auth_invalidated")
                    last_error = (status, error_body, filtered_headers, account, "account_auth_invalidated")
                    await self._write_failed_attempt(
                        last_error=last_error,
                        request_id=request_id,
                        api_key=api_key,
                        metadata=metadata,
                        started=started,
                        client_headers=client_headers,
                        client_ip=client_ip,
                    )
                    continue
                if 400 <= status < 500:
                    await self._settle(reservation, metadata.model, _TokenUsage(), success=False)
                    await self._write_log(
                        request_id=request_id,
                        account=account,
                        api_key=api_key,
                        metadata=metadata,
                        usage=_TokenUsage(),
                        started=started,
                        status="error",
                        error_code=error_type_for_status(status),
                        error_message=_error_message(error_body),
                        client_headers=client_headers,
                        client_ip=client_ip,
                        upstream_status_code=status,
                    )
                    return _passthrough_response(status, error_body, filtered_headers)
                await self._load_balancer.record_error(account)
                last_error = (status, error_body, filtered_headers, account, "upstream_error")
                await self._write_failed_attempt(
                    last_error=last_error,
                    request_id=request_id,
                    api_key=api_key,
                    metadata=metadata,
                    started=started,
                    client_headers=client_headers,
                    client_ip=client_ip,
                )

            if last_error is not None:
                status, error_body, headers, _, _ = last_error
                await self._settle(reservation, metadata.model, _TokenUsage(), success=False)
                return _passthrough_response(status, error_body, headers)
            return await self._terminal_error(
                status_code=429,
                message=selection.error_message or "No Claude API-key account is currently available",
                request_id=request_id,
                account=None,
                api_key=api_key,
                reservation=reservation,
                metadata=metadata,
                usage=_TokenUsage(),
                started=started,
                client_headers=client_headers,
                client_ip=client_ip,
                error_code="no_available_accounts",
            )
        except asyncio.CancelledError:
            await self._settle(reservation, metadata.model, _TokenUsage(), success=False)
            raise
        except BaseException:
            await self._settle(reservation, metadata.model, _TokenUsage(), success=False)
            raise

    async def _reserve(
        self,
        api_key: ApiKeyData | None,
        metadata: _RequestMetadata,
        body: bytes,
        *,
        upstream_path: str,
    ) -> _Reservation | Response | None:
        if api_key is None or self._repo_factory is None:
            return None
        try:
            async with self._repo_factory() as repos:
                reservation = await ApiKeysService(repos.api_keys).enforce_limits_for_request(
                    api_key.id,
                    request_model=metadata.model,
                    request_usage_budget=ApiKeyRequestUsageBudget(
                        input_tokens=min(len(body), API_KEY_USAGE_RESERVATION_MAX_TOKEN_BUDGET),
                        output_tokens=0 if upstream_path == "/v1/messages/count_tokens" else metadata.max_tokens,
                    ),
                )
            return _Reservation(reservation.reservation_id)
        except ApiKeyRateLimitExceededError as exc:
            retry_after = max(
                1,
                int((exc.reset_at - datetime.now(timezone.utc).replace(tzinfo=None)).total_seconds()),
            )
            return _anthropic_error_response(
                429,
                str(exc),
                headers={"retry-after": str(retry_after)},
            )
        except ApiKeyInvalidError as exc:
            return _anthropic_error_response(401, str(exc))

    async def _settle(
        self,
        reservation: _Reservation | None,
        model: str,
        usage: _TokenUsage,
        *,
        success: bool,
    ) -> None:
        if reservation is None or self._repo_factory is None:
            return
        try:
            async with self._repo_factory() as repos:
                service = ApiKeysService(repos.api_keys)
                if success:
                    await service.finalize_usage_reservation(
                        reservation.reservation_id,
                        model=model,
                        input_tokens=usage.input_tokens,
                        output_tokens=usage.output_tokens,
                        cached_input_tokens=usage.cached_input_tokens,
                        cost_microdollars=0,
                    )
                else:
                    await service.fail_usage_reservation(
                        reservation.reservation_id,
                        model=model,
                        input_tokens=usage.input_tokens,
                        output_tokens=usage.output_tokens,
                        cached_input_tokens=usage.cached_input_tokens,
                    )
        except Exception:
            logger.exception("Failed to settle Anthropic API-key usage reservation")

    async def _write_log(
        self,
        *,
        request_id: str,
        account: Account | None,
        api_key: ApiKeyData | None,
        metadata: _RequestMetadata,
        usage: _TokenUsage,
        started: float,
        status: str,
        error_code: str | None,
        error_message: str | None,
        client_headers: Mapping[str, str],
        client_ip: str | None,
        upstream_status_code: int | None = None,
    ) -> None:
        if self._repo_factory is None:
            return
        useragent, useragent_group = _request_log_useragent_fields(client_headers)
        try:
            async with self._repo_factory() as repos:
                await repos.request_logs.add_log(
                    account_id=account.id if account is not None else None,
                    api_key_id=api_key.id if api_key is not None else None,
                    request_id=request_id,
                    provider=PROVIDER_ANTHROPIC,
                    model=metadata.model or "unknown",
                    input_tokens=usage.input_tokens,
                    output_tokens=usage.output_tokens,
                    cached_input_tokens=usage.cached_input_tokens,
                    latency_ms=int((time.monotonic() - started) * 1000),
                    status=status,
                    error_code=error_code,
                    error_message=error_message,
                    transport="anthropic_http",
                    useragent=useragent,
                    useragent_group=useragent_group,
                    client_ip=client_ip,
                    upstream_status_code=upstream_status_code,
                )
        except Exception:
            logger.exception("Failed to write Anthropic request log request_id=%s", request_id)

    async def _write_failed_attempt(
        self,
        *,
        last_error: tuple[int, bytes, list[tuple[str, str]], Account | None, str],
        request_id: str,
        api_key: ApiKeyData | None,
        metadata: _RequestMetadata,
        started: float,
        client_headers: Mapping[str, str],
        client_ip: str | None,
    ) -> None:
        status, error_body, _, account, error_code = last_error
        await self._write_log(
            request_id=request_id,
            account=account,
            api_key=api_key,
            metadata=metadata,
            usage=_TokenUsage(),
            started=started,
            status="error",
            error_code=error_code,
            error_message=_error_message(error_body),
            client_headers=client_headers,
            client_ip=client_ip,
            upstream_status_code=status,
        )

    async def _terminal_error(
        self,
        *,
        status_code: int,
        message: str,
        request_id: str,
        account: Account | None,
        api_key: ApiKeyData | None,
        reservation: _Reservation | None,
        metadata: _RequestMetadata,
        usage: _TokenUsage,
        started: float,
        client_headers: Mapping[str, str],
        client_ip: str | None,
        error_code: str,
    ) -> Response:
        await self._settle(reservation, metadata.model, usage, success=False)
        await self._write_log(
            request_id=request_id,
            account=account,
            api_key=api_key,
            metadata=metadata,
            usage=usage,
            started=started,
            status="error",
            error_code=error_code,
            error_message=message,
            client_headers=client_headers,
            client_ip=client_ip,
            upstream_status_code=status_code,
        )
        headers = {"retry-after": "30"} if status_code == 429 else None
        return _anthropic_error_response(status_code, message, headers=headers)

    async def _stream_with_settlement(
        self,
        *,
        first_chunk: bytes,
        iterator: AsyncIterator[bytes],
        upstream: AnthropicUpstreamResponse,
        request_id: str,
        account: Account,
        api_key: ApiKeyData | None,
        reservation: _Reservation | None,
        metadata: _RequestMetadata,
        started: float,
        client_headers: Mapping[str, str],
        client_ip: str | None,
    ) -> AsyncIterator[bytes]:
        parser = _SseUsageParser()
        succeeded = False
        error_code: str | None = None
        error_message: str | None = None
        try:
            parser.feed(first_chunk)
            yield first_chunk
            async for chunk in iterator:
                parser.feed(chunk)
                yield chunk
            if parser.error_code is None:
                succeeded = True
            else:
                error_code = parser.error_code
                error_message = parser.error_message
                await self._load_balancer.record_error(account)
        except asyncio.CancelledError:
            error_code = "client_disconnected"
            error_message = "Client disconnected during Anthropic stream"
            raise
        except (aiohttp.ClientError, asyncio.TimeoutError, OSError) as exc:
            error_code = "stream_interrupted"
            error_message = str(exc) or type(exc).__name__
            await self._load_balancer.record_error(account)
            raise
        except BaseException as exc:
            error_code = "stream_interrupted"
            error_message = str(exc) or type(exc).__name__
            raise
        finally:
            try:
                await upstream.aclose()
            finally:
                await self._settle(reservation, metadata.model, parser.usage, success=succeeded)
                await self._write_log(
                    request_id=request_id,
                    account=account,
                    api_key=api_key,
                    metadata=metadata,
                    usage=parser.usage,
                    started=started,
                    status="success" if succeeded else "error",
                    error_code=error_code,
                    error_message=error_message,
                    client_headers=client_headers,
                    client_ip=client_ip,
                    upstream_status_code=200 if succeeded else None,
                )

    def _ingest_rate_limit_headers(self, account_id: str, headers: Mapping[str, str]) -> None:
        for snapshot in parse_rate_limits(headers):
            key = (account_id, snapshot.quota_key)
            now = time.monotonic()
            if now - self._usage_write_state.get(key, 0.0) < _USAGE_WRITE_MIN_INTERVAL_SECONDS:
                continue
            self._usage_write_state[key] = now
            task = asyncio.create_task(self._write_rate_limit(account_id, snapshot))
            self._usage_tasks.add(task)
            task.add_done_callback(self._usage_tasks.discard)

    async def _write_rate_limit(self, account_id: str, snapshot: AnthropicRateLimit) -> None:
        if self._repo_factory is None:
            return
        try:
            async with self._repo_factory() as repos:
                await repos.additional_usage.add_entry(
                    account_id,
                    quota_key=snapshot.quota_key,
                    limit_name=snapshot.limit_name,
                    metered_feature=snapshot.quota_key,
                    window="primary",
                    used_percent=snapshot.used_percent,
                    reset_at=snapshot.reset_at,
                )
            get_account_selection_cache().invalidate()
        except Exception:
            logger.exception("Failed to persist Anthropic rate limit account_id=%s", account_id)

    async def drain_persistence_tasks(self, timeout_seconds: float) -> bool:
        """Await detached Anthropic rate-limit snapshot writes."""
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout_seconds
        while True:
            pending = {task for task in self._usage_tasks if not task.done()}
            if not pending:
                await asyncio.sleep(0)
                if not any(not task.done() for task in self._usage_tasks):
                    return True
                continue
            remaining = deadline - loop.time()
            if remaining <= 0:
                for task in pending:
                    logger.warning("Anthropic persistence task did not drain before shutdown: %s", task.get_name())
                return False
            _, still_pending = await asyncio.wait(pending, timeout=remaining)
            if still_pending:
                for task in still_pending:
                    logger.warning("Anthropic persistence task did not drain before shutdown: %s", task.get_name())
                return False


def _parse_request_metadata(body: bytes) -> _RequestMetadata:
    try:
        payload = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ValueError("Request body must be a JSON object") from exc
    if not isinstance(payload, dict):
        raise ValueError("Request body must be a JSON object")
    model = payload.get("model")
    if not isinstance(model, str) or not model.strip():
        raise ValueError("Request body must include a model")
    max_tokens_raw = payload.get("max_tokens")
    max_tokens = max_tokens_raw if isinstance(max_tokens_raw, int) and not isinstance(max_tokens_raw, bool) else None
    return _RequestMetadata(model=model.strip(), max_tokens=max_tokens)


def _validate_client_key_policy(api_key: ApiKeyData | None, model: str) -> str | None:
    if api_key is None:
        return None
    if api_key.enforced_model and api_key.enforced_model != model:
        return f"This API key requires model '{api_key.enforced_model}'"
    try:
        validate_model_access(api_key, model)
    except ProxyModelNotAllowed as exc:
        return exc.message
    return None


def _has_applicable_cost_limit(api_key: ApiKeyData | None, model: str) -> bool:
    if api_key is None:
        return False
    return any(
        limit.limit_type == "cost_usd" and (limit.model_filter is None or limit.model_filter == model)
        for limit in api_key.limits
    )


def _scoped_account_ids(api_key: ApiKeyData | None) -> set[str] | None:
    if api_key is None or not api_key.account_assignment_scope_enabled:
        return None
    return {account_id for account_id in api_key.assigned_account_ids if account_id}


async def _first_non_empty_chunk(iterator: AsyncIterator[bytes]) -> bytes:
    while True:
        chunk = await anext(iterator)
        if chunk:
            return chunk


def _parse_json_usage(body: bytes, *, count_tokens: bool) -> _TokenUsage:
    try:
        payload = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return _TokenUsage()
    if not isinstance(payload, dict):
        return _TokenUsage()
    if count_tokens:
        return _TokenUsage(input_tokens=_non_negative_int(payload.get("input_tokens")))
    raw_usage = payload.get("usage")
    if not isinstance(raw_usage, dict):
        return _TokenUsage()
    return _TokenUsage(
        input_tokens=_non_negative_int(raw_usage.get("input_tokens")),
        output_tokens=_non_negative_int(raw_usage.get("output_tokens")),
        cached_input_tokens=_non_negative_int(raw_usage.get("cache_read_input_tokens")),
    )


def _merge_stream_usage(target: _TokenUsage, event: dict[str, Any]) -> None:
    raw_usage: object | None = event.get("usage")
    message = event.get("message")
    if isinstance(message, dict) and isinstance(message.get("usage"), dict):
        raw_usage = message["usage"]
    if not isinstance(raw_usage, dict):
        return
    target.input_tokens = max(target.input_tokens, _non_negative_int(raw_usage.get("input_tokens")))
    target.output_tokens = max(target.output_tokens, _non_negative_int(raw_usage.get("output_tokens")))
    target.cached_input_tokens = max(
        target.cached_input_tokens,
        _non_negative_int(raw_usage.get("cache_read_input_tokens")),
    )


def _non_negative_int(value: object) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0


def _rate_limit_error(headers: Mapping[str, str]) -> UpstreamError:
    error: UpstreamError = {"message": "Anthropic rate limit reached"}
    lowered = {key.lower(): value for key, value in headers.items()}
    retry_after = _retry_after_seconds(lowered.get("retry-after"))
    if retry_after is not None:
        error["resets_in_seconds"] = retry_after
        return error
    exhausted_resets: list[int] = []
    for name, value in lowered.items():
        if not name.startswith("anthropic-ratelimit-") or not name.endswith("-reset"):
            continue
        prefix = name.removesuffix("-reset")
        remaining = _finite_float(lowered.get(f"{prefix}-remaining"))
        reset = parse_reset_at(value)
        if remaining is not None and remaining <= 0 and reset is not None:
            exhausted_resets.append(reset)
    if exhausted_resets:
        error["resets_at"] = max(exhausted_resets)
    return error


def _retry_after_seconds(raw: str | None) -> int | None:
    value = _finite_float(raw)
    return max(0, int(value)) if value is not None else None


def _finite_float(raw: str | None) -> float | None:
    if raw is None:
        return None
    try:
        value = float(raw)
    except ValueError:
        return None
    return value if isfinite(value) else None


def _response_header(headers: Mapping[str, str], name: str) -> str | None:
    normalized = name.lower()
    return next((value for key, value in headers.items() if key.lower() == normalized), None)


def _looks_like_revocation(body: bytes) -> bool:
    text = body.decode("utf-8", errors="replace").lower()
    return any(marker in text for marker in _REVOCATION_MARKERS)


def _error_message(body: bytes) -> str:
    try:
        payload = json.loads(body)
        error = payload.get("error") if isinstance(payload, dict) else None
        message = error.get("message") if isinstance(error, dict) else None
        if isinstance(message, str) and message:
            return message
    except (json.JSONDecodeError, UnicodeDecodeError):
        pass
    return body.decode("utf-8", errors="replace")[:1000] or "Anthropic upstream error"


def _passthrough_response(status: int, body: bytes, headers: list[tuple[str, str]]) -> Response:
    return Response(content=body, status_code=status, headers=dict(headers))


def _anthropic_error_response(status: int, message: str, *, headers: dict[str, str] | None = None) -> Response:
    return Response(
        content=anthropic_error_body(error_type_for_status(status), message),
        status_code=status,
        media_type="application/json",
        headers=headers,
    )

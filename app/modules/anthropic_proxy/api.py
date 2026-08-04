from __future__ import annotations

import logging

from fastapi import APIRouter, Request
from starlette.responses import Response

from app.core.auth.dependencies import validate_proxy_api_key_authorization
from app.core.exceptions import ProxyAuthError
from app.dependencies import get_anthropic_proxy_service_for_app
from app.modules.anthropic_proxy.schemas import anthropic_error_body
from app.modules.api_keys.service import ApiKeyData

logger = logging.getLogger(__name__)

router = APIRouter(tags=["anthropic"])

_MAX_BODY_BYTES = 32 * 1024 * 1024


async def _relay(request: Request, upstream_path: str) -> Response:
    try:
        api_key = await _authenticate(request)
    except ProxyAuthError as exc:
        return Response(
            content=anthropic_error_body("authentication_error", str(exc)),
            status_code=401,
            media_type="application/json",
        )

    try:
        body = await _read_bounded_body(request)
    except ValueError:
        return Response(
            content=anthropic_error_body("invalid_request_error", "Request body too large"),
            status_code=413,
            media_type="application/json",
        )

    service = get_anthropic_proxy_service_for_app(request.app)
    return await service.relay(
        upstream_path=upstream_path,
        client_headers=request.headers,
        body=body,
        api_key=api_key,
        client_ip=request.client.host if request.client else None,
    )


async def _authenticate(request: Request) -> ApiKeyData | None:
    # Claude Code sends the proxy key as either Authorization: Bearer (when
    # ANTHROPIC_AUTH_TOKEN is set) or x-api-key. Synthesize a Bearer string and
    # reuse the shared proxy-API-key validation.
    authorization = request.headers.get("authorization")
    if authorization is None:
        api_key = request.headers.get("x-api-key")
        if api_key:
            authorization = f"Bearer {api_key}"
    return await validate_proxy_api_key_authorization(authorization, request=request)


async def _read_bounded_body(request: Request) -> bytes:
    content_length = request.headers.get("content-length")
    if content_length is not None:
        try:
            if int(content_length) > _MAX_BODY_BYTES:
                raise ValueError("request body too large")
        except ValueError as exc:
            if content_length.isdigit():
                raise
            raise ValueError("invalid content length") from exc
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > _MAX_BODY_BYTES:
            raise ValueError("request body too large")
    return bytes(body)


@router.post("/v1/messages")
async def messages(request: Request) -> Response:
    return await _relay(request, "/v1/messages")


@router.post("/v1/messages/count_tokens")
async def count_tokens(request: Request) -> Response:
    return await _relay(request, "/v1/messages/count_tokens")

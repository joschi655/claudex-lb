from __future__ import annotations

import logging

from fastapi import APIRouter, Request
from starlette.responses import Response

from app.core.auth.dependencies import validate_proxy_api_key_authorization
from app.core.exceptions import ProxyAuthError
from app.dependencies import get_anthropic_proxy_service_for_app
from app.modules.anthropic_proxy.schemas import anthropic_error_body

logger = logging.getLogger(__name__)

# Registered both bare (ANTHROPIC_BASE_URL=http://host:port) and under
# /anthropic (…/anthropic). The bare paths are unclaimed by the OpenAI proxy.
router = APIRouter(tags=["anthropic"])
alias_router = APIRouter(prefix="/anthropic", tags=["anthropic"])

_MAX_BODY_BYTES = 32 * 1024 * 1024


async def _relay(request: Request, upstream_path: str) -> Response:
    try:
        await _authenticate(request)
    except ProxyAuthError as exc:
        return Response(
            content=anthropic_error_body("authentication_error", str(exc)),
            status_code=401,
            media_type="application/json",
        )

    body = await request.body()
    if len(body) > _MAX_BODY_BYTES:
        return Response(
            content=anthropic_error_body("invalid_request_error", "Request body too large"),
            status_code=413,
            media_type="application/json",
        )

    service = get_anthropic_proxy_service_for_app(request.app)
    return await service.relay(upstream_path=upstream_path, client_headers=request.headers, body=body)


async def _authenticate(request: Request) -> None:
    # Claude Code sends the proxy key as either Authorization: Bearer (when
    # ANTHROPIC_AUTH_TOKEN is set) or x-api-key. Synthesize a Bearer string and
    # reuse the shared proxy-API-key validation.
    authorization = request.headers.get("authorization")
    if authorization is None:
        api_key = request.headers.get("x-api-key")
        if api_key:
            authorization = f"Bearer {api_key}"
    await validate_proxy_api_key_authorization(authorization, request=request)


@router.post("/v1/messages")
async def messages(request: Request) -> Response:
    return await _relay(request, "/v1/messages")


@router.post("/v1/messages/count_tokens")
async def count_tokens(request: Request) -> Response:
    return await _relay(request, "/v1/messages/count_tokens")


@alias_router.post("/v1/messages")
async def messages_alias(request: Request) -> Response:
    return await _relay(request, "/v1/messages")


@alias_router.post("/v1/messages/count_tokens")
async def count_tokens_alias(request: Request) -> Response:
    return await _relay(request, "/v1/messages/count_tokens")

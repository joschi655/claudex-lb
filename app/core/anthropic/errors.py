from __future__ import annotations

import json
from typing import TypedDict

_MESSAGES_PATHS = frozenset({"/v1/messages", "/v1/messages/count_tokens"})


class AnthropicErrorDetail(TypedDict):
    type: str
    message: str


class AnthropicErrorEnvelope(TypedDict):
    type: str
    error: AnthropicErrorDetail


def is_anthropic_messages_path(path: str) -> bool:
    return path.rstrip("/") in _MESSAGES_PATHS


def anthropic_error(error_type: str, message: str) -> AnthropicErrorEnvelope:
    return {
        "type": "error",
        "error": {"type": error_type, "message": message},
    }


def anthropic_error_body(error_type: str, message: str) -> bytes:
    return json.dumps(anthropic_error(error_type, message)).encode("utf-8")


def error_type_for_status(status: int) -> str:
    if status == 400:
        return "invalid_request_error"
    if status == 401:
        return "authentication_error"
    if status == 403:
        return "permission_error"
    if status == 404:
        return "not_found_error"
    if status == 413:
        return "request_too_large"
    if status == 429:
        return "rate_limit_error"
    if status in (502, 503, 529):
        return "overloaded_error"
    return "api_error"


def anthropic_error_for_status(status: int, message: str) -> AnthropicErrorEnvelope:
    return anthropic_error(error_type_for_status(status), message)


__all__ = [
    "AnthropicErrorDetail",
    "AnthropicErrorEnvelope",
    "anthropic_error",
    "anthropic_error_body",
    "anthropic_error_for_status",
    "error_type_for_status",
    "is_anthropic_messages_path",
]

from __future__ import annotations

import json

# Anthropic error envelope: {"type": "error", "error": {"type": ..., "message": ...}}.
# See https://docs.anthropic.com/en/api/errors.


def anthropic_error_body(error_type: str, message: str) -> bytes:
    return json.dumps({"type": "error", "error": {"type": error_type, "message": message}}).encode("utf-8")


# Maps an HTTP status the relay itself originates to the Anthropic error type.
ERROR_TYPE_BY_STATUS = {
    401: "authentication_error",
    403: "permission_error",
    429: "rate_limit_error",
    500: "api_error",
    503: "overloaded_error",
}


def error_type_for_status(status: int) -> str:
    return ERROR_TYPE_BY_STATUS.get(status, "api_error")

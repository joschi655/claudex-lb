"""The Claude Code fingerprint the pool's OAuth accounts expect upstream.

Anthropic routes OAuth-scoped traffic on the calling client's identity, and a
request that spends a Claude Code token without presenting as Claude Code draws
intermittent 5xx rather than a clean rejection. The credential kind is known only
to the relay -- a caller holding a proxy API key cannot tell whether an OAuth
subscription account or a static console key will serve it -- so the fingerprint
is applied here rather than by each client.

Two surfaces share these constants: the relay (rewriting a caller's request) and
the warmup ping (synthesizing one from nothing). They must agree, or a warmup
would open a five-hour window under a different identity than the traffic that
follows it.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

# The leading system block is the load-bearing part of the fingerprint: it is
# what upstream inspects, and the one piece a client cannot fake with headers.
CLAUDE_CODE_SYSTEM_TEXT = "You are Claude Code, Anthropic's official CLI for Claude."

CLAUDE_CODE_BETA = "claude-code-20250219"
CLAUDE_CODE_APP = "cli"

# Pinned rather than detected: there is no Claude Code installation on the proxy
# host to read a version from. A caller that is genuinely Claude Code keeps its
# own version (see ``client_presents_as_claude_code``), so this value is only
# ever sent for a client that had no Claude Code version to begin with.
CLAUDE_CODE_VERSION = "2.1.0"
CLAUDE_CODE_USER_AGENT = f"claude-cli/{CLAUDE_CODE_VERSION} (external, cli)"

_CLAUDE_CODE_PRODUCT_TOKEN = "claude-cli"


def client_presents_as_claude_code(client_headers: Mapping[str, str]) -> bool:
    """Whether the caller's own user-agent is already a Claude Code one.

    Such a caller is left alone: overwriting its user-agent would replace a real
    version with this module's pinned one, which is strictly less accurate.
    """
    for key, value in client_headers.items():
        if key.lower() != "user-agent":
            continue
        stripped = value.strip()
        if not stripped:
            return False
        product = stripped.split(maxsplit=1)[0].split("/", 1)[0]
        return product.strip().lower() == _CLAUDE_CODE_PRODUCT_TOKEN
    return False


def apply_claude_code_identity(body: bytes) -> bytes:
    """Ensure a Messages body opens its ``system`` with the identity block.

    Returns ``body`` unchanged -- the same object, never a re-serialization --
    when the identity is already present, when the payload is not a JSON object,
    or when ``system`` has a shape this cannot safely extend. Upstream is the
    authority on malformed requests; rewriting one here would only turn its 400
    into a different 400.
    """
    try:
        payload = json.loads(body)
    except (ValueError, UnicodeDecodeError):
        return body
    if not isinstance(payload, dict):
        return body

    system: Any = payload.get("system")
    if _already_identified(system):
        return body

    existing = _as_blocks(system)
    if existing is None:
        return body

    payload["system"] = [{"type": "text", "text": CLAUDE_CODE_SYSTEM_TEXT}, *existing]
    return json.dumps(payload).encode()


def _already_identified(system: Any) -> bool:
    if isinstance(system, str):
        return system.strip().startswith(CLAUDE_CODE_SYSTEM_TEXT)
    if isinstance(system, list) and system:
        first = system[0]
        if isinstance(first, dict) and first.get("type") == "text":
            text = first.get("text")
            return isinstance(text, str) and text.strip().startswith(CLAUDE_CODE_SYSTEM_TEXT)
    return False


def _as_blocks(system: Any) -> list[Any] | None:
    """The caller's ``system`` as a block list, or ``None`` if it cannot be one."""
    if system is None:
        return []
    if isinstance(system, str):
        # An empty string is not a valid text block; drop it rather than send one.
        return [{"type": "text", "text": system}] if system.strip() else []
    if isinstance(system, list):
        return system
    return None

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
from dataclasses import dataclass
from typing import Any

# The leading system block is the load-bearing part of the fingerprint: it is
# what upstream inspects, and the one piece a client cannot fake with headers.
CLAUDE_CODE_SYSTEM_TEXT = "You are Claude Code, Anthropic's official CLI for Claude."

# Claude Code does not send its billing attribution as a header; it writes the
# header line into the first ``system`` block and lets upstream lift it out.
# Under a first-party base URL that line carries per-request fields (``cch``, a
# request hash, and ``cc_prev_req``, the previous request id), so the prompt
# prefix differs on every call and no prompt cache can ever be read -- upstream
# re-writes the whole prefix instead, which on a large conversation is the
# difference between a few thousand billed input tokens and several hundred
# thousand. The relay lifts the line back into the header it is written as.
ATTRIBUTION_HEADER = "x-anthropic-billing-header"
_ATTRIBUTION_BLOCK_PREFIX = f"{ATTRIBUTION_HEADER}:"

CLAUDE_CODE_BETA = "claude-code-20250219"
CLAUDE_CODE_APP = "cli"

# Pinned rather than detected: there is no Claude Code installation on the proxy
# host to read a version from. A caller that is genuinely Claude Code keeps its
# own version (see ``client_presents_as_claude_code``), so this value is only
# ever sent for a client that had no Claude Code version to begin with.
#
# Keep it a version that real Claude Code clients actually report. Upstream is
# free to treat an unknown build differently, and a synthesized identity that
# names a version nobody runs is the one part of the fingerprint that cannot be
# defended as accurate. Worth re-pinning when the pool's clients move on.
CLAUDE_CODE_VERSION = "2.1.220"
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


@dataclass(frozen=True, slots=True)
class NormalizedRelayRequest:
    """A Messages body ready for an OAuth upstream leg.

    ``attribution`` is the billing metadata lifted out of the body, to be sent
    as ``ATTRIBUTION_HEADER``. It is ``None`` when the caller sent none.
    """

    body: bytes
    attribution: str | None = None


def normalize_claude_code_request(body: bytes) -> NormalizedRelayRequest:
    """Open a Messages body's ``system`` with the identity block, cache-safely.

    Two transforms, in order: lift Claude Code's billing attribution out of the
    leading ``system`` block, then ensure ``system`` begins with the identity
    text. The lift comes first because the attribution line is what displaces
    the identity block in a real Claude Code request.

    Returns ``body`` unchanged -- the same object, never a re-serialization --
    when there is nothing to do, when the payload is not a JSON object, or when
    ``system`` has a shape this cannot safely extend. Upstream is the authority
    on malformed requests; rewriting one here would only turn its 400 into a
    different 400.
    """
    try:
        payload = json.loads(body)
    except (ValueError, UnicodeDecodeError):
        return NormalizedRelayRequest(body)
    if not isinstance(payload, dict):
        return NormalizedRelayRequest(body)

    attribution, system = _lift_attribution(payload.get("system"))
    if attribution is None and _already_identified(system):
        return NormalizedRelayRequest(body)

    existing = _as_blocks(system)
    if existing is None:
        return NormalizedRelayRequest(body)

    if _already_identified(system):
        payload["system"] = existing
    else:
        payload["system"] = [{"type": "text", "text": CLAUDE_CODE_SYSTEM_TEXT}, *existing]
    return NormalizedRelayRequest(json.dumps(payload).encode(), attribution)


def _lift_attribution(system: Any) -> tuple[str | None, Any]:
    """Split the attribution line off ``system``, if it opens with one.

    Returns the header value and the remaining ``system``. A block carrying a
    ``cache_control`` breakpoint is left in place: removing it would move the
    caller's cache boundary, which is the very thing this protects.
    """
    if not isinstance(system, list) or not system:
        return None, system
    first = system[0]
    if not isinstance(first, dict) or first.get("type") != "text" or "cache_control" in first:
        return None, system
    text = first.get("text")
    if not isinstance(text, str):
        return None, system
    stripped = text.strip()
    if not stripped.lower().startswith(_ATTRIBUTION_BLOCK_PREFIX):
        return None, system
    return stripped[len(_ATTRIBUTION_BLOCK_PREFIX) :].strip(), system[1:]


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

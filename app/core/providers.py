"""Account provider discriminators.

An account's ``provider`` names the upstream vendor whose credentials it
holds. Selection, refresh, and per-account schedulers are provider-scoped:
code paths built for one provider must never touch another provider's
accounts or send its credentials to the wrong upstream.
"""

from __future__ import annotations

PROVIDER_OPENAI = "openai"
PROVIDER_ANTHROPIC = "anthropic"


def is_anthropic_provider(provider: str) -> bool:
    return provider == PROVIDER_ANTHROPIC

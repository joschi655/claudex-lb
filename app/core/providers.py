"""Account provider discriminators.

An account's ``provider`` names the upstream vendor whose credentials it
holds. Selection, refresh, and per-account schedulers are provider-scoped:
code paths built for one provider must never touch another provider's
accounts or send its credentials to the wrong upstream.
"""

from __future__ import annotations

from typing import Literal, TypeAlias, cast

PROVIDER_OPENAI = "openai"
PROVIDER_ANTHROPIC = "anthropic"
PROVIDER_ALL = "all"

CREDENTIAL_OPENAI_OAUTH = "openai_oauth"
CREDENTIAL_ANTHROPIC_API_KEY = "anthropic_api_key"
CREDENTIAL_LEGACY_ANTHROPIC_OAUTH = "legacy_anthropic_oauth"

AccountProvider: TypeAlias = Literal["openai", "anthropic"]
ProviderScope: TypeAlias = Literal["all", "openai", "anthropic"]
AccountCredentialKind: TypeAlias = Literal[
    "openai_oauth",
    "anthropic_api_key",
    "legacy_anthropic_oauth",
]

SUPPORTED_PROVIDERS = frozenset({PROVIDER_OPENAI, PROVIDER_ANTHROPIC})
SUPPORTED_PROVIDER_SCOPES = frozenset({PROVIDER_ALL, *SUPPORTED_PROVIDERS})
SUPPORTED_CREDENTIAL_KINDS = frozenset(
    {
        CREDENTIAL_OPENAI_OAUTH,
        CREDENTIAL_ANTHROPIC_API_KEY,
        CREDENTIAL_LEGACY_ANTHROPIC_OAUTH,
    }
)


def is_anthropic_provider(provider: str) -> bool:
    return provider == PROVIDER_ANTHROPIC


def is_selectable_anthropic_credential(provider: str, credential_kind: str) -> bool:
    return provider == PROVIDER_ANTHROPIC and credential_kind == CREDENTIAL_ANTHROPIC_API_KEY


def require_account_provider(value: str) -> AccountProvider:
    if value not in SUPPORTED_PROVIDERS:
        raise ValueError(f"Unsupported account provider: {value}")
    return cast(AccountProvider, value)


def require_account_credential_kind(value: str) -> AccountCredentialKind:
    if value not in SUPPORTED_CREDENTIAL_KINDS:
        raise ValueError(f"Unsupported account credential kind: {value}")
    return cast(AccountCredentialKind, value)


def provider_from_scope(scope: ProviderScope) -> AccountProvider | None:
    if scope == PROVIDER_ALL:
        return None
    return require_account_provider(scope)

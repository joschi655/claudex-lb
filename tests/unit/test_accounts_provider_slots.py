"""Provider guards in the account slot/merge helpers.

Accounts must never merge across providers (an OpenAI row holding Anthropic
credentials would send them to the wrong upstream), and the merge field copy
must carry the provider-specific columns.
"""

from __future__ import annotations

import pytest

from app.core.providers import PROVIDER_ANTHROPIC
from app.core.utils.time import utcnow
from app.db.models import Account, AccountStatus
from app.modules.accounts.repository import (
    _apply_account_updates,
    _can_reuse_email_fallback,
    _slot_lock_keys,
)

pytestmark = pytest.mark.unit


def _account(
    account_id: str,
    *,
    provider: str | None = None,
    email: str = "user@example.com",
    access_token_expires_at: int | None = None,
) -> Account:
    return Account(
        id=account_id,
        provider=provider,
        email=email,
        plan_type="plus",
        access_token_encrypted=b"access",
        refresh_token_encrypted=b"refresh",
        id_token_encrypted=None,
        access_token_expires_at=access_token_expires_at,
        last_refresh=utcnow(),
        status=AccountStatus.ACTIVE,
    )


def test_email_fallback_never_crosses_providers():
    existing_openai = _account("openai-1", provider=None)
    incoming_anthropic = _account("anthropic-1", provider=PROVIDER_ANTHROPIC)

    assert _can_reuse_email_fallback(existing_openai, incoming_anthropic) is False
    assert _can_reuse_email_fallback(incoming_anthropic, existing_openai) is False


def test_email_fallback_allows_same_provider():
    existing = _account("anthropic-1", provider=PROVIDER_ANTHROPIC)
    incoming = _account("anthropic-2", provider=PROVIDER_ANTHROPIC)

    assert _can_reuse_email_fallback(existing, incoming) is True


def test_apply_account_updates_carries_provider_columns():
    target = _account("anthropic-1", provider=PROVIDER_ANTHROPIC, access_token_expires_at=1_700_000_000)
    source = _account("anthropic-2", provider=PROVIDER_ANTHROPIC, access_token_expires_at=1_900_000_000)
    source.access_token_encrypted = b"rotated-access"

    _apply_account_updates(target, source)

    assert target.provider == PROVIDER_ANTHROPIC
    assert target.access_token_expires_at == 1_900_000_000
    assert target.access_token_encrypted == b"rotated-access"


def test_slot_lock_keys_for_anthropic_account_key_on_email():
    account = _account("anthropic-1", provider=PROVIDER_ANTHROPIC, email="claude@example.com")

    assert _slot_lock_keys(account) == ("slot-anthropic:claude@example.com",)
    assert _slot_lock_keys(account, preserve_unknown_workspace_duplicates=False) == (
        "slot-anthropic:claude@example.com",
    )

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from app.core.auth.refresh import RefreshError
from app.core.providers import CREDENTIAL_ANTHROPIC_API_KEY, PROVIDER_ANTHROPIC
from app.core.utils.time import utcnow
from app.db.models import Account, AccountStatus
from app.modules.accounts.auth_manager import AuthManager

pytestmark = pytest.mark.unit


def _account() -> Account:
    return Account(
        id="anthropic-api-key",
        provider=PROVIDER_ANTHROPIC,
        credential_kind=CREDENTIAL_ANTHROPIC_API_KEY,
        email="anthropic-api-key@api-key.local",
        plan_type="claude_api",
        access_token_encrypted=b"api-key",
        refresh_token_encrypted=b"placeholder",
        id_token_encrypted=None,
        last_refresh=utcnow(),
        status=AccountStatus.ACTIVE,
    )


@pytest.mark.asyncio
async def test_ensure_fresh_never_refreshes_anthropic_api_key() -> None:
    repo = AsyncMock()
    account = _account()

    result = await AuthManager(repo).ensure_fresh(account, force=True)

    assert result is account
    repo.rotate_tokens.assert_not_awaited()
    repo.update_account_metadata.assert_not_awaited()


@pytest.mark.asyncio
async def test_direct_oauth_refresh_rejects_anthropic_before_repository_access() -> None:
    repo = AsyncMock()
    account = _account()

    with pytest.raises(RefreshError, match="OAuth refresh is not supported") as exc_info:
        await AuthManager(repo).refresh_account(account)

    assert exc_info.value.code == "provider_action_unsupported"
    repo.rotate_tokens.assert_not_awaited()

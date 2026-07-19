from __future__ import annotations

import time
from datetime import datetime
from typing import cast

import pytest

from app.core.anthropic.oauth import ClaudeTokenRefreshResult
from app.core.auth.refresh import RefreshError
from app.core.crypto import TokenEncryptor
from app.core.providers import PROVIDER_ANTHROPIC
from app.core.utils.time import utcnow
from app.db.models import Account, AccountStatus
from app.modules.accounts import auth_manager as auth_manager_module
from app.modules.accounts.auth_manager import (
    AccountsRepositoryPort,
    AuthManager,
    anthropic_token_needs_refresh,
)

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _clear_refresh_state() -> None:
    auth_manager_module._clear_refresh_singleflight_state()


class _AnthropicRepo:
    def __init__(self) -> None:
        self.tokens_payload: dict[str, object] | None = None
        self.status_payload: dict[str, object] | None = None
        self.accounts_by_id: dict[str, Account] = {}

    async def get_by_id(self, account_id: str) -> Account | None:
        return self.accounts_by_id.get(account_id)

    async def get_by_id_fresh(self, account_id: str) -> Account | None:
        return self.accounts_by_id.get(account_id)

    async def update_status(
        self,
        account_id: str,
        status: AccountStatus,
        deactivation_reason: str | None = None,
        reset_at: int | None = None,
        blocked_at: int | None = None,
    ) -> bool:
        self.status_payload = {"account_id": account_id, "status": status}
        return True

    async def update_status_if_current(
        self,
        account_id: str,
        status: AccountStatus,
        deactivation_reason: str | None = None,
        reset_at: int | None = None,
        *,
        expected_status: AccountStatus,
        expected_deactivation_reason: str | None = None,
        expected_reset_at: int | None = None,
        expected_refresh_token_encrypted: bytes | None = None,
    ) -> bool:
        self.status_payload = {
            "account_id": account_id,
            "status": status,
            "deactivation_reason": deactivation_reason,
        }
        return True

    async def rotate_tokens(
        self,
        account_id: str,
        access_token_encrypted: bytes,
        refresh_token_encrypted: bytes,
        id_token_encrypted: bytes | None,
        last_refresh: datetime,
        *,
        expected_refresh_token_encrypted: bytes,
        plan_type: str | None = None,
        email: str | None = None,
        chatgpt_account_id: str | None = None,
        chatgpt_user_id: str | None = None,
        workspace_id: str | None = None,
        workspace_label: str | None = None,
        seat_type: str | None = None,
        access_token_expires_at: int | None = None,
    ) -> bool:
        self.tokens_payload = {
            "account_id": account_id,
            "access_token_encrypted": access_token_encrypted,
            "refresh_token_encrypted": refresh_token_encrypted,
            "id_token_encrypted": id_token_encrypted,
            "plan_type": plan_type,
            "access_token_expires_at": access_token_expires_at,
        }
        return True

    async def update_account_metadata(self, account_id: str, **kwargs: object) -> bool:
        return True

    async def workspace_slot_taken(self, **kwargs: object) -> bool:
        return False


def _make_anthropic_account(
    encryptor: TokenEncryptor,
    *,
    expires_at: int | None,
    refresh_token: str = "sk-ant-ort01-old",
) -> Account:
    return Account(
        id="anthropic-test",
        provider=PROVIDER_ANTHROPIC,
        email="claude@example.com",
        plan_type="claude_max",
        access_token_encrypted=encryptor.encrypt("sk-ant-oat01-old"),
        refresh_token_encrypted=encryptor.encrypt(refresh_token),
        id_token_encrypted=None,
        access_token_expires_at=expires_at,
        last_refresh=utcnow(),
        status=AccountStatus.ACTIVE,
        deactivation_reason=None,
    )


@pytest.mark.asyncio
async def test_expired_anthropic_account_refreshes_and_persists(monkeypatch):
    new_expiry = int(time.time()) + 8 * 3600

    async def _fake_claude_refresh(refresh_token: str, **_kwargs: object) -> ClaudeTokenRefreshResult:
        assert refresh_token == "sk-ant-ort01-old"
        return ClaudeTokenRefreshResult(
            access_token="sk-ant-oat01-new",
            refresh_token="sk-ant-ort01-new",
            expires_at=new_expiry,
            subscription_type="max",
        )

    monkeypatch.setattr(auth_manager_module, "refresh_claude_access_token", _fake_claude_refresh)

    encryptor = TokenEncryptor()
    account = _make_anthropic_account(encryptor, expires_at=int(time.time()) - 60)
    repo = _AnthropicRepo()
    repo.accounts_by_id[account.id] = account
    manager = AuthManager(cast(AccountsRepositoryPort, repo))

    result = await manager.ensure_fresh(account)

    assert repo.tokens_payload is not None
    assert repo.tokens_payload["id_token_encrypted"] is None
    assert repo.tokens_payload["access_token_expires_at"] == new_expiry
    assert repo.tokens_payload["plan_type"] == "claude_max"
    assert encryptor.decrypt(cast(bytes, repo.tokens_payload["access_token_encrypted"])) == "sk-ant-oat01-new"
    assert encryptor.decrypt(cast(bytes, repo.tokens_payload["refresh_token_encrypted"])) == "sk-ant-ort01-new"
    assert result.access_token_expires_at == new_expiry
    assert encryptor.decrypt(result.access_token_encrypted) == "sk-ant-oat01-new"


@pytest.mark.asyncio
async def test_fresh_anthropic_account_skips_refresh(monkeypatch):
    async def _fail_refresh(*_args: object, **_kwargs: object) -> ClaudeTokenRefreshResult:
        raise AssertionError("refresh must not be called for a fresh token")

    monkeypatch.setattr(auth_manager_module, "refresh_claude_access_token", _fail_refresh)

    encryptor = TokenEncryptor()
    account = _make_anthropic_account(encryptor, expires_at=int(time.time()) + 2 * 3600)
    manager = AuthManager(cast(AccountsRepositoryPort, _AnthropicRepo()))

    result = await manager.ensure_fresh(account)
    assert result is account


@pytest.mark.asyncio
async def test_static_anthropic_account_never_refreshes_even_forced(monkeypatch):
    async def _fail_refresh(*_args: object, **_kwargs: object) -> ClaudeTokenRefreshResult:
        raise AssertionError("static credentials must never refresh")

    monkeypatch.setattr(auth_manager_module, "refresh_claude_access_token", _fail_refresh)

    encryptor = TokenEncryptor()
    account = _make_anthropic_account(encryptor, expires_at=None, refresh_token="")
    manager = AuthManager(cast(AccountsRepositoryPort, _AnthropicRepo()))

    result = await manager.ensure_fresh(account, force=True)
    assert result is account


@pytest.mark.asyncio
async def test_invalid_grant_marks_anthropic_account_reauth_required(monkeypatch):
    async def _fake_claude_refresh(*_args: object, **_kwargs: object) -> ClaudeTokenRefreshResult:
        raise RefreshError("invalid_grant", "refresh token dead", True)

    monkeypatch.setattr(auth_manager_module, "refresh_claude_access_token", _fake_claude_refresh)

    encryptor = TokenEncryptor()
    account = _make_anthropic_account(encryptor, expires_at=int(time.time()) - 60)
    repo = _AnthropicRepo()
    repo.accounts_by_id[account.id] = account
    manager = AuthManager(cast(AccountsRepositoryPort, repo))

    with pytest.raises(RefreshError):
        await manager.ensure_fresh(account)

    assert repo.status_payload is not None
    assert repo.status_payload["status"] == AccountStatus.REAUTH_REQUIRED


def test_anthropic_token_needs_refresh_skew():
    now = 1_000_000
    assert anthropic_token_needs_refresh(now + 200, now=now)
    assert anthropic_token_needs_refresh(now + 300, now=now)
    assert not anthropic_token_needs_refresh(now + 301, now=now)
    assert anthropic_token_needs_refresh(now - 10, now=now)

"""How the Anthropic route reads an API key's account assignments.

Contract: openspec/changes/scope-anthropic-relay-to-assigned-accounts/specs/anthropic-provider/spec.md.
"""

from __future__ import annotations

from datetime import UTC, datetime

from app.modules.anthropic_proxy.api import _scoped_account_ids
from app.modules.api_keys.service import ApiKeyData


def _make_key(*, scope_enabled: bool, assigned: list[str]) -> ApiKeyData:
    return ApiKeyData(
        id="key-1",
        name="hermes",
        key_prefix="sk-clb-abc",
        allowed_models=None,
        enforced_model=None,
        enforced_reasoning_effort=None,
        enforced_service_tier=None,
        expires_at=None,
        is_active=True,
        created_at=datetime(2026, 8, 5, tzinfo=UTC),
        last_used_at=None,
        account_assignment_scope_enabled=scope_enabled,
        assigned_account_ids=assigned,
    )


def test_armed_scope_narrows_to_its_assignments():
    key = _make_key(scope_enabled=True, assigned=["anthropic-check24"])

    assert _scoped_account_ids(key) == ["anthropic-check24"]


def test_disarmed_scope_leaves_the_pool_open():
    """Assignments can be edited before the scope is armed; until it is, they are
    a draft, not a restriction."""
    key = _make_key(scope_enabled=False, assigned=["anthropic-check24"])

    assert _scoped_account_ids(key) is None


def test_armed_scope_with_no_assignments_is_not_a_pool_of_nothing():
    """Otherwise a half-finished edit locks the key out of every account."""
    key = _make_key(scope_enabled=True, assigned=[])

    assert _scoped_account_ids(key) is None


def test_blank_assignment_ids_are_dropped():
    key = _make_key(scope_enabled=True, assigned=["", "anthropic-check24", ""])

    assert _scoped_account_ids(key) == ["anthropic-check24"]


def test_no_api_key_means_no_scope():
    """Proxy auth can be disabled entirely; there is no key to read a scope off."""
    assert _scoped_account_ids(None) is None

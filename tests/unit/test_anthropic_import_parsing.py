from __future__ import annotations

import pytest

from app.modules.accounts.anthropic_import import (
    InvalidAnthropicCredentialError,
    looks_like_anthropic_payload,
    parse_anthropic_credential,
    parse_anthropic_credential_bytes,
)


def test_oauth_backup_shape_parses():
    parsed = parse_anthropic_credential(
        {
            "email": "user@example.com",
            "claudeAiOauth": {
                "accessToken": "sk-ant-oat01-abc",
                "refreshToken": "sk-ant-ort01-def",
                "expiresAt": 1_752_900_000_000,
                "scopes": ["user:inference"],
                "subscriptionType": "max",
            },
        }
    )
    assert parsed.email == "user@example.com"
    assert parsed.access_token == "sk-ant-oat01-abc"
    assert parsed.refresh_token == "sk-ant-ort01-def"
    # Milliseconds converted to epoch seconds.
    assert parsed.access_token_expires_at == 1_752_900_000
    assert parsed.plan_type == "claude_max"
    assert parsed.is_static is False


def test_expires_at_in_seconds_is_not_divided():
    parsed = parse_anthropic_credential(
        {
            "email": "user@example.com",
            "claudeAiOauth": {
                "accessToken": "sk-ant-oat01-abc",
                "refreshToken": "sk-ant-ort01-def",
                # Already epoch seconds (non-Claude-Code tooling): dividing by
                # 1000 would misread it as 1970 and force a needless refresh.
                "expiresAt": 1_752_900_000,
            },
        }
    )
    assert parsed.access_token_expires_at == 1_752_900_000


def test_oauth_without_refresh_token_is_static():
    parsed = parse_anthropic_credential(
        {"claudeAiOauth": {"accessToken": "sk-ant-oat01-abc", "expiresAt": 1_752_900_000_000}}
    )
    assert parsed.is_static is True
    assert parsed.refresh_token is None


def test_console_api_key_shape_parses_as_static():
    parsed = parse_anthropic_credential({"email": "console@example.com", "apiKey": "sk-ant-api03-xyz"})
    assert parsed.is_static is True
    assert parsed.refresh_token is None
    assert parsed.access_token_expires_at is None
    assert parsed.plan_type == "claude_console"


def test_missing_access_token_raises():
    with pytest.raises(InvalidAnthropicCredentialError):
        parse_anthropic_credential({"claudeAiOauth": {"refreshToken": "r"}})


def test_non_json_bytes_raise():
    with pytest.raises(InvalidAnthropicCredentialError):
        parse_anthropic_credential_bytes(b"not json")


def test_codex_auth_json_is_not_anthropic_shaped():
    assert not looks_like_anthropic_payload({"tokens": {"id_token": "x"}, "auth_mode": "chatgpt"})
    assert looks_like_anthropic_payload({"claudeAiOauth": {}})
    assert looks_like_anthropic_payload({"apiKey": "sk-ant-api03-xyz"})

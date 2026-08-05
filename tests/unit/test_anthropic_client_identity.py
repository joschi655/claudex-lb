from __future__ import annotations

import json

from app.core.anthropic.client_identity import (
    CLAUDE_CODE_SYSTEM_TEXT,
    apply_claude_code_identity,
    client_presents_as_claude_code,
)

_IDENTITY_BLOCK = {"type": "text", "text": CLAUDE_CODE_SYSTEM_TEXT}


def _system_of(body: bytes):
    return json.loads(body)["system"]


def test_string_system_becomes_block_list_led_by_the_identity():
    body = json.dumps({"model": "claude-sonnet-4-5", "system": "You are Hermes."}).encode()

    result = apply_claude_code_identity(body)

    assert _system_of(result) == [_IDENTITY_BLOCK, {"type": "text", "text": "You are Hermes."}]
    # The rest of the payload survives the round-trip.
    assert json.loads(result)["model"] == "claude-sonnet-4-5"


def test_block_list_system_is_prepended():
    caller_block = {"type": "text", "text": "You are Hermes.", "cache_control": {"type": "ephemeral"}}
    body = json.dumps({"system": [caller_block]}).encode()

    assert _system_of(apply_claude_code_identity(body)) == [_IDENTITY_BLOCK, caller_block]


def test_missing_system_gains_one():
    body = json.dumps({"model": "claude-sonnet-4-5", "messages": []}).encode()

    assert _system_of(apply_claude_code_identity(body)) == [_IDENTITY_BLOCK]


def test_empty_string_system_does_not_produce_an_empty_text_block():
    """An empty text block is rejected upstream, so it is dropped, not forwarded."""
    body = json.dumps({"system": "   "}).encode()

    assert _system_of(apply_claude_code_identity(body)) == [_IDENTITY_BLOCK]


def test_already_identified_body_is_returned_unchanged():
    body = json.dumps({"system": [_IDENTITY_BLOCK, {"type": "text", "text": "…"}]}).encode()

    # Same object: Claude Code's own bytes are never re-serialized.
    assert apply_claude_code_identity(body) is body


def test_already_identified_string_system_is_returned_unchanged():
    body = json.dumps({"system": f"{CLAUDE_CODE_SYSTEM_TEXT}\n\nAnd then some."}).encode()

    assert apply_claude_code_identity(body) is body


def test_transform_is_idempotent():
    body = json.dumps({"system": "You are Hermes."}).encode()

    once = apply_claude_code_identity(body)

    assert apply_claude_code_identity(once) is once


def test_non_json_body_is_passed_through():
    body = b"not json at all"

    assert apply_claude_code_identity(body) is body


def test_non_object_json_body_is_passed_through():
    assert apply_claude_code_identity(b"[1, 2, 3]") == b"[1, 2, 3]"


def test_unextendable_system_shape_is_left_for_upstream_to_reject():
    """A malformed ``system`` earns a 400 from upstream; rewriting it here would
    only trade one 400 for another."""
    body = json.dumps({"system": 42}).encode()

    assert apply_claude_code_identity(body) is body


def test_client_presents_as_claude_code():
    assert client_presents_as_claude_code({"user-agent": "claude-cli/2.1.0 (external, cli)"})
    assert client_presents_as_claude_code({"User-Agent": "claude-cli/1.0"})
    assert not client_presents_as_claude_code({"user-agent": "hermes-agent/1.0"})
    assert not client_presents_as_claude_code({"user-agent": "  "})
    assert not client_presents_as_claude_code({})

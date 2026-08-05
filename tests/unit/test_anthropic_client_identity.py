from __future__ import annotations

import json

from app.core.anthropic.client_identity import (
    ATTRIBUTION_HEADER,
    CLAUDE_CODE_SYSTEM_TEXT,
    client_presents_as_claude_code,
    normalize_claude_code_request,
)

_IDENTITY_BLOCK = {"type": "text", "text": CLAUDE_CODE_SYSTEM_TEXT}


def _system_of(body: bytes):
    return json.loads(body)["system"]


def _normalized_system(body: bytes):
    return _system_of(normalize_claude_code_request(body).body)


def _attribution_block(nonce: str) -> dict[str, str]:
    """The shape Claude Code sends: a header line smuggled as a system block."""
    return {
        "type": "text",
        "text": (
            f"{ATTRIBUTION_HEADER}: cc_version=2.1.220.b7d; cc_entrypoint=claude-vscode;"
            f" cch={nonce}; cc_prev_req=req_{nonce};"
        ),
    }


def test_string_system_becomes_block_list_led_by_the_identity():
    body = json.dumps({"model": "claude-sonnet-4-5", "system": "You are Hermes."}).encode()

    result = normalize_claude_code_request(body).body

    assert _system_of(result) == [_IDENTITY_BLOCK, {"type": "text", "text": "You are Hermes."}]
    # The rest of the payload survives the round-trip.
    assert json.loads(result)["model"] == "claude-sonnet-4-5"


def test_block_list_system_is_prepended():
    caller_block = {"type": "text", "text": "You are Hermes.", "cache_control": {"type": "ephemeral"}}
    body = json.dumps({"system": [caller_block]}).encode()

    assert _normalized_system(body) == [_IDENTITY_BLOCK, caller_block]


def test_missing_system_gains_one():
    body = json.dumps({"model": "claude-sonnet-4-5", "messages": []}).encode()

    assert _normalized_system(body) == [_IDENTITY_BLOCK]


def test_empty_string_system_does_not_produce_an_empty_text_block():
    """An empty text block is rejected upstream, so it is dropped, not forwarded."""
    body = json.dumps({"system": "   "}).encode()

    assert _normalized_system(body) == [_IDENTITY_BLOCK]


def test_already_identified_body_is_returned_unchanged():
    body = json.dumps({"system": [_IDENTITY_BLOCK, {"type": "text", "text": "…"}]}).encode()

    result = normalize_claude_code_request(body)

    # Same object: Claude Code's own bytes are never re-serialized.
    assert result.body is body
    assert result.attribution is None


def test_already_identified_string_system_is_returned_unchanged():
    body = json.dumps({"system": f"{CLAUDE_CODE_SYSTEM_TEXT}\n\nAnd then some."}).encode()

    assert normalize_claude_code_request(body).body is body


def test_transform_is_idempotent():
    body = json.dumps({"system": "You are Hermes."}).encode()

    once = normalize_claude_code_request(body).body

    assert normalize_claude_code_request(once).body is once


def test_non_json_body_is_passed_through():
    body = b"not json at all"

    assert normalize_claude_code_request(body).body is body


def test_non_object_json_body_is_passed_through():
    assert normalize_claude_code_request(b"[1, 2, 3]").body == b"[1, 2, 3]"


def test_unextendable_system_shape_is_left_for_upstream_to_reject():
    """A malformed ``system`` earns a 400 from upstream; rewriting it here would
    only trade one 400 for another."""
    body = json.dumps({"system": 42}).encode()

    assert normalize_claude_code_request(body).body is body


def test_attribution_block_is_lifted_out_of_the_body():
    sdk_block = {"type": "text", "text": f"{CLAUDE_CODE_SYSTEM_TEXT} Running within the Claude Agent SDK."}
    body = json.dumps({"system": [_attribution_block("ff2f4"), sdk_block]}).encode()

    result = normalize_claude_code_request(body)

    assert _system_of(result.body) == [sdk_block]
    assert result.attribution == (
        "cc_version=2.1.220.b7d; cc_entrypoint=claude-vscode; cch=ff2f4; cc_prev_req=req_ff2f4;"
    )


def test_lifting_the_attribution_leaves_an_identical_prefix_across_requests():
    """The whole point: the per-request nonce must not reach the prompt, or every
    request presents a different prefix and no prompt cache can be read."""
    sdk_block = {"type": "text", "text": CLAUDE_CODE_SYSTEM_TEXT, "cache_control": {"type": "ephemeral"}}
    first = json.dumps({"system": [_attribution_block("aaaaa"), sdk_block]}).encode()
    second = json.dumps({"system": [_attribution_block("bbbbb"), sdk_block]}).encode()

    assert first != second
    assert normalize_claude_code_request(first).body == normalize_claude_code_request(second).body


def test_attribution_block_before_a_foreign_system_still_gains_the_identity():
    caller_block = {"type": "text", "text": "You are Hermes."}
    body = json.dumps({"system": [_attribution_block("ff2f4"), caller_block]}).encode()

    result = normalize_claude_code_request(body)

    assert _system_of(result.body) == [_IDENTITY_BLOCK, caller_block]
    assert result.attribution is not None


def test_attribution_block_carrying_a_breakpoint_is_left_in_place():
    """Removing a block with ``cache_control`` would move the caller's cache
    boundary -- the very thing the lift exists to protect."""
    block = _attribution_block("ff2f4") | {"cache_control": {"type": "ephemeral"}}
    body = json.dumps({"system": [block, {"type": "text", "text": CLAUDE_CODE_SYSTEM_TEXT}]}).encode()

    result = normalize_claude_code_request(body)

    assert result.attribution is None
    assert _system_of(result.body) == [_IDENTITY_BLOCK, block, {"type": "text", "text": CLAUDE_CODE_SYSTEM_TEXT}]


def test_attribution_is_only_lifted_from_the_leading_block():
    """Mid-conversation system blocks are the client's business, not the relay's."""
    body = json.dumps({"system": [_IDENTITY_BLOCK, _attribution_block("ff2f4")]}).encode()

    result = normalize_claude_code_request(body)

    assert result.body is body
    assert result.attribution is None


def test_client_presents_as_claude_code():
    assert client_presents_as_claude_code({"user-agent": "claude-cli/2.1.0 (external, cli)"})
    assert client_presents_as_claude_code({"User-Agent": "claude-cli/1.0"})
    assert not client_presents_as_claude_code({"user-agent": "hermes-agent/1.0"})
    assert not client_presents_as_claude_code({"user-agent": "  "})
    assert not client_presents_as_claude_code({})

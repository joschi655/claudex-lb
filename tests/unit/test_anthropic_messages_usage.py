"""Usage extraction from Anthropic Messages responses.

Contract: openspec/changes/add-anthropic-request-logs/specs/anthropic-provider/spec.md.
"""

from __future__ import annotations

import json

import pytest

from app.core.anthropic.messages_usage import (
    AnthropicMessageUsage,
    SseUsageAccumulator,
    parse_message_usage,
)

pytestmark = pytest.mark.unit


def _sse(event: str, payload: dict) -> bytes:
    return f"event: {event}\ndata: {json.dumps(payload)}\n\n".encode()


def _message_start(**usage: int) -> bytes:
    return _sse(
        "message_start",
        {"type": "message_start", "message": {"model": "claude-opus-5", "usage": usage}},
    )


def _message_delta(output_tokens: int) -> bytes:
    return _sse(
        "message_delta",
        {"type": "message_delta", "delta": {"stop_reason": "end_turn"}, "usage": {"output_tokens": output_tokens}},
    )


class TestNonStreamingParse:
    def test_reads_model_and_counts(self) -> None:
        body = json.dumps(
            {
                "type": "message",
                "model": "claude-opus-5",
                "usage": {"input_tokens": 120, "output_tokens": 45},
            }
        ).encode()
        assert parse_message_usage(body) == AnthropicMessageUsage(
            model="claude-opus-5",
            input_tokens=120,
            cached_input_tokens=None,
            output_tokens=45,
        )

    def test_input_total_includes_cache_reads_and_writes(self) -> None:
        # request_logs treats cached_input_tokens as a SUBSET of input_tokens,
        # so the three disjoint upstream counters must be summed.
        body = json.dumps(
            {
                "model": "claude-opus-5",
                "usage": {
                    "input_tokens": 10,
                    "cache_read_input_tokens": 90,
                    "cache_creation_input_tokens": 5,
                    "output_tokens": 7,
                },
            }
        ).encode()
        usage = parse_message_usage(body)
        assert usage.input_tokens == 105
        assert usage.cached_input_tokens == 90

    @pytest.mark.parametrize(
        "body",
        [b"", b"not json", b"[]", b'{"error": {"type": "overloaded_error"}}'],
    )
    def test_unparseable_bodies_yield_empty_usage(self, body: bytes) -> None:
        usage = parse_message_usage(body)
        assert usage.input_tokens is None
        assert usage.output_tokens is None

    def test_negative_and_non_integer_counts_are_ignored(self) -> None:
        body = json.dumps({"model": "claude-opus-5", "usage": {"input_tokens": -3, "output_tokens": "many"}}).encode()
        usage = parse_message_usage(body)
        assert usage.input_tokens is None
        assert usage.output_tokens is None
        assert usage.model == "claude-opus-5"


class TestStreamingAccumulator:
    def test_collects_input_from_start_and_output_from_delta(self) -> None:
        accumulator = SseUsageAccumulator()
        accumulator.feed(_message_start(input_tokens=100, output_tokens=1))
        accumulator.feed(_sse("content_block_delta", {"type": "content_block_delta"}))
        accumulator.feed(_message_delta(250))

        assert accumulator.usage == AnthropicMessageUsage(
            model="claude-opus-5",
            input_tokens=100,
            cached_input_tokens=None,
            output_tokens=250,
        )

    def test_delta_does_not_erase_input_counts(self) -> None:
        accumulator = SseUsageAccumulator()
        accumulator.feed(_message_start(input_tokens=40, cache_read_input_tokens=60))
        accumulator.feed(_message_delta(9))

        assert accumulator.usage.input_tokens == 100
        assert accumulator.usage.cached_input_tokens == 60
        assert accumulator.usage.output_tokens == 9

    def test_last_delta_wins(self) -> None:
        accumulator = SseUsageAccumulator()
        accumulator.feed(_message_start(input_tokens=10))
        accumulator.feed(_message_delta(5))
        accumulator.feed(_message_delta(500))

        assert accumulator.usage.output_tokens == 500

    @pytest.mark.parametrize("chunk_size", [1, 3, 17, 64, 4096])
    def test_arbitrary_chunk_boundaries_produce_the_same_result(self, chunk_size: int) -> None:
        stream = _message_start(input_tokens=100, cache_read_input_tokens=20) + _message_delta(250)
        accumulator = SseUsageAccumulator()
        for offset in range(0, len(stream), chunk_size):
            accumulator.feed(stream[offset : offset + chunk_size])

        assert accumulator.usage.input_tokens == 120
        assert accumulator.usage.cached_input_tokens == 20
        assert accumulator.usage.output_tokens == 250

    def test_missing_message_delta_keeps_start_values(self) -> None:
        # A stream cut short by a client disconnect still logs what it knew.
        accumulator = SseUsageAccumulator()
        accumulator.feed(_message_start(input_tokens=100, output_tokens=1))

        assert accumulator.usage.input_tokens == 100
        assert accumulator.usage.output_tokens == 1

    def test_empty_and_malformed_lines_are_ignored(self) -> None:
        accumulator = SseUsageAccumulator()
        accumulator.feed(b"\n\n: ping\n")
        accumulator.feed(b"data: {not json, message_delta}\n")
        accumulator.feed(_message_start(input_tokens=5))

        assert accumulator.usage.input_tokens == 5

    def test_oversized_unterminated_line_is_dropped_without_unbounded_growth(self) -> None:
        accumulator = SseUsageAccumulator()
        accumulator.feed(b"data: " + b"x" * (2 * 1024 * 1024))
        # The overflowing line's tail is discarded, and the stream recovers.
        accumulator.feed(b"garbage-tail\n")
        accumulator.feed(_message_start(input_tokens=42))

        assert accumulator.usage.input_tokens == 42

    def test_oversized_terminated_line_is_not_parsed(self) -> None:
        padded = json.dumps(
            {
                "type": "message_start",
                "message": {"model": "claude-opus-5", "usage": {"input_tokens": 7}, "pad": "x" * (2 * 1024 * 1024)},
            }
        ).encode()
        accumulator = SseUsageAccumulator()
        accumulator.feed(b"data: " + padded + b"\n")

        assert accumulator.usage.input_tokens is None


class TestCacheWriteCounter:
    """Cache writes are billed at 1.25x base input while reads are billed at 0.1x.

    Folding them into the input total alone leaves them indistinguishable from
    uncached input, and therefore priced as if they were uncached.
    """

    def test_buffered_response_keeps_the_counter(self) -> None:
        body = json.dumps(
            {
                "model": "claude-opus-5",
                "usage": {
                    "input_tokens": 10,
                    "cache_read_input_tokens": 90,
                    "cache_creation_input_tokens": 5,
                    "output_tokens": 42,
                },
            }
        ).encode()

        usage = parse_message_usage(body)

        assert usage.input_tokens == 105
        assert usage.cached_input_tokens == 90
        assert usage.cache_write_input_tokens == 5

    def test_absent_cache_creation_records_no_counter(self) -> None:
        body = json.dumps({"model": "claude-opus-5", "usage": {"input_tokens": 10, "output_tokens": 3}}).encode()

        usage = parse_message_usage(body)

        assert usage.cache_write_input_tokens is None

    def test_streamed_counter_survives_later_deltas(self) -> None:
        accumulator = SseUsageAccumulator()
        accumulator.feed(_message_start(input_tokens=10, cache_read_input_tokens=90, cache_creation_input_tokens=5))
        accumulator.feed(_sse("message_delta", {"type": "message_delta", "usage": {"output_tokens": 42}}))

        assert accumulator.usage.cache_write_input_tokens == 5
        assert accumulator.usage.cached_input_tokens == 90
        assert accumulator.usage.output_tokens == 42

    def test_counter_alone_makes_usage_present(self) -> None:
        assert AnthropicMessageUsage(cache_write_input_tokens=5).has_any

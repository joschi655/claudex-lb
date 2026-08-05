"""Token usage extraction from Anthropic Messages API responses.

Two shapes carry the same information. A non-streaming response puts ``usage``
in the JSON body; a streaming response splits it across SSE events, with the
input counts arriving in ``message_start`` and the output count growing over
successive ``message_delta`` events.

Both are normalized to :class:`AnthropicMessageUsage`, whose ``input_tokens`` is
the TOTAL prompt size. Anthropic reports uncached input, cache reads, and cache
writes as three disjoint counters, but ``request_logs`` treats
``cached_input_tokens`` as a subset of ``input_tokens`` (the cost path computes
billable input as the difference). Summing the three on the way in is what makes
the stored row mean the same thing for both providers.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, replace

_MESSAGE_START = "message_start"
_MESSAGE_DELTA = "message_delta"

# Cap on a single buffered SSE line. Real events are far smaller; a line that
# exceeds this is a malformed or hostile upstream, and the accumulator drops it
# rather than growing without bound behind a client that is still streaming.
_MAX_LINE_BYTES = 1024 * 1024

_DATA_PREFIX = b"data:"


@dataclass(frozen=True, slots=True)
class AnthropicMessageUsage:
    """Usage for one Messages API response, in ``request_logs`` terms."""

    model: str | None = None
    input_tokens: int | None = None
    cached_input_tokens: int | None = None
    output_tokens: int | None = None

    @property
    def has_any(self) -> bool:
        return any(
            value is not None for value in (self.model, self.input_tokens, self.cached_input_tokens, self.output_tokens)
        )


def parse_message_usage(body: bytes) -> AnthropicMessageUsage:
    """Read usage from a complete non-streaming Messages response body.

    Returns an empty usage when the body is not a Messages response; callers log
    the request either way, with null counts.
    """
    payload = _loads_object(body)
    if payload is None:
        return AnthropicMessageUsage()
    return _usage_from_message(payload)


class SseUsageAccumulator:
    """Extracts usage from an Anthropic SSE stream as bytes flow past.

    Fed raw response chunks in order via :meth:`feed`; chunk boundaries may fall
    anywhere, including mid-line and mid-UTF-8-sequence, so partial lines are
    carried over. Nothing is retained beyond the current partial line, so the
    accumulator's memory does not grow with stream length.
    """

    __slots__ = ("_buffer", "_overflowing", "_usage")

    def __init__(self) -> None:
        self._buffer = bytearray()
        # Set while discarding the tail of a line that blew the size cap, so the
        # remainder is dropped instead of being parsed as a fresh line.
        self._overflowing = False
        self._usage = AnthropicMessageUsage()

    @property
    def usage(self) -> AnthropicMessageUsage:
        return self._usage

    def feed(self, chunk: bytes) -> None:
        if not chunk:
            return
        self._buffer.extend(chunk)
        while True:
            newline = self._buffer.find(b"\n")
            if newline < 0:
                break
            line = bytes(self._buffer[:newline])
            del self._buffer[: newline + 1]
            if self._overflowing:
                self._overflowing = False
                continue
            self._consume_line(line)
        if len(self._buffer) > _MAX_LINE_BYTES:
            self._buffer.clear()
            self._overflowing = True

    def _consume_line(self, line: bytes) -> None:
        # Guards the terminated case too: a single chunk can carry an oversized
        # line complete with its newline, which the loop above never buffers.
        if len(line) > _MAX_LINE_BYTES:
            return
        if not line.startswith(_DATA_PREFIX):
            return
        # Cheap pre-filter: content_block_delta events are by far the most
        # numerous and carry no usage, so only lines naming an event type we act
        # on are worth the JSON parse.
        if _MESSAGE_START.encode() not in line and _MESSAGE_DELTA.encode() not in line:
            return
        payload = _loads_object(line[len(_DATA_PREFIX) :])
        if payload is None:
            return
        event_type = payload.get("type")
        if event_type == _MESSAGE_START:
            message = payload.get("message")
            if isinstance(message, dict):
                self._merge(_usage_from_message(message))
        elif event_type == _MESSAGE_DELTA:
            usage = payload.get("usage")
            if isinstance(usage, dict):
                self._merge(_usage_from_usage_object(usage))

    def _merge(self, update: AnthropicMessageUsage) -> None:
        # message_delta repeats a cumulative output count and omits the input
        # counts, so later events must not erase what message_start established.
        merged = self._usage
        if update.model is not None:
            merged = replace(merged, model=update.model)
        if update.input_tokens is not None:
            merged = replace(merged, input_tokens=update.input_tokens)
        if update.cached_input_tokens is not None:
            merged = replace(merged, cached_input_tokens=update.cached_input_tokens)
        if update.output_tokens is not None:
            merged = replace(merged, output_tokens=update.output_tokens)
        self._usage = merged


def _usage_from_message(message: dict[str, object]) -> AnthropicMessageUsage:
    raw_model = message.get("model")
    model = raw_model if isinstance(raw_model, str) and raw_model else None
    usage = message.get("usage")
    if not isinstance(usage, dict):
        return AnthropicMessageUsage(model=model)
    return replace(_usage_from_usage_object(usage), model=model)


def _usage_from_usage_object(usage: dict[str, object]) -> AnthropicMessageUsage:
    uncached = _non_negative_int(usage.get("input_tokens"))
    cache_read = _non_negative_int(usage.get("cache_read_input_tokens"))
    cache_write = _non_negative_int(usage.get("cache_creation_input_tokens"))
    output = _non_negative_int(usage.get("output_tokens"))

    parts = [part for part in (uncached, cache_read, cache_write) if part is not None]
    total_input = sum(parts) if parts else None
    return AnthropicMessageUsage(
        input_tokens=total_input,
        cached_input_tokens=cache_read,
        output_tokens=output,
    )


def _non_negative_int(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value if value >= 0 else None


def _loads_object(raw: bytes) -> dict[str, object] | None:
    try:
        payload = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        return None
    return payload if isinstance(payload, dict) else None

# Tasks

## 1. Usage extraction

- [x] 1.1 New `app/core/anthropic/messages_usage.py` with an `AnthropicMessageUsage`
      dataclass carrying model, total input, cache-read, and output tokens
- [x] 1.2 `parse_message_usage(body)` for non-streaming JSON responses
- [x] 1.3 `SseUsageAccumulator` that consumes raw SSE chunks, tolerates chunk boundaries
      splitting a line, and reads `message_start` / `message_delta`
- [x] 1.4 Bound the accumulator's buffer so a pathological upstream line cannot grow it
      without limit, and pre-filter lines so ordinary text deltas are never JSON-parsed

## 2. Shared helpers

- [x] 2.1 Move `_request_log_useragent_fields` out of `app/modules/proxy/_service/support.py`
      into `app/core/usage/useragent.py`; re-point the OpenAI call site rather than
      duplicating the logic

## 3. Relay wiring

- [x] 3.1 Thread the authenticated API key id and client IP from
      `app/modules/anthropic_proxy/api.py` into `relay()`
- [x] 3.2 Skip logging for `count_tokens`
- [x] 3.3 Read the requested model from the client request body once per relay
- [x] 3.4 Time each attempt; capture time-to-first-byte for streaming responses
- [x] 3.5 Emit a row per attempt: success, and each upstream error that produced a
      response
- [x] 3.6 Write on tracked background tasks, mirroring the existing usage-write pattern
      (strong reference held until completion, failures warned and swallowed)

## 4. Tests

- [x] 4.1 Unit: non-streaming usage parse, including the total-and-subset normalization
- [x] 4.2 Unit: SSE accumulation across chunk boundaries, mid-JSON splits, and a missing
      `message_delta`
- [x] 4.3 Unit: buffer bound holds against an oversized line
- [x] 4.4 Integration: a successful relay writes one row with tokens and latency
- [x] 4.5 Integration: `count_tokens` writes no row
- [x] 4.6 Integration: 429 failover writes one error row and one success row
- [x] 4.7 Integration: a streaming relay writes a row with a first-token latency

## 5. Docs

- [x] 5.1 Note Claude request logging and the `count_tokens`/cost exclusions in the
      Anthropic operator docs, linking back to the capability

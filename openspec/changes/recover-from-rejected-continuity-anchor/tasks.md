# Tasks

## 1. Classify an anchor rejection by its condition, not its sentence

- [x] 1.1 Widen `is_previous_response_not_found_message` to also match a message
      that names `previous_response_id` and calls it invalid, keeping the existing
      "previous response … not found" match intact.
- [x] 1.2 Relax the `param` precondition in `is_previous_response_not_found_error`
      so a missing `param` no longer blocks classification, while a `param` naming
      a different field still does.
- [x] 1.3 Leave `previous_response_id_from_not_found_message` unchanged — the new
      wording carries no response id to extract, and returning `None` is the
      correct answer for it.

## 2. Verify

- [x] 2.1 Unit test: the live wording `Invalid \`previous_response_id\`.` classifies
      as an anchor rejection, with and without `param`.
- [x] 2.2 Unit test: the original `not found` wording still classifies, and the
      bare `previous_response_not_found` code still short-circuits.
- [x] 2.3 Unit test: an `invalid_request_error` naming a different `param` does not
      classify, and an unrelated invalid-request message does not classify.
- [x] 2.4 Unit test: no response id is extracted from the new wording.
- [x] 2.5 Regression test at the failing surface — the Codex websocket route: a
      proxy-injected anchor rejected with the live wording is retried without the
      anchor, and the client receives the recovered response rather than the raw
      upstream invalid-request error.
- [x] 2.6 Regression test: a rejection whose payload is not self-contained is not
      replayed as a fresh turn, and surfaces the retryable continuity error.
- [x] 2.7 Full gate: `uv run pytest`, `uv run ruff check`, and
      `openspec validate --strict` on this change.

## 3. Confirm against the live deployment

- [ ] 3.1 Deploy to ubuntu-tunnel and confirm a Codex session that reproduces the
      anchor rejection now completes its turn.

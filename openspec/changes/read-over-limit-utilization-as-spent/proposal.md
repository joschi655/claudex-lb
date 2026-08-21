## Why

An exhausted Claude account reported itself as 1% used, and the pool kept sending
it traffic.

The unified rate-limit headers report utilization as a fraction of the window, and
that fraction does not stop at 1: an account 4% over reports `1.04`. The parser
carried a tolerance for an "already a percentage" value — anything above 1 was
taken at face value — so `1.04` became **1.04%**. Not merely wrong: inverted. The
window reads as empty at the exact moment it is spent.

The misreading sustains itself, because a 429 carries the same headers. Observed
live on `claude-a@example.com`:

| 12:32:19 | usage poll writes `100.0%` — the account is genuinely spent |
| 12:33:34.798 | a 429's headers write `1.04%` |
| 12:33:34.896 | that same request is logged `rate_limit_exceeded` |
| 12:33:45 | balancer reads 1.04%, routes back, 429 again |

`/api/oauth/usage` confirmed `five_hour utilization = 100.0` while the stored row
said `1.04`. The account's own rejection is what marked it healthy.

The tolerance is not fixable by widening a band. No value in `(1, 100]` can be
told apart from a fraction by inspection, and biasing either way trades one wrong
answer for another. The fraction is the contract.

## What Changes

- The unified rate-limit utilization headers are read as a fraction, always, and
  clamped to 100%. A value above 1 means over-limit, which is spent, not empty.
- The tolerance for a percentage-shaped header value is removed rather than
  widened.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `live-usage-ingestion`: the utilization header's scale is stated, including what
  a value above 1 means.

## Impact

- Code: `app/core/anthropic/usage_headers.py`.
- Migration: none. Stored rows written by the old parser are corrected by the next
  usage poll or the next relayed response for that account.
- Tests: `tests/unit/test_anthropic_usage_headers.py`.
- Specs: this change's deltas, on top of `add-anthropic-request-logs` (which
  introduced header ingestion) and `poll-anthropic-usage-api`.

## Simplicity

The change deletes a branch. It is safe to delete now in a way it was not when the
parser was written: back then these headers were the only source of window state,
so a format change upstream would have been unrecoverable and the guess was worth
making. `/api/oauth/usage` now reads the same two windows on its own percentage
scale, so a format change is corrected within a poll cycle and the parser does not
need to hedge.

# Context

## Why inference was not enough on its own

The inference is sound and stays the default. What it cannot do is be corrected.
It reads a fact about the *data* — "this account reports a budget and no
window" — and presents it as a fact about the *account*. Those come apart
whenever the data is incomplete rather than absent:

- Before the first successful usage poll, a usage-based seat has no budget row
  and looks like a subscription with two empty bars.
- A seat that moved from subscription to usage-based billing keeps its old
  window rows, and the inference keeps believing them.
- A seat that reports neither presents as a subscription with nothing in it,
  which reads as a fault rather than as "this account does not work that way".

In all three the operator already knows the answer. The setting is the place to
put it.

## Why `auto` is a value rather than an absence

A two-valued setting would have to pick something for every existing row at
migration time, which means baking today's inference into a migration and
freezing it. `auto` keeps the inference live: an account left alone continues to
follow its data, including when that data changes. Only an account an operator
has actually ruled on stops listening.

This also keeps the simplicity gate honest. The default is zero-config and
behaviourally identical to what shipped before; the control only exists for the
case where the system got it wrong.

## Why an explicit kind does not fall back

The tempting shape is "show the budget if there is one, otherwise fall back to
windows". Under that rule an operator who marks an account `usage_based` sees
window bars whenever the budget data is briefly missing — which is exactly the
situation that made them set it. The setting would appear not to work, with no
way to tell whether it failed to save or the data lapsed.

So an explicit kind renders its own surface even when empty. An empty budget bar
is a legible statement ("this account bills against a budget, and we do not have
a reading"). Window bars on an account the operator declared usage-based are a
lie about what the account is.

## Presentation only

The quota kind changes nothing about selection. Routing already keys off the
usage rows themselves, and warm-up already excludes a seat that has never
recorded a window — an account with no window row produces no warm-up candidate,
which is the correct outcome for a usage-based seat regardless of what the
setting says. Making the setting steer routing would let a display preference
change where traffic goes, which is a much larger promise than the one being
made here.

The consequence worth naming: marking a seat `subscription` does not create
windows for it, and marking one `usage_based` does not stop the balancer from
using whatever windows it does report. The setting describes how the account is
shown, not how it is billed or chosen.

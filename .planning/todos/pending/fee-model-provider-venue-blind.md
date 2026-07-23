---
id: fee-model-provider-venue-blind
title: "The admission fee-model provider is hard-bound to the paper venue, and its in-code justification is false"
status: pending
severity: medium
source: 11.1-REVIEW.md (WR-01)
created: 2026-07-23
resolves_by: Phase 11.2
---

# A live order's fee headroom is estimated from the paper exchange

`compose_engine` resolves `admission_exchange = execution_handler.exchanges.get((COMPUTE_VENUE,
DEFAULT_ACCOUNT_ID))` **once**, and the `fee_model_provider` closure reads `fee_model` off that
one object for every order, regardless of the order's venue or account.
`ExecutionHandler.init_exchanges` always resolves the paper bundle — even on a live OKX boot —
so `admission_exchange` is always the `SimulatedExchange`.

The comment at `live_trading_system.py:1990-1995` states *"the live OKX exchange exposes no
`fee_model`, so the provider yields None here."* **That is not what happens.** The provider never
looks at the OKX exchange at all; it returns the paper exchange's fee model.

Verified: `OkxExchange` has no `fee_model` attribute, and `ExchangeConfig.default()` pins
`FeeModelType.ZERO` (`config/exchange.py:190`) — which is the *only* reason the reservation is
`Decimal("0")` today.

## Decision (2026-07-23) — venue-aware provider + correct the comment

Make the `fee_model_provider` closure take `(venue, account_id)`, and replace the comment with
the truth. Queued for **Phase 11.2**.

### Rationale

The numbers are unchanged today — OKX yields `None`, paper yields `ZeroFeeModel`, and both are
zero — so the change is **oracle-safe**.

What it buys is breaking the coupling whereby a venue-scoped fee update aimed at the *paper*
exchange silently moves **OKX** admission reservations (`ExecutionHandler.update_config` is
venue-blind and always targets `(COMPUTE_VENUE, DEFAULT_ACCOUNT_ID)`). It also means a future
`OkxExchange.fee_model` takes effect the moment it exists — whereas today nothing would read it.

Correcting the comment is not cosmetic. As written it asserts a mechanism that does not exist,
which would send the next reader looking for a `None` that the code never produces.

### Deliberately scoped out

Giving `OkxExchange` a real fee model is the **only** option that makes live reservations
actually correct — a venue-aware provider reading a venue with no fee model still reserves zero.
It was considered and **rejected for this scope**: it changes live reservation amounts, and
belongs with the work that makes live OKX tradeable, not with a review closure.

Recorded in full, with the other three 11.1 review decisions, under `## Resolution (2026-07-23)`
in `.planning/phases/11.1-account-provisioning-mandatory-account-identity/11.1-REVIEW.md`.

---
id: venue-bundle-memo-check-then-set-race
title: "VenueBundles.get and ConnectorProvider.get are unlocked check-then-set around an I/O-adjacent build"
status: pending
severity: medium
source: 11.1-REVIEW.md (WR-06)
created: 2026-07-23
resolves_by: Phase 12
---

# Both venue memos are check-then-set with no lock

`VenueBundles.get` (`itrader/venues/bundles.py`) and `ConnectorProvider.get`
(`itrader/connectors/provider.py`) have the identical unlocked shape:

```
if key not in self._memo:
    self._memo[key] = ...build_bundle(...)
```

`build_bundle` is long and I/O-adjacent — it constructs an exchange and, on the OKX arm,
resolves credentials and memoizes a connector — so the window between the membership test and
the assignment is wide, not a theoretical instruction-level race.

## Why it matters

`PortfolioHandler`'s class docstring documents a single-writer engine-thread contract (D-19),
but it **also** states that live portfolios are added by the application *after*
`build_live_system` returns — and this project's FastAPI plan makes that "application" a
request handler. Those two statements are not reconciled anywhere.

Two concurrent `add_portfolio` calls could each build a bundle for `('paper', 'default')`,
yielding two `SimulatedExchange` objects and two independent resting-order books. On a venue
arm the same race yields two `OkxExchange`/connector pairs for a single authenticated account —
which is the double-`_stream_fills` defect **D-08 exists to prevent**.

Unreachable today: no off-engine-thread caller exists.

## Open decision for Phase 12

Pick one deliberately:

**(a) Lock both memos.** An `RLock` around the build, keeping the fast path a plain dict read
and re-checking under the lock on miss. `RLock` rather than `Lock` because `build_bundle`
re-enters `ConnectorProvider.get`.

**(b) Declare and enforce `add_portfolio` as engine-thread-only.** This is the stronger
statement, but it obliges the FastAPI layer to marshal portfolio creation through the queue
rather than calling the handler directly.

The owner deferred this to Phase 12 **deliberately**, to settle it alongside the rest of the
threading contract rather than decide the engine's concurrency model inside a review closure.

Related Phase 12 item out of the same review:
`.planning/todos/pending/account-reservation-ledger-narrow-port.md`.

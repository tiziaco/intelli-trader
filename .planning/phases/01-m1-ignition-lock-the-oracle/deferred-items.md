# Deferred Items — Phase 01 (m1-ignition-lock-the-oracle)

Out-of-scope discoveries logged during execution. NOT fixed in the discovering plan.
Per PROJECT.md, gap discovery is bounded — these are flagged for owner approval and
routed to their correct milestone, never silently folded into the running phase.

| ID | Found In | Description | Owner Milestone | Status |
|----|----------|-------------|-----------------|--------|
| DEF-01-A | Plan 01-03 (smoke trace) | `Position.avg_price` (position.py:81) computes `self.avg_sold * self.sell_quantity - self.sell_commission` mixing `float` (avg_sold/quantity) with `Decimal` (sell_commission) → `TypeError: unsupported operand type(s) for -: 'float' and 'decimal.Decimal'`. Surfaces only once fills actually execute against an open SELL position. | M4 (Decimal money end-to-end, #22 Critical cash-through-CashManager) | RESOLVED (minimal local fix) in Plan 01-04 — see note below; **must be reconciled at M4** |
| DEF-01-B | Plan 01-03 (smoke trace) | The end-to-end smoke run needs three integration wirings to turn green: (1) `csv` registered as an execution-venue alias to `SimulatedExchange` in `ExecutionHandler.init_exchanges`; (2) the golden ticker `BTCUSD` added to the simulated exchange's `supported_symbols` (default preset only lists `*USDT`); (3) the `EnhancedOrderValidator` allowing `quantity=0` to pass to the sizing seam (currently `_validate_quantity_ranges` hard-rejects it, and `test_zero_quantity_signal` locks that behavior). | Plan 01-04 (oracle capture — plan explicitly says smoke-green is "confirm in Plan 04") | RESOLVED in Plan 01-04 — see note below |
| DEF-01-C | Plan 01-05 (oracle blessing) | No margin/liquidation/collateral model. Shorts (and the transient short opened on a SELL-when-flat first signal) ride to unbounded mark-to-market loss with no stop-out — total_equity goes negative (min −$33,748 at 2023-11-10) while cash stays ≥0 (engine enforces InsufficientFundsError, so this is NOT negative cash; it is an un-liquidated short liability in positions_value). A real venue would have margin-called/liquidated. This behavior was BLESSED INTO THE M1 ORACLE BY THE HUMAN as current-behavior-to-preserve; M2–M4 lock against it, M5 fixes results and re-blesses. | M5 (strategy/execution correctness; the only milestone allowed to change results, cross-validated) | Accepted into oracle — deferred to M5 |

## Resolution Notes (Plan 01-04)

- **DEF-01-B resolved.** (1) `csv` aliased to the same `SimulatedExchange` instance in
  `ExecutionHandler.init_exchanges` (with an id-dedup guard in `on_market_data` so the shared
  instance is driven once per bar). (2) `BTCUSD` added to that instance's `_supported_symbols`
  (instance-level mutation, not the shared preset). (3) Implemented as a **narrow gate**:
  fraction-of-cash sizing is resolved in `OrderManager` *before* the validator runs
  (`_resolve_signal_quantity` called at the top of `process_signal`), so the running engine never
  presents `quantity=0` to the validator — `test_zero_quantity_signal` (which calls
  `validate_signal_pipeline` directly) is untouched and still asserts failure for `quantity=0`.
  Two additional same-class wirings surfaced during the run and were applied: the validator now
  admits the `csv` venue (`supported_exchanges`) and raises its stock-tuned `max_price` ceiling so
  crypto prices (BTC ~$116k in 2024-2026) are not rejected. Also extended the sizing seam to size a
  long-only SELL exit to the open long's net quantity so round-trips actually close (otherwise the
  trade log stays empty).
- **DEF-01-A resolved with a MINIMAL local fix (overlaps M4 scope — reconcile at M4).** The fee
  model returns `Decimal` commissions into a float transaction/position path. Fixed at the single
  fill→transaction boundary (`PortfolioHandler.on_fill` coerces `fill_event.commission` to `float`,
  matching `Transaction.commission: float`) plus a defensive `float(...)` coercion in
  `Position.avg_price`. This is a behavior-preserving type-consistency fix, NOT the Decimal-money
  redesign M4 owns (#22 Critical) — M4 must revisit these two sites when money moves to Decimal
  end-to-end.

## Notes

- Plan 01-03 scope was the three M1 ignition bugs (M1-04 indexing/fillna, M1-05 record_metrics,
  M1-06 sizing seam). All three are implemented and committed; the 274 legacy tests stay green.
- During execution the smoke test (RED scaffold from Plan 01) was driven forward far enough to
  prove the sizing seam emits correct non-zero quantities (e.g. 1.27 / 1.42 BTC at the right
  prices) and that orders route + execute — but it cannot go fully green within this plan's file
  scope without the DEF-01-A money-type fix (M4) and the DEF-01-B integration wirings (Plan 04).
  Those edits were made experimentally to locate the blockers, then reverted to keep this plan's
  diff to its three `files_modified` and preserve the 274-green criterion.

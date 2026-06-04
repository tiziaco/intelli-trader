# Deferred Items — Phase 01 (m1-ignition-lock-the-oracle)

Out-of-scope discoveries logged during execution. NOT fixed in the discovering plan.
Per PROJECT.md, gap discovery is bounded — these are flagged for owner approval and
routed to their correct milestone, never silently folded into the running phase.

| ID | Found In | Description | Owner Milestone | Status |
|----|----------|-------------|-----------------|--------|
| DEF-01-A | Plan 01-03 (smoke trace) | `Position.avg_price` (position.py:81) computes `self.avg_sold * self.sell_quantity - self.sell_commission` mixing `float` (avg_sold/quantity) with `Decimal` (sell_commission) → `TypeError: unsupported operand type(s) for -: 'float' and 'decimal.Decimal'`. Surfaces only once fills actually execute against an open SELL position. | M4 (Decimal money end-to-end, #22 Critical cash-through-CashManager) | Deferred — owner approval pending |
| DEF-01-B | Plan 01-03 (smoke trace) | The end-to-end smoke run needs three integration wirings to turn green: (1) `csv` registered as an execution-venue alias to `SimulatedExchange` in `ExecutionHandler.init_exchanges`; (2) the golden ticker `BTCUSD` added to the simulated exchange's `supported_symbols` (default preset only lists `*USDT`); (3) the `EnhancedOrderValidator` allowing `quantity=0` to pass to the sizing seam (currently `_validate_quantity_ranges` hard-rejects it, and `test_zero_quantity_signal` locks that behavior). | Plan 01-04 (oracle capture — plan explicitly says smoke-green is "confirm in Plan 04") | Deferred to Plan 04 |

## Notes

- Plan 01-03 scope was the three M1 ignition bugs (M1-04 indexing/fillna, M1-05 record_metrics,
  M1-06 sizing seam). All three are implemented and committed; the 274 legacy tests stay green.
- During execution the smoke test (RED scaffold from Plan 01) was driven forward far enough to
  prove the sizing seam emits correct non-zero quantities (e.g. 1.27 / 1.42 BTC at the right
  prices) and that orders route + execute — but it cannot go fully green within this plan's file
  scope without the DEF-01-A money-type fix (M4) and the DEF-01-B integration wirings (Plan 04).
  Those edits were made experimentally to locate the blockers, then reverted to keep this plan's
  diff to its three `files_modified` and preserve the 274-green criterion.

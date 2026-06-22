# Phase 3 — Deferred Items

Tracked follow-ups from the Phase 3 code review (`03-REVIEW.md`). The BLOCKER (CR-01)
and four warnings (WR-01/02/03/05) were fixed inline during execution (commits
`1667467`, `01db518`) with regression tests; the items below were deliberately deferred.

## Code review residuals (03-REVIEW.md)

| ID | Severity | Summary | Target | Rationale for deferral |
|----|----------|---------|--------|------------------------|
| WR-04 | warning | ✅ **RESOLVED in Phase 4.** `assert_lock_fits_buying_power` now runs in `assert → release → lock` order so the add-back reads the TRUE prior lock, not `0`. Landed at `portfolio.py:439-441` and `:460-464`; assertion at `cash_manager.py:449-490`. (Was: `release_margin` popped the prior lock before the assertion ran.) | ~~Phase 4 (margin seam)~~ DONE | Fixed as the call-order change described, under the P4/XVAL-01 owner-gated re-baseline. Confirmed 2026-06-17 while scoping Phase 5.1 (short scale-in). |
| IN-01 | info | `Portfolio.update_market_value` (portfolio.py:494) is dead on the run path — `update_portfolios_market_value` only calls the carry-bearing `update_market_value_of_portfolio`. | Future cleanup | Dead code, no behavioral impact; remove or fold into the single mark entry point. |
| IN-02 | info | `_validate_position_consistency` has an unreachable `net_quantity < 0` branch (`net_quantity` is unsigned `abs(...)`). | Future cleanup | Latent trap for a future signed-read reintroduction; convert to an assertion documenting the unsigned invariant. |
| IN-03 | info | Carry over a multi-day gap charges the whole interval at the current close / current `net_quantity`, not a per-day mark. | Phase B realism | The documented static approximation (CONTEXT D-01/D-04); per-day carry fidelity is the Phase-B borrow-rate-time-series extension. |
| IN-04 | info | `get_reserved_cash` seeds `Decimal("0.00")` while `get_locked_margin` seeds `Decimal("0")` — inconsistent zero exponents. | Future cleanup | Verified byte-exact today (balance carries more places than either zero); pick one zero-exponent convention for readability. |

## Fixed inline (for the record)

- **CR-01** (BLOCKER) — carry no longer accrues on a stale mark for a short absent from a bar's prices; `_accrue_short_carry` takes `marked_tickers`, skips unmarked shorts, and does NOT advance `_last_accrual_time` so the next priced bar accrues the full interval. Regression test: `test_short_absent_from_prices_defers_carry_and_does_not_advance_clock`.
- **WR-01** — unsized SELL-while-short is now an audited `ADMISSION_INCREASE` rejection (was falling into first-entry sizing). Test: `test_short_only_unsized_sell_while_short_is_rejected`.
- **WR-02** — member-missing `KeyError` in the carry loop now raises a context-rich `StateError` naming the ticker/position (mirrors the maintenance-margin guard).
- **WR-03** — explicit `current_price <= Decimal("0")` guard before carry. Test: `test_zero_current_price_skips_carry`.
- **WR-05** — dead clock-advance in the `borrow_rate == 0` branch dropped (plain `continue`); default-off path stays byte-exact.

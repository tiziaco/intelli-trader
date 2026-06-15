# Phase 02 — Deferred Items

Out-of-scope discoveries logged during execution (not fixed in the discovering plan).

| ID | Item | Discovered | Owner | Status |
|----|------|------------|-------|--------|
| DEF-02-03-A | `tests/unit/core/test_sizing.py::test_sizing_policy_union_members` asserts the OLD 3-member `SizingPolicy` union (`FractionOfCash \| FixedQuantity \| RiskPercent`) but Plan 02-02 (`e2afb00`) grew the union with `LeveredFraction`. The stale assertion now fails. Pre-existing failure in an unrelated file — out of Plan 02-03's scope (admission/order-domain wiring). Re-confirmed still open during Plan 02-04 execution (2026-06-15) — still out of scope (Plan 02-04 owns portfolio cash/position internals, zero `core/sizing.py` overlap). | Plan 02-03 execution (2026-06-15) | Plan 02-02 / a follow-up quick-task | RESOLVED 2026-06-15 (post-Wave-2 integration gate) — added `LeveredFraction` to the expected union assertion + import. |

## Code review residuals (02-REVIEW.md)

The Phase-2 standard code review (`02-REVIEW.md`, 2026-06-15) raised 10 findings.
Plan 02-08 CLOSED both BLOCKERs (CR-01 fully; CR-02 the fail-loud guard). The
remaining findings are tracked below for Phase 3 (shorts, where flips/short
settlement become reachable) and future margin-hardening. None is reachable on
the SMA_MACD spot golden path (`enable_margin` off — oracle-dark).

| ID | Summary | Severity | Status / Target |
|----|---------|----------|-----------------|
| CR-01 | LIMIT/STOP entry orders dropped effective leverage (locked margin ≠ admission reservation) | Critical | **CLOSED by 02-08** — `new_limit_order`/`new_stop_order` carry keyword-only leverage; admission LIMIT/STOP arms pass `effective_leverage` (commits `a27e275`). |
| CR-02-guard | Over-close margin fill silently re-locks a flipped position and settles a wrong cash delta | Critical | **Guard CLOSED by 02-08** — over-close now raises `InvalidTransactionError` before mutation/settlement (commit `0448ad9`). |
| CR-02-residual | Full flip-settlement economics: split a flip fill into full-close + fresh-open (or correct `realised_increment` to the clamped quantity) so a flip settles correctly instead of being rejected | Critical (deferred) | Phase 3 (shorts) — flips become reachable once short opens/covers are ungated. |
| WR-01 | Margin funds invariant only guards commission — no settlement-side assertion that the locked margin (`aggregate_notional / L`) fits available buying power at lock time | Warning | Phase 3 — add a settlement-side solvency assertion (or assert lock == released reservation) once levered LIMIT/STOP + shorts actually lock margin on the run path. |
| WR-02 | `maintenance_margin`/`margin_ratio` dereference `self._universe` with no None guard — bare `AttributeError` if read before `set_universe` with open positions | Warning | Phase 3/4 — fail loud with context (`StateError`, universe-unwired) when positions exist but the universe is unwired. |
| WR-03 | Reservation-release symmetry comment reasons only about the order-keyed cash reservation; silently assumes no position-keyed margin lock can exist at the assembly-failure release site | Warning | Phase 3 — add an explicit assertion/comment (no fill yet → no margin lock), or release the lock there if the lock lifecycle ever moves to admission. |
| WR-04 | `_effective_leverage` clamp has no `≥1` floor / zero guard — a misconfigured `Instrument.max_leverage < 1` (or 0) yields sub-1 effective leverage or a divide-by-zero | Warning | Phase 3 — floor the cap at `Decimal("1")` and guard zero (or validate `Instrument.max_leverage >= 1` at construction). |
| WR-05 | Margin close re-credit derives the open commission from the position's aggregate `buy_commission` via a quantity fraction — drifts after a non-uniform-commission scale-in | Warning | Phase 3 — track the pre-debited open commission as a separate per-lock accumulator (or settle against the actual filled-fraction commission). |
| IN-01 | Misleading comment in `fill.py`: only EXECUTED fills' leverage is consumed by the Transaction hop (REFUSED/CANCELLED never reach `on_fill`) | Info | Future — trim the comment (doc-only). |
| IN-02 | `position_manager.py:171` uses raw `Decimal(str(signal_leverage))` instead of the `to_money` house helper (correct but off-convention) | Info | Future — use `to_money(signal_leverage)` for money-policy consistency. |
| IN-03 | `_DEFAULT_MAINTENANCE_MARGIN_RATE = 0.005` is a single global magic default governing `margin_ratio` for every symbol (no per-instrument override exercised) | Info | Phase 4 — declare the per-instrument MMR as a table entry before the liquidation milestone consumes `margin_ratio`. |

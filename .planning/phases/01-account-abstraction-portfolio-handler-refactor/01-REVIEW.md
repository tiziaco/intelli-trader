---
phase: 01-account-abstraction-portfolio-handler-refactor
reviewed: 2026-06-30T22:24:15Z
depth: standard
files_reviewed: 60
files_reviewed_list:
  - itrader/connectors/__init__.py
  - itrader/connectors/base.py
  - itrader/core/enums/portfolio.py
  - itrader/portfolio_handler/account/__init__.py
  - itrader/portfolio_handler/account/base.py
  - itrader/portfolio_handler/account/simulated.py
  - itrader/portfolio_handler/account/venue.py
  - itrader/portfolio_handler/cash/__init__.py
  - itrader/portfolio_handler/portfolio_handler.py
  - itrader/portfolio_handler/portfolio.py
  - itrader/portfolio_handler/storage/sql_storage.py
  - itrader/portfolio_handler/validators.py
  - itrader/reporting/cash_operations.py
  - itrader/trading_system/__init__.py
  - itrader/trading_system/backtest_trading_system.py
  - itrader/trading_system/system_spec.py
  - scripts/run_backtest.py
  - tests/e2e/conftest.py
  - tests/e2e/forced_liq_long/test_forced_liq_long_scenario.py
  - tests/e2e/forced_liq_short/test_forced_liq_short_scenario.py
  - tests/e2e/levered_long_into_liquidation/test_levered_long_into_liquidation_scenario.py
  - tests/e2e/levered_long/test_levered_long_scenario.py
  - tests/e2e/partial_cover/test_partial_cover_scenario.py
  - tests/e2e/short_carry/test_short_carry_scenario.py
  - tests/e2e/short_roundtrip/test_short_roundtrip_scenario.py
  - tests/e2e/short_scale_in_partial_cover/test_short_scale_in_partial_cover_scenario.py
  - tests/e2e/short_scale_in/test_short_scale_in_scenario.py
  - tests/e2e/smoke/single_market_buy/scenario.py
  - tests/e2e/trailing_long/test_trailing_long_scenario.py
  - tests/e2e/trailing_short/test_trailing_short_scenario.py
  - tests/integration/storage/test_cached_sql_portfolio_storage.py
  - tests/integration/storage/test_sql_portfolio_storage.py
  - tests/integration/test_backtest_oracle.py
  - tests/integration/test_backtest_smoke.py
  - tests/integration/test_expire_non_cascade.py
  - tests/integration/test_pair_exit_safety.py
  - tests/integration/test_pair_flagship_snapshot.py
  - tests/integration/test_reservation_inertness.py
  - tests/integration/test_results_persist.py
  - tests/integration/test_universe_spans.py
  - tests/unit/core/test_portfolio_read_model.py
  - tests/unit/order/test_admission_rules.py
  - tests/unit/order/test_admission_snapshot.py
  - tests/unit/order/test_expire_all_resting.py
  - tests/unit/order/test_liquidation_reconcile.py
  - tests/unit/order/test_on_signal.py
  - tests/unit/order/test_order_handler.py
  - tests/unit/order/test_order_manager.py
  - tests/unit/order/test_order_storage.py
  - tests/unit/order/test_order_update_config.py
  - tests/unit/order/test_sltp_policy.py
  - tests/unit/order/test_stop_limit_orders.py
  - tests/unit/order/test_trailing_bracket.py
  - tests/unit/portfolio/test_carry.py
  - tests/unit/portfolio/test_cash_manager.py
  - tests/unit/portfolio/test_cash_reservations.py
  - tests/unit/portfolio/test_liquidation.py
  - tests/unit/portfolio/test_money_decimal.py
  - tests/unit/portfolio/test_on_fill_status_guard.py
  - tests/unit/portfolio/test_portfolio_handler.py
  - tests/unit/portfolio/test_portfolio_margin.py
  - tests/unit/portfolio/test_portfolio_update.py
  - tests/unit/portfolio/test_portfolio.py
  - tests/unit/portfolio/test_realised_pnl_accumulator.py
  - tests/unit/portfolio/test_spot_oversell_guard.py
  - tests/unit/portfolio/test_state_storage.py
  - tests/unit/portfolio/test_update_config.py
  - tests/unit/portfolio/test_wr04_lock_fits_buying_power.py
  - tests/unit/reporting/test_cash_operations.py
findings:
  critical: 0
  warning: 3
  info: 4
  total: 7
status: partially_resolved
resolved_by: "WR-02 + WR-03 fixed in Phase 1 (v1.7) PR #71 / commit 26b914e3 — all InsufficientFundsError sites pass Decimal and _validate_and_convert_amount's rounding branch serializes via str(); WR-03 tag cited inline at account/simulated.py:571. WR-01 DEFERRED (owner-gated, todos/pending/margin-equity-double-counts-notional-wr01.md). IN-01 / IN-02 / IN-03 OPEN (minor, off the all-spot golden path, untracked). IN-04 documented-intentional unwired seam (no action)."
---

# Phase 1: Code Review Report

**Reviewed:** 2026-06-30T22:24:15Z
**Depth:** standard
**Files Reviewed:** 60
**Status:** issues_found

> **RESOLUTION (2026-07-07):** Verified against HEAD. Two of three WARNINGs are FIXED in the
> merged Phase 1 PR #71 (`26b914e3`): **WR-02** — all five `InsufficientFundsError` constructions in
> `account/simulated.py` (`:260, :324, :425, :463, :805`) now pass `Decimal` (`required_cash` /
> `available_cash` / `lock_amount` / `buying_power`), no `float()` remains; **WR-03** —
> `_validate_and_convert_amount`'s post-rounding branch (`simulated.py:574`) now serializes
> `{"amount": str(to_money(amount)), "rounded_amount": str(amount_decimal)}`, tag cited inline at `:571`.
> **WR-01** is genuinely **DEFERRED** (owner decision 2026-07-01) — the formula is still
> `total_market_value + cash` (`portfolio.py:284`, `portfolio_handler.py:388`); the fix was applied,
> found to break 6 owner-frozen accounting goldens, and rolled back — tracked in
> `todos/pending/margin-equity-double-counts-notional-wr01.md`. The four INFO items are unchanged in
> code: **IN-01** (`simulated.py:525,528` truthiness), **IN-02** (`portfolio.py:741` wall-clock trade
> stamp), and **IN-03** (`in_memory_storage.py:91` / `sql_storage.py:273` `Decimal("0.00")` seed)
> remain **OPEN** (minor, dark on the all-spot oracle, untracked); **IN-04** is a documented-intentional
> unwired seam, no action required.

## Narrative Findings (AI reviewer)

## Summary

This phase extracts an `Account` ABC family (`SimulatedCashAccount`,
`SimulatedMarginAccount`, `VenueAccount`) out of the former `CashManager`,
pulls the margin/liquidation math down onto the margin leaf, and re-points the
`PortfolioHandler`/`Portfolio` to delegate cash, reserve/release, locked-margin
and liquidation through the account. The code is heavily decision-anchored and
the test suite (account, liquidation, carry, reservations, oversell, SQL
storage, e2e scenarios) is meaningful — assertions check real values and the
liquidation/gap-through tests pin actual economic behavior rather than tautologies.

The spot byte-exact oracle path (the shipping value of this phase) appears
correct: cash flow goes through one full-precision `apply_fill_cash_flow`
primitive, the solvency invariant checks ledger balance (not buying power), the
over-sell/flip guards fail loud on a gross excess while absorbing quantization
noise, and reservation lifecycle is balance-neutral with idempotent release.

No BLOCKER on the shipping spot path was found. The findings below are: a real
correctness defect in **margin-mode** equity (off the golden path but wired into
the margin/risk read surface), and two money-policy consistency defects where
the new account code reintroduces the exact `float()` round-trip the surrounding
decisions (WR-04 / IN-05) were written to remove. Margin mode is deferred/dark
this phase, which is why the equity defect is graded WARNING rather than BLOCKER —
but it must be fixed before any leveraged/risk-sizing consumer reads it.

## Warnings

### WR-01: Margin-mode `total_equity` / `margin_ratio` double-count the borrowed notional

**⏸ DEFERRED** (tracked in `todos/pending/margin-equity-double-counts-notional-wr01.md`) — genuine real defect, owner-gated (tiziaco, 2026-07-01). Unchanged at HEAD: `total_equity = total_market_value + cash` (`portfolio.py:284`, `portfolio_handler.py:388`). The reviewer-recommended `enable_margin`-gated fix was applied and verified (oracle + mypy green), then rolled back because it breaks 6 owner-frozen accounting-core goldens (D-17) that hand-assert open-position equity as `balance + market_value` (never externally cross-validated). Dark on the all-spot golden run; adjudicate before any live margin/leverage consumer reads margin equity. Original finding preserved below.

**File:** `itrader/portfolio_handler/portfolio_handler.py:311-326`, `itrader/portfolio_handler/portfolio.py:245-252`, `itrader/portfolio_handler/account/simulated.py:836-854`
**Issue:** `total_equity` is computed as `account.balance + position_manager.get_total_market_value()`. For a margin position, opening a leveraged long debits only commission and *locks* margin — the full notional is never removed from `balance`. Meanwhile `Position.market_value` returns the **full** notional (`current_price * |net_quantity|`, see `position.py:104-107`). So for a freshly opened leveraged long, `total_equity ≈ cash + full_notional`, overstating true equity (`cash + unrealised_pnl ≈ cash`) by the borrowed amount. `SimulatedMarginAccount.margin_ratio` (`simulated.py:847-854`) reads exactly this inflated `portfolio.total_equity`, so the margin ratio is inflated by leverage and would never read a sub-1 margin-call value. This is currently shielded only by margin mode being deferred/dark (the actual liquidation engine bypasses `margin_ratio` and uses `_isolated_liq_price` against the bar close, and the golden run is all-spot where the formula degenerates to the correct `cash + market_value`). It is still a wrong formula for any leveraged position and will silently mislead the first risk/sizing consumer that reads it.
**Fix:** Compute margin equity from cash plus unrealised PnL, not cash plus gross market value, e.g.:
```python
def total_equity(self, portfolio_id):
    p = self.get_portfolio(portfolio_id)
    return p.account.balance + p.position_manager.get_total_unrealized_pnl()
```
(Or, on the `Portfolio.total_equity` property, gate the aggregation on `enable_margin` so the spot arm stays byte-exact while the margin arm uses `cash + Σ unrealised_pnl`.) Add a margin-mode unit test asserting equity ≈ cash immediately after a leveraged open.

### WR-02: Account leaf constructs `InsufficientFundsError` with `float()`, re-introducing the binary-float artifact WR-04 removed

**✓ FIXED** (Phase 1 PR #71, commit `26b914e3`) — all five `InsufficientFundsError` sites in `account/simulated.py` (`:260, :324, :425, :463, :805`) now pass `Decimal` straight through (`required_cash=amount_decimal` / `available_cash=available` / `lock_amount` / `buying_power`); no `float()` remains at any construction site (`git log -S 'float(available)'` on the file is empty). Original finding preserved below.

**File:** `itrader/portfolio_handler/account/simulated.py:243-246, 307-310, 408-411, 446-449, 785-788`
**Issue:** `InsufficientFundsError` was deliberately reworked (see `core/exceptions/portfolio.py:24-29` WR-04, and `validators.py:114-123`) so money fields are stored as `Decimal` — callers must pass `Decimal` to avoid the binary-float repr artifact in fields "consumed programmatically." Every `InsufficientFundsError` construction in the new account leaf instead passes `float(amount_decimal)` / `float(available)` / `float(required)`. Because the exception coerces a non-`Decimal` via `Decimal(str(x))`, a full-precision amount (e.g. `Decimal('1100.00000000123')`) is lossily round-tripped through `float` before storage — exactly the defect WR-04 was written to prevent. The ledger is unaffected (these are error-path fields), but the structured field precision is silently degraded, contradicting the file's own "Decimal end-to-end, float only at the edge" docstring (`simulated.py:21-23`).
**Fix:** Pass the `Decimal` straight through at every site; let the exception format `float` only inside its message:
```python
raise InsufficientFundsError(required_cash=amount_decimal, available_cash=available)
```

### WR-03: `_validate_and_convert_amount` post-rounding error branch still leaks a raw float into the audit payload

**✓ FIXED** (Phase 1 PR #71, commit `26b914e3`) — the second (post-rounding) branch now mirrors the first: `account/simulated.py:574` emits `{"amount": str(to_money(amount)), "rounded_amount": str(amount_decimal)}`, no raw `amount` or `float()` cast reaches the payload; the fix is tagged inline "IN-05/WR-03" at `:571`. Original finding preserved below.

**File:** `itrader/portfolio_handler/account/simulated.py:551-555`
**Issue:** The first error branch (line 540-546) was fixed under IN-05 to serialize via `str(to_money(amount))` so an incoming float never surfaces in the structured payload. The second branch — raised when the amount rounds to `<= 0` after precision quantize — still emits `{"amount": amount, "rounded_amount": float(amount_decimal)}`, passing the raw (possibly `float`) `amount` and a `float()` cast directly into the `InvalidTransactionError` data dict. This is the same "Decimal until the edge" violation IN-05 claims to have closed, applied inconsistently to only one of the two branches.
**Fix:** Mirror the first branch:
```python
{"amount": str(to_money(amount)), "rounded_amount": str(amount_decimal)}
```

## Info

### IN-01: `get_cash_operations` truthiness silently disables `limit=0` / falsy filters

**⚠ OPEN** — unchanged at HEAD: `account/simulated.py:525` (`if operation_type:`) and `:528` (`if limit:`) still use truthiness, not `is not None`. Low impact (no caller passes `0` today), untracked. Original finding preserved below.

**File:** `itrader/portfolio_handler/account/simulated.py:504-514`
**Issue:** `if operation_type:` and `if limit:` use truthiness, not `is not None`. A caller passing `limit=0` (intending "zero rows") is silently treated as "no limit" and gets the full history. Low impact (no internal caller passes 0 today), but a latent surprise on a public accessor.
**Fix:** Use `if limit is not None:` and `if operation_type is not None:`.

### IN-02: Trade path stamps `_last_activity` with wall clock, leaking non-determinism into `to_dict()`

**⚠ OPEN** — unchanged at HEAD: `transact_shares` still sets `self._last_activity = datetime.now(UTC)` at `portfolio.py:741`. The mark path was made deterministic (`:816` uses `mark_time`/`bar_time`), but the trade path still stamps wall clock. Off the oracle artifact (no golden break), untracked. Original finding preserved below.

**File:** `itrader/portfolio_handler/portfolio.py:681` (and `643`)
**Issue:** `transact_shares` sets `self._last_activity = datetime.now(UTC)` on every fill, overriding the bar-business-time value `update_market_value_of_portfolio` sets (`portfolio.py:752`). `_last_activity` is then serialized in `to_dict()['last_activity']` (`portfolio.py:898`), which feeds `PortfolioUpdateEvent`. In a determinism-critical engine ("seeded RNG + injected clock; business time, never wall clock") this is a wall-clock value on the trade path. It is off the oracle artifact (oracle reads closed positions + snapshots, not `to_dict`), so no golden break — but it is a determinism leak in a surface that is meant to be reproducible.
**Fix:** Thread the transaction's event-derived `time` into `_last_activity` on the trade path (e.g. `self._last_activity = transaction.time`), consistent with the mark path.

### IN-03: Reserved-cash sum seed `Decimal("0.00")` contradicts the Pitfall-6 `Decimal("0")` rationale used for locked margin

**⚠ OPEN** — unchanged at HEAD: `get_reserved_cash` still seeds `sum(..., Decimal("0.00"))` in both backends (`in_memory_storage.py:91`, `sql_storage.py:273`), while the sibling `get_locked_margin` seeds `Decimal("0")` (`:105` / `:323`). No behavioral defect (values compare equal, reporting casts to float), untracked. Original finding preserved below.

**File:** `itrader/portfolio_handler/storage/in_memory_storage.py:91` and `itrader/portfolio_handler/storage/sql_storage.py:271`
**Issue:** `get_locked_margin` deliberately seeds `sum(..., Decimal("0"))` with an explicit Pitfall-6 comment ("`x - Decimal('0') == x`" byte-exact), but the sibling `get_reserved_cash` seeds `sum(..., Decimal("0.00"))`. `available_balance = balance - reserved - locked` therefore acquires a 2-dp exponent from the reserved term even when no reservation exists. Values still compare equal (`Decimal("9000") == Decimal("9000.00")`) and reporting casts to float, so there is no behavioral defect — but it is an internal inconsistency that violates the very rationale documented two lines away and could matter if `available_balance` is ever serialized via `str()`/Decimal repr.
**Fix:** Seed reserved-cash sums with `Decimal("0")` to match the locked-margin path, in both backends.

### IN-04: `validators.py` is an unwired seam mixing Decimal-strict and float-typed siblings

**⚠ OPEN** (documented-intentional, no action required) — unchanged and correct at HEAD: `validators.py` remains a zero-importer seam kept under HYG-01 no-deletion (module note WR-02 at `:4-10`), still mixing `validate_portfolio_data(cash: float)` (`:80`) and `to_decimal(value: Union[int, float])` (`:137`) with the Decimal-strict `validate_transaction_data`. As the finding states, retype the float-typed members to `Decimal` only if/when the seam is wired. Original finding preserved below.

**File:** `itrader/portfolio_handler/validators.py:77-98, 137-144, 146-177`
**Issue:** The module docstring (WR-02) already declares this an unwired, intentionally-kept seam under HYG-01 no-deletion, and acknowledges the mixed `validate_portfolio_data(cash: float)` / `to_decimal` / `PositionValidator(float ...)` typing as deliberate-by-scope. Flagged only so it is on record: if/when this seam is wired, the float-typed entry points (`cash: float`, `to_decimal`, `validate_position_consistency`) violate the Decimal-end-to-end money policy and must be retyped first. No action required this phase.
**Fix:** None now (documented intentional). When wiring the seam, retype the float-typed members to `Decimal` to match `validate_transaction_data`.

---

_Reviewed: 2026-06-30T22:24:15Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_

---
phase: 07-cost-sizing-sltp-scenarios
reviewed: 2026-06-10T00:00:00Z
depth: standard
files_reviewed: 11
files_reviewed_list:
  - itrader/execution_handler/exchanges/simulated.py
  - tests/e2e/conftest.py
  - tests/e2e/strategies/scripted_emitter.py
  - tests/e2e/cost/percent_fee/scenario.py
  - tests/e2e/cost/percent_fee/test_scenario.py
  - tests/e2e/cost/combined_roundtrip/scenario.py
  - tests/e2e/cost/linear_slippage/scenario.py
  - tests/e2e/sizing/risk_percent/scenario.py
  - tests/e2e/sizing/over_cash_reject/scenario.py
  - tests/e2e/sltp/from_fill_held/scenario.py
  - tests/e2e/sltp/from_decision_sl_hit/scenario.py
findings:
  critical: 0
  warning: 3
  info: 2
  total: 5
status: issues_found
---

# Phase 7: Code Review Report

**Reviewed:** 2026-06-10
**Depth:** standard
**Files Reviewed:** 11
**Status:** issues_found

## Summary

Phase 7 adds E2E cost/sizing/SLTP scenario leaves plus one production-code change
in `simulated.py` (fee/slippage config fallbacks switched from `or` to `is not None`).
I verified the production change against the diff, the model implementations, every
scenario's VERIFY hand-derivation against its frozen golden, and the oracle-dark
guarantee.

Adversarial verification performed:
- **Production fix is correct, minimal, and mypy --strict clean.** The `or`→`is not None`
  switch genuinely fixes a real defect (a configured `Decimal("0")` base-slippage was
  silently overridden by the `0.01` default because `Decimal("0")` is falsy). Confirmed
  the COST-04 linear-slippage scenario depends on this fix to be hand-derivable.
- **All 11 scenario goldens match their VERIFY derivations to the cent.** I re-derived
  fees, slippage, sizing, SL/TP levels, realised PnL, and final cash for each leaf and
  cross-checked against the frozen `trades.csv`/`orders.csv`/`summary.json`. All 15 E2E
  tests pass; the BTCUSD oracle (`test_backtest_oracle.py`) still passes — oracle-dark
  holds (the always-on `commission` column is appended to E2E goldens only, never to
  `TRADE_COLUMNS` which feeds the oracle).
- **The conftest D-14 seam correctly avoids the symbol-set wipe** (assigns `config` +
  re-inits the two models, never re-derives `_supported_symbols`), as documented.

No BLOCKER-class correctness/security/data-loss defects found. The findings below are
documentation accuracy and latent-robustness issues.

## Warnings

### WR-01: combined_roundtrip module-level comment contradicts engine truth and its own VERIFY note

**File:** `tests/e2e/cost/combined_roundtrip/scenario.py:106-109`
**Issue:** The module-level comment on `_EXCHANGE` states:

> "The fee is charged on the slipped notional, so both costs compound in one round-trip..."

This is FALSE and directly contradicts both (a) the engine and (b) this same file's
own VERIFY note. In `simulated.py::_emit_fill` the fee is computed on the BASE
(un-slipped) price BEFORE slippage is applied:
```
price = to_money(fill_price)                       # base = bar open (100 / 200)
commission = self.fee_model.calculate_fee(price=price, ...)   # fee on BASE notional
executed_price = price * slippage_factor           # slippage applied AFTER
```
The file's own header (lines 11-16) and VERIFY (lines 53-56) correctly derive the fee
on the base notional (`95*100*0.01=95`, `95*200*0.01=190`), and the frozen golden
`commission=285.00` confirms it (a slipped-notional fee would be `95*102*0.01 + 95*196*0.01
= 96.90 + 186.20 = 283.10`, which is NOT the golden value). In a VERIFY-anchored
regression suite, a comment that misstates the cost model is a maintenance hazard: a
future author trusting it will hand-derive the wrong number and mis-diagnose a real
regression.
**Fix:** Replace the contradicting sentence with the correct statement (already present
in the file header, lines 11-16):
```python
# COST-06: BOTH a PERCENT fee (1%) AND a deterministic FIXED slippage (2%,
# random_variation=False). The fee is charged on the BASE (un-slipped) notional
# (simulated.py:196-205 computes commission before executed_price = price * factor),
# while the position settles at the slipped price — the two costs do NOT compound.
```

### WR-02: Decimal config values are round-tripped through float() in the fee/slippage init path

**File:** `itrader/execution_handler/exchanges/simulated.py:497,500-501,519-524,529-531`
**Issue:** The init path narrows configured `Decimal` rates to `float` before passing
them on, e.g. `PercentFeeModel(fee_rate=float(config.fee_rate if ... ))`. The receiving
models then re-enter the Decimal domain via `to_money(x)` → `Decimal(str(x))`. So a
configured `Decimal` flows `Decimal → float → Decimal(str(float))`. CLAUDE.md's money
policy is explicit: "NEVER call `Decimal(float)` directly (binary-float repr artifact)"
and "float for money is a correctness defect." For the values used by these scenarios
(`0.01`, `2`, `0.0001`, `50`) the `str(float())` round-trip happens to be lossless, so
no scenario is currently wrong. But the `float()` cast is a latent trap: a config value
whose float repr is not clean (e.g. `Decimal("0.07")`-class rates) can re-enter as a
binary-float artifact, silently breaking the hand-derivability guarantee this phase
exists to establish. This pre-dates Phase 7 but the phase now actively relies on this
path for correctness, raising the stakes.
**Fix:** Pass the `Decimal` through unchanged — both `PercentFeeModel` and the slippage
models already accept `float | Decimal` and call `to_money` internally:
```python
return PercentFeeModel(
    fee_rate=config.fee_rate if config.fee_rate is not None else Decimal("0.001"))
```
(and likewise for maker/taker/base/size/max/slippage_pct), dropping the `float()` cast.

### WR-03: commission merge key (entry_date, exit_date, side) is not guaranteed unique

**File:** `tests/e2e/conftest.py:325-342`
**Issue:** `_assemble` builds `commission_frame` from `portfolio.closed_positions` and
`trades.merge(..., on=["entry_date","exit_date","side"], how="left")`. If two distinct
closed positions share the same `(entry_date, exit_date, side)` — e.g. two round-trips
opened and closed on the same bars, or partial exits that collapse to the same dates —
the left merge becomes many-to-many and silently DUPLICATES trade rows (row-count
explosion) or mis-attributes commission. The parallel `attach_slippage` path shares the
same key assumption. No Phase 7 scenario triggers this (all are single round-trips), and
`_diff_frame` would catch a row-count drift against a frozen golden, so it is not an
active bug — but it is a latent correctness trap in shared harness infra that future
multi-trade leaves (Phase 8-9) could hit, and it would manifest as a confusing diff
rather than a clear error.
**Fix:** Either assert uniqueness before merging, or merge with validation so a
non-unique key fails loudly instead of duplicating:
```python
trades = trades.merge(
    commission_frame, on=["entry_date", "exit_date", "side"],
    how="left", validate="one_to_one")
```
(`pandas` raises `MergeError` on a many-to-many violation, converting a silent
mis-attribution into a hard, diagnosable failure.)

## Info

### IN-01: VERIFY-note column tables omit columns the frozen golden actually contains

**File:** `tests/e2e/sizing/over_cash_reject/scenario.py:57-58`, `tests/e2e/sltp/from_fill_held/scenario.py:74-77`
**Issue:** The illustrative order-mirror tables in these VERIFY notes show the columns
`role, ticker, order_type, action, status, price, quantity, filled_quantity` but OMIT
the trailing `time` column that `ORDER_SNAPSHOT_COLUMNS` defines and that the frozen
`golden/orders.csv` actually carries (e.g. `...,2020-01-02 01:00:00+01:00`). A reader
hand-checking the golden against the VERIFY table will find an "extra" column not
explained by the note. Purely a documentation/golden column-set mismatch — the goldens
are correct.
**Fix:** Add a `time` column to the illustrative tables (or a one-line note that the
real golden also pins the deterministic `time` identity column per
`ORDER_SNAPSHOT_COLUMNS`).

### IN-02: over_cash_reject VERIFY references engine line numbers that are not re-verified here

**File:** `tests/e2e/sizing/over_cash_reject/scenario.py:8,39,49`
**Issue:** The VERIFY note cites precise engine line numbers
(`order_manager.py:393-414`) for the cash-reservation rejection path. Such pinned line
references drift as the codebase evolves and become misleading without notice. The
behavioral assertion (REJECTED order, untouched cash) is correct and golden-locked; the
line citations are the fragile part. This convention is used project-wide (decision-tag
anchoring), so this is informational, not a defect.
**Fix:** Prefer anchoring to a stable symbol/decision tag (e.g. "the cash-reservation
admission gate, D-15") over a numeric line range, or accept that these citations are
best-effort and may drift.

---

_Reviewed: 2026-06-10_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_

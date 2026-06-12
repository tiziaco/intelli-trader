---
phase: 05-naming-encapsulation
fixed_at: 2026-06-11T19:04:52Z
review_path: .planning/phases/05-naming-encapsulation/05-REVIEW.md
iteration: 1
findings_in_scope: 1
fixed: 1
skipped: 0
status: all_fixed
---

# Phase 05: Code Review Fix Report

**Fixed at:** 2026-06-11T19:04:52Z
**Source review:** .planning/phases/05-naming-encapsulation/05-REVIEW.md
**Iteration:** 1

**Summary:**
- Findings in scope (critical_warning): 1
- Fixed: 1
- Skipped: 0

## Fixed Issues

### WR-01: `register_symbol` seam is bypassed by `update_config`, silently dropping registered symbols

**Files modified:** `itrader/execution_handler/exchanges/simulated.py`
**Commit:** 3ec74a6
**Applied fix:** Documented the durability boundary on the `register_symbol`
docstring (the reviewer's explicit second alternative), rather than changing
`update_config` behavior.

**Why not the union code change:** The review's primary suggestion — have the
`update_config` limits block *union* rather than *replace* `_supported_symbols`
— was applied first (commit `e137dc4`) and then **reverted**. The union changes
the intended replace-on-reconfigure contract of `update_config(supported_symbols=…)`
and broke two tests that encode it:

- `tests/unit/execution/exchanges/test_simulated_exchange.py::TestSimulatedExchangeConfiguration::test_update_config_limits`
  — asserts `get_supported_symbols()` equals exactly the new symbol set after a
  reconfigure (union leaks the default-config symbols back in).
- `tests/unit/execution/exchanges/test_simulated_exchange.py::test_rejected_market_order_emits_refused_fill`
  — narrows the exchange to `{BTCUSDT}` via `update_config` to test
  unsupported-symbol rejection; union re-admits the default `ETHUSDT`, so the
  expected `REFUSED` fill never fires.

These tests prove the drop-on-reconfigure behavior is **intentional and
covered**, so under the milestone's behavior-preserving contract the union fix
is a regression, not an improvement. The reviewer anticipated this: *"If the
drop-on-reconfigure behavior is intentional, state it explicitly in the
`register_symbol` docstring."* That is the resolution shipped here — the
docstring no longer implies durability and now names the two covering tests.

**Verification:** `mypy --strict` clean (162 files); full suite **844 passed**;
golden-master oracle byte-exact (134 trades / final_equity 46189.87730727451).

## Skipped Issues

The three INFO-tier findings are out of the `critical_warning` fix scope (run
`/gsd:code-review 05 --fix --all` to include them). All are cosmetic and
non-behavioral:

### IN-01: `SMA_MACD` logger component name not updated to the new class name
**File:** `itrader/strategy_handler/strategies/SMA_MACD_strategy.py:13`
**Reason:** Info-tier, out of scope. Stale `component="SMA_MACD_strategy"` log label.

### IN-02: Stale class/field names in crossval & normalize comments
**File:** `scripts/crossval/*`, `scripts/normalize_data.py`, `scripts/run_backtest.py`
**Reason:** Info-tier, out of scope. Comment wording cites old `FAST/SLOW/WIN`; no executable reference broken.

### IN-03: `test_universe_spans` comment references a removed `WR-02` tag
**File:** `tests/integration/test_universe_spans.py:144`
**Reason:** Info-tier, out of scope. Stale finding-ID prefix in a comment.

---

_Fixed: 2026-06-11T19:04:52Z_
_Fixer: Claude (gsd-code-review --fix --auto, orchestrator-adjudicated)_
_Iteration: 1_

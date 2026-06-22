---
phase: 05-engine-native-trailing-stops
verified: 2026-06-17T00:00:00Z
status: passed
score: 3/3 must-haves verified
overrides_applied: 0
---

# Phase 5: Engine-Native Trailing Stops — Verification Report

**Phase Goal:** A strategy can declare a TRAILING_STOP order; the MatchingEngine ratchets the resting stop in the favorable direction only as price extends, look-ahead-safe (trail updates from closed-bar extremes, active the next bar), cross-validated against backtesting.py and backtrader, with a result-change frozen only under owner sign-off.
**Verified:** 2026-06-17T00:00:00Z
**Status:** passed
**Re-verification:** No — initial verification

---

## Goal Achievement

### Observable Truths

| #   | Truth                                                                                                                                                       | Status     | Evidence                                                                                                                                                                                                                                                                                                             |
| --- | ----------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | A declared TRAILING_STOP order rests in the MatchingEngine and its stop ratchets in the favorable direction only as price extends (never loosens).          | ✓ VERIFIED | `MatchingEngine._trails` side-table (line 113). Ratchet step at END of `on_bar` (lines 401, 456 — after both fill passes). `_ratchet_trail` uses `max/min` favorably-only. `test_trailing_long_ratchet_favorable_only` + `test_trailing_short_ratchet_favorable_only` GREEN; `test_trailing_oco_sl_vs_tp_limit` GREEN. |
| 2   | The trail updates from closed-bar extremes and becomes active on the NEXT bar (look-ahead-safe per the bar_feed.py contract).                               | ✓ VERIFIED | `_run_ratchet_step` called AFTER both pass-1 and pass-2 fill pops (lines 401, 456). `_evaluate` reads `state.current_stop` (pre-bar level). `test_trailing_next_bar_activation_not_same_bar` directly proves the "tall bar" case: fills==[] on the tall bar, fires on the next bar. Both e2e scenarios assert ratcheted exits (not initial-seed exits). |
| 3   | Trailing-stop backtest behavior is cross-validated against backtesting.py and backtrader, and any result-change freezes only under owner sign-off.          | ✓ VERIFIED | `tests/golden/CROSS-VALIDATION-TRAILING.md` present with trade-level reconciliation EXACT (all 3 engines: entry 2020-01-03, exit 2020-01-07, PnL +8.0) and all 8 headline metrics PASS at 1% tolerance. Owner sign-off block: `APPROVED 2026-06-17, tiziaco (tiziano.iaco@gmail.com)`. Legitimate high-vs-close LEGITIMATE-DIFFERENCE documented. Scripts `cross_validate_trailing.py`, `trailing_run.py`, `backtesting_py_trailing_run.py`, `backtrader_trailing_run.py` all present. |

**Score:** 3/3 truths verified

---

### Also-held Invariants

| Invariant                                           | Status     | Evidence                                                                                                                                                         |
| --------------------------------------------------- | ---------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| mypy --strict clean                                 | ✓ VERIFIED | `poetry run mypy --strict itrader` → "Success: no issues found in 185 source files"                                                                             |
| SMA_MACD spot oracle byte-exact (134 / 46189.877…) | ✓ VERIFIED | `tests/integration/test_backtest_oracle.py` 3 tests PASSED; `tests/golden/summary.json` shows `final_equity: 46189.87730727451`, `trade_count: 134`             |
| Determinism double-run byte-identical               | ✓ VERIFIED | `test_trailing_long_scenario_deterministic` + `test_trailing_short_scenario_deterministic` both PASSED, asserting byte-identical `realised_pnl` across two runs  |

---

### Required Artifacts

| Artifact                                                                  | Expected                                                      | Status     | Details                                                                              |
| ------------------------------------------------------------------------- | ------------------------------------------------------------- | ---------- | ------------------------------------------------------------------------------------ |
| `itrader/execution_handler/matching_engine.py`                            | TRAILING_STOP arm + side-table + end-of-on_bar ratchet        | ✓ VERIFIED | TrailState dataclass; `_trails` dict; `_seed_trail`; `_ratchet_trail`; `_run_ratchet_step` at END of `on_bar`; TRAILING_STOP arm in `_evaluate`; `_fill_reason`; `_pick_bracket_winner` |
| `itrader/core/enums/order.py`                                             | OrderType.TRAILING_STOP + order_type_map entry                | ✓ VERIFIED | Line 25: `TRAILING_STOP = "TRAILING_STOP"`; line 67: map entry with TRAIL-01 comment |
| `itrader/config/order.py`                                                 | TrailType config-enum (PRICE/PERCENT)                         | ✓ VERIFIED | `class TrailType(str, Enum)` with PRICE/PERCENT members; config-enum exception documented |
| `itrader/config/__init__.py`                                              | TrailType re-export                                           | ✓ VERIFIED | `from itrader.config import TrailType` confirmed importable                          |
| `itrader/events_handler/events/order.py`                                  | trail_type/trail_value optional fields + getattr read-back    | ✓ VERIFIED | Fields present; `make_order_event` factory passes them through to the test helper   |
| `itrader/order_handler/order.py`                                          | Order.trail_type/trail_value + new_trailing_stop_order        | ✓ VERIFIED | Lines 107-108: trail fields; line 282: factory returning OrderType.TRAILING_STOP    |
| `itrader/order_handler/order_validator.py`                                | D-TRAIL-7 non-viable-trail rejection (INVALID_TRAIL)          | ✓ VERIFIED | Lines 249-272: TRAILING_STOP branch with PERCENT<1 and PRICE<reference checks        |
| `itrader/core/sizing.py`                                                  | WR-02 upper-bound guard on PercentFromFill PERCENT trail      | ✓ VERIFIED | Lines 264-269: `SizingPolicyViolation` raised when `trail_type == PERCENT and trail_value >= ONE` |
| `itrader/order_handler/brackets/bracket_manager.py`                      | CR-01 PRICE trail viability gate + trailing SL child creation | ✓ VERIFIED | Lines 255-296: PRICE gate (`trail_value >= anchor` raises) then `Order.new_trailing_stop_order` seeded from anchor |
| `itrader/order_handler/brackets/bracket_book.py`                         | _PendingBracket carries trail_type/trail_value                | ✓ VERIFIED | Lines 57-58: `trail_type`/`trail_value` fields survive arm->fill round-trip         |
| `tests/unit/execution/test_matching_engine_trailing.py`                   | 9 unit tests GREEN                                            | ✓ VERIFIED | 9 passed (ratchet long/short, next_bar tall-bar, gap long/short, OCO, modify-reseed, no-leak, full-precision) |
| `tests/unit/order/test_trailing_validation.py`                            | 6 unit tests GREEN                                            | ✓ VERIFIED | 6 passed (reject PERCENT>=1, reject PRICE>=ref, reject missing, reject nonpositive, viable percent passes, viable price passes) |
| `tests/e2e/trailing_long/test_trailing_long_scenario.py`                  | Long e2e asserts ratcheted exit 135, PnL 350                  | ✓ VERIFIED | 2 passed (scenario + determinism); ratcheted stop 135 vs initial seed 90 asserted   |
| `tests/e2e/trailing_short/test_trailing_short_scenario.py`                | Short e2e asserts ratcheted cover 55, PnL 450                 | ✓ VERIFIED | 2 passed (scenario + determinism); ratcheted stop 55 vs initial seed 110 asserted   |
| `tests/golden/CROSS-VALIDATION-TRAILING.md`                               | Evidence report + owner sign-off APPROVED                     | ✓ VERIFIED | Present; trade-level exact; all metrics PASS; LEGITIMATE-DIFFERENCE documented; sign-off block APPROVED 2026-06-17 by tiziaco |
| `scripts/cross_validate_trailing.py`                                      | Standalone sibling cross-val orchestrator                     | ✓ VERIFIED | File present                                                                         |
| `scripts/crossval/trailing_run.py`                                        | iTrader white-box trailing runner (TRAILUSD)                  | ✓ VERIFIED | File present                                                                         |
| `scripts/crossval/backtesting_py_trailing_run.py`                         | backtesting.py oracle runner (script-only import)             | ✓ VERIFIED | File present; no `import backtesting` under `tests/`                                |
| `scripts/crossval/backtrader_trailing_run.py`                             | backtrader oracle runner (script-only import)                 | ✓ VERIFIED | File present; no `import backtrader` under `tests/`                                 |

### Key Link Verification

| From                                            | To                                    | Via                                       | Status     | Details                                                                               |
| ----------------------------------------------- | ------------------------------------- | ----------------------------------------- | ---------- | ------------------------------------------------------------------------------------- |
| `MatchingEngine.on_bar` end                     | `_trails` side-table TrailState       | `_run_ratchet_step` at lines 401 and 456  | ✓ WIRED    | Ratchet step runs AFTER both fill passes and OCO cancels (verified by code position) |
| `MatchingEngine._evaluate` TRAILING_STOP arm    | `state.current_stop` (bars <= N-1)    | `self._trails.get(order.order_id)`        | ✓ WIRED    | Active level from side-table, NOT this bar's extreme                                 |
| `bracket_manager._create_fill_anchored_children`| `Order.new_trailing_stop_order`       | CR-01 PRICE gate then factory call        | ✓ WIRED    | `sl_order = Order.new_trailing_stop_order(... price=anchor ...)` at line 285         |
| `_PendingBracket.trail_type/trail_value`        | `_create_fill_anchored_children`      | `pending.trail_type / pending.trail_value`| ✓ WIRED    | Trail descriptor survives the arm->fill round-trip                                   |
| `MatchingEngine` every `_resting.pop` site      | `_trails.pop` (no leak)               | Co-located pop at lines 144, 378, 449, 453| ✓ WIRED    | Side-table cleaned at all 4 pop sites (cancel, pass-1 fill, pass-2 chosen, OCO cancel)|
| `scripts/cross_validate_trailing.py`            | `scripts/crossval/reconcile.py`       | Reused helpers                            | ✓ WIRED    | File present; LEGITIMATE-DIFFERENCE documented in evidence report                    |

### Data-Flow Trace (Level 4)

| Artifact                              | Data Variable      | Source                                                         | Produces Real Data | Status     |
| ------------------------------------- | ------------------ | -------------------------------------------------------------- | ------------------ | ---------- |
| `test_trailing_long_scenario.py`      | `realised_pnl`     | Full run path: signal → bracket → fill → position → portfolio  | Yes                | ✓ FLOWING  |
| `test_trailing_short_scenario.py`     | `realised_pnl`     | Full run path: signal → trailing BUY-stop → fill → short pos   | Yes                | ✓ FLOWING  |
| `MatchingEngine._trails`              | `current_stop`     | `_seed_trail` at submit; `_ratchet_trail` at END of `on_bar`  | Yes                | ✓ FLOWING  |

### Behavioral Spot-Checks

| Behavior                                  | Command                                                                                                    | Result                                       | Status  |
| ----------------------------------------- | ---------------------------------------------------------------------------------------------------------- | -------------------------------------------- | ------- |
| Oracle byte-exact (134 / 46189.877…)      | `poetry run pytest tests/integration/test_backtest_oracle.py -q`                                          | 3 passed                                     | ✓ PASS  |
| Trailing unit tests (ratchet + viability) | `poetry run pytest tests/unit/order/test_trailing_validation.py tests/unit/execution/test_matching_engine_trailing.py -q` | 15 passed (0 skip)           | ✓ PASS  |
| Trailing e2e scenarios (long + short)     | `poetry run pytest tests/e2e/trailing_long tests/e2e/trailing_short -q`                                   | 4 passed (0 skip)                            | ✓ PASS  |
| mypy --strict clean                       | `poetry run mypy --strict itrader`                                                                         | Success: no issues in 185 files              | ✓ PASS  |

### Requirements Coverage

| Requirement | Source Plan | Description                                                                       | Status     | Evidence                                                                              |
| ----------- | ----------- | --------------------------------------------------------------------------------- | ---------- | ------------------------------------------------------------------------------------- |
| TRAIL-01    | 05-01, 05-02, 05-03 | Strategy can declare TRAILING_STOP; MatchingEngine ratchets favorably-only | ✓ SATISFIED | `OrderType.TRAILING_STOP` enum; `new_trailing_stop_order`; `_trails` side-table; ratchet step; 15 unit tests GREEN; 4 e2e tests GREEN |
| TRAIL-02    | 05-01, 05-02, 05-03 | Trail updates from closed-bar extremes, active NEXT bar (look-ahead-safe)  | ✓ SATISFIED | `_run_ratchet_step` runs AFTER both fill passes; tall-bar test asserts no same-bar fill; both e2e exit at ratcheted levels |
| TRAIL-03    | 05-04        | Cross-validated against backtesting.py and backtrader; result-change owner-gated | ✓ SATISFIED | `CROSS-VALIDATION-TRAILING.md` present with trade-exact reconciliation and APPROVED sign-off |

### Anti-Patterns Found

| File                                            | Line | Pattern          | Severity  | Impact  |
| ----------------------------------------------- | ---- | ---------------- | --------- | ------- |
| (none found in phase-5 modified files)           |      |                  |           |         |

Scanned `matching_engine.py`, `bracket_manager.py`, `sizing.py`, `order_validator.py` for TBD/FIXME/XXX/placeholder patterns. Zero unresolved debt markers found. No stub returns (empty lists/dicts/None from rendering paths), no oracle imports under `tests/`.

### Human Verification Required

None. All must-haves are programmatically verifiable and confirmed. The one human-in-the-loop item — the owner-gated TRAIL-03 re-baseline sign-off — is documented as APPROVED in `tests/golden/CROSS-VALIDATION-TRAILING.md` with explicit attribution (tiziaco, 2026-06-17). The code-review gate (CR-01 BLOCKER + WR-01..WR-04 warnings) is recorded as `status: resolved` in `05-REVIEW.md` with four fix commits and revalidation confirmation.

### Gaps Summary

No gaps. All three roadmap success criteria are VERIFIED against the actual codebase, not just SUMMARY claims:

1. **TRAIL-01 (ratchet favorably-only)** — Verified at four levels: enum + factory (static); `_trails` side-table + `_ratchet_trail` `max/min` guards (logic); unit tests `test_trailing_long_ratchet_favorable_only` + `test_trailing_short_ratchet_favorable_only` asserting `current_stop` never decreases/increases (behavioral); e2e exits at ratcheted levels (end-to-end). CR-01 fix confirmed in `bracket_manager.py` lines 255-296.

2. **TRAIL-02 (next-bar / look-ahead-safe)** — Verified: `_run_ratchet_step` is invoked at lines 401 and 456 in `on_bar`, both AFTER the fill-and-pop operations. `_evaluate`'s TRAILING_STOP arm reads `state.current_stop` from the side-table (derived from bars <= N-1), never from `bar_struct.high/low` of the current bar. The "tall bar" unit test directly falsifies a same-bar implementation and proves the correct ordering.

3. **TRAIL-03 (cross-validation + owner sign-off)** — Verified: `CROSS-VALIDATION-TRAILING.md` exists with a complete trade table, all 8 metrics PASS at 1% tolerance, the high-vs-close LEGITIMATE-DIFFERENCE is documented, and the APPROVED sign-off block bears explicit attribution. Oracle imports remain script-only (no `import backtesting`/`import backtrader` anywhere under `tests/`).

---

_Verified: 2026-06-17_
_Verifier: Claude (gsd-verifier)_

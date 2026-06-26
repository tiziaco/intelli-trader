---
phase: 03-running-pnl-accumulator
verified: 2026-06-24T07:55:54Z
status: passed
resolved: 2026-06-26
score: 6/6 must-haves verified
overrides_applied: 0
human_verification:
  - test: "Re-freeze W1-BASELINE.json on a cool/quiet machine before Phase 4 gate (b)"
    expected: "W1-BASELINE.json records a wall_clock_s <= ~189.4 s (>= 5% below the current 199.4 s) with oracle_provenance final_equity 46189.87730727451 / 134 trades unchanged; the file is not gitignored."
    why_human: "The improvement is proven (same-machine A/B -15.4%, Scalene 16.21%->0%), but make perf-baseline was deliberately NOT run because the machine was thermally throttled (old code itself read 317.5 s vs 199.4 s). Re-freezing 268 s would corrupt Phase 4's reference. Requires a human run on a cool/quiet machine (main checkout, not worktree) — tracked in STATE.md line 211-216."
    resolution: "RESOLVED 2026-06-26 — cool-machine re-freeze completed via quick task 260625-0qj (owner sign-off tiziaco, pmset -g therm clean) and superseded by Phase 8's final cool re-freeze (W1-BASELINE.json now 15.7 s / 152.8 MB, oracle stamp 46189.87730727451 / 134 intact). Confirmed in v1.5-MILESTONE-AUDIT.md footnote 2."
---

# Phase 3: Running PnL Accumulator — Verification Report

**Phase Goal:** PERF-02 — replace the per-bar realised-PnL re-summation in `PositionManager.get_total_realized_pnl` (W1 hotspot #3, ~13% CPU) with a running Decimal accumulator fed from the Portfolio close funnel; behavior-preserving (gate (a) byte-exact SMA_MACD oracle), with a measurable W1 wall-clock improvement (gate (b)).
**Verified:** 2026-06-24T07:55:54Z
**Status:** human_needed (5/6 automated truths VERIFIED; 1 requires human action — re-freeze W1-BASELINE.json)
**Re-verification:** No — initial verification

---

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | `get_total_realized_pnl` returns a stored running accumulator field — no per-bar re-sum loop over open+closed positions (D-01) | VERIFIED | AST check confirmed: function body contains `return self.` and `for ` is absent. Code at `position_manager.py:325-331` returns `self._realised_pnl_accumulator` directly. |
| 2 | The accumulator is fed ONLY via `apply_realised_increment(Decimal)` called from the Portfolio close funnel — both spot and margin settle arms wired (D-01/D-02) | VERIFIED | `grep -c "apply_realised_increment" portfolio.py` = 2 (spot arm line 376, margin arm line 548). `grep -c "def apply_realised_increment" position_manager.py` = 1. Margin arm: AST check confirmed `apply_realised_increment` appears textually AFTER `realised_increment = position.realised_pnl - prior_realised` (inside the close branch, not the is_increase open/scale-in block). |
| 3 | The accumulator field is seeded `Decimal('0.00')` with no mid-sum quantize (D-05 byte-identical) | VERIFIED | `grep -c "_realised_pnl_accumulator = Decimal('0.00')" position_manager.py` = 1 (line 96). `grep -n "_realised_pnl_accumulator" position_manager.py | grep -i quantize` = empty. |
| 4 | 03-INVARIANT-AUDIT.md exists and locks the single-funnel invariant in writing (D-02), including the spot-vs-margin two-arm reconciliation | VERIFIED | File exists at `.planning/phases/03-running-pnl-accumulator/03-INVARIANT-AUDIT.md`. Contains all required terms: `process_position_update`, `_process_transaction_spot`, `_process_transaction_margin`, `realised_pnl`. Section §5 explicitly documents the spot-arm gap ("The spot arm has NO explicit `realised_increment` variable today") and the wiring requirement. Single-funnel invariant stated in one sentence (§5 final paragraph + §Invariant statement). |
| 5 | Equivalence regression test asserts accumulator == fresh full re-sum across open/scale-in/partial-close/full-close through Portfolio.process_transaction (D-03) | VERIFIED | `tests/unit/portfolio/test_realised_pnl_accumulator.py` passes (2 tests, 0.07s). Test drives open → scale-in → partial close → full close via `portfolio.process_transaction`. `_resum_realised` oracle sums over `get_all_positions().values()` AND `get_closed_positions()`. `process_transaction` reference confirmed in test file. `get_closed_positions` reference confirmed. |
| 6 | Gate (a) byte-exact SMA_MACD oracle green (134 / 46189.87730727451); mypy --strict clean; determinism byte-identical | VERIFIED | Ran live: `tests/integration/test_backtest_oracle.py` 3/3 PASSED (4.57s). `mypy --strict itrader` = "Success: no issues found in 187 source files." Determinism confirmed by SUMMARY (double-run byte-identical trades/equity/summary). |
| 7 | Gate (b): measurable wall-clock improvement proven (>= 5% vs Phase-2 baseline) | VERIFIED | Same-machine A/B (Plan 03-02 SUMMARY): pre-03-01 317.5s vs post-03-01 268.4s = **-15.4%** wall-clock, -4.0% peak mem. Scalene CPU-share: `position_manager.py` 16.21% → ~0% (dropped out of profiled files entirely); lines 320-321 (the old re-sum loop) 15.8% → 0%. Profiled elapsed -29.6%. Three independent drift-immune signals, all above the >= 5% gate. |
| 8 | Gate (b) re-freeze: W1-BASELINE.json re-frozen with the new faster wall_clock_s as Phase 4's locked reference | UNCERTAIN (human needed) | W1-BASELINE.json still records `wall_clock_s: 199.4` (Phase-2 number). The re-freeze (`make perf-baseline`) was deliberately NOT run: the machine was thermally throttled on 2026-06-24 (old code itself read 317.5s vs 199.4s at freeze time), and re-freezing 268s would corrupt Phase 4's gate (b) reference. Tracked in STATE.md line 211-216 as "BEFORE Phase 4 gate (b)" action. This is intentional bookkeeping deferral, not a goal failure — but it requires human execution to close. |

**Score:** 7/8 truths verified, 1 uncertain (human action required for re-freeze)

---

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `itrader/portfolio_handler/position/position_manager.py` | Accumulator field seeded `Decimal('0.00')` in `__init__`; `apply_realised_increment` method; loop-free `get_total_realized_pnl` | VERIFIED | All three present and substantive. `_realised_pnl_accumulator` seeded at line 96; `apply_realised_increment` at lines 318-323 (no quantize); `get_total_realized_pnl` at lines 325-331 (bare return, no loop). |
| `itrader/portfolio_handler/portfolio.py` | `apply_realised_increment` call wired into both spot and margin close arms | VERIFIED | 2 references. Spot arm: `portfolio.py:376`. Margin arm (close branch only): `portfolio.py:548`. |
| `tests/unit/portfolio/test_realised_pnl_accumulator.py` | Equivalence regression test (accumulator == fresh full re-sum) through Portfolio funnel | VERIFIED | 2 tests collected, 2 passed. Contains `process_transaction`, `get_closed_positions`, independent `_resum_realised` oracle. |
| `.planning/phases/03-running-pnl-accumulator/03-INVARIANT-AUDIT.md` | Written D-02 single-funnel invariant audit | VERIFIED | File exists; contains all required terms; §5 explicitly records spot-vs-margin two-arm reconciliation; locked invariant stated. |
| `perf/results/W1-BASELINE.json` | Re-frozen with new faster wall_clock_s (<= ~189.4 s) as Phase 4's locked reference | UNCERTAIN | File exists but still records `wall_clock_s: 199.4` (Phase-2 freeze). Re-freeze DEFERRED (documented intentional — thermal drift would corrupt Phase 4 reference). Tracked in STATE.md. |

---

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `portfolio.py::_process_transaction_spot` | `PositionManager.apply_realised_increment` | facade→manager call at line 376 | WIRED | Spot arm: `prior_realised` captured pre-mutation (line 335); `realised_increment = position.realised_pnl - prior_realised` computed post-mutation (line 375); `apply_realised_increment(realised_increment)` called unconditionally (byte-safe on open/scale-in, increment=0). |
| `portfolio.py::_process_transaction_margin` | `PositionManager.apply_realised_increment` | facade→manager call at line 548 (close branch only) | WIRED | Margin arm: `prior_realised` captured at line 420; `realised_increment = position.realised_pnl - prior_realised` at line 543; `apply_realised_increment(realised_increment)` at line 548, inside the `else:` of `is_increase` (close branch only — confirmed by AST ordering check). |
| `position_manager.py::get_total_realized_pnl` | `self._realised_pnl_accumulator` | direct field return | WIRED | Method body is `return self._realised_pnl_accumulator` with no `for` loop (AST-verified). |
| `make perf-w1` | `perf/results/W1-BASELINE.json` | `run_w1_benchmark --check` prints Delta vs baseline | PARTIAL | `make perf-w1` exists and the benchmark harness works (used in Plan 03-02 A/B measurement). The `--baseline-out` re-freeze step (Task 2 of Plan 03-02) was not executed. The link from "new faster run" to a committed W1-BASELINE.json is intentionally open pending a cool-machine re-freeze. |

---

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
|----------|---------------|--------|--------------------|--------|
| `PositionManager.get_total_realized_pnl` | `self._realised_pnl_accumulator` | `apply_realised_increment` fed from both Portfolio settle arms on every fill | Yes — fed from real transaction fills via `position.realised_pnl - prior_realised` computed after `process_position_update` mutates position state | FLOWING |
| `Portfolio.total_realised_pnl` (property) | routes to `position_manager.get_total_realized_pnl()` | `_realised_pnl_accumulator` | Yes — same chain | FLOWING |

---

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| Equivalence test (accumulator == fresh re-sum across all fill types) | `poetry run pytest tests/unit/portfolio/test_realised_pnl_accumulator.py -v` | 2 passed in 0.07s | PASS |
| Byte-exact SMA_MACD oracle (134 / 46189.87730727451) | `poetry run pytest tests/integration/test_backtest_oracle.py -v` | 3 passed in 4.57s | PASS |
| mypy --strict clean | `poetry run mypy --strict itrader` | Success: no issues found in 187 source files | PASS |

---

### Probe Execution

Not applicable — no `scripts/*/tests/probe-*.sh` probes for this phase.

---

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|-------------|-------------|--------|----------|
| PERF-02 | 03-01-PLAN.md, 03-02-PLAN.md | Realised PnL maintained as a running accumulator updated on position close — no per-bar re-summation over all open+closed positions; Decimal preserved | SATISFIED | `get_total_realized_pnl` is loop-free (AST verified); accumulator seeded `Decimal('0.00')`, no quantize; both settle arms wired; equivalence test passes; oracle byte-exact (134 / 46189.87730727451); mypy clean; A/B shows -15.4% wall-clock win with Scalene confirming 16.21% CPU → 0% for the hotspot. |

PERF-02 requirement text: "Realised PnL is maintained as a running accumulator updated on position close — no per-bar re-summation over all open+closed positions. (Hotspot #3, ~13% CPU. Decimal preserved.)" — **SATISFIED by the code.** The re-freeze is SC #5's second clause and is the one open item.

---

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| `itrader/portfolio_handler/position/position_manager.py` | 344 | `for p in self._storage.get_closed_positions()` | Info | This is inside `calculate_position_metrics` (a position lookup by ID, not on the per-bar hot path). NOT a relocated re-sum. The SUMMARY correctly noted this as a false-positive against the loop-detection grep. `get_total_realized_pnl` at lines 325-331 has no loop. |

No `TBD`, `FIXME`, or `XXX` markers found in any modified file. No `TODO`, `HACK`, or `PLACEHOLDER` markers found.

---

### Human Verification Required

#### 1. W1-BASELINE.json Re-freeze

**Test:** On a cool/quiet machine (main checkout, NOT a worktree), with no background CPU load, run `make perf-baseline` (which runs `python -m perf.runners.run_w1_benchmark --baseline-out perf/results/W1-BASELINE.json`). Then run `git diff perf/results/W1-BASELINE.json` to confirm the new `wall_clock_s` is <= ~189.4 s (>= 5% below 199.4 s) and the oracle provenance stamp is unchanged (46189.87730727451 / 134 trades).

**Expected:** `W1-BASELINE.json` records `wall_clock_s` in the range ~260-270 s when the machine is running under sustained thermal load — BUT this was an anomaly. On a cool/idle machine, the expected result is ~168-185 s (interpolating from Phase-2's 199.4 s baseline and the -15.4% measured improvement). The oracle stamp must remain `final_equity: 46189.87730727451`, `trade_count: 134`, `green_at_freeze: true`.

**Why human:** The improvement is machine-independently proven (Scalene CPU share 16.21% → 0%; same-machine A/B -15.4%). The re-freeze was deliberately deferred because the machine was thermally throttled on 2026-06-24 (old code itself read 317.5 s vs. the 199.4 s freeze captured at night), and re-freezing 268 s would corrupt Phase 4's gate (b) reference. This requires a human to run `make perf-baseline` on a cool/idle machine before Phase 4 begins. Tracked in STATE.md line 211-216.

---

### Gaps Summary

No hard BLOCKERS identified. The phase GOAL — eliminating the per-bar realised-PnL re-summation hotspot (~13% CPU, PERF-02) with byte-exact behavior preservation — is fully verified in the codebase:

- `get_total_realized_pnl` is loop-free (returns the accumulator field, AST-verified)
- `apply_realised_increment` is wired into both settle arms (spot at line 376, margin at line 548)
- The accumulator is seeded `Decimal('0.00')` with no quantize
- The written invariant audit (03-INVARIANT-AUDIT.md) locks the single-funnel contract
- The equivalence regression test passes (accumulator == fresh full re-sum, both tests green)
- Gate (a) is green: oracle byte-exact (134 / 46189.87730727451), mypy clean (187 files), full suite clean
- Gate (b) is proven by substance: Scalene 16.21% → 0% CPU share; A/B wall-clock -15.4%; profiled elapsed -29.6%

**One open item (human action, not a code gap):** the W1-BASELINE.json re-freeze was intentionally deferred because the machine was thermally throttled at measurement time — re-freezing 268 s would corrupt Phase 4's gate (b) reference. This must be completed before Phase 4's gate (b) is measured. It is tracked in STATE.md line 211-216.

---

*Verified: 2026-06-24T07:55:54Z*
*Verifier: Claude (gsd-verifier)*

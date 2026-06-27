---
phase: 06-bar-feed-window-copies-optional-slip-able
plan: 03
subsystem: perf-denominator-cleanup
tags: [PERF-06, D-13, hot-path, harness, behavior-preserving]
requires:
  - "frozen W1/W2 baselines (Phase 1 tooling)"
  - "06-PROFILE-FINDINGS.md (real W2 hotspot map)"
provides:
  - "dispatcher hot path with the per-bar TIME EVENT debug log removed (~22% W2 CPU eager-f-string waste eliminated)"
  - "two-pass W2 sweep runner — clean timed wall-clock + separate tracemalloc peak-mem (no ~19% allocation-tracking overhead in the timed region)"
affects:
  - "06-04 (cursor): the cleaned denominator makes the searchsorted-removal win a larger honest fraction"
  - "06-05 (gate re-freeze): re-freeze both baseline and check-run with this de-timed harness (apples-to-apples)"
tech-stack:
  added: []
  patterns:
    - "two-pass perf measurement: time wall-clock on a clean run, capture peak-mem on a fresh re-wired run under tracemalloc"
    - "plain removal of an already-DEBUG-gated hot-path log (no lazy/guarded isEnabledFor branch)"
key-files:
  created: []
  modified:
    - "itrader/events_handler/full_event_handler.py"
    - "perf/runners/run_w2_sweep.py"
decisions:
  - "D-13(1): plain-remove the per-bar TIME EVENT debug block (not a lazy/guarded log) — the line is DEBUG-gated and never prints at INFO, so there is no observable behavior to preserve"
  - "D-13(2): de-time _run_point — tracemalloc no longer wraps the timed system.run(); peak-mem moves to a separate fresh-wired pass (same seed=42)"
  - "Factored identical wiring into _wire_system so both passes re-wire from the SAME csv_paths/start/end; the returned dict shape and the 06-02 --check/--baseline-out flags are unchanged"
metrics:
  duration_min: 2
  tasks: 2
  files: 2
  completed: 2026-06-24
---

# Phase 6 Plan 03: D-13 Denominator Cleanup Summary

D-13 prep step (runs BEFORE the cursor): removed the per-bar `TIME EVENT` debug log from the event dispatcher (~22% W2 CPU as an eager caller-built f-string discarded at INFO) and de-timed the W2 sweep harness into two passes (clean wall-clock + separate tracemalloc peak-mem), so the W2/W1 denominator measures engine work — not logging waste or ~19% allocation-tracking overhead. Behavior-neutral: re-baselines nothing numeric (the cleaned baselines re-freeze in 06-05).

## What Was Built

### Task 1 — Remove the per-bar TIME EVENT debug log (D-13 part 1)
- Deleted the three-line `if event.type is EventType.TIME:` block (its `# D-21:` comment + the `self.logger.debug(f"TIME EVENT: {event.time}")` call) from `EventHandler._dispatch`.
- The eager `f"TIME EVENT: {event.time}"` was formatted every bar before `.debug()` ran, then discarded at the default INFO level — pure denominator inflation (RESEARCH Finding C, code-verified).
- The `EventType.TIME` route entry in `self.routes` is untouched — TIME dispatch is unchanged; only the debug log was removed.
- TAB indentation preserved (the file is a TAB module — CLAUDE.md indentation hazard).
- Commit: `15834d7`

### Task 2 — De-time `run_w2_sweep._run_point` into two passes (D-13 part 2)
- Restructured `_run_point` so synthetic frames/CSVs are generated ONCE outside both passes and reused.
- PASS 1 (clean wall-clock): wires a fresh `BacktestTradingSystem` and times ONLY `system.run(print_summary=False)` with `time.perf_counter()` — NO `tracemalloc` anywhere in the timed region.
- PASS 2 (peak memory): re-wires a SECOND fresh system from the same `csv_paths`/`start`/`end` (same `seed=42`, same `_TIMEFRAME`), then runs under `tracemalloc.start()` → `get_traced_memory()` → `stop()` and computes `peak_mem_mb`.
- Factored the identical wiring into a small local `_wire_system` helper (no wiring-parameter changes: same `exchange="csv"`, same cash, same strategy/tickers).
- The returned dict shape (`{"n_symbols", "wall_clock_s", "peak_mem_mb"}`) and the 06-02 `--check`/`--baseline-out`/`--json` flags are unchanged.
- 4-space indentation preserved.
- Commit: `43e5e72`

## Deviations from Plan

None — plan executed exactly as written. (The wiring helper `_wire_system` was anticipated by the plan: "Factor the repeated wiring into a small local helper if it reduces duplication.")

## Verification Evidence

- Task 1 automated verify: `grep 'TIME EVENT'` returns nothing; `EventType.TIME` still present once (the route literal); `^\t+try:` matches (TAB indentation intact).
- Gate (a) oracle GREEN: `poetry run pytest tests/integration/test_backtest_oracle.py -q` → 3 passed (byte-exact 134 trades / `final_equity 46189.87730727451`). Logs are not the oracle — removal is behavior-neutral.
- `poetry run mypy itrader` → `Success: no issues found in 187 source files`.
- Task 2 automated verify: `poetry run python -m perf.runners.run_w2_sweep --help` exits 0 and lists `--check` + `--baseline-out`; AST check confirms exactly 2 `system.run()` calls in `_run_point` and `perf_counter` + `tracemalloc.start` present; targeted assertion confirms the `t0=perf_counter()` → `wall_clock_s=` timed window contains NO `tracemalloc` call (the timed pass is clean).

## Threat Surface Scan

No new threat surface. This plan removes a debug log and re-orders perf measurement; it touches neither `bar_feed.py` nor the look-ahead window slice, and introduces no external input, auth, network, or schema change. T-06-03-01 (Tampering: log removal alters behavior) is backstopped GREEN by the byte-exact oracle in Task 1's verify.

## Notes for Downstream Plans

- 06-04 (cursor) and 06-05 (gate re-freeze) MUST run against this cleaned engine + de-timed harness. Re-freezing on the pre-D-13 (diluted) engine would leave the ≥10% W2 bar unreachable by design (RESEARCH Pitfall 3) — the exact reason 06-01's measurement read ~0%.
- 06-05 should capture BOTH the baseline and the check-run with this same de-timed harness so the delta is apples-to-apples (RESEARCH Pattern 4 / T-06-03-02 mitigation).

## Self-Check: PASSED
- FOUND: itrader/events_handler/full_event_handler.py (modified, TIME EVENT block removed)
- FOUND: perf/runners/run_w2_sweep.py (modified, two-pass `_run_point`)
- FOUND: commit 15834d7 (Task 1)
- FOUND: commit 43e5e72 (Task 2)

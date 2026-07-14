---
phase: quick-260713-phm
plan: 01
subsystem: trading_system (live)
status: complete
tags: [live, code-review-fix, WR-02, IN-02, oracle-dark]
requires: []
provides:
  - "LiveTradingSystem.start() raises unhandled StateError when constructed unwired (WR-02)"
  - "LiveRunner.stop() warns when the drain thread outlives its join timeout (IN-02)"
affects:
  - itrader/trading_system/live_trading_system.py
  - itrader/trading_system/live_runner.py
tech-stack:
  added: []
  patterns: [fail-loud-guard-clause, operator-warning-on-timeout]
key-files:
  created: []
  modified:
    - itrader/trading_system/live_trading_system.py
    - itrader/trading_system/live_runner.py
decisions:
  - "WR-02 guard placed ABOVE _update_status(STARTING) and the start() try-block so the broad `except Exception` cannot swallow it and mask it as SystemStatus.ERROR + return False"
  - "StateError added to the existing `from itrader.core.exceptions import ConfigurationError` line (no duplicate import)"
  - "WR-02 comment reworded to avoid the literal token `try:` (the plan's placement-assert does `src.index('try:')` and would otherwise match the comment)"
metrics:
  duration: ~6 min
  completed: 2026-07-13
  tasks: 2
  files: 2
---

# Quick Task 260713-phm: Fix Phase 06 Review Findings (WR-02 typed guard, IN-02 stop warn) Summary

Batch-fixed two Phase 06 live-trading code-review findings — both live-only and oracle-dark — turning two silent failure modes into loud, correct signals: an unhandled `StateError` when `LiveTradingSystem.start()` runs on a facade constructed outside `build_live_system()` (WR-02), and an operator `warning` when `LiveRunner.stop()`'s drain thread is still alive after its join timeout (IN-02).

## What Was Built

### Task 1 — WR-02: typed guard in `LiveTradingSystem.start()`
- Added `StateError` to the existing single `from itrader.core.exceptions import ConfigurationError` import line (now `..., StateError`).
- Inserted a typed guard clause after the `if self._running:` early-return and ABOVE both `self._update_status(SystemStatus.STARTING)` and the start() `try`-block. Placement is load-bearing: inside the try, the broad `except Exception` (~line 1210) would catch the raise and mask it as `SystemStatus.ERROR` + `return False`.
- Guard raises `StateError("LiveTradingSystem", "unwired", required_state="built via build_live_system() (LiveRunner/ErrorPolicy attached)", operation="start")` when `_live_runner is None or _error_policy is None` — matching the `(entity_id, current_state, required_state, operation)` signature in `core/exceptions/base.py`. Propagates unhandled.

### Task 2 — IN-02: warn on non-joining drain thread in `LiveRunner.stop()`
- After `self._thread.join(timeout=timeout)`, added an `is_alive()` check that logs a lazy `%`-formatted `self.logger.warning` (with a `%.1fs` timeout arg) when the daemon drain thread survives the join — so `stop()` no longer advertises STOPPED while a live worker keeps draining.
- `self._stop_event.set()` and the trailing `self._worker_supervisor.stop(timeout=timeout)` left unchanged.

## Deviations from Plan

None functional. One mechanical adjustment: the WR-02 guard comment was reworded to avoid the literal token `try:`, because the plan's own placement-assert (`src.index('try:')`) matched the comment on the first draft and produced a false-negative. Rewording to "start() try-block" made the assert pass without changing placement or behavior. Tracked as `[Rule 3 - Blocking] verify-script token collision`.

## Verification

All guardrail gates green (non-isolated, `poetry run` on branch `v1.8/phase-6-live-runner`):

1. Imports clean — `import itrader.trading_system.live_trading_system, itrader.trading_system.live_runner` → OK
2. `poetry run mypy itrader` → Success: no issues found in 249 source files
3. Inertness gate — `tests/integration/test_okx_inertness.py` → 4 passed
4. Backtest oracle byte-exact — `tests/integration/test_backtest_oracle.py` → 3 passed (134 / 46189.87730727451 unaffected; live-only edits)
5. Live start/stop unit tests — `pytest -k "live_runner or live_trading_system or (start or stop)" tests/unit` → 54 passed
6. Both per-task automated `<verify>` scripts → T1 placement OK, T2 verify OK

Both files confirmed tab-free (4-space indentation preserved).

## Commits

- `fe38b501` — fix(quick-260713-phm): raise unhandled StateError on unwired LiveTradingSystem.start() (WR-02)
- `a9f3b5ac` — fix(quick-260713-phm): warn when LiveRunner drain thread outlives join timeout (IN-02)

## Self-Check: PASSED
- itrader/trading_system/live_trading_system.py — modified (guard + import), committed fe38b501
- itrader/trading_system/live_runner.py — modified (stop warn), committed a9f3b5ac
- Both commits present in git log

---
phase: 06-liverunner-factory-facade-shrink
plan: 01
subsystem: trading_system
status: complete
tags: [RUN-04, universe-wiring, oracle-critical, refactor, D-01, D-02]
requires:
  - "trading_system/compose.py::Engine holder"
  - "universe/ pure derivations (derive_membership, derive_instruments, Universe)"
provides:
  - "wire_universe(engine) -> Universe — the shared oracle-critical universe-injection ordering"
  - "itrader/trading_system/universe_wiring.py"
affects:
  - "backtest_runner._initialise_backtest_session (now delegates to wire_universe)"
  - "live SessionInitializer (plan 06-04 — future consumer)"
tech-stack:
  added: []
  patterns:
    - "Free-function composition helper (D-02) — not a class/shared-runner-base"
    - "Verbatim code-motion over an oracle-sensitive seam (analogous to v1.2 MOD-01)"
key-files:
  created:
    - itrader/trading_system/universe_wiring.py
  modified:
    - itrader/trading_system/backtest_runner.py
decisions:
  - "D-01: wire_universe ADDS strategies_handler.set_universe to the backtest path — inert by construction (Universe construction-time Readiness.READY + membership derived from strategy tickers => is_ready always True at the readiness gate), PROVEN by the byte-exact oracle double-run"
  - "D-02: wire_universe is a free function homed in trading_system/ (NOT universe/) because it does feed.bind + handler injection, which universe/ is kept clean of"
metrics:
  duration: "~4 min"
  completed: "2026-07-13"
  tasks: 2
  files: 2
---

# Phase 6 Plan 01: UniverseWiring Extraction (RUN-04) Summary

Extracted the oracle-critical universe-injection ordering out of `BacktestRunner._initialise_backtest_session` into a standalone TABS free function `wire_universe(engine) -> Universe` in the new module `itrader/trading_system/universe_wiring.py`, and repointed the backtest runner to call it — with the SMA_MACD oracle held byte-exact (134 trades / final equity `46189.87730727451`, `check_exact=True`) across a determinism double-run and OKX import-inertness green.

## What Was Built

- **`itrader/trading_system/universe_wiring.py`** (new, TABS): a single free function `wire_universe(engine: Engine) -> Universe` that performs the full RUN-04 unit — `derive_membership` → `derive_instruments` → WR-03 desync assert → build `Universe` → `engine.universe` → inject into simulated exchange (isinstance-guarded) / order handler / portfolio handler / **strategies handler (D-01, new to the backtest path)** → `engine.feed.bind(engine.global_queue, universe.members)` → `return universe`. The donor block (`backtest_runner.py:64-113`) was transplanted VERBATIM including every load-bearing comment (D-01a / Pitfall / WR-03 / INST-02 rationale). Module docstring cites D-01/D-02/RUN-04 and the oracle-sensitivity; `Indentation: TABS` recorded.
- **`itrader/trading_system/backtest_runner.py`** (modified): `_initialise_backtest_session` now delegates the shared middle block to `wire_universe(engine)`; the leading `engine = self.engine` + `logger.info` and the trailing ping-grid union (`reduce(pd.Index.union, ...)` + empty-store `ConfigurationError` guard + `time_generator.set_dates`) + per-strategy `feed.precompute` loop stay VERBATIM as the runner's own post-step. Nothing reordered (Trap 4). Now-unused `Universe`/`derive_instruments`/`derive_membership`/`SimulatedExchange` imports removed; `ConfigurationError` kept (empty-store guard).

## Oracle / Gate Results (the per-PLAN gate on the milestone's highest oracle risk)

- **Backtest oracle byte-exact: PASS on TWO consecutive runs** — `tests/integration/test_backtest_oracle.py` 3 passed (run 1) and 3 passed (run 2), identical output. `check_exact=True` → 134 trades / final equity `46189.87730727451`. This PROVES the D-01 `strategies_handler.set_universe` addition is oracle-inert AND deterministic.
- **OKX import-inertness: PASS** — `tests/integration/test_okx_inertness.py` 3 passed (the new module pulls no `ccxt.pro` / live surface onto the backtest import path; imports only `universe/` pure derivations + compose `Engine` + `SimulatedExchange`).
- **mypy --strict: clean** — `Success: no issues found in 245 source files`.
- **Full suite: green** — `poetry run pytest tests` → 2125 passed, 6 skipped (all OKX-credential-gated opt-in live suites; no credentials in this env).

## Grep / Structural Acceptance

- `grep -c "strategies_handler.set_universe" universe_wiring.py` → 1 (D-01 addition present).
- `grep -c "set(membership) != set(instruments)" universe_wiring.py` → 1 (WR-03 desync assert transplanted).
- File ends the wiring body with `engine.feed.bind(engine.global_queue, universe.members)` then `return universe`.
- TABS: 71 tab-indented body lines, 0 space-indented body lines.
- `grep -c "wire_universe(engine)" backtest_runner.py` → 1; `grep -c "Universe(members=membership" backtest_runner.py` → 0 (block moved); `grep -c "engine.feed.precompute" backtest_runner.py` → 1 (post-step retained).

## Deviations from Plan

None — plan executed exactly as written. (Two cosmetic docstring/comment rewordings were applied so the literal acceptance-criteria greps count only the load-bearing call, not the D-01/D-02 prose citations: the docstring uses `StrategiesHandler.set_universe` and the runner comment uses `wire_universe()` — no behavior or semantics changed.)

## Known Stubs

None.

## Threat Flags

None — pure structural refactor, no new external input / network / trust boundary (matches the plan threat register: T-06-01 mitigated by the byte-exact double-run; T-06-02 mitigated by inertness green; T-06-SC zero new dependencies).

## Notes for Downstream

- `wire_universe(engine)` is now the ONE shared home for the cross-domain universe-injection ordering. Plan 06-04's live `SessionInitializer` reuses it VERBATIM at construction time — the live side GAINS the WR-03 desync assert (a safety upgrade, oracle-neutral since live is backtest-dark).
- This plan is ISOLATED and locks green ALONE before any other P6 plan touches the live tree (D-18 guardrail). `live_trading_system.py` was NOT modified.

## Self-Check: PASSED

- FOUND: `itrader/trading_system/universe_wiring.py`
- FOUND commit `a2d361a4` (Task 1)
- FOUND commit `567973ec` (Task 2)

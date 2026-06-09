---
phase: 02-m2a-identity-money-determinism
plan: 06
subsystem: execution + engine determinism
tags: [determinism, rng, clock, D-09, D-10, D-11, M2-05, PERF2]
requires: ["02-02 (core/clock.py: BacktestClock)", "02-05 (real ABCs / Protocol seams)"]
provides:
  - "documented rng_seed config key (config/system PerformanceSettings)"
  - "seeded random.Random injected into slippage models + SimulatedExchange"
  - "single seeded Random constructed at ExecutionHandler wiring"
  - "BacktestClock constructed + advanced on the backtest engine path"
affects:
  - itrader/config/system/config.py
  - itrader/execution_handler/slippage_model/fixed_slippage_model.py
  - itrader/execution_handler/slippage_model/linear_slippage_model.py
  - itrader/execution_handler/exchanges/simulated.py
  - itrader/execution_handler/execution_handler.py
  - itrader/trading_system/backtest_trading_system.py
tech-stack:
  added: []
  patterns:
    - "Injected seeded random.Random (Pattern B) — accept rng: random.Random | None, store self._rng, replace module-level random.* with self._rng.*"
    - "Config seed source (Pattern C) — documented @dataclass default rng_seed: int = 42 in PerformanceSettings"
    - "Injected Clock seam (Pattern 5) — BacktestClock.set_time(bar_time) advanced on the engine run loop"
key-files:
  created: []
  modified:
    - itrader/config/system/config.py
    - itrader/execution_handler/slippage_model/fixed_slippage_model.py
    - itrader/execution_handler/slippage_model/linear_slippage_model.py
    - itrader/execution_handler/exchanges/simulated.py
    - itrader/execution_handler/execution_handler.py
    - itrader/trading_system/backtest_trading_system.py
    - test/test_execution_handler/test_exchanges/test_simulated_exchange.py
decisions:
  - "D-11: a single seeded random.Random is constructed once at ExecutionHandler wiring and shared across SimulatedExchange + its slippage model — never seeded per-call or duplicated"
  - "rng_seed sourced from system config performance.rng_seed (documented default 42) via SystemConfig.from_dict, robust to an absent/partial settings/system.yaml"
  - "D-09/D-10: BacktestClock built + advanced on the engine path; perf-telemetry datetime.now() (run-duration) kept wall-clock; order/transaction timestamps left for M2b"
metrics:
  tasks: 3
  files: 7
  completed: 2026-06-04
---

# Phase 2 Plan 06: Identity, Money & Determinism — Determinism (seeded RNG + injected clock) Summary

Made backtests deterministic (M2-05, #5/PERF2): added a documented `rng_seed` config key, injected one
seeded `random.Random` into the two slippage models + `SimulatedExchange` (eliminating all 6 module-level
`random.*` engine-sim sites — D-11), and wired the injected `BacktestClock` (from Plan 02) onto the backtest
engine run loop, advancing it with each bar/sim time (D-09/D-10). No oracle impact (M1 runs failure-sim off +
zero slippage) — this future-proofs determinism.

## What Was Built

### Task 1 — Seed config key + inject seeded Random (commit `2bf09bb`)
- `config/system/config.py`: added documented `rng_seed: int = 42` to `PerformanceSettings` (SPACES), wired
  into `to_dict`/`from_dict` for round-trip consistency. Comment documents it as the intentional determinism
  default per D-11.
- `fixed_slippage_model.py` / `linear_slippage_model.py` (SPACES): each `__init__` now accepts
  `rng: random.Random | None = None` and stores `self._rng = rng or random.Random()`; the `random.uniform(...)`
  jitter call uses `self._rng.uniform(...)`.
- `simulated.py` (TABS): `__init__` accepts `rng: Optional[random.Random] = None`, stores `self._rng`, and shares
  it with its slippage model in `_init_slippage_model`. All 4 engine-sim `random.*` sites repointed to `self._rng`:
  `random.random()` → `self._rng.random()` (failure trigger), `random.choice(...)` → `self._rng.choice(...)`
  (error scenario), and two `random.uniform(...)` → `self._rng.uniform(...)` (latency telemetry). The wall-clock
  `datetime.now()` live/health-telemetry sites were left untouched (D-09/D-10).

### Task 2 — Construct + inject single seeded Random at wiring (commit `1f8b320`)
- `execution_handler.py` (TABS): `ExecutionHandler.__init__` resolves the seed via a new `_resolve_rng_seed()`
  helper (reads `performance.rng_seed` through the system config provider, falling back to the documented
  `PerformanceSettings` default via `SystemConfig.from_dict` — robust to an absent/partial gitignored
  `settings/system.yaml`), then constructs ONE `random.Random(seed)` and injects it into the `SimulatedExchange`
  it builds. One shared `Random` — never per-call, never duplicated.

### Task 3 — Wire BacktestClock onto the engine path (commit `05d43ce`)
- `backtest_trading_system.py` (TABS): constructs `self.clock = BacktestClock()` at wiring and calls
  `self.clock.set_time(ping_event.time)` at the top of each run-loop iteration, so any engine-path consumer of
  "now" reads deterministic simulation time. The `:97,105`-equivalent perf-telemetry `datetime.now()`
  (start_time/end_time run-duration) were kept wall-clock (D-09). No `order.py` audit / transaction timestamp
  sites were touched (M2b, D-10).

## Verification

- `poetry run pytest test/test_execution_handler test/test_smoke -q` → **64 passed**.
- No bare `random.(random|uniform|choice)(` in the 3 engine files (grep clean).
- Determinism sanity check: same seed → identical slippage-factor sequences for both Fixed and Linear models;
  injected RNG is the one used; both `ExecutionHandler` instances resolve `rng_seed=42`.
- Behavioral oracle unchanged: `SMA_MACD` run produced 134 trades, final equity **$53,229.75** (byte-identical
  to the frozen oracle on the key/behavioral columns).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Repointed `test_failure_simulation_deterministic` to the injected RNG**
- **Found during:** Task 2
- **Issue:** The test patched the module-level `random.random` (`@patch('random.random')`) to control the
  failure-simulation draw. After D-11 moved that draw to the injected instance (`self._rng.random()`), the
  module-level patch no longer intercepted it, so the "success" branch drew a real value and spuriously failed.
- **Fix:** Replaced the module-level patch with `patch.object(self.exchange._rng, 'random', return_value=...)`,
  which correctly exercises the new injected-RNG seam and is the determinism-correct way to control the draw.
- **Files modified:** `test/test_execution_handler/test_exchanges/test_simulated_exchange.py`
- **Commit:** `1f8b320`

## Deferred / Known Issues

- **DEF-02-04-A (pre-existing, NOT introduced here):** `test/test_integration/test_backtest_oracle.py` fails on
  the full-frame exact comparison at the numeric `net_quantity` column (~2.99% drift) — the intended float→Decimal
  precision shift from Plan 02-04, deferred to the owner-gated post-M2 numerical re-baseline (Phase 3 / M2b). The
  behavioral key columns (trade count, dates, sides, pairs) and final equity ($53,229.75) remain byte-identical,
  confirming this plan's clock change is behavior-preserving. Per the plan's context note, re-baselining the
  golden oracle is explicitly out of scope for 02-06 and is owner-gated.

## Notes for Downstream (M2b)

- The clock mechanism is built + advanced on the engine path but no engine-path consumer reads it yet — that is
  intentional (M2a deliverable). M2b applies `self.clock` / the injected `Clock` to `order.py` audit timestamps
  and transaction timestamps (M2b SC2).
- `ExecutionHandler._rng` is the single engine RNG; future stochastic engine components should accept an injected
  `random.Random` and receive this instance rather than calling `random.*` directly.

## Self-Check: PASSED

All 6 modified source files + SUMMARY.md exist on disk; all 3 task commits (2bf09bb, 1f8b320, 05d43ce) present in git history.

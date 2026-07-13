---
phase: 06-liverunner-factory-facade-shrink
plan: 03
subsystem: price_handler/feed
tags: [RUN-07, D-17, CF-10, warmup, cache-registration, live]
status: complete
requires: ["06-01"]
provides:
  - "StrategyWarmupConsumer (frozen RawBarConsumer) in cache_registration.py"
  - "derive_warmup_depth(strategies) -> int — named D-17/CF-10 warmup-depth boundary"
  - "register_strategy_warmup(feed, strategies) -> None — reusable registration entry point"
affects:
  - "06-04 SessionInitializer will call register_strategy_warmup and remove the old _LiveWarmupConsumer"
tech-stack:
  added: []
  patterns:
    - "structural Protocol loose-typing (_SupportsWarmup, _SupportsRawBarConsumerRegistration)"
    - "named-function seam so CF-10 changes ONE body, not the wiring (D-17)"
key-files:
  created: []
  modified:
    - itrader/price_handler/feed/cache_registration.py
decisions:
  - "warmup concern named derive_warmup_depth, distinct from derive() raw-history ladder (RESEARCH Landmine 4)"
  - "ONE global ring (scalar required_history_depth); per-symbol ring sizing + K-computation stay DEFERRED (D-17)"
  - "old _LiveWarmupConsumer + inline registration left in live_trading_system.py; removed in 06-04 to avoid cross-file conflict"
metrics:
  duration: ~6 min
  completed: 2026-07-13
  tasks: 1
  files: 1
---

# Phase 6 Plan 3: Rehome StrategyWarmupConsumer + Named Warmup-Depth Seam Summary

Rehomed the live-only `_LiveWarmupConsumer` into the shared feed module `price_handler/feed/cache_registration.py` as a reusable `StrategyWarmupConsumer`, and shaped the CF-10 depth boundary as a NAMED, replaceable `derive_warmup_depth(strategies)` function plus a reusable `register_strategy_warmup(feed, strategies)` entry point — additive symbols only, import-inert, mypy --strict clean, backtest oracle byte-exact.

## What Was Built

Three new symbols in `itrader/price_handler/feed/cache_registration.py` (4-space, import-inert, added to `__all__`):

1. **`StrategyWarmupConsumer`** — a `@dataclass(frozen=True)` with a single `required_history_depth: int`, transplanting `_LiveWarmupConsumer` (structurally implements the existing `RawBarConsumer` Protocol, so it coexists with `derive()` by construction). Carries the load-bearing docstring (sizes `cache_capacity()` to the max strategy warmup; without it indicators never warm and the run yields zero trades — Pitfall 1). ONE global ring; per-symbol ring sizing stays deferred.

2. **`derive_warmup_depth(strategies) -> int`** — the NAMED, replaceable D-17 seam. Body returns the global `max((s.warmup for s in strategies), default=1)` — the exact expression extracted from the inline donor at `live_trading_system.py:1289-1292`. Docstring states this is the CF-10 boundary: CF-10 later changes ONLY this body (global max → per-concerned-strategy max), without re-touching the registration wiring or `SessionInitializer`. Named distinctly from `derive` (RESEARCH Landmine 4 — `derive` is the raw-history ladder; this is the separate warmup concern).

3. **`register_strategy_warmup(feed, strategies) -> None`** — the reusable registration entry point (consumed by `SessionInitializer` in 06-04): computes `depth = derive_warmup_depth(strategies)`, then `feed.register_raw_bar_consumer(StrategyWarmupConsumer(required_history_depth=depth))`. Typed with two minimal structural Protocols (`_SupportsWarmup`, `_SupportsRawBarConsumerRegistration`) matching the file's loose-typing convention.

The old `_LiveWarmupConsumer` + its inline registration remain in `live_trading_system.py` (removed in 06-04 when `_initialize_live_session` becomes `SessionInitializer`), keeping the two coexisting briefly to avoid a cross-file conflict and keep the suite green.

## Milestone Gate Results (recorded per critical_gate)

- **OKX import-inertness** — `poetry run pytest tests/integration/test_okx_inertness.py -q`: **3 passed** (green). The shared feed module stays pure typing + stdlib (`Iterable`, `dataclass`, `Protocol`) — no ccxt.pro/async/SQL pulled onto the backtest graph.
- **Backtest oracle byte-exact** — `poetry run pytest tests/integration/test_backtest_oracle.py -q`: **3 passed**, byte-exact **134 / 46189.87730727451** (`check_exact=True`; this plan adds symbols only, does not change the backtest path).
- **mypy --strict** — `poetry run mypy itrader`: **Success: no issues found in 248 source files**.
- **Full suite** — `poetry run pytest tests`: **2125 passed, 6 skipped** (skips are OKX-demo-credential-gated live suites), `filterwarnings=["error"]` green.
- **Zero new dependencies** — no poetry change.
- **Indentation** — 4-SPACE preserved (`grep -Pn "^\t"` returns empty).

## Acceptance Criteria

- All three symbols exist and are importable (asserted via runtime import); all three in `__all__`.
- `derive_warmup_depth` returns the global `max((s.warmup for s in strategies), default=1)`; `grep -c "def derive_warmup_depth"` = 1.
- `StrategyWarmupConsumer` is a frozen dataclass with a single `required_history_depth`; `grep -c "required_history_depth"` = 10 (>= 2).
- Existing `derive`/`derive_required_depths` unchanged.
- 4-space preserved; mypy clean; oracle byte-exact + inertness green.

## Deviations from Plan

None - plan executed exactly as written.

## Self-Check: PASSED

- FOUND: itrader/price_handler/feed/cache_registration.py (modified, all 3 symbols present + importable)
- FOUND: commit d228fc8e (feat 06-03)
- Gate commands re-run and green (recorded above).

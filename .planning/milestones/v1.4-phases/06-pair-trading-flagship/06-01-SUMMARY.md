---
phase: 06
plan: 01
subsystem: strategy_handler
tags: [pair-trading, strategy-base, dispatch, wave-0, PAIR-01]
requires:
  - "itrader/strategy_handler/base.py::Strategy (ABC + _apply_params/validate/_run_init/evaluate)"
  - "itrader/core/sizing.py::SignalIntent (quantity/exit_fraction/leverage fields)"
  - "itrader/core/enums::TradingDirection.LONG_SHORT, Side, OrderType.MARKET"
provides:
  - "itrader/strategy_handler/pair_base.py::PairStrategy — two-leg pure-alpha ABC (evaluate_pair seam, _entry explicit-quantity constructor, LONG_SHORT + log-price defaults)"
  - "itrader/strategy_handler/strategies_handler.py::_dispatch_pair — pair-aware two-leg dispatch type-branch + _emit_intent shared per-intent path"
  - "4 Wave-0 collectible test stub files (Nyquist contract)"
affects:
  - "itrader/strategy_handler/strategies_handler.py (calculate_signals loop — additive isinstance branch, single-leg path refactored to _emit_intent, byte-exact)"
tech-stack:
  added: []
  patterns:
    - "Typed isinstance dispatch branch (replaces the removed runtime isinstance(tickers[0], tuple) pairs sniff, IN-01)"
    - "Explicit-quantity ENTRY intent constructor threading β-weighted quantity (inherited buy/sell sugar cannot)"
key-files:
  created:
    - "itrader/strategy_handler/pair_base.py"
    - "tests/unit/strategy/test_pair_strategy.py"
    - "tests/unit/strategy/test_pair_dispatch.py"
    - "tests/integration/test_pair_exit_safety.py"
    - "tests/integration/test_pair_flagship_snapshot.py"
  modified:
    - "itrader/strategy_handler/strategies_handler.py"
decisions:
  - "D-01: PairStrategy dispatched once per tick via a typed isinstance branch returning both legs together (evaluate_pair); single-leg per-ticker path structurally untouched"
  - "D-02: both-present guard returns early when either leg's bar is absent — no forward-fill (no stale price enters the spread)"
  - "D-04/D-14: PairStrategy pins direction=LONG_SHORT and use_log_prices=True as the base defaults"
  - "Pitfall 3: warmup short-circuit gates on beta_warmup+z_lookback (not the handle-derived strategy.warmup=0); validate() asserts max_window >= that sum"
  - "Nyquist contract: every 06-VALIDATION.md -k selector collects >=1 (skipped) test before any RED step"
metrics:
  duration: ~10 min
  completed: 2026-06-22
---

# Phase 6 Plan 01: PairStrategy Base + Pair Dispatch + Wave-0 Stubs Summary

Landed the only net-new engine surface Phase 6 adds — the `PairStrategy` two-leg
pure-alpha base and the pair-aware dispatch type-branch in `StrategiesHandler` —
plus all four Wave-0 collectible test scaffolds, so every downstream plan builds
against fixed contracts. SMA_MACD oracle byte-exact (134 / 46189.87730727451);
`mypy --strict` clean (164 files).

## What Was Built

### Task 1 — `PairStrategy` base (`pair_base.py`, TABS) — commit 7255c81
- `PairStrategy(Strategy)` ABC pinning `direction = TradingDirection.LONG_SHORT`
  (D-14) and `use_log_prices = True` (D-04), with annotated alpha-knob class attrs
  `entry_z` / `exit_z` / `z_lookback` / `beta_warmup` / `leverage` / `max_window`
  (every Decimal knob via the `Decimal("...")` string path — Pitfall 4).
- Abstract `evaluate_pair(win_A, win_B) -> list[SignalIntent] | None` two-leg seam
  (the pinned name, A4) returning BOTH legs together.
- `_entry(ticker, action, quantity)` — the explicit-β-weighted-quantity ENTRY
  constructor (the inherited `buy()/sell()/_intent()` sugar always builds
  `quantity=None`, so it cannot express per-leg β-weighting). `quantity` enters the
  Decimal domain via `to_money` only.
- `generate_signal` overridden to raise `NotImplementedError` (the single-leg seam
  is structurally bypassed for pairs; reaching it means the dispatch branch is
  unwired — fail loudly).
- `validate()` asserts the pair invariants: exactly two tickers, `exit_z < entry_z`,
  and `max_window >= beta_warmup + z_lookback` (Pitfall 3 — a too-narrow fetch width
  yields a window that can never satisfy the fit/z warmup).
- Inherited `_apply_params` / `validate` / `_run_init` / `evaluate` reused verbatim,
  NOT re-implemented. No β/statsmodels math here (that is Plan 06-02).

### Task 2 — pair dispatch type-branch (`strategies_handler.py`, TABS) — commit 4eb8fda
- Imported `PairStrategy`; added `if isinstance(strategy, PairStrategy): self._dispatch_pair(strategy, event); continue`
  at the TOP of the per-strategy loop (after `check_timeframe`, before the
  per-ticker loop).
- `_dispatch_pair`: reads the pair's two tickers, requires BOTH legs' bars present
  this tick (D-02 — skip silently, no forward-fill, T-06-01), fetches both
  completed-bar windows (`asof=event.time` only, T-06-02/T-06-18), short-circuits on
  `beta_warmup + z_lookback` (Pitfall 3, not the handle-derived `warmup=0`), calls
  `evaluate_pair`, and fans EACH returned intent through the shared per-intent path.
- Factored the single-leg per-intent record + fan-out block into a private
  `_emit_intent(strategy, event, ticker, bar, intent)` helper; the single-leg loop
  now calls it (pure code-motion — same store call, same MARKET price stamp from the
  leg's `bar.close`, same fan-out args). Both pair legs reuse it verbatim.
- Single-leg behavior byte-identical: oracle holds 134 / 46189.87730727451.

### Task 3 — Wave-0 collectible test stubs (4 files, 4 spaces) — commit b536c9c
- `tests/unit/strategy/test_pair_strategy.py`: `test_beta_log_ols_fixture` (`-k beta`),
  `test_zscore_rolling_and_crossing` (`-k zscore`).
- `tests/unit/strategy/test_pair_dispatch.py`: `test_both_legs_emit_once_per_tick`
  (`-k both_legs`), `test_both_present_guard_skips_when_one_absent` (`-k both_present`),
  `test_beta_weighted_leg_quantities` (`-k beta_weighted`).
- `tests/integration/test_pair_exit_safety.py`: `test_close_only_exit_noop_when_flat`.
- `tests/integration/test_pair_flagship_snapshot.py`: `test_pair_flagship_snapshot_matches`,
  `test_pair_flagship_determinism_double_run` (`-k determinism`). Module docstring
  states this is a STABILITY lock, NOT a correctness oracle (D-11).
- All bodies are runtime `pytest.skip(...)` (collectible — NOT module-skip / decorator).
  No hand-added markers (folder-derived). Every 06-VALIDATION.md `-k` selector collects
  and skips exactly 1 test.

## Verification Results

- `poetry run pytest tests/integration/test_backtest_oracle.py -q` — 3 passed (oracle
  byte-exact: 134 trades / final_equity 46189.87730727451; additive phase, no re-baseline).
- `poetry run pytest tests/unit/strategy/test_strategies_handler_registration.py` — 5 passed.
- Each Wave-0 selector (`-k beta`, `-k zscore`, `-k both_legs`, `-k both_present`,
  `-k beta_weighted`, `test_pair_exit_safety.py`, `-k determinism`) collects + skips
  exactly 1 test (`1 skipped, N deselected`).
- `poetry run pytest tests/unit/strategy tests/integration/test_backtest_oracle.py
  tests/integration/test_pair_exit_safety.py tests/integration/test_pair_flagship_snapshot.py -q`
  — 97 passed, 8 skipped.
- `poetry run mypy` — Success: no issues found in 164 source files (strict).
- Indentation: `pair_base.py` + `strategies_handler.py` TABS (no 4-space lines);
  test stubs 4 spaces (no tab lines).

## Deviations from Plan

None — plan executed exactly as written. The optional "factor the per-intent
record+fanout block into a private helper" was taken (it removes duplication between
the single-leg loop and `_dispatch_pair`), as the plan's Task 2 action explicitly
sanctioned; the single-leg path stays byte-exact (proven by the oracle).

## Authentication Gates

None.

## Known Stubs

The four Wave-0 test files are intentional collectible `pytest.skip` stubs (the
Nyquist contract). They are implemented in later Phase 6 plans (06-02/06-03 and the
exit-safety / flagship-snapshot plans). This is the documented, plan-mandated Wave-0
pattern — not an unwired data stub. No production-code stubs exist: `PairStrategy`
is a complete ABC and `_dispatch_pair` is fully wired; the β/z alpha lives in the
concrete reference strategy delivered by Plan 06-02 (by design).

## Self-Check: PASSED

- FOUND: itrader/strategy_handler/pair_base.py
- FOUND: tests/unit/strategy/test_pair_strategy.py
- FOUND: tests/unit/strategy/test_pair_dispatch.py
- FOUND: tests/integration/test_pair_exit_safety.py
- FOUND: tests/integration/test_pair_flagship_snapshot.py
- FOUND commit 7255c81 (Task 1), 4eb8fda (Task 2), b536c9c (Task 3)

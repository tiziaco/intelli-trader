---
phase: 07-m5b-sizing-policy-metrics-universe-coverage
plan: 02
subsystem: universe / price-feed / event-dispatch
tags: [universe-collapse, bar-event-factory, membership, tdd, oracle-inert]
requires:
  - "06-05: Store+Feed seams (BacktestBarFeed is the data engine the factory moves into)"
provides:
  - "itrader/universe/membership.py — derive_membership pure union (D-20/D-21)"
  - "BacktestBarFeed.generate_bar_event + bind(global_queue, membership) — feed-owned BarEvent production"
  - "EventHandler bar_event_source constructor seam (TIME route)"
affects:
  - "07-04 (strategies_handler rework reads get_strategies_universe — logic now also lives in membership.py)"
  - "future D-screener rebalance milestone (touches only membership.py)"
tech-stack:
  added: []
  patterns:
    - "LEAN/Nautilus data-engine shape: the feed produces BarEvents; universe is derived membership data"
    - "Protocol-typed pure function (SupportsTickers) for mypy --strict duck typing"
key-files:
  created:
    - itrader/universe/membership.py
    - tests/unit/universe/test_membership.py
  modified:
    - itrader/universe/__init__.py
    - itrader/price_handler/feed/bar_feed.py
    - itrader/events_handler/full_event_handler.py
    - itrader/trading_system/backtest_trading_system.py
    - itrader/trading_system/live_trading_system.py
    - tests/unit/price/test_bar_feed.py
    - tests/unit/events/test_dispatch_registry.py
    - tests/unit/events/test_error_flow.py
    - tests/integration/test_event_wiring.py
  deleted:
    - itrader/universe/dynamic.py
    - itrader/universe/static.py
    - itrader/universe/universe.py
decisions:
  - "Feed binding via bind(global_queue, membership) method (not constructor params) — membership is only known after strategies register, at session init"
  - "derive_membership flattens tuple entries per-element (mypy-strict-safe narrowing) — identical results to the legacy first-element check for homogeneous ticker lists"
  - "last_bar tracking dropped from the relocated factory body — grep found zero consumers"
  - "Missing-ticker warning loop now iterates full membership (strategy ∪ screener) instead of strategies-only — log-only path, screener set empty on the golden run, oracle byte-exact confirms inertness"
metrics:
  duration: ~10 min
  completed: 2026-06-07
  tasks: 2
  commits: 3
---

# Phase 7 Plan 02: Universe Collapse + Feed-Owned BarEvent Factory Summary

**One-liner:** universe/ collapsed to one pure documented `derive_membership` module (LEAN UniverseSelectionModel named as growth target) and BarEvent production relocated into `BacktestBarFeed.generate_bar_event`, with the EventHandler TIME route rewired to an injected `bar_event_source` callable — proven byte-exact inert by the oracle.

## What Was Built

### Task 1 — membership stub + feed factory (TDD)
- **RED** (`d07717e`): 6 membership tests (union, tuple-pair flattening, dedupe, defaults) + 4 feed-factory tests (unbound return contract, bound enqueue contract, missing-ticker warning via caplog, no-warning when covered).
- **GREEN** (`08ac7ca`):
  - `itrader/universe/membership.py` (spaces): `derive_membership(strategies, screener_tickers=()) -> list[str]` — the relocated `get_strategies_universe` union logic (tuple-pair flattening preserved) ∪ screener tickers, deduplicated via `list(set(...))` exactly like the legacy code. Docstring documents the stub IS the universe, prominently names the LEAN `UniverseSelectionModel` + D-screener rebalance loop as the growth target (D-20), and states the purity rule (rebalance touches only membership, never event plumbing). `SupportsTickers` Protocol keeps it mypy --strict clean.
  - `itrader/universe/__init__.py` exports `derive_membership` only.
  - `BacktestBarFeed` gains `bind(global_queue, membership)` (wiring-time binding) and `generate_bar_event(time_event)` — the relocated `DynamicUniverse` body with `self.feed.current_bars(...)` → `self.current_bars(...)`; missing-ticker warning kept (RESEARCH OQ4); enqueue-and-return-None when queue bound, else return the BarEvent. `last_bar` dropped (zero consumers).
  - `dynamic.py`, `static.py`, `universe.py` deleted via `git rm` (StaticUniverse + the never-honored `get_assets` ABC die).

### Task 2 — TIME-route rewire (`ad69010`)
- `full_event_handler.py` (tabs): `universe: Universe` constructor param replaced by `bar_event_source: Callable[[Any], Any]`; TIME route literal is now `[screeners_handler.screen_markets, self.bar_event_source]`; the `Universe` import deleted. Rest of the routing registry untouched.
- `backtest_trading_system.py` (tabs): `DynamicUniverse` construction + `init_universe` deleted; `_initialise_backtest_session` derives membership (`derive_membership(strategies, get_screeners_universe())`) and binds queue + membership onto the feed; `feed.generate_bar_event` passed as the EventHandler's `bar_event_source`. The feed's precompute/ticker initialization input is unchanged (`strategy.tickers` per strategy, store index for the ping clock).
- `live_trading_system.py` (A4 minimal shim): mirrors the backtest wiring shape; imports and constructs (D-live owns real behavior).
- Mocked-test blast radius (Pitfall 7): `test_dispatch_registry.py` TIME assertion repointed to the injected `bar_event_source` mock; `test_error_flow.py` + `test_event_wiring.py` replace the MagicMock universe with a mock factory callable; the now-nonexistent `itrader.universe.universe` stub module removed from all three stub blocks. Assertion intent (routing order, error consumption) identical.

## Verification Evidence

| Gate | Result |
|------|--------|
| `pytest tests/unit/universe tests/unit/price tests/unit/events tests/integration/test_event_wiring.py -q` | pass (115) |
| `pytest tests/integration/test_backtest_oracle.py -q` | **2 passed — byte-exact, the collapse is inert** |
| `python -c "import itrader.trading_system.live_trading_system"` | exit 0 (A4 shim holds) |
| `grep -rn "DynamicUniverse\|StaticUniverse\|universe.universe" itrader/ --include="*.py"` | zero hits (docstring mentions reworded to honor the literal gate) |
| `mypy itrader` (--strict) | Success: no issues in 137 source files |
| Full suite | 600 passed |

`itrader/universe/` contains only `__init__.py` and `membership.py`. `membership.py` contains `UniverseSelectionModel`, `D-screener`, and `def derive_membership`; `bar_feed.py` contains `def generate_bar_event`; tuple-pair flattening locked by `test_tuple_pair_flattening_produces_both_legs`.

## Deviations from Plan

**1. [Minor] Docstring mentions of deleted class names reworded**
- **Found during:** Task 2 acceptance-criteria grep
- **Issue:** Relocation docstrings/comments referenced `DynamicUniverse` by name, tripping the literal `grep ... returns nothing` gate
- **Fix:** Reworded to "legacy/dynamic universe" phrasing; meaning preserved
- **Files modified:** bar_feed.py, membership.py, universe/__init__.py
- **Commit:** ad69010

**2. [Behavior-noted, oracle-proven inert] Missing-ticker warning loop iterates full membership**
- The legacy loop iterated `strategies_universe` only; the relocated loop iterates membership (strategy ∪ screener). Log-only path; screener set is empty on the golden run; oracle byte-exact confirms inertness.

Otherwise executed as written.

## TDD Gate Compliance

RED `d07717e` (test) → GREEN `08ac7ca` (feat) → no refactor commit needed (clean on first pass).

## Threat Register Outcomes

- **T-07-03 (silent oracle drift):** mitigated — factory body is a verbatim relocation; byte-exact oracle gate passed in-plan.
- **T-07-04 (missing-data silence):** mitigated — warning loop kept and caplog-tested (`test_generate_bar_event_missing_membership_ticker_warns`).
- **T-07-SC:** zero package installs.

## Known Stubs

None blocking — `membership.py` is BY DESIGN a documented stub (M5-08): a static symbol set derived at wiring time, with the rebalance growth path documented in its docstring.

## Requirements

- **M5-08:** complete (marked in REQUIREMENTS.md).
- **M5-09 (TC6 slice):** membership + bar-feed factory coverage landed; M5-09 is shared with plans 07-03/07-04 and left unmarked for the orchestrator/final plan.

## Self-Check: PASSED

- itrader/universe/membership.py — FOUND
- itrader/price_handler/feed/bar_feed.py `def generate_bar_event` — FOUND
- tests/unit/universe/test_membership.py — FOUND
- dynamic.py/static.py/universe.py — DELETED as planned
- Commits d07717e, 08ac7ca, ad69010 — FOUND on worktree-agent branch

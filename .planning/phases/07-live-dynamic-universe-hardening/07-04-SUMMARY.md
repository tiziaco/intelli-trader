---
phase: 07-live-dynamic-universe-hardening
plan: 04
subsystem: strategy
tags: [strategy, readiness, WR-02, OP-SEAM, live-trading, universe, warmup]

# Dependency graph
requires:
  - phase: 07-01 (v1.7)
    provides: BarsLoaded / StrategyCommandEvent / UniversePollEvent structs + EventType members
  - phase: 07-02 (v1.7)
    provides: Universe.is_ready(sym) readiness surface (construction members READY = oracle-inert)
provides:
  - StrategiesHandler.set_universe live-only seam + _universe field (defaults None, backtest-inert)
  - WR-02 defensive readiness gate BEFORE strategy.is_ready in calculate_signals (None-guarded O(1))
  - on_bars_loaded — warm concerned strategies from a BarsLoaded payload via strategy.update, no signals (D-03)
  - on_strategy_command — idempotent .tickers mutation + UniversePollEvent follow-on (D-11)
affects: [07-05, 07-06, 07-07, live-warmup, operator-strategy-edit]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Inert-by-default live seam: _universe defaults None so the per-tick gate is a single `is None` short-circuit on the backtest hot path"
    - "Emit-a-follow-on (D-11): queue-only cross-domain write (UniversePollEvent) instead of calling UniverseHandler"

key-files:
  created:
    - tests/unit/strategy/test_strategies_live_membership.py
  modified:
    - itrader/strategy_handler/strategies_handler.py

key-decisions:
  - "Gate composed AFTER strategy.update, BEFORE strategy.is_ready — a PENDING symbol still warms the O(1) recurrence while it is not traded (D-03c)"
  - "Universe import is TYPE_CHECKING-guarded + string-annotated so the backtest path adds zero runtime import cost (D-01 inertness)"
  - "on_strategy_command emits the UniversePollEvent follow-on iff the command is ACCEPTED (incl. idempotent no-op); a refused emptying-remove and an unknown strategy/verb are documented no-ops (no event)"
  - "Emptying-remove is refused with a logged warning to preserve the non-empty list[str] invariant (base.py)"

requirements-completed: [WR-02, OP-SEAM]

# Metrics
duration: 5min
completed: 2026-07-06
---

# Phase 7 Plan 04: Readiness-Gated + Operator-Editable StrategiesHandler Summary

**`StrategiesHandler` gains three live-only seams — a None-guarded O(1) `universe.is_ready` readiness gate composed BEFORE the indicator-warmth gate (warm-but-don't-trade while PENDING), an `on_bars_loaded` that warms concerned strategies via the identical `strategy.update` path with NO signals, and an `on_strategy_command` that idempotently mutates `.tickers` then emits a `UniversePollEvent` follow-on (never calls `UniverseHandler`) — all inert on the backtest hot path, oracle byte-exact.**

## Performance

- **Duration:** ~5 min
- **Started:** 2026-07-06T18:34:17Z
- **Completed:** 2026-07-06T18:38:58Z
- **Tasks:** 3
- **Files modified:** 2 (1 created, 1 modified)

## Accomplishments
- **WR-02 readiness gate (Task 1):** In `calculate_signals`, a `if self._universe is not None and not self._universe.is_ready(ticker): continue` is inserted immediately AFTER `strategy.update(ticker, bar)` and BEFORE `strategy.is_ready(ticker)`. It is a single None-check + one O(1) `is_ready` read, NO allocation. Default `_universe is None` → the backtest wires no universe → the gate is a single `is None` short-circuit → the SMA_MACD oracle is byte-exact (134 / `46189.87730727451`). `set_universe(universe)` is the sole live-only wiring point; the `Universe` import is `TYPE_CHECKING`-guarded + string-annotated so the backtest path pays zero runtime import cost.
- **on_bars_loaded (Task 2):** For each strategy CONCERNED with `event.symbol` (its `.tickers` include the symbol), it replays `event.bars` IN ORDER through `strategy.update(event.symbol, bar)` and NOTHING else — no `is_ready`/`generate_signal`/`_emit_intent`, no store, no queue. Warmup, not trading (D-03). Non-concerned strategies are skipped.
- **on_strategy_command (Task 3):** Locates the strategy by `.name`, applies the verb idempotently to the plain `list[str]` tickers (`add_ticker` appends if absent; `remove_ticker` removes if present), refuses a remove that would empty the list with a logged warning (non-empty invariant, base.py), then EMITS a follow-on `UniversePollEvent(time=event.time)` on `self.global_queue` (D-11 — mutate happens-before re-select). It NEVER references `UniverseHandler`/`Universe` in code (queue-only cross-domain write, grep-asserted). Unknown strategy name / verb is a logged no-op (no mutation, no event).

## Task Commits

Each task was committed atomically:

1. **Task 1: WR-02 readiness gate + set_universe seam** - `e56bb994` (feat)
2. **Task 2: on_bars_loaded warms concerned strategies (no signals)** - `f6812e14` (feat)
3. **Task 3: on_strategy_command mutates tickers + emits UniversePollEvent** - `6b698c9d` (feat)

**Plan metadata:** _(final docs commit)_

## Files Created/Modified
- `itrader/strategy_handler/strategies_handler.py` (modified, TABS) - `_universe` field + `set_universe`, the readiness gate in `calculate_signals`, `on_bars_loaded`, `on_strategy_command`, and the `BarsLoaded`/`StrategyCommandEvent`/`UniversePollEvent` barrel import + `TYPE_CHECKING` `Universe` import.
- `tests/unit/strategy/test_strategies_live_membership.py` (created, 4-space) - 13 tests: 5 readiness-gate/set_universe, 2 on_bars_loaded, 6 on_strategy_command (against a fake universe + a spy strategy).

## Decisions Made
- Followed the plan exactly. The gate stays AFTER `strategy.update` (D-03c — the recurrence advances while pending), and the follow-on `UniversePollEvent` is emitted iff the command is accepted (idempotent no-ops still emit; refused emptying-remove and unknown-name/verb are documented no-ops with no event).
- Indentation matched per file: TABS in `strategies_handler.py`, 4-space in the new test (sibling strategy tests are 4-space).

## Deviations from Plan

None - plan executed exactly as written.

## Threat Surface

Threat register mitigations from the plan are satisfied and asserted:
- **T-07-04-ORACLE** (DoS on the per-tick path): the gate is a None-guarded single O(1) `is_ready` read, no allocation; backtest wires no universe; oracle byte-exact re-confirmed (134 / `46189.87730727451`).
- **T-07-04-FANOUT** (Tampering): `on_strategy_command` emits a `UniversePollEvent` follow-on; no direct `UniverseHandler`/`Universe` call (grep-asserted — only docstring mentions).
- **T-07-04-EMPTY** (DoS): a remove that would empty `.tickers` is refused with a logged warning (non-empty `list[str]` invariant preserved).

No NEW security-relevant surface introduced (no endpoints, auth paths, file/schema access).

## Known Stubs
None — all three seams are real and behavior-tested. The route wiring that reaches `on_bars_loaded` / `on_strategy_command` on the live `EventHandler` and calls `set_universe` at the live composition root is the declared scope of Plan 07-05/07 (this plan is the strategy-side half of the readiness-gated warmup + operator-edit direction; it is intentionally not route-wired here).

## Issues Encountered
- `requirements.mark-complete WR-02 OP-SEAM` reports `not_found`: the Phase-7 WR-/OP- requirement IDs are not present in `.planning/REQUIREMENTS.md`'s traceability table (Phase 7 was added post-hoc from the Phase 6 code review). Consistent with prior 07-01/02/03 plans; not a blocker. Requirements are tracked in the phase docs/ROADMAP instead.

## User Setup Required
None.

## Verification
- `poetry run pytest tests/unit/strategy tests/integration/test_backtest_oracle.py -q` → **143 passed** (13 new live-membership tests + oracle byte-exact 3/3).
- `poetry run mypy itrader/strategy_handler/strategies_handler.py` → clean.
- Oracle byte-exact (134 / `46189.87730727451`) with no universe wired — the primary inertness proof.
- `on_strategy_command` body grep-clean of `UniverseHandler`/`Universe(`/`universe` code references (docstring/comment mentions only).

## Self-Check: PASSED

- FOUND: itrader/strategy_handler/strategies_handler.py
- FOUND: tests/unit/strategy/test_strategies_live_membership.py
- FOUND: .planning/phases/07-live-dynamic-universe-hardening/07-04-SUMMARY.md
- FOUND commit: e56bb994
- FOUND commit: f6812e14
- FOUND commit: 6b698c9d

---
*Phase: 07-live-dynamic-universe-hardening*
*Completed: 2026-07-06*

---
phase: 06-dynamic-universe-membership
plan: 03
subsystem: universe
tags: [universe-membership, poll-seam, selection-model, event-consumer, live-only]

# Dependency graph
requires:
  - phase: 06-dynamic-universe-membership
    plan: 01
    provides: "UniverseUpdateEvent + Universe.apply(desired, instruments)->UniverseDelta (in-place, default-ladder fallback) + leaving-set surface"
  - phase: 06-dynamic-universe-membership
    plan: 02
    provides: "OkxDataProvider.subscribe/unsubscribe dynamic seam + warmup-before-subscribe contract"
  - phase: 02-okx-connector
    provides: "OkxExchange.validate_symbol (D-06 venue markets-map bound)"
  - phase: 03-live-bar-feed
    provides: "LiveBarFeed.warmup (REST replay through update()) — the add-branch warmup driver"
provides:
  - "Lean UniverseSelectionModel Protocol + StaticUniverseSelectionModel in membership.py (pure select(asof)->set[str], no queue/feed; operator set_symbols drive)"
  - "UniverseHandler.on_time: source-guard -> D-06 validate_symbol filter -> Universe.apply -> emit UniverseUpdateEvent only on non-empty delta"
  - "UniverseHandler.on_universe_update ADD branch: warmup-before-subscribe per added symbol, provider-None tolerant"
  - "Three live-only wiring seams (set_selection_source / set_symbol_validator / set_provider) defaulting to None (inert unwired)"
affects: [06-04, 06-05, dynamic-universe-membership, remove-policy, live_trading_system-wiring]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Lean selection seam: pure select(asof)->set[str] holding no queue/feed (mirrors active_membership's set contract; D-20 growth target, NOT a ranking engine)"
    - "Source-guarded poll host: single cheap `if selection_source is None: return` inertness lever keeps an unwired route near-free (oracle-dark)"
    - "Dedicated live-only handler isolates the poll route from the backtest-shared _routes[TIME] literal (Claude's-Discretion divergence from PATTERNS §7)"
    - "Emit-only-on-non-empty: no empty-delta event floods (T-06-03-DOS)"
    - "D-06 direct validate_symbol filter BEFORE apply keeps Universe connector-free (D-03) and blocks spoofed symbols pre-membership (T-06-03-SPOOF)"

key-files:
  created:
    - itrader/universe/universe_handler.py
    - tests/unit/universe/test_universe_selection.py
    - tests/unit/universe/test_universe_poll.py
  modified:
    - itrader/universe/membership.py
    - itrader/universe/__init__.py

key-decisions:
  - "Instrument resolution for added symbols passes None to Universe.apply (plan-01 _DEFAULT_* ladder fallback) rather than reaching into connector markets internals — venue-correct precision resolution is a plan-05 composition-root wiring concern (honors D-03; the plan's explicit 'else pass None' branch)"
  - "Dedicated 4-space UniverseHandler (NOT growing onto ScreenersHandler) so plan-05 mutates the LIVE _routes[TIME] only and the backtest per-tick path pays zero source-guard/W1 burden by construction (Pitfall 3 / A3)"
  - "UNIV-01 left Pending — this plan ships selection + poll + add-side; the REMOVE branch (plan 04) and live wiring (plan 05) remain, per plan 01's 'completes across plans 02-05' note"

patterns-established:
  - "UniverseSelectionModel is runtime_checkable so conformance is assertable; StaticUniverseSelectionModel.select returns a defensive copy so callers cannot corrupt internal state"
  - "on_universe_update ADD branch never reorders warmup/subscribe (Pitfall 6) and tolerates provider is None (paper/replay path)"

requirements-completed: []  # UNIV-01 is multi-plan (01-05); selection+poll+add shipped, remove(04)+wiring(05) pending

# Metrics
duration: 6min
completed: 2026-07-06
---

# Phase 6 Plan 03: UniverseSelectionModel + UniverseHandler Poll/Add Seam Summary

**A lean pure `UniverseSelectionModel` in `membership.py` (the D-20 growth target — "what SHOULD the universe be?" as `select(asof)->set[str]`, no queue/feed) and a new `UniverseHandler` hosting `on_time` (source-guard -> D-06 filter -> `Universe.apply` -> emit only on non-empty delta) plus the `on_universe_update` ADD branch (warmup-before-subscribe) — the selection/poll half of D-02, backtest-inert by construction.**

## Performance

- **Duration:** ~6 min
- **Started:** 2026-07-06T10:20:51Z
- **Completed:** 2026-07-06T10:26:48Z
- **Tasks:** 2 (both TDD)
- **Files modified:** 5 (3 created, 2 modified)

## Accomplishments
- Added a `UniverseSelectionModel` `Protocol` (runtime-checkable, `select(asof: datetime) -> set[str]`) and a concrete lean `StaticUniverseSelectionModel` under the D-20 header in `membership.py`: pure/queue-free/feed-free by construction (ctor takes only symbols), `select` returns a defensive copy, `set_symbols` is the operator/test mid-run add/remove lever. Explicitly documented as the lean poll seam (UNIV-01), NOT the deferred v2 ranked production screener. Exported from the `universe` barrel.
- Created `itrader/universe/universe_handler.py` (4-space, mypy `--strict` clean): `UniverseHandler` holds the queue + injected `Universe` read-model + feed + timeframe, plus three live-only seams (`_selection_source`/`_symbol_validator`/`_provider`) defaulting to `None` with `set_*` wiring setters. Holds ZERO membership duplication — reads/mutates only through the injected `Universe`.
- `on_time`: source-guard (`if self._selection_source is None: return` — the single cheap inertness lever) → `select(event.time)` → D-06 `validate_symbol` filter (direct call, keeps `Universe` connector-free) → `Universe.apply(desired, None)` → emit exactly ONE `UniverseUpdateEvent` ONLY when the delta is non-empty (no empty-delta floods).
- `on_universe_update` ADD branch: for each added symbol `feed.warmup(sym, tf)` FIRST then `provider.subscribe(sym)` (warmup-before-subscribe, Pitfall 6), tolerant of `provider is None` (paper/replay). A clearly-marked `# plan 04: REMOVE branch (policy) inserted here` placeholder leaves the `event.removed` handling for plan 04 to extend in place.

## Task Commits

Each task was committed atomically (TDD RED -> GREEN):

1. **Task 1: lean UniverseSelectionModel in membership.py**
   - `d985362e` (test — RED)
   - `b9db38a4` (feat — GREEN)
2. **Task 2: UniverseHandler on_time poll + add-side subscribe consumer**
   - `e196098a` (test — RED)
   - `6739da94` (feat — GREEN)

## Files Created/Modified
- `itrader/universe/membership.py` - Added `UniverseSelectionModel` Protocol + `StaticUniverseSelectionModel` under the D-20 header (4-space); `runtime_checkable` import.
- `itrader/universe/__init__.py` - Barrel export of the two new selection-model names.
- `itrader/universe/universe_handler.py` - NEW. `UniverseHandler` (poll host + add consumer) + three private Protocols (`_SupportsWarmup`/`_SymbolValidator`/`_SupportsSubscribe`).
- `tests/unit/universe/test_universe_selection.py` - NEW. 6 behaviors: Protocol conformance, static select, purity-by-construction (signature has only `symbols`; no queue/feed attrs), set_symbols drive, set return type, defensive copy.
- `tests/unit/universe/test_universe_poll.py` - NEW. 6 behaviors via fakes + a real `queue.Queue` and real `Universe`: source-guard no-op, empty-delta no-put, add emits one event, rejected-symbol dropped before apply, warmup-before-subscribe ORDER, provider-None tolerance.

## Decisions Made
- **Instrument resolution passes `None`:** `on_time` calls `Universe.apply(desired, None)`, deferring to the plan-01 `_DEFAULT_*` ladder fallback rather than building venue-precision `Instrument`s from a connector markets map. RESEARCH §6 flags venue-markets precision resolution as Claude's-discretion territory with a real precision-mode landmine (ccxt DECIMAL_PLACES vs TICK_SIZE); the plan's action text offers "else pass None" as an explicit branch and no must-have/test covers venue resolution. Passing `None` keeps the handler from reaching into connector internals (honors D-03 connector-free), relies on the plan-01 default-ladder guarantee (`.instrument(sym)` never `KeyError`s), and defers the venue-correct-precision resolver to plan-05 wiring where a real OKX markets map + precisionMode is available and testable. Documented inline.
- **Dedicated `UniverseHandler` (not `ScreenersHandler`):** followed the plan's deliberate PATTERNS §7 divergence — a NEW 4-space `universe/universe_handler.py` isolates the live-only poll route so plan 05 mutates the LIVE `_routes[TIME]` only and the backtest per-tick literal is untouched by construction (Pitfall 3 / A3 — zero W1 source-guard burden).
- **UNIV-01 NOT marked complete:** consistent with plan 01's note that UNIV-01 "completes across plans 02-05". Selection + poll + add-side land here; the REMOVE branch (plan 04) and live composition wiring (plan 05) remain.

## Deviations from Plan

None - plan executed exactly as written. (The instrument-resolution `None` choice is within the plan's explicit "else pass None" latitude, documented above as a design decision rather than a deviation.)

## Threat Model Coverage
- **T-06-03-SPOOF (mitigate):** `on_time` filters `desired` through `validate_symbol` (D-06) BEFORE `Universe.apply`, so a non-listed/spoofed symbol never enters membership or reaches `provider.subscribe`. Asserted by `test_on_time_rejected_symbol_dropped_before_apply` (rejected symbol never a member).
- **T-06-03-DOS (mitigate):** `on_time` puts NOTHING when the delta is empty. Asserted by `test_on_time_current_membership_puts_nothing` (empty-delta no-put).

## Issues Encountered
None.

## Known Stubs
None. The `# plan 04: REMOVE branch` placeholder in `on_universe_update` is an intentional, documented extension point for the next plan (the ADD branch is fully wired), not a stub blocking this plan's goal. The three live-only seams defaulting to `None` are the documented inert-unwired contract (plan 05 wires them), not stubs.

## Milestone Gate
- **Oracle byte-exact:** `tests/integration/test_backtest_oracle.py` 3 passed (134 / 46189.87730727451) — `UniverseHandler` is live-only (not on the backtest import/per-tick path); the `membership.py` additions are pure and unused on the backtest path.
- **Inertness:** `tests/integration/test_okx_inertness.py` 1 passed.
- **mypy --strict:** clean on the whole `itrader/universe` package (5 files).
- **Unit tests:** `tests/unit/universe` 48 passed (selection 6 + poll 6 + apply 10 + existing).

## Next Phase Readiness
- Plan 04 extends `on_universe_update` in place with the REMOVE branch (orphan-and-track vs force-close, leaving-set admission gate) — the placeholder + `Universe.mark_leaving/leaving_symbols/clear_leaving` surface (plan 01) are ready.
- Plan 05 wires the live path: mutate the LIVE `_routes[TIME]`/`_routes[UNIVERSE_UPDATE]`, construct `UniverseHandler`, and call `set_selection_source`/`set_symbol_validator`/`set_provider`.
- No blockers.

## Self-Check: PASSED

All created files present on disk; all four task commits (`d985362e`, `b9db38a4`, `e196098a`, `6739da94`) present in git history.

---
*Phase: 06-dynamic-universe-membership*
*Completed: 2026-07-06*

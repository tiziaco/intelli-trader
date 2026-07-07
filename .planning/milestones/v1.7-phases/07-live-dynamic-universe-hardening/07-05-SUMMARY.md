---
phase: 07-live-dynamic-universe-hardening
plan: 05
subsystem: universe
tags: [universe, poll, freeze-gate, precision-resolver, WR-04, WR-05, WR-06, live-trading]

# Dependency graph
requires:
  - phase: 07-01 (v1.7)
    provides: UniversePollEvent + EventType.UNIVERSE_POLL (the dedicated poll discriminator)
  - phase: 07-02 (v1.7)
    provides: Universe.apply(desired, instruments) add-branch (resolved.get(sym) or default) + TrackedInstrument record
  - phase: 06-dynamic-universe-membership (v1.7)
    provides: UniverseHandler on_time poll + _SymbolValidator seam pattern (the seam being hardened)
provides:
  - on_poll (renamed from on_time) consuming the dedicated UniversePollEvent — poll off the shared TIME route (WR-06)
  - set_freeze_gate seam + early-return freeze-in-place at the top of on_poll (WR-05/D-07)
  - _PrecisionResolver Protocol + set_precision_resolver seam + on_poll venue-precision resolution (WR-04/D-16)
affects: [07-07, live-poll-composition-root, freeze-gate-wiring, venue-precision-wiring]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Live-only injected seam mirroring _SymbolValidator (field None + set_X setter) reused verbatim for freeze gate + precision resolver"
    - "Freeze-in-place early-return (level-triggered, no replay/buffering) at the top of a control-plane handler"

key-files:
  created: []
  modified:
    - itrader/universe/universe_handler.py
    - tests/unit/universe/test_universe_poll.py
    - itrader/trading_system/live_trading_system.py

key-decisions:
  - "on_poll consumes the dedicated UniversePollEvent (WR-06/D-06) — poll never rides a route reaching screeners/bar-gen"
  - "Freeze gate early-returns at the TOP of on_poll, before select/apply (WR-05/D-07) — membership freezes in place, self-heals next unfrozen tick"
  - "_PrecisionResolver.resolve -> Instrument | None; None falls to Universe.apply's _DEFAULT_* ladder (paper); Universe stays connector-free (D-16)"
  - "All three seams (freeze gate, precision resolver, plus prior selection/validator/provider) default None — unwired handler is inert; route/predicate/resolver WIRING is Plan 07"

patterns-established:
  - "Control-plane poll: freeze-gate -> source-guard -> select -> venue-filter -> precision-resolve -> apply -> emit-only-on-non-empty"

requirements-completed: [WR-04, WR-05, WR-06]

# Metrics
duration: 5min
completed: 2026-07-06
---

# Phase 7 Plan 05: Poll Routing Hardening (dedicated route + freeze gate + precision resolver) Summary

**`UniverseHandler.on_time` is renamed `on_poll` and now consumes the DEDICATED `UniversePollEvent` (WR-06, off the shared TIME route), early-returns while a wired `_freeze_gate` reports the engine halted/paused so membership freezes in place (WR-05/D-07, level-triggered self-heal), and resolves poll-added symbols to venue precision via an injected `_PrecisionResolver` seam — falling to the `_DEFAULT_*` ladder when unwired (WR-04/D-16). All three seams default inert; the route/predicate/resolver wiring is Plan 07.**

## Performance

- **Duration:** ~5 min
- **Started:** 2026-07-06T18:45:28Z
- **Completed:** 2026-07-06T18:50:28Z
- **Tasks:** 2
- **Files modified:** 3 (0 created, 3 modified)

## Accomplishments
- `on_time` -> `on_poll` with its parameter type changed from `TimeEvent` to the new `UniversePollEvent` (WR-06/D-06) — the poll now consumes its own dedicated discriminator (`EventType.UNIVERSE_POLL`) instead of riding the business `TIME` route; the unused `TimeEvent` import was dropped.
- `set_freeze_gate(gate: Callable[[], bool])` seam + `self._freeze_gate` field mirroring `set_symbol_validator`; a top-of-`on_poll` early-return (`if self._freeze_gate is not None and self._freeze_gate(): return`) BEFORE any select/apply (WR-05/D-07 freeze-in-place — level-triggered, no replay/buffering). Unwired (None) never freeze-skips, so paper/backtest are inert.
- `_PrecisionResolver(Protocol)` (`resolve(symbol) -> Instrument | None`) mirroring `_SymbolValidator` exactly + `set_precision_resolver` seam + `_resolve_added_instruments` helper. `on_poll` now computes the added set (`desired - set(universe.members)`), builds a `{symbol: Instrument}` dict from the wired resolver (non-None only), and passes it to `Universe.apply(desired, instruments)` (replacing the hardcoded `apply(desired, None)`). `Universe` stays connector-free (D-16); an unresolvable symbol or an unwired resolver falls to the `_DEFAULT_*` ladder via `apply`'s `resolved.get(sym) or default`.
- `test_universe_poll.py` extended: freeze-gate short-circuit (spy asserts NO select, no apply, empty queue), freeze-gate-False-as-unwired, resolver-precision vs default-ladder for a poll-added symbol. The four prior `on_time` tests were migrated to `on_poll(UniversePollEvent(...))`.

## Task Commits

Each task was committed atomically:

1. **Task 1: on_time → on_poll (dedicated UNIVERSE_POLL route) + freeze gate** - `44db7a76` (feat)
2. **Task 2: _PrecisionResolver seam + on_poll precision resolution** - `aeae427e` (feat)

**Plan metadata:** _(final docs commit)_

## Files Created/Modified
- `itrader/universe/universe_handler.py` (modified, 4-space) - rename + freeze-gate seam + `_PrecisionResolver` seam + `_resolve_added_instruments` + on_poll precision wiring
- `tests/unit/universe/test_universe_poll.py` (modified, 4-space) - migrated on_time→on_poll; +4 tests (freeze-gate x2, precision x2), now 16 tests
- `itrader/trading_system/live_trading_system.py` (modified, TABS, ignore_errors) - method reference `on_time`→`on_poll` on the live TIME-route append (route migration deferred to Plan 07)

## Decisions Made
- Followed the plan's WR-04/05/06 (D-06/D-07/D-16) design exactly. Both new seams copy the established `_SymbolValidator`/`set_symbol_validator` shape (field defaults None, live-only setter) so an unwired handler stays inert.
- Indentation: 4 spaces in `universe/` + its tests; TABS in `live_trading_system.py` (matched per-file).
- `Callable` imported from `collections.abc` (non-deprecated form, mypy --strict clean).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Updated the live_trading_system.py `on_time` method reference to `on_poll`**
- **Found during:** Task 1
- **Issue:** `live_trading_system.py::_initialize_live_session` appends `self._universe_handler.on_time` to the live TIME route. Renaming `on_time` → `on_poll` would leave a dangling attribute reference (AttributeError at live wiring). The plan scopes the full route migration (TIME → UNIVERSE_POLL, poll-timer event type, freeze-gate/precision-resolver wiring) to Plan 07, but the bare method-name reference must not break in the meantime.
- **Fix:** Changed the single reference to `.on_poll` (both `UniversePollEvent` and the poll-timer's `TimeEvent` carry a business `.time`, so `on_poll` reads it either way). The dedicated-route migration + freeze-gate/precision-resolver wiring remains Plan 07's scope; a code comment records this.
- **Files modified:** `itrader/trading_system/live_trading_system.py`
- **Commit:** `44db7a76`

## Threat Surface

Threat register mitigations from the plan are all satisfied and asserted:
- **T-07-05-FREEZE** (Tampering): the `on_poll` top-of-body freeze gate early-returns while halted/paused (`test_on_poll_freeze_gate_true_short_circuits` — no select, no apply, no event); level-triggered self-heal, no naked teardown during freeze.
- **T-07-05-COUPLE** (Tampering): `on_poll` consumes only its own `UniversePollEvent` (`EventType.UNIVERSE_POLL`), never the shared `TIME` route (WR-06/D-06).
- **T-07-05-PRECISION** (Tampering): venue precision is injected via `_PrecisionResolver` from the (Plan-07-built) markets map; `Universe` stays connector-free; a poll-added symbol carries the resolver's precision (`test_on_poll_added_symbol_takes_resolver_precision`) and the default ladder otherwise.
- **T-07-05-SC** (accept): no package installs in this plan.

No NEW security-relevant surface introduced (no endpoints, auth paths, file/schema access). The precision resolver reads the OKX markets map — an existing untrusted-venue boundary already in the threat model, mitigated by the string-path Decimal contract (resolver IMPLEMENTATION is Plan 07).

## Known Stubs
None — the three seams are real. The freeze-gate PREDICATE (`lambda: engine._is_halted() or engine._is_submission_paused()`), the precision-resolver IMPLEMENTATION (built from the OKX markets map), and the dedicated-route migration (poll timer emitting `UniversePollEvent` on the `UNIVERSE_POLL` route) are the declared Plan 07 composition-root wiring — this plan is the seam + on_poll logic + fake-driven tests, its stated scope.

## Issues Encountered
None.

## User Setup Required
None.

## Verification
- `poetry run pytest tests/unit/universe/test_universe_poll.py -q` → **16 passed**.
- `poetry run pytest tests/unit/universe -q` → **66 passed**.
- `poetry run mypy itrader/universe/universe_handler.py` → clean (1 source file).
- `grep "def on_poll"` matches; `grep -c "def on_time"` = 0; `grep -c "apply(desired, None)"` = 0; `class _PrecisionResolver` + `def set_precision_resolver` both present.
- Milestone gate: `import itrader.trading_system.live_trading_system` OK (live path un-broken); oracle byte-exact + determinism double-run (`tests/integration/test_backtest_oracle.py`) → **3 passed** (134 / 46189.87730727451 untouched — universe_handler is live-only, never on the backtest path).

## Next Phase Readiness
- The dedicated-route, freeze-gated, precision-correct `on_poll` is in place with all three seams inert-by-default. Plan 07 wires at the live composition root: (1) the poll timer emits `UniversePollEvent` on the `UNIVERSE_POLL` route (replacing the TIME-route append), (2) `set_freeze_gate` to the halt/pause predicate, (3) `set_precision_resolver` to the OKX-markets-map resolver.

## Self-Check: PASSED

- FOUND: itrader/universe/universe_handler.py
- FOUND: tests/unit/universe/test_universe_poll.py
- FOUND: .planning/phases/07-live-dynamic-universe-hardening/07-05-SUMMARY.md
- FOUND commit: 44db7a76
- FOUND commit: aeae427e

---
*Phase: 07-live-dynamic-universe-hardening*
*Completed: 2026-07-06*

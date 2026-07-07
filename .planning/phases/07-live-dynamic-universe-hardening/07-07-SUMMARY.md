---
phase: 07-live-dynamic-universe-hardening
plan: 07
subsystem: trading-system
tags: [live-trading, composition-root, add-event, allowlist, universe, poll, freeze-gate, precision-resolver, WR-04, WR-06, OP-SEAM, D-10, D-06, D-12, D-16]

# Dependency graph
requires:
  - phase: 07-01 (v1.7)
    provides: UniversePollEvent/StrategyCommandEvent/BarsLoaded/BarsLoadFailed structs + EventType members + explicit-empty backtest _routes
  - phase: 07-04 (v1.7)
    provides: StrategiesHandler.set_universe / on_bars_loaded / on_strategy_command + get_strategies_universe
  - phase: 07-05 (v1.7)
    provides: UniverseHandler on_poll (dedicated UNIVERSE_POLL route) + set_freeze_gate + set_precision_resolver (_PrecisionResolver Protocol)
  - phase: 07-06 (v1.7)
    provides: UniverseHandler on_bars_loaded / on_bars_load_failed + StrategyDerivedSelectionModel
provides:
  - "add_event fail-closed default-deny allowlist (_EXTERNALLY_ADMISSIBLE = {SIGNAL, STRATEGY_COMMAND}); every internal-fact type rejected (D-10)"
  - "poll timer emits UniversePollEvent on the dedicated UNIVERSE_POLL route (D-06/WR-06), not a TIME event"
  - "live EventHandler routes for UNIVERSE_POLL/STRATEGY_COMMAND/BARS_LOADED/BARS_LOAD_FAILED wired live-only (list order = execution order); backtest literal untouched"
  - "strategy-derived selection source (D-12) + strategies.set_universe + set_freeze_gate (WR-05) + _OkxPrecisionResolver over the OKX markets map (WR-04/D-16), guarded on okx presence"
affects: [live-composition-root, milestone-gate, phase-07-close]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Fail-closed default-deny allowlist at the external ingress (ASVS V4/V5) — admit an explicit frozenset, reject everything else"
    - "Live-only seam wiring confined to _initialize_live_session on a SEPARATE EventHandler — the backtest _routes literal is never mutated (oracle-inertness contract)"
    - "Venue-precision resolver built at the composition root from the connector markets map (Decimal string path), Universe stays connector-free"

key-files:
  created: []
  modified:
    - itrader/trading_system/live_trading_system.py
    - tests/unit/trading_system/test_add_event_admission_guard.py
    - tests/integration/test_okx_inertness.py

key-decisions:
  - "add_event inverted denylist->allowlist: _EXTERNALLY_ADMISSIBLE frozenset admits exactly SIGNAL + STRATEGY_COMMAND; every other type (incl. the prior narrow ORDER reject) is default-denied (D-10)"
  - "Poll timer swaps TimeEvent -> UniversePollEvent; the now-unused TimeEvent import was removed (no remaining instantiation on the live path)"
  - "_OkxPrecisionResolver is a module-level class (satisfies the _PrecisionResolver Protocol), reading okx._connector.client.markets precision via the D-04 string path; None on unloaded markets/absent symbol -> Universe.apply _DEFAULT_* ladder"
  - "Selection source swapped to StrategyDerivedSelectionModel (reads the live strategy universe each poll, D-12); StaticUniverseSelectionModel no longer used at the live root"

patterns-established:
  - "The recurring milestone gate (oracle byte-exact + inertness + full-suite + mypy + W1/W2 A/B) is the phase-close proof; W1/W2 attributed via same-machine A/B, never the frozen-baseline compare"

requirements-completed: [WR-04, WR-06, OP-SEAM]

# Metrics
duration: ~8min (autonomous work) + human W1/W2 A/B checkpoint
completed: 2026-07-06
---

# Phase 7 Plan 07: Live Composition-Root Wiring + Milestone Gate Summary

**The Phase-7 seams are wired at the live composition root and the recurring milestone gate is proven: `add_event` is inverted from a narrow ORDER denylist to a fail-closed default-deny allowlist (`_EXTERNALLY_ADMISSIBLE = {SIGNAL, STRATEGY_COMMAND}`, D-10 — the primary external-surface security control); the poll timer emits `UniversePollEvent` on its own dedicated `UNIVERSE_POLL` route (D-06/WR-06, off the shared TIME route); the live EventHandler routes the four new control types (list order = execution order, BARS_LOADED runs strategies-then-universe) while the backtest `_routes` literal stays untouched; the selection source becomes the strategy-derived model (D-12) with `set_universe`, `set_freeze_gate` (WR-05), and an `_OkxPrecisionResolver` over the OKX markets map (WR-04/D-16) all wired live-only — and the backtest oracle stays byte-exact (134 / `46189.87730727451`) with no W1/W2 regression (same-machine A/B).**

## Performance

- **Duration:** ~8 min autonomous + human W1/W2 A/B checkpoint
- **Tasks:** 3 (Tasks 1-2 autonomous; Task 3 automatable half + human-verify W1/W2)
- **Files modified:** 3 (0 created, 3 modified)

## Accomplishments

- **Task 1 — `add_event` fail-closed allowlist (D-10):** Added module-level
  `_EXTERNALLY_ADMISSIBLE = frozenset({EventType.SIGNAL, EventType.STRATEGY_COMMAND})` and
  replaced the narrow `is EventType.ORDER` reject with `event_type not in _EXTERNALLY_ADMISSIBLE
  -> warn + return False`. The `if not self._running` guard and the try/except `put` are
  unchanged. The docstring now describes the ASVS V4/V5 default-deny posture. The admission-guard
  test was rewritten into a table: SIGNAL + STRATEGY_COMMAND are admitted (enqueued, returns True);
  each internal-fact type is rejected (returns False, never enqueued) — plus a check that the
  allowlist is EXACTLY `{SIGNAL, STRATEGY_COMMAND}`.
- **Task 2 — live composition wiring:** `_run_poll_timer` swaps `TimeEvent(time=datetime.now(UTC))`
  -> `UniversePollEvent(time=datetime.now(UTC))` (the sole wall-clock event; cadence wait unchanged);
  the now-unused `TimeEvent` import was removed. Route mutations on the LIVE EventHandler:
  `UNIVERSE_POLL = [on_poll]`, `UNIVERSE_UPDATE = [on_universe_update]`,
  `STRATEGY_COMMAND = [strategies.on_strategy_command]`,
  `BARS_LOADED = [strategies.on_bars_loaded, universe.on_bars_loaded]` (list order = execution
  order — warm indicators FIRST, then absorb ring + mark_ready + subscribe, D-03b),
  `BARS_LOAD_FAILED = [universe.on_bars_load_failed]`, `FILL.append(universe.on_fill)`; the
  `TIME.append(on_poll)` line is GONE. Seams: `set_selection_source(StrategyDerivedSelectionModel(
  self.strategies_handler))` (D-12), `strategies_handler.set_universe(universe)` (Plan 04 readiness
  gate), `set_freeze_gate(lambda: self._is_halted() or self._is_submission_paused())` (WR-05/D-07),
  and guarded on `self._okx_exchange is not None`: `set_symbol_validator` + a new
  `set_precision_resolver(_OkxPrecisionResolver(self._okx_exchange))` (WR-04/D-16). The backtest
  `_routes` literal is never touched (SEPARATE EventHandler).
- **`_OkxPrecisionResolver` (new, WR-04/D-16):** module-level class satisfying the
  `_PrecisionResolver` Protocol; reads `okx._connector.client.markets[symbol]['precision']` (the
  SAME source `validate_symbol`/`*_to_precision` consume), normalises the symbol through the venue
  `_to_symbol` helper, and converts the venue tick sizes into an `Instrument` with Decimal
  price/quantity scales via the D-04 string path (`Decimal(str(x))`, never `Decimal(float)`).
  Returns `None` on unloaded markets / absent symbol / unusable precision -> `Universe.apply` falls
  to the `_DEFAULT_*` ladder (the paper posture). `Universe` stays connector-free.
- **Task 3 (automatable half) — inertness:** extended `test_okx_inertness.py` with a test that
  builds a fresh backtest `EventHandler` (MagicMock collaborators + real Queue) and asserts the four
  Phase-7 routes (`UNIVERSE_POLL`/`STRATEGY_COMMAND`/`BARS_LOADED`/`BARS_LOAD_FAILED`) are
  explicit-empty lists — the 3-step-flow inertness guarantee, complementing the existing subprocess
  module-absence probe (universe_handler / live_bar_feed / okx / ccxt / replay_provider /
  venue_reconciler stay forbidden on the backtest import path).

## Task Commits

Each task was committed atomically:

1. **Task 1: invert add_event to a fail-closed allowlist (D-10)** — `a2f7c909` (feat)
2. **Task 2: wire live composition seams — poll swap, routes, freeze/precision (D-06/D-12/D-16)** — `0ce38c51` (feat)
3. **Task 3: assert backtest EventHandler keeps the four Phase-7 routes inert-empty** — `438f9e3c` (test)

**Plan metadata:** _(final docs commit)_

## Files Created/Modified

- `itrader/trading_system/live_trading_system.py` (modified, 4-SPACE — confirmed zero tab lines) —
  `_EXTERNALLY_ADMISSIBLE` constant + fail-closed `add_event`; `_precision_to_scale` helper +
  `_OkxPrecisionResolver` class; `UniversePollEvent`/`Instrument` imports (+ `InvalidOperation`);
  removed the unused `TimeEvent` import; poll-timer event swap; live route mutations + selection
  source / set_universe / set_freeze_gate / set_precision_resolver wiring.
- `tests/unit/trading_system/test_add_event_admission_guard.py` (modified, 4-SPACE, `unit`) —
  table-driven fail-closed assertions (allowlist-exact + admit SIGNAL/STRATEGY_COMMAND + reject
  every internal-fact type); imports `_EXTERNALLY_ADMISSIBLE`.
- `tests/integration/test_okx_inertness.py` (modified, 4-SPACE, `integration`) — new
  backtest-EventHandler four-route inert-empty assertion.

## Decisions Made

- Followed the plan exactly for D-10 / D-06 / D-12 / D-16 / WR-04 / WR-05 wiring. Indentation matched
  per file: **live_trading_system.py is 4-space, zero tab lines** (empirically confirmed — the plan's
  guidance was correct; a stale note in the 07-05 SUMMARY calling it TABS was wrong).
- `_OkxPrecisionResolver` built as a module-level class (not an inline closure) so it is a clean,
  named `_PrecisionResolver` implementation; margin fields default to the inert `derive_instruments`
  placeholders (unused on the spot path this phase).
- The unused `TimeEvent` import was removed after the poll-timer swap (grep confirmed no remaining
  `TimeEvent(` instantiation on the live path).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Plan docstring listed a non-existent `EventType.PORTFOLIO_UPDATE`**
- **Found during:** Task 1 (writing the internal-fact rejection table)
- **Issue:** The plan's action text enumerated the internal-fact types as
  `FILL/BAR/UNIVERSE_UPDATE/UNIVERSE_POLL/BARS_LOADED/BARS_LOAD_FAILED/TIME/ORDER/ERROR/PORTFOLIO_UPDATE`,
  but `core/enums/event.py::EventType` has **no `PORTFOLIO_UPDATE` member** — the portfolio-update
  event type is named `UPDATE` (line 25; the routes literal comment confirms "live API path consumes
  these"). Using `EventType.PORTFOLIO_UPDATE` would `AttributeError` at test collection.
- **Fix:** Used the real member `EventType.UPDATE` in the rejection table, and additionally covered
  `EventType.ORDER_ACK` and `EventType.SCREENER` (also internal-fact types present in the enum) for a
  fuller default-deny proof. The production `add_event` allowlist is unaffected (it admits a positive
  set, so it rejects `UPDATE`/`ORDER_ACK`/`SCREENER`/every non-listed type by construction regardless
  of naming).
- **Files modified:** `tests/unit/trading_system/test_add_event_admission_guard.py`
- **Commit:** `a2f7c909`

## Threat Surface

Threat register mitigations from the plan are all satisfied and asserted:
- **T-07-07-INJECT / T-07-07-SPOOF-ORDER** (Elevation of Privilege): `add_event` is default-deny —
  the admission-guard test asserts EACH internal-fact type (FILL/BAR/UNIVERSE_*/BARS_*/TIME/ORDER/
  ORDER_ACK/SCREENER/ERROR/UPDATE) is rejected, and the allowlist is exactly `{SIGNAL,
  STRATEGY_COMMAND}`. Raw ORDER injection is covered by the default-deny gate.
- **T-07-07-ORACLE** (DoS via live routing leaking onto the backtest path): all live mutations are
  confined to `_initialize_live_session` on a SEPARATE EventHandler; the inertness gate forbids live
  modules on the backtest import AND asserts the four new routes are explicit-empty on a fresh
  backtest EventHandler; the oracle byte-exact gate is green.
- **T-07-07-CLOCK** (Tampering): `UniversePollEvent` is the SOLE wall-clock control-plane event; bar/
  fill business time stays venue-sourced (Pitfall 3).
- **T-07-07-SC** (accept): no package installs in this phase.

No NEW security-relevant surface introduced (no new endpoints/auth paths/file access). The precision
resolver reads the OKX markets map — an existing untrusted-venue boundary already in the threat model,
mitigated by the string-path Decimal contract.

## Known Stubs

None — every seam is real and wired. The `_OkxPrecisionResolver`'s live venue behavior is exercised
only against a loaded OKX markets map (an online precondition), so its precision correctness is proven
by construction (string-path Decimal, mirrors `validate_symbol`/`*_to_precision`) rather than by an
offline unit test; the paper/replay fallback (resolver unset -> default ladder) is the offline path.

## Milestone Gate (recurring) — ALL GREEN

1. **Oracle byte-exact:** `tests/integration/test_backtest_oracle.py` -> **3 passed** — 134 trades /
   final_equity `46189.87730727451` (`check_exact=True`), determinism double-run identical.
2. **Inertness:** `tests/integration/test_okx_inertness.py` -> **2 passed** — subprocess
   module-absence probe (universe_handler / live_bar_feed / okx / ccxt / replay_provider /
   venue_reconciler forbidden on the backtest import path) + the new backtest-EventHandler
   four-route inert-empty assertion.
3. **Full suite:** `poetry run pytest tests` -> **1929 passed, 6 skipped** (all skips are
   OKX-credential-gated live tests, expected offline) under `filterwarnings=["error"]`,
   `--strict-markers`.
4. **Type gate:** `poetry run mypy itrader` (`--strict`) -> **clean, 234 source files**.
5. **W1/W2 — no regression (same-machine A/B, human-verified):**

   | Side | Commit | Runs (s) | Median | peak_mem | total_fills |
   |------|--------|----------|--------|----------|-------------|
   | PRE  | `3b9059ff` (pre-07-01) | 20.549 / 19.978 / 20.051 | **20.051 s** | 144.47 MB | 1578 |
   | POST | `438f9e3c` (HEAD)       | 20.030 / 20.111 / 20.030 | **20.030 s** | 144.48 MB | 1578 |

   - **Harness:** `poetry run python -m perf.runners.run_w1_benchmark` (pinned window
     2026-04-23→2026-06-23, seed 42), 3 runs/side, same machine, back-to-back.
   - **Delta:** median **-0.10%**, min +0.26% — within noise; memory identical; fills identical.
   - **Attribution:** NO Phase-7 per-tick regression. The absolute ~20 s (vs the frozen **15.7 s**
     baseline) is this machine's thermal/load state, NOT Phase 7 — proven because the pre-Phase-7
     code (`3b9059ff`) runs at the same ~20 s on this same box. The frozen-baseline compare was
     deliberately avoided (memory `v15-perf-gateb-thermal-drift`); **`W1-BASELINE.json` was NOT
     re-frozen** on this throttled machine.

## Issues Encountered

- `requirements.mark-complete WR-04 WR-06 OP-SEAM` is expected to report `not_found` — the Phase-7
  WR-/OP- requirement IDs are not present in `.planning/REQUIREMENTS.md`'s traceability table (Phase 7
  was added post-hoc from the Phase 6 code review). Consistent with prior 07-01..06 plans; tracked in
  the phase docs / ROADMAP instead. Not a blocker.

## User Setup Required

None — all executed gates are socket-free/offline (the 6 skipped tests are opt-in OKX-credential
live tests). The W1/W2 A/B judgment was performed by the human coordinator.

## Self-Check: PASSED

- FOUND: itrader/trading_system/live_trading_system.py (`_EXTERNALLY_ADMISSIBLE`, `_OkxPrecisionResolver`)
- FOUND: tests/unit/trading_system/test_add_event_admission_guard.py
- FOUND: tests/integration/test_okx_inertness.py
- FOUND: .planning/phases/07-live-dynamic-universe-hardening/07-07-SUMMARY.md
- FOUND commit: a2f7c909
- FOUND commit: 0ce38c51
- FOUND commit: 438f9e3c

---
*Phase: 07-live-dynamic-universe-hardening*
*Completed: 2026-07-06*

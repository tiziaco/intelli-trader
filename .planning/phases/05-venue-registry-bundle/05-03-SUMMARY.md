---
phase: 05-venue-registry-bundle
plan: 03
subsystem: api
tags: [protocol, runtime_checkable, live-provider, replay, venue-registry, inertness]

# Dependency graph
requires:
  - phase: 04-storage-schema-migrations-relocation-new-durable-stores
    provides: ReplayDataProvider (paper-replay parity fixture over the golden CsvPriceStore)
provides:
  - "LiveDataProvider @runtime_checkable Protocol — the uniform live-data-provider surface (required set_bar_sink + optional streaming/wiring seams)"
  - "BaseLiveDataProvider — concrete no-op defaults for every optional streaming seam (is_streaming_healthy -> True)"
  - "ReplayDataProvider now inherits BaseLiveDataProvider — a uniform LiveDataProvider with deliberate no-op streaming seams"
affects: [venue-lifecycle, 05-06, 05-04, venue-registry, paper-path-wiring]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Optional-method uniformity via a no-op base (D-10): an optional METHOD on a PRESENT object gets a no-op default, killing hasattr probes at the call site"
    - "runtime_checkable Protocol as a swap-a-fake structural seam (mirrors connectors/base.py LiveConnector)"

key-files:
  created:
    - itrader/price_handler/providers/live_provider.py
    - tests/unit/price_handler/test_live_provider.py
  modified:
    - itrader/price_handler/providers/replay_provider.py
    - tests/unit/price/test_replay_provider.py

key-decisions:
  - "set_bar_sink is NOT defaulted on BaseLiveDataProvider (fail-loud): a defaulted no-op would silently drop every closed bar, so a bare base is intentionally NOT a conforming provider — it becomes one the moment a subclass adds set_bar_sink"
  - "OkxDataProvider is NOT edited — it already exposes the full surface so it conforms structurally (also avoids a file conflict with 05-01's StreamSupervisor delegation in okx_provider.py)"

patterns-established:
  - "Uniform provider surface (VENUE-05 / D-10): base no-op seams + a real set_bar_sink = a LiveDataProvider the VenueLifecycle wires unconditionally (no venue branch)"

requirements-completed: [VENUE-05]

coverage:
  - id: D1
    description: "LiveDataProvider @runtime_checkable Protocol + BaseLiveDataProvider no-op defaults for every optional streaming seam (is_streaming_healthy -> True); set_bar_sink deliberately not defaulted"
    requirement: "VENUE-05"
    verification:
      - kind: unit
        ref: "tests/unit/price_handler/test_live_provider.py"
        status: pass
      - kind: integration
        ref: "tests/integration/test_okx_inertness.py (live_provider imports nothing ccxt/sqlalchemy/async)"
        status: pass
    human_judgment: false
  - id: D2
    description: "ReplayDataProvider inherits BaseLiveDataProvider — a uniform LiveDataProvider with no-op streaming seams; behavior unchanged; both standing gates green"
    requirement: "VENUE-05"
    verification:
      - kind: unit
        ref: "tests/unit/price/test_replay_provider.py#test_replay_provider_is_a_uniform_live_data_provider"
        status: pass
      - kind: integration
        ref: "tests/integration/test_backtest_oracle.py (byte-exact 46189.87730727451) + test_okx_inertness.py"
        status: pass
    human_judgment: false

# Metrics
duration: 4min
completed: 2026-07-12
status: complete
---

# Phase 5 Plan 03: Uniform LiveDataProvider Surface Summary

**LiveDataProvider @runtime_checkable Protocol + BaseLiveDataProvider no-op base, with ReplayDataProvider inheriting it — every live data provider now presents ONE structural shape the VenueLifecycle can wire unconditionally (no `if exchange==` provider branch, no `hasattr`).**

## Performance

- **Duration:** ~4 min
- **Started:** 2026-07-12T22:18:14Z
- **Completed:** 2026-07-12T22:22Z
- **Tasks:** 2
- **Files modified:** 4 (2 created, 2 modified)

## Accomplishments
- `LiveDataProvider` `@runtime_checkable` Protocol declares the uniform provider surface: required `set_bar_sink` + the optional streaming/wiring seams (`set_global_queue`, `set_halt_signal`, `set_stream_state_listener`, `subscribe`, `unsubscribe`, `spawn_warmup`, `is_streaming_healthy`), mirroring the `LiveConnector` shape.
- `BaseLiveDataProvider` supplies inert `return None` / `return True` defaults for every optional seam so a non-streaming provider can be wired unconditionally — killing the venue-string provider-wiring branch VENUE-06 removes (D-10).
- `ReplayDataProvider(BaseLiveDataProvider)`: gains the no-op streaming seams while keeping its own real `set_bar_sink`, so `isinstance(replay, LiveDataProvider)` is True; offline-replay behavior is unchanged.
- `OkxDataProvider` conforms structurally without any edit (avoids a file conflict with 05-01's StreamSupervisor delegation).
- Both standing gates hold: oracle byte-exact (`46189.87730727451`, determinism double-run identical) and OKX import-inertness green; `live_provider.py` is 4-space, pure typing/no-op, imports nothing ccxt/sqlalchemy/async; `mypy --strict` clean.

## Task Commits

Each task was committed atomically:

1. **Task 1: Define LiveDataProvider Protocol + BaseLiveDataProvider no-op defaults** (TDD)
   - `a7ee55e3` (test — RED gate: failing test for the Protocol + base)
   - `40e664a2` (feat — GREEN gate: implementation + inertness-scan test refinement)
2. **Task 2: Make ReplayDataProvider inherit BaseLiveDataProvider** - `a57b8401` (feat)

**Plan metadata:** _(this docs commit)_

_TDD note: Task 1 followed RED → GREEN (no REFACTOR needed)._

## Files Created/Modified
- `itrader/price_handler/providers/live_provider.py` - NEW. `LiveDataProvider` `@runtime_checkable` Protocol + `BaseLiveDataProvider` no-op base (4-space; inert; mypy --strict clean).
- `tests/unit/price_handler/test_live_provider.py` - NEW. No-op default seams, runtime_checkable structural conformance (fake / base+set_bar_sink / OKX), set_bar_sink-not-defaulted fail-loud, import-inertness scan.
- `itrader/price_handler/providers/replay_provider.py` - `class ReplayDataProvider(BaseLiveDataProvider)` + import; decision-anchored docstring note.
- `tests/unit/price/test_replay_provider.py` - Added uniform-provider conformance + inherited-no-op-seam tests.

## Decisions Made
- **`set_bar_sink` is NOT defaulted on the base (fail-loud).** A defaulted no-op would silently drop every closed bar. Consequence: a bare `BaseLiveDataProvider` is intentionally NOT a conforming `LiveDataProvider` (`isinstance` is False); it becomes one only when a subclass adds the real `set_bar_sink` (exactly what `ReplayDataProvider` does). This reconciles the plan's "prove conformance with BaseLiveDataProvider" intent with the explicit "do not default set_bar_sink" instruction by proving conformance via a base subclass that adds the required method.
- **`OkxDataProvider` left untouched** — already exposes the full surface (structural conformance), which also avoids a merge conflict with 05-01's StreamSupervisor delegation in `okx_provider.py`.

## Deviations from Plan

None - plan executed exactly as written. (The Task 1 test asserts `isinstance` conformance via a `BaseLiveDataProvider` subclass that adds `set_bar_sink` and additionally asserts a bare base is NOT yet conforming — a faithful reading of the plan's behavior spec under the explicit "set_bar_sink is NOT defaulted" instruction, not a scope change.)

## Issues Encountered
- The initial import-inertness test scanned the whole module source for the substrings `ccxt`/`sqlalchemy`, which tripped on the docstring prose that legitimately names those libraries when explaining the D-10 rule. Fixed by scanning only actual `import` / `from ... import` lines (the correct check). Resolved within Task 1's GREEN phase before the feat commit.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- The uniform provider surface is ready for the `VenueLifecycle` (05-06): it can now call the streaming seams on ANY provider unconditionally — the base-backed `ReplayDataProvider` no-ops them, the `OkxDataProvider` implements them — so the `if exchange=='okx' … elif =='paper'` provider-wiring divergence can be deleted without `hasattr` sprinkling.
- The single legitimate `hasattr(self._provider, "spawn_gap_backfill")` capability probe at `live_bar_feed.py:501` is untouched (loop-native-backfill probe, not the venue-string divergence VENUE-05 targets).

## Self-Check: PASSED

- FOUND: `itrader/price_handler/providers/live_provider.py`
- FOUND: `tests/unit/price_handler/test_live_provider.py`
- FOUND commit `a7ee55e3` (test), `40e664a2` (feat), `a57b8401` (feat)

---
*Phase: 05-venue-registry-bundle*
*Completed: 2026-07-12*

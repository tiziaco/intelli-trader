---
phase: 07-live-dynamic-universe-hardening
plan: 06
subsystem: universe
tags: [universe, warmup, readiness, keep-until-flat, selection, WR-01, WR-02, OP-SEAM, live-trading]

# Dependency graph
requires:
  - phase: 07-02 (v1.7)
    provides: Universe.mark_ready/mark_failed/discard_instrument + TrackedInstrument record (keep-until-flat)
  - phase: 07-03 (v1.7)
    provides: feed.absorb_warmup (non-emitting ring/L absorb) + provider.spawn_warmup (async → BarsLoaded/BarsLoadFailed)
  - phase: 07-05 (v1.7)
    provides: UniverseHandler on_poll + injected-seam pattern (freeze gate / precision resolver / provider) extended here
  - phase: 07-01 (v1.7)
    provides: BarsLoaded / BarsLoadFailed event structs
provides:
  - "UniverseHandler async add-branch: provider.spawn_warmup (live) vs synchronous feed.warmup + mark_ready (paper) with per-symbol try isolation (D-04)"
  - "on_bars_loaded: absorb_warmup → mark_ready → subscribe in deterministic route order (D-03b, WR-02)"
  - "on_bars_load_failed: mark_failed, kept in membership, retried next poll (D-04)"
  - "discard_instrument teardown at the two final points (no-holder removal + detach-on-flat) — WR-01 keep-until-flat proven (D-13)"
  - "StrategyDerivedSelectionModel: select() reads the live strategy universe each call (D-12, OP-SEAM)"
affects: [07-07, live-poll-composition-root, warmup-before-subscribe, strategy-command-propagation]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Readiness-gated warmup pipeline: async spawn (I/O) → BarsLoaded consumer completes absorb→ready→subscribe (D-03b)"
    - "Per-symbol try isolation on the add batch — one failure never aborts the batch or the remove branch (D-04)"
    - "Read-live selection source (no held snapshot) so operator edits propagate on next poll (D-12)"

key-files:
  created:
    - tests/unit/universe/test_universe_warmup_consumers.py
  modified:
    - itrader/universe/universe_handler.py
    - itrader/universe/membership.py
    - tests/unit/universe/test_universe_poll.py
    - tests/integration/test_universe_remove_policy.py

key-decisions:
  - "Extended _SupportsSubscribe with spawn_warmup (one provider seam) rather than a separate Protocol — the live OkxDataProvider carries subscribe/unsubscribe/spawn_warmup together"
  - "Paper/no-provider path resolved to ONE behavior (WARNING 1): synchronous feed.warmup + IMMEDIATE mark_ready — a poll-added paper symbol is NEVER left PENDING (would permanently block trading under the 07-04 strategy gate + 07-08 admission gate)"
  - "Warmup depth K = feed.cache_capacity() + _WARMUP_MARGIN with a LOCAL _WARMUP_MARGIN=5 mirroring live_bar_feed (WARNING 2, RESEARCH OQ4 SAFE for SMA_MACD-only); depth_hint seam DEFERRED (todo present)"
  - "discard_instrument only at the two final-teardown points (no-holder removal + on_fill detach-on-flat); force-close discards on flat too, same as orphan-and-track — grep count exactly 2"
  - "StrategyDerivedSelectionModel is a NEW class; StaticUniverseSelectionModel kept in place (paper default / other callers)"

patterns-established:
  - "The WR-02 warmup-before-subscribe contract is completed handler-side: add-branch spawns, on_bars_loaded gates readiness then subscribes"

requirements-completed: [WR-01, WR-02, OP-SEAM]

# Metrics
duration: ~12min
completed: 2026-07-06
---

# Phase 7 Plan 06: Async Warmup Consumers + Keep-Until-Flat Teardown + Strategy-Derived Selection Summary

**The WR-02 handler-side centrepiece: the `UniverseHandler` add-branch now KICKS OFF warmup (async `provider.spawn_warmup` live, synchronous `feed.warmup` + immediate `mark_ready` paper — never left PENDING) with per-symbol isolation, and the readiness-gated consumers complete the pipeline — `on_bars_loaded` runs absorb → mark_ready → subscribe in that deterministic order (D-03b) while `on_bars_load_failed` marks the symbol FAILED and keeps it a member (retried next poll, D-04); WR-01 keep-until-flat is finished by `discard_instrument` at the two final-teardown points (no-holder removal + detach-on-flat), and a new `StrategyDerivedSelectionModel` reads the live strategy set each `select()` so operator ticker edits propagate (D-12).**

## Performance

- **Duration:** ~12 min
- **Tasks:** 3
- **Files modified:** 5 (1 created, 4 modified)

## Accomplishments

- **Async add-branch (Task 1):** `on_universe_update` replaces the synchronous `feed.warmup` + `provider.subscribe` per added symbol with `_begin_warmup(sym)`: live (provider wired) → `provider.spawn_warmup(sym, tf, K)` (I/O only, no state, `K = feed.cache_capacity() + _WARMUP_MARGIN`); paper (`provider is None`) → synchronous `feed.warmup(sym, tf)` + IMMEDIATE `universe.mark_ready(sym)`. Each added symbol's warmup runs in its OWN `try` (D-04) so one spawn failure never aborts the remaining adds nor the remove branch.
- **Readiness-gated consumers (Task 1):** `on_bars_loaded` runs `feed.absorb_warmup` → `universe.mark_ready` → `provider.subscribe` in EXACTLY that order (D-03b — subscribe only after the ring is warmed and readiness flipped); `on_bars_load_failed` calls `universe.mark_failed` + a logged WARNING naming the symbol, NEVER removing it from membership (rollback redundant with the gate).
- **Protocol seams (Task 1):** `_SupportsWarmup` extended with `absorb_warmup` + `cache_capacity`; `_SupportsSubscribe` extended with `spawn_warmup` (one provider seam — the live `OkxDataProvider` carries all three).
- **discard_instrument teardown (Task 2):** added at the two final-teardown points co-located with the existing unsubscribe — `_on_symbol_removed` no-holder branch (nothing references the symbol → discard now) and `on_fill` detach-on-flat (the orphan went flat → discard). The orphan-and-track WITH-open-position branch does NOT discard (keep-until-flat). `grep -c discard_instrument` = exactly 2.
- **Strategy-derived selection (Task 3):** `StrategyDerivedSelectionModel.select` reads `source.get_strategies_universe()` on EVERY call (no held snapshot) so an operator ticker edit propagates on the next poll; `SupportsStrategiesUniverse` Protocol (structurally satisfied by `StrategiesHandler`); `StaticUniverseSelectionModel` kept in place.

## Task Commits

Each task was committed atomically:

1. **Task 3: StrategyDerivedSelectionModel (D-12)** — `d39d0594` (feat) — committed first so the Task-1 test's import resolves.
2. **Task 1 (+ Task 2 code): async warmup consumers + discard_instrument teardown** — `38a8cb79` (feat)
3. **Task 2 (integration proof): keep-until-flat + atomic discard end-to-end** — `4bf3c9f5` (test)

**Plan metadata:** _(final docs commit)_

## Files Created/Modified

- `itrader/universe/universe_handler.py` (modified, 4-SPACE) — async add-branch + `_begin_warmup` + `on_bars_loaded` + `on_bars_load_failed` + `discard_instrument` at 2 points + extended Protocols + `_WARMUP_MARGIN` + imports (BarsLoaded/BarsLoadFailed/Bar)
- `itrader/universe/membership.py` (modified, 4-SPACE) — `SupportsStrategiesUniverse` Protocol + `StrategyDerivedSelectionModel`
- `tests/unit/universe/test_universe_warmup_consumers.py` (created, 4-SPACE, `unit`) — 8 tests: spawn-no-subscribe, ordered absorb→ready→subscribe spy, provider-none absorb, FAILED-keeps-member, per-symbol isolation, paper synchronous-READY, + 2 strategy-derived
- `tests/unit/universe/test_universe_poll.py` (modified, 4-SPACE) — migrated the 2 old synchronous-add-branch tests to the new async/paper contract; extended `_RecordingFeed`/`_RecordingProvider` fakes
- `tests/integration/test_universe_remove_policy.py` (modified, 4-SPACE, `integration`) — extended keep-until-flat proof (record survives until flat, KeyErrors after discard) + new no-holder immediate-discard test

## Decisions Made

- Followed the plan's WARNING resolutions exactly: WARNING 1 (paper path → synchronous warmup + immediate `mark_ready`, never PENDING), WARNING 2 (explicit `K = cache_capacity() + _WARMUP_MARGIN`, depth_hint DEFERRED — the todo file is present).
- Extended the single `_SupportsSubscribe` provider seam with `spawn_warmup` rather than a separate Protocol (the live provider is one object with all three methods).
- Indentation: 4 spaces throughout (the `universe/` package and its tests are 4-space).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Migrated 2 stale synchronous-add-branch tests in `test_universe_poll.py`**
- **Found during:** Task 1
- **Issue:** `test_on_universe_update_warmup_before_subscribe` and `test_on_universe_update_provider_none_tolerant` asserted the OLD synchronous add-branch (`feed.warmup` THEN `provider.subscribe`), directly invalidated by the async contract change. The old `_RecordingProvider` had no `spawn_warmup` (would AttributeError) and the provider-none test's universe had no PENDING record for the added symbol (would KeyError on `mark_ready`).
- **Fix:** Rewrote both to the new contract — the live add-branch asserts `spawn` per symbol with NO subscribe; the paper test asserts synchronous `warmup` + `is_ready` True. Extended the local `_RecordingFeed` (added `absorb_warmup`/`cache_capacity`) and `_RecordingProvider` (added `spawn_warmup`) fakes. Directly caused by this task's contract change (in-scope).
- **Files modified:** `tests/unit/universe/test_universe_poll.py`
- **Commit:** `38a8cb79`

## Threat Surface

Threat register mitigations from the plan are all satisfied and asserted:
- **T-07-06-ORDER** (Tampering): `on_bars_loaded` runs absorb → mark_ready → subscribe in that exact order (`test_on_bars_loaded_absorb_then_ready_then_subscribe_in_order` via an ordered `_SpyUniverse`); readiness flips only after the ring is warmed, subscribe only after the flip.
- **T-07-06-BATCH** (DoS): per-symbol `try` isolation (`test_one_spawn_failure_does_not_abort_batch_or_remove_branch`) — a raising spawn processes the remaining adds AND the remove branch; `on_bars_load_failed` marks FAILED (dark, retried), never aborts.
- **T-07-06-DROP** (Info Disclosure): `discard_instrument` only at the two final-teardown points (no-holder / detach-on-flat); the held orphan's record survives until flat (`test_orphan_and_track_..._detaches_on_flat` step a2/d).
- **T-07-06-SC** (accept): no package installs in this plan.

No NEW security-relevant surface introduced (no endpoints, auth paths, file/schema access).

## Known Stubs

None — all three seams are real and wired to the record model. The composition-root wiring (poll timer emitting `UniversePollEvent`; `set_freeze_gate` / `set_precision_resolver` / `set_selection_source(StrategyDerivedSelectionModel)`; the `on_bars_loaded`/`on_bars_load_failed` route registration + `set_global_queue` on the provider) is the declared Plan 07 scope. The max-across-concerned-strategies warmup `depth_hint` seam is DEFERRED (`.planning/todos/pending/warmup-depth-max-concerned-strategy.md`, RESEARCH OQ4).

## Issues Encountered

None.

## User Setup Required

None — all tests are socket-free/offline.

## Verification

- `poetry run pytest tests/unit/universe tests/integration/test_universe_remove_policy.py -q` → **76 passed**.
- `poetry run mypy itrader/universe/universe_handler.py itrader/universe/membership.py` → clean (`--strict`).
- Acceptance greps: `def on_bars_loaded` (1), `def on_bars_load_failed` (1), `discard_instrument` (2), `class StrategyDerivedSelectionModel` (1).
- Milestone gate: `tests/integration/test_backtest_oracle.py` + `tests/integration/test_okx_inertness.py` → **4 passed** (oracle byte-exact 134 / `46189.87730727451`; universe_handler/membership live-only, never on the backtest path; determinism double-run identical).

## Self-Check: PASSED

- FOUND: itrader/universe/universe_handler.py::on_bars_loaded
- FOUND: itrader/universe/membership.py::StrategyDerivedSelectionModel
- FOUND: tests/unit/universe/test_universe_warmup_consumers.py
- FOUND commit: d39d0594
- FOUND commit: 38a8cb79
- FOUND commit: 4bf3c9f5

---
*Phase: 07-live-dynamic-universe-hardening*
*Completed: 2026-07-06*

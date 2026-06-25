---
phase: 05-incremental-indicators-fragile-oracle-gated-last
plan: 01
subsystem: infra
tags: [bar-feed, shared-cache, derive-once, look-ahead-safety, plumbing, price-handler]

# Dependency graph
requires:
  - phase: 06-bar-feed-window-copies
    provides: "BacktestBarFeed D-08/D-10 monotonic int64 window cursor + the 7-rule bar-timing contract (preserved byte-for-byte this plan)"
provides:
  - "BarFeed.newest_bar(ticker) — the shared recent-bars newest-bar provision (P5-D16)"
  - "BarFeed.register_raw_bar_consumer / cache_capacity — the consumer-registration / capacity-derivation interface (P5-D16)"
  - "cache_registration.derive — pure derive-once cache-capacity function over raw-bar consumers (derive_instruments mirror)"
  - "assert_update_trigger — interface-only G1 base_timeframe<=min(timeframe) causality guard (P5-D16b)"
  - "G5 single-walk newest-bar unify: newest_bar(ticker) IS BarEvent.bars[ticker] (P5-D16a, one source of truth)"
affects: [05-02, 05-03, stateful-indicators, deep-shared-bar-history, multi-timeframe-consolidator, screener]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Pure derive-once-at-wiring capacity function mirroring universe/instruments.py::derive_instruments (no class/state/queue/feed/store import, sorted/deduped/laddered output)"
    - "G5 single-walk unify: one per-symbol-per-tick walk feeds BOTH the BarEvent payload AND the shared-cache newest row"
    - "Interface-only seam (G1) with a causality assertion + a deferred deep implementation behind the same surface"

key-files:
  created:
    - itrader/price_handler/feed/cache_registration.py
    - tests/integration/test_bar_cache_registration.py
  modified:
    - itrader/price_handler/feed/base.py
    - itrader/price_handler/feed/bar_feed.py
    - .gitignore

key-decisions:
  - "Cache capacity keys off RAW-BAR consumers (not indicator min_period) because indicators self-buffer under Model B (P5-D07); empty consumer set -> newest-bar-only depth 1, deep cache deferred (P5-D16/P5-D22)"
  - "The G5 cache write rides the EXISTING current_bars per-symbol walk — no second loop added (for-ticker count stays 2)"
  - "G1 trigger seam is module-level + interface-only (base_timeframe<=min(timeframe)); golden 1d==base collapses to 'every tick'; multi-timeframe consolidator deferred"
  - "Narrow .gitignore negations un-ignore cache_registration.py + test_bar_cache_registration.py (broad **cache** rule caught them by filename)"

patterns-established:
  - "Shared recent-bars feed seam: newest-bar provision + registration interface on the BarFeed ABC, deep buffer behind the same surface"
  - "RawBarConsumer Protocol mirrors membership.SupportsTickers — the screener/raw-history extension point"

requirements-completed: [PERF-05]

# Metrics
duration: ~10min
completed: 2026-06-24
---

# Phase 5 Plan 01: Shared Recent-Bars Feed Data Layer (Plan A) Summary

**BarFeed now owns the shared recent-bars API — a G5 single-walk newest-bar provision plus a pure derive-once consumer-registration/capacity interface and an interface-only G1 causality guard — added as byte-exact plumbing (SMA_MACD oracle held 134 / 46189.87730727451, window cursor byte-for-byte unchanged).**

## Performance

- **Duration:** ~10 min
- **Started:** 2026-06-24
- **Completed:** 2026-06-24
- **Tasks:** 3
- **Files modified:** 5 (2 created, 3 modified)

## Accomplishments

- Pure `cache_registration.derive` — derive-once cache-capacity function over registered raw-bar consumers, mirroring `universe/instruments.py::derive_instruments` (no class/state/queue/feed/store import, sorted/deduped/laddered output). Empty consumer set yields the newest-bar-only floor (depth 1); the deep multi-bar cache is deferred (P5-D16/P5-D22).
- `BarFeed` ABC extended with the shared recent-bars + registration interface: `register_raw_bar_consumer` / `cache_capacity` (delegating to `derive`), an abstract `newest_bar` accessor, and the module-level `assert_update_trigger` G1 causality guard.
- G5 unify (P5-D16a): the SINGLE existing `current_bars` per-symbol walk now ALSO writes `_newest_bars[ticker]` — one walk, not two — so `newest_bar(ticker)` is provably `BarEvent.bars[ticker]` for every present symbol (one source of truth). The for-ticker loop count stays at 2 (no second walk).
- A3 byte-exact preservation: the `window(...)` D-08/D-10 monotonic int64 cursor + the 7-rule bar-timing contract docstring + `_offset_alias`/`_readonly_master`/searchsorted-rebuild paths are byte-for-byte unchanged (`git diff` shows no window-body edits). SMA_MACD oracle byte-exact `134 / 46189.87730727451`.
- Integration coverage (6 tests): capacity deferral + ladder, the G5 newest-bar unify (one source of truth + latest-tick tracking), and the G1 `base_timeframe <= min(timeframe)` guard.

## Task Commits

Each task was committed atomically:

1. **Task 1: Pure capacity-derivation function** - `5be5047` (feat) — includes the `.gitignore` Rule-3 fix
2. **Task 2: G5 newest-bar unify + G1 seam on BarFeed** - `86ff5b2` (feat)
3. **Task 3: Integration coverage** - `484724f` (test) — includes the `.gitignore` test negation

## Files Created/Modified

- `itrader/price_handler/feed/cache_registration.py` (created) — pure derive-once cache-capacity function + `RawBarConsumer` Protocol + `NEWEST_BAR_ONLY` floor + `derive_required_depths`.
- `itrader/price_handler/feed/base.py` (modified) — `BarFeed` ABC gains `register_raw_bar_consumer`/`cache_capacity`/abstract `newest_bar`/lazy `_raw_bar_consumers`; module-level `assert_update_trigger` (G1).
- `itrader/price_handler/feed/bar_feed.py` (modified) — `_newest_bars` cache field; G5 cache write on the existing `current_bars` walk; `newest_bar` + `assert_update_trigger` wiring (delegates with `self._base_timeframe`). Window cursor untouched.
- `tests/integration/test_bar_cache_registration.py` (created) — 6 Plan-A plumbing tests.
- `.gitignore` (modified) — two narrow negations so the broad `**cache**` rule does not ignore the two tracked `*cache*`-named source/test files.

## Decisions Made

- **Capacity keys off raw-bar consumers, not indicator min_period** (P5-D16/P5-D22): indicators self-buffer under Model B (P5-D07), so the shared cache is driven only by genuine raw-history consumers. With none registered, capacity is the newest-bar floor (depth 1) and the deep buffer is deferred to the first raw-bar consumer.
- **The newest-bar cache write rides the existing walk** (P5-D16a): no second `for ticker in self._symbols` loop — the cache row and the `BarEvent` payload come from the same `bar` for the same tick.
- **G1 is interface-only + module-level** (P5-D16b): `assert_update_trigger` lives in `base.py` as a pure helper (testable, feed-agnostic); `BacktestBarFeed.assert_update_trigger` delegates with its own `base_timeframe`. The full multi-timeframe consolidator is deferred.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Narrow `.gitignore` negations for the two `*cache*`-named tracked files**
- **Found during:** Task 1 (committing `cache_registration.py`) and Task 3 (committing `test_bar_cache_registration.py`)
- **Issue:** The repo `.gitignore` line 32 `**cache**` (intended for `__pycache__`/cache dirs) matched both new source/test filenames by substring, so `git add` refused them ("paths are ignored"). The plan mandates these exact filenames (acceptance criteria reference them), so renaming was not an option.
- **Fix:** Added two narrow negation rules (`!itrader/price_handler/feed/cache_registration.py`, `!tests/integration/test_bar_cache_registration.py`) directly under the `**cache**` rule. Verified via `git check-ignore` that both files are now un-ignored.
- **Files modified:** `.gitignore`
- **Verification:** `git check-ignore -v <file>` resolves to the negation rule; both files staged + committed in their respective task commits.
- **Committed in:** `5be5047` (Task 1) and `484724f` (Task 3)

---

**Total deviations:** 1 auto-fixed (1 blocking — `.gitignore`, split across the two commits that hit it)
**Impact on plan:** The fix was necessary to commit the plan's mandated artifacts. Narrow, scoped negations — no behavior change, no scope creep. The `**cache**` rule still ignores everything else.

## Issues Encountered

None beyond the `.gitignore` deviation above. All verification gates passed first try: mypy `--strict` clean (188 files), SMA_MACD oracle byte-exact, window cursor byte-for-byte unchanged, 61 price+integration tests green.

## Known Stubs

The deferred deep multi-bar cache is INTENTIONAL and tracked (P5-D16/P5-D22): `cache_registration.derive` returns the newest-bar-only depth (1) for the empty consumer set; the deep capacity-derived buffer lands with the first raw-bar consumer (screener / raw-history strategy), tracked at `.planning/todos/deep-shared-bar-history.md`. The G1 multi-timeframe consolidator is likewise interface-only this plan, tracked at `.planning/todos/multi-timeframe-consolidator.md`. Neither blocks Plan A's goal (newest-bar provision + registration interface), which is fully wired and tested.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- The shared recent-bars feed data layer (Plan A) is complete and byte-exact: Plan B (stateful indicators + oracle re-baseline) and Plan C (pair migration + per-tick window removal) build on this seam.
- Plan B's stateful indicators (Model B, P5-D07) self-buffer and do NOT read this cache — Plan A deliberately ships only the newest-bar provision + registration interface, so Plan B is unblocked structurally (it remains gated only on the G2 seeding decision P5-D04, per 05-CONTEXT).
- The byte-exact lock (window cursor + 7-rule contract + oracle) is preserved, so any future re-baseline in Plan B is attributable to the indicator VALUES, not this plumbing.

## Self-Check: PASSED

- All created files exist (`cache_registration.py`, `test_bar_cache_registration.py`, this SUMMARY).
- All task commits exist (`5be5047`, `86ff5b2`, `484724f`).
- mypy `--strict` clean (188 files); SMA_MACD oracle byte-exact (134 / 46189.87730727451); window cursor byte-for-byte unchanged; for-ticker loop count stays 2; feed files 0 tabs.

---
*Phase: 05-incremental-indicators-fragile-oracle-gated-last*
*Completed: 2026-06-24*

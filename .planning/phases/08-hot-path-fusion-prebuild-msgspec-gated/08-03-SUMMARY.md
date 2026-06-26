---
phase: 08-hot-path-fusion-prebuild-msgspec-gated
plan: 03
subsystem: infra
tags: [perf, pandas, itertuples, serialization, cache, decimal, byte-exact]

# Dependency graph
requires:
  - phase: 06-hot-path-improvments
    provides: "bar_feed.py prebuild + D-10 cursor; _offset_alias body-byte-unchanged memo discipline"
  - phase: 04
    provides: "_declared_hints @cache per-class memo that the per-instance to_dict cache layers on"
provides:
  - "itertuples/vectorized {ts: Bar} prebuild in bar_feed.py (drops ~69k throwaway pandas Series; D-14 string path byte-exact)"
  - "Per-instance static to_dict cache + _invalidate_to_dict_cache seam in strategy_handler/base.py (byte-identical output)"
  - "Field-for-field Bar prebuild equivalence test + str-parity pin"
  - "Snapshot-drift test: byte-identical to_dict, per-instance isolation, invalidation seam"
affects: [08-04 (gate-b A/B re-freeze + keep-only-measured revert decisions)]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "pandas itertuples(index=True) batch construct (first itertuples usage in the repo) — body byte-unchanged, str() parity verified"
    - "Per-INSTANCE lazily-built static serialization cache + in-place runtime-field refresh (byte-identical key order)"
    - "Forward-looking _invalidate_to_dict_cache seam wired into the only declared-param mutator (reconfigure)"

key-files:
  created:
    - tests/unit/price/test_bar_prebuild_equivalence.py
    - tests/unit/strategy/test_to_dict_snapshot.py
  modified:
    - itrader/price_handler/feed/bar_feed.py
    - itrader/strategy_handler/base.py

key-decisions:
  - "itertuples chosen over column-array zip: str() parity holds for float64 OHLCV columns (str(native scalar) == str(series value)) — verified empirically on the golden frame (0 diffs / 3076 rows) and pinned by test_str_parity, so the D-14 Decimal(str(...)) path receives byte-identical strings; no Series-shaped fallback needed."
  - "to_dict cache is PER-INSTANCE (stash on self), never per-class: a per-class cache would leak one instance's declared windows into another (D-06 correctness bug)."
  - "Rule 2 add: reconfigure() calls _invalidate_to_dict_cache(). reconfigure is the only declared-param mutator (re-runs _apply_params); the plan assumed 'no such setter exists', but reconfigure does — wiring the seam keeps the cache correct if reconfigure is ever called. Backtest never calls reconfigure, so zero backtest cost / byte-exact preserved."

patterns-established:
  - "itertuples batch Bar construction with str()-parity equivalence test (the dedicated drift lock; no hot-path runtime guard)"
  - "Per-instance static serialization cache + in-place two-field runtime refresh for byte-identical key ordering"

requirements-completed: [PERF-08]

# Metrics
duration: ~25min
completed: 2026-06-25
---

# Phase 8 Plan 03: itertuples Bar Prebuild + Per-Instance to_dict Cache Summary

**Two independent deterministic, byte-exact construction-cost wins: bar_feed.py drops `frame.iterrows()` (~69k throwaway pandas Series) for an `itertuples` Bar prebuild, and `Strategy.to_dict` caches its serialized static snapshot per instance — refreshing only `is_active` + `subscribed_portfolios` in place — both verified field-for-field equivalent with the SMA_MACD oracle held byte-exact (134 / 46189.87730727451).**

## Performance

- **Duration:** ~25 min
- **Started:** 2026-06-25T14:11Z
- **Completed:** 2026-06-25T14:35Z
- **Tasks:** 3 (2 code + TDD tests, 1 gate-verification)
- **Files modified:** 4 (2 source, 2 new tests)

## Accomplishments
- **Req 3:** Replaced the `{ts: Bar.from_row(ts, row) for ts, row in frame.iterrows()}` prebuild with an `itertuples(index=True)` build constructing `Bar` directly via `Decimal(str(...))`. iterrows materializes one throwaway pandas Series per row (~69k across the golden run); itertuples yields a lightweight NamedTuple with no Series allocation. The D-14 string path is byte-exact — `str()` parity verified for float64 OHLCV columns.
- **Req 4 (D-06):** `Strategy.to_dict` now builds the static snapshot once per instance (`_build_to_dict_snapshot`, lazy first-call), stashes it on `self._to_dict_static_cache`, and per call returns a copy with only `subscribed_portfolios` + `is_active` overwritten in place — key ordering unchanged, output byte-identical. Shipped the `_invalidate_to_dict_cache()` seam, wired into `reconfigure` (the only declared-param mutator).
- **Gate (a) byte-exact:** oracle 134 / 46189.87730727451; `mypy --strict itrader` clean (166 files); full unit + integration suite 1232 passed; determinism double-run identical.

## Task Commits

Each task was committed atomically:

1. **Task 1: itertuples Bar prebuild (Req 3) + field-for-field equivalence test** - `1419a8e` (perf)
2. **Task 2: per-instance to_dict static cache + invalidation seam (Req 4 / D-06)** - `d81f9a5` (perf)
3. **Task 3: Gate (a) byte-exact for Reqs 3 + 4** - verification-only, no code change (gate run against `1419a8e` + `d81f9a5`)

_Note: TDD tasks combined RED+GREEN into one commit each since the equivalence/drift tests pass against both the pre- and post-change code (they are byte-exact drift locks); the str-parity / seam assertions are the genuinely behavior-pinning RED checks (the seam test was RED before Task 2's implementation)._

## Files Created/Modified
- `itrader/price_handler/feed/bar_feed.py` - itertuples prebuild replacing iterrows; added `from decimal import Decimal`; updated a stale "frame.iterrows() below" comment.
- `itrader/strategy_handler/base.py` - `_to_dict_static_cache` field in `__init__`; `to_dict` split into a cached-return path + `_build_to_dict_snapshot`; `_invalidate_to_dict_cache` seam; `reconfigure` calls it.
- `tests/unit/price/test_bar_prebuild_equivalence.py` - field-for-field byte-identity vs the iterrows build, explicit str_parity pin, D-14 decimal_string_path assertion.
- `tests/unit/strategy/test_to_dict_snapshot.py` - byte-identical snapshot, key-order preservation, runtime-field refresh, per-instance isolation, invalidation seam, reconfigure invalidation.

## Decisions Made
- **itertuples vs column-array zip:** chose `itertuples` — str() parity holds for the float64 OHLCV dtypes (empirically 0 diffs / 3076 rows; pinned by `test_str_parity`), so no Series-shaped fallback was needed and the D-14 contract is preserved without re-routing through a mapping.
- **Per-instance cache:** stashed on `self`, never per-class, to avoid the cross-instance declared-window leak (D-06).
- **Runtime-mutable set audit:** grep-confirmed the exhaustive runtime-mutable set serialized by `to_dict` is exactly `{is_active, subscribed_portfolios}`. `is_active` is set in `__init__`/`activate_strategy`/`deactivate_strategy`; `subscribed_portfolios` is mutated via `.append`/`.remove` in `subscribe_portfolio`/`unsubscribe_portfolio`. Every other serialized field (short/long_window, sizing_policy, direction, allow_increase, max_positions, sltp_policy, timeframe_alias, strategy_id, strategy_name) is set only via `_apply_params` (`setattr(self, nm, val)` at base.py:273) or `__init__`, reachable at runtime only through `reconfigure` — which invalidates the cache.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing Critical] Wired `_invalidate_to_dict_cache()` into `reconfigure()`**
- **Found during:** Task 2 (to_dict cache)
- **Issue:** The plan/PATTERNS asserted "no setter that mutates a declared param exists in Phase 8, so the seam is never called." But `Strategy.reconfigure()` calls `_apply_params`, which re-commits every declared param via `setattr`. Without invalidation, a reconfigured strategy would serve a stale static snapshot from `to_dict` (a correctness bug for any live/runtime reconfigure caller).
- **Fix:** `reconfigure()` calls `self._invalidate_to_dict_cache()` after `_run_init()`. This is the documented "any setter that mutates a declared param MUST call this." Backtest never calls reconfigure on the run path, so backtest cost is unchanged and the oracle stays byte-exact.
- **Files modified:** itrader/strategy_handler/base.py
- **Verification:** `test_reconfigure_invalidates_cache` asserts `to_dict()["short_window"]` reflects the new value after `reconfigure(short_window=30)`; oracle byte-exact; mypy clean.
- **Committed in:** d81f9a5 (Task 2 commit)

---

**Total deviations:** 1 auto-fixed (1 missing-critical correctness add)
**Impact on plan:** The seam is now correctly invalidated by the only declared-param mutator instead of being a dead forward-looking hook. No scope creep; zero backtest-path cost; byte-exact preserved.

## Issues Encountered
- **Worktree venv shadow:** Poetry created a fresh empty `.venv` in the worktree (no deps). Per the documented worktree-venv-shadowing hazard, ran all tests/mypy via the main checkout's interpreter with `PYTHONPATH="$PWD"` prepended (`<main>/.venv/bin/python`) so the worktree edits are exercised, not the main checkout's editable install. Did NOT run `make` (worktree `.env` abort + `ITRADER_DISABLE_LOGS` caplog hazard).

## Known Stubs
None.

## Threat Flags
None — internal construction-cost + serialization refactor; no new network/auth/file/schema surface. Threat register T-08-05 (itertuples str() parity) and T-08-06 (to_dict static-cache staleness / per-class leak) are both mitigated by the dedicated equivalence/drift tests + oracle gate, as planned.

## Self-Check: PASSED
- `itrader/price_handler/feed/bar_feed.py` — FOUND
- `itrader/strategy_handler/base.py` — FOUND
- `tests/unit/price/test_bar_prebuild_equivalence.py` — FOUND
- `tests/unit/strategy/test_to_dict_snapshot.py` — FOUND
- Commit `1419a8e` — FOUND
- Commit `d81f9a5` — FOUND

## Next Phase Readiness
- Gate (a) byte-exact green for Reqs 3 + 4. Plan 08-04 owns the per-req A/B attribution + keep-only-measured revert decisions and the gate-(b) re-freeze on a verified-cool machine (do NOT trust the frozen-baseline compare on a throttled box — memory `v15-perf-gateb-thermal-drift`).
- No blockers.

---
*Phase: 08-hot-path-fusion-prebuild-msgspec-gated*
*Completed: 2026-06-25*

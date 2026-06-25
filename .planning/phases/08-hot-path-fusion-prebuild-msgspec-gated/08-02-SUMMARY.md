---
phase: 08-hot-path-fusion-prebuild-msgspec-gated
plan: 02
subsystem: portfolio / outils
tags: [perf, cache, byte-exact, PERF-08, D-05, Phase7-D-01]
requires:
  - "Position mutable class (D-01 excluded from msgspec)"
  - "_aligned @functools.lru_cache(maxsize=32) (Phase 7 D-01)"
provides:
  - "Position._net_quantity_cache / _avg_price_cache — explicit fill-invalidated Decimal caches (D-05)"
  - "tests/unit/portfolio/positions/test_position_cache.py — fill-invalidation lock"
  - "tests/unit/outils/test_time_parser_alignment.py — _aligned boolean-equivalence lock"
affects:
  - "itrader/portfolio_handler/position/position.py"
tech-stack:
  added: []
  patterns:
    - "Explicit lazily-initialised mutable cache field (NOT cached_property) — _last_accrual_time idiom (CARRY-01)"
    - "Audit-the-invariant + dedicated equivalence test, NO hot-path runtime guard"
key-files:
  created:
    - "tests/unit/portfolio/positions/test_position_cache.py"
    - "tests/unit/outils/test_time_parser_alignment.py"
  modified:
    - "itrader/portfolio_handler/position/position.py"
    - ".gitignore"
decisions:
  - "Req 2/D-05: explicit Optional[Decimal] cache fields invalidated at the single fill mutator (update_position), not functools.cached_property."
  - "Req 5: no new cache added — _aligned already memoized (Phase 7 D-01); residual is cache-miss first-touch, int64-ns lever deferred to 08-04 A/B (keep-only-measured)."
metrics:
  duration: "~25 min"
  completed: "2026-06-25"
  tasks: 3
  files-created: 2
  files-modified: 2
---

# Phase 8 Plan 02: Position Cache + Alignment Audit Summary

Cached `Position.net_quantity` / `avg_price` in explicit fill-invalidated Decimal fields (Req 2 / D-05)
and locked the already-memoized `_aligned` alignment seam with a boolean-equivalence test (Req 5,
audit-first) — both behavior-preserving, SMA_MACD oracle byte-exact (134 / 46189.87730727451).

## What Was Built

### Task 1 — Explicit fill-invalidated cache on Position (Req 2 / D-05)
- Added `self._net_quantity_cache: Optional[Decimal] = None` and `self._avg_price_cache: Optional[Decimal] = None`
  in `__init__` (alongside the `_last_accrual_time` precedent, CARRY-01).
- Converted the `net_quantity` and `avg_price` `@property`s to compute-and-stash-if-`None`-else-return-cache.
  The Decimal arithmetic bodies are **byte-unchanged**.
- Reset BOTH caches to `None` in `update_position` — the single input mutator (grep-audited: see below).
- `market_value` / `aggregate_notional` keep calling `net_quantity` / `avg_price` (picking up the cache)
  while still multiplying by the **live** per-bar `current_price`, so price-only updates stay live.
- TDD: RED commit (7 failing tests, no cache fields) → GREEN commit (implementation).

**Grep audit (acceptance criterion):** the only sites that mutate the six fill-derived inputs
(`buy_quantity` / `sell_quantity` / `buy_commission` / `sell_commission` / `avg_bought` / `avg_sold`)
are `__init__` construction (lines 61-66) and `update_position` (lines 256-262). A repo-wide grep for
those attribute assignments outside `position.py` returned **zero** hits. Both caches are reset in
`update_position` (lines 288-289). No other mutator exists → no other reset site needed.

### Task 2 — Audit + boolean-equivalence test for `_aligned` (Req 5, keep-only-measured)
- **Stale-reference correction:** CONTEXT/SPEC cite a `check_aligned` function that does NOT exist
  (`grep -rn check_aligned itrader/` → 0 hits). The alignment math is `_aligned(ts, tf)` + its delegator
  `check_timeframe`, and `_aligned` ALREADY carries `@functools.lru_cache(maxsize=32)` (Phase 7 D-01).
- **Re-profile finding** (from `perf/results/scalene-w1.json` post-phase-7 vs `scalene-w1-pre07.json`):
  - Pre-phase-7: the `astimezone/replace/total_seconds` math totaled **~8.66%** CPU (file lines 154-157).
  - Post-phase-7 (current, with `lru_cache`): the same math totals **~3.12%** CPU (file lines 167-170).
  - Phase 7 D-01 cut ~5.5pp. The **residual ~3.1% is cache-miss first-touch**: each per-bar `ts` is a
    distinct, unbounded key, so `lru_cache(maxsize=32)` only captures the intra-tick repeats across the
    registered strategies (same `event.time`, different strategy) — the per-bar first-touch math still runs.
- **Keep-only-measured verdict:** Req 5 = equivalence test + A/B-confirmed-sufficient. **No production
  code beyond the test** (oracle untouched). SPEC's "precomputed/cached int64-ns grid" (mirroring the
  bar_feed D-10 cursor) is the candidate next lever for the residual first-touch cost — recommended for
  the plan **08-04** A/B, **not pre-added here** (it would add an unbounded-key cache that may land in noise).
- Added `tests/unit/outils/test_time_parser_alignment.py` — 29 cases (daily 00:00 UTC golden tick,
  intra-day on/off-grid, non-day-divisor 7h, weekly, two DST-boundary America/New_York timestamps),
  each asserted against a **fresh independent reference computation** of the same midnight-relative UTC
  math AND a hand-pinned expected boolean.

### Task 3 — Gate (a) byte-exact for Reqs 2 + 5
Verification-only (no code change). All gates green against the Task 1+2 commits.

## Verification

| Gate | Result |
|------|--------|
| `tests/unit/portfolio/positions/test_position_cache.py` | 7 passed (fill-invalidation on buy AND sell) |
| `tests/unit/portfolio/positions/` (regression) | 13 passed |
| `tests/unit/outils/test_time_parser_alignment.py` | 29 passed (boolean equivalence) |
| `tests/integration/test_backtest_oracle.py` | 3 passed — **134 / 46189.87730727451** + determinism double-run |
| `mypy --strict itrader` | Success: no issues found in 166 source files |
| Full suite `pytest tests` | **1331 passed**, 0 failed |

> In-worktree runs used `PYTHONPATH="$PWD" <main-checkout>/.venv/bin/pytest` to defeat the editable-install
> shadow (the worktree's own `.venv` had no deps). The orchestrator runs the authoritative `make test` +
> oracle gate in the main checkout after merge-back.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] `.gitignore` `**cache**` glob blocked the mandated test path**
- **Found during:** Task 1, when committing the RED test.
- **Issue:** `.gitignore:32` has a broad `**cache**` rule; the plan's mandated artifact filename
  `tests/unit/portfolio/positions/test_position_cache.py` matched it, so `git add` refused the file.
  The artifact name is pinned in the plan's `must_haves.artifacts`, so renaming was not an option.
- **Fix:** Added a `!` negation for the exact path, following the established in-file precedent
  (`!itrader/price_handler/feed/cache_registration.py`, `!tests/integration/test_bar_cache_registration.py`).
- **Files modified:** `.gitignore`
- **Commit:** cf0f56d

## Indentation

`position.py` and `time_parser.py` are both **TABS** (verified `grep -cP '^\t'` non-zero; matched, never
normalized). The new test files use **4 spaces** (matching the `tests/unit/outils/` convention and the
test-file style). `mypy --strict` clean confirms no mixed-indentation breakage.

## Known Stubs

None.

## Threat Flags

None — internal cache + a pure utility memo audit; no new network/auth/persistence/file surface.
T-08-03 (cache staleness) mitigated by reset-at-mutator + the fill-invalidation test + oracle byte-exact.
T-08-04 (unbounded cache) accepted: no new cache added; existing `lru_cache(maxsize=32)` is bounded.

## Notes for 08-04 (Gate b / A/B)

- Req 2: Position-cache same-machine A/B + keep-only-measured revert decision is taken in 08-04.
- Req 5: re-profile shows residual ~3.1% on `_aligned` cache-miss first-touch. The int64-ns precomputed
  grid (SPEC, mirroring bar_feed D-10) is the candidate lever — A/B it in 08-04; revert if it lands in noise.

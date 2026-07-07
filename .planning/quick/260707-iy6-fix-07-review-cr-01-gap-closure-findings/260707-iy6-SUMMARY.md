---
phase: quick-260707-iy6
plan: 01
subsystem: price-handler-feed / universe-handler
tags: [live-only, CR-01-gap-closure, WR-01, WR-02, IN-01, IN-02, observability, forward-only]
requires:
  - "07-10 CR-01 gap-closure (absorb_warmup _last_delivered cursor guard)"
provides:
  - "absorb_warmup WR-01 revision observability (differing-OHLCV same-ts -> WARN, no mutation)"
  - "absorb_warmup WR-02 off-grid rejection (last < bt < last + tf -> WARN + drop, cursor not advanced)"
  - "IN-01 / IN-02 docstring accuracy"
affects:
  - "live warmup-absorption path only (backtest hot path untouched, oracle byte-exact)"
tech-stack:
  added: []
  patterns:
    - "mirror the sibling _duplicate_or_revision revision-observability on the absorb path"
    - "mirror update()'s WR-01 off-grid rejection on the absorb path"
key-files:
  created: []
  modified:
    - "itrader/price_handler/feed/live_bar_feed.py"
    - "itrader/universe/universe_handler.py"
    - "tests/unit/price/test_absorb_warmup_idempotency_cr01.py"
decisions:
  - "WR-01: byte-identical same-ts warmup bar drops SILENTLY; differing-OHLCV same-ts bar is a forward-only revision (D-07) — WARN + drop, no state mutation (reuses _same_ohlcv)"
  - "WR-02: off-grid warmup bar (last < bt < last + tf) rejected with WARN BEFORE ring.append/cursor-advance so it cannot poison the shared _last_delivered cursor (mirrors update() WR-01)"
metrics:
  duration: ~8min
  completed: 2026-07-07
---

# Phase quick-260707-iy6 Plan 01: Fix 07-REVIEW CR-01 Gap-Closure Findings Summary

Closed the four 07-REVIEW.md findings on the CR-01 gap-closure (plan 07-10): `absorb_warmup`
now observes a genuine venue-side revision (WR-01) and rejects an off-grid warmup bar (WR-02),
and its docstring plus `_record_rewarm_failure`'s docstring now match the actual behavior
(IN-01/IN-02). All four changes are live-only and inert on the byte-exact backtest oracle.

## What Was Built

### Task 1 (TDD) — WR-01 revision observability + WR-02 off-grid rejection

`LiveBarFeed.absorb_warmup`'s `bt == last` leg previously dropped every same-timestamp bar
silently. It now mirrors the sibling `_duplicate_or_revision`: a byte-identical re-delivery
stays silent, but a differing-OHLCV bar at the same open-time is a forward-only **revision**
(D-07) — a `"Revision dropped ..."` WARNING surfaces the conflict while the already-ringed bar
stays canonical (no state mutation, no rewind), reusing the existing `_same_ohlcv` static helper.

A new off-grid rejection was added after the `==` leg, mirroring `update()`'s WR-01 branch:
a bar strictly between `last` and `last + tf` is dropped with an `"Off-grid warmup bar ..."`
WARNING **before** `ring.append` / cursor-advance, so an off-grid warmup bar can never poison the
shared `_last_delivered` cursor and make every subsequent live `update()` spuriously trip the gap
branch. Bars at `bt >= last + tf` fall through to the existing append path unchanged.

TDD cycle: RED commit (`0d090857`) added the two failing tests + tightened the duplicate test to
be byte-identical; GREEN commit (`8eb66f73`) implemented both guards.

### Task 2 — IN-01 + IN-02 docstring rewords (docstring-only)

- **IN-01:** `absorb_warmup`'s docstring now states it diverges from `_deliver` in TWO ways —
  (1) it never emits (skips terminal `_emit`) and (2) it applies its own `<=` monotonic cursor
  guard (the CR-01-feed WR-01/WR-02 guard) before appending — noting `_deliver` has no monotonic
  guard (that classification lives one layer up in `update()`, never reached by `absorb_warmup`).
- **IN-02:** `_record_rewarm_failure`'s docstring now reflects the `if streak >= 3` semantics —
  the warning fires at the 3rd AND every subsequent consecutive failure, bounded to at most once
  per bar interval by the `on_poll` cadence gate (ongoing visibility, no flood).

## Deviations from Plan

None — plan executed exactly as written.

## Tests

New/updated in `tests/unit/price/test_absorb_warmup_idempotency_cr01.py` (4-space, offline, `unit`):
- `test_same_timestamp_duplicate_drops_silently` — tightened: duplicate now built with
  `close="42102"` (byte-identical to the ringed bar) so the silent-drop assertion is meaningful.
- `test_same_timestamp_revision_warns` (new) — same ts, `close="99999"` → ring + cursor unchanged,
  `"Revision dropped"` WARNING captured.
- `test_off_grid_warmup_bar_dropped_and_warns` (new) — bar at `L + tf/2` → ring unchanged, cursor
  still at `bars[2].time`, `"Off-grid warmup bar"` WARNING captured.

## Verification (full gate set — all green)

1. Backtest oracle byte-exact: `tests/integration/test_backtest_oracle.py` — 3 passed
   (134 trades / 46189.87730727451, `check_exact`).
2. mypy clean: `itrader/price_handler/feed/live_bar_feed.py itrader/universe/universe_handler.py`
   — Success, no issues.
3. Targeted units: `test_absorb_warmup_idempotency_cr01.py` + `test_absorb_warmup.py` — 11 passed.
4. No tabs introduced — all three files remain 4-space.

## Commits

- `0d090857` test(quick-260707-iy6): add failing tests for revision-warn + off-grid rejection (RED)
- `8eb66f73` feat(quick-260707-iy6): absorb_warmup WR-01 revision-observability + WR-02 off-grid (GREEN)
- `222219a4` docs(quick-260707-iy6): IN-01 + IN-02 docstring rewords

## Self-Check: PASSED

- Modified files exist: live_bar_feed.py, universe_handler.py, test_absorb_warmup_idempotency_cr01.py — FOUND.
- Commits exist: 0d090857, 8eb66f73, 222219a4 — FOUND.

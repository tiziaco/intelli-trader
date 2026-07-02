---
phase: quick-260702-m8d
plan: 01
subsystem: live-trading / paper-path
tags: [code-review-fixup, cleanup, parity, phase-04]
requires: [".planning/phases/04-paper-path-milestone-dod/04-REVIEW.md"]
provides:
  - "live_trading_system.py: cleaned imports, enum-based _update_stats, stale-stamp-safe run_paper_replay, wiring-time window guard"
  - "run_live_paper.py: dead DATASET literal removed, unconditional connector teardown on failed start"
  - "REQUIREMENTS.md: PAPER-01/02/04 + RUN-01 re-synced to the revised 2026-07-02 ROADMAP"
affects: [itrader/trading_system/live_trading_system.py, scripts/run_live_paper.py, .planning/REQUIREMENTS.md]
key-files:
  created: []
  modified:
    - itrader/trading_system/live_trading_system.py
    - scripts/run_live_paper.py
    - .planning/REQUIREMENTS.md
decisions: []
metrics:
  duration: ~10min
  completed: 2026-07-02
  tasks: 3
  files: 3
---

# Phase quick-260702-m8d: Apply Phase 04 Code-Review Fix-Now Bucket Summary

Applied the curated Phase 04 code-review fix-now bucket (IN-01/02/03/04, WR-03, WR-05,
WR-02 assertion half) plus a REQUIREMENTS.md stale-doc sync — low-risk cleanups, two
latent-gap closures (WR-03 stale-stamp, WR-05 connector leak), and a loud-failure window
guard (WR-02) — with the paper-parity gate held byte-exact throughout.

## What Was Built

**Task 1 — `live_trading_system.py` (commit `13d083ef`):**
- IN-01: removed the unused module-scope `import time` (all time via `datetime.now(UTC)`).
- IN-02: trimmed the events import to `EventType, ErrorEvent` (dropped `TimeEvent`/`OrderEvent`,
  referenced only in a comment).
- IN-04: `_update_stats` now compares `event_type == EventType.ORDER.name` and the leftover
  `# TODO: Add more specific event type handling ...` comment is gone. Behavior unchanged
  (`EventType.ORDER.name == 'ORDER'`, same str contract).
- WR-03: `run_paper_replay`'s per-bar loop now skips `record_metrics` when the feed's
  newest-delivered bar is not the bar replayed this iteration
  (`int(newest.time.timestamp() * 1000) != cb["ts"]` → `continue`), so a monotonic-guard drop
  can no longer re-stamp a duplicate/stale equity point. On the contiguous golden dataset no
  bar is ever dropped → every bar still records exactly once → byte-exact preserved.
- WR-02 (assertion half only): added module-level `_PAPER_EXPECTED_START = "2018-01-01"` /
  `_PAPER_EXPECTED_END = "2026-06-03"` constants and a wiring-time assertion in `run_paper_replay`
  (after the `_replay_provider is None` guard) that the replay store's `start_date`/`end_date` and
  `_symbol` match the canonical backtest parity window — raising `ConfigurationError` (already
  imported) on drift. No shared-config refactor, assertion/guard only.

**Task 2 — `run_live_paper.py` (commit `8a4a507e`):**
- IN-03: deleted the never-wired `DATASET` literal (CsvPriceStore class defaults are the single
  source). `CASH`/`TICKER`/`TIMEFRAME` untouched; the used `import time` (`time.sleep`) kept.
- WR-05: restructured `_run_okx_smoke` so `system.stop(timeout=10.0)` runs on the failed-start path
  too — removed the bare `return` on `not started`, wrapped the drive in `try/finally`, and gated the
  `time.sleep(5.0)` on `started`. The connector's `disconnect()` (CR-01, in `stop()`'s finally) now
  always tears down a partially-connected OKX socket.

**Task 3 — `.planning/REQUIREMENTS.md` (commit `148836a6`):**
- PAPER-01: reworded to the reused `SimulatedExchange` as-is (D-04) — no new adapter, no
  MatchingEngine/apply_costs re-composition.
- PAPER-02: apply_costs extraction dropped, satisfied-by-reuse (D-05).
- PAPER-04: parity re-anchored to a fresh backtest (`check_exact=True`), not the frozen `46189…`
  artifact (D-01); transitive lock held by the separate oracle test.
- RUN-01: Postgres `LISTEN/NOTIFY` channel + FastAPI wrapper marked deferred to Phase 5 (D-08).
- PAPER-03, the status table, and ROADMAP.md untouched.

## Verification

Mandatory gate ran clean before both source commits:
`test_paper_parity.py` (paper ≡ fresh backtest, `check_exact=True`), `test_okx_inertness.py`,
`test_backtest_oracle.py` (134 / `46189.87730727451`), `test_live_paper_lifecycle.py`,
`test_replay_provider.py` — **13 passed**. `mypy --strict itrader/trading_system/live_trading_system.py`
clean. `scripts/run_live_paper.py` parses (ast). Task 3 verified by the grep gate (`SYNC_OK`).

## Deviations from Plan

None — plan executed exactly as written.

## Self-Check: PASSED

- itrader/trading_system/live_trading_system.py — modified, committed `13d083ef`
- scripts/run_live_paper.py — modified, committed `8a4a507e`
- .planning/REQUIREMENTS.md — modified, committed `148836a6`
- All three commits present in `git log`.

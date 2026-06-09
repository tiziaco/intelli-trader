---
phase: 03-m2b-config-types-storage-seam-oracle-re-freeze
plan: 01
subsystem: scaffold / dependencies / test-infra
tags: [scaffold, inertness-reference, pydantic, characterization-tests, wave-0]
requires: []
provides:
  - "D-17 inertness baseline (M2a-end byte-exact engine output) at M2A-INERTNESS-REF/"
  - "pydantic ^2.13 + pydantic-settings ^2.14 as lockfile-tracked Poetry deps"
  - "5 Wave-0 characterization test stubs (M2-06..10) collectable under current test/ tree"
affects:
  - "03-05 (config collapse — consumes pydantic + the M2-06 stub)"
  - "03-08 (type-split — moves the 5 stubs into tests/unit/...)"
  - "03-09 (oracle re-freeze — verifies phase-end run == M2A-INERTNESS-REF)"
tech-stack:
  added: [pydantic@2.13.4, pydantic-settings@2.14]
  patterns: [skip-gated-characterization-stubs, importorskip-pending-wave]
key-files:
  created:
    - .planning/phases/03-m2b-config-types-storage-seam-oracle-re-freeze/M2A-INERTNESS-REF/trades.csv
    - .planning/phases/03-m2b-config-types-storage-seam-oracle-re-freeze/M2A-INERTNESS-REF/equity.csv
    - .planning/phases/03-m2b-config-types-storage-seam-oracle-re-freeze/M2A-INERTNESS-REF/summary.json
    - test/test_config/test_config_models.py
    - test/test_core/test_enums.py
    - test/test_portfolio_handler/test_state_storage.py
    - test/test_order_handler/test_order_timestamps.py
    - test/test_outils/test_time_parser.py
  modified:
    - pyproject.toml
    - poetry.lock
decisions:
  - "Inertness reference captured FIRST, before any code change, from unmodified M2a-end HEAD (no itrader/** touched)"
  - "M2-07 stub guards on getattr(FillStatus) because only ExecutionStatus exists today (FillStatus lands later wave)"
  - "M2-10 check_timeframe asserted LIVE (works today); 1W/1M/1H to_timedelta skip-gated (M2-10 wave)"
  - "test_config/ created without __init__.py — unique filename, no collection collision under default importmode"
metrics:
  duration: ~3 min
  completed: 2026-06-05
---

# Phase 3 Plan 01: Wave-0 Scaffold (Inertness Ref + Pydantic + Characterization Stubs) Summary

Captured the D-17 byte-exact inertness baseline from the unmodified M2a-end HEAD, added
pydantic v2 + pydantic-settings as lockfile-tracked deps, and wrote 5 skip-gated Wave-0
characterization stubs (M2-06..10) that collect under the current `test/` tree and keep
the full suite green.

## What Was Built

**Task 1 — D-17 inertness reference (commit `53df71a`):**
Ran `poetry run python scripts/run_backtest.py` at the current (pre-M2b) HEAD with NO
source edits, then copied `output/{trades,equity,summary}` into
`M2A-INERTNESS-REF/`. This is the byte-exact (behavioral AND numeric) baseline the
phase-end run (03-09) must reproduce before the oracle re-freeze. Captured numbers:
`final_cash`/`final_equity` = 53229.685, `total_realised_pnl` = 43229.685, `trade_count` = 134
(134 trades, 3076 equity points). These match the M2a Decimal-end numbers (the documented
~1.5e-6 drift from the golden 53229.75 recorded in DEF-02-08-A) — NOT a new M2b number.
`git status` confirmed NO `itrader/**` file was modified in this task's commit.

**Task 2 — pydantic + pydantic-settings (commit `6832455`):**
`poetry add pydantic@^2.13 pydantic-settings@^2.14` → `pydantic = "^2.13"` and
`pydantic-settings = "^2.14"` in pyproject.toml, both `name = "..."` entries in poetry.lock.
`poetry run python -c "import pydantic; from pydantic_settings import BaseSettings, SettingsConfigDict"`
exits 0 and reports 2.13.4. Lockfile-tracked so it survives `make init-env`.

**Task 3 — 5 Wave-0 characterization stubs (commit `c1eb3dd`):**
Five pytest-native, 4-space-indented files under the CURRENT `test/` tree (testpaths=["test"]),
one per requirement, all collecting at Wave 0 with pending assertions skip/importorskip-gated:
- `test/test_config/test_config_models.py` (M2-06) — `model_dump(mode="json")` round-trip
  (Decimal→str) + `Settings` missing-secret `ValidationError`. `test_config/` directory created.
- `test/test_core/test_enums.py` (M2-07) — `FillStatus` case-insensitive parse + clear
  (non-printf-tuple) unknown-value error.
- `test/test_portfolio_handler/test_state_storage.py` (M2-08) —
  `PortfolioStateStorageFactory.create("backtest")` in-memory backend + round-trip seam.
- `test/test_order_handler/test_order_timestamps.py` (M2-09) — `add_state_change` event-time +
  `modify_order` routing.
- `test/test_outils/test_time_parser.py` (M2-10) — `to_timedelta` 1W/1M/1H (skip-gated) +
  `check_timeframe` daily-UTC grid (asserted LIVE, passes today).

All five MOVE with the tree into `tests/unit/...` during the 03-08 type-split (noted in each
file's module docstring so 03-08 reconciles without duplication). conftest/markers were NOT
touched (the type-axis marker home is decided in 03-08).

## Verification

- `pytest --co -q` on the 5 stubs: 12 tests collected, 0 errors.
- `make test`: **300 passed, 11 skipped, 1 xfailed** in ~11s. The 11 skips are the pending
  stub assertions; the 1 xfail is the pre-existing DEF-02-08-A numeric-oracle deferral.
  `test_check_timeframe_fires_on_daily_utc_grid` ran live and passed.
- Inertness reference: all three files exist and are non-empty.
- pydantic import + lockfile entries confirmed.

## Deviations from Plan

None — plan executed exactly as written. Two planned conditional choices were resolved as
the plan anticipated: the M2-07 stub guards on `getattr(enums, "FillStatus", None)` because
only `ExecutionStatus` exists today (the plan explicitly noted the enum home; `FillStatus`
arrives in a later wave), and `test_config/` needed no `__init__.py` (unique filename, no
collision — exactly the plan's stated expectation).

## Known Stubs

The 5 Wave-0 files are intentional characterization stubs, not production stubs. Their
pending assertions are skip/importorskip-gated and turn into live assertions as waves
03-02..03-07 land the corresponding code (M2-06→03-05, M2-07/08/09/10→their owning waves).
`check_timeframe` (M2-10) is already asserted live. This is by design per the plan objective
(Wave-0 scaffold) — they do not block the plan goal.

## Self-Check: PASSED

- M2A-INERTNESS-REF/{trades,equity,summary} — FOUND (committed in 53df71a)
- pyproject.toml + poetry.lock pydantic entries — FOUND (committed in 6832455)
- 5 test stub files — FOUND (committed in c1eb3dd)
- Commits 53df71a / 6832455 / c1eb3dd — present in git log

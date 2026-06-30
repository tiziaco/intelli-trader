---
phase: 04-retention-live-write-through-2-live-path
plan: 04
subsystem: storage / phase-gate
tags: [gate-01, gate-02, import-quarantine, oracle, perf-gate, inertness, hot-path]
requires:
  - 04-01 CachedSqlOrderStorage + order factory 'live' arm (Wave 1, merged)
  - 04-02 CachedSqlPortfolioStateStorage + portfolio factory 'live' arm (Wave 1, merged)
  - 04-03 CachedSqlSignalStorage + signal factory 'live' arm (Wave 1, merged)
provides:
  - clean-interpreter import-quarantine proof (backtest storage path pulls no SQL / no cached_sql_storage)
  - GATE-01 (bound here) closed — oracle byte-exact + W1 no-regression + import-quarantine
  - GATE-02 (recurring) closed — mypy --strict clean over the 3 new modules + full suite green
affects: [N+4 reconciliation, v1.6 milestone gate ledger]
tech-stack:
  added: []
  patterns:
    - "subprocess + sys.executable clean-interpreter import-quarantine (in-process sys.modules is unreliable — sqlalchemy already imported by sibling integration tests in-session)"
    - "thermal-attribution: same-tree A/B variance over the frozen-absolute compare when the box is throttled (auto-memory v1.5)"
key-files:
  created:
    - tests/unit/storage/test_import_quarantine.py
  modified:
    - tests/unit/order/test_order_storage.py
decisions:
  - "GATE-01 perf half attributed via same-machine same-tree A/B (W1 clean; W2 wall-clock under thermal drift) — NOT the frozen W2 absolute; W2 baseline re-freeze DEFERRED to a cool machine"
  - "Stale Phase-3 order live-arm test updated to the Wave-1 CachedSql wrapper contract (D-04) — Rule 1 auto-fix, not a behavior regression"
metrics:
  tasks_completed: 2
  files_created: 1
  files_modified: 1
  commits: 3
  duration: ~7min
  completed: 2026-06-30
requirements-completed: [GATE-01, RETAIN-01]
---

# Phase 4 Plan 04: GATE-01 Inertness + GATE-02 Quality Gate Summary

**Closed the GATE-01 hot-path-inertness gate (bound to Phase 4) and the recurring GATE-02
quality gate against the real merged Wave-1 tree: a clean-interpreter import-quarantine proves
the backtest storage path pulls neither SQLAlchemy nor any `cached_sql_storage` wrapper, the
SMA_MACD oracle holds byte-exact 134 / 46189.87730727451, W1 shows no regression, and the full
suite is mypy --strict + `filterwarnings=["error"]` green.**

## Performance

- **Duration:** ~7 min
- **Tasks:** 2 / 2
- **Files:** 1 created, 1 modified
- **Commits:** 3 (`e3c3a0c`, `4f97b8f`, + this docs commit)

## What Was Built

### Task 1 — Subprocess import-quarantine unit test (GATE-01)
`tests/unit/storage/test_import_quarantine.py` (folder-derived `unit` marker, no `__init__.py`).
A PROBE script runs in a **fresh interpreter** via `subprocess.run([sys.executable, "-c", PROBE])`
(an in-process `sys.modules` assertion would be unreliable — SQLAlchemy is already imported by the
sibling `tests/integration/storage/` suite within the same pytest session). The probe imports all
three storage factories, constructs each `'backtest'` backend
(`OrderStorageFactory.create('backtest')`, `PortfolioStateStorageFactory.create('backtest')`,
`SignalStorageFactory.create('backtest')`), then asserts `'sqlalchemy' not in sys.modules` and no
module name contains `'cached_sql_storage'`, printing the `QUARANTINE_OK` sentinel. The test asserts
returncode 0 + the sentinel in stdout and surfaces the probe stderr on failure. Module docstring ties
it to GATE-01 / Pitfall 3 / RETAIN-01 (backend-selection at wiring — zero hot-path cost is structural,
not disciplined).

### Task 2 — Phase gate run (GATE-01 + GATE-02), recorded below
No production code; the gate verification itself. Surfaced and fixed one stale Wave-1 test (Deviations).

## Gate Results (recorded)

| Gate | Command | Result |
|------|---------|--------|
| Import-quarantine (GATE-01) | `poetry run pytest tests/unit/storage/test_import_quarantine.py -x -q` | **1 passed** — `QUARANTINE_OK`; backtest path SQL-free + wrapper-free in a clean interpreter |
| Oracle byte-exact (GATE-01) | `poetry run pytest tests/integration/test_backtest_oracle.py -x -q` | **3 passed** — zero-tolerance vs golden `tests/golden/summary.json` (`trade_count: 134`, `final_equity: 46189.87730727451`, `final_cash: 46189.87730727451`) |
| mypy --strict 3 new modules (GATE-02) | `poetry run mypy --strict itrader/{order_handler,portfolio_handler,strategy_handler}/storage/cached_sql_storage.py` | **Success: no issues in 3 source files** — no new pyproject override (A5) |
| mypy --strict full project (GATE-02) | `poetry run mypy` | **Success: no issues in 210 source files** |
| Full suite (GATE-02) | `poetry run pytest tests -q` (Docker up, testcontainers Postgres) | **1456 passed** under `filterwarnings=["error"]` — no new broad ignore |
| W1 perf no-regression (GATE-01) | `make perf-w1` (`--check` vs frozen baseline 15.7 s / 152.8 MB) | **PASS** — 15.3 s **Δ −2.8 %** wall (faster, within ±5 % band); 144.1 MB Δ −5.7 % (watched); fill/closed counts identical (1578 / 659) |
| W2 perf (GATE-01) | `make perf-w2` (`--check`) | Thermal-attribution caveat below — NOT a code regression |

### W2 thermal-attribution caveat (per the plan + auto-memory v1.5 note)
`make perf-w2 --check` is an **inverted-sense improvement gate** (it was built for the v1.5 perf
phase that had to *prove* a ≥10 % speedup vs the optimization baseline); for v1.6 the relevant
question is the inverse — regression. W2@50 came in 2.79 s vs the v1.5-frozen 2.30 s (+21.5 %), so
the improvement gate "FAILED" by design.

This is **machine thermal/contention drift, not a code regression**:
- Two **back-to-back runs of the identical tree** gave W2@50 = **2.79 s then 4.59 s** (≈+64 %
  swing). The same-tree variance envelope dwarfs the +21.5 % vs-baseline delta — so it cannot be
  attributed to code (same-machine A/B attribution, the auto-memory v1.5 method).
- W2@50 **peak_mem was bit-stable** across both runs (188.65 → 188.68 MB) — the *work* is identical;
  only wall-clock drifts. (Memory is "watched, never gated" in the harness.)
- The **gating W1 workload passed clean** (−2.8 % wall, identical 1578/659 fill counts).
- This plan + Wave 1 add **zero code to the backtest hot path** — the persistence layer is
  structurally inert (import-quarantine green; the `'backtest'` factory arms import no SQL/wrapper).

**Action:** W2 baseline re-freeze is **DEFERRED to a cool machine** (do NOT re-freeze under throttle,
auto-memory v1.5). No regression is attributable to Phase 4.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Stale Phase-3 order live-arm test failed against the Wave-1 wrapper contract**
- **Found during:** Task 2 (full-suite gate run — initial `poetry run pytest tests` was 1 failed / 1455 passed)
- **Issue:** `tests/unit/order/test_order_storage.py::test_create_live_storage_returns_sql_backend`
  (Phase-3 era) asserted the `'live'` arm returns a bare `SqlOrderStorage` and called
  `storage.dispose()`. Wave-1 04-01 intentionally rewired the arm to
  `CachedSqlOrderStorage(SqlOrderStorage(...))` (D-04, documented in 04-01-SUMMARY); the wrapper is
  not a `SqlOrderStorage` subclass and exposes no `dispose()`. The test was never updated when the
  factory contract changed (the Wave-1 worktree ran only the storage integration suite). This
  surfaces only on the merged tree — it is the GATE-02 full-suite gate doing its job.
- **Fix:** Renamed to `test_create_live_storage_returns_cached_sql_wrapper`; assert
  `isinstance(storage, CachedSqlOrderStorage)` and `isinstance(storage._store, SqlOrderStorage)`
  (composition over the untouched Phase-3 store); dispose the underlying engine via
  `storage._store.dispose()` to avoid a `ResourceWarning` under `filterwarnings=["error"]` (WR-03).
- **Why this is an auto-fix, not papering over a regression:** the behavior change (live arm returns
  the cache wrapper) is the *intended, summary-documented* Wave-1 design; the oracle is byte-exact and
  W1 shows no regression. Only a stale test assertion was out of sync.
- **Files modified:** `tests/unit/order/test_order_storage.py`
- **Commit:** `4f97b8f`

Sibling check: `tests/unit/portfolio/test_state_storage.py::test_factory_live_raises` correctly
expects `ConfigurationError` (the portfolio live arm requires `portfolio_id`) and needed no change;
no signal-factory live-arm unit test constructs a backend. Only the order test was stale.

## Threat Coverage
- **T-04-09 (Tampering/DoS — backtest hot-path inertness):** mitigated and now *verified structurally*
  by the clean-interpreter import-quarantine subprocess test (`'sqlalchemy'`/`'cached_sql_storage'`
  absent on the backtest path) plus the oracle byte-exact + W1 A/B no-regression — zero hot-path cost
  (Pitfall 3 / GATE-01).
- **T-04-SC (supply chain):** accept — Phase 4 installs NO packages; nothing to verify.

No new threat surface introduced.

## Known Stubs
None. This plan is the cross-cutting gate; it adds one test and fixes one stale test.

## Self-Check: PASSED
- FOUND: tests/unit/storage/test_import_quarantine.py
- FOUND: tests/unit/order/test_order_storage.py (modified)
- NOT created: tests/unit/storage/__init__.py (package-collision hazard avoided)
- Commits verified in git history: `e3c3a0c` (test), `4f97b8f` (fix)

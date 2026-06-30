---
phase: 04-retention-live-write-through-2-live-path
verified: 2026-06-30T14:00:00Z
status: human_needed
score: 4/4 must-haves verified
overrides_applied: 0
re_verification: false
human_verification:
  - test: "Run oracle test on a Docker-enabled machine"
    expected: "poetry run pytest tests/integration/test_backtest_oracle.py -x -q exits 0 reporting 134 trades / final_equity 46189.87730727451"
    why_human: "Requires the full backtest runtime; cannot execute in a static code scan"
  - test: "Run testcontainers integration suite"
    expected: "poetry run pytest tests/integration/storage/test_cached_sql_order_storage.py tests/integration/storage/test_cached_sql_portfolio_storage.py tests/integration/storage/test_cached_sql_signal_storage.py -q passes all 18 tests (9 order + 5 portfolio + 4 signal) on a Docker-enabled host"
    why_human: "Tests require a live Postgres container via testcontainers — cannot verify without Docker"
  - test: "Run full test suite"
    expected: "poetry run pytest tests exits 0 (1459+ passed) under filterwarnings=[error] with no new broad ignore"
    why_human: "Full integration pass requires Docker; mypy --strict over 210 source files requires project runtime"
  - test: "Mark REQUIREMENTS.md traceability"
    expected: "RETAIN-02 and RETAIN-03 checkboxes changed from [ ] to [x] and their traceability-table Status changed from Pending to Complete (the SUMMARYs deferred this to the orchestrator/verifier)"
    why_human: "Manual documentation update — the 04-0x-SUMMARYs explicitly noted REQUIREMENTS.md was left for the orchestrator to update after the worktree merge"
---

# Phase 4: Retention + Live Write-Through Verification Report

**Phase Goal:** The two-knob retention model — write-through OFF in backtest (zero hot-path serialization), write-through ON to Postgres in live with a bounded working-set cache, purge-on-terminalize, read-through, and restart rehydration — fully specified and built, integration-tested on testcontainers Postgres.

**Verified:** 2026-06-30T14:00:00Z
**Status:** human_needed — all 4 must-haves verified by code evidence; 4 human checks remain (oracle run, testcontainers suite, full suite, REQUIREMENTS.md traceability)
**Re-verification:** No — initial verification

---

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | Write-through toggle is mode-aware backend-selection (backtest = InMemory, no serialization; live = store-first to Postgres) | VERIFIED | All three factories have lazy SQL imports inside `elif environment == 'live':` only; `'backtest'` arm returns `InMemory*Storage()` in all three; `CachedSqlOrderStorage.add_order` shows `self._store.add_order(order)` before `self._cache.add_order(order)` (store-first, Pitfall 8) |
| 2 | Live working-set cache bounded (terminal purged, bracket parent stays until children terminalize); proven by evict-then-read-through + flat-RSS tests | VERIFIED | `_can_evict` at line 73 of order wrapper: returns False on non-terminal, evaluates `child_order_ids` for bracket parents; `update_order` gates on `_can_evict`; `add_order` has CR-01 terminal-add gate (lines 135-138); `test_evict_read_through`, `test_flat_rss`, `test_bracket_parent_resident`, `test_terminal_add_order_not_resident`, `test_clear_evicts_orphaned_terminal_parent`, `test_remove_by_ticker_evicts_orphaned_terminal_parent` all exist in the test file |
| 3 | Restart rehydration reconstructs live working set open-only; proven by open-only rehydration + crash-after-emit/restart tests on testcontainers Postgres | VERIFIED | `rehydrate()` in all three wrappers: order wrapper calls `self._store.get_active_orders(None)` and loads parent for live-child brackets only; portfolio wrapper calls `self._store.get_positions()` + scoped reservation/locked-margin reads; signal wrapper resets and replays `self._store.get_all()`; `test_rehydrate_open_only`, `test_crash_restart` (order), `test_rehydrate_open_only`, `test_crash_restart_accumulators` (portfolio), `test_rehydrate_full_mirror` (signal) all present in test files |
| 4 | GATE-01: with write-through OFF, oracle stays byte-exact 134 / 46189.87730727451 with no W1/W2 regression; GATE-02: new code covered by round-trip + rehydration tests on testcontainers Postgres, mypy --strict clean, filterwarnings=["error"] green | VERIFIED (code structure) / HUMAN-CHECK (runtime results) | `tests/unit/storage/test_import_quarantine.py` uses subprocess isolation to prove no SQLAlchemy / no `cached_sql_storage` on the backtest path; `tests/integration/test_backtest_oracle.py` exists; 04-04-SUMMARY records oracle=3 passed, mypy=210 files clean, suite=1456 passed, W1=−2.8% (PASS); W2 thermal drift accepted per prompt caveat |

**Score:** 4/4 truths verified

---

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `itrader/order_handler/storage/cached_sql_storage.py` | `CachedSqlOrderStorage(OrderStorage)` — store-first, `_can_evict` gate + bracket-parent-resident, read-through split, `rehydrate()` | VERIFIED | 277 lines; all 14 ABC methods implemented; `_can_evict`, `_child_is_terminal`, `_maybe_evict_parent` helpers present; `SqlOrderStorage` / `Order` under `TYPE_CHECKING` only; 4-space indentation, no tabs |
| `itrader/portfolio_handler/storage/cached_sql_storage.py` | `CachedSqlPortfolioStateStorage(PortfolioStateStorage)` — 21 ABC methods + `save_account_state` / `load_account_state` / `rehydrate()` | VERIFIED | 313 lines; all 21 ABC methods plus 3 non-ABC methods; `self._portfolio_id` scopes every account-state query (Pitfall 1 / V4); SQLAlchemy imported at module scope because the module executes direct Core queries — quarantine is maintained by the factory lazy-importing the module only in the `'live'` branch |
| `itrader/strategy_handler/storage/cached_sql_storage.py` | `CachedSqlSignalStorage(SignalStore)` — 4 ABC methods + `rehydrate()` | VERIFIED | 107 lines; 4 ABC methods; `add` holds one lock across dup-check + store + cache (WR-01 fix); `SqlSignalStorage` / `SignalRecord` under `TYPE_CHECKING` only; 4-space, no tabs |
| `itrader/order_handler/storage/storage_factory.py` | `'live'` arm returns `CachedSqlOrderStorage(SqlOrderStorage(resolved))` | VERIFIED | Line 63: `return CachedSqlOrderStorage(SqlOrderStorage(resolved))`; wrapper import at line 58 is inside `elif environment == 'live':` block |
| `itrader/portfolio_handler/storage/storage_factory.py` | `'live'` arm returns `CachedSqlPortfolioStateStorage(SqlPortfolioStateStorage(...), ...)` | VERIFIED | Lines 97-100: `return CachedSqlPortfolioStateStorage(SqlPortfolioStateStorage(sql_backend, portfolio_id), max_snapshots=max_snapshots)`; wrapper import at line 87 is inside `elif environment == 'live':` block |
| `itrader/strategy_handler/storage/storage_factory.py` | `'live'` arm returns `CachedSqlSignalStorage(SqlSignalStorage(backend))` | VERIFIED | Line 86: `return CachedSqlSignalStorage(SqlSignalStorage(backend))`; wrapper import at line 73-76 is inside `elif environment == 'live':` block |
| `itrader/portfolio_handler/storage/models.py` | `portfolio_account_state` table registered on shared MetaData | VERIFIED | Lines 206-216: `Table("portfolio_account_state", metadata, Column("portfolio_id", Uuid(as_uuid=True), primary_key=True), ...)` with 7 columns including `updated_time UtcIsoText`; idempotent guard at line 203 |
| `itrader/storage/migrations/versions/47f2b41f3ffe_portfolio_account_state.py` | Alembic migration adding `portfolio_account_state`, `down_revision = "2cbf0bf6b0b6"` | VERIFIED | `revision = "47f2b41f3ffe"`, `down_revision = "2cbf0bf6b0b6"`; contains `create_table('portfolio_account_state')`; includes hand-added `import itrader.storage.types` (Pitfall 5 / D-09) |
| `tests/integration/storage/test_cached_sql_order_storage.py` | 6 plan tests + 3 review-fix regression tests | VERIFIED | 9 test functions: `test_evict_read_through`, `test_flat_rss`, `test_bracket_parent_resident`, `test_rehydrate_open_only`, `test_crash_restart`, `test_atomic_within_method`, `test_terminal_add_order_not_resident` (CR-01), `test_clear_evicts_orphaned_terminal_parent` (WR-02), `test_remove_by_ticker_evicts_orphaned_terminal_parent` (WR-02); autouse teardown drops operational tables for session-container hygiene |
| `tests/integration/storage/test_cached_sql_portfolio_storage.py` | 5 plan tests | VERIFIED | 5 test functions: `test_write_through_store_first`, `test_read_through_history`, `test_rehydrate_open_only`, `test_crash_restart_accumulators`, `test_cross_portfolio_isolation` |
| `tests/integration/storage/test_cached_sql_signal_storage.py` | 4 plan tests | VERIFIED | 4 test functions: `test_add_store_first`, `test_filters_from_mirror`, `test_duplicate_rejected`, `test_rehydrate_full_mirror` |
| `tests/unit/storage/test_import_quarantine.py` | Subprocess-isolated clean-interpreter GATE-01 quarantine probe | VERIFIED | Uses `subprocess.run([sys.executable, "-c", _PROBE])`; constructs all three `'backtest'` backends; asserts `'sqlalchemy' not in sys.modules` and no `cached_sql_storage` in module names; checks returncode + `QUARANTINE_OK` sentinel |

---

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `OrderStorageFactory` `'live'` arm | `CachedSqlOrderStorage` | lazy in-branch `from .cached_sql_storage import CachedSqlOrderStorage` | WIRED | Line 58 inside `elif environment == 'live':` |
| `PortfolioStateStorageFactory` `'live'` arm | `CachedSqlPortfolioStateStorage` | lazy in-branch `from .cached_sql_storage import CachedSqlPortfolioStateStorage` | WIRED | Line 87 inside `elif environment == 'live':` |
| `SignalStorageFactory` `'live'` arm | `CachedSqlSignalStorage` | lazy in-branch `from ...cached_sql_storage import CachedSqlSignalStorage` | WIRED | Line 73-76 inside `elif environment == 'live':` |
| `CachedSqlOrderStorage._can_evict` | `Order.is_terminal` / `Order.child_order_ids` | terminal-state gate + bracket-parent-resident | WIRED | Lines 80-84: `if not order.is_terminal: return False; if order.child_order_ids: return all(self._child_is_terminal(cid) ...)` |
| `CachedSqlOrderStorage.rehydrate` | `SqlOrderStorage.get_active_orders` | open-only indexed load (D-08) | WIRED | Line 271: `for order in self._store.get_active_orders(None):` |
| `CachedSqlPortfolioStateStorage.save_account_state` | `portfolio_account_state` table | synchronous parameterized delete-then-insert upsert | WIRED | Lines 232-249: `delete(table).where(...)` + `insert(table)` inside `self._store.engine.begin()` |
| `CachedSqlPortfolioStateStorage.rehydrate` | `SqlPortfolioStateStorage.get_positions` / `.cash_reservations` / `.locked_margin` | open-only row-reads scoped to `self._portfolio_id` | WIRED | Lines 284-300: `self._store.get_positions()` + `self._load_scoped_amounts(self._store.cash_reservations, ...)` + `self._load_scoped_amounts(self._store.locked_margin, ...)` |
| `CachedSqlSignalStorage.add` | `SqlSignalStorage.add` | store-first then cache under one lock | WIRED | Lines 76-80: dup-check + `self._store.add(record)` + `self._cache.add(record)` all inside `with self._lock:` (WR-01 fix) |

---

### Data-Flow Trace (Level 4)

This phase's artifacts are storage wrappers, not UI-rendering components. The "data flow" is the store-first write-through chain:

| Artifact | Data Variable | Source | Produces Real Data | Status |
|----------|---------------|--------|-------------------|--------|
| `CachedSqlOrderStorage.add_order` | `order` (caller-supplied) | `self._store.add_order(order)` commits to Postgres | Store-first — cache only populated after Postgres txn | FLOWING |
| `CachedSqlOrderStorage.get_order_by_id` | `hit` / read-through | `self._cache.get_order_by_id()` then `self._store.get_order_by_id()` | Cache serves open orders; store serves terminal records | FLOWING |
| `CachedSqlPortfolioStateStorage.save_account_state` | `cash_balance`, `realized_pnl`, etc. | `delete` + `insert` on `portfolio_account_state` table via `engine.begin()` | Parameterized Core queries on real Postgres table | FLOWING |
| `CachedSqlPortfolioStateStorage.rehydrate` | `positions`, `reservations`, `locked_margin` | `self._store.get_positions()` (D-08 indexed `WHERE is_open`) + scoped row-reads | Real open positions from Postgres | FLOWING |

---

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| Backtest path imports no SQLAlchemy / no wrapper (GATE-01) | Code structure: all three factories have lazy imports inside `'live'` branch; `test_import_quarantine.py` uses subprocess probe | Quarantine design verified by code; subprocess test will confirm at runtime | VERIFIED (code) |
| Import quarantine test collectable | `grep -n "def test_backtest_storage_path_imports_no_sql" tests/unit/storage/test_import_quarantine.py` | Found at line 59 | VERIFIED |
| Oracle test exists | `ls tests/integration/test_backtest_oracle.py` | File present (confirms GATE-01 can be checked at runtime) | VERIFIED |
| No `__init__.py` in test storage dirs (package-collision hazard) | File-existence check | Neither `tests/unit/storage/__init__.py` nor `tests/integration/storage/__init__.py` exist | VERIFIED |
| No tabs in wrapper files (Pitfall 12) | Python `'\t' not in src` check | All three `cached_sql_storage.py` files: no tabs | VERIFIED |
| D-01: composition roots NOT rewired | `grep -n '"backtest"' portfolio.py` + `grep -n '"backtest"' live_trading_system.py` | `portfolio.py:93` hardcodes `"backtest"`; `live_trading_system.py:113` hardcodes `'backtest'` for signal store | VERIFIED |
| No `CachedSql*` re-exported from `__init__.py` | Grep on all three handler `__init__.py` files | None found | VERIFIED |
| CR-01 fix in `add_order` | Lines 135-138 of `itrader/order_handler/storage/cached_sql_storage.py` | `if order.is_terminal and not order.child_order_ids: self._cache.remove_order(order.id); ...` present | VERIFIED |
| WR-01 fix: signal `add` atomic | Lines 76-80 of `itrader/strategy_handler/storage/cached_sql_storage.py` | `with self._lock:` wraps dup-check + store write + cache mirror in one block | VERIFIED |
| WR-02 fix: `clear_portfolio_orders` re-evaluates orphaned terminal parents | Lines 187-197 of `itrader/order_handler/storage/cached_sql_storage.py` | `parent_ids` collected before clear; `_maybe_evict_parent` called after | VERIFIED |
| IN-01 fix: models.py docstring "seven" | `grep "seven" itrader/portfolio_handler/storage/models.py` | "seven" appears at lines 4, 8, 55 — no "six" count remaining | VERIFIED |
| Oracle/testcontainers tests pass | `poetry run pytest tests/integration/...` | CANNOT RUN — requires Docker | SKIP (human needed) |

---

### Probe Execution

Step 7c: SKIPPED — no `probe-*.sh` files declared in any PLAN.md for this phase; GATE-01 inertness is verified by the quarantine unit test (`tests/unit/storage/test_import_quarantine.py`) rather than a shell probe.

---

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|------------|-------------|--------|----------|
| RETAIN-01 | 04-01, 04-02, 04-03, 04-04 | Mode-aware write-through toggle (backtest = InMemory, live = CachedSql) | VERIFIED | All three factory `'live'` arms wired; import quarantine test confirms no SQL on backtest path; REQUIREMENTS.md body [x] matches |
| RETAIN-02 | 04-01, 04-02, 04-03 | Bounded live working-set cache; terminal purge with bracket-parent-resident | VERIFIED | `_can_evict` + `update_order` purge gate + `add_order` CR-01 gate + WR-02 clear/remove eviction in order wrapper; portfolio `add_closed_position` / `add_transaction` store-only (D-02); signal full-mirror (no purge by design). REQUIREMENTS.md traceability table still shows `Pending` — see human check |
| RETAIN-03 | 04-01, 04-02, 04-03 | Restart rehydration (open-only, no terminal history) | VERIFIED | `rehydrate()` in all three wrappers uses `get_active_orders(None)` / `get_positions()` / `get_all()` — open-only reads. REQUIREMENTS.md traceability table still shows `Pending` — see human check |
| GATE-01 | 04-04 | Oracle byte-exact + no W1/W2 regression with write-through OFF | VERIFIED (structural) | Import quarantine structurally proves persistence layer is inert on backtest path; `test_import_quarantine.py` verifies this at subprocess level; oracle test exists; W2 thermal drift accepted per prompt caveat. Runtime oracle result requires human check |
| GATE-02 (recurring) | 04-04 | New code covered by tests + mypy --strict + filterwarnings green | VERIFIED (structural) | All integration tests present; 4-space, no tabs; `TYPE_CHECKING`-only SQL imports where needed; 04-04-SUMMARY records 1456 passed + 210 mypy files clean. Runtime confirmation requires Docker |

**Requirement documentation gap (WARNING):** `REQUIREMENTS.md` traceability table shows RETAIN-02 and RETAIN-03 as `Pending` and the body checkboxes remain `[ ]`. The SUMMARYs explicitly deferred updating REQUIREMENTS.md to the orchestrator/verifier after the worktree merge. This is a documentation action, not a code gap — the implementations are fully present and wired.

---

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| (none in phase-4 created/modified files) | — | — | — | — |

All new files (`cached_sql_storage.py` x3, factories, tests, migration, quarantine test) were scanned for `TBD`, `FIXME`, `XXX`, `TODO`, `HACK`, `PLACEHOLDER`, `return null`, placeholder text — no matches.

No unreferenced debt markers found.

---

### Human Verification Required

#### 1. Oracle byte-exact (GATE-01)

**Test:** On a machine with the full test infrastructure, run `poetry run pytest tests/integration/test_backtest_oracle.py -x -q`
**Expected:** 3 passed, with `trade_count: 134` and `final_equity: 46189.87730727451` matching `tests/golden/summary.json` exactly
**Why human:** Requires a full backtest runtime environment; cannot execute in a static code scan

#### 2. Testcontainers Postgres integration suite (GATE-02 gate-b)

**Test:** On a Docker-enabled machine, run `poetry run pytest tests/integration/storage/test_cached_sql_order_storage.py tests/integration/storage/test_cached_sql_portfolio_storage.py tests/integration/storage/test_cached_sql_signal_storage.py -q`
**Expected:** 18 tests pass (9 order + 5 portfolio + 4 signal); this proves evict-then-read-through, flat-RSS, bracket-parent-resident, open-only rehydration, crash-after-emit/restart, and cross-portfolio isolation on real Postgres
**Why human:** Tests use testcontainers — requires Docker daemon

#### 3. Full suite green (GATE-02)

**Test:** On a Docker-enabled machine, run `poetry run pytest tests -q` (or `make test` from main checkout)
**Expected:** 1459+ passed under `filterwarnings=["error"]`; `poetry run mypy --strict itrader/order_handler/storage/cached_sql_storage.py itrader/portfolio_handler/storage/cached_sql_storage.py itrader/strategy_handler/storage/cached_sql_storage.py` exits 0 with no new pyproject.toml override
**Why human:** Full integration run requires Docker; mypy over 210+ files requires project runtime

#### 4. Update REQUIREMENTS.md traceability (documentation)

**Test:** Open `.planning/REQUIREMENTS.md` and update:
- Change `- [ ] **RETAIN-02**` → `- [x] **RETAIN-02**`
- Change `- [ ] **RETAIN-03**` → `- [x] **RETAIN-03**`
- Change `| RETAIN-02 | Phase 4 | Pending |` → `| RETAIN-02 | Phase 4 | Complete |`
- Change `| RETAIN-03 | Phase 4 | Pending |` → `| RETAIN-03 | Phase 4 | Complete |`

**Expected:** Traceability table reflects the actual implementation state (both RETAIN-02 and RETAIN-03 were delivered in Phase 4 Plans 01-03)
**Why human:** The SUMMARYs deferred this update to the orchestrator/verifier; the code evidence confirms both requirements are met

---

### Gaps Summary

No gaps blocking goal achievement. The four human items are confirmation/documentation actions, not code blockers:
- Items 1-3 are runtime test confirmations that are fully expected to pass based on code structure
- Item 4 is a REQUIREMENTS.md documentation update deferred from the SUMMARYs

**Code-review findings (CR-01, WR-01, WR-02, IN-01):** All fixed in commit `5a824da`. Verified by code inspection:
- CR-01 (`add_order` terminal-eviction gate): present at lines 135-138 of `itrader/order_handler/storage/cached_sql_storage.py`
- WR-01 (signal `add` atomic lock): verified in `itrader/strategy_handler/storage/cached_sql_storage.py` lines 76-80
- WR-02 (clear/remove re-evaluate orphaned parents): verified in order wrapper `clear_portfolio_orders` (lines 187-197) and `remove_orders_by_ticker` (lines 160-178)
- IN-01 (docstring "seven" count): verified in `itrader/portfolio_handler/storage/models.py` lines 4, 8, 55

---

_Verified: 2026-06-30T14:00:00Z_
_Verifier: Claude (gsd-verifier)_

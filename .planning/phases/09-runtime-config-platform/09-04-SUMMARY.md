---
phase: 09-runtime-config-platform
plan: 04
subsystem: database
tags: [runtime-config, read-model, system-stats, state-kv, alembic, migration, single-head, rtcfg-06, d-17, d-18, d-19, d-25]

# Dependency graph
requires:
  - phase: 09-runtime-config-platform
    plan: 01
    provides: "ITraderConfig frozen root + mutable sub-models + validate_assignment"
  - phase: 09-runtime-config-platform
    plan: 03
    provides: "build_order_config_table registrar + extended build_portfolio_tables (config_json column) whose Alembic migration this plan finalizes; SystemStore state.* KV surface"
provides:
  - "system_stats append-only table + build_system_stats_table registrar + SystemStatsStore (append/read_recent/read_all) — engine-operational counters only, schema-pure, lock-free reads (RTCFG-06/D-18)"
  - "state.status / state.halt_reason upserted into SystemStore at the SafetyController status-transition + halt event sources; state.last_started_at at facade start() (D-19)"
  - "thin engine-thread stats writer (_snapshot_system_stats) appending engine-operational counters on each status transition — NO entity duplication (D-17)"
  - "P9 migration finalization: single-head Alembic chain strategy_registry -> module_config (order_config table + portfolio_account_state.config_json column) -> system_stats, with create_all/upgrade-head parity gate extended by hand"
affects: [10-strategies-registry, 11-multi-portfolio-live, fastapi-config-ingress]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Read-model = domain stores + state.* KV + thin system_stats series; NO entity duplication (D-17) — equity/orders/halts read from their OWN domain stores, only engine-operational counters no domain store owns live in system_stats"
    - "Registrar single-source (build_system_stats_table feeds BOTH create_all and migrations/env.py target_metadata); schema-pure store (WR-03/D-14 — register, never create_all)"
    - "Migration-owner finalization: the phase's schema changes chain single-head (strategy_registry -> module_config -> system_stats); module_config creates order_config + ALTERs portfolio_account_state ADD config_json (D-25 — no portfolio_config table)"
    - "state.* read-model KV written event-driven at source (status transition/halt/start) into SystemStore, best-effort (a durable-write failure never aborts a status transition — a halt above all)"
    - "system_stats seq is engine-written (max(seq)+1 in-txn, autoincrement=False) — no second ID scheme; reads are plain lock-free engine.connect() (RTCFG-06)"

key-files:
  created:
    - itrader/storage/system_stats_store.py
    - migrations/versions/module_config.py
    - migrations/versions/system_stats.py
    - tests/unit/storage/test_system_stats_store.py
  modified:
    - migrations/env.py
    - itrader/trading_system/safety/safety_controller.py
    - itrader/trading_system/live_trading_system.py
    - tests/integration/storage/test_migrations.py
    - tests/integration/storage/test_cached_sql_order_storage.py

key-decisions:
  - "system_stats holds ONLY engine-operational counters no domain store owns (throttle breach count, error counts by severity, queue depth, uptime, connector/stream health) — portfolio equity is NEVER copied in (D-17/D-18)"
  - "The migration chain is strategy_registry -> module_config -> system_stats (two new revisions), NOT the single system_stats revision the pre-D-25 PATTERNS/RESEARCH docs sketched — Plan 03 deferred the order_config/config_json migration here, so module_config finalizes it (down_revision=strategy_registry) and system_stats chains after it as the new head"
  - "The test_migrations.py parity gate is HARDCODED (not dynamic): _NEW_TABLES tuple + explicit engine-A registrar list + single-head tuple assertion were all extended BY HAND to cover order_config + system_stats as NEW tables plus a config_json column-parity check on the EXISTING portfolio_account_state (A3's dynamic-enumeration assumption was false)"
  - "Error counts by severity start minimal: the facade holds ONE aggregate error counter today (snapshot into error_count_error); warning/critical stay 0 until a per-severity surface exists — the schema leaves room (D-18 extensible)"
  - "connector_up/stream_up are derived from the safety latch (not halted / not submission-paused) — the event-driven CONNECTOR_FATAL->halt and STREAM_STATE->pause_submission are the sources; a minimal proxy, extensible"

patterns-established:
  - "Best-effort read-model write: SafetyController._persist_state + facade state.last_started_at + _snapshot_system_stats all swallow-and-log a durable-write failure so a read-model write can never abort the engine event that triggered it"
  - "Pristine shared-container discipline: a create_all-based pg round-trip test must drop EVERY table its store registers (order_config was the gap) so a sibling migration test's upgrade head stays collision-free"

requirements-completed: [RTCFG-06]

coverage:
  - id: D1
    description: "system_stats append-only store: append(row, at) persists an engine-operational-counter row with engine-written seq; read_recent(n)/read_all() reads it back; reads are lock-free (RTCFG-06/D-18)"
    requirement: RTCFG-06
    verification:
      - kind: unit
        ref: "tests/unit/storage/test_system_stats_store.py#test_append_read_round_trip, test_seq_is_engine_written_and_monotonic, test_reads_are_lock_free"
        status: pass
    human_judgment: false
  - id: D2
    description: "state.* read-model KV surface: state.status/state.halt_reason upsert into SystemStore round-trips last-write-wins (D-19)"
    requirement: RTCFG-06
    verification:
      - kind: unit
        ref: "tests/unit/storage/test_system_stats_store.py#test_state_kv_upsert_round_trips"
        status: pass
    human_judgment: false
  - id: D3
    description: "Single-head Alembic chain strategy_registry -> module_config -> system_stats; create_all/upgrade-head parity covers order_config + system_stats as NEW tables PLUS the config_json ADD COLUMN on the EXISTING portfolio_account_state (D-18/D-25)"
    requirement: RTCFG-06
    verification:
      - kind: integration
        ref: "tests/integration/storage/test_migrations.py#test_migration_chain_is_single_head, test_full_chain_upgrade_creates_new_stores_sqlite, test_create_all_vs_migration_parity"
        status: pass
    human_judgment: false
  - id: D4
    description: "Thin stats writer + state.* writers wired in build_live_system (SafetyController state.status/halt_reason at event source; facade state.last_started_at + _snapshot_system_stats); live-only, backtest-dark + import-lazy"
    requirement: RTCFG-06
    verification:
      - kind: integration
        ref: "tests/integration/test_okx_inertness.py, tests/integration/test_backtest_oracle.py"
        status: pass
    human_judgment: false

# Metrics
duration: 30min
completed: 2026-07-16
status: complete
---

# Phase 9 Plan 04: Read-Model (system_stats + state.*) & Migration Finalization Summary

**Built the RTCFG-06 UI read-model half — a schema-pure `system_stats` append-only table/store holding ONLY engine-operational counters (no entity duplication, D-17), event-driven `state.*` writers at their sources (D-19), and a thin engine-thread stats writer — and finalized the phase's Alembic chain single-head as `strategy_registry -> module_config (order_config table + portfolio_account_state.config_json column) -> system_stats` with a hand-extended create_all/migration parity gate.**

## Performance
- **Duration:** ~30 min
- **Completed:** 2026-07-16
- **Tasks:** 3 (+1 auto-fix)
- **Files:** 9 (4 created, 5 modified)

## Accomplishments
- **Task 1 (store + migration finalization, D-18/D-25).** `itrader/storage/system_stats_store.py` (NEW, 4-space) clones the `equity_snapshots` append-only shape + the `SystemStore` template: `build_system_stats_table` registrar (idempotent, single-source), a `seq` Integer PK with `autoincrement=False` (engine writes seq — no second ID scheme), a `UtcIsoText` business `timestamp`, and the minimal counter set (throttle breach / error-by-severity / queue depth / uptime / connector+stream health). `SystemStatsStore` is schema-pure (WR-03/D-14) with `append(row, at)` (SELECT-max-then-INSERT in one `engine.begin()`) + lock-free `read_recent(n)`/`read_all()`. The phase migration chain was finalized: `migrations/versions/module_config.py` (down_revision `strategy_registry`) creates `order_config` (matching Plan 03's `build_order_config_table`) AND `op.add_column("portfolio_account_state", config_json)` (Plan 03's extended `build_portfolio_tables` — NO portfolio_config table); `migrations/versions/system_stats.py` (down_revision `module_config`) is the new single head; `migrations/env.py` registers `build_order_config_table` + `build_system_stats_table`.
- **Task 2 (thin stats writer + state.* writers, D-18/D-19).** `SafetyController` gained an optional `system_store` injection and upserts `state.status` on every winning transition + `state.halt_reason` on a HALTED flip (best-effort via `_persist_state` — never aborts a transition). The facade upserts `state.last_started_at` at `start()`, and `_snapshot_system_stats` appends the engine-operational counters it already holds to `system_stats` on each status transition (NO domain-entity data, D-17). Both the durable KV sink and `SystemStatsStore` are constructed + injected in `build_live_system`, gated on the SQL spine (lazy import, None-degrade on the in-memory fallback → backtest never reaches it).
- **Task 3 (tests).** `tests/unit/storage/test_system_stats_store.py` (NEW, package-less) proves append/read round-trip, engine-written monotonic seq, lock-free reads (structural — the store holds no threading lock), the idempotent registrar, and the sibling `state.*` KV round-trip. `tests/integration/storage/test_migrations.py` was HAND-extended (the parity gate is hardcoded, not dynamic — A3's assumption was false): `_NEW_TABLES` + the engine-A registrar block gained `order_config` + `system_stats`; a `config_json` ADD COLUMN parity assertion was added on the EXISTING `portfolio_account_state`; the single-head + full-chain head assertions became `system_stats`.

## Task Commits
1. **Task 1: system_stats store/table + module_config & system_stats migrations + env.py registrars** — `f97e3938` (feat)
2. **Task 2: thin stats writer + state.* writers wired in build_live_system** — `0a804d76` (feat)
3. **Task 3: system_stats store unit test + extend migration parity/single-head gate** — `1a2017e8` (test)
4. **Auto-fix: drop leftover order_config in pg round-trip teardown** — `08a4e78f` (fix)

## Files Created/Modified
- `itrader/storage/system_stats_store.py` — NEW schema-pure append-only stats store + registrar
- `migrations/versions/module_config.py` — NEW revision: order_config table + portfolio_account_state.config_json column
- `migrations/versions/system_stats.py` — NEW revision: system_stats table (new single head)
- `migrations/env.py` — register build_order_config_table + build_system_stats_table
- `itrader/trading_system/safety/safety_controller.py` — state.status/state.halt_reason writers (optional system_store)
- `itrader/trading_system/live_trading_system.py` — _snapshot_system_stats + state.last_started_at + build_live_system wiring
- `tests/unit/storage/test_system_stats_store.py` — NEW store/state.* unit test
- `tests/integration/storage/test_migrations.py` — hand-extended parity + single-head gate
- `tests/integration/storage/test_cached_sql_order_storage.py` — drop order_config in pg teardown (auto-fix)

## Decisions Made
- Chain is `strategy_registry -> module_config -> system_stats` (two revisions), superseding the pre-D-25 single-revision sketch in PATTERNS/RESEARCH — the plan is authoritative (Plan 03 deferred the order_config/config_json migration here).
- Extended the hardcoded parity gate by hand (not relying on dynamic enumeration — A3 was false).
- Error-by-severity starts minimal (aggregate count → error_count_error; warning/critical 0 until a per-severity surface exists).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking issue] Dropped leftover `order_config` in the pg round-trip teardown**
- **Found during:** Task 3 full-suite gate (the testcontainers Postgres arm).
- **Issue:** `test_cached_sql_order_storage.py`'s autouse `_drop_operational_order_tables` teardown dropped `orders`/`order_state_changes` but was never updated to drop `order_config` when Plan 03 added that table to `SqlOrderStorage.__init__`. The leftover `create_all`-built `order_config` sat in the shared session container. Before this plan the migration chain never created `order_config`, so it was harmless; the NEW `module_config` migration's `CREATE TABLE order_config` during `upgrade head` collided (`DuplicateTable: relation "order_config" already exists`). Latent leak directly exposed by the migration finalization.
- **Fix:** Added `DROP TABLE IF EXISTS order_config CASCADE` to the teardown (no FK, order-independent) so the shared container is left pristine — the same discipline the migration test follows with `downgrade base`.
- **Files modified:** `tests/integration/storage/test_cached_sql_order_storage.py`
- **Verification:** `tests/integration/storage/` 59 passed; full suite 2297 passed / 6 skipped.
- **Committed in:** `08a4e78f`

---

**Total deviations:** 1 auto-fixed (1 blocking). **Impact on plan:** In-scope test-hygiene fix directly caused by adding the `order_config` migration; no production-code or scope change.

## Issues Encountered
- The store's `uptime_seconds` (`Numeric`) round-trips as `Decimal('12.5000000000')` on SQLite (trailing zeros); the unit test compares numerically (`== Decimal("12.5")`), which holds. No `SAWarning` for Decimal-on-SQLite is raised under `filterwarnings=["error"]` (verified with `-W error`).

## Gates
- Backtest oracle byte-exact `134 / 46189.87730727451` (`check_exact`) — backtest-dark confirmed (live-only stats/state plumbing).
- OKX import-inertness green (4 passed) — the system_stats store + build_live_system additions stay SQL/ccxt import-lazy.
- Single-head Alembic chain confirmed: `alembic heads` → `system_stats (head)`; full upgrade + downgrade (to `strategy_registry`) verified clean on SQLite.
- `mypy --strict` clean (261 files).
- Full suite: `2297 passed / 6 skipped` (skips are OKX-credential-gated live suites).

## Next Phase Readiness
- RTCFG-06 read-model surface complete and migration-finalized: the (future FastAPI) UI can read `system_stats` + `state.*` + domain stores lock-free. Phase 9 is complete (plan 4 of 4).
- The read-model logic is independent of the D-21/D-25 config-store move (it never reads config from SystemStore), so it is unaffected by where module config persists.

## Self-Check: PASSED
- Created files verified present: `system_stats_store.py`, `module_config.py`, `system_stats.py`, `test_system_stats_store.py`, `09-04-SUMMARY.md`
- Task commits verified in git log: `f97e3938`, `0a804d76`, `1a2017e8`, `08a4e78f`

---
*Phase: 09-runtime-config-platform*
*Completed: 2026-07-16*

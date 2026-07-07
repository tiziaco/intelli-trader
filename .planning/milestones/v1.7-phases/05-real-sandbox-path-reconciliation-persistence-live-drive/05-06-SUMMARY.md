---
phase: 05-real-sandbox-path-reconciliation-persistence-live-drive
plan: 06
subsystem: live-drive
tags: [live-drive, store, persistence, CachedSql, split-write-path, metrics, equity-curve, RECON-04, D-10, D-11, D-16, WR-01]

# Dependency graph
requires:
  - phase: 05-real-sandbox-path-reconciliation-persistence-live-drive
    plan: 02
    provides: "Offline test infra / FakeLiveConnector + tests/support (reconciliation double)"
  - phase: 05-real-sandbox-path-reconciliation-persistence-live-drive
    plan: 04
    provides: "Halt-aware LiveTradingSystem (HALTED status, _dispatch_live gate) driven here"
provides:
  - "v1.6 operational store driven off the live composition root (RECON-04): sync-durable order working set via CachedSqlOrderStorage + live-driven CachedSqlSignalStorage, both over one SqlBackend"
  - "Split write paths by durability (D-10/D-11): order create/terminalize store-first (survives restart via rehydrate); signal store on the async/best-effort path (never inside a connector coroutine)"
  - "SYSTEM_DB_URL-unset loud in-memory fallback (WR-10) for BOTH order + signal stores; the operational SQL spine is disposed on stop() (no leaked socket)"
  - "BAR-keyed live per-bar equity curve (D-16/WR-01): LiveTradingSystem._record_bar_metrics keys on EventType.BAR with the bar-open business stamp; the old TIME key never fired under the BAR-only LiveBarFeed"
affects: [05-07, 05-08, restart-reconcile, live-drive, persistence]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Split write paths by durability (D-10/D-11): the sync-durable working set (order lifecycle) persists store-first (persist-then-acknowledge) via CachedSqlOrderStorage; derived/advisory state (signals, equity curve) rides the engine-thread async/best-effort path — never a sync Postgres write inside the connector asyncio coroutine (Pitfall 9)"
    - "Keep-only-measured write-through boundary: per-write store-first IS the boundary; no cross-method bracket transaction and no async buffering built (deferred until a live stall is profiled)"
    - "One shared SqlBackend built at the composition root and disposed on stop() — the CachedSql* stores compose it; an undisposed engine leaks a socket under filterwarnings=[error]"

key-files:
  created:
    - tests/integration/test_store_live_drive.py
    - tests/integration/test_live_bar_metrics.py
  modified:
    - itrader/trading_system/live_trading_system.py

key-decisions:
  - "Order working set constructed EXPLICITLY as CachedSqlOrderStorage(SqlOrderStorage(backend)) at the composition root (not via OrderStorageFactory.create('live')) so the store-first working-set wrapper is visible where the durability split is documented — functionally identical to the factory arm."
  - "The 'async/best-effort path' is realized structurally (keep-only-measured, D-10): signals/metrics persist on the ENGINE (queue-draining) thread, never inside a connector asyncio coroutine. No background writer thread / async buffer is built — that is deferred until a live stall is profiled, per RESEARCH Priority Resolution 5."
  - "The in-memory signal fallback uses SignalStorageFactory.create_in_memory() (not create('backtest')) so the stale unconditional backtest-signal wiring is provably removed (acceptance grep == 0) while preserving the WR-10 loud in-memory fallback."
  - "The metrics-record loop body was extracted into _record_bar_metrics so the D-16 BAR key is unit-testable without spinning the daemon thread; the loop calls the helper."

requirements-completed: [RECON-04]

# Metrics
duration: ~50min
completed: 2026-07-02
---

# Phase 05 Plan 06: Live Store Drive + BAR-Keyed Metrics Summary

**Drive the v1.6 operational store off the real feed at the live composition root (RECON-04) with write paths split by durability — order create/terminalize persists store-first via `CachedSqlOrderStorage` (sync-durable, survives a restart via `rehydrate()`), the signal store is live-driven (`CachedSqlSignalStorage`) on the engine-thread async/best-effort path so it can never stall the connector loop (D-10/D-11) — and record the live per-bar equity curve by re-keying `record_metrics` on `EventType.BAR` (the D-16/WR-01 fix, since `LiveBarFeed` emits only `BarEvent`), all without disturbing the byte-exact backtest path.**

## Performance
- **Tasks:** 2
- **Files modified:** 3 (2 created, 1 modified)

## Accomplishments
- **Task 1 — split write paths (D-10/D-11, RECON-04):** Completed the deferred live store wiring at the composition root. Restructured the `SYSTEM_DB_URL`-gated store block so one shared `SqlBackend` drives the whole v1.6 operational store: the sync-durable order working set is `CachedSqlOrderStorage(SqlOrderStorage(backend))` (store-first — order create/terminalize, rehydratable on restart), and the signal store is live-driven via `SignalStorageFactory.create('live', backend=backend)` → `CachedSqlSignalStorage` on the async/best-effort path (D-11 — advisory audit records, not the restart working set). All SQL imports stay lazy inside the `SYSTEM_DB_URL`-set arm (inertness gate intact). Unset `SYSTEM_DB_URL` falls back loudly to in-memory for BOTH stores (WR-10). The shared spine is now retained on `self._system_db_backend` and disposed in `stop()` (Rule 2 fix — an undisposed engine leaked a socket / ResourceWarning under `filterwarnings=["error"]`).
- **Task 2 — BAR-keyed live metrics (D-16/WR-01):** Re-keyed the live event-loop metrics record from `EventType.TIME` to `EventType.BAR`, extracted into `_record_bar_metrics(event)` which stamps each snapshot with the bar-open business time (`event.time`, never wall-clock) and iterates the active portfolios. `LiveBarFeed` emits only `BarEvent`, so the old TIME key never fired live and the equity curve was always empty (WR-01); it is now populated per bar. Kept on the async/best-effort path (D-10 — a lost tail is harmless). Backtest metrics path untouched → oracle byte-exact.

## Task Commits
1. **Task 1: split live store write paths — CachedSql sync working set + live signal store** — `58e24ea8` (feat)
2. **Task 2: BAR-keyed live metrics — record the equity curve** — `64b3e9d4` (feat)

## Files Created/Modified
- `itrader/trading_system/live_trading_system.py` (modified) — split-write-path store block (shared `SqlBackend`, explicit `CachedSqlOrderStorage`, live signal store, in-memory fallback, spine disposal on `stop()`); `_record_bar_metrics` helper + BAR-keyed loop call. 4-space indent; `mypy --strict` clean.
- `tests/integration/test_store_live_drive.py` (created, 4 tests) — order create/terminalize durable store-first + survives simulated restart via `rehydrate()`; signal store live-driven and its persist is off the connector coroutine (no running asyncio loop); the composition root wires `CachedSql*` when `SYSTEM_DB_URL` is set; unset → in-memory fallback, no crash. Testcontainers Postgres, skip-if-Dockerless (D-11).
- `tests/integration/test_live_bar_metrics.py` (created, 2 tests) — a `BarEvent` populates a non-empty per-bar equity curve with the bar-open stamp; a `TimeEvent` records nothing (recorder keys on BAR, not TIME).

## Decisions Made
- **Explicit `CachedSqlOrderStorage` at the composition root** rather than the factory arm — so the store-first working-set wrapper is visible exactly where the durability split is documented (functionally identical to `OrderStorageFactory.create('live', backend=...)`).
- **"Async/best-effort" realized structurally (keep-only-measured).** Per RESEARCH Priority Resolution 5, no background writer thread or async buffer is built. Signals/metrics persist on the engine (queue-draining) thread, never inside a connector asyncio coroutine — so they can never stall the loop (Pitfall 9). Async buffering is deferred until a live stall is profiled.
- **`create_in_memory()` for the signal fallback** so the stale unconditional `create('backtest')` wiring is provably removed (acceptance grep == 0) while keeping the WR-10 loud in-memory fallback.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing critical] Dispose the operational SQL spine on `stop()`**
- **Found during:** Task 1 (the composition-root wiring test constructs a full `LiveTradingSystem` with a real Postgres backend).
- **Issue:** The `SqlBackend` built in `__init__` was a local never retained/disposed (pre-existing since the original `else`-branch), so its connection pool leaked a socket at shutdown — a `ResourceWarning` under `filterwarnings=["error"]`.
- **Fix:** Retain the spine on `self._system_db_backend` (`None` on the in-memory fallback) and dispose it in `stop()`'s `finally` (runs on every return path). No leaked socket.
- **Files modified:** `itrader/trading_system/live_trading_system.py`
- **Committed in:** `58e24ea8`

### Scope resolution (not a code deviation)

**2. Portfolio-state store (`CachedSqlPortfolioStateStorage`) live-drive deferred — blocked by a missing injection seam.**
- **Found during:** Task 1. The plan action names wiring the portfolio-state store through `CachedSqlPortfolioStateStorage`, but the plan's `files_modified` lists only `live_trading_system.py` + the two test files.
- **Constraint:** `Portfolio._init_managers` hardcodes `PortfolioStateStorageFactory.create("backtest")`, and the live `CachedSqlPortfolioStateStorage` arm *requires a per-portfolio `portfolio_id`*. Portfolios are created dynamically via `PortfolioHandler.add_portfolio` (an app-layer concern), NOT at the `LiveTradingSystem` composition root — and `live_trading_system.py` never calls `add_portfolio`. Wiring it would require a new per-portfolio state-storage injection seam on `portfolio.py` / `portfolio_handler.py`, both OUT of the plan's declared files (a Rule-4 architectural change).
- **Resolution:** Delivered the in-scope sync-durable working set (order lifecycle via `CachedSqlOrderStorage` — the `rehydrate()`-backed restart precondition) and the live signal store, keeping the change within the declared single file. The per-portfolio state-store injection is a follow-on (mirrors 05-04's documented VenueAccount cash-settlement follow-on: the drift-compare read path landed there; live cash-settlement was deferred for the same reason). In live mode positions/cash are venue-truth (VenueAccount, 05-03/05-04) reconciled by drift compare, and the two-sided restart's venue side is the 05-05 reconcile work — so the position/cash restart path is not blocked by this deferral.

## Known Stubs / Follow-ons
- **Per-portfolio `CachedSqlPortfolioStateStorage` live-drive** — needs a state-storage injection seam on `Portfolio`/`PortfolioHandler` (each live portfolio's `portfolio_id` binds the SQL backend). Out of this plan's declared files; a follow-on for the persistence/restart work. Not exercised by any gate here.

## Verification Results
- `tests/integration/test_store_live_drive.py` — **4 passed** (testcontainers Postgres).
- `tests/integration/test_live_bar_metrics.py` — **2 passed**.
- `tests/integration/test_okx_inertness.py` — **1 passed** (backtest import path pulls no SQLAlchemy/OKX/ccxt).
- `tests/integration/test_backtest_oracle.py` — **3 passed** (byte-exact 134 / 46189.87730727451 — backtest metrics path untouched).
- Regression: `test_live_system_okx_wiring.py` (5) + `test_paper_parity.py` (1) + `test_live_paper_lifecycle.py` (3) + `test_live_bar_feed_route_order.py` (2) + `test_live_bar_feed_warmup.py` (6) — **all passed**.
- `mypy --strict itrader/trading_system/live_trading_system.py` — **Success: no issues found**.
- Acceptance greps (`live_trading_system.py`): `SignalStorageFactory.create('backtest')` = **0**; `SignalStorageFactory.create('live'` = **1**; `CachedSql` = **5**; `EventType.BAR` = **4**; no `EventType.TIME` in the metrics-record path.

## Threat Flags
None found — no new network endpoints, auth paths, or trust-boundary surface beyond the plan's `<threat_model>`. `SYSTEM_DB_URL` stays wrapped in `SecretStr` with no hardcoded credential fallback (T-05-19/WR-10 — unset → in-memory warning, not a leaked default); the sync-durable store is store-first so a cache bug can't corrupt the store (T-05-17); signals/metrics ride the engine-thread async/best-effort path, never a sync write inside the connector coroutine (T-05-18/Pitfall 9).

## Self-Check: PASSED
- `itrader/trading_system/live_trading_system.py` — FOUND
- `tests/integration/test_store_live_drive.py` — FOUND
- `tests/integration/test_live_bar_metrics.py` — FOUND
- Commit `58e24ea8` — FOUND
- Commit `64b3e9d4` — FOUND

---
*Phase: 05-real-sandbox-path-reconciliation-persistence-live-drive*
*Completed: 2026-07-02*

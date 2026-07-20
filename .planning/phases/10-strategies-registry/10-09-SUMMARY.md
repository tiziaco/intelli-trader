---
phase: 10-strategies-registry
plan: 09
subsystem: strategy-registry
tags: [testing, integration, live-trading, strategy-registry, phase-closer, D-22, D-21]
status: complete
requires:
  - "10-05: construction-time rehydrate gate (build_live_system × StrategyRegistryStore)"
  - "10-07: the add verb + warmup pipeline (spawn_warmup / on_bars_loaded)"
  - "10-08: reconfigure verb (goes dark + re-warm)"
provides:
  - "D-22 external-ingress lifecycle test (the FastAPI stand-in) — add_event → warm → trade → restart → resume"
  - "measured phase-wide validation sign-off (10-VALIDATION.md status: validated)"
affects:
  - "tests/integration/ (one new integration test file)"
tech-stack:
  added: []
  patterns:
    - "live-system integration test over the shared testcontainers Postgres spine (mirrors test_strategy_registry_restart)"
    - "external ingress driven via LiveTradingSystem.add_event with synchronous process_events drive (deterministic, no daemon thread)"
    - "route wiring through the production LiveRouteRegistrar (dispatch stays production-owned, not hand-written in the test)"
key-files:
  created:
    - "tests/integration/test_strategy_external_add_lifecycle.py (459 lines, 4 tests)"
  modified:
    - ".planning/phases/10-strategies-registry/10-VALIDATION.md (measured sign-off)"
decisions:
  - "D-22 implemented: the operator command surface is driven end-to-end through add_event (the only proof until FastAPI lands, LR-01)"
  - "D-21 implemented: an empty registry is the valid first-start state every lifecycle begins from"
  - "The restart-rehydrate gate is Postgres-only (build_live_system forces POSTGRESQL_PSYCOPG2 when a spine exists) — the plan's 'SQLite spine' premise was false; used pg_database_env"
metrics:
  duration: "~40 min"
  completed: "2026-07-17"
  tasks: 2
  files_created: 1
  files_modified: 1
  commits: 2
---

# Phase 10 Plan 09: Phase Closer — D-22 External Lifecycle + Measured Sign-Off Summary

Drove the P10 operator command surface end-to-end through the public `add_event` ingress
(the FastAPI stand-in) — add → dark → warm → trade → restart → resume, plus
disable/enable/reconfigure/remove — proving waves 1–8 COMPOSE, then swept every phase-wide
gate and recorded MEASURED reality in `10-VALIDATION.md`.

## What was built

**Task 1 — `tests/integration/test_strategy_external_add_lifecycle.py` (4 tests, all green):**

- **Test 1 (full D-22 lifecycle):** empty registry (D-21) → `add_event(StrategyCommandEvent.add(...))`
  → registered + persisted (`enabled=True`, `strategy_type` resolved) → DARK (WR-02) → `BarsLoaded`
  warms it → produces a signal on the next bar → **restart** over the SAME Postgres DB → rehydrates
  the same instance with matching params + portfolio subscriptions. The restart leg seeds NOTHING by
  hand — the only row is the one the `add` verb itself wrote (RESEARCH Item 2 / D-02).
- **Test 2 (admission is real):** a non-admissible `BarEvent` is denied by `add_event`, proving Test
  1's success came from the D-10 fail-closed `_EXTERNALLY_ADMISSIBLE` allowlist, not an open door.
- **Test 3 (verbs beyond add):** disable → enable → reconfigure all ride `add_event`; the reconfigured
  `max_positions` survives a restart (STRAT-02 + STRAT-03 through the same ingress).
- **Test 4 (D-11 remove):** remove via `add_event` drops the strategy; a restart rehydrates nothing.

Every verb goes through `add_event` (18 call sites); the test file never names the handler method
(`grep -c 'on_strategy_command' == 0`) — dispatch is wired by the production `LiveRouteRegistrar`.
No network (`grep -cE 'requests|httpx|ccxt\.' == 0`); offline replay + testcontainers Postgres only.

**Task 2 — measured phase-gate sign-off in `10-VALIDATION.md`:** every Per-Task Verification Map row
set to measured green, `status: validated`, `nyquist_compliant: true`, `wave_0_complete: true`, with a
recorded gate-results block.

## Measured gate results

| Gate | Result |
|------|--------|
| Full suite `poetry run pytest tests -q` | **2530 passed, 6 skipped, 0 warnings** (6 skips are OKX-credential-gated e2e/live) |
| Oracle `test_backtest_oracle.py` | **green — byte-exact 134 / 46189.87730727451** |
| Inertness `test_okx_inertness.py` | **green** |
| `poetry run mypy itrader` | **clean (244 source files)** |
| `policy_codec` / `strategy_handler.registry` under `ignore_errors` | **none** (grep pyproject == 0) |
| `live_trading_system.py` dead-import sweep (mypy blindspot) | **clean** — all P10 names consumed |
| Lazy-import spot-check (store/codec/rehydrate outside own pkgs) | **all function-body imports**, none barrel-exported |

**Lazy-import sites (checkable):** `live_trading_system.py:1602,1603,1621,1630,1644` (all inside the
`system_store is not None` rehydrate gate body); `strategies_handler.py:722` (`build_strategy`, method
body); `strategies_handler.py:1080` (`default_policy_registry`, method body). No module-top import, no
barrel re-export.

## Deviations from Plan

### Blocking / design deviations (Rule 3 — auto-resolved)

**1. [Rule 3 — Blocking] The rehydrate gate is Postgres-only; the plan's "SQLite spine" premise is false.**
- **Found during:** Task 1 harness design.
- **Issue:** The plan (and CONTEXT) said "build a live system against a SQLite spine." In fact
  `build_live_system` hardcodes `SqlSettings(driver=SqlDriver.POSTGRESQL_PSYCOPG2)` (live_trading_system.py:1364)
  whenever a spine exists; the credential probe only chooses between Postgres and an in-memory
  fallback (no rehydrate gate). There is NO SQLite path to the construction-time rehydrate gate.
- **Fix:** Built the lifecycle over the shared session **testcontainers Postgres** via the
  `pg_database_env` fixture — the exact substrate `test_strategy_registry_restart.py` uses. SKIPS
  Dockerless (D-11), consistent with the phase's other restart test. This is another confirmed instance
  of the phase pattern (every plan carried ≥1 false factual claim; the D-NN decisions held).

**2. [Rule 3 — Blocking] `add_event` requires `_running=True`; drove synchronously.**
- **Issue:** `add_event` returns False unless `self._running`. A full `start()` spins the daemon drain
  thread (async, non-deterministic) plus venue connect/reconcile.
- **Fix:** Flipped `_running=True` by hand WITHOUT spawning the drain thread, and drove
  `event_handler.process_events()` synchronously (the same reflex `TestRunner` uses). The allowlist,
  queue, route dispatch, and handler are ALL still in the assertion path — only the async executor
  wrapper is bypassed, which is not part of the D-22 path semantics.

**3. [Rule 3 — Design] Wired the STRATEGY_COMMAND route via the production `LiveRouteRegistrar`.**
- **Issue:** The default `STRATEGY_COMMAND` route is empty (`full_event_handler.py:108`, wired live-only
  in session init). Hand-writing `routes[STRATEGY_COMMAND] = [sh.on_strategy_command]` would trip the
  `grep -c 'on_strategy_command' == 0` criterion and put dispatch wiring in the test.
- **Fix:** Installed the real `LiveRouteRegistrar` (the same central declarative table
  `_initialize_live_session` installs) with the test's synthetic-symbol `universe_handler`. Dispatch
  stays production-owned; the test file references only `add_event`.

### Scope deviation (Rule 3)

**4. [Rule 3 — Scope] Test 4 drives the no-position remove-drop path, not a WITH-position force-flat.**
- **Issue:** Opening a real position needs the full signal→order→fill chain, which drags in the
  order/portfolio SQL persistence (`cash_reservations`, etc.) that registers lazily on a metadata the
  light `provision_schema` does not cover — fragile to provision in this harness.
- **Fix:** Removed a strategy that holds NO position, so the D-11 force-flat condition already holds and
  the instance drops on the same cycle. The WITH-position force-close is ALREADY proven end-to-end in
  `test_strategy_remove_flat.py`; this file's unique contribution — the external ingress + the
  restart-rehydrates-nothing — is fully exercised. Documented in the test docstring.

**5. [Rule 2 — Missing setup] Provisioned the full system schema after build.**
- With the Postgres spine, the live signal store is SQL-backed and the warmup→trade leg writes to a
  `signals` table. Added `provision_schema(system._system_db_backend)` right after build so the trade
  path's tables exist (checkfirst=True makes the restart-rebuild a clean no-op). The `strategy_registry`
  table is still provisioned pre-build via the seed-store handle so the rehydrate gate's `has_table`
  probe wires the durable store.

### Confirmed-false CONTEXT/plan claims (phase pattern)

- "SQLite spine" for `build_live_system` — FALSE (Postgres-only; deviation 1).
- The plan referenced `live_trading_system.py:1519-1570` for the gate; the gate as-built is at
  **1543–1648** (lines shifted as waves merged) — found by symbol, not line, per the audit note.

## Wave 0 completeness

All twelve Wave 0 files exist and are green (verified in the full-suite run); the shared
`tests/support/strategy_catalog.py` fixture exists. All Per-Task Map `-k` selectors resolve to
non-empty test sets (spot-checked: `-k empty` → 2/18, `-k decimal` → 3/16, etc.).

## Manual-Only (pending by design)

The A1 `SELECT count(*)` DB-state check stays PENDING — no automated run in this repo can inspect a
deployed DB, and Plan 02's migration guard fails loud on a wrong assumption rather than destroying
data. It is a pre-deploy operator step, not a merge blocker (noted in `10-VALIDATION.md`).

## Notes for the orchestrator

- STATE.md / ROADMAP.md were NOT modified (owned by the wave orchestrator).
- Two per-task commits (`98ec8094` test, `9a3130df` docs) on the worktree branch.

## Self-Check: PASSED

- `tests/integration/test_strategy_external_add_lifecycle.py` — FOUND
- `.planning/phases/10-strategies-registry/10-09-SUMMARY.md` — FOUND
- Commit `98ec8094` (test) — FOUND
- Commit `9a3130df` (docs) — FOUND

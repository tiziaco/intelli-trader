---
phase: 05-real-sandbox-path-reconciliation-persistence-live-drive
plan: 07
subsystem: reconciliation
tags: [two-sided-restart, venue-reconcile, reconciling-events, brackets, restart-relink, venue-order-id, RECON-05, D-03, D-05]

# Dependency graph
requires:
  - phase: 05-real-sandbox-path-reconciliation-persistence-live-drive
    plan: 03
    provides: "VenueAccount cached-venue body — snapshot()/positions (venue balance/position truth on restart)"
  - phase: 05-real-sandbox-path-reconciliation-persistence-live-drive
    plan: 05
    provides: "Idempotent, partial-aware fill path (fill-ID dedup + cumulative-filled accumulation) the reconciling events drive through"
  - phase: 05-real-sandbox-path-reconciliation-persistence-live-drive
    plan: 06
    provides: "CachedSqlOrderStorage live-drive + rehydrate() (the store-side INTENT working set) at the live composition root"
provides:
  - "Two-sided restart rehydration (D-03): VenueReconciler.reconcile() rehydrates the store working set (INTENT) AND reconciles it against the venue REST snapshot (balances/positions/fills) BEFORE status=RUNNING"
  - "In-band fill-delta adoption as reconciling FillEvents (last_qty = venue_filled - order.filled) driven through the SAME idempotent fill path — adopt-once by delta recomputation, never mutating portfolio state directly"
  - "Halt-and-alert (reconciliation-unresolved) on a venue position with no stored intent, and a per-bracket halt on a leg that cannot be confidently re-linked"
  - "Persisted nullable venue_order_id on the order mirror (Order entity + orders table + Alembic migration) so a bracket leg re-links venue-id-first across a restart (Open Question 3 resolution)"
affects: [restart-reconcile, live-drive, order-mirror, brackets, RECON-05, RECON-06]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Reconciling-event generation (D-03 restart): concept-ported from nautilus create_inferred_order_filled_event (NEVER imported) — mint via FillEvent.new_fill(EXECUTED, ...) and global_queue.put on the engine thread before RUNNING; idempotent by delta recomputation off the persisted filled_quantity"
    - "Authority split (D-03): the store owns INTENT (which orders exist); the venue owns balances/positions/fills — a venue position with no stored intent halts (never auto-adopts), an in-band delta is adopted"
    - "Bracket re-link match predicate (D-05): venue_order_id-first (exact id equality — the confident path) then symbol+side+price+qty fallback (one-least-unit tolerance via drift.is_within_single_unit_tolerance); zero-or-ambiguous fallback → per-bracket halt, never a guess"
    - "venue_order_id population path: the reconciler stamps venue_order_id onto a leg confidently matched via the attribute fallback and persists it, so a subsequent restart re-links by id (Open Question 3)"
    - "Backtest-inertness: venue_reconciler.py is lazy-imported at the OKX live composition root only; LiveConnector/VenueAccount/CachedSqlOrderStorage are TYPE_CHECKING-only"

key-files:
  created:
    - itrader/portfolio_handler/reconcile/venue_reconciler.py
    - itrader/storage/migrations/versions/p05_venue_order_id.py
    - tests/integration/test_two_sided_restart.py
    - tests/integration/test_bracket_restart_relink.py
  modified:
    - itrader/order_handler/order.py
    - itrader/order_handler/storage/models.py
    - itrader/order_handler/storage/sql_storage.py
    - itrader/trading_system/live_trading_system.py

key-decisions:
  - "venue_order_id persisted as a nullable String column with an Alembic migration chained onto head 47f2b41f3ffe — nullable keeps backtest/paper orders byte-exact (oracle-dark) and round-tripping through both create_all (test path) and Alembic (deploy path)."
  - "The reconciling-event idempotency is by DELTA RECOMPUTATION (venue_filled − persisted order.filled), not a fill-ID cache: a second restart re-reads the now-updated persisted filled and computes a zero delta, so no reconciling FillEvent is re-emitted (adopt-once). The 05-05 fill-ID dedup covers the concurrent live-stream double-send; the two mechanisms are complementary."
  - "reconcile() is self-contained (it calls venue_account.snapshot() itself) so it is testable without going through start(); start() already snapshots to seed the cache before streaming, so the reconcile-time snapshot is a documented, idempotent second REST read (the snapshot is authoritative)."
  - "Orphan-position intent coverage keys on order.ticker across the WHOLE rehydrated working set (active orders + resident bracket parents), so a FILLED entry parent held resident by its live protective leg still explains its venue position — no false orphan halt."
  - "The venue_order_id-first match is the CONFIDENT bracket path; the attribute fallback is confident ONLY when exactly one candidate matches (zero or >1 → per-bracket halt), so a mis-linked protective leg is never guessed (T-05-22)."

requirements-completed: [RECON-05]

# Metrics
duration: ~45min
completed: 2026-07-02
---

# Phase 5 Plan 07: Two-Sided Restart Rehydration (RECON-05/D-03/D-05) Summary

**Restart rehydration is now two-sided: on startup, before RUNNING, `VenueReconciler.reconcile()` rehydrates the store working set (INTENT truth) AND reconciles it against the venue REST snapshot (balance/position/fill truth) — adopting each in-band fill delta as a reconciling `FillEvent` driven through the SAME idempotent fill path (adopt-once by delta recomputation, never mutating state directly), halting-and-alerting on a venue position with no stored intent, and re-linking bracket legs venue-id-first (per-bracket halt on an unconfident leg) — with the venue order id now persisted on the order mirror so legs re-link confidently across a restart.**

## Performance
- **Duration:** ~45 min
- **Completed:** 2026-07-02
- **Tasks:** 3
- **Files modified:** 8 (4 created, 4 modified)

## Accomplishments
- **Task 1 — persist the venue order id (Open Question 3).** Added a nullable `venue_order_id: Optional[str] = None` to the `Order` entity (TABS), a matching nullable `venue_order_id` String column to the `orders` table (`models.py`, 4-space), the row-codec round-trip in `sql_storage.py` (`_order_to_row` / `_row_to_order`), and an Alembic migration `p05_venue_order_id.py` chained onto head `47f2b41f3ffe` (batch add-column up / drop-column down). Nullable keeps backtest/paper orders byte-exact and round-trips through both `create_all` (test path) and Alembic (deploy path).
- **Task 2 — VenueReconciler + reconciling events (D-03).** Created `portfolio_handler/reconcile/venue_reconciler.py` (4-space, `mypy --strict` clean): `reconcile()` runs on the engine thread before RUNNING — (1) `store.rehydrate()` reconstructs the INTENT working set (active orders + resident bracket parents); (2) `venue_account.snapshot()` + `fetch_my_trades` take the venue truth; (3) each stored order whose `venue_order_id` maps to venue trades adopts the positive `venue_filled − order.filled` delta as an EXECUTED reconciling `FillEvent` (`FillEvent.new_fill`, business time from the venue trade ts) `put` on `global_queue` — driven through the idempotent fill path, never a direct state mutation; (4) a venue position with no stored intent calls the 05-04 halt entrypoint (`reconciliation-unresolved`). Invoked at the OKX live composition root before RUNNING (lazy import — inertness preserved), guarded on the store exposing `rehydrate()`.
- **Task 3 — bracket re-link + per-bracket halt (D-05).** Extended `VenueReconciler` with `_relink_brackets`: for each rehydrated bracket parent, re-link its still-resting legs against `fetch_open_orders` — `venue_order_id`-first (exact id equality, the confident path), then symbol+side+price+qty fallback (one-least-unit tolerance via `drift.is_within_single_unit_tolerance`, confident only when exactly one candidate matches). A confident re-link stamps `venue_order_id` onto the leg and persists it (the Open Question 3 population path) and resumes OCO; an unconfident leg escalates THAT bracket to `reconciliation-unresolved` — a per-bracket halt, never a guess.

## Task Commits
1. **Task 1: persist venue_order_id on the order mirror (Open Question 3)** — `bdf68a71` (feat)
2. **Task 2: VenueReconciler — venue-side restart reconcile + reconciling events (D-03)** — `6a9e3f56` (feat)
3. **Task 3: bracket parent/child re-link + per-bracket halt (D-05)** — `4b244b09` (feat)

## Files Created/Modified
- `itrader/portfolio_handler/reconcile/venue_reconciler.py` (created, ~330 lines) — `VenueReconciler`: `reconcile()` orchestration, `_working_set`, fill-delta adoption (`_adopt_fill_deltas` / `_aggregate` / `_emit_reconciling_fill` / `_venue_ts_to_dt`), orphan-position halt (`_halt_on_orphan_positions`), bracket re-link (`_relink_brackets` / `_relink_bracket` / `_match_leg` / `_leg_attributes_match`), venue REST helper (`_fetch`). `mypy --strict` clean. `venue_order_id` appears 7×.
- `itrader/storage/migrations/versions/p05_venue_order_id.py` (created) — Alembic migration, `down_revision="47f2b41f3ffe"`, batch add/drop of the nullable `venue_order_id` column.
- `tests/integration/test_two_sided_restart.py` (created, 3 tests) — testcontainers PG + `fake_venue_connector`: agree → no halt / no phantom fill; downtime fill → adopted once (idempotent on re-run); orphan position → halt.
- `tests/integration/test_bracket_restart_relink.py` (created, 2 tests) — venue-id re-link resumes OCO (no halt); unconfident leg → per-bracket halt.
- `itrader/order_handler/order.py` (modified, TABS) — nullable `venue_order_id` field on the `Order` entity.
- `itrader/order_handler/storage/models.py` (modified, 4-space) — nullable `venue_order_id` column on the `orders` table.
- `itrader/order_handler/storage/sql_storage.py` (modified, 4-space) — `venue_order_id` in `_order_to_row` / `_row_to_order`.
- `itrader/trading_system/live_trading_system.py` (modified, 4-space) — retain `self._order_storage`; invoke `VenueReconciler.reconcile()` at the OKX arm before RUNNING (lazy import, `rehydrate()`-guarded).

## Decisions Made
See frontmatter `key-decisions` — the load-bearing ones: nullable persisted `venue_order_id` (byte-exact); idempotency by delta recomputation (not a fill-ID cache); reconcile() self-snapshots (testable, idempotent); orphan coverage across active + resident parents; confident-only bracket match (per-bracket halt otherwise).

## Deviations from Plan
None — plan executed as written. The three Rules 1–3 auto-fixes were not required; the only in-flight correction was a `mypy --strict` narrowing fix inside Task 2 (assign `trade.get("fee")` to a local before the `isinstance` guard so the `dict.get` narrows) — a typing hygiene fix within the same task's file, folded into the Task-2 commit, not a behavioral deviation.

## Verification Results
- `poetry run pytest tests/integration/test_two_sided_restart.py -x` → **3 passed** (agree / downtime-fill-adopted-once / orphan-halt).
- `poetry run pytest tests/integration/test_bracket_restart_relink.py -x` → **2 passed** (venue-id re-link resumes OCO / unconfident leg → per-bracket halt).
- `poetry run pytest tests/unit/order -x -q` → **260 passed** (venue_order_id round-trips; existing order tests unaffected).
- `poetry run pytest tests/integration/storage/test_migrations.py tests/integration/storage/test_sql_order_storage.py tests/integration/storage/test_cached_sql_order_storage.py` → **18 passed** — the migration applies + reverts cleanly against testcontainers Postgres AND autogenerate stays diff-free (the models.py column matches the migration chain).
- `poetry run pytest tests/integration/test_backtest_oracle.py -x` → **3 passed** (byte-exact: 134 / 46189.87730727451 — venue_order_id nullable/None on backtest).
- `poetry run pytest tests/integration/test_okx_inertness.py -x` → **1 passed** (backtest import path pulls no OKX/async/SQL; venue_reconciler lazy-imported at the OKX arm only).
- `poetry run mypy --strict itrader/portfolio_handler/reconcile/venue_reconciler.py itrader/order_handler/order.py itrader/order_handler/storage/models.py itrader/order_handler/storage/sql_storage.py` → **Success: no issues found**.
- Regression: `tests/unit/portfolio tests/unit/execution` → **508 passed**.
- Acceptance greps: `def reconcile` = 1; `grep -L 'import nautilus_trader' venue_reconciler.py` lists the file (no nautilus runtime import); `reconcile` in `live_trading_system.py` = 7 (≥1, invoked before RUNNING); `venue_order_id` in `order.py` ≥ 1, in `models.py` ≥ 1, in `venue_reconciler.py` = 7 (venue-id-first match); `p05_venue_order_id` is the single Alembic head, history linear onto `47f2b41f3ffe`.

## Known Stubs
None — no hardcoded/placeholder values, no unwired data sources. The reconciler is fully implemented and exercised end-to-end (store rehydrate → venue snapshot → reconciling events / halt / bracket re-link) against real testcontainers Postgres + the credential-free FakeLiveConnector.

## Threat Flags
None beyond the plan's `<threat_model>`. The four registered threats are mitigated as designed: T-05-20 (double-apply) — reconciling events drive the idempotent fill path and idempotency is by delta recomputation; T-05-21 (silent adopt of a hand-opened position) — a venue position with no stored intent halts-and-alerts, never auto-adopts; T-05-22 (mis-linked bracket leg) — venue-id-first match, ambiguous/absent fallback → per-bracket halt, never a guess; T-05-23 (store integrity) — the working set is rehydrated store-first, the venue is truth for balances/positions/fills (D-03 authority split). No new network endpoint, auth path, or schema surface at a trust boundary beyond the declared nullable `venue_order_id` column.

## Self-Check
- `itrader/portfolio_handler/reconcile/venue_reconciler.py` — FOUND
- `itrader/storage/migrations/versions/p05_venue_order_id.py` — FOUND
- `tests/integration/test_two_sided_restart.py` — FOUND
- `tests/integration/test_bracket_restart_relink.py` — FOUND
- Commit `bdf68a71` — FOUND
- Commit `6a9e3f56` — FOUND
- Commit `4b244b09` — FOUND

## Self-Check: PASSED

---
*Phase: 05-real-sandbox-path-reconciliation-persistence-live-drive*
*Completed: 2026-07-02*

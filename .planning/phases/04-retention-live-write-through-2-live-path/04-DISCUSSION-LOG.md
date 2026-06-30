# Phase 4: Retention + Live Write-Through (#2 — live path) - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-06-30
**Phase:** 4-Retention + Live Write-Through (#2 — live path)
**Areas discussed:** Live-path scope, Terminal-record retention, Restart rehydration, Cache-layer topology + naming

---

## Live-path scope — how far without a real feed

| Option | Description | Selected |
|--------|-------------|----------|
| Close all 3 seams, synthetic-event driver | Wire SQL backends into all three live seams; drive the full retention loop via synthetic events through the daemon queue | |
| Order + portfolio only, defer signal | Wire order mirror + portfolio state; leave signal on in-memory | |
| Build cache machinery, defer live wiring | Build + integration-test the retention components against testcontainers; don't rewire LiveTradingSystem | ✓ |

**User's choice:** Option 3 — build machinery + integration-test on testcontainers, **with the refinement** (agreed in clarification) that we still point each factory's `'live'` arm at the new wrapper (so the order seam, which `LiveTradingSystem` already routes to `create('live')`, is exercised end-to-end), while NOT rewiring `LiveTradingSystem`'s composition (`portfolio.py:93`, `live_trading_system.py:113`) or building a synthetic end-to-end event driver.
**Notes:** Recommendation aligned with the choice — every Phase-4 success criterion (SC2/SC3) is a component-level test against real Postgres; full-loop-through-`LiveTradingSystem` validation needs the real feed = N+4. Avoids risky surgery on `Portfolio.__init__`'s self-created storage + throwaway scaffolding.

---

## Terminal-record retention policy

| Option | Description | Selected |
|--------|-------------|----------|
| Immediate purge + read-through | Evict on terminalize-commit; serve later terminal queries via read-through to Postgres; no buffer, no sweep timer | ✓ |
| Nautilus-style buffer window | Keep terminal records resident for a bounded recent-N/recent-T window + age/count safety sweep | |
| Let research decide | Lock the terminal-state gate + read-through, defer immediate-vs-buffered | |

**User's choice:** Immediate purge + read-through.
**Notes:** Simplest, tightest memory bound, zero tuning knobs; reconciliation buffering becomes N+4's concern when actually needed. The mandatory terminal-state gate is kept: never evict an open record; bracket parent resident until all children terminalize.

---

## Restart rehydration — snapshot + accumulators

| Option | Description | Selected |
|--------|-------------|----------|
| Periodic snapshot row + load-latest | Persist account snapshot at a cadence; on restart load latest snapshot row + open positions/working orders | ✓ |
| Recompute accumulators from open positions | Recompute snapshot/accumulators from open positions + minimal scalars | |
| Let research decide | Lock open-only/no-history-replay, defer cadence + recompute-vs-load | |

**User's choice:** Option 1 — periodic snapshot row + load-latest.
**Notes:** User confirmed (clarification) that open positions always load from the store regardless — the snapshot row is the *additional* piece for the account aggregate + accumulators that depend on purged closed-trade history. Locked refinement: the **accumulator scalars ride the synchronous write-through txn** (not a per-bar-only cadence) so the latest persisted account state is never behind the working set after a crash — keeps SC3's "rehydrated == pre-crash" exact under immediate-purge. Per-TIME-bar `equity_snapshots` rows remain the historical curve. Never replay terminal history; load open-only.

---

## Cache-layer topology + naming

| Option | Description | Selected |
|--------|-------------|----------|
| Wrapper-per-concern decorator | New live-only class per concern composing in-memory working set + Phase-3 SqlStorage, same ABC; factory `'live'` arm returns it | ✓ |
| Build into the Sql*Storage classes | Add cache/write-through/purge/read-through inside the Phase-3 SQL classes | |
| Let research/planner decide | Lock behavior + composition rule, defer topology | |

**User's choice:** Option 1 — wrapper-per-concern decorator.
**Notes:** Keeps the Phase-3 `Sql*Storage` as a pure, gate-passed persistence layer; isolates all new/risky behavior in a separate composed layer (a cache bug can't compromise the store). Composition-not-inheritance.
**Naming:** User considered `LiveOrderStorage` (recommended), `WriteThroughOrderStorage`, `CachedSqlOrderStorage`, `BufferedOrderStorage`; rejected anything with "WorkingSet". **Locked: `CachedSqlOrderStorage` / `CachedSqlPortfolioStateStorage` / `CachedSqlSignalStorage`** — the `InMemory` / `Sql` / `CachedSql` per-concern triple.

---

## Claude's Discretion

- Internal working-set data structure inside the wrapper (reuse `InMemory*Storage` vs purpose-built).
- Exact rehydration query surface / boot sequence; which accumulator scalars ride the txn vs recompute.
- Per-write-point transaction-boundary mechanics; one-txn vs store-first for atomic multi-row writes.
- Daemon-thread vs API-thread read-through/status-query interaction (research-flagged).
- Whether `CachedSql*Storage` enters `mypy --strict` scope now or stays deferred.
- Plan-time research is flagged (`--research-phase`) for the novel surfaces (write-through txn boundary,
  bracket-parent safety, read-through scope, rehydration query surface, daemon/API-thread interaction).

## Deferred Ideas

- Rewiring the live composition root (`portfolio.py:93`, `live_trading_system.py:113`) for portfolio +
  signal — N+4.
- Synthetic end-to-end event driver through the daemon loop — N+4.
- Real live feed + venue reconciliation — N+4.
- Reconciliation buffer window + age/count sweep for terminal records — N+4.
- Async batch write-through for append-heavy non-durability-critical writes — only if profiling justifies.

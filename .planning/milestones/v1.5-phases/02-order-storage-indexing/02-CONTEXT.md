# Phase 2: Order-Storage Indexing - Context

**Gathered:** 2026-06-23
**Status:** Ready for planning

<domain>
## Phase Boundary

Phase 2 adds **derived secondary indexes** over the flat `{id: order}` dict in
`InMemoryOrderStorage` so the per-bar / per-fill hot path stops linear-scanning **all orders ever
created** — removing the single largest W1 hotspot (`_orders` + `get_orders_by_status`, ~37% CPU,
PERF-01). The flat dict stays the **sole source of truth (D-20)**; the indexes are caches kept
consistent over it. The `OrderStorage` interface stays designed for extension so a future Postgres
backend satisfies the same contract.

**In scope:**
- A dedicated `active_by_portfolio` index + an active-only `by_status` index, maintained over the
  flat dict in `InMemoryOrderStorage` (D-01, D-02, D-06).
- Index consistency on every insert / status-transition / terminal write via a shadow-key registry
  inside the storage class (D-03).
- Rerouting the existing active-set scanners (`get_pending_orders`, `remove_orders_by_ticker`,
  `clear_portfolio_orders`) through the active index (D-07).
- Insertion-order preservation so query output stays byte-identical (D-08) + an order-equivalence
  regression test (D-09).

**Out of scope (behavior-preserving milestone — changes NO numbers):**
- Indexing cold/audit queries (`get_orders_by_time_range`, `search_orders`, `get_order_history`)
  and terminal-status queries — they keep scanning the flat dict (D-01, D-10).
- Any actual PostgreSQL storage code — deferred to the **N+3b Persistence** milestone (PERSIST-01).
  This phase only audits/documents that the seam *could* host it (D-05).
- Any money / float / Decimal change, any oracle re-baseline (this is the perf analog of v1.2
  Consolidation).

**Gate (inherited, every wave):**
- **Gate (a):** byte-exact SMA_MACD oracle green (134 trades / `final_equity 46189.87730727451`);
  `mypy --strict` clean; determinism double-run byte-identical.
- **Gate (b):** clean W1 benchmark shows ≥5% wall-clock improvement (D-04, single timed run) vs the
  Phase 1 re-frozen baseline; re-freeze as the new locked reference. Peak memory tracked alongside.

</domain>

<decisions>
## Implementation Decisions

### Index set & granularity
- **D-01 (index scope = hot queries only):** Index only what the per-bar / per-fill path hits —
  active-orders-by-portfolio and active-status. Cold/audit queries
  (`get_orders_by_time_range`, `search_orders`, `get_order_history`) keep scanning the flat dict;
  they are not on the measured hot path.
- **D-02 (index shape = "Option A", nested-by-portfolio):** Maintain two derived structures over the
  flat dict:
  - `active_by_portfolio: {portfolio_id: <ordered set of order_id>}` — serves the **dominant**
    `get_active_orders(portfolio_id)` as a single direct lookup (O(active-in-portfolio), not
    O(all-orders-ever)). `get_active_orders(None)` = union of all portfolios' active sets.
  - `by_status: {status: <ordered set of order_id>}` — serves `get_orders_by_status`.
  - **Rationale:** the profiler's hot query is active-by-portfolio (reconcile per fill,
    lifecycle run-end sweep); a dedicated active set makes it one lookup with no union/filter.
    Option B (composite `(portfolio_id, status)`) was considered and rejected — it adds a 2-set
    union tax on the one query run most, and its only advantage (O(result) terminal-status queries)
    is off the hot path. Both shapes clear the ≥5% gate; Option A is fastest on the profiled query
    and simplest to keep consistent.

### Consistency mechanism (correctness-critical)
- **D-03 (shadow-key registry):** Because orders mutate status **in place** (`order.status = …` in
  `order.py:441`) and `update_order(order)` is called *after* the mutation — so the stored object
  already shows the new status — `InMemoryOrderStorage` keeps a private
  `{order_id: last_indexed_status}` registry (portfolio_id is immutable, read off the order).
  `add_order` / `update_order` / `remove_order` diff old→new and patch the affected buckets, then
  refresh the registry. Fully encapsulated; **no `Order` entity change, no caller change.** Rejected:
  a transition-aware write API (leaks index concerns into the order domain / every transition site).
- **D-04 (invariant by audit + test, not runtime guard):** Index correctness depends on the
  invariant "every `order.status` mutation is followed by `storage.update_order(order)`" (today:
  reconcile + lifecycle honor it). Planning/research **audits every mutation site**, locks the
  invariant in writing, and relies on the oracle + determinism double-run to catch drift. **No
  hot-path runtime consistency guard** (it would burn the cycles this phase is trying to save).

### Postgres-extensible seam
- **D-05 (indexes private to InMemory; ABC unchanged):** Keep `OrderStorage` (ABC) query-shaped —
  its methods (`get_active_orders`, `get_orders_by_status`, …) already express intent. The indexes
  are an **internal cache of `InMemoryOrderStorage` only**. A future `PostgreSQLOrderStorage`
  implements the same methods via native SQL indexes / `WHERE` clauses. **No interface change.**
  Rejected: putting `ensure_index`/`rebuild` hooks on the base class (leaks an in-memory caching
  concern onto a backend that manages its own indexes).
- **D-05a (no-leak via audit + document):** Satisfy success-criterion #3 by auditing each interface
  method (return types, the `get_pending_orders` nested-dict shape, the `IdLike` union, any ordering
  guarantee) and confirming it is expressible by a SQL backend — document anything that isn't. **No
  Postgres code written this phase** (that's PERSIST-01, deferred). Rejected: drafting a Postgres
  conformance test now (overlaps the deferred milestone).

### Result-order / determinism
- **D-06 / D-08 (insertion-ordered buckets):** Back each index bucket with an **insertion-ordered**
  structure (e.g. `dict[order_id, None]`), NOT a plain `set` (hash-ordered). Query results then come
  out in the same order as today's flat-dict scan — **byte-identical by construction**,
  determinism-safe, no per-query sort. Protects gate (a). Rejected: plain sets + sort-at-query
  (changes order vs today, adds sort cost) and plain sets accepting hash order (fragile, changes
  output).
- **D-09 (order-equivalence regression test):** Add a targeted test asserting index-backed query
  order == prior full-scan order, as an explicit lock against future drift — on top of the oracle /
  determinism / e2e gate.

### by_status coverage
- **D-10 (active statuses only):** `by_status` indexes only the active statuses
  (`PENDING` / `PARTIALLY_FILLED`); an order is **dropped** from `by_status` when it goes terminal.
  Terminal-status queries (`get_orders_by_status(FILLED/REJECTED/CANCELLED/…)`) fall back to scanning
  the flat dict. **Evidence:** non-active-status queries have NO production caller — `get_orders_by_status`
  is reached only through the public facade (external/API/reporting); the only callers passing terminal
  statuses are unit tests. Indexing terminal statuses therefore yields **0% measurable speedup** (no
  hot caller) while costing **unbounded memory** (terminal buckets grow with run length under D-20).

### Scanner rerouting
- **D-07 (reroute all three active-set scanners):** `get_pending_orders` (nested-dict builder),
  `remove_orders_by_ticker`, and `clear_portfolio_orders` all currently scan to find active orders;
  reroute each to derive its working set from `active_by_portfolio` (then apply the ticker filter
  where needed). They already filter on `is_active`, so it's a drop-in — routes **all** active reads
  through one index and removes more full scans.

### Memory posture
- **D-11 (accept added memory; gate is wall-clock):** Per D-04 (Phase 1), pass on **≥5% wall-clock**
  improvement; peak memory is tracked alongside and watched for material regression, but there is
  **no hard memory ceiling** for this phase. Active-only indexing (D-10) keeps the footprint small.

### Claude's Discretion
- Exact names/types of the index attributes and the shadow registry; the precise ordered-set
  representation (`dict[id, None]` vs an ordered-dict wrapper); how `get_active_orders(None)` unions
  the per-portfolio sets — all left to planning, within D-02 / D-06 / D-08.
- Whether the audit of the "mutation → update_order" invariant (D-04) yields any defensive assert in
  non-hot paths (e.g. test-only helpers) — planner's call; the contract (audited + tested) is what
  matters.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Source of truth (the spike IS the research)
- `perf/results/PERF-BASELINE-RESULTS.md` §1 (frozen baseline 240.8 s / 167.3 MB), §2 (ranked
  hotspot map — **hotspot #1 is this phase's target**), §6 (phase breakdown), §7 (exit criteria).
  **Authoritative.**

### Milestone scope + requirements + gate
- `.planning/REQUIREMENTS.md` — **PERF-01** (this phase) + the milestone gate (a)/(b) definition.
- `.planning/milestones/v1.5-ROADMAP.md` — Phase 2 goal + success criteria.
- `.planning/ROADMAP.md` — Phase 2 entry + v1.5 framing.
- `.planning/phases/01-perf-tooling-baseline/01-CONTEXT.md` — **D-04** (≥5% wall-clock,
  single-run) and the baseline/regression-guard tooling Phase 2's gate (b) uses.

### Target code (the seam being optimized)
- `itrader/order_handler/storage/in_memory_storage.py` — `InMemoryOrderStorage`; the flat-dict
  `_orders` generator + all query methods. **The file this phase edits.**
- `itrader/order_handler/base.py` — `OrderStorage` ABC (stays unchanged, D-05) + the `IdLike` union.
- `itrader/order_handler/order.py` — in-place status mutation (`order.status =` ~line 441,
  `_is_valid_transition`, `VALID_ORDER_TRANSITIONS`) — the reason for the shadow registry (D-03).

### Hot-path callers (the consumers whose order/behavior must not change)
- `itrader/order_handler/reconcile/reconcile_manager.py` (~line 319) — `get_active_orders` per fill,
  + `update_order` after each transition (~267).
- `itrader/order_handler/lifecycle/lifecycle_manager.py` (~line 253) — run-end active sweep,
  + `update_order` after transitions (~116, ~179).

### Gate (a) — correctness lock (held, not changed)
- `tests/integration/test_backtest_oracle.py` — byte-exact SMA_MACD oracle
  (134 / `46189.87730727451`).
- `tests/unit/order/test_order_storage.py` — existing storage behavior tests (incl. the
  terminal-status `get_orders_by_status` callers cited in D-10); the order-equivalence test (D-09)
  lands alongside.

### Future-milestone reference (NOT built here)
- `itrader/order_handler/storage/postgresql_storage.py` — `NotImplementedError` placeholder; the
  D-05/D-05a seam audit targets this backend's future contract (PERSIST-01, deferred to N+3b).

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- The write seams (`add_order`, `update_order`, `remove_order`, `remove_orders_by_ticker`,
  `clear_portfolio_orders`) are already the *only* mutation entry points — the shadow registry +
  index maintenance hook cleanly into exactly these methods (D-03).
- `order.is_active` already encodes the active predicate (PENDING / PARTIALLY_FILLED) — the
  active index just caches membership; no new predicate logic.
- `portfolio_id` is immutable per order, so the registry only needs to track the mutable key
  (status) — simplifies the diff (D-03).

### Established Patterns
- The flat-dict-only design + D-20 source-of-truth contract is already documented in the
  `InMemoryOrderStorage` docstring — index maintenance must *preserve* it (caches, never a second
  source of truth).
- Indentation: `order_handler/` modules use **tabs**; `in_memory_storage.py` itself uses **4 spaces**
  (it imports from `..base`). Match each file exactly — do not normalize.
- Existing queries return `List[Order]` in flat-dict insertion order; `get_pending_orders` returns a
  derived nested `{pid: {id: order}}` shape (return-shape convenience, not stored).

### Integration Points
- New index state lives entirely inside `InMemoryOrderStorage.__init__` (alongside `self._by_id`).
- No event-queue, handler, or `OrderStorage` ABC changes — the optimization is contained to one
  class (D-05); callers see identical method signatures and identical (insertion-ordered) output.

</code_context>

<specifics>
## Specific Ideas

- Index shape chosen explicitly as "Option A" (dedicated `active_by_portfolio` set + `by_status`
  map) over the composite `(portfolio_id, status)` alternative — see D-02 rationale.
- `by_status` is **active-only** with terminal orders dropped on transition — see D-10 (backed by a
  grep showing no production hot caller of terminal-status queries).
- Insertion-ordered buckets specifically to keep output byte-identical (D-08), not merely
  deterministic — the byte-exact oracle is the lock.

</specifics>

<deferred>
## Deferred Ideas

- **Composite `(portfolio_id, status)` index (Option B)** — rejected for this phase (D-02). Revisit
  only if a future *hot* consumer of terminal-status or arbitrary (portfolio, status) queries
  appears (e.g. on the live path).
- **Indexing terminal statuses / cold queries** (time-range, search, history) — deferred (D-01,
  D-10); no hot caller justifies the memory cost today.
- **Actual PostgreSQL order storage (PERSIST-01)** — the whole point of the D-05/D-05a seam audit,
  but built in the **N+3b Persistence** milestone, not here.

</deferred>

---

*Phase: 2-order-storage-indexing*
*Context gathered: 2026-06-23*

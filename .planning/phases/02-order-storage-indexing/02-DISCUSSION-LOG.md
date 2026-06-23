# Phase 2: Order-Storage Indexing - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-06-23
**Phase:** 2-order-storage-indexing
**Areas discussed:** Index set & granularity, Consistency mechanism, Postgres-extensible seam, Result-order / determinism, by_status coverage, Reroute active scanners, Memory posture

---

## Index set & granularity

### Index scope
| Option | Description | Selected |
|--------|-------------|----------|
| Hot queries only | Index active-orders-by-portfolio + by-status; cold/audit queries scan | ✓ |
| Hot + by-ticker | Also index ticker for get/remove_orders_by_ticker | |
| Full coverage | Index every list-returning query | |

### Index shape
| Option | Description | Selected |
|--------|-------------|----------|
| Nested by portfolio (A) | Dedicated active_by_portfolio set (single lookup for dominant query) + by_status map | ✓ |
| Composite key (B) | Index keyed on (portfolio_id, status) tuples | |
| You decide | Lock requirement, let planning pick | |

**User's choice:** Hot queries only + Option A.
**Notes:** User asked which shape gives best performance. Analysis: the profiled hot query is
`get_active_orders(portfolio_id)`; Option A makes it a single direct lookup with no union/filter,
fastest on the measured query and simplest to keep consistent. Option B's only edge (O(result)
terminal-status queries) is off the hot path. Both clear the ≥5% gate. User locked Option A.

---

## Consistency mechanism

### Diff method
| Option | Description | Selected |
|--------|-------------|----------|
| Shadow-key registry | Storage keeps {order_id: last_indexed_status}, diffs old→new on add/update/remove | ✓ |
| Transition-aware write API | Caller passes old→new transition explicitly | |
| You decide | Lock requirement, let planning pick | |

### Integrity
| Option | Description | Selected |
|--------|-------------|----------|
| Audit + test the contract | Lock the "mutation → update_order" invariant; oracle + determinism catch drift; no hot-path guard | ✓ |
| Defensive runtime guard | Runtime assertion / periodic rebuild | |
| You decide | Lock invariant, let planning choose enforcement | |

**User's choice:** Shadow-key registry + audit/test the contract.
**Notes:** Crux of the phase — orders mutate status in place, so storage can't diff old→new without
a shadow record. Registry is fully encapsulated (no entity/caller change). Invariant proven by audit
+ oracle + determinism rather than a hot-path guard (which would cost the cycles being saved).

---

## Postgres-extensible seam

### Seam shape
| Option | Description | Selected |
|--------|-------------|----------|
| Private to InMemory; ABC unchanged | Indexes are internal to InMemoryOrderStorage; OrderStorage ABC stays query-shaped | ✓ |
| Add index-aware hooks to ABC | Put ensure_index/rebuild on the base class | |
| You decide | Lock requirement, let planning shape | |

### Leak check
| Option | Description | Selected |
|--------|-------------|----------|
| Audit + document the contract | Walk each interface method, confirm SQL-expressible; no Postgres code | ✓ |
| Draft a Postgres conformance test | Skeleton contract test now | |
| You decide | Lock no-leak, let planning choose rigor | |

**User's choice:** Private to InMemory; ABC unchanged + audit/document.
**Notes:** Actual Postgres storage is deferred to the N+3b Persistence milestone (PERSIST-01). This
phase only ensures the seam *could* host it.

---

## Result-order / determinism

### Ordering
| Option | Description | Selected |
|--------|-------------|----------|
| Insertion-ordered buckets | dict[order_id, None] → byte-identical to flat-dict scan order, no per-query sort | ✓ |
| Plain sets + sort at query | Sort by order_id before returning | |
| Plain sets, accept order | Rely on set iteration order | |

### Verify
| Option | Description | Selected |
|--------|-------------|----------|
| Existing gate is enough | Oracle + determinism + e2e prove byte-identical output | |
| Add order-equivalence test | Explicit test: index-backed order == prior full-scan order | ✓ |
| You decide | Lock contract, let planning choose coverage | |

**User's choice:** Insertion-ordered buckets + add order-equivalence test.
**Notes:** Python set iteration is hash-ordered, not insertion-ordered — naive set indexes could
shift result order and risk the byte-exact oracle. Insertion-ordered buckets keep output identical
by construction; an explicit regression test locks it.

---

## by_status coverage

| Option | Description | Selected |
|--------|-------------|----------|
| Active statuses only | Index PENDING/PARTIALLY_FILLED only; drop on terminal; terminal-status queries scan | ✓ |
| All statuses | Index every status (unbounded terminal buckets) | |
| You decide | Lock principle, let planning decide terminal coverage | |

**User's choice:** Active statuses only.
**Notes:** User asked whether indexing all statuses would help performance and when other-status
queries are used. Grep showed `get_orders_by_status` has NO production hot caller (facade/API/reporting
only); the only callers passing terminal statuses are unit tests. Indexing terminal statuses gives
0% measurable speedup and unbounded memory growth under D-20 — net negative. Active-only confirmed.

---

## Reroute active scanners

| Option | Description | Selected |
|--------|-------------|----------|
| Reroute all three | get_pending_orders, remove_orders_by_ticker, clear_portfolio_orders via active index | ✓ |
| Only get_pending_orders | Reroute just the nested-dict builder | |
| Leave as-is | Only the two profiled queries change | |

**User's choice:** Reroute all three.
**Notes:** All three already filter on is_active, so the active index is a drop-in; routes all active
reads through one index and removes more full scans.

---

## Memory posture vs gate (b)

| Option | Description | Selected |
|--------|-------------|----------|
| Accept added memory | Pass on ≥5% wall-clock (D-04); peak memory tracked + watched, no hard ceiling | ✓ |
| Tighter memory bar | Explicit peak-memory non-regression threshold for this phase | |
| You decide | Lock wall-clock gate, let planning set memory expectation | |

**User's choice:** Accept added memory.
**Notes:** Consistent with Phase 1 D-04. Active-only indexing (D-10) keeps the footprint small.

---

## Claude's Discretion

- Exact index attribute names/types, the shadow-registry representation, the concrete ordered-set
  type (`dict[id, None]` vs ordered-dict wrapper), and how `get_active_orders(None)` unions the
  per-portfolio sets — within D-02 / D-06 / D-08.
- Whether the invariant audit (D-04) yields any non-hot-path defensive assert — planner's call.

## Deferred Ideas

- Composite `(portfolio_id, status)` index (Option B) — revisit only if a future hot consumer of
  terminal-status / arbitrary (portfolio, status) queries appears (live path).
- Indexing terminal statuses / cold queries — deferred; no hot caller justifies the memory cost.
- Actual PostgreSQL order storage (PERSIST-01) — built in the N+3b Persistence milestone.

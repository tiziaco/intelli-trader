# Phase 3: Hot-Path Performance - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-06-11
**Phase:** 3-Hot-Path Performance
**Areas discussed:** Perf-proof rigor, Storage copy contract, Bar prebuild scope, Cache-invalidation safety (W1-13)

---

## Perf-proof rigor

| Option | Description | Selected |
|--------|-------------|----------|
| Behavioral regression asserts | Deterministic, non-flaky asserts (object-identity on get_positions, prebuilt-Bar feed assert) proving + locking each opt; CI-safe | ✓ |
| Code-review only | No new tests; rely on byte-exact oracle | |
| Wall-clock micro-benchmark | Before/after timing artifact (flaky as a gate) | |

**User's choice:** Behavioral regression asserts — **with an explicit exclusion:** do NOT add any new unit test against the `SMA_MACD` strategy.
**Notes:** The W1-12 MACD-guard reorder therefore rides on code-review + byte-exact oracle only. Storage/feed optimizations get behavioral asserts; the strategy module does not. → CONTEXT D-01, D-02.

---

## Storage copy contract

| Option | Description | Selected |
|--------|-------------|----------|
| Default live-ref + *_snapshot() twins | Drop getter copies; add explicit copy-returning *_snapshot() twins (matches the W1-01 finding) | |
| Drop .copy() only where hot | Surgically drop only proven-hot getters | |
| Add snapshot accessors only | Minimal: only snapshot_count()/get_latest_snapshot() | |
| **Drop all copies, no *_snapshot()** (reframed) | Drop .copy() from all getters, read-only-view ABC contract, no speculative seam | ✓ |

**User's choice:** Drop all copies completely; **no `*_snapshot()` variant** (diverges from the cleanup-review finding).
**Notes:** User asked "why do we need safe copies from Postgres at all?" — surfaced that a query-based backend is copy-safe for free, so the `*_snapshot()` hedge is speculative API for a hypothetical write-through-cache backend. Caller-mutation audit run live during discussion confirmed no caller mutates a returned container (shallow copy never protected the contained objects; `close_all_positions` already uses `list()`). Logged as a bounded gap-discovery delta. → CONTEXT D-03, D-04, D-05, D-06.

---

## Bar prebuild scope

| Option | Description | Selected |
|--------|-------------|----------|
| Eager-all at feed init | Materialize all Bars once at init; current_bars() → dict lookup | ✓ |
| Lazy-memoize on first touch | Build + cache on first access | |
| You decide | Defer eager-vs-lazy to the planner | |

**User's choice:** Eager-all at init.
**Notes:** User asked for the performance consequence of each. Hot-path trace showed each `(ticker, time)` row is queried exactly once over the run, so lazy-memoize yields zero cache hits (rejected). The real win is structural (de-pandas the per-tick loop), not a conversion-count reduction — W1-04's "computed once" framing overstates it. User confirmed option 2 ("eager + log the finding") is just option 1 plus a one-line note, and that the framing correction belongs **inline in CONTEXT.md** (not a todo, not a future phase) so the Phase-3 planner writes an honest rationale. → CONTEXT D-07, D-08, D-09.

---

## Cache-invalidation safety (W1-13)

| Option | Description | Selected |
|--------|-------------|----------|
| Cache + multi-portfolio regression test | Implement cache w/ status-change invalidation + test the blind spot | |
| Cache, code-review only | Implement cache, no multi-portfolio test | |
| **Defer W1-13 (descope from PERF-02)** | Skip the cache; bounded owner-flagged PERF-02 descope | ✓ |

**User's choice:** Defer W1-13 (the button-click landed on "Cache + multi-portfolio regression test," but the typed message — "i like option 1" — is authoritative). User asked for a concrete example of the stale-cache bug first.
**Notes:** Grounded analysis showed W1-13 is inverted risk/reward: zero payoff on the single-portfolio golden run, oracle-blind invalidation risk across the ACTIVE/INACTIVE/ARCHIVED state machine. Worked example given (suspend P2 via `set_state(INACTIVE)` → naive cache not invalidated → P2 keeps re-pricing → drifted equity; golden run can't catch it). Bounded PERF-02 descope: correct SC-2 wording; record as deferred idea → revisit at N+2 with a status-transition regression test. → CONTEXT D-10 + Deferred.

---

## Claude's Discretion

- Plan/wave decomposition across PERF-01/02/03 + the mechanical items (W1-08/03/14/07/09/12).
- Exact mechanics of the mechanical transforms (Decimal re-wraps, local caches, redundant-call removal, guard hoist, load-time copy).
- Test placement/naming for the behavioral asserts; accessor signatures for `snapshot_count`/`get_latest_snapshot`.
- Exact wording/home of the two gap-discovery deltas (D-04, D-09) and the corrected SC-2 wording (D-10).
- Extent of touched-path opportunistic cleanup (Phase-1 D-05 / CLEANUP-STANDARD.md).

## Deferred Ideas

- **W1-13 active-portfolio cache** — deferred to when multi-portfolio runs are a measured workload (N+2); ships with a multi-portfolio status-transition regression test when revisited.

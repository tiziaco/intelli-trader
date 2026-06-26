# Phase 7: Per-Bar Metrics & Timestamp Polish - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-06-25
**Phase:** 07-per-bar-metrics-timestamp-polish
**Areas discussed:** _aligned memo shape, Debug-log disposition, Snapshot deque accessor, Metrics-cache disposition

---

## Item 1 — `_aligned` memo shape

| Option | Description | Selected |
|--------|-------------|----------|
| Module-level lru_cache (bounded) | `@functools.lru_cache(maxsize=N)` on `_aligned`, keyed `(ts, tf)`; follows the `@functools.cache` precedent, bounded for the unbounded `ts` key | ✓ |
| Instance-bounded dict memo | Hand-rolled bounded dict on the caller/manager; cache lifetime tied to the run instance | |
| Compute-once-per-tick restructure | Restructure callers so alignment computes once per TIME event instead of per symbol | |

**User's choice:** Module-level lru_cache (bounded), after asking for the most-correct option / whether a codebase pattern exists.
**Notes:** User asked whether an established pattern existed. Found two precedents — `bar_feed.py:86` `@functools.cache _offset_alias` (Phase 6 D-01) and `strategy_handler/base.py:106` `@cache _declared_hints` (Phase 4 D-05). Both use bare `@functools.cache` because their key spaces (timeframes / strategy classes) are inherently bounded. `_aligned`'s `(ts, tf)` key is unbounded (`ts` grows per bar), so the correct adaptation is bounded `lru_cache(maxsize=N)` to honor the SPEC bounded-memory constraint; repeats are intra-tick so a small `maxsize` captures the win. Locked as D-01.

---

## Item 2 — Debug-log disposition

| Option | Description | Selected |
|--------|-------------|----------|
| Remove the call entirely | Drop `metrics_manager.py:194-198`; snapshot already stores raw Timestamp / equity / pnl | ✓ |
| Guard with a level check | Build `isoformat()`/`str()` args only when debug level enabled (structlog gate) | |

**User's choice:** Remove the call entirely.
**Notes:** Snapshot already persists everything the log carried; SPEC Requirement 2 explicitly permits intentional removal recorded as a decision. Locked as D-02.

---

## Item 3 — Snapshot deque accessor

| Option | Description | Selected |
|--------|-------------|----------|
| Return the deque directly | No-copy; loosen ABC `List[Any]` → `Sequence[Any]` | |
| `get_snapshots()` returns `list()` copy on read | Keep the uniform `List[Any]` seam; copy off the hot path | ✓ |

**User's choice:** `list()` copy-on-read, after asking whether it's correct for performance.
**Notes:** User probed the performance angle (this is a perf phase). Verified via call graph that the performance win comes entirely from `deque(maxlen)` killing the per-bar trim copy, and that `get_snapshots()` has NO per-bar caller once the trim is removed — so the `list()` copy is off the hot path and W1-irrelevant. The list-copy preserves the uniform 5-accessor storage seam, avoids a `Sequence` sliceability type-lie, and is safe for live-mode concurrent iteration (an auto-evicting deque handed live is a mutation-during-iteration hazard). Locked as D-03.

---

## Item 4 — Metrics-cache disposition

| Option | Description | Selected |
|--------|-------------|----------|
| Remove the cache entirely | Drop the per-bar `clear()`, the cache dicts, and the wall-clock `datetime.now()` TTL; recompute on call | ✓ |
| Keep bounded, invalidate-on-write | Version/generation counter bumped on `add_snapshot`; bounded; serves in-memory live polling | |

**User's choice:** Remove entirely + defer the live solution.
**Notes:** User asked whether removal still allows end-of-backtest metrics (yes — calculation is untouched, only memoization is removed) and about live metrics-at-a-moment. Call graph showed `calculate_performance_metrics` (the only cache consumer) has zero callers today; the cache is inert in backtest and broken for live (wall-clock TTL + per-bar clear). The version-invalidated in-memory cache was the correct shape for in-memory live polling — but the user decided live metrics will be a **Postgres-backed time-series** (a long series doesn't belong in process memory), making the in-memory cache the wrong layer. Removed now (D-04); Postgres-backed live metrics deferred to the Live Trading milestone.

---

## Claude's Discretion

- `maxsize=N` for the `_aligned` `lru_cache` (D-01) — researcher pins against the W1 tick/symbol fan-out.
- Exact deletion shape for the cache removal (D-04) — within "no change to returned metrics."
- Behavior-preservation proof shape (dedicated equivalence test per the audit-the-invariant precedent).

## Deferred Ideas

- **Postgres-backed live metrics persistence + at-a-moment query** — replaces the removed in-memory cache; tackle in N+3b Persistence / N+4 Live Trading Readiness (owner decision 2026-06-25).
- **msgspec event-model migration / `base.py` serialization / hot-path log-volume policy** — SPEC out-of-scope; separate spikes / policy decision.

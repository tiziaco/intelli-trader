# Phase 7: Per-Bar Metrics & Timestamp Polish — Specification

**Created:** 2026-06-25
**Ambiguity score:** 0.11 (gate: ≤ 0.20)
**Requirements:** 4 locked

## Goal

Cut four profiler-confirmed per-bar CPU hotspots (~24% of W1 CPU combined) on the backtest hot
path — `_aligned` timestamp math, a per-bar `debug`-log's eager argument evaluation, the snapshot
retention full-copy trim, and the per-bar metrics-cache clear — with **zero change to engine
numbers**: the SMA_MACD oracle stays byte-exact (134 trades / `final_equity 46189.87730727451`).

## Background

With all six v1.5 optimizations merged, the W1 benchmark was de-noised in two ways before this
re-profile: (1) the benchmark's `on_tick` limit-chase probe was switched from the un-indexed
`get_orders_by_status(PENDING)` (a full `_by_id` scan that dominated the profile at ~76% CPU and
masked everything else) to the indexed `get_active_orders(pid)` — trade log verified byte-identical
(1578 fills / 659 closed); and (2) logging was disabled via `ITRADER_DISABLE_LOGS`. The resulting
Scalene CPU profile (`perf/results/scalene-w1.json`, full 2-month W1 window) exposed four per-bar
hotspots that the order-storage scan and the (largely benchmark-coverage-driven) logging volume had
been hiding. All four touch only timestamp/metrics/reporting surfaces — none touch money, positions,
orders, or fills — so the phase is **byte-exact**, not a re-baseline like Phase 5.

Profiler line attributions (logging-disabled run):
- `time_parser.py:154-156` `_aligned` — `astimezone`/`replace`/`total_seconds` ≈ **8.7%**
- `metrics_manager.py:194-198` per-bar `logger.debug(...)` args (`isoformat()`+`str()`) ≈ **8.6%**
- `portfolio_handler/storage/in_memory_storage.py` `set_snapshots` full-copy + `metrics_manager.py:181-184` trim ≈ **5%**
- `metrics_manager.py:191-192` `_metrics_cache.clear()`/`_cache_timestamp.clear()` ≈ **2.9%**

## Requirements

1. **`_aligned` memoization**: The per-bar timestamp-alignment math is not recomputed identically every tick.
   - Current: `itrader/outils/time_parser.py::_aligned` runs `ts.astimezone(pytz.utc).replace(...)`, a midnight `replace`, `total_seconds()`, and a modulo on every bar (≈8.7% W1 CPU); inputs `(timestamp, timeframe)` repeat heavily across bars/symbols but nothing is cached.
   - Target: `_aligned` returns the same result via a bounded memo keyed on `(timestamp, timeframe)` (or an equivalent recomputation-elimination), so repeated `(ts, tf)` pairs are O(1).
   - Acceptance: A re-profile shows `time_parser.py` CPU share materially reduced; `_aligned` output is provably unchanged for all inputs (existing time-alignment behavior identical); oracle byte-exact.

2. **Drop per-bar debug-log eager arg-eval**: `record_snapshot` does not build `isoformat()`/`str()` strings for a log that is gated or disabled.
   - Current: `metrics_manager.py:194-198` calls `self.logger.debug("Portfolio snapshot recorded", timestamp=timestamp.isoformat(), total_equity=str(total_equity), total_pnl=str(total_pnl))` every bar × portfolio. Python evaluates the arguments before the gated `debug` drops them, so `isoformat()` + two `str()` conversions run unconditionally (≈8.6% W1 CPU). The `PortfolioSnapshot` itself already stores the raw `Timestamp` (line 163), so these strings exist ONLY for the dropped log.
   - Target: The per-bar argument construction no longer runs when the log will not be emitted (remove the call from the per-bar path, or guard it so args are built only when the level is enabled). No new money/Decimal float conversions introduced.
   - Acceptance: A re-profile shows the `metrics_manager.py:195-197` arg-construction cost gone; with logging enabled at debug level the message content is unchanged (or the call is intentionally removed — recorded as a decision); oracle byte-exact.

3. **Snapshot retention → bounded deque (remove O(n²) trim)**: Snapshot history uses an O(1)-append, auto-evicting structure instead of a per-bar full-list copy.
   - Current: `PortfolioStorage._snapshots` is a `list`; `add_snapshot` appends, but `metrics_manager.py:181-184` trims via `set_snapshots(get_snapshots()[-max_snapshots:])`, and `set_snapshots` does `self._snapshots = list(snapshots)`. Once a portfolio exceeds `max_snapshots` (10000), every subsequent bar full-copies the entire retained window (slice + `list()`, ≈20k elements) to evict one — O(max_snapshots) per bar, i.e. latent O(n²) over runs longer than 10k bars (the 2-month W1 window is ~17.3k bars; the trim fires for ~7k bars × 6 portfolios, ≈5% CPU). The D-06 comment's claim that the trim "never fires on the golden run" does not hold for this window.
   - Target: `_snapshots` is a `collections.deque(maxlen=max_snapshots)` (or equivalent bounded structure) giving O(1) append with automatic oldest-eviction; the explicit trim block (`metrics_manager.py:181-184`) is removed. Exact last-`max_snapshots` retention is preserved.
   - Acceptance: No per-bar full-list copy remains on the snapshot path (re-profile confirms `set_snapshots`/trim cost gone); all consumers behave identically — `get_latest_snapshot()` (`[-1]`), `get_snapshots()`, and any `[-N:]`/index access in `reporting/frames.py` return the same values as before; a run exceeding `max_snapshots` retains exactly the last `max_snapshots` snapshots; oracle byte-exact.

4. **Eliminate per-bar metrics-cache churn (bounded)**: The metrics cache is not cleared on every snapshot, and remains bounded.
   - Current: `metrics_manager.py:191-192` calls `self._metrics_cache.clear()` and `self._cache_timestamp.clear()` on every `record_snapshot` (≈2.9% W1 CPU). The WR-03 fix made both dicts clear together to avoid unbounded growth; clearing every bar likely yields no cross-bar cache benefit (cleared before reuse) — pure clear/repopulate churn.
   - Target: The per-bar clear churn is eliminated. Whether by a bounded cache, lazy/invalidate-on-read invalidation, or removing the cache entirely is a HOW decision deferred to plan-phase; the cache (if kept) MUST stay bounded — no reintroduction of the WR-03 unbounded-growth bug.
   - Acceptance: A re-profile shows the per-bar `clear()` cost gone; over a long run the metrics-cache memory stays bounded (does not grow unbounded with distinct `(period, date)` keys); any metrics read returns the same values as before; oracle byte-exact.

## Boundaries

**In scope:**
- `_aligned` recomputation elimination (`itrader/outils/time_parser.py`).
- Removing/guarding the per-bar `record_snapshot` debug-log argument evaluation (`metrics_manager.py`).
- Snapshot retention → bounded deque + trim-block removal (`portfolio_handler/storage/in_memory_storage.py`, `metrics_manager.py`).
- Eliminating the per-bar `_metrics_cache`/`_cache_timestamp` clear churn while keeping the cache bounded (`metrics_manager.py`).
- A W1 re-profile + clean-benchmark re-freeze validating the reclaim.

**Out of scope:**
- Dataclass/event-model migration to `msgspec.Struct` (~10% CPU) — separate measure-first spike; entangled with the frozen-event immutability guarantee + a new dependency.
- `strategy_handler/base.py` `to_dict`/`_json_safe` serialization cost (~8.5%, diffuse) — no single hot line; lower priority, separate item.
- Switching the event bus `queue.Queue` → `deque` — explicitly rejected: the bus is ~1.75% CPU and live mode needs the lock.
- Hot-path `warning()`/`info()` log volume — largely a W1-coverage artifact (over-extending C/D strategies); a logging-policy question, not this phase.
- Any change to money/Decimal handling, order/fill/position logic, or the matching engine — this phase has no numeric surface.
- Changing `max_snapshots` value or snapshot semantics beyond the storage structure — retention count stays 10000.

## Constraints

- **Byte-exact gate (Gate a):** SMA_MACD oracle green (134 trades / `final_equity 46189.87730727451`), e2e suite green, `mypy --strict` clean, determinism double-run byte-identical. This phase is NOT a re-baseline.
- **Decimal end-to-end:** no float-for-money introduced; `str()`/`isoformat()` removals must not change any stored or reported numeric value.
- **Indentation:** match each file — `config/`, `core/`, `price_handler/feed/`, and the events package use 4 spaces; handler modules use tabs. `metrics_manager.py` / `in_memory_storage.py` (portfolio_handler) use tabs; `time_parser.py` (outils) — match the file. Do NOT normalize indentation.
- **Determinism:** no wall-clock; memoization keys must be deterministic business values.
- **Bounded memory:** any memo/cache added or retained MUST be bounded (no unbounded growth over a long run).

## Acceptance Criteria

- [ ] `_aligned` no longer recomputes the per-bar `astimezone`/`replace`/`total_seconds` identically each tick; a re-profile shows `time_parser.py` CPU share materially down; alignment output unchanged for all inputs.
- [ ] `record_snapshot`'s per-bar `isoformat()`/`str()` argument construction no longer runs when the debug log is gated/disabled; re-profile shows that cost gone.
- [ ] Snapshot storage uses a bounded `deque(maxlen=max_snapshots)` (or equivalent); the `set_snapshots(get_snapshots()[-N:])` per-bar trim is removed; a run exceeding 10000 bars retains exactly the last 10000 snapshots with no per-bar full-list copy.
- [ ] `get_latest_snapshot()`, `get_snapshots()`, and reporting-frame snapshot access return byte-identical values to pre-phase behavior.
- [ ] The per-bar `_metrics_cache.clear()`/`_cache_timestamp.clear()` churn is eliminated; the metrics cache stays bounded over a long run; metrics reads return the same values.
- [ ] **Gate (a):** SMA_MACD oracle byte-exact (134 / `46189.87730727451`); e2e green; `mypy --strict` clean; determinism double-run byte-identical.
- [ ] **Gate (b):** clean W1 benchmark shows a measurable wall-clock improvement vs the current re-frozen baseline (same-machine A/B attribution; re-freeze on a verified-cool machine per the thermal-drift caveat).

## Ambiguity Report

| Dimension          | Score | Min  | Status | Notes                                                        |
|--------------------|-------|------|--------|--------------------------------------------------------------|
| Goal Clarity       | 0.92  | 0.75 | ✓      | 4 hotspots with exact files/lines/%CPU; byte-exact outcome   |
| Boundary Clarity   | 0.88  | 0.70 | ✓      | Explicit out-of-scope (msgspec, queue, base.py, log volume)  |
| Constraint Clarity | 0.88  | 0.65 | ✓      | Byte-exact gate, Decimal, tabs/spaces, bounded-memory locked |
| Acceptance Criteria| 0.85  | 0.70 | ✓      | Gate (b) = measurable + re-freeze (owner-chosen)             |
| **Ambiguity**      | 0.11  | ≤0.20| ✓      |                                                              |

Status: ✓ = met minimum, ⚠ = below minimum (planner treats as assumption)

## Interview Log

| Round | Perspective     | Question summary                              | Decision locked                                                        |
|-------|-----------------|-----------------------------------------------|------------------------------------------------------------------------|
| 0     | Researcher (profile) | What surfaced after de-noising the W1 profile? | 4 per-bar hotspots: `_aligned`, debug-arg eval, snapshot trim O(n²), cache churn |
| 1     | Boundary Keeper | Phase home, now that v1.5 1-6 are complete?    | Phase 7 of v1.5 (keep all perf work in one milestone; close v1.5 after) |
| 1     | Failure Analyst | Gate (b) reclaim target?                      | Measurable improvement + re-freeze (no hard % threshold)               |
| 1     | Simplifier      | Item 4 (cache) outcome scope?                 | Fix-or-remove; eliminate churn + keep bounded; HOW deferred to plan    |
| —     | Researcher (code) | Does the snapshot store isoformat or raw ts?  | Stores raw `Timestamp` (line 163) — isoformat is debug-arg-only        |

---

*Phase: 07-per-bar-metrics-timestamp-polish*
*Spec created: 2026-06-25*
*Next step: /gsd:discuss-phase 7 — implementation decisions (memo structure, cache disposition, etc.)*

---
phase: 05-real-sandbox-path-reconciliation-persistence-live-drive
plan: 13
subsystem: execution
tags: [okx, live-trading, reconciliation, correlation, dedup-ring, memory-bound, wr-05]

# Dependency graph
requires:
  - phase: 05 (plan 05-11)
    provides: "adopt_venue_correlation inbound restart seam + the _handle_trade dedup/resolve/buffer flow this plan encapsulates and extends"
  - phase: 02 (plan 02-03)
    provides: "OkxExchange live arm (watch_my_trades fill stream, venue-id -> OrderEvent correlation, _emit_fill)"
provides:
  - "VenueCorrelationIndex — the OKX arm's venue-correlation state as one cohesive, socket-free, unit-testable class (3 maps + late-fill buffer + bounded dedup ring + cumulative counter + lock)"
  - "Fill-driven release-on-terminal: a fully-filled order self-releases its correlation entries (bounded memory over a long live session)"
  - "Bounded trade-id dedup ring (deque(maxlen)+set) replacing the insert-only _seen_trade_ids"
  - "OkxExchange.release_venue_correlation — the outbound twin of adopt_venue_correlation"
affects: [okx-connector, live-reconciliation, wr-05-r4-non-fill-terminals]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Encapsulated correlation-state class delegated-to by the exchange arm (R1)"
    - "Index self-release inside the execution domain via a per-venue_id cumulative counter — NOT coupled to ReconcileManager (WR05-D1)"
    - "deque(maxlen=capacity)+companion set FIFO dedup ring (WR05-D2, mirrors live_bar_feed.py)"
    - "drain-then-evict, emit-outside-lock release (WR05-D3)"

key-files:
  created:
    - itrader/execution_handler/exchanges/venue_correlation.py
    - tests/unit/execution/test_venue_correlation.py
  modified:
    - itrader/execution_handler/exchanges/okx.py
    - tests/unit/execution/test_okx_fill_idempotency.py
    - tests/unit/execution/test_okx_exchange.py
    - tests/e2e/test_okx_sandbox_recon.py

key-decisions:
  - "Index self-releases (WR05-D1) — cumulative-filled counter owned by VenueCorrelationIndex, zero cross-domain coupling, zero backtest-path touch"
  - "Dedup ring = deque(maxlen=10000)+set (WR05-D2); durable venue_trade_id DB layer is the evicted-id backstop"
  - "release is drain-then-evict + idempotent + emit-outside-lock (WR05-D3); _emit_fill returns bool so a malformed fill never advances the counter"
  - "release_ NOT added to AbstractExchange — SimulatedExchange untouched (zero backtest touch)"

patterns-established:
  - "R1: exchange arm delegates all correlation reads/writes to an injected/composed state class taking its own lock internally (WR-03 preserved)"
  - "R2: fill-driven self-release keyed on a per-venue_id cumulative Decimal counter, terminal at cumulative >= order.quantity"
  - "R3: bounded FIFO dedup ring — deque(maxlen)+set, oldest evicted past capacity"

requirements-completed: [RECON-02]

# Metrics
duration: 10min
completed: 2026-07-04
---

# Phase 5 Plan 13: WR-05 Correlation-State Remediation Summary

**Bounded the live OkxExchange venue-correlation state — encapsulated it in a socket-free `VenueCorrelationIndex`, added fill-driven release-on-terminal + a capacity-bounded trade-id dedup ring — closing WR-05's insert-only unbounded-growth vector for the common (fill) path with zero backtest impact (oracle byte-exact 134 / 46189.87730727451).**

## Performance

- **Duration:** 10 min
- **Started:** 2026-07-04T09:30:22Z
- **Completed:** 2026-07-04T09:41Z
- **Tasks:** 3 completed (TDD: RED → GREEN → GREEN)
- **Files created/modified:** 6 (2 created, 4 modified)

## Accomplishments
- **R1 — encapsulation:** the four insert-only correlation structures (`_orders_by_venue_id`, `_venue_id_by_order_id`, `_orders_by_clOrdId`, `_seen_trade_ids`), the `_pending_fills_by_venue_id` late-fill buffer, and `_correlation_lock` moved out of `OkxExchange` into one cohesive `VenueCorrelationIndex` (constructible with no socket / no connector). `OkxExchange` delegates every correlation read/write to `self._index`.
- **R2 — release-on-terminal (fill-driven):** a per-`venue_id` cumulative-filled `Decimal` counter self-releases an order's venue-id / order-id / clOrdId entries + the empty pending buffer when cumulative reaches `order.quantity` (drain-any-buffered-fill FIRST, WR05-D3). The index owns the terminal decision entirely inside the execution domain (WR05-D1 — NOT coupled to `ReconcileManager`).
- **R3 — bounded dedup ring:** `_seen_trade_ids` is now a `deque(maxlen=10000)` FIFO ring + a companion `set` for O(1) membership; the oldest id is evicted past capacity.
- **Zero-backtest-impact gate held:** SMA_MACD oracle byte-exact (134 / `46189.87730727451`), backtest inertness green, `mypy --strict` clean (205 files), tabs preserved, no new `EventType`, `release_` NOT on `AbstractExchange`, `SimulatedExchange` untouched.

## Task Commits

Each task was committed atomically (TDD test → impl):

1. **Task 1: Failing VenueCorrelationIndex unit suite (RED)** - `06b4b933` (test)
2. **Task 2: Implement VenueCorrelationIndex (R1+R3) + delegate from OkxExchange (GREEN)** - `381652c8` (feat)
3. **Task 3: Release-on-terminal (R2) — cumulative self-release + release_venue_correlation seam (GREEN)** - `a611c4d2` (feat)

## Files Created/Modified
- `itrader/execution_handler/exchanges/venue_correlation.py` (created) — `VenueCorrelationIndex`: 3 correlation maps + `_pending_fills_by_venue_id` buffer + bounded dedup ring (`deque(maxlen)`+set) + per-`venue_id` cumulative counter + `_correlation_lock`; exposes `register_pending`/`register`/`adopt`/`resolve`/`mark_seen`/`venue_id_for`/`record_fill`/`release` + `__len__`/`seen_count`/`pending_count`. Live-only imports (stdlib + core/events).
- `itrader/execution_handler/exchanges/okx.py` (modified) — deleted the five inline maps + inline lock; delegates to `self._index`; added `release_venue_correlation` (outbound twin of `adopt_venue_correlation`); `_emit_fill` now returns `bool`; `_handle_trade` feeds the cumulative counter after an actual emit and self-releases on terminal; dropped now-unused `threading`/`OrderId` imports.
- `tests/unit/execution/test_venue_correlation.py` (created) — 8 socket-free direct-index tests (register/adopt→resolve, mark_seen dedup, bounded-ring eviction, drain-before-release, partial-retains/full-releases, idempotent release).
- `tests/unit/execution/test_okx_fill_idempotency.py`, `tests/unit/execution/test_okx_exchange.py`, `tests/e2e/test_okx_sandbox_recon.py` (modified) — direct-attribute references repointed onto `exchange._index.*` (behavior unchanged).

## Decisions Made
- **`_emit_fill` returns `bool` (Rule 2 — correctness):** the plan's Task-3 wiring feeds the cumulative counter "after a correlated fill is emitted". A fill with an `amount` but missing `price`/`timestamp` is skipped by `_emit_fill` yet still carries an amount — advancing the counter on it would risk a premature self-release. Making `_emit_fill` return whether it actually emitted lets `_handle_trade` gate the counter on a real emit, so a malformed/skipped fill never advances cumulative-filled. (Documented as a deviation below.)
- **`release` implemented fully in Task 2 as a stub, completed in Task 3:** `record_fill`/`release` signatures landed with the index in Task 2 (stubs) so the Task-1 RED tests had a target; the drain-then-evict + cumulative bodies + the OKX self-release wiring landed in Task 3, per the plan's task split.
- **`release_venue_correlation` takes a `venue_id: str`** (not an `OrderEvent`): the self-release path in `_handle_trade` holds the resolved `venue_id`, the natural release key; symmetry with `adopt_venue_correlation` is conceptual (inbound adopt / outbound release), not signature-identical.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing correctness guard] `_emit_fill` return-status gate on the cumulative counter**
- **Found during:** Task 3 (release-on-terminal wiring)
- **Issue:** The plan wired `record_fill` to run after emit, but `_emit_fill` skips malformed fills (missing price/timestamp) that may still carry an `amount`. Feeding the cumulative counter unconditionally would count a never-settled fill toward `order.quantity`, risking a premature self-release (correlation dropped while the order is still live).
- **Fix:** `_emit_fill` now returns `bool` (True emitted / False skipped); `_handle_trade` gates `record_fill` + `release_venue_correlation` on an actual emit AND a non-None `venue_id`.
- **Files modified:** `itrader/execution_handler/exchanges/okx.py`
- **Verification:** `test_okx_fill_idempotency.py` malformed-trade tests stay green (skipped fill emits nothing and does not advance the counter); oracle byte-exact; mypy clean.
- **Committed in:** `a611c4d2` (part of Task 3)

---

**Total deviations:** 1 auto-fixed (1 × Rule 2)
**Impact on plan:** The single auto-fix is a correctness guard required to keep the fill-driven self-release from firing on a non-settled fill. No scope creep — all other work matched the plan exactly.

## Issues Encountered
None. Worktree gotchas handled per project memory: `PYTHONPATH="$PWD"` prepended so pytest/mypy see the worktree edits (editable-install shadowing); tests run via `poetry run pytest` (not `make test`, which aborts in a worktree on missing `.env`).

## Threat Surface
No new security-relevant surface. This change *reduces* a resource-exhaustion (DoS) vector (T-05-13-01) in a live-only module: no new external input, no new `EventType`, no new network listener, no new package (stdlib `collections.deque` + `threading` only). The plan's threat register (T-05-13-01..04) is fully mitigated by R1/R2/R3.

## Known Stubs / Residual (→ R4, future phase)
- **Non-fill terminals** (partial-then-cancel D-12, expire, reject-without-fill) have no mid-session terminal signal today (`watch_orders` is log-only, `VenueReconciler` is startup-only) — their correlation releases only at restart until R4. This plan intentionally closes the **fill-driven common path** + bounds the ring; the R4 residual is the carved-out broad slice, not a new gap (per 05-SPEC.md + WR05-D1 risk note).

## Next Phase Readiness
- WR-05 narrow slice (R1–R3) closed; RECON-02 (fill-ID dedup / partial-fill idempotency) satisfied.
- W1/W2 within the v1.5 frozen baseline is structurally guaranteed by the inertness gate (`venue_correlation.py` imports only stdlib + core/events; okx.py stays live-only) — recorded as the structural proxy; no in-suite benchmark automation.
- No blockers. Full-suite `make test` should be re-run in the main checkout at phase close (worktree `.env` abort caveat).

## Self-Check: PASSED
- Created files verified on disk: `venue_correlation.py`, `test_venue_correlation.py`, `05-13-SUMMARY.md`.
- Task commits verified in git log: `06b4b933` (RED test), `381652c8` (R1/R3 GREEN), `a611c4d2` (R2 GREEN).
- TDD gate sequence honored: `test(...)` commit precedes both `feat(...)` commits.
- Verification: `test_venue_correlation.py` 8/8 green; `test_okx_fill_idempotency.py` + `test_okx_exchange.py` 29/29 green; full `tests/unit/execution` 232/232; oracle byte-exact `134 / 46189.87730727451`; inertness green; `mypy --strict` clean (205 files).

---
*Phase: 05-real-sandbox-path-reconciliation-persistence-live-drive*
*Completed: 2026-07-04*

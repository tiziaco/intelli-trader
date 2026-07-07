# Phase 5 (reopened) — Plan 05-13: WR-05 correlation-state remediation — Specification

**Created:** 2026-07-03
**Ambiguity score:** 0.12 (gate: ≤ 0.20)
**Requirements:** 3 locked (R1–R3) + the zero-backtest-impact gate
**Scope:** the **NARROW** slice of the mid-session order-lifecycle reconciliation design — resolves Phase 5 review warning **WR-05** (unbounded `OkxExchange` correlation growth). The **BROAD** capability (mid-session order-status signal + out-of-band coverage, R4) is a **future phase**, NOT this plan.

> **Full design context (READ before planning):** `docs/superpowers/specs/2026-07-03-mid-session-order-lifecycle-reconciliation-spec.md` — the complete 6-requirement design with the WR-05→continuous-reconciliation reframing and framework precedent. This file is the trimmed R1–R3 slice carved into plan 05-13 per the 2026-07-03 scope-split decision.

## Goal

Bound the live `OkxExchange` venue-correlation state so it no longer grows without limit over a long session: **encapsulate** the correlation concern into one testable unit, **release** an order's correlation entries when the order terminalizes (fill-driven), and **bound** the trade-id dedup set — resolving WR-05's unbounded-growth for the common (fill) path, with **zero backtest impact** (SMA_MACD oracle stays `134 / 46189.87730727451` byte-exact).

## Background

As of 2026-07-03 (symbol-anchored — line numbers rot):

- `OkxExchange` holds four **insert-only** correlation structures (ctor): `_orders_by_venue_id`, `_venue_id_by_order_id`, `_orders_by_clOrdId`, `_seen_trade_ids`, plus the `_pending_fills_by_venue_id` late-fill buffer, guarded by `_correlation_lock`. Written on submit (`_submit_order`), read on fill (`_handle_trade`); **nothing is ever removed** → over a long session every order and every trade id is retained (WR-05).
- `_handle_trade` already resolves a fill → originating `OrderEvent` and emits `FillEvent(EXECUTED)`; `ReconcileManager.on_fill` terminalizes the mirror (FILLED when cumulative == quantity).
- `adopt_venue_correlation(order)` exists (called by the startup-only `VenueReconciler`) — the **inbound** correlation seam. Its symmetric **outbound** twin (release-on-terminal) does not exist.
- `SimulatedExchange` (backtest) has **none** of these structures; the backtest path imports no connector/async code (inertness test enforced).

**Residual explicitly left to the future phase (R4):** non-fill terminals (cancel/expire/reject-without-fill) and out-of-band venue changes have no mid-session terminal signal today (`watch_orders` is log-only; `VenueReconciler` is startup-only), so their correlation entries release only at restart until R4 lands. This plan does **not** close that; it closes the fill-driven common path + bounds the dedup ring.

## Requirements

1. **VenueCorrelationIndex encapsulation**: the venue-correlation concern is a cohesive, unit-testable unit.
   - Current: four loose dicts/set + the `_pending_fills_by_venue_id` buffer + `_correlation_lock` inline in `OkxExchange`; no release path.
   - Target: a `VenueCorrelationIndex` class owning those structures, exposing `register / resolve / adopt / release / mark_seen`; `OkxExchange` delegates to it.
   - Acceptance: unit tests construct the index directly (no socket) and exercise `register → resolve → release` and `adopt → resolve`; existing fast-fill-race + WR-02 adopt tests stay green; `mypy --strict` clean.

2. **Lifecycle eviction — release on terminal (fill-driven)**: an order's correlation entries are removed when a fill terminalizes it.
   - Current: entries persist for the process lifetime; a fully-filled order's three map entries are never dropped.
   - Target: when a fill completes an order (cumulative == quantity → terminal), `release` drops its venue-id / order-id / clOrdId entries and any now-empty pending-fills buffer for its venue_id — **draining the buffer first** so a late buffered fill still emits its `FillEvent` (no WR-02 regression).
   - Acceptance: a test fills an order fully then asserts the index holds 0 entries for it; a buffered late fill is drained (emits its `FillEvent`) before the entry is released; partial fills leave the order OPEN and its entries retained.

3. **Bounded trade-id dedup ring**: `_seen_trade_ids` is capacity-bounded.
   - Current: `set[str]`, insert-only, unbounded.
   - Target: a capacity-bounded recency ring (FIFO/LRU — `LiveBarFeed` deque-ring precedent) with a configured maximum; oldest id evicted past capacity.
   - Acceptance: inserting > capacity ids keeps size ≤ capacity; dedup within the window still returns an idempotent no-op; an evicted-then-resent id is still deduped at the durable `venue_trade_id` DB layer (documented backstop — CR-01 tail).

**Zero-backtest-impact gate (applies to all of R1–R3):** all changes in live-only modules (`okx.py`, `connectors/`); `release_`/index is **not** on the `AbstractExchange` Protocol (or a no-op default) so `SimulatedExchange` is untouched; **no new `EventType`**; `tests/integration/test_backtest_oracle.py` byte-exact (`134 / 46189.87730727451`); determinism double-run identical; inertness test green; W1/W2 within the v1.5 baseline.

## Boundaries

**In scope:**
- `VenueCorrelationIndex` class (encapsulate 3 maps + pending-fills buffer + bounded `_seen_trade_ids` ring + lock).
- `release_venue_correlation` seam on `OkxExchange`, symmetric with `adopt_venue_correlation`.
- Fill-driven release-on-terminal wiring.
- Bounding the trade-id dedup ring.

**Out of scope (→ future phase / R4):**
- **Mid-session order-status signal** (promote `watch_orders` / REST order-poll) — that's the broad capability; not this plan.
- **Out-of-band (web-UI) cancel coverage** — depends on R4.
- **Non-fill terminal release** (cancel/expire/reject-without-fill) mid-session — depends on R4; residual documented above.
- **Native OKX OCO/algo orders**; **multi-venue**; **`SimulatedExchange`/backtest fail-fast changes**; **new `EventType`**.

## Constraints

- **Zero backtest hot-path impact**: oracle byte-exact; determinism double-run identical; inertness preserved; W1/W2 within the v1.5 baseline (15.7 s / 152.8 MB).
- **Decimal money edge held**; single UUIDv7; business `time` from venue ts, never wall-clock.
- **Indentation**: tabs in `okx.py`; match the file, never normalize.
- **Test strictness**: `filterwarnings=["error"]`, `--strict-markers`, `--strict-config`; no new markers; `mypy --strict` clean.
- **No new `EventType`**: reuse the existing `FillEvent` path + the direct `adopt_`/`release_` seam.

### OPEN DECISIONS for discuss-phase (the "how" — resolve these, do NOT let the planner guess)

1. **Release-hook placement (load-bearing — oracle-safety stakes):**
   - (a) `ReconcileManager` terminal transition — single terminalization authority, but shared engine-thread code that also runs in backtest → `release_` MUST be a proven no-op on `SimulatedExchange` to keep the oracle byte-exact.
   - (b) `OkxExchange` self-managed — track cumulative-filled per venue_id in `_handle_trade`, self-release when the order completes → fully live-isolated (nothing on the backtest path), but duplicates the "fully filled?" check the mirror also does.
2. **`_seen_trade_ids` ring** — concrete capacity value + structure (`OrderedDict` vs `deque`).
3. **Late-echo safety** — confirm drain-then-evict ordering + idempotency (buffer drained before release).

## Acceptance Criteria

- [ ] Correlation index holds **0 entries** for a fully-filled order after its fill is processed.
- [ ] Partial fills leave the order OPEN with its correlation entries **retained**.
- [ ] A buffered late fill is **drained (emits its `FillEvent`) before** its correlation is released — no WR-02 regression.
- [ ] `_seen_trade_ids` size stays **≤ configured capacity** under > capacity inserts; dedup within the window is still an idempotent no-op.
- [ ] `tests/integration/test_backtest_oracle.py` **byte-exact** (`134 / 46189.87730727451`); determinism double-run identical.
- [ ] Inertness test **green** (no `connectors`/`ccxt.pro` after a backtest-root import); **no new `EventType`** added.
- [ ] `poetry run mypy itrader` clean; full suite green under `filterwarnings=["error"]` with **no new markers**.
- [ ] Existing fast-fill-race + WR-02 adopt tests stay green.

## Ambiguity Report

| Dimension          | Score | Min  | Status | Notes                                                                  |
|--------------------|-------|------|--------|------------------------------------------------------------------------|
| Goal Clarity       | 0.90  | 0.75 | ✓      | Bound correlation state (encapsulate + fill-driven release + ring), oracle byte-exact |
| Boundary Clarity   | 0.90  | 0.70 | ✓      | R4 / out-of-band explicitly carved out to future phase                 |
| Constraint Clarity | 0.82  | 0.65 | ✓      | Hard gates enumerated; 3 "how" decisions flagged for discuss           |
| Acceptance Criteria| 0.85  | 0.70 | ✓      | 8 pass/fail checks                                                      |
| **Ambiguity**      | 0.12  | ≤0.20| ✓      | Openness is in the 3 "how" decisions (discuss-phase territory)         |

Status: ✓ = met minimum, ⚠ = below minimum (planner treats as assumption)

## Interview Log

Requirements derived from the 2026-07-03 design discussion (recorded in the full docs/ spec's Interview Log). This file is the narrow R1–R3 slice per the scope-split decision.

| Round | Perspective     | Decision locked                                                                 |
|-------|-----------------|---------------------------------------------------------------------------------|
| —     | (see full spec) | Narrow WR-05 remediation (R1–R3) → Phase 5 plan 05-13; broad R4 → future phase   |

---

*Phase: 05-real-sandbox-path-reconciliation-persistence-live-drive (reopened for 05-13)*
*Spec created: 2026-07-03*
*Next step: /gsd:discuss-phase 5 (resolve the 3 "how" decisions) → /gsd:plan-phase 5 (produce 05-13-PLAN.md)*

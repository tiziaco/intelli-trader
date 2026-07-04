# Mid-Session Order-Lifecycle Reconciliation (live OKX path) — Specification

**Created:** 2026-07-03
**Status:** Draft spec — supersedes Phase 05 review warning **WR-05**; candidate **v1.7 Phase 7** (NOT yet registered in ROADMAP.md — scope decision pending)
**Ambiguity score:** 0.125 (gate: ≤ 0.20)
**Requirements:** 6 locked
**Origin:** Design discussion 2026-07-03 (WR-05 leak → reframed as a missing continuous order-lifecycle reconciliation)

> **Scope split (decided 2026-07-03):** this work is split in two.
> - **Narrow WR-05 remediation → new Phase 5 plan `05-13`** (resolves the review warning): Requirements **R1 (VenueCorrelationIndex), R2 (release-on-terminal, fill-driven), R3 (bounded dedup ring)** under the R5/R6 constraints. Localized, live-only, zero backtest impact — matches how WR-01/02/03/04 + CR-01 were resolved within Phase 5.
> - **Broad continuous-reconciliation capability → future phase (this spec's remaining core):** Requirement **R4 (mid-session order-status signal + out-of-band coverage)**. New capability beyond Phase 5's delivered scope; kept here as the future-phase artifact.
> The narrow plan leaves a **documented residual**: non-fill terminals (cancel/expire/reject-without-fill) release only at restart until R4 lands — tracked to this spec.

> **Note on placement:** written to `docs/superpowers/specs/` (the project's design-spec home) rather than a `.planning/phases/07-*` dir, to avoid mutating the near-closing v1.7 roadmap or creating an orphan phase dir that perturbs GSD phase tooling. To register the broad capability as a plannable phase, add it to ROADMAP.md + REQUIREMENTS.md, then this file lifts directly into that phase's `SPEC.md`.

## Goal

The live OKX path gains **continuous (mid-session) order-lifecycle reconciliation**: cancelled / expired / rejected-without-fill orders **and** out-of-band (exchange-website) venue changes terminalize the order mirror *during a running session* (not only at the next restart), and the `OkxExchange` venue-correlation state is **bounded** (released on terminal; trade-id dedup capacity-capped) — with **zero backtest impact** (SMA_MACD oracle stays `134 / 46189.87730727451` byte-exact).

## Background

Grounded in the code as of 2026-07-03 (symbol-anchored — line numbers rot):

- **`OkxExchange` holds four insert-only correlation structures** (`okx.py` ctor): `_orders_by_venue_id`, `_venue_id_by_order_id`, `_orders_by_clOrdId`, `_seen_trade_ids`, plus the `_pending_fills_by_venue_id` late-fill buffer, guarded by `_correlation_lock`. Written on submit (`_submit_order`) and read on fill (`_handle_trade`); **nothing is ever removed**. Over a long-running session they grow without bound (WR-05) — every order ever submitted and every trade id ever seen is retained (with a live `OrderEvent` reference).
- **`watch_my_trades` → `FillEvent(EXECUTED)`** drives fill-based terminalization and works today (`_handle_trade` → `ReconcileManager`).
- **`watch_orders` (`_consume_orders`) is log-only** — it `logger.debug`s each venue order-status update and does nothing else.
- **`VenueReconciler.reconcile()` is startup-only** (`venue_reconciler.py` / `live_trading_system.py`: *"a blind mid-session reconcile would spuriously HALT … a startup-before-RUNNING contract only"*). There is **no** periodic mid-session order-status sweep.
- **`PortfolioHandler._drift_reconciler`** is a **position/balance** drift-**halt** (engine thread, on fills), **not** an order-lifecycle reconcile.
- **OKX arm places plain orders** (no native OCO/algo; `okx.py` note that trigger translation is unwired). **Brackets/OCO are engine-side** (`BracketManager` emits CANCEL `OrderEvent`s on a flattening fill). `_cancel_order` fires the cancel RPC and **emits nothing on success**; the cancel/fill-race guard deliberately does *not* emit `FillEvent(REFUSED)` on a failed cancel (leaves the mirror resting, next reconcile fixes it).

**Consequence (the gap this phase closes):** a cleanly-cancelled internal order, and *any* out-of-band venue change, is **not confirmed or terminalized mid-session** — the engine believes the order is still resting for the rest of the session, and its correlation entries never release. The WR-05 leak is one symptom of this missing continuous reconciliation. Mature frameworks treat this as first-class (Nautilus continuous reconciliation + external-order handling; freqtrade REST-polls order status each loop; LEAN brokerage order-event stream) — a startup-only reconcile is understood to be insufficient.

## Requirements

1. **VenueCorrelationIndex encapsulation** _(NARROW — Phase 5 plan 05-13)_: the venue-correlation concern is a cohesive, unit-testable unit.
   - Current: four loose dicts/set + the `_pending_fills_by_venue_id` buffer + `_correlation_lock` live inline in `OkxExchange`; no release path exists.
   - Target: a `VenueCorrelationIndex` class owning those structures, exposing `register / resolve / adopt / release / mark_seen / gc_against_active`; `OkxExchange` delegates to it.
   - Acceptance: unit tests construct the index directly (no socket) and exercise `register → resolve → release` and `adopt → resolve`; `OkxExchange` behavior unchanged for existing fast-fill-race + WR-02 adopt tests; `mypy --strict` clean.

2. **Lifecycle eviction (release on terminal)** _(NARROW — Phase 5 plan 05-13; fill-driven only)_: an order's correlation entries are removed when the order terminalizes.
   - Current: entries persist for the process lifetime; a filled/cancelled order's three map entries are never dropped.
   - Target: on an order reaching a terminal mirror state, `release` drops its venue-id / order-id / clOrdId entries and any now-empty pending-fills buffer for its venue_id — **draining the buffer first** so a late buffered fill still emits its `FillEvent` (no WR-02 regression).
   - Acceptance: a test fills an order then asserts the index holds 0 entries for it; a test cancels an order then asserts 0 entries; a buffered late fill is drained (emits its `FillEvent`) before the entry is released.

3. **Bounded trade-id dedup ring** _(NARROW — Phase 5 plan 05-13)_: `_seen_trade_ids` is capacity-bounded.
   - Current: `set[str]`, insert-only, unbounded (grows one entry per fill).
   - Target: a capacity-bounded recency ring (FIFO/LRU — e.g. `OrderedDict`/`deque`, `LiveBarFeed` deque-ring precedent) with a configured maximum; oldest id evicted past capacity.
   - Acceptance: inserting > capacity ids keeps size ≤ capacity; dedup within the window still returns an idempotent no-op; an evicted-then-resent id is still deduped at the durable `venue_trade_id` DB layer (documented backstop — CR-01 tail).

4. **Mid-session order-status signal (the linchpin)** _(BROAD — future phase)_: non-execution terminals (cancel/reject/expire) and out-of-band venue changes terminalize the mirror mid-session.
   - Current: `watch_orders` is log-only; `VenueReconciler` is startup-only; these terminals are invisible until the next restart.
   - Target: a **continuous** order-status signal feeds terminalization mid-session, driving Requirement 2's release for non-fill terminals and closing out-of-band coverage. **OPEN MECHANISM FORK (deferred to discuss-phase — "how"):** (a) promote `watch_orders` — `_consume_orders` emits terminal `FillEvent(CANCELLED/REJECTED/EXPIRED)` `SimulatedExchange`-style; **or** (b) a periodic REST order-poll. The *requirement* (a mid-session signal must exist) is locked; the mechanism is a discuss-phase decision.
   - Acceptance: a simulated venue "canceled" order-status update (fake WS or fake poll) terminalizes the mirror to CANCELLED and releases the correlation mid-session; an out-of-band cancel the engine did **not** initiate is detected mid-session (mirror terminalizes, correlation releases) rather than only at restart.

5. **`watch_my_trades` remains the money/execution source**: no change to fill-money handling; race double-fills still captured.
   - Current: `watch_my_trades` → `FillEvent(EXECUTED)` with the `to_money(str)` Decimal edge.
   - Target: unchanged and explicitly retained — NOT replaced by the order-status signal (the sibling that fills during a cancel/fill race must still be reported here).
   - Acceptance: existing fill/reconcile tests stay green; a scenario where a cancel-targeted order fills is still reported via `watch_my_trades`.

6. **Zero backtest impact**: the whole change is live-only; the oracle stays byte-exact.
   - Current: `SimulatedExchange` has no correlation maps; the backtest path imports no connector/async code (inertness test enforces it).
   - Target: all changes in live-only modules (`okx.py`, `connectors/`, `venue_reconciler.py`); `release_venue_correlation` is **not** on the `AbstractExchange` Protocol (or is a no-op default so `SimulatedExchange` is untouched); **no new `EventType`** (reuse the `FillEvent` channel + the `adopt_`/`release_` direct seam); backtest fail-fast policy unchanged.
   - Acceptance: `tests/integration/test_backtest_oracle.py` byte-exact (`134 / 46189.87730727451`); determinism double-run identical; inertness test green (no `connectors`/`ccxt.pro` after a backtest-root import); no new `EventType` member added; W1/W2 within the v1.5 baseline.

## Boundaries

**In scope:**
- `VenueCorrelationIndex` class — encapsulate the three correlation maps + pending-fills buffer + bounded `_seen_trade_ids` ring + lock, with `release` and `gc_against_active`.
- `release_venue_correlation` seam on `OkxExchange`, symmetric with the existing `adopt_venue_correlation`.
- A mid-session order-status terminalization signal for non-fill terminals (cancel/reject/expire) **and** out-of-band cancels (mechanism chosen in discuss).
- Terminal-release wiring for both feeders (fill-driven full-fill + status-driven terminal).
- Bounding the trade-id dedup ring.

**Out of scope:**
- **Native OKX OCO/algo orders** — brackets stay engine-side; native venue OCO is a separate concern.
- **A full continuous two-sided position/balance reconcile loop** — the startup two-sided `VenueReconciler.reconcile()` stays startup-only (it exists precisely to avoid the spurious-HALT problem of a blind mid-session two-sided compare); only **order-lifecycle** is made continuous.
- **Multi-venue** — OKX only.
- **Changing `SimulatedExchange` / backtest fail-fast behavior** — backtest stays byte-exact.
- **New `EventType` / new route** — preferred design reuses `FillEvent` + the direct `adopt_`/`release_` seam.
- **`watch_my_trades` money-path changes** — retained unchanged.

## Constraints

- **Zero backtest hot-path impact**: oracle byte-exact (`134 / 46189.87730727451`); determinism double-run identical; inertness test (no connectors/ccxt on backtest import) preserved; W1/W2 within the v1.5 baseline (15.7 s / 152.8 MB).
- **Decimal money edge held** — `to_money(str)` at the connector edge; no float money; no `Decimal(float)`.
- **Single UUIDv7**; business `time` from the venue timestamp, never wall-clock.
- **Indentation**: tabs in `okx.py`; 4 spaces in `venue_reconciler.py` and `core/`. Match the file; never normalize.
- **Test strictness**: `filterwarnings=["error"]`, `--strict-markers`, `--strict-config`; no new markers; `mypy --strict` clean on new code.
- **No new `EventType`** (preferred): reuse the `FillEvent` channel for the lifecycle signal and the direct `adopt_`/`release_` seam for the index teardown.
- **OPEN DECISIONS for discuss-phase (the "how"):**
  - R4 mechanism: promote `watch_orders` (emit terminal `FillEvent`s) **vs.** periodic REST order-poll.
  - `_seen_trade_ids` ring capacity value + structure (`OrderedDict` vs `deque`).
  - `release_` hook placement: `ReconcileManager` terminal transition (no-op-guarded for `SimulatedExchange`) **vs.** `OkxExchange`-self-managed from its own emitted fills + the status signal.
  - Late-echo / cancel-fill-race safety: drain-then-evict + rely on OKX terminal-status semantics + the DB `venue_trade_id` dedup backstop — confirm acceptable.

## Acceptance Criteria

- [ ] Correlation index holds **0 entries** for a fully-filled order after its fill is processed.
- [ ] Correlation index holds **0 entries** for a cancelled order after the cancel is confirmed mid-session.
- [ ] An out-of-band (engine-did-not-initiate) venue cancel **terminalizes the mirror mid-session** (not only at restart).
- [ ] `_seen_trade_ids` size stays **≤ configured capacity** under > capacity inserts; dedup within the window is still an idempotent no-op.
- [ ] A buffered late fill is **drained (emits its `FillEvent`) before** its correlation is released — no WR-02 regression.
- [ ] `tests/integration/test_backtest_oracle.py` **byte-exact** (`134 / 46189.87730727451`); determinism double-run identical.
- [ ] Inertness test **green** (no `connectors`/`ccxt.pro` after a backtest-root import); **no new `EventType`** added.
- [ ] `poetry run mypy itrader` clean; full suite green under `filterwarnings=["error"]` with **no new markers**.
- [ ] `watch_my_trades` money path **unchanged**; existing reconcile/fill tests green (incl. a cancel/fill-race scenario reporting the fill via `watch_my_trades`).

## Ambiguity Report

| Dimension          | Score | Min  | Status | Notes                                                                 |
|--------------------|-------|------|--------|-----------------------------------------------------------------------|
| Goal Clarity       | 0.90  | 0.75 | ✓      | Measurable: mid-session terminalization + bounded correlation, oracle byte-exact |
| Boundary Clarity   | 0.88  | 0.70 | ✓      | Explicit in/out; R4 mechanism deferred to discuss as "how"            |
| Constraint Clarity | 0.85  | 0.65 | ✓      | Hard constraints enumerated; ring-capacity value flagged open         |
| Acceptance Criteria| 0.85  | 0.70 | ✓      | 9 pass/fail checks                                                     |
| **Ambiguity**      | 0.125 | ≤0.20| ✓      | Only genuine openness is the R4 how-fork, not a what-gap              |

Status: ✓ = met minimum, ⚠ = below minimum (planner treats as assumption)

## Interview Log

Requirements derived from the 2026-07-03 design discussion (no separate Socratic loop — the conversation served as the interview):

| Round | Perspective     | Question summary                                              | Decision locked                                                                 |
|-------|-----------------|--------------------------------------------------------------|---------------------------------------------------------------------------------|
| 1     | Researcher      | Why do the OKX correlation maps leak?                        | Insert-only cache; no "release on terminal" half — terminalization lives in the order domain, invisible to the exchange |
| 2     | Simplifier      | Is this a leak-patch or a design gap?                        | Design gap — ownership duplication; encapsulate into `VenueCorrelationIndex`, evict by lifecycle, bound the dedup ring |
| 3     | Boundary Keeper | Do we need both watchers / a new event?                      | `watch_my_trades` mandatory (money + race fills); no new `EventType` — reuse `FillEvent` + direct `adopt_`/`release_` seam |
| 4     | Failure Analyst | Where's a cancel confirmed? Out-of-band web-UI cancel?       | Confirmed on `watch_orders`, currently dropped; **out-of-band caught nowhere mid-session** (reconcile is startup-only) — the linchpin requirement |
| 5     | Seed Closer     | What's the irreducible mid-session requirement vs the "how"? | A continuous order-status signal is required (locked); watch_orders-promotion vs REST-poll is the discuss-phase mechanism fork |

---

*Design origin: WR-05 (Phase 05 review) → reframed as missing continuous order-lifecycle reconciliation.*
*Spec created: 2026-07-03*
*Next step (when scope-approved): register as v1.7 Phase 7 in ROADMAP.md + REQUIREMENTS.md, lift this into `07-SPEC.md`, then `/gsd:discuss-phase 7` to resolve the R4 mechanism fork and the other open "how" decisions.*

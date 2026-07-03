---
slug: cr-01-fill-double-count
status: awaiting_human_verify
trigger: "CR-01 (Phase 5) code-review finding — live-trading fill double-count when the restart reconciler and the OKX trade stream both book the same economic venue trade"
created: 2026-07-03
updated: 2026-07-03
phase: 05-real-sandbox-path-reconciliation-persistence-live-drive
oracle_dark: true
---

# Debug Session: cr-01-fill-double-count

## Symptoms

- **Expected behavior:** A single economic venue trade (one OKX fill) is booked into
  portfolio position/cash exactly once, regardless of whether it arrives via the live
  `watch_my_trades` stream or is adopted by the startup `VenueReconciler`.
- **Actual behavior:** On restart, the reconciler mints a synthetic reconciling `FillEvent`
  for the venue-vs-store delta while the already-armed stream can re-deliver the same
  historical trade. Both fills are booked → position/cash double-count (e.g. 0.5 BTC booked
  as 1.0).
- **Error / failure mode:** Fails *safe* — the on-fill / on-bar drift compare detects the
  divergence and HALTs — but portfolio state is corrupted at the point of halt. No exception
  at book time (`PortfolioHandler.on_fill` has no dedup).
- **Timeline:** Introduced in Phase 5 with the restart-reconciliation + live-drive surface.
- **Reproduction:** Restart with an open/partially-filled venue order; stream re-delivers the
  historical trade after `connect()` arms it (streams spawn BEFORE `reconcile()` runs,
  `live_trading_system.py:1072-1112`) and the reconciler also emits its delta for the same
  trade before the store mirror reflects it.

## Root Cause (established during review + diagnosis, HIGH confidence)

Two independent emitters book the same economic venue trade with **no shared idempotency key**:

1. **Stream path** — `OkxExchange._handle_trade` → `_emit_fill` (okx.py:409) mints a fill and
   dedups on the venue trade id (`trade['id']`) via the exchange-local `_seen_trade_ids`
   set (okx.py:359-388).
2. **Reconciler path** — `VenueReconciler._emit_reconciling_fill` (venue_reconciler.py:286)
   mints a synthetic fill for the aggregated `venue_filled − order.filled_quantity` delta,
   **bypassing** `_handle_trade` and therefore `_seen_trade_ids`.

`FillEvent.new_fill` mints a fresh `uuid7` `fill_id` on every call (fill.py:142), so the two
fills for the same venue trade carry DIFFERENT `fill_id`s. `PortfolioHandler.on_fill` has no
dedup, so both settle → double-count. The `fill_id` is an internal *event* id, not the venue's
*trade* id, so a `fill_id`-based dedup (as the REVIEW's alternative suggested) is structurally
ineffective — confirmed with the user.

## Agreed Fix Design (Nautilus/FIX-grounded)

Promote the venue trade id to a first-class idempotency key, matching Nautilus `TradeId` /
FIX ExecID(17)/TradeID(1003):

1. **Add `venue_trade_id` field to `FillEvent`** (events/fill.py) — optional (default None so
   backtest/simulated fills stay unaffected and oracle-dark).
2. **Thread it to `Transaction`** (portfolio_handler settlement record).
3. **Stamp it at both emitters:**
   - `OkxExchange._emit_fill` (okx.py:409) — set `venue_trade_id = trade['id']`.
   - `VenueReconciler` — emit **one fill PER venue trade** (matching the stream's granularity)
     instead of one aggregated summed-delta fill, so each reconciling fill carries exactly one
     `venue_trade_id`. Preserve the adopt-once idempotency vs `order.filled_quantity`.
4. **Dedup at the settlement chokepoint** — `PortfolioHandler.on_fill` rejects a `FillEvent`
   whose `venue_trade_id` was already settled (a bounded per-portfolio or per-handler seen-set),
   so it works regardless of which emitter produced the fill. Backtest fills (venue_trade_id
   None) skip the dedup entirely → SMA_MACD byte-exact.

Scope guards:
- Order-level `Order.venue_order_id` already exists (venue_reconciler.py:199) — no change.
- Positions stay reconciled-by-quantity (drift compare) — NO venue position id (net-mode
  convention; `venue_position_id` only relevant under hedge mode, deferred).
- **Whole surface is oracle-dark (live/sandbox only).** The frozen SMA_MACD backtest must stay
  byte-exact — simulated fills carry `venue_trade_id = None` and take no new branch.

5. **Correct the CR-01 remediation note in `05-REVIEW.md`** so a future `--fix` pass does not
   apply the ineffective `fill_id`-dedup suggestion; point it at `venue_trade_id`.

## Current Focus

- status: fixing → verifying
- hypothesis: Root cause established (dual-emitter, no shared idempotency key). Implementing the
  agreed `venue_trade_id` fix.
- next_action: Implement across (1) FillEvent field + new_fill, (2) Transaction field +
  on_fill construction, (3) OkxExchange._emit_fill stamp, (4) VenueReconciler per-trade
  emission, (5) PortfolioHandler.on_fill bounded dedup guard; correct 05-REVIEW.md; add unit
  coverage; run oracle + Phase-5 live tests + mypy.
- implementation_notes:
  - FillEvent/Transaction are frozen msgspec.Struct (NOT dataclass); field = `venue_trade_id:
    str | None = None`. kw_only on FillEvent, defaults-last on Transaction.
  - Reconciler behavior change (per-trade emission) breaks the OLD single-fill assertion in
    test_two_sided_restart.py::test_downtime_fill_is_adopted_once — canned fixture has 2 trades
    (0.2 + 0.3 = 0.5). Updated to assert 2 per-trade fills each with its own venue_trade_id;
    adopt-once re-run still emits nothing (skip-budget = order.filled_quantity).
- reasoning_checkpoint:
  - hypothesis: two emitters book the same venue trade with no shared idempotency key.
  - falsification_test: a stream trade + reconciler adopt of the SAME venue_trade_id must settle
    ONCE after the fix; a backtest fill (venue_trade_id=None) must be byte-exact (oracle).
  - fix_rationale: venue_trade_id is the venue's TradeId (FIX ExecID) — the only stable
    cross-emitter key; dedup at the settlement chokepoint covers BOTH emitters.
  - blind_spots: partial-trade straddle at the filled_quantity boundary (skip-budget prorates
    one trade) — acceptable pre-existing edge, strictly better than the aggregate double-count.

## Evidence

- timestamp: 2026-07-03 — FillEvent.new_fill mints fresh uuid7 fill_id every call (fill.py:142);
  confirms fill_id cannot be a cross-emitter dedup key.
- timestamp: 2026-07-03 — okx.py:359-388 dedups stream trades on trade['id'] in _seen_trade_ids;
  okx.py:409 _emit_fill drops trade['id'] before minting the FillEvent (venue id not carried onto event).
- timestamp: 2026-07-03 — venue_reconciler.py:205-215 aggregates N trades into one summed-delta
  fill; _emit_reconciling_fill (venue_reconciler.py:286) puts it on the queue, bypassing _handle_trade.
- timestamp: 2026-07-03 — portfolio_handler.py:830 copies fill_event.fill_id onto Transaction;
  on_fill (portfolio_handler.py:782-858) has no dedup guard.
- timestamp: 2026-07-03 — FillEvent/Transaction are frozen msgspec.Struct (NOT dataclass); added
  `venue_trade_id: str | None = None` to both, threaded through new_fill/new_transaction.
- timestamp: 2026-07-03 — canned recon fixture (okx_recon_payloads.json) narrates the 0.5 downtime
  fill as TWO venue trades (0.2 + 0.3, ids TRD-0001/0002). Reconciler rewritten to emit one fill
  PER trade via a skip-budget over order.filled_quantity (adopt-once preserved).
- timestamp: 2026-07-03 — VERIFICATION all green: new tests/unit/portfolio/test_on_fill_venue_dedup.py
  (5) + test_on_fill_status_guard (6) + test_okx_fill_idempotency (10) = 21 pass; full portfolio +
  reconnect + two_sided_restart + bracket_restart_relink = 332 pass; execution+events+okx wiring/
  inertness = 310 pass; oracle byte-exact = 3 pass; mypy --strict = clean (225 files).

## Eliminated

- hypothesis: Dedup on Transaction.fill_id in on_fill fixes it — ELIMINATED: the two duplicate
  fills have different uuid7 fill_ids, so a fill_id set never matches; structurally ineffective.

## Resolution

root_cause: Two independent live emitters (OkxExchange trade stream + restart VenueReconciler)
  book the same economic venue trade with NO shared idempotency key. FillEvent.fill_id is a fresh
  uuid7 per emit, and PortfolioHandler.on_fill had no dedup — so both fills settle → position/cash
  double-count (0.5 BTC booked as 1.0), later HALTing on the drift compare with corrupted state.

fix: Promoted the venue trade id to a first-class cross-emitter idempotency key (FIX
  ExecID/Nautilus TradeId):
  1. FillEvent gains `venue_trade_id: str | None = None` (fill.py) threaded through new_fill.
  2. Transaction gains the same field (transaction.py) threaded through new_transaction.
  3. OkxExchange._emit_fill stamps `venue_trade_id = trade['id']` (okx.py).
  4. VenueReconciler now emits ONE reconciling fill PER venue trade (skip-budget over
     order.filled_quantity preserves adopt-once), each carrying its own venue_trade_id
     (venue_reconciler.py — replaced the aggregated summed-delta `_aggregate` path with
     `_adopt_order_trades`/`_order_trades`/`_trade_commission`).
  5. PortfolioHandler.on_fill rejects a fill whose venue_trade_id is already in a bounded
     FIFO settled-set (`_settled_venue_trade_ids`, cap 100k, recorded only after the
     transaction applies). Fills with venue_trade_id=None skip the guard → oracle byte-exact.
  6. Corrected the CR-01 remediation note in 05-REVIEW.md (repointed away from the ineffective
     fill_id-dedup / OKX-only mark_trade_seen suggestions to venue_trade_id).

verification: |
  - New tests/unit/portfolio/test_on_fill_venue_dedup.py (5) prove same-venue_trade_id settles
    ONCE, distinct ids both settle, venue_trade_id=None skips the guard (both settle), the id is
    threaded onto Transaction, and the ledger is bounded FIFO.
  - Updated test_two_sided_restart.py::test_downtime_fill_is_adopted_once → 2 per-trade fills each
    with its own venue_trade_id, summing to 0.5; adopt-once re-run emits nothing.
  - Green: portfolio+reconnect+two_sided_restart+bracket_restart_relink = 332 pass;
    execution+events+okx wiring/inertness = 310 pass; test_okx_fill_idempotency = 10 pass.
  - Oracle byte-exact (tests/integration/test_backtest_oracle.py) = 3 pass.
  - mypy --strict clean (225 source files).
  - PENDING human-verify: a real OKX-sandbox restart with an open/partially-filled order
    (stream re-delivers the historical trade after connect() arms it while the reconciler adopts
    the same trade) — the live end-to-end path cannot be exercised from the test harness.

files_changed:
  - itrader/events_handler/events/fill.py
  - itrader/portfolio_handler/transaction/transaction.py
  - itrader/execution_handler/exchanges/okx.py
  - itrader/portfolio_handler/reconcile/venue_reconciler.py
  - itrader/portfolio_handler/portfolio_handler.py
  - .planning/phases/05-real-sandbox-path-reconciliation-persistence-live-drive/05-REVIEW.md
  - tests/unit/portfolio/test_on_fill_venue_dedup.py (new)
  - tests/integration/test_two_sided_restart.py (updated assertions)

## Specialist Review

- specialist_hint: python
- verdict: LOOKS_GOOD — no findings at confidence >= 80 across all six changed/added files.
- checked:
  1. Money/Decimal — every venue float crosses via to_money(str(x)) in _emit_fill (okx.py:438,
     450-451) and _adopt_order_trades/_trade_commission (venue_reconciler.py:223,229,238,291);
     no Decimal(float) leak; straddling-trade commission proration stays Decimal-native.
  2. Dedup ordering — on_fill checks _settled_venue_trade_ids before mutating and marks only after
     transact_shares() succeeds (exception propagates before the mark → re-delivery not falsely
     treated as settled); _mark_venue_trade_settled guards `if venue_trade_id is not None` so None
     never enters the ledger; OrderedDict move_to_end + popitem(last=False) is a correct FIFO-cap.
  3. Adopt-once skip-budget — greedy prefix-consumption over the deterministically-sorted trade
     list (sorted by (timestamp, id)) against the incrementally-updated order.filled_quantity
     neither re-emits an applied trade nor drops a genuinely-new partial across multi-restart.
  4. Frozen-struct — FillEvent stays frozen=True, kw_only=True; `venue_trade_id: str | None = None`
     valid for a kw-only struct; new_fill returns fully-constructed, no post-construction mutation.
  5. Indentation — okx.py/transaction.py 100% tabs; venue_reconciler.py/fill.py 100% spaces;
     portfolio_handler.py new code matches that file's existing 4-space convention. No mixed diff.
- sub-threshold note (~40, not a finding): portfolio_handler.py:837 uses
  getattr(fill_event, "venue_trade_id", None) though the field is now always present; direct
  attribute access would be equivalent and marginally clearer. No functional impact.

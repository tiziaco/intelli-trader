"""
Pure order-matching engine for simulated execution.

Holds resting OrderEvents (stop/limit, AND market orders — the single
matching path, D-13) and decides which fill on each bar using intrabar
high/low, with pessimistic gap fills and exchange-enforced OCO between
bracket siblings.

Next-bar-open convention (D-01/D-13): a market order decided at tick T rests
in the book and fills unconditionally at the OPEN of the next bar it sees
(stamped T+1tf) — the backtest never trades on information it could not have
had. There is no immediate-execution path.

Same-bar bracket rule (RESEARCH Open Question 1, accepted) + parent-filled
gate (CR-01): bracket children are DORMANT while their parent entry order
still rests in the book — a child whose parent never triggered can neither
fill nor OCO-cancel its sibling (no position exists to protect). A parent
that fills THIS bar (market, limit, or stop entry) leaves the book in pass 1
and thereby unlocks its children against this SAME bar's high/low — entry at
the parent's fill price, children evaluated against the bar (real-exchange
semantics, matched by both reference engines). A parent that is NOT in the
book (never rested, or filled/cancelled on an earlier bar) does not gate:
children-only books remain evaluable. The parent's fill is emitted BEFORE
any child fill within one ``on_bar`` (pass-1 fills precede pass-2 fills),
and the existing STOP-beats-LIMIT sibling priority arbitrates a same-bar
double trigger.

Last-bar edge (bar-timing contract rule 7): an order decided on the FINAL
bar of the dataset never fills — no next bar exists, so it simply remains
resting in the book when the run ends. Not special-cased; documented and
regression-tested behavior.

This module has NO dependency on the event queue, fee/slippage models, or
logging side-effects. It takes OrderEvents and BarEvents in and returns plain
decision objects out, so it is fully deterministic and unit-testable.

Money (D-12/D-14): matching is Decimal end-to-end — order prices and Bar OHLC
are both Decimal, so trigger comparisons and gap-fill min/max run in the
Decimal domain with NO quantization (never-round-prices: rounding happens only
at money boundaries, never inside matching).

DEF-01-C (known limitation, blessed into the M1 oracle): the engine has no
margin/liquidation model. A short position that is never liquidated can drive
total equity negative — this is current-behavior-to-preserve, routed to the
Phase 7 (M5b) risk layer per D-07. Documentation only; no matching behavior
encodes margin.
"""

from decimal import Decimal, InvalidOperation
from typing import List, Optional, Tuple

import msgspec

from itrader.core.ids import OrderId
from itrader.core.money import to_money
from itrader.events_handler.events import OrderEvent, BarEvent
from itrader.config import TrailType
from itrader.core.enums import OrderType, Side


class TrailState(msgspec.Struct, gc=False):
    """Mutable per-trailing-order ratchet bookkeeping (D-TRAIL-6).

    Lives in a ``MatchingEngine``-owned side-table parallel to ``_resting`` —
    NOT on the frozen ``OrderEvent`` (a ``frozen=True`` ``msgspec.Struct`` that
    would raise ``AttributeError`` on set). The static trail declaration
    (``trail_type``/``trail_value``) stays on the immutable event; the running
    extreme and the active stop level are the only mutable state and live here.

    ``hwm``/``lwm`` are carried at FULL 28-digit Decimal precision (D-TRAIL-8) —
    only ``current_stop`` (the level used for the trigger comparison/fill) is
    carried at full precision. For a long sell-stop only ``hwm`` advances; for a
    short buy-stop only ``lwm`` advances.
    """
    hwm: Decimal           # running max of closed-bar highs (long); seed = fill price
    lwm: Decimal           # running min of closed-bar lows (short); seed = fill price
    current_stop: Decimal  # active ratcheted stop, derived from bars <= N-1


class FillDecision(msgspec.Struct, frozen=True, kw_only=True, gc=False):
    """One resting order has matched and should be filled.

    Full-quantity contract (D-06): a fill always covers the order's entire
    quantity — partial fills do not exist in the engine, so the decision
    carries no quantity field (the exchange reads ``order_event.quantity``).
    ``fill_price`` is Decimal, the product of Decimal-native trigger/gap math
    against Decimal Bar OHLC (D-12).
    """
    order_event: OrderEvent
    fill_price: Decimal
    reason: str


class CancelDecision(msgspec.Struct, frozen=True, kw_only=True, gc=False):
    """One resting order should be cancelled (OCO sibling of a fill)."""
    order_event: OrderEvent
    reason: str


class MatchingEngine:
    """Resting-order book + trigger/OCO evaluation."""

    def __init__(self) -> None:
        # Order ids have been UUIDv7-backed since M2 (D-12) — the book is
        # keyed by OrderId, never by int.
        # CACHE-CLASS: (a-engine) resting-order working state — see docs/CACHE-CLASSIFICATION.md
        self._resting: dict[OrderId, OrderEvent] = {}
        # D-TRAIL-6: mutable ratchet state for resting TRAILING_STOP orders,
        # keyed by the SAME OrderId as ``_resting`` and popped at every
        # ``_resting.pop`` site so no entry leaks for a filled/cancelled order.
        self._trails: dict[OrderId, TrailState] = {}
        # WR-03 / D-TRAIL-8: the computed trailing stop is carried at FULL Decimal
        # precision exactly like every other matching price (D-14 never-round-prices).
        # The engine is a pure, dependency-free module with no Instrument access,
        # so it does NOT quantize the stop — the one and only construction site
        # (SimulatedExchange) wires no resolver, so the former optional
        # instrument-resolver quantize seam was dead on every real run and has
        # been removed. The running extreme (hwm/lwm) is full precision too —
        # the genuine D-TRAIL-8 risk (quantizing the running extreme, causing
        # ratchet drift) cannot occur because nothing quantizes here.

    # --- book management ---

    def submit(self, order_event: OrderEvent) -> None:
        """Add a resting order (every NEW order rests here — stop, limit,
        and market alike; D-13 single matching path).

        A TRAILING_STOP additionally seeds its side-table TrailState from the
        order's positive initial ``price`` (the fill-anchored INITIAL stop set
        by 05-03's declaration; D-TRAIL-3). HWM/LWM seed to that same anchor so
        the first ratcheted level can never loosen below the declared initial
        stop, and ``current_stop`` is the declared initial stop verbatim.
        """
        if order_event.order_id is None:
            raise ValueError("Cannot rest an order with no order_id")
        self._resting[order_event.order_id] = order_event
        if order_event.order_type == OrderType.TRAILING_STOP:
            self._trails[order_event.order_id] = self._seed_trail(order_event)

    def cancel(self, order_id: OrderId) -> bool:
        """Remove a resting order. Returns True if it was present."""
        self._trails.pop(order_id, None)
        return self._resting.pop(order_id, None) is not None

    def modify(self, order_id: OrderId, new_price: Optional[Decimal] = None,
               new_quantity: Optional[Decimal] = None) -> bool:
        """Replace a resting order with an updated copy. Returns True if present.

        Replace-in-book: the stored OrderEvent is never mutated in place —
        ``msgspec.structs.replace`` builds an updated copy from the None-guarded
        changed kwargs and stores it back under the same key. ``replace``
        deliberately PRESERVES ``order_id`` (and ``event_id`` once events
        carry one): a MODIFY changes an order's terms, not its identity —
        it is the same instruction, amended (RESEARCH Open Question 2).

        D-22: the annotation follows the event retype (Decimal money);
        ``to_money`` normalizes so a legacy float caller still stores
        Decimal in the book (identity on Decimal input).
        """
        order = self._resting.get(order_id)
        if order is None:
            return False
        # None-guarded: an omitted kwarg keeps the resting order's own value.
        updated = msgspec.structs.replace(
            order,
            price=order.price if new_price is None else to_money(new_price),
            quantity=order.quantity if new_quantity is None else to_money(new_quantity),
        )
        self._resting[order_id] = updated
        # WR-01: a TRAILING_STOP's ratchet state (hwm/lwm/current_stop) is seeded
        # from the order's reference ``price``. A MODIFY changes that reference,
        # so the parallel side-table MUST be re-seeded — otherwise the engine
        # keeps triggering against the STALE level derived from the original
        # price and the modify silently has no effect on the dynamic trigger.
        # Re-seed from the updated order so the ratchet restarts from the new
        # reference (the favorably-only invariant resumes from there).
        if updated.order_type == OrderType.TRAILING_STOP:
            self._trails[order_id] = self._seed_trail(updated)
        return True

    def has_order(self, order_id: OrderId) -> bool:
        return order_id in self._resting

    def get_order(self, order_id: OrderId) -> Optional[OrderEvent]:
        return self._resting.get(order_id)

    # --- trailing-stop ratchet bookkeeping (D-TRAIL-1/2/3/8) ---

    def _seed_trail(self, order: OrderEvent) -> TrailState:
        """Build the initial TrailState for a TRAILING_STOP entering the book.

        D-TRAIL-3: HWM (long) / LWM (short) seed from the entry/reference price
        (``order.price`` — the fill-anchored reference, the same value the
        D-TRAIL-7 validator gates ``trail_value`` against). The initial active
        stop is computed from that seed at full precision (WR-03 — no quantize),
        so the order is immediately triggerable on its first bar against the
        level derived from its entry (bars <= N-1, where N-1 is the entry bar).
        """
        anchor = order.price                       # full-precision Decimal reference
        stop = self._compute_stop(order, anchor)
        # Seed BOTH water-marks to the anchor: only the relevant one advances
        # (hwm for a long sell-stop, lwm for a short buy-stop); the other is
        # inert. Keeping both seeded avoids a None branch in the ratchet step.
        return TrailState(hwm=anchor, lwm=anchor, current_stop=stop)

    def _compute_stop(self, order: OrderEvent, watermark: Decimal) -> Decimal:
        """Compute the stop level for ``watermark`` per the trail.

        Long sell-stop:  stop = HWM - trail (PRICE) | HWM * (1 - trail) (PERCENT)
        Short buy-stop:  stop = LWM + trail (PRICE) | LWM * (1 + trail) (PERCENT)

        The arithmetic runs at full Decimal precision off the full-precision
        watermark (D-TRAIL-8); the returned stop is carried at full precision
        like every other matching price (D-14 never-round-prices — WR-03: the
        engine does NOT quantize the stop, the dead resolver seam was removed).
        """
        trail_value = order.trail_value
        trail_type = order.trail_type
        if trail_value is None or trail_type is None:
            # Defensive: a TRAILING_STOP without a viable trail is rejected by
            # D-TRAIL-7 before it rests; never reached on the validated path.
            return watermark
        if order.action is Side.SELL:                       # long sell-stop
            if trail_type == TrailType.PRICE:
                raw = watermark - trail_value
            else:                                           # PERCENT
                raw = watermark * (Decimal("1") - trail_value)
        else:                                               # short buy-stop
            if trail_type == TrailType.PRICE:
                raw = watermark + trail_value
            else:                                           # PERCENT
                raw = watermark * (Decimal("1") + trail_value)
        # WR-03 / D-14: carried at full precision — the engine never quantizes
        # the stop (the dead instrument-resolver seam was removed).
        return raw

    def _ratchet_trail(self, order: OrderEvent, state: TrailState, bar: BarEvent) -> None:
        """Advance HWM/LWM from THIS bar's extreme and recompute the stop for
        the NEXT bar (D-TRAIL-1/D-TRAIL-2 — runs at the END of on_bar).

        Long: hwm = max(hwm, bar.high); short: lwm = min(lwm, bar.low) — extremes,
        not close (D-TRAIL-1). The recomputed candidate is applied favorably-only
        (long: current_stop never decreases; short: never increases) so the stop
        ratchets but never loosens (the ratchet invariant)."""
        bar_struct = bar.bars.get(order.ticker)
        if bar_struct is None:
            return                                          # no bar this tick — no ratchet
        if order.action is Side.SELL:                       # long sell-stop
            state.hwm = max(state.hwm, bar_struct.high)     # full precision (D-TRAIL-8)
            candidate = self._compute_stop(order, state.hwm)
            state.current_stop = max(state.current_stop, candidate)   # non-decreasing
        else:                                               # short buy-stop
            state.lwm = min(state.lwm, bar_struct.low)
            candidate = self._compute_stop(order, state.lwm)
            state.current_stop = min(state.current_stop, candidate)   # non-increasing

    # --- matching ---

    def _evaluate(self, order: OrderEvent, bar: BarEvent) -> Optional[Decimal]:
        """Return the fill price if `order` triggers on `bar`, else None."""
        ticker = order.ticker
        bar_struct = bar.bars.get(ticker)
        if bar_struct is None:
            # No bar for this ticker at T (sparse universe / data gap) —
            # same no-data semantics as the legacy Optional accessors.
            return None
        # D-12: Decimal end-to-end — Bar OHLC is Decimal by construction and
        # order.price is Decimal money, so the trigger comparisons and min/max
        # gap-fill math below run in the Decimal domain. NO quantization here
        # (D-14 never-round-prices): rounding belongs to money boundaries only.
        open_ = bar_struct.open
        high = bar_struct.high
        low = bar_struct.low
        trigger = order.price

        if order.order_type == OrderType.MARKET:
            # next-bar market order: unconditional fill at the open
            return open_

        if order.order_type == OrderType.STOP:
            if order.action is Side.SELL:           # stop-loss on a long
                if low <= trigger:
                    return min(open_, trigger)      # pessimistic gap-down
            else:                                   # BUY stop (cover short)
                if high >= trigger:
                    return max(open_, trigger)      # pessimistic gap-up

        elif order.order_type == OrderType.TRAILING_STOP:
            # D-TRAIL-2/D-TRAIL-4: a trailing stop evaluates EXACTLY like a STOP,
            # but against the ACTIVE ratcheted level from the side-table (derived
            # from bars <= N-1), NOT this bar's extreme. The level is advanced for
            # the NEXT bar by the ratchet step at the END of on_bar — never here.
            # Reuses the STOP gap-aware min/max(open_, trigger) rule verbatim.
            state = (self._trails.get(order.order_id)
                     if order.order_id is not None else None)
            if state is None:
                return None                         # no side-table entry — not armed
            trail_trigger = state.current_stop
            if order.action is Side.SELL:           # long trailing sell-stop
                if low <= trail_trigger:
                    return min(open_, trail_trigger)        # pessimistic gap-down
            else:                                   # short trailing buy-stop
                if high >= trail_trigger:
                    return max(open_, trail_trigger)        # pessimistic gap-up

        elif order.order_type == OrderType.LIMIT:
            # Limit-or-better (D-03): a limit fill can never be worse than the
            # limit price. On a favorable gap the order fills at the (better)
            # open; an in-bar touch fills at the limit exactly. Asymmetric with
            # the pessimistic open-based gap fill used for stops by design.
            if order.action is Side.SELL:           # take-profit on a long
                if open_ >= trigger:
                    return open_                    # gap-through: better open
                elif high >= trigger:
                    return trigger                  # in-bar touch: at limit
            else:                                   # BUY limit (cover short)
                if open_ <= trigger:
                    return open_                    # gap-through: better open
                elif low <= trigger:
                    return trigger                  # in-bar touch: at limit

        return None

    def on_bar(self, bar: BarEvent) -> Tuple[List[FillDecision], List[CancelDecision]]:
        """
        Evaluate all resting orders against `bar` in two passes.

        - Candidates are orders whose trigger price is reached this bar;
          resting MARKET orders fill unconditionally at the bar's open
          (next-bar-open convention, D-01/D-13).
        - Pass 1 — parents/standalone (``parent_order_id is None``): each
          fills independently (no bracket arbitration) and is removed from
          the book BEFORE pass 2 runs.
        - Pass 2 — bracket children: a child is eligible only if its
          ``parent_order_id`` no longer keys the book (parent filled in
          pass 1 this bar, filled/cancelled on an earlier bar, or never
          rested). A child whose parent STILL RESTS is dormant — not a
          candidate, cannot fill, cannot trigger OCO cancels (CR-01
          parent-filled gate).
        - For bracket siblings (same non-None parent_order_id), at most one
          fills per bar; if both a STOP and a LIMIT are candidates, the STOP
          wins (pessimistic same-bar priority).
        - When a bracket leg fills, all other resting orders in that bracket
          are cancelled (OCO), even if they did not trigger this bar.
        - Same-bar bracket rule: a parent filling THIS bar (market, limit,
          or stop entry) does NOT shield its children — having left the book
          in pass 1, they are evaluated against the same bar's high/low and
          may fill on the bar that filled their parent. Pass-1 fills precede
          pass-2 fills in the returned list, so the entry settles before the
          protective exit (parents-before-children contract).
        """
        # --- Pass 1: parents/standalone (parent_order_id is None) ---------
        fills: List[FillDecision] = []
        for order in list(self._resting.values()):
            if order.parent_order_id is not None:
                continue                            # children belong to pass 2
            try:
                price = self._evaluate(order, bar)
            except (TypeError, ValueError, KeyError, InvalidOperation):
                # A single malformed resting order (e.g. price=None, missing bar
                # field, NaN/sNaN Decimal trigger) must not drop the whole bar.
                # decimal.InvalidOperation is an ArithmeticError, NOT a
                # ValueError, so it must be named explicitly for the
                # Decimal-end-to-end matching domain (CR-01). Programming errors
                # (AttributeError, etc.) are NOT swallowed — they propagate.
                continue
            if price is not None and order.order_id is not None:
                fills.append(FillDecision(
                    order_event=order,
                    fill_price=price,
                    reason=self._fill_reason(order),
                ))
                # Leaving the book NOW is what unlocks this parent's bracket
                # children for pass 2 on this same bar (CR-01).
                self._resting.pop(order.order_id, None)
                self._trails.pop(order.order_id, None)   # D-TRAIL-6: no leak

        # --- Pass 2: bracket children whose parent has left the book ------
        # 1. Collect candidate fills (price reached AND parent not resting).
        candidates: dict[OrderId, Decimal] = {}
        for order in list(self._resting.values()):
            if order.parent_order_id is None:
                continue                            # parents already handled
            if order.parent_order_id in self._resting:
                # CR-01 parent-filled gate: the parent entry still rests, so
                # no position exists to protect — the child is dormant.
                continue
            try:
                price = self._evaluate(order, bar)
            except (TypeError, ValueError, KeyError, InvalidOperation):
                continue                            # same malformed-order semantics (incl. NaN Decimal, CR-01)
            if price is not None and order.order_id is not None:
                candidates[order.order_id] = price

        if not candidates:
            # No child fills this bar — still run the END-of-on_bar ratchet so
            # resting trailing orders advance their level for the NEXT bar
            # (D-TRAIL-2 holds on every bar, fill or no fill).
            self._run_ratchet_step(bar)
            return fills, []

        # 2. Resolve, per bracket, which single child fills.
        chosen: dict[OrderId, Decimal] = {}   # order_id -> fill_price
        seen_brackets = set()
        for order_id, price in candidates.items():
            order = self._resting[order_id]
            bracket = order.parent_order_id
            if bracket is None:
                continue                            # unreachable: pass-2 candidates are children
            if bracket in seen_brackets:
                continue                            # already chose a leg for this bracket
            seen_brackets.add(bracket)
            winner_id = self._pick_bracket_winner(bracket, candidates)
            chosen[winner_id] = candidates[winner_id]

        # 3. Build child fills and OCO cancels. Appending to the pass-1 list
        # preserves the parents-before-children fill ordering by construction
        # (the former post-hoc stable sort is no longer needed).
        cancels: List[CancelDecision] = []
        cancelled_ids: set[Optional[OrderId]] = set()

        for order_id, price in chosen.items():
            order = self._resting[order_id]
            fills.append(FillDecision(
                order_event=order,
                fill_price=price,
                reason=self._fill_reason(order),
            ))
            bracket = order.parent_order_id
            # O(n) sibling scan per filled bracket; negligible at backtest
            # scale (< ~100 resting orders per symbol). Pre-index by
            # parent_order_id if the book ever grows to thousands.
            for sibling in list(self._resting.values()):
                if (sibling.parent_order_id == bracket
                        and sibling.order_id != order_id
                        and sibling.order_id not in cancelled_ids):
                    cancels.append(CancelDecision(
                        order_event=sibling, reason="OCO - sibling filled"))
                    cancelled_ids.add(sibling.order_id)

        # 4. Remove filled + cancelled children from the book (pass-1 fills
        # were already popped as they filled). Pop the parallel side-table at
        # every pop site so a filled/OCO-cancelled trailing order leaks no
        # ratchet state (D-TRAIL-6).
        for order_id in chosen:
            self._resting.pop(order_id, None)
            self._trails.pop(order_id, None)
        for cancel in cancels:
            if cancel.order_event.order_id is not None:
                self._resting.pop(cancel.order_event.order_id, None)
                self._trails.pop(cancel.order_event.order_id, None)

        # END-of-on_bar ratchet (D-TRAIL-1/D-TRAIL-2) — see _run_ratchet_step.
        self._run_ratchet_step(bar)

        return fills, cancels

    def _run_ratchet_step(self, bar: BarEvent) -> None:
        """Advance every still-resting trailing order's level for the NEXT bar.

        D-TRAIL-1/D-TRAIL-2: runs at the END of on_bar, AFTER both fill passes
        and OCO cancels resolve. The level a trailing order triggers against on
        bar N is therefore always derived from bars <= N-1, never N — the
        phase-defining look-ahead-safety invariant. A "tall bar" whose high
        ratchets the stop AND whose low pierces the new tighter level does NOT
        fill on that bar; the new level is active only on the following bar.
        FORBIDDEN: advancing HWM/LWM before/inside the fill passes (same-bar
        ratchet-and-trigger)."""
        for order_id, state in self._trails.items():
            order = self._resting.get(order_id)
            if order is None:
                continue                            # filled/cancelled this bar
            self._ratchet_trail(order, state, bar)

    def _pick_bracket_winner(self, bracket: OrderId,
                             candidates: dict[OrderId, Decimal]) -> OrderId:
        """Among candidate legs of a bracket, prefer a STOP (pessimistic).

        D-TRAIL-5: a trailing SL is a (dynamic) stop — it keeps the same
        STOP-beats-LIMIT same-bar priority as a fixed SL, so TRAILING_STOP is
        included in the stop preference alongside STOP."""
        leg_ids = [oid for oid in candidates
                   if self._resting[oid].parent_order_id == bracket]
        for oid in leg_ids:
            if self._resting[oid].order_type in (OrderType.STOP, OrderType.TRAILING_STOP):
                return oid
        return leg_ids[0]

    @staticmethod
    def _fill_reason(order: OrderEvent) -> str:
        if order.order_type == OrderType.STOP:
            return "stop triggered"
        if order.order_type == OrderType.TRAILING_STOP:
            return "trailing stop triggered"
        if order.order_type == OrderType.LIMIT:
            return "limit triggered"
        return "market fill"

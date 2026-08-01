"""Pre-trade risk backstop for the live engine.

``PreTradeThrottle`` is an operator-defined risk backstop — a pre-trade sibling of
``EnhancedOrderValidator`` that rejects risk-INCREASING order flow BEFORE submission when
it exceeds a configured submit-rate or a per-order max-notional cap. It protects a live
run from a runaway strategy, a bad loop or a fat-finger; it is NOT a venue-compliance
tool, since the connector's ccxt token bucket already owns the exchange's API rate limits.

Design contract:

- Caps are owner-set STATIC config (``config.safety.throttle``). Nothing mutates them at
  runtime — the ``ConfigRouter`` has no throttle scope.
- On a breach the throttle REJECTS that one order by emitting a ``FillEvent(REFUSED)`` on
  the bus — the same egress ``EnhancedOrderValidator`` uses, so the order mirror
  reconciles REFUSED->REJECTED — and order flow continues. It is NOT a pause and NOT a
  halt: a per-order risk cap is not a kill switch.
- Caps are a single GLOBAL engine-wide set. Per-``account_id`` keying is a shaped seam,
  not built.
- The rate limiter is a sliding-window COUNT — a deque of timestamps pruned-left off the
  INJECTED clock, never wall clock.
- The throttle reuses the SINGLE shared ``classify`` predicate that travels with
  ``SafetyController``, and meters ``ENTRY`` ONLY. ``CANCEL`` and ``PROTECTIVE``
  (bracket-child) orders bypass unconditionally and are NOT counted toward the window.
  That is what makes "reject that order" safe by construction: the throttle physically
  cannot reject a stop, a bracket child or a cancel. It also means a MODIFY/REPLACE on a
  protective child bypasses, so no notional-delta metering of modifies is needed.
- On breach it increments a ``breach_count`` read-model counter AND emits a
  WARNING-severity ``ErrorEvent`` de-duped by a min-interval off the injected clock, so a
  runaway breach burst cannot flood the ERROR route. Only declared ErrorEvent fields plus
  a fixed message are bound, so no order payload or ``str(exc)`` can leak.
- The max-notional check uses the order's limit price when present, else the last mark
  the order layer stamped — carried on ``OrderEvent.price`` either way. ``size * price``
  is computed in ``Decimal`` end-to-end, with no ``float`` coercion on the notional path.

A plain injected collaborator: injected ``ThrottleSettings``, an injected clock
(determinism seam), an injected bus (the REFUSED + WARNING egress), and a bound logger.
No facade back-reference. This module is NEVER barrel-exported from any
``trading_system`` package — it is constructed only by ``build_live_system`` — so the
inertness gate stays green and the backtest path never meters an order.
"""

from collections import deque
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Optional

from itrader.config.safety import ThrottleSettings
from itrader.core.clock import Clock
from itrader.core.enums import ErrorSeverity, EventType, OrderRiskRole
from itrader.events_handler.events import ErrorEvent, FillEvent
from itrader.logger import get_itrader_logger
from itrader.trading_system.safety.safety_controller import classify

# The fixed machine-readable identity for the breach WARNING ErrorEvent. Fixed
# literals only (never str(exc) or an order payload) so no secret can leak when the
# WARNING crosses the ERROR route.
_BREACH_ERROR_SOURCE = "pre_trade_throttle"
_BREACH_ERROR_TYPE = "ThrottleBreach"
_BREACH_ERROR_MESSAGE = "order rejected: submit-rate/notional cap exceeded"
_BREACH_ERROR_OPERATION = "pre_submit"

# A rejected pre-submit order never executed, so the REFUSED mirror fill carries zero
# commission (mirrors EnhancedOrderValidator's REFUSED egress).
_ZERO_COMMISSION = Decimal("0")


class PreTradeThrottle:
    """Operator pre-trade risk backstop — meters ENTRY only.

    Constructed once inside ``build_live_system`` and invoked by the runner at the
    pre-submit boundary. Reuses the shared ``classify`` predicate so it can physically
    never touch a CANCEL/PROTECTIVE order; only risk-opening ENTRY orders are metered
    against the sliding-window rate cap and the per-order max-notional cap. A breach
    rejects that one order via ``FillEvent(REFUSED)``, increments the read-model
    ``breach_count``, and emits a de-duped WARNING ``ErrorEvent``.

    Parameters
    ----------
    settings : ThrottleSettings
        The static caps from ``config.safety.throttle``.
    clock : Clock
        The INJECTED determinism clock. The sliding window and the WARNING dedup read
        ``clock.now()`` — NEVER wall clock.
    bus : Any
        The engine ``global_queue``/bus. Only ``.put`` is used — the
        ``FillEvent(REFUSED)`` egress and the WARNING ``ErrorEvent`` egress.
    """

    def __init__(
        self,
        *,
        settings: ThrottleSettings,
        clock: Clock,
        bus: Any,
    ) -> None:
        self.logger = get_itrader_logger().bind(component="PreTradeThrottle")
        self._settings = settings
        self._clock = clock
        self._bus = bus
        # Sliding-window rate limiter — a deque of ENTRY submit timestamps (datetimes off
        # the injected clock), pruned-left on each evaluation.
        self._stamps: "deque[datetime]" = deque()
        self._breach_count = 0
        # Last WARNING emission time (injected clock) for the min-interval dedup.
        self._last_warn: Optional[datetime] = None

    @property
    def breach_count(self) -> int:
        """The read-model breach counter."""
        return self._breach_count

    def allow(self, event: Any) -> bool:
        """Meter one pre-submit order; ``True`` to submit, ``False`` if rejected.

        The pre-submit gate, invoked by the runner ahead of the dispatch gate. The branch
        order is load-bearing:

        0. ORDER-only top-gate: any event whose ``type`` is not ``EventType.ORDER`` returns
           ``True`` IMMEDIATELY — bypass, meters nothing. Past this gate the classifier
           branch provably sees an ``OrderEvent``, so the throttle does not depend on the
           runner's call-site type gate for safety.
        1. ``role = classify(event)``. A CANCEL or PROTECTIVE role returns ``True``
           IMMEDIATELY, WITHOUT touching the window or the notional check, so a
           risk-reducing order is never counted and can never be rejected.
        2. For an ENTRY only: prune-left the sliding window off the injected clock and
           evaluate the rate breach (``len(stamps) >= max_orders``) AND the max-notional
           breach (Decimal ``size * price > max_notional_per_order``).
        3. On NO breach: record the timestamp and return ``True``.
        4. On a breach (rate OR notional): do NOT record; emit ``FillEvent(REFUSED)``,
           increment ``breach_count``, emit the de-duped WARNING, and return ``False``.
        """
        # (0) ORDER-only top-gate, BEFORE classify() ever runs. Mirrors classify()'s
        # defensive idiom — no AttributeError on a typeless object.
        if getattr(event, 'type', None) is not EventType.ORDER:
            return True

        # (1) Reuse the SINGLE shared classifier. CANCEL/PROTECTIVE bypass uncounted —
        # never metered, never rejected.
        if classify(event) is not OrderRiskRole.ENTRY:
            return True

        # (2) ENTRY only past here. Prune the sliding window off the INJECTED clock before
        # measuring the rate.
        now = self._clock.now()
        cutoff = now - timedelta(seconds=self._settings.window_s)
        while self._stamps and self._stamps[0] < cutoff:
            self._stamps.popleft()
        rate_breach = len(self._stamps) >= self._settings.max_orders
        notional_breach = self._exceeds_notional(event)

        # (4) Breach -> reject WITHOUT recording: a rejected order must not consume a slot
        # in the window. Rate OR notional trips the reject.
        if rate_breach or notional_breach:
            self._reject(event, now, rate_breach=rate_breach,
                         notional_breach=notional_breach)
            return False

        # (3) No breach -> record the metered ENTRY and allow submission.
        self._stamps.append(now)
        return True

    def _exceeds_notional(self, event: Any) -> bool:
        """Whether the ENTRY's notional exceeds the per-order cap.

        The reference price is the order's limit price when present, else the last mark —
        both carried on ``OrderEvent.price``. ``size * price`` is computed in ``Decimal``
        end-to-end, with no ``float`` coercion. Any event reaching here is guaranteed an
        ``OrderEvent`` by ``allow()``'s ORDER-only top-gate, whose ``price``/``quantity``
        are non-optional ``Decimal`` by construction.
        """
        price = getattr(event, "price")
        quantity = getattr(event, "quantity")
        notional = abs(price * quantity)
        return bool(notional > self._settings.max_notional_per_order)

    def _reject(
        self,
        event: Any,
        now: datetime,
        *,
        rate_breach: bool,
        notional_breach: bool,
    ) -> None:
        """Reject one over-cap ENTRY: REFUSED fill + breach counter + de-duped WARNING.

        Emits ``FillEvent(REFUSED)`` on the bus — the SAME egress
        ``EnhancedOrderValidator`` uses, with the order's own price/quantity and zero
        commission — so the order mirror reconciles REFUSED->REJECTED. Order flow
        continues; this is not a pause or a halt.

        Always increments the read-model ``breach_count``, but emits the WARNING-severity
        ``ErrorEvent`` only when at least ``warn_min_interval_s`` have elapsed (off the
        injected clock) since the last one, so a breach burst cannot flood the ERROR route.
        Only declared ErrorEvent fields plus a fixed message are bound.
        """
        # The REFUSED mirror fill defaults its time to the order's own decision time — an
        # admission-time outcome, matching the validator's REFUSED egress.
        self._bus.put(FillEvent.new_fill(
            'REFUSED', event,
            price=event.price,
            quantity=event.quantity,
            commission=_ZERO_COMMISSION,
        ))

        # The read-model counter always increments; every breach is counted.
        self._breach_count += 1
        self.logger.warning(
            'Pre-trade throttle rejected an ENTRY order (rate_breach=%s, '
            'notional_breach=%s) — FillEvent(REFUSED) emitted (D-02)',
            rate_breach, notional_breach)

        # De-dup the WARNING ErrorEvent by a min-interval off the injected clock so a breach
        # burst cannot flood the ERROR route.
        if (self._last_warn is not None
                and (now - self._last_warn).total_seconds()
                < self._settings.warn_min_interval_s):
            return
        self._last_warn = now
        self._bus.put(ErrorEvent(
            time=now,
            source=_BREACH_ERROR_SOURCE,
            error_type=_BREACH_ERROR_TYPE,
            error_message=_BREACH_ERROR_MESSAGE,
            operation=_BREACH_ERROR_OPERATION,
            severity=ErrorSeverity.WARNING,
        ))

"""Pre-trade risk backstop for the live engine (SAFE-06, D-01..D-10).

``PreTradeThrottle`` is a net-new operator-defined risk backstop — a pre-trade
sibling of ``EnhancedOrderValidator`` that rejects risk-INCREASING order flow
BEFORE submission when it exceeds a configured submit-rate (D-04 sliding window)
or a per-order max-notional cap (D-10). It protects the first live run from a
runaway strategy / bad loop / fat-finger; it is NOT a venue-compliance tool (the
connector's ccxt token bucket already owns the exchange's API rate limits, D-01).

Design contract (locked by 07-CONTEXT decisions):

- **D-01/D-07/D-14:** caps are owner-set static config (``config.safety.throttle``
  — 10 orders / 10s + $25k, ON by default). This plan ships STATIC caps and merely
  consumes the settings object; NO runtime ``ConfigUpdateEvent`` mutation is wired
  here (that is P9).
- **D-02:** on a breach the throttle REJECTS that one order — emits a
  ``FillEvent(REFUSED)`` on the bus (the same egress ``EnhancedOrderValidator``
  uses, so the order mirror reconciles REFUSED->REJECTED) — order flow continues.
  It is NOT a pause and NOT a halt (a per-order risk cap is not a kill switch).
- **D-03:** caps are a single GLOBAL engine-wide set. Per-``account_id`` keying is
  a shaped seam for P11 multi-portfolio-live — NOT built now.
- **D-04:** the rate limiter is a sliding-window COUNT — a deque of timestamps
  pruned-left off the INJECTED clock (determinism seam), never wall clock.
- **D-05/D-16:** the throttle reuses the SINGLE shared ``classify`` predicate that
  travels with ``SafetyController`` — it meters ``ENTRY`` ONLY. ``CANCEL`` and
  ``PROTECTIVE`` (bracket-child) orders bypass unconditionally and are NOT counted
  toward the window. This makes D-02's "reject that order" safe by construction:
  the throttle physically cannot reject a stop, bracket child, or cancel.
- **D-06:** fires at the pre-submit (ORDER->execution) boundary invoked by the
  runner, ahead of the dispatch gate. Wiring lands in Plan 06; this plan authors
  the throttle + tests only.
- **D-08:** metering is ENTRY-only — a MODIFY/REPLACE on a protective child bypasses
  via the PROTECTIVE role, so no notional-delta metering of modifies is added here.
- **D-09:** on breach, increment a ``breach_count`` read-model counter (surfaced for
  P9's stats/state UI via a thin accessor) AND emit a WARNING-severity ``ErrorEvent``
  de-duped by a min-interval off the injected clock, so a runaway breach burst
  cannot flood the ERROR route. Only declared ErrorEvent fields + a fixed message
  are bound (V7 secret-scrub — no order payload / str(exc) leak, T-07-01).
- **D-10:** the max-notional check uses the order's limit price when present, else
  the last mark / best-available the order layer stamped — carried on the
  ``OrderEvent.price`` field either way (LIMIT price for LIMIT orders; the
  decision-bar-close mark estimate for MARKET/STOP orders). size * price is computed
  in ``Decimal`` end-to-end — NO ``float`` coercion on the notional path (money policy).

Collaborator shape (analog: ``trading_system/live_runner.py``): a plain injected
collaborator — injected ``ThrottleSettings``, an injected clock (determinism seam),
an injected bus (the REFUSED + WARNING egress), and a bound logger. NO facade
back-reference. Import-inert: imports stdlib + config + the shared ``classify`` +
event classes only (no ccxt.pro / no SQL / no async), and this module is NEVER
barrel-exported from any ``trading_system`` package (the throttle is constructed
only by ``build_live_system`` in Plan 06), so ``test_okx_inertness.py`` stays green
and the backtest path never meters an order.

Indentation: 4 SPACES (matches ``safety_controller.py`` / ``live_runner.py``).
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

# D-09: the fixed machine-readable identity for the breach WARNING ErrorEvent.
# Fixed literals only (never str(exc) / an order payload) so the V7 secret-scrub
# holds when the WARNING crosses the ERROR route (T-07-01).
_BREACH_ERROR_SOURCE = "pre_trade_throttle"
_BREACH_ERROR_TYPE = "ThrottleBreach"
_BREACH_ERROR_MESSAGE = "order rejected: submit-rate/notional cap exceeded"
_BREACH_ERROR_OPERATION = "pre_submit"

# D-02: a rejected pre-submit order never executed, so the REFUSED mirror fill
# carries zero commission (mirrors EnhancedOrderValidator's REFUSED egress).
_ZERO_COMMISSION = Decimal("0")


class PreTradeThrottle:
    """Operator pre-trade risk backstop — meters ENTRY only (SAFE-06, D-01..D-10).

    Constructed once inside ``build_live_system`` (Plan 06) and invoked by the
    runner at the pre-submit boundary. Reuses the shared ``classify`` predicate so
    it can physically never touch a CANCEL/PROTECTIVE order; only risk-opening
    ENTRY orders are metered against the sliding-window rate cap (D-04) and the
    per-order max-notional cap (D-10). A breach rejects that one order via
    ``FillEvent(REFUSED)`` (D-02), increments the read-model ``breach_count``, and
    emits a de-duped WARNING ``ErrorEvent`` (D-09).

    Parameters
    ----------
    settings : ThrottleSettings
        The static caps from ``config.safety.throttle`` (D-07/D-14) — a settable
        caps object (the shaped P9 mutation seam); NO runtime mutation is wired here.
    clock : Clock
        The INJECTED determinism clock (``core/clock.py``). The sliding window and
        the D-09 WARNING dedup read ``clock.now()`` — NEVER wall clock (D-04).
    bus : Any
        The engine ``global_queue``/bus. Only ``.put`` is used — the D-02
        ``FillEvent(REFUSED)`` egress and the D-09 WARNING ``ErrorEvent`` egress.
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
        # D-04: sliding-window rate limiter — a deque of ENTRY submit timestamps
        # (datetimes off the injected clock), pruned-left on each evaluation.
        self._stamps: "deque[datetime]" = deque()
        # D-09: read-model breach counter surfaced to P9's stats/state UI.
        self._breach_count = 0
        # D-09: last WARNING emission time (injected clock) for the min-interval dedup.
        self._last_warn: Optional[datetime] = None

    @property
    def breach_count(self) -> int:
        """The D-09 read-model breach counter (thin accessor for P9's stats UI)."""
        return self._breach_count

    def allow(self, event: Any) -> bool:
        """Meter one pre-submit order; ``True`` to submit, ``False`` if rejected.

        The pre-submit gate (D-06), invoked by the runner ahead of the dispatch
        gate. The branch order is load-bearing:

        0. ORDER-only top-gate (IN-01): any event whose ``type`` is not
           ``EventType.ORDER`` returns ``True`` IMMEDIATELY — bypass, meters nothing
           (no window append, no classify, no breach). Past this gate the classifier
           branch provably sees an ``OrderEvent``, so the throttle meters ORDER
           events only and no longer depends on the runner's call-site type gate
           for safety.
        1. ``role = classify(event)`` (the shared D-05 predicate). A CANCEL or
           PROTECTIVE role returns ``True`` IMMEDIATELY — WITHOUT touching the
           window or the notional check — so a risk-reducing order is never counted
           and can never be rejected (D-05 bypass, uncounted).
        2. For an ENTRY only: prune-left the sliding window off the injected clock
           and evaluate the D-04 rate breach (``len(stamps) >= max_orders``) AND the
           D-10 max-notional breach (Decimal ``size * price > max_notional_per_order``).
        3. On NO breach: record the timestamp (append to the window) and return
           ``True``.
        4. On a breach (rate OR notional): do NOT record; emit ``FillEvent(REFUSED)``
           (D-02), increment ``breach_count`` and emit the de-duped WARNING (D-09);
           return ``False``.
        """
        # (0) IN-01: ORDER-only top-gate. Any non-ORDER event bypasses cleanly
        # (allows submission, meters nothing) BEFORE classify() ever runs, so the
        # throttle meters ORDER events only and no longer relies on the runner's
        # call-site type gate for safety. Past this gate the ENTRY branch provably
        # implies an OrderEvent. Mirrors classify()'s defensive idiom — no
        # AttributeError on a typeless object.
        if getattr(event, 'type', None) is not EventType.ORDER:
            return True

        # (1) D-05/D-16: reuse the SINGLE shared classifier. CANCEL/PROTECTIVE bypass
        # uncounted — never metered, never rejected (the throttle physically cannot
        # touch a stop/bracket-child/cancel).
        if classify(event) is not OrderRiskRole.ENTRY:
            return True

        # (2) ENTRY only past here. Prune the sliding window off the INJECTED clock
        # (D-04, determinism) before measuring the rate.
        now = self._clock.now()
        cutoff = now - timedelta(seconds=self._settings.window_s)
        while self._stamps and self._stamps[0] < cutoff:
            self._stamps.popleft()
        rate_breach = len(self._stamps) >= self._settings.max_orders
        notional_breach = self._exceeds_notional(event)

        # (4) breach -> reject WITHOUT recording (a rejected order must not consume a
        # slot in the window). Rate OR notional trips the reject.
        if rate_breach or notional_breach:
            self._reject(event, now, rate_breach=rate_breach,
                         notional_breach=notional_breach)
            return False

        # (3) no breach -> record the metered ENTRY and allow submission.
        self._stamps.append(now)
        return True

    def _exceeds_notional(self, event: Any) -> bool:
        """Whether the ENTRY's notional exceeds the per-order cap (D-10, Decimal).

        Notional reference price (D-10): the order's limit price when present, else
        the last mark / best-available — both carried on ``OrderEvent.price`` (the
        LIMIT price for LIMIT orders; the decision-bar-close mark estimate the order
        layer stamped for MARKET/STOP orders). ``size * price`` is computed in
        ``Decimal`` end-to-end — no ``float`` coercion on this path (money policy).
        Any event reaching here is guaranteed an ``OrderEvent`` (by ``allow()``'s
        ORDER-only top-gate), whose ``price``/``quantity`` are non-optional
        ``Decimal`` by construction (``events/order.py``).
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

        D-02: emit ``FillEvent(REFUSED)`` on the bus — the SAME egress
        ``EnhancedOrderValidator`` uses (the order's own price/quantity, zero
        commission), so the order mirror reconciles REFUSED->REJECTED. Order flow
        continues (this is not a pause / halt).

        D-09: always increment the read-model ``breach_count``; emit ONE
        WARNING-severity ``ErrorEvent`` only when at least ``warn_min_interval_s``
        have elapsed (off the injected clock) since the last WARNING, so a runaway
        breach burst cannot flood the ERROR route. Only declared ErrorEvent fields +
        a fixed message are bound (V7 secret-scrub — no order payload / str(exc)).
        """
        # D-02: the REFUSED mirror fill (same path as EnhancedOrderValidator). The
        # fill defaults its time to the order's own decision time (an admission-time
        # outcome), matching the validator's REFUSED egress.
        self._bus.put(FillEvent.new_fill(
            'REFUSED', event,
            price=event.price,
            quantity=event.quantity,
            commission=_ZERO_COMMISSION,
        ))

        # D-09: the read-model counter always increments (every breach is counted).
        self._breach_count += 1
        self.logger.warning(
            'Pre-trade throttle rejected an ENTRY order (rate_breach=%s, '
            'notional_breach=%s) — FillEvent(REFUSED) emitted (D-02)',
            rate_breach, notional_breach)

        # D-09: de-dup the WARNING ErrorEvent by a min-interval off the injected
        # clock so a breach burst cannot flood the ERROR route.
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

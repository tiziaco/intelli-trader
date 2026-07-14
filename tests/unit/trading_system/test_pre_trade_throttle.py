"""PreTradeThrottle pre-trade risk-backstop tests (SAFE-06, Plan 07-05).

Constructs ``PreTradeThrottle`` with fakes (a fake bus recording every ``put``, a
fake INJECTED clock the sliding window/dedup read) and pins the D-01..D-10 contract:

  1. the 11th ENTRY inside the 10s window is REFUSED — a ``FillEvent(REFUSED)`` is
     emitted and the rejected order is NOT recorded (D-04 sliding-window rate cap);
  2. the sliding window prunes-left off the injected clock — an ENTRY allowed again
     once the window elapses (D-04 determinism seam, never wall clock);
  3. an ENTRY whose Decimal notional exceeds $25k is REFUSED (D-10 max-notional);
  4. a CANCEL and a PROTECTIVE (parent_order_id set) ALWAYS pass and are NEVER
     counted toward the window — even over the rate cap and over the notional cap
     (D-05 shared-classifier bypass, uncounted);
  5. the D-09 read-model breach counter increments on every breach;
  6. the D-09 WARNING ErrorEvent is de-duped off the injected clock — a burst of 5
     breaches within ``warn_min_interval_s`` emits exactly 1 WARNING, and a later
     breach past the interval emits a second.

Fully offline: no ``LiveTradingSystem``, no venue, no network. New test dir is
package-less (no ``__init__.py``) to avoid the full-suite package collision.
Folder-derived ``unit`` marker.
"""

from datetime import datetime, timedelta, UTC
from decimal import Decimal
from typing import Any, List

import pytest
import uuid_utils.compat as uuid_compat

from itrader.config.safety import ThrottleSettings
from itrader.core.enums import (
    ErrorSeverity,
    FillStatus,
    OrderCommand,
    OrderType,
    Side,
)
from itrader.events_handler.events import ErrorEvent, FillEvent, OrderEvent
from itrader.trading_system.safety.pre_trade_throttle import PreTradeThrottle

pytestmark = pytest.mark.unit


class _FakeBus:
    """A minimal bus recording every ``put`` (the REFUSED + WARNING egress)."""

    def __init__(self) -> None:
        self.events: List[Any] = []

    def put(self, event: Any) -> None:
        self.events.append(event)


class _FakeClock:
    """An injected, hand-advanced clock — the determinism seam (never wall clock)."""

    def __init__(self, start: datetime) -> None:
        self._t = start

    def now(self) -> datetime:
        return self._t

    def advance(self, seconds: float) -> None:
        self._t = self._t + timedelta(seconds=seconds)


def _order(
    *,
    command: OrderCommand = OrderCommand.NEW,
    parent: Any = None,
    price: Decimal = Decimal("100"),
    quantity: Decimal = Decimal("1"),
    order_type: OrderType = OrderType.LIMIT,
) -> OrderEvent:
    """A real ENTRY-typed OrderEvent; ``command``/``parent`` shift its risk role.

    Defaults are a $100 ENTRY (well under the $25k cap). A ``CANCEL`` command or a
    non-None ``parent`` (bracket child) flips the shared classifier off ``ENTRY``.
    """
    return OrderEvent(
        time=datetime(2024, 1, 1, tzinfo=UTC),
        ticker="BTCUSD",
        action=Side.BUY,
        price=price,
        quantity=quantity,
        exchange="okx",
        strategy_id=uuid_compat.uuid7(),
        portfolio_id=uuid_compat.uuid7(),
        order_type=order_type,
        order_id=uuid_compat.uuid7(),
        parent_order_id=parent,
        command=command,
    )


def _throttle(clock: _FakeClock, bus: _FakeBus) -> PreTradeThrottle:
    """A PreTradeThrottle on the default D-07 caps (10/10s + $25k), fake-wired."""
    return PreTradeThrottle(
        settings=ThrottleSettings.default(),
        clock=clock,
        bus=bus,
    )


def _refused_fills(bus: _FakeBus) -> List[Any]:
    """The FillEvent(REFUSED) mirror rejections the throttle put on the bus (D-02)."""
    return [
        e for e in bus.events
        if isinstance(e, FillEvent) and e.status == FillStatus.REFUSED
    ]


def _breach_warnings(bus: _FakeBus) -> List[Any]:
    """The de-duped WARNING ThrottleBreach ErrorEvents on the bus (D-09)."""
    return [
        e for e in bus.events
        if isinstance(e, ErrorEvent) and e.severity == ErrorSeverity.WARNING
    ]


def test_eleventh_entry_in_window_is_refused() -> None:
    """The 11th ENTRY inside the 10s window is REFUSED and NOT recorded (D-04)."""
    clock = _FakeClock(datetime(2024, 1, 1, tzinfo=UTC))
    bus = _FakeBus()
    throttle = _throttle(clock, bus)

    # 10 ENTRYs at the same instant — all under both caps, all allowed + recorded.
    for _ in range(10):
        assert throttle.allow(_order()) is True
    assert _refused_fills(bus) == []
    assert throttle.breach_count == 0
    assert len(throttle._stamps) == 10

    # The 11th ENTRY breaches the rate cap → REFUSED, not recorded.
    assert throttle.allow(_order()) is False
    assert len(_refused_fills(bus)) == 1
    assert throttle.breach_count == 1
    assert len(throttle._stamps) == 10  # rejected order consumed no slot


def test_window_prunes_left_off_injected_clock() -> None:
    """Once the window elapses (injected clock), an ENTRY is allowed again (D-04)."""
    clock = _FakeClock(datetime(2024, 1, 1, tzinfo=UTC))
    bus = _FakeBus()
    throttle = _throttle(clock, bus)

    for _ in range(10):
        assert throttle.allow(_order()) is True
    assert throttle.allow(_order()) is False  # 11th breaches at the same instant

    # Advance past the 10s window — the 10 old stamps prune-left, so a fresh ENTRY
    # is under cap again (proves the window reads the injected clock, not wall time).
    clock.advance(11)
    assert throttle.allow(_order()) is True
    assert len(throttle._stamps) == 1


def test_entry_over_max_notional_is_refused() -> None:
    """An ENTRY whose Decimal notional exceeds $25k is REFUSED (D-10)."""
    clock = _FakeClock(datetime(2024, 1, 1, tzinfo=UTC))
    bus = _FakeBus()
    throttle = _throttle(clock, bus)

    # 30_000 = 30000 * 1 > 25_000 cap.
    over = _order(price=Decimal("30000"), quantity=Decimal("1"))
    assert throttle.allow(over) is False
    assert len(_refused_fills(bus)) == 1
    assert throttle.breach_count == 1
    # A notional breach consumes no window slot (rejected, not recorded).
    assert len(throttle._stamps) == 0

    # An ENTRY exactly at the cap is NOT over (strict >), so it is allowed.
    assert throttle.allow(_order(price=Decimal("25000"), quantity=Decimal("1"))) is True


def test_cancel_and_protective_bypass_uncounted_even_over_cap() -> None:
    """CANCEL/PROTECTIVE ALWAYS pass, never count, never REFUSED — even over-cap (D-05)."""
    clock = _FakeClock(datetime(2024, 1, 1, tzinfo=UTC))
    bus = _FakeBus()
    throttle = _throttle(clock, bus)

    # Saturate the rate window with ENTRYs so the cap is already exceeded.
    for _ in range(10):
        assert throttle.allow(_order()) is True

    # A CANCEL passes and is NOT counted even though the window is full.
    cancel = _order(command=OrderCommand.CANCEL)
    assert throttle.allow(cancel) is True

    # A PROTECTIVE bracket child passes and is NOT counted — even with an
    # over-notional price the throttle physically cannot reject it (bypass first).
    protective = _order(parent=uuid_compat.uuid7(), price=Decimal("99999"),
                        quantity=Decimal("10"))
    assert throttle.allow(protective) is True

    # No REFUSED fill, no breach, and the window is untouched by the bypasses.
    assert _refused_fills(bus) == []
    assert throttle.breach_count == 0
    assert len(throttle._stamps) == 10


def test_breach_warning_is_deduped_off_injected_clock() -> None:
    """A burst of 5 breaches within warn_min_interval_s emits exactly 1 WARNING (D-09)."""
    clock = _FakeClock(datetime(2024, 1, 1, tzinfo=UTC))
    bus = _FakeBus()
    throttle = _throttle(clock, bus)

    # 5 notional breaches at the same instant (no window state consumed by rejects).
    for _ in range(5):
        assert throttle.allow(
            _order(price=Decimal("30000"), quantity=Decimal("1"))) is False

    # Counter counts all 5; the WARNING is de-duped to exactly 1 within the interval.
    assert throttle.breach_count == 5
    assert len(_refused_fills(bus)) == 5
    assert len(_breach_warnings(bus)) == 1

    warning = _breach_warnings(bus)[0]
    assert warning.error_type == "ThrottleBreach"
    assert warning.operation == "pre_submit"
    assert warning.source == "pre_trade_throttle"

    # Advance past warn_min_interval_s (default 5s) — the next breach emits a 2nd WARNING.
    clock.advance(6)
    assert throttle.allow(
        _order(price=Decimal("30000"), quantity=Decimal("1"))) is False
    assert throttle.breach_count == 6
    assert len(_breach_warnings(bus)) == 2

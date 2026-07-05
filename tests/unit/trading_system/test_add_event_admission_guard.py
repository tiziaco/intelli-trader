"""D-18 (V17-16 — HIGH) RED gate — no raw external ORDER injection onto the live queue.

The threat (V17-16, ASVS V4/V5)
-------------------------------
``LiveTradingSystem.add_event`` is the engine's PUBLIC external/web surface. Today it
enqueues ANY event once ``_running`` is set — including a raw ``OrderEvent`` — with NO
validation, NO sizing, NO cash reservation and NO order-mirror engagement. An external
caller can therefore inject an arbitrary order that bypasses every admission control
(the ``AdmissionManager`` pipeline) and lands straight on the execution queue. That is
the phase's HIGH threat surface (elevation-of-privilege / input-validation defect).

The fix (D-18, Phase 05.3)
--------------------------
``add_event`` REJECTS ``EventType.ORDER`` events — raw order injection is not allowed onto
the live queue. Non-ORDER events (the sanctioned SIGNAL-form entry, which routes through
``OrderHandler.on_signal`` -> ``AdmissionManager`` for validation + sizing + reservation +
mirror) still enqueue normally. The internal order flow is UNAFFECTED: handlers emit
``OrderEvent``s by putting them on ``global_queue`` directly, never through ``add_event``.

Fully offline: a credential-free ``LiveTradingSystem`` on the default (non-OKX) venue; the
public ``add_event`` surface is driven directly (no daemon thread, no network). Package-less
test dir (no ``__init__.py``) to avoid the full-suite package-collision; folder-derived
``unit`` marker.
"""

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from unittest.mock import MagicMock

from itrader.core.enums import EventType, OrderCommand, OrderType, Side
from itrader.core.ids import OrderId, PortfolioId
from itrader.events_handler.events import OrderEvent
from itrader.trading_system.live_trading_system import LiveTradingSystem


def _live_system(monkeypatch: Any) -> LiveTradingSystem:
    """A credential-free LiveTradingSystem for the default (non-OKX) venue, marked running."""
    for var in ("OKX_API_KEY", "OKX_API_SECRET", "OKX_API_PASSPHRASE"):
        monkeypatch.delenv(var, raising=False)
    system = LiveTradingSystem(exchange="binance")
    # Drive add_event directly — flip the running flag without launching the daemon thread.
    system._running = True
    return system


def _order_event() -> OrderEvent:
    return OrderEvent(
        time=datetime(2024, 1, 1, tzinfo=timezone.utc),
        ticker="BTC-USDT",
        action=Side.BUY,
        price=Decimal("42000.0"),
        quantity=Decimal("0.5"),
        exchange="okx",
        strategy_id=1,
        portfolio_id=PortfolioId(uuid.uuid4()),
        order_type=OrderType.LIMIT,
        order_id=OrderId(uuid.uuid4()),
        command=OrderCommand.NEW,
    )


def test_add_event_rejects_raw_order_injection(monkeypatch: Any) -> None:
    """A raw ``add_event(OrderEvent)`` is REJECTED and never reaches the queue (D-18 HIGH).

    RED today: ``add_event`` only checks ``_running`` and enqueues the OrderEvent, so an
    external caller injects an unvalidated/unsized/unreserved order straight onto the
    execution queue (V17-16 elevation-of-privilege). GREEN after D-18 restricts ``add_event``
    to non-ORDER events.
    """
    system = _live_system(monkeypatch)
    order = _order_event()

    accepted = system.add_event(order)

    assert accepted is False, (
        "D-18/V17-16: add_event accepted a raw OrderEvent — an external caller can inject "
        "an order that bypasses admission (validation + sizing + reservation + mirror). "
        "add_event must reject EventType.ORDER; external orders route through the "
        "AdmissionManager pipeline (signal-form entry)."
    )
    assert system.global_queue.empty(), (
        "D-18/V17-16: a raw OrderEvent reached the live queue via add_event — raw order "
        "injection must never be enqueued."
    )


def test_add_event_still_enqueues_non_order_events(monkeypatch: Any) -> None:
    """The sanctioned SIGNAL-form entry (and any non-ORDER event) still enqueues (D-18 guard).

    Over-fit guard: the D-18 restriction must be narrow — only ORDER events are blocked. A
    SIGNAL event (which routes through OrderHandler.on_signal -> AdmissionManager, the
    sanctioned external-order path) and all other non-ORDER events keep passing the existing
    ``_running`` check unchanged.
    """
    system = _live_system(monkeypatch)
    non_order = MagicMock(name="non_order_event")
    non_order.type = EventType.TIME

    accepted = system.add_event(non_order)

    assert accepted is True
    assert not system.global_queue.empty()
    assert system.global_queue.get_nowait() is non_order

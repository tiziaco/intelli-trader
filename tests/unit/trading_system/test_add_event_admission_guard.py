"""D-10 (fail-closed admission) gate — ``add_event`` is a default-deny allowlist.

The threat (V17-16, ASVS V4/V5)
-------------------------------
``LiveTradingSystem.add_event`` is the engine's PUBLIC external/web surface. A fail-open
gate that enqueues ANY event once ``_running`` is set — including a raw ``OrderEvent`` —
with NO validation, NO sizing, NO cash reservation and NO order-mirror engagement lets an
external caller inject an arbitrary order that bypasses every admission control (the
``AdmissionManager`` pipeline) straight onto the execution queue. That is the phase's HIGH
threat surface (elevation-of-privilege / input-validation defect).

The fix (D-10, Phase 07 — fail-open -> fail-closed)
---------------------------------------------------
``add_event`` is now a DEFAULT-DENY allowlist: it admits ONLY the two sanctioned
externally-originated types in ``_EXTERNALLY_ADMISSIBLE`` — ``SIGNAL`` (routes through
``OrderHandler.on_signal`` -> ``AdmissionManager`` for validation + sizing + reservation +
mirror) and ``STRATEGY_COMMAND`` (an operator add/remove-ticker command). EVERY other type
— every internal-fact type (FILL / BAR / UNIVERSE_UPDATE / UNIVERSE_POLL / BARS_LOADED /
BARS_LOAD_FAILED / TIME / ORDER / ERROR / PORTFOLIO_UPDATE) — is REJECTED (returns False,
never enqueued). This is the intended fail-open->fail-closed behavior change, NOT a
regression: the prior narrow ORDER-only denylist is now covered by the default-deny gate.
The internal order flow is UNAFFECTED: handlers emit ``OrderEvent``s by putting them on
``global_queue`` directly, never through ``add_event``.

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

import pytest

from itrader.core.enums import EventType, OrderCommand, OrderType, Side
from itrader.core.ids import OrderId, PortfolioId
from itrader.events_handler.events import OrderEvent
from itrader.trading_system.live_trading_system import (
    LiveTradingSystem,
    _EXTERNALLY_ADMISSIBLE,
)


def _live_system(monkeypatch: Any) -> LiveTradingSystem:
    """A credential-free LiveTradingSystem for the default (non-OKX) venue, marked running."""
    for var in ("OKX_API_KEY", "OKX_API_SECRET", "OKX_API_PASSPHRASE"):
        monkeypatch.delenv(var, raising=False)
    system = LiveTradingSystem.for_exchange("binance")
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


def test_externally_admissible_is_exactly_signal_and_strategy_command() -> None:
    """The D-10 allowlist is EXACTLY {SIGNAL, STRATEGY_COMMAND} — nothing else (fail-closed)."""
    assert _EXTERNALLY_ADMISSIBLE == frozenset(
        {EventType.SIGNAL, EventType.STRATEGY_COMMAND}
    )


@pytest.mark.parametrize("admissible_type", [EventType.SIGNAL, EventType.STRATEGY_COMMAND])
def test_add_event_admits_sanctioned_external_types(
    monkeypatch: Any, admissible_type: EventType
) -> None:
    """The two sanctioned external types (SIGNAL, STRATEGY_COMMAND) are ADMITTED and enqueued.

    These are the ONLY externally-originated types allowed onto the public queue: a SIGNAL
    routes through ``OrderHandler.on_signal`` -> ``AdmissionManager`` (validation + sizing +
    reservation + mirror), and a STRATEGY_COMMAND is an operator add/remove-ticker command.
    """
    system = _live_system(monkeypatch)
    event = MagicMock(name=f"{admissible_type.name}_event")
    event.type = admissible_type

    accepted = system.add_event(event)

    assert accepted is True
    assert not system.global_queue.empty()
    assert system.global_queue.get_nowait() is event


# Every internal-fact type — nothing an external caller may inject. Includes ORDER (the prior
# narrow denylist, now covered by the default-deny gate) plus every other engine-internal type.
_INTERNAL_FACT_TYPES = [
    EventType.FILL,
    EventType.BAR,
    EventType.UNIVERSE_UPDATE,
    EventType.UNIVERSE_POLL,
    EventType.BARS_LOADED,
    EventType.BARS_LOAD_FAILED,
    EventType.TIME,
    EventType.ORDER,
    EventType.ORDER_ACK,
    EventType.SCREENER,
    EventType.ERROR,
    EventType.UPDATE,
]


@pytest.mark.parametrize("internal_type", _INTERNAL_FACT_TYPES)
def test_add_event_rejects_every_internal_fact_type(
    monkeypatch: Any, internal_type: EventType
) -> None:
    """Each internal-fact type is REJECTED by the fail-closed default-deny gate (D-10).

    This is the intended fail-open->fail-closed change: ``add_event`` admits ONLY the
    sanctioned external types, so every internal-fact type an external caller might inject —
    FILL, BAR, the four universe/warmup control types, TIME, ORDER, ORDER_ACK, SCREENER,
    ERROR, UPDATE — returns False and never reaches the live queue. Driven by a MagicMock
    carrying only the
    discriminating ``.type`` (``add_event`` reads nothing else on the reject path).
    """
    system = _live_system(monkeypatch)
    event = MagicMock(name=f"{internal_type.name}_event")
    event.type = internal_type

    accepted = system.add_event(event)

    assert accepted is False, (
        f"D-10 fail-closed: add_event admitted an internal-fact {internal_type.name} event — "
        "only SIGNAL and STRATEGY_COMMAND are admissible from the external surface."
    )
    assert system.global_queue.empty(), (
        f"D-10 fail-closed: an internal-fact {internal_type.name} event reached the live "
        "queue via add_event — every non-allowlisted type must be rejected before enqueue."
    )

"""External CONFIG_UPDATE ingress test (D-23 mandatory / RTCFG-02).

With no FastAPI driver yet (LR-01 out of scope), P9's OWN tests MUST drive the external
``add_event(ConfigUpdateEvent(...))`` path directly so the opened ingress is not untested
surface (D-23). This test exercises the public ``LiveTradingSystem.add_event`` boundary:

* a VALID ``CONFIG_UPDATE`` is ADMITTED (returns True, enqueued) and — once drained on the
  engine thread through the wired ``ConfigRouter`` — APPLIED + PERSISTED into ITS OWNING
  store (an order update lands in the ORDER store, NOT ``SystemStore``);
* an INVALID update (bad type/range on a KNOWN field) is REJECTED SYNCHRONOUSLY at the
  ingress (returns False, never enqueued) — the 400 once FastAPI exists (D-16);
* a NON-ALLOWLISTED event type (a raw internal-fact event) is REJECTED (default-deny D-10).

Fully offline: a credential-free facade on the default (non-OKX) venue; the public
``add_event`` surface is driven directly (no daemon thread, no network). The engine-thread
drain is simulated by pulling the admitted event off the queue and invoking the wired
``ConfigRouter.apply`` (exactly what the ``CONFIG_UPDATE`` route does). Package-less dir.
"""

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest

from itrader.config.itrader_config import ITraderConfig
from itrader.config.sql import SqlSettings
from itrader.core.enums import (
    EventType,
    MarketExecution,
    OrderCommand,
    OrderType,
    Side,
)
from itrader.core.ids import OrderId, PortfolioId
from itrader.events_handler.events import ConfigUpdateEvent, OrderEvent
from itrader.order_handler.storage.sql_storage import SqlOrderStorage
from itrader.storage import SqlEngine
from itrader.storage.system_store import SystemStore
from itrader.storage.venue_store import VenueStore
from itrader.trading_system.config_router import ConfigRouter
from itrader.trading_system.live_trading_system import LiveTradingSystem
from tests.support.schema import provision_schema

_NOW = datetime(2026, 7, 16, 12, 0, tzinfo=timezone.utc)


def _live_system(monkeypatch: Any) -> LiveTradingSystem:
    """A credential-free, non-OKX facade marked running (no daemon thread)."""
    for var in ("OKX_API_KEY", "OKX_API_SECRET", "OKX_API_PASSPHRASE"):
        monkeypatch.delenv(var, raising=False)
    system = LiveTradingSystem.for_exchange("binance")
    system._running = True
    return system


def _config_event(scope: str, key: str, value: Any) -> ConfigUpdateEvent:
    return ConfigUpdateEvent(time=_NOW, scope=scope, key=key, value=value)


def _attach_order_router(system: LiveTradingSystem) -> SimpleNamespace:
    """Wire a real-ORDER-store ConfigRouter onto the facade (the CONFIG_UPDATE consumer)."""
    engine = SqlEngine(SqlSettings.default())
    order_store = SqlOrderStorage(engine)
    system_store = SystemStore(engine)
    venue_store = VenueStore(engine)
    provision_schema(engine)

    pushed: list = []
    order_handler = SimpleNamespace(
        storage=order_store, update_config=lambda updates: pushed.append(updates)
    )
    exec_handler = SimpleNamespace(update_config=lambda updates: None)
    portfolio_handler = SimpleNamespace(get_portfolio=lambda pid: None)
    router_config = ITraderConfig()

    router = ConfigRouter(
        config=router_config,
        system_store=system_store,
        venue_store=venue_store,
        order_handler=order_handler,
        portfolio_handler=portfolio_handler,
        execution_handler=exec_handler,
        venue_kind=lambda name: True,
        bus=system.global_queue,
        clock=SimpleNamespace(now=lambda: _NOW),
    )
    system._config_router = router
    return SimpleNamespace(
        router=router,
        router_config=router_config,
        order_store=order_store,
        system_store=system_store,
        pushed=pushed,
    )


def test_valid_config_update_admitted_applied_and_persisted_to_owning_store(monkeypatch):
    """A valid order CONFIG_UPDATE is admitted, then drained -> applied + persisted (ORDER store)."""
    system = _live_system(monkeypatch)
    ctx = _attach_order_router(system)

    event = _config_event("order", "market_execution", "next_bar")
    accepted = system.add_event(event)

    assert accepted is True, "a valid CONFIG_UPDATE must be admitted at the ingress"
    assert not system.global_queue.empty()

    # Simulate the engine-thread CONFIG_UPDATE route: drain -> ConfigRouter.apply.
    drained = system.global_queue.get_nowait()
    assert drained is event
    system._config_router.apply(drained)

    # APPLIED — the router's live config sub-model mutated + the owning handler was pushed.
    assert ctx.router_config.order.market_execution is MarketExecution.NEXT_BAR
    assert ctx.pushed == [{"market_execution": "next_bar"}]
    # PERSISTED into ITS OWNING store — the ORDER store, NOT SystemStore (D-21/D-25).
    assert ctx.order_store.load_config() == {"market_execution": "next_bar"}
    assert ctx.system_store.read_all() == []


def test_invalid_config_update_rejected_synchronously_at_ingress(monkeypatch):
    """A bad type/range on a KNOWN field returns False at the ingress and never enqueues (400)."""
    system = _live_system(monkeypatch)
    _attach_order_router(system)

    # market_execution is a MarketExecution enum — "bogus" is not a member (bad range).
    bad = _config_event("order", "market_execution", "bogus")
    accepted = system.add_event(bad)

    assert accepted is False, "an invalid CONFIG_UPDATE must be rejected synchronously (400)"
    assert system.global_queue.empty(), "a rejected CONFIG_UPDATE must never reach the queue"


def test_malformed_scope_or_key_rejected_at_ingress(monkeypatch):
    """An unrouted scope / unknown key on a known scope is rejected at the ingress."""
    system = _live_system(monkeypatch)
    _attach_order_router(system)

    # Unknown key on the (known) system scope.
    assert system.add_event(_config_event("system", "not_a_field", 1)) is False
    # Unrouted scope entirely.
    assert system.add_event(_config_event("strategy", "enabled", True)) is False
    assert system.global_queue.empty()


def test_non_allowlisted_event_type_rejected(monkeypatch):
    """A raw internal-fact event (ORDER) is rejected by the D-10 default-deny allowlist."""
    system = _live_system(monkeypatch)
    _attach_order_router(system)

    order = OrderEvent(
        time=_NOW,
        ticker="BTC-USDT",
        action=Side.BUY,
        price=Decimal("42000.0"),
        quantity=Decimal("0.5"),
        exchange="binance",
        strategy_id=1,
        portfolio_id=PortfolioId(uuid.uuid4()),
        order_type=OrderType.LIMIT,
        order_id=OrderId(uuid.uuid4()),
        command=OrderCommand.NEW,
    )
    assert system.add_event(order) is False
    assert system.global_queue.empty()

    # A discriminating-only MagicMock FILL is also rejected (default-deny).
    fill = MagicMock(name="FILL_event")
    fill.type = EventType.FILL
    assert system.add_event(fill) is False
    assert system.global_queue.empty()


def test_valid_system_scope_update_admitted(monkeypatch):
    """A valid system-scope CONFIG_UPDATE (known mutable field, in range) is admitted."""
    system = _live_system(monkeypatch)
    _attach_order_router(system)

    event = _config_event("system", "auto_restart_delay_seconds", 25)
    assert system.add_event(event) is True
    assert not system.global_queue.empty()


def test_config_update_rejected_when_no_router_wired_in_memory_fallback(monkeypatch):
    """CR-01: in-memory-live (no SQL spine -> no ConfigRouter) rejects CONFIG_UPDATE fail-closed.

    Without a durable store ``build_live_system`` never constructs a ``ConfigRouter``
    (``facade._config_router`` stays None) and the CONFIG_UPDATE route is left the pre-declared
    empty slot. An external ``add_event(ConfigUpdateEvent)`` must be REJECTED synchronously
    (truthful False, never enqueued) rather than admitted then silently dropped with a
    per-event AttributeError on the engine thread (None.apply).
    """
    system = _live_system(monkeypatch)
    assert system._config_router is None  # in-memory fallback: no router wired

    # An OTHERWISE-VALID order update — the only reason to reject is the missing durable store.
    event = _config_event("order", "market_execution", "next_bar")
    accepted = system.add_event(event)

    assert accepted is False, "no durable store -> CONFIG_UPDATE must be rejected fail-closed"
    assert system.global_queue.empty(), "a rejected CONFIG_UPDATE must never reach the queue"


def test_config_update_route_not_installed_without_router():
    """CR-01: LiveRouteRegistrar leaves CONFIG_UPDATE the empty slot when the router is None."""
    from unittest.mock import MagicMock

    from itrader.core.enums import EventType
    from itrader.trading_system.route_registrar import LiveRouteRegistrar

    routes = {EventType.CONFIG_UPDATE: [], EventType.FILL: []}
    event_handler = SimpleNamespace(routes=routes)
    registrar = LiveRouteRegistrar(
        MagicMock(name="strategies_handler"),
        MagicMock(name="universe_handler"),
        safety=MagicMock(name="safety"),
        stream_recovery=MagicMock(name="stream_recovery"),
        config_router=None,  # in-memory fallback
    )
    registrar.install(event_handler)  # type: ignore[arg-type]

    # The CONFIG_UPDATE route stays the pre-declared empty slot (no None-router consumer).
    assert routes[EventType.CONFIG_UPDATE] == []

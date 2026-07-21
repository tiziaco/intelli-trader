"""D-11 `remove` end-to-end — force-flat first, survive while pending, drop on flat.

Drives the STRAT-02 ``remove`` verb through a fully-wired OFFLINE paper system (reused
``SimulatedExchange``, no OKX/network): a strategy holding an open position is removed, the
follow-on ``UniversePollEvent`` re-derives membership WITHOUT the pending strategy (D-11 —
``get_strategies_universe`` excludes it), the poll's REMOVE branch fires the EXISTING P7
force-close (``_on_symbol_removed`` -> market exit), the exit settles through the reused
exchange (``FillEvent`` -> ``PortfolioHandler.on_fill`` flat), and the FILL route's
``StrategiesHandler.on_fill`` then drops the object + deletes child-then-parent rows.

The registry ROW survives WHILE PENDING (crash-safety): a mid-force-close crash rehydrates
the strategy and it resumes managing its own positions rather than orphaning them.

D-16: the same path force-flats a pair's BOTH legs (covered at the unit layer,
``test_strategy_command_verbs.py``); this file proves the single-leg end-to-end wiring.

CI-safe: offline replay, SQLite registry, no network. NO ``__init__.py`` in this dir.
4-space indentation (matches ``tests/integration/*``).
"""

import datetime as _dt
from decimal import Decimal

import pytest

from itrader.config.sql import SqlSettings
from itrader.core.enums import Side
from itrader.core.instrument import Instrument
from itrader.core.enums import EventType
from itrader.core.money import to_money
from itrader.core.sizing import FractionOfCash
from itrader.events_handler.events import SignalEvent
from itrader.storage import SqlEngine
from itrader.storage.strategy_registry_store import StrategyRegistryStore
from itrader.strategy_handler.base import Strategy
from itrader.strategy_handler.strategies_handler import StrategiesHandler
from itrader.universe.membership import StrategyDerivedSelectionModel
from itrader.universe.universe import Universe
from itrader.universe.universe_handler import UniverseHandler, UniverseHandlerConfig
from itrader.execution_handler.execution_handler import DEFAULT_ACCOUNT_ID
from tests.support.replay_harness import build_paper_replay_system
from tests.support.schema import provision_schema

pytestmark = pytest.mark.integration

_HELD = "AAAUSD"
_BASE_MS = int(_dt.datetime(2024, 1, 1, tzinfo=_dt.timezone.utc).timestamp() * 1000)
_DAY_MS = 86_400_000
_T = _dt.datetime(2024, 1, 1, tzinfo=_dt.timezone.utc)


class _NoopStrategy(Strategy):
    """A handle-free membership strategy — always ready, never signals on its own."""

    sizing_policy = FractionOfCash(Decimal("0.5"))

    def init(self) -> None:
        pass

    def generate_signal(self, ticker: str) -> object | None:
        return None


class _Recorder:
    """Paper subscribe/unsubscribe recorder (no socket on the paper venue)."""

    def __init__(self) -> None:
        self.unsubscribed: list[str] = []

    def subscribe(self, symbol: str) -> None:  # noqa: D401
        pass

    def unsubscribe(self, symbol: str) -> None:
        self.unsubscribed.append(symbol)


class _RemoveHarness:
    def __init__(self):
        self.store = StrategyRegistryStore(SqlEngine(SqlSettings.default()))
        provision_schema(self.store.backend)
        system, _ = build_paper_replay_system()
        self.system = system
        simulated = system.execution_handler.exchanges[("simulated", DEFAULT_ACCOUNT_ID)]
        simulated.register_symbol(_HELD)
        system.feed.bind(system.global_queue, [_HELD])
        # D-27: LIVE (paper) system — the portfolio must name its venue account
        # or on_order refuses it (no default-account fallback).
        self.portfolio_id = system.portfolio_handler.add_portfolio(
            name="rm_pf", exchange="simulated", cash=1_000_000,
            account_id=DEFAULT_ACCOUNT_ID)

        instrument = Instrument(
            symbol=_HELD,
            price_precision=Decimal("0.01"),
            quantity_precision=Decimal("0.00000001"),
            maintenance_margin_rate=Decimal("0.005"),
            max_leverage=Decimal("1"))
        self.universe = Universe(members=[_HELD], instrument_map={_HELD: instrument})
        system.order_handler.set_universe(self.universe)
        from itrader.execution_handler.exchanges.simulated import SimulatedExchange
        if isinstance(simulated, SimulatedExchange):
            simulated.set_universe(self.universe)

        sh: StrategiesHandler = system.strategies_handler
        sh.strategy_catalog = {"_NoopStrategy": _NoopStrategy}
        sh.registry_store = self.store
        sh.portfolio_read_model = system.portfolio_handler
        sh.set_universe(self.universe)

        self.provider = _Recorder()
        self.universe_handler = UniverseHandler(
            bus=system.global_queue,
            universe=self.universe,
            feed=system.feed,
            config=UniverseHandlerConfig(poll_timeframe="1d", remove_policy="force-close"))
        self.universe_handler.set_portfolio_read_model(system.portfolio_handler)
        self.universe_handler.set_provider(self.provider)
        self.universe_handler.set_selection_source(
            StrategyDerivedSelectionModel(sh))

        routes = system.event_handler.routes
        routes[EventType.UNIVERSE_POLL] = [self.universe_handler.on_poll]
        routes[EventType.UNIVERSE_UPDATE] = [self.universe_handler.on_universe_update]
        routes[EventType.FILL].append(self.universe_handler.on_fill)
        routes[EventType.FILL].append(sh.on_fill)

        # Register the strategy trading _HELD and subscribe it to the holding portfolio.
        self.strategy = _NoopStrategy(timeframe="1d", tickers=[_HELD], name="rm_probe")
        sh.add_strategy(self.strategy)
        self.strategy.subscribe_portfolio(self.portfolio_id)
        self._next_ts = _BASE_MS

    def dispose(self) -> None:
        self.store.dispose()

    def _drive_bar(self, price: str) -> None:
        cb = {
            "ts": self._next_ts,
            "open": to_money(price), "high": to_money(price),
            "low": to_money(price), "close": to_money(price),
            "volume": to_money("1"), "symbol": _HELD, "timeframe": "1d"}
        self._next_ts += _DAY_MS
        self.system.feed.update(cb)
        self.system.event_handler.process_events()

    def _signal(self, action, price):
        from typing import cast

        from itrader import idgen
        from itrader.core.enums import OrderType
        from itrader.core.ids import StrategyId
        from itrader.core.sizing import TradingDirection

        return SignalEvent(
            time=_T, order_type=OrderType.MARKET, ticker=_HELD, action=action,
            price=to_money(price), stop_loss=Decimal("0"), take_profit=Decimal("0"),
            strategy_id=cast(StrategyId, idgen.generate_strategy_id()),
            portfolio_id=self.portfolio_id,
            sizing_policy=FractionOfCash(fraction=Decimal("0.5")),
            direction=TradingDirection.LONG_SHORT, exit_fraction=Decimal("1"))

    def open_long(self, price: str = "100") -> None:
        self.system.global_queue.put(self._signal(Side.BUY, price))
        self.system.event_handler.process_events()
        self._drive_bar(price)

    def position_qty(self) -> Decimal:
        position = self.system.portfolio_handler.get_portfolio(
            self.portfolio_id).get_open_position(_HELD)
        return position.net_quantity if position is not None else Decimal("0")

    def remove(self) -> None:
        from itrader.events_handler.events import StrategyCommandEvent

        self.system.strategies_handler.on_strategy_command(
            StrategyCommandEvent.remove(strategy_name="rm_probe", time=_T))
        self.system.event_handler.process_events()


@pytest.fixture()
def harness():
    h = _RemoveHarness()
    try:
        yield h
    finally:
        h.dispose()


def test_remove_force_flats_survives_pending_then_drops_after_flat(harness):
    """D-11 — remove of a strategy holding a position force-flats, survives pending, drops."""
    harness.open_long(price="100")
    assert harness.position_qty() > 0

    # Remove: deactivate + pending + persist enabled=False + poll -> force-close exit.
    harness.remove()

    # While pending: the instance and its row SURVIVE (crash-safety), and a force-close
    # exit was emitted (the socket was unsubscribed at removal under force-close policy).
    assert "rm_probe" in harness.system.strategies_handler._pending_removals
    assert any(s.name == "rm_probe" for s in harness.system.strategies_handler.strategies)
    assert harness.store.get("rm_probe") is not None
    assert _HELD in harness.provider.unsubscribed

    # Settle the force-close exit on the next bar -> position flat -> StrategiesHandler.on_fill
    # drops the object and deletes child-then-parent rows.
    harness._drive_bar(price="100")
    assert harness.position_qty() == Decimal("0")
    assert not any(
        s.name == "rm_probe" for s in harness.system.strategies_handler.strategies)
    assert "rm_probe" not in harness.system.strategies_handler._pending_removals
    assert harness.store.get("rm_probe") is None


def test_remove_with_no_position_completes_on_the_same_cycle(harness):
    """D-11 — with no open position the flat condition already holds; it drops immediately."""
    harness.remove()

    assert not any(
        s.name == "rm_probe" for s in harness.system.strategies_handler.strategies)
    assert harness.store.get("rm_probe") is None

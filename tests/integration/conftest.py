"""Integration-layer fixtures (D-13/D-15).

These fixtures serve the cross-component cascade, the run-path smoke test, and the
golden-master oracle — all of which exercise MORE than one collaborating component
(the D-15 integration boundary). They live here, not at the root, because the unit
layer never needs the frozen-oracle assets or a full ``TradingSystem``.

Golden assets moved with the tree (D-13): ``tests/golden/{trades,equity}.csv`` +
``summary.json``. The path fixtures below resolve to that moved location.
"""

import pathlib

import pytest

# This file lives at <repo>/tests/integration/, so the golden dir is one level up
# under tests/golden/.
_GOLDEN_DIR = pathlib.Path(__file__).resolve().parent.parent / "golden"


@pytest.fixture
def golden_dir():
    """Path to the committed frozen-oracle directory (tests/golden/)."""
    return _GOLDEN_DIR


@pytest.fixture
def golden_trades_path():
    """Path to the frozen trade-log CSV."""
    return _GOLDEN_DIR / "trades.csv"


@pytest.fixture
def golden_equity_path():
    """Path to the frozen equity-curve CSV."""
    return _GOLDEN_DIR / "equity.csv"


@pytest.fixture
def golden_summary_path():
    """Path to the frozen summary JSON."""
    return _GOLDEN_DIR / "summary.json"


# --- Shared operational-Postgres substrate (single suite-wide container) ------


@pytest.fixture(scope="session")
def pg_container_url():
    """The SINGLE session-scoped testcontainers Postgres for the whole integration tree.

    Models its lifecycle EXACTLY on ``tests/integration/storage/conftest.py::pg_engine``:
    the ``testcontainers`` import is DEFERRED into the body so ``--collect-only`` needs no
    Docker daemon; the ``PostgresContainer`` constructor eagerly builds a DockerClient, so an
    absent/unreachable daemon raises as early as construction (kept inside the ``try``). ANY
    startup failure is converted to a ``pytest.skip`` (D-11) — the PG arm must never hard-fail
    a Dockerless run. It yields the connection URL so consumers build their own Engine off it.

    This is the ONE container for the whole ``tests/integration/`` tree (it cascades into
    ``storage/``): ``storage/conftest.py::pg_engine`` and the ``pg_database_env`` opt-in fixture
    both consume this URL, so no second competing container is ever spun.
    """
    from testcontainers.postgres import PostgresContainer

    container = None
    try:
        # Constructor eagerly builds a DockerClient — absent daemon raises here, not .start().
        container = PostgresContainer("postgres:16")
        container.start()
    except Exception as exc:
        if container is not None:
            try:
                container.stop()
            except Exception:
                pass
        pytest.skip(f"PostgreSQL container unavailable — skipped (D-11): {exc}")

    try:
        yield container.get_connection_url()
    finally:
        container.stop()


@pytest.fixture
def pg_database_env(pg_container_url, monkeypatch):
    """Point the ``ITRADER_DATABASE_URL`` env gate at the shared container within test scope.

    The companion for tests that go through the ``LiveTradingSystem`` env gate: it
    ``monkeypatch.setenv``s ``ITRADER_DATABASE_URL`` to the shared ``pg_container_url`` (the
    function-scoped set overrides the session-scoped dev-DB guard in ``tests/conftest.py`` and
    is undone at test teardown) and returns the URL so the test can also build a drop Engine.
    """
    monkeypatch.setenv("ITRADER_DATABASE_URL", pg_container_url)
    return pg_container_url


@pytest.fixture
def backtest_engine():
    """Factory that builds a CSV-fed backtest ``BacktestTradingSystem``.

    Returns a callable so construction is DEFERRED until a test actually invokes it.
    The BacktestTradingSystem import lives inside the inner function body so
    ``--collect-only`` succeeds even if a referenced branch is not yet wired.
    """

    def _make(
        ticker="BTCUSD",
        timeframe="1d",
        start_date="2018-01-01",
        end_date="2026-06-03",
        cash=10_000,
    ):
        # Deferred import: only executed when a test calls the factory.
        from itrader.trading_system.backtest_trading_system import (
            BacktestTradingSystem,
        )

        return BacktestTradingSystem(
            exchange="csv",
            start_date=start_date,
            end_date=end_date,
        )

    return _make


# --- Multi-symbol universe remove-policy harness (06-04 Task 3) --------------
#
# Deterministic, OFFLINE vehicle for the D-01 open-position-on-remove policy
# (orphan-and-track + force-close) and the plan-04 leaving-symbol admission gate.
# RESEARCH §10: a small multi-symbol replay harness stamps two symbols and drives
# their bars synchronously through ``LiveBarFeed.update`` — the SAME provider->feed
# seam OKX uses — while paper ``subscribe``/``unsubscribe`` are no-op recording stubs
# (there is no socket). The feed ring + admission gate + force-close order + fill
# settlement all run through the REAL synchronous path against the reused
# ``SimulatedExchange`` on the ``'paper'`` venue (D-04): no live venue is touched.
#
# The ``UniverseHandler`` is NOT yet on the ``EventHandler`` routes (plan 05 wires the
# live route). The plan-04 seams under test — ``on_universe_update`` REMOVE and the
# ``on_fill`` detach hook — are therefore driven by DIRECT calls here, reading the
# REAL ``PortfolioReadModel`` (the live ``PortfolioHandler``) so every policy decision
# keys off genuine settled portfolio state, not a fake.

import datetime as _dt
from decimal import Decimal as _Decimal


class _RecordingUniverseProvider:
    """Paper ``subscribe``/``unsubscribe`` recorder — the remove branch's provider seam.

    No socket: the ``'paper'`` venue has no live data plane, so the provider the
    remove-policy consumer drives is a pure recorder. ``subscribed``/``unsubscribed``
    capture the exact deferred-vs-immediate detach behaviour the policy asserts.
    """

    def __init__(self) -> None:
        self.subscribed: list[str] = []
        self.unsubscribed: list[str] = []

    def subscribe(self, symbol: str) -> None:
        self.subscribed.append(symbol)

    def unsubscribe(self, symbol: str) -> None:
        self.unsubscribed.append(symbol)


class _FlatFill:
    """Minimal stand-in for the live FILL-route event the detach hook consumes.

    ``UniverseHandler.on_fill`` reads ONLY ``event.ticker`` and then consults the
    (real, now-settled) read model; the position going flat has already happened
    through the REAL ``SimulatedExchange`` -> ``PortfolioHandler.on_fill`` path, so
    this carries just the ticker the plan-05-wired FILL route would forward.
    """

    def __init__(self, ticker: str) -> None:
        self.ticker = ticker


class _RemovePolicyHarness:
    """A two-symbol paper/replay engine wired for the remove-policy behaviours.

    Holds a fully-wired ``LiveTradingSystem(exchange='paper')`` (reused
    ``SimulatedExchange``), a two-symbol ``Universe`` injected into the admission
    gate, and a ``UniverseHandler`` reading the live ``PortfolioHandler`` as its
    ``PortfolioReadModel``. Bars are driven per-symbol through ``feed.update`` with
    contiguous 1d timestamps (the feed's monotonic-forward guard requires ``L+tf``).
    """

    _BASE_MS = int(_dt.datetime(2024, 1, 1, tzinfo=_dt.timezone.utc).timestamp() * 1000)
    _DAY_MS = 86_400_000
    _SIGNAL_TIME = _dt.datetime(2024, 1, 1, tzinfo=_dt.timezone.utc)

    def __init__(self, system, universe, universe_handler, provider,
                 portfolio_id, held_symbol, other_symbol):
        self.system = system
        self.universe = universe
        self.universe_handler = universe_handler
        self.provider = provider
        self.portfolio_id = portfolio_id
        self.held_symbol = held_symbol
        self.other_symbol = other_symbol
        self._next_ts: dict[str, int] = {}

    # -- bar drive (the SAME provider->feed seam OKX uses) --------------------

    def _next_ts_for(self, symbol: str) -> int:
        cur = self._next_ts.get(symbol, self._BASE_MS)
        self._next_ts[symbol] = cur + self._DAY_MS
        return cur

    def drive_bar(self, symbol: str, price: str) -> None:
        """Push one closed bar for ``symbol`` through ``feed.update`` and drain.

        A flat OHLC at ``price`` (open == fill price for a resting MARKET order,
        next-bar-open contract). Decimal edge via ``to_money`` (money correctness).
        """
        from itrader.core.money import to_money

        cb = {
            "ts": self._next_ts_for(symbol),
            "open": to_money(price),
            "high": to_money(price),
            "low": to_money(price),
            "close": to_money(price),
            "volume": to_money("1"),
            "symbol": symbol,
            "timeframe": "1d",
        }
        self.system.feed.update(cb)
        self.system.event_handler.process_events()

    # -- signal construction --------------------------------------------------

    def _signal(self, action, symbol, price, *, exit_fraction="1"):
        from typing import cast

        from itrader import idgen
        from itrader.core.enums import OrderType
        from itrader.core.ids import StrategyId
        from itrader.core.money import to_money
        from itrader.core.sizing import FractionOfCash, TradingDirection
        from itrader.events_handler.events import SignalEvent

        return SignalEvent(
            time=self._SIGNAL_TIME,
            order_type=OrderType.MARKET,
            ticker=symbol,
            action=action,
            price=to_money(price),
            stop_loss=_Decimal("0"),
            take_profit=_Decimal("0"),
            strategy_id=cast(StrategyId, idgen.generate_strategy_id()),
            portfolio_id=self.portfolio_id,
            # Entry sizes half the cash; an exit ignores the policy value and
            # sizes from the open position magnitude (resolve_exit, D-07).
            sizing_policy=FractionOfCash(fraction=_Decimal("0.5")),
            direction=TradingDirection.LONG_SHORT,
            exit_fraction=_Decimal(exit_fraction),
        )

    # -- REAL-path position lifecycle ----------------------------------------

    def open_long(self, symbol: str, price: str = "100") -> None:
        """Open a long via the real path: BUY market rests, next bar fills it."""
        from itrader.core.enums import Side

        self.system.global_queue.put(self._signal(Side.BUY, symbol, price))
        self.system.event_handler.process_events()  # order rests in the book
        self.drive_bar(symbol, price)               # next-bar-open fill

    def emit_exit_and_settle(self, symbol: str, price: str = "100") -> None:
        """Emit a sanctioned SELL exit and settle it on the next bar (position flat)."""
        from itrader.core.enums import Side

        self.system.global_queue.put(
            self._signal(Side.SELL, symbol, price, exit_fraction="1"))
        self.system.event_handler.process_events()  # exit order rests
        self.drive_bar(symbol, price)               # fill -> flat

    def process_and_settle(self, symbol: str, price: str = "100") -> None:
        """Drain any queued (e.g. force-close) signal, then settle it on the next bar."""
        self.system.event_handler.process_events()  # queued exit order rests
        self.drive_bar(symbol, price)               # fill -> flat

    def submit_new_entry(self, symbol: str, price: str = "100"):
        """Run a NEW-entry BUY through admission and return the OperationResults.

        A direct ``process_signal`` so the audited rejection verdict is observable
        (the gate returns before any OrderEvent is emitted).
        """
        from itrader.core.enums import Side

        return self.system.order_handler.order_manager.process_signal(
            self._signal(Side.BUY, symbol, price))

    # -- REMOVE-policy seams (plan-04 direct-call, real read model) -----------

    def remove(self, symbol: str):
        """Drive the ``on_universe_update`` REMOVE branch for ``symbol``."""
        from itrader.events_handler.events.market import UniverseUpdateEvent

        self.universe_handler.on_universe_update(
            UniverseUpdateEvent(time=self._SIGNAL_TIME, added=(), removed=(symbol,)))

    def fire_flat_fill(self, symbol: str) -> None:
        """Drive the detach-on-flat FILL hook for ``symbol``."""
        self.universe_handler.on_fill(_FlatFill(symbol))

    # -- observation ----------------------------------------------------------

    def position_qty(self, symbol: str):
        position = self.system.portfolio_handler.get_portfolio(
            self.portfolio_id).get_open_position(symbol)
        return position.net_quantity if position is not None else _Decimal("0")

    def queued_signals(self, symbol: str):
        from itrader.events_handler.events import SignalEvent

        return [
            event for event in list(self.system.global_queue.queue)
            if isinstance(event, SignalEvent) and event.ticker == symbol
        ]

    def has_audited_leaving_rejection(self, symbol: str) -> bool:
        """True iff an audited REJECTED order for ``symbol`` cites ADMISSION_LEAVING."""
        from itrader.core.enums import OrderStatus
        from itrader.core.enums.order import OrderTriggerSource

        manager = self.system.order_handler.order_manager
        for order in manager.get_orders_by_status(OrderStatus.REJECTED, self.portfolio_id):
            if order.ticker != symbol:
                continue
            for change in manager.get_order_history(order.id):
                if change.get("triggered_by") == OrderTriggerSource.ADMISSION_LEAVING.value:
                    return True
        return False


@pytest.fixture
def remove_policy_harness():
    """Factory building a two-symbol paper/replay engine for remove-policy tests.

    Returns a callable ``_make(remove_policy=..., cash=...)`` so construction is
    DEFERRED until a test invokes it (heavy imports stay out of ``--collect-only``).
    """

    def _make(remove_policy: str = "orphan-and-track", cash: int = 1_000_000):
        from itrader.core.instrument import Instrument
        from itrader.execution_handler.exchanges.simulated import SimulatedExchange
        from itrader.trading_system.live_trading_system import LiveTradingSystem
        from itrader.universe.universe import Universe
        from itrader.universe.universe_handler import (
            UniverseHandler,
            UniverseHandlerConfig,
        )

        held, other = "AAAUSD", "BBBUSD"

        # Fully-wired paper engine (reused SimulatedExchange, offline — no OKX/network).
        system = LiveTradingSystem(exchange="paper")
        simulated = system.execution_handler.exchanges["simulated"]
        simulated.register_symbol(held)
        simulated.register_symbol(other)
        # Bind the live feed to the queue + membership so update() emits BarEvents.
        system.feed.bind(system.global_queue, [held, other])

        portfolio_id = system.portfolio_handler.add_portfolio(
            name="remove_policy_pf", exchange="simulated", cash=cash)

        def _instrument(symbol: str) -> Instrument:
            return Instrument(
                symbol=symbol,
                price_precision=_Decimal("0.01"),
                quantity_precision=_Decimal("0.00000001"),
                maintenance_margin_rate=_Decimal("0.005"),
                max_leverage=_Decimal("1"),
            )

        universe = Universe(
            members=sorted([held, other]),
            instrument_map={held: _instrument(held), other: _instrument(other)},
        )
        # Wire the universe into the admission gate (the leaving-symbol gate reads
        # Universe.leaving_symbols) and the exchange (instrument precision seam).
        system.order_handler.set_universe(universe)
        if isinstance(simulated, SimulatedExchange):
            simulated.set_universe(universe)

        provider = _RecordingUniverseProvider()
        universe_handler = UniverseHandler(
            bus=system.global_queue,
            universe=universe,
            feed=system.feed,
            config=UniverseHandlerConfig(
                poll_timeframe="1d", remove_policy=remove_policy
            ),
        )
        # Real read model (open-position truth) + paper provider recorder.
        universe_handler.set_portfolio_read_model(system.portfolio_handler)
        universe_handler.set_provider(provider)

        return _RemovePolicyHarness(
            system=system,
            universe=universe,
            universe_handler=universe_handler,
            provider=provider,
            portfolio_id=portfolio_id,
            held_symbol=held,
            other_symbol=other,
        )

    return _make

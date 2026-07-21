"""Pair close-only / safe-when-flat exit — the D-12 trace as a live test (PAIR-01).

The property the whole in-pair-flag design rests on (D-12 / 06-RESEARCH Pitfall 1):
a quantity-free ``exit_fraction = Decimal("1")`` close resolves as "close existing
position, no-op when flat". This drives the engine's real SIGNAL -> ORDER -> FILL ->
PORTFOLIO path on a SYNTHETIC ticker (NOT BTCUSD — oracle protection) and asserts on
the live read-model + position state.

Two facts are locked:

1. A quantity-free ``exit_fraction = Decimal("1")`` cover of an open short clamps to
   flat — the cover sizes from the open magnitude (``resolve_exit`` D-07 no-op returns
   the full ``net_quantity``) and the short closes to net 0.
2. A quantity-free ``exit_fraction = Decimal("1")`` close issued while ALREADY FLAT
   opens NO new position. The flat-state close is NOT a reduction
   (``admission_manager.py:784`` — ``is_reduction`` is False with no open position),
   and the SHORT_ONLY direction gate rejects a BUY with no open short to cover
   (``admission_manager.py:441`` arm) — so the engine no-ops loudly rather than
   opening a fresh long. This is the engine-level guarantee under-pinning the
   strategy's own in-pair flag (the safe close-only contract).

The inverse hazard (an explicit-``quantity`` exit, which short-circuits the reduction
logic and WOULD open a new position when flat — 06-RESEARCH Pitfall 1) is deliberately
NOT exercised here: every exit below is quantity-free.

The system is constructed with ``allow_short_selling=True`` AND ``enable_margin=True``
(T-06-10 — the short/margin registration + lock-and-settle gate), mirroring the
``partial_cover`` scenario wiring.

Folder-derived ``integration`` marker only (tests/conftest.py applies it).
"""

import pathlib
from decimal import Decimal

from itrader.core.enums import Side
from itrader.core.enums.order import OrderStatus, OrderType
from itrader.core.enums.trading import TradingDirection
from itrader.core.instrument import Instrument
from itrader.core.sizing import FixedQuantity, SignalIntent
from itrader.strategy_handler.base import Strategy
from itrader.trading_system.backtest_trading_system import BacktestTradingSystem
from itrader.universe import Universe
from itrader.config import PortfolioConfig, get_portfolio_preset
from itrader.outils.dict_merge import recursive_merge
from itrader.execution_handler.execution_handler import DEFAULT_ACCOUNT_ID


def _margin_config() -> PortfolioConfig:
    """enable_margin + short selling + max_leverage set in the CONSTRUCTOR config —
    01-03 selects the account leaf at construction, so a post-construction config
    edit no longer rebuilds it (the short leg needs the margin leaf)."""
    return PortfolioConfig.model_validate(recursive_merge(
        get_portfolio_preset("default").model_dump(),
        {"trading_rules": {"enable_margin": True, "allow_short_selling": True,
                           "max_leverage": _PORTFOLIO_MAX_LEVERAGE}},
    ))

HERE = pathlib.Path(__file__).resolve().parent

_TICKER = "PXSAFEUSD"          # synthetic — NEVER BTCUSD (oracle protection)
_CASH = 100_000
_QTY = Decimal("10")
_PORTFOLIO_MAX_LEVERAGE = Decimal("5")


class _CloseOnlyShortStrategy(Strategy):
    """SHORT_ONLY: SELL-to-open on 2020-01-02, a quantity-free full cover
    (``exit_fraction=1``) on 2020-01-04, then ANOTHER quantity-free full cover
    on 2020-01-06 while ALREADY FLAT (the D-12 safe-when-flat probe).

    Every exit is quantity-free (``exit_fraction=Decimal("1")``, no ``quantity``)
    — the safe close-only path. The hazardous explicit-quantity exit is never
    emitted.
    """

    name = "close_only_short"
    max_window = 100
    warmup = 0
    sizing_policy = FixedQuantity(qty=_QTY)
    direction = TradingDirection.SHORT_ONLY

    def __init__(self, timeframe: str, tickers: list[str]) -> None:
        super().__init__(timeframe=timeframe, tickers=list(tickers))

    def generate_signal(self, ticker: str) -> SignalIntent | None:
        date = self.now.tz_convert("UTC").strftime("%Y-%m-%d")
        if date == "2020-01-02":
            # SELL-to-open the short (quantity-free entry, sized by FixedQuantity).
            return SignalIntent(ticker=ticker, action=Side.SELL, order_type=OrderType.MARKET)
        if date in ("2020-01-04", "2020-01-06"):
            # Quantity-free full cover (exit_fraction=1, NO quantity). The first
            # closes the open short to flat; the second fires while flat (no-op).
            return SignalIntent(
                ticker=ticker, action=Side.BUY, order_type=OrderType.MARKET,
                exit_fraction=Decimal("1"))
        return None


def _instrument() -> Instrument:
    return Instrument(
        symbol=_TICKER,
        price_precision=Decimal("0.01"),
        quantity_precision=Decimal("0.00000001"),
        min_order_size=None,
        maintenance_margin_rate=Decimal("0.01"),
        max_leverage=Decimal("10"),
        settles_funding=False,
        borrow_rate=Decimal("0"),
    )


def _build_system():
    system = BacktestTradingSystem(
        exchange="csv",
        csv_paths={_TICKER: HERE / "pair_exit_safety" / "bars.csv"},
        start_date="2020-01-01",
        end_date="2020-01-08",
    )
    # T-06-10: both flags ON so a SHORT_ONLY strategy registers and the
    # lock-and-settle model that can represent a short is active.
    sh = system.strategies_handler
    sh._allow_short_selling = True
    sh._enable_margin = True
    strategy = _CloseOnlyShortStrategy(timeframe="1d", tickers=[_TICKER])
    sh.add_strategy(strategy)
    portfolio_id = system.portfolio_handler.add_portfolio(
        name="exit_safety_pf", exchange="csv", cash=_CASH,
        portfolio_config=_margin_config())
    strategy.subscribe_portfolio(portfolio_id)

    portfolio = system.portfolio_handler.get_portfolio(portfolio_id)
    portfolio.config = portfolio.config.model_copy(update={
        "trading_rules": portfolio.config.trading_rules.model_copy(update={
            "enable_margin": True,
            "allow_short_selling": True,
            "max_leverage": _PORTFOLIO_MAX_LEVERAGE,
        })})
    order_manager = system.order_handler.order_manager
    order_manager.admission_manager._enable_margin = True
    order_manager.admission_manager._portfolio_max_leverage = _PORTFOLIO_MAX_LEVERAGE
    order_manager.order_validator.enable_margin = True

    system.runner._initialise_backtest_session()
    universe = Universe(members=[_TICKER], instrument_map={_TICKER: _instrument()})
    system.execution_handler.exchanges[("simulated", DEFAULT_ACCOUNT_ID)].set_universe(universe)
    system.order_handler.set_universe(universe)
    system.portfolio_handler.set_universe(universe)

    return system, portfolio, portfolio_id


def test_close_only_exit_noop_when_flat():
    """A quantity-free exit_fraction=1.0 cover clamps the short to flat, and a
    second quantity-free exit_fraction=1.0 close fired while flat opens NO new
    position (D-12 safe close-only path, proven live)."""
    system, portfolio, portfolio_id = _build_system()
    engine = system.engine
    handler = system.portfolio_handler

    snaps: dict[str, dict] = {}
    for time_event in engine.time_generator:
        date = time_event.time.tz_convert("UTC").strftime("%Y-%m-%d")
        engine.clock.set_time(time_event.time)
        engine.global_queue.put(time_event)
        engine.event_handler.process_events()
        for active in handler.get_active_portfolios():
            active.record_metrics(time_event.time)

        position = portfolio.get_open_position(_TICKER)
        snaps[date] = {
            "qty": None if position is None else position.net_quantity,
            "side": None if position is None else position.side.name,
        }

    engine.order_handler.expire_all_resting()
    engine.event_handler.process_events()

    # --- SELL-to-open fill (2020-01-03): SHORT 10 opened -------------------------
    opened = snaps["2020-01-03"]
    assert opened["side"] == "SHORT", "SELL-to-open opens a short"
    assert opened["qty"] == _QTY, "FixedQuantity short of 10 opened"

    # --- quantity-free full cover fill (2020-01-05): clamps to flat --------------
    # The cover sizes from the open magnitude (resolve_exit D-07 no-op returns the
    # full net_quantity) and closes the short to net 0 — NOT a flip.
    covered = snaps["2020-01-05"]
    assert covered["side"] is None, "exit_fraction=1 cover clamps the short to flat"
    assert covered["qty"] is None, "no open position remains after the full cover"
    assert len(portfolio.closed_positions) == 1, "the cover closed the short (1 closed)"

    # --- quantity-free close fired WHILE FLAT (2020-01-06/07): NO new position ---
    # admission_manager.py:784 — with no open position is_reduction is False; the
    # SHORT_ONLY direction gate (admission_manager.py:441 arm) rejects a BUY with no
    # open short to cover, so the engine no-ops rather than opening a fresh long.
    flat_after = snaps["2020-01-08"]
    assert flat_after["side"] is None, "a quantity-free close while flat opens NO position (D-12)"
    assert flat_after["qty"] is None, "still flat — the safe-when-flat no-op holds"

    # The flat-state close opened nothing: still exactly the one closed short, and
    # no open position lingers.
    assert len(portfolio.closed_positions) == 1, "no second position was opened/closed"
    assert portfolio.get_open_position(_TICKER) is None, "no open position after the flat close"

    # Order-level proof the flat-state close NO-OPPED loudly (not silently dropped):
    # exactly three orders — SELL-to-open (FILLED), the quantity-free cover (FILLED),
    # and the quantity-free flat-state close (REJECTED at the direction gate). The
    # rejected order is the live engine guarantee under-pinning the close-only contract.
    orders = system.order_handler.get_orders_by_ticker(_TICKER, portfolio_id)
    assert len(orders) == 3, "open SELL + cover BUY + rejected flat-state BUY"
    statuses = [o.status for o in orders]
    assert statuses.count(OrderStatus.FILLED) == 2, "the open and the cover both fill"
    assert statuses.count(OrderStatus.REJECTED) == 1, "the flat-state close is rejected (no-op)"

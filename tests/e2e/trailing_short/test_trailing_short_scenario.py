"""End-to-end SHORT trailing-stop scenario (TRAIL-01/TRAIL-02) — Phase 5 (Plan 05-03).

The short mirror of ``trailing_long``: a SHORT_ONLY strategy declares a trailing-SL
bracket (``PercentFromFill`` with a PERCENT trail), the cover SL child rests as an
engine-native ``TRAILING_STOP`` (a BUY-stop) seeded from the ENTRY FILL (D-TRAIL-3),
ratchets DOWN across falling closed-bar lows (D-TRAIL-1/D-TRAIL-2, favorably-only),
then a bounce triggers the RATCHETED level — NOT the initial seed. Shorts were added
only in Phase 3, so long coverage does NOT transfer (dedicated short e2e).

Synthetic ticker (NEVER BTCUSD) so the SMA_MACD spot oracle stays byte-exact.

================================ HAND COMPUTATION ================================

Price series (``bars.csv`` — daily, tz-aware Open time):

    bar  date         open   high   low    close
    0    2020-01-01   100    100    100    100
    1    2020-01-02   100    100    100    100   <- SELL-to-open decided here (MARKET)
    2    2020-01-03   100    100    90     90    <- parent fills @ OPEN 100 == fill anchor
    3    2020-01-04   90     90     70     70
    4    2020-01-05   70     70     50     50
    5    2020-01-06   50     80     50     75    <- bounce triggers the RATCHETED stop
    6    2020-01-07   75     75     75     75

Trailing SL = PERCENT, trail_value = 0.10 (10% above the running LOW water-mark).
The trail ratchets from the CLOSED-bar LOW and is live for the NEXT bar (D-TRAIL-2:
the level on bar N is derived from bars <= N-1).

NOTE the one-bar arming delay: the cover SL child is created at the parent's fill
and SUBMITTED after bar2's matching pass already ran, so its FIRST ratchet step is
on bar3 (it rests at the seeded level 110 through bar2, then ratchets from bar3 on).

  fill bar2 @100  : seed LWM = anchor = 100; initial stop = 100*(1+0.10) = 110
                    (child submitted post-matching; no bar2 ratchet).
  bar3            : active stop 110; high 90 < 110 -> NO trigger.
                    END-of-bar3 ratchet: LWM = min(100, 70) = 70; stop = 77.
  bar4            : active stop 77; high 70 < 77 -> NO trigger.
                    END-of-bar4 ratchet: LWM = min(70, 50) = 50; stop = 55.
  bar5            : active stop 55; high 80 >= 55 -> TRIGGERS. BUY-stop gap fill at
                    max(open 50, trigger 55) = 55 (pessimistic gap for a buy-stop).

Cover @55 (the RATCHETED level), NOT the initial seed 110. The ratchet earned a
better cover: a fixed 110 stop would have covered at 110 (PnL = (100-110)*qty < 0),
whereas the ratcheted 55 cover yields short PnL = (100-55)*qty > 0.

Sizing: FixedQuantity(qty=10). Short PnL = |size| * (entry - exit) =
10 * (100 - 55) = +450. Zero fee / zero slippage (csv exchange). Unlevered.

================================ END HAND COMPUTATION ================================
"""

import pathlib
from decimal import Decimal

from itrader.config import PortfolioConfig, TrailType, get_portfolio_preset
from itrader.outils.dict_merge import recursive_merge
from itrader.core.enums import Side
from itrader.core.enums.order import OrderStatus, OrderType
from itrader.core.enums.trading import TradingDirection
from itrader.core.instrument import Instrument
from itrader.core.sizing import FixedQuantity, PercentFromFill, SignalIntent
from itrader.strategy_handler.base import Strategy
from itrader.trading_system.backtest_trading_system import BacktestTradingSystem
from itrader.universe import Universe
from itrader.execution_handler.execution_handler import DEFAULT_ACCOUNT_ID

HERE = pathlib.Path(__file__).resolve().parent

_TICKER = "TRAILSHORTUSD"  # synthetic — NEVER BTCUSD.
_CASH = 100_000
_QTY = Decimal("10")
_PORTFOLIO_MAX_LEVERAGE = Decimal("5")
# PERCENT trail: stop = LWM * (1 + 0.10), ratcheting down off falling lows. The
# TP-limit leg (a BUY cover at 100*(1-0.90) = 10) is placed FAR below the price
# path so it never fills — the trailing stop is the only exit (D-TRAIL-5: the
# trailing SL and the TP-limit are independent OCO legs; here the ratcheted stop
# wins on the bounce before the TP is ever reached).
_TRAIL = PercentFromFill(
    sl_pct=Decimal("0.10"), tp_pct=Decimal("0.90"),
    trail_type=TrailType.PERCENT, trail_value=Decimal("0.10"),
)


class _TrailingShortStrategy(Strategy):
    """A SHORT_ONLY strategy that declares a trailing-SL bracket on entry: a single
    MARKET SELL-to-open on 2020-01-02; the trailing BUY-stop cover child rides the
    fill-anchored carve-out (created at the parent's EXECUTED fill)."""

    name = "trailing_short"
    max_window = 100
    warmup = 0
    sizing_policy = FixedQuantity(qty=_QTY)
    sltp_policy = _TRAIL
    direction = TradingDirection.SHORT_ONLY

    def __init__(self, timeframe: str, tickers: list[str]) -> None:
        super().__init__(timeframe=timeframe, tickers=list(tickers))

    def generate_signal(self, ticker: str) -> SignalIntent | None:
        date = self.now.tz_convert("UTC").strftime("%Y-%m-%d")
        if date == "2020-01-02":
            return SignalIntent(ticker=ticker, action=Side.SELL, order_type=OrderType.MARKET)
        return None


def _short_instrument() -> Instrument:
    """Oracle-dark synthetic instrument — borrow_rate 0 (no carry in this scenario)."""
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
        exchange="paper",
        csv_paths={_TICKER: HERE / "bars.csv"},
        start_date="2020-01-01",
        end_date="2020-01-07",
    )
    # Two-flag short registration (SHORT-01) on the StrategiesHandler.
    sh = system.strategies_handler
    sh._allow_short_selling = True
    sh._enable_margin = True
    strategy = _TrailingShortStrategy(timeframe="1d", tickers=[_TICKER])
    sh.add_strategy(strategy)
    portfolio_id = system.portfolio_handler.add_portfolio(
        # 01-03 D-03 (sibling 01-03b finding): the account leaf is selected at
        # CONSTRUCTION from enable_margin; the post-construction config swap below
        # refines the rest but no longer rebuilds the leaf — so margin must be on
        # in the constructor config to get a SimulatedMarginAccount.
        name="trailing_short_pf", exchange="paper", cash=_CASH,
        portfolio_config=PortfolioConfig.model_validate(recursive_merge(
            get_portfolio_preset("default").model_dump(),
            {"trading_rules": {"enable_margin": True}})))
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
    universe = Universe(members=[_TICKER], instrument_map={_TICKER: _short_instrument()})
    system.execution_handler.exchanges[("paper", DEFAULT_ACCOUNT_ID)].set_universe(universe)
    system.order_handler.set_universe(universe)
    system.portfolio_handler.set_universe(universe)
    return system, portfolio_id


def _run(system, portfolio_id):
    engine = system.engine
    handler = system.portfolio_handler
    portfolio = handler.get_portfolio(portfolio_id)
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
    return snaps, portfolio


def test_trailing_short_scenario():
    """A declared trailing SL rests as a BUY-stop, ratchets DOWN off falling lows,
    then a bounce triggers the RATCHETED level (55), not the initial seed (110).
    The realized cover reflects the ratchet; short PnL beats the initial-stop
    cover; the trade reconciles through the mirror (TRAIL-01/TRAIL-02 end-to-end)."""
    system, portfolio_id = _build_system()
    snaps, portfolio = _run(system, portfolio_id)

    # Entry filled bar2 @100: a SHORT position of 10 opened (SELL-to-open).
    opened = snaps["2020-01-03"]
    assert opened["side"] == "SHORT", "MARKET SELL opened a SHORT"
    assert opened["qty"] == Decimal("10")

    # The position survives the falling bars (the active stop is always above the
    # bar high — no premature cover).
    assert snaps["2020-01-04"]["side"] == "SHORT"
    assert snaps["2020-01-05"]["side"] == "SHORT"

    # The bounce on bar5 triggers the RATCHETED BUY-stop -> the short is FLAT.
    assert snaps["2020-01-06"]["qty"] is None, "ratcheted stop covered -> flat"
    assert snaps["2020-01-06"]["side"] is None

    # The realized cover reflects the RATCHETED level (55), NOT the initial seed
    # (110): short PnL = |size| * (entry - exit) = 10 * (100 - 55) = +450, POSITIVE
    # — proof the ratchet earned a better cover than the -100 a fixed-110 stop gives.
    closed = portfolio.closed_positions
    assert len(closed) == 1
    assert closed[0].side.name == "SHORT"
    assert closed[0].realised_pnl == Decimal("450"), \
        "cover @ratcheted 55 -> 10*(100-55) = 450 (initial-stop 110 would be -100)"
    assert closed[0].realised_pnl > Decimal("0"), "the ratchet earned a winning cover"

    # The SL child filled via the execution layer; the mirror reconciled to FILLED
    # — the order handler declared + reconciled but never matched (D-18).
    orders = system.order_handler.get_orders_by_ticker(_TICKER, portfolio_id)
    sl_orders = [o for o in orders if o.type == OrderType.TRAILING_STOP]
    assert len(sl_orders) == 1, "exactly one TRAILING_STOP child was declared"
    assert sl_orders[0].status == OrderStatus.FILLED


def test_trailing_short_scenario_deterministic():
    """Re-running the scenario yields byte-identical realised PnL (determinism)."""
    s1, p1 = _build_system()
    _, portfolio1 = _run(s1, p1)
    s2, p2 = _build_system()
    _, portfolio2 = _run(s2, p2)
    assert portfolio1.closed_positions[0].realised_pnl == \
        portfolio2.closed_positions[0].realised_pnl == Decimal("450")

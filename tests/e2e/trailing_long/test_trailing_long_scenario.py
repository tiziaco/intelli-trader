"""End-to-end LONG trailing-stop scenario (TRAIL-01/TRAIL-02) — Phase 5 (Plan 05-03).

Drives the engine's real SIGNAL -> ORDER -> FILL -> PORTFOLIO path: a strategy
declares a trailing-SL bracket (``PercentFromFill`` carrying a PERCENT trail), the
SL child rests as an engine-native ``TRAILING_STOP`` seeded from the ENTRY FILL
(D-TRAIL-3), ratchets UP across rising closed-bar highs (D-TRAIL-1/D-TRAIL-2,
favorably-only), then a pullback triggers the RATCHETED level — NOT the initial
seed. The realized exit reflects the ratcheted stop, and the trade reconciles
through the order mirror (the order handler declares + reconciles, NEVER matches —
matching stays in the execution layer, D-18 / T-05-07).

Synthetic ticker (NEVER BTCUSD) so the SMA_MACD spot oracle stays byte-exact.

================================ HAND COMPUTATION ================================

Price series (``bars.csv`` — daily, tz-aware Open time):

    bar  date         open   high   low    close
    0    2020-01-01   100    100    100    100
    1    2020-01-02   100    100    100    100   <- BUY decided here (MARKET)
    2    2020-01-03   100    110    100    110   <- parent fills @ OPEN 100 == fill anchor
    3    2020-01-04   110    130    110    130
    4    2020-01-05   130    150    130    150
    5    2020-01-06   150    150    120    125   <- pullback triggers the RATCHETED stop
    6    2020-01-07   125    125    125    125

Trailing SL = PERCENT, trail_value = 0.10 (10% below the running high water-mark).
The trail ratchets from the CLOSED-bar HIGH and is live for the NEXT bar
(D-TRAIL-2 look-ahead safety: the level on bar N is derived from bars <= N-1).

NOTE the one-bar arming delay: the SL child is created at the parent's fill and
SUBMITTED after bar2's matching pass already ran, so its FIRST ratchet step is on
bar3 (it rests at the seeded level 90 through bar2, then ratchets from bar3 on).

  fill bar2 @100  : seed HWM = anchor = 100; initial stop = 100*(1-0.10) = 90
                    (child submitted post-matching; no bar2 ratchet).
  bar3            : active stop 90; low 110 > 90 -> NO trigger.
                    END-of-bar3 ratchet: HWM = max(100, 130) = 130; stop = 117.
  bar4            : active stop 117; low 130 > 117 -> NO trigger.
                    END-of-bar4 ratchet: HWM = max(130, 150) = 150; stop = 135.
  bar5            : active stop 135; low 120 <= 135 -> TRIGGERS. STOP-SELL gap fill
                    at min(open 150, trigger 135) = 135 (pessimistic gap).

Exit @135 (the RATCHETED level), NOT the initial seed 90. The ratchet earned a
better exit: a fixed 90 stop would have exited at 90 (PnL = (90-100)*qty < 0),
whereas the ratcheted 135 exit yields PnL = (135-100)*qty > 0.

Sizing: FixedQuantity(qty=10). Entry 10 @100 -> total_bought 1000; exit 10 @135 ->
total_sold 1350; realised_pnl = 1350 - 1000 = +350 = (135 - 100) * 10. Zero fee /
zero slippage (csv exchange).

================================ END HAND COMPUTATION ================================
"""

import pathlib
from decimal import Decimal

from itrader.config import TrailType
from itrader.core.enums import Side
from itrader.core.enums.order import OrderStatus, OrderType
from itrader.core.enums.trading import TradingDirection
from itrader.core.sizing import FixedQuantity, PercentFromFill, SignalIntent
from itrader.strategy_handler.base import Strategy
from itrader.trading_system.backtest_trading_system import BacktestTradingSystem

HERE = pathlib.Path(__file__).resolve().parent

_TICKER = "TRAILUSD"  # synthetic — NEVER BTCUSD (the spot oracle is untouchable).
_CASH = 100_000
_QTY = Decimal("10")
# PERCENT trail: stop = HWM * (1 - 0.10), ratcheting up off rising highs.
_TRAIL = PercentFromFill(
    sl_pct=Decimal("0.10"), tp_pct=Decimal("5"),
    trail_type=TrailType.PERCENT, trail_value=Decimal("0.10"),
)


class _TrailingLongStrategy(Strategy):
    """A LONG strategy that declares a trailing-SL bracket on entry. A single
    MARKET BUY on 2020-01-02; the trailing SL child rides the fill-anchored
    carve-out (created at the parent's EXECUTED fill)."""

    name = "trailing_long"
    max_window = 100
    warmup = 0
    sizing_policy = FixedQuantity(qty=_QTY)
    sltp_policy = _TRAIL
    direction = TradingDirection.LONG_ONLY

    def __init__(self, timeframe: str, tickers: list[str]) -> None:
        super().__init__(timeframe=timeframe, tickers=list(tickers))

    def generate_signal(self, ticker: str) -> SignalIntent | None:
        date = self.now.tz_convert("UTC").strftime("%Y-%m-%d")
        if date == "2020-01-02":
            return SignalIntent(ticker=ticker, action=Side.BUY, order_type=OrderType.MARKET)
        return None


def _build_system():
    system = BacktestTradingSystem(
        exchange="csv",
        csv_paths={_TICKER: HERE / "bars.csv"},
        start_date="2020-01-01",
        end_date="2020-01-07",
    )
    strategy = _TrailingLongStrategy(timeframe="1d", tickers=[_TICKER])
    system.strategies_handler.add_strategy(strategy)
    portfolio_id = system.portfolio_handler.add_portfolio(
        user_id=1, name="trailing_long_pf", exchange="csv", cash=_CASH)
    strategy.subscribe_portfolio(portfolio_id)
    system.runner._initialise_backtest_session()
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


def test_trailing_long_scenario():
    """A declared trailing SL rests, ratchets up off rising highs, then a pullback
    triggers the RATCHETED level (135), not the initial seed (90). The realized
    exit reflects the ratchet; PnL beats the initial-stop exit; the trade
    reconciles through the mirror (TRAIL-01/TRAIL-02 end-to-end)."""
    system, portfolio_id = _build_system()
    snaps, portfolio = _run(system, portfolio_id)

    # Entry filled bar2 @100: a LONG position of 10 opened.
    opened = snaps["2020-01-03"]
    assert opened["side"] == "LONG", "MARKET BUY opened a LONG"
    assert opened["qty"] == Decimal("10")

    # The position survives the rising bars (the trailing stop ratchets but the
    # active level is always below the bar low — no premature trigger).
    assert snaps["2020-01-04"]["side"] == "LONG"
    assert snaps["2020-01-05"]["side"] == "LONG"

    # The pullback on bar5 triggers the RATCHETED stop -> the position is FLAT.
    assert snaps["2020-01-06"]["qty"] is None, "ratcheted stop triggered -> flat"
    assert snaps["2020-01-06"]["side"] is None

    # The realized exit reflects the RATCHETED level (135), NOT the initial seed
    # (90): realised_pnl = (135 - 100) * 10 = +350, which is POSITIVE — proof the
    # ratchet earned a better exit than the -100 a fixed-90 stop would have given.
    closed = portfolio.closed_positions
    assert len(closed) == 1
    assert closed[0].side.name == "LONG"
    assert closed[0].realised_pnl == Decimal("350"), \
        "exit @ratcheted 135 -> (135-100)*10 = 350 (initial-stop 90 would be -100)"
    assert closed[0].realised_pnl > Decimal("0"), "the ratchet earned a winning exit"

    # The SL child filled via the execution layer; the order mirror reconciled to
    # FILLED — the order handler declared + reconciled but never matched (D-18).
    orders = system.order_handler.get_orders_by_ticker(_TICKER, portfolio_id)
    sl_orders = [o for o in orders if o.type == OrderType.TRAILING_STOP]
    assert len(sl_orders) == 1, "exactly one TRAILING_STOP child was declared"
    assert sl_orders[0].status == OrderStatus.FILLED


def test_trailing_long_scenario_deterministic():
    """Re-running the scenario yields byte-identical realised PnL (determinism:
    no per-call RNG, the seeded engine is reused)."""
    s1, p1 = _build_system()
    _, portfolio1 = _run(s1, p1)
    s2, p2 = _build_system()
    _, portfolio2 = _run(s2, p2)
    assert portfolio1.closed_positions[0].realised_pnl == \
        portfolio2.closed_positions[0].realised_pnl == Decimal("350")

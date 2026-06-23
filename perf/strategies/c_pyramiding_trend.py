"""Coverage instrument C — pyramiding trend (LONG_ONLY, allow_increase=True).

================================ COVERAGE INSTRUMENT ================================
This is NOT a real/product strategy. It exists ONLY to exercise engine paths for
the performance benchmark. It deliberately over-extends to trigger rejections.
Never tradeable.
====================================================================================

Engine path owned (PERF-BASELINE §6):
- **Repeated admission** + **position averaging** (``allow_increase = True`` —
  RECON §4: with the increase gate open, repeated same-direction ``buy()`` on an
  open long falls through to sizing and averages in, instead of being rejected as
  a duplicate)
- **Insufficient-funds rejections** (``FillEvent(REFUSED)`` -> order-mirror
  reconcile). Sizing has NO cash headroom cap so the strategy over-extends and the
  rejections fire from CASH for free (not from a duplicate guard).

Signal: a cheap trend-continuation condition — short MA above long MA AND the
close rising vs the prior bar -> a (bracketed) ``buy()`` that adds to the open
long every continuation bar. Instrument: BTCUSDT.
"""

from decimal import Decimal

from itrader.core.enums import TradingDirection
from itrader.core.sizing import FractionOfCash, SignalIntent
from itrader.strategy_handler.base import Strategy
from itrader.strategy_handler.indicators import SMA
from itrader.strategy_handler.primitives import is_above

__all__ = ["PyramidingTrendStrategy"]

_SL_PCT = Decimal("0.03")  # aggregate stop a few % below the latest add


class PyramidingTrendStrategy(Strategy):
    """C: pyramiding trend — repeated same-direction buys average into one long.

    ``allow_increase = True`` is what lets the repeated buys average in (RECON
    §4). Sizing is uncapped (FractionOfCash 0.95 per add) so the position
    over-extends and the engine's CASH reservation gate fires the
    insufficient-funds rejections the benchmark wants to exercise.
    """

    name = "C_pyramiding_trend"
    tickers = ["BTCUSDT"]
    # 0.95 per add with allow_increase -> rapidly over-extends -> CASH rejections.
    sizing_policy = FractionOfCash(Decimal("0.95"))
    direction = TradingDirection.LONG_ONLY
    # RECON §4: open the increase gate so repeated buys average in.
    allow_increase = True
    short_window: int = 20
    long_window: int = 50

    def init(self) -> None:
        self.short_sma = self.indicator(SMA, "close", self.short_window)
        self.long_sma = self.indicator(SMA, "close", self.long_window)

    def generate_signal(self, ticker: str) -> SignalIntent | None:
        # Trend-continuation: uptrend filter + a rising close vs the prior bar.
        if is_above(self.short_sma, self.long_sma):
            close = float(self.bars["close"].iloc[-1])
            prev = float(self.bars["close"].iloc[-2]) if len(self.bars) >= 2 else close
            if close > prev:
                sl = Decimal(str(close)) * (Decimal("1") - _SL_PCT)
                # Repeated buys -> averaging (allow_increase) + CASH rejections.
                return self.buy(ticker, sl=sl)
        return None

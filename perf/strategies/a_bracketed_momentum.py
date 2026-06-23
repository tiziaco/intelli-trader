"""Coverage instrument A — bracketed momentum (LONG_ONLY).

================================ COVERAGE INSTRUMENT ================================
This is NOT a real/product strategy. It exists ONLY to exercise engine paths for
the performance benchmark. It deliberately trades at trade-density-maximising
thresholds, not for alpha. Never mistake it for a tradeable strategy.
====================================================================================

Engine path owned (PERF-BASELINE §6):
- Market-order fill
- **Bracket / parent-child OCO + same-bar priority** (every entry declares both
  ``sl`` and ``tp`` -> a bracket with two OCO children)
- Resting **stop** (SL child) + resting **limit** (TP child) trigger evaluation
- Gap-aware intrabar fills (on gappy 5m bars same-bar double-triggers fire — the
  nastiest matching corner)

Signal: reuse the SMA_MACD crossover signal (same SMA/MACDHist init, same
crossover trigger), changing ONLY the order plumbing — every entry returns a
bracketed ``buy()`` with sl a few % below and tp a few % above the decision close.
Instrument: BTCUSDT.
"""

from decimal import Decimal

from itrader.core.enums import TradingDirection
from itrader.core.sizing import FractionOfCash, SignalIntent
from itrader.strategy_handler.base import Strategy
from itrader.strategy_handler.indicators import SMA, MACDHist
from itrader.strategy_handler.primitives import crossover, crossunder, is_above

__all__ = ["BracketedMomentumStrategy"]

# Bracket offsets (fractions of decision close). Wide enough that brackets rest
# and trigger over gappy 5m bars; this is a coverage instrument, not alpha.
_SL_PCT = Decimal("0.02")
_TP_PCT = Decimal("0.03")


class BracketedMomentumStrategy(Strategy):
    """A: bracketed momentum — every entry declares an OCO bracket (sl + tp)."""

    name = "A_bracketed_momentum"
    tickers = ["BTCUSDT"]
    sizing_policy = FractionOfCash(Decimal("0.95"))
    direction = TradingDirection.LONG_ONLY
    short_window: int = 50
    long_window: int = 100
    fast_window: int = 6
    slow_window: int = 12
    signal_window: int = 3

    def init(self) -> None:
        self.short_sma = self.indicator(SMA, "close", self.short_window)
        self.long_sma = self.indicator(SMA, "close", self.long_window)
        self.macd_hist = self.indicator(
            MACDHist, "close", self.fast_window, self.slow_window, self.signal_window
        )

    def generate_signal(self, ticker: str) -> SignalIntent | None:
        # Reuse the SMA_MACD trigger; change only the order plumbing (bracket).
        if is_above(self.short_sma, self.long_sma):
            if crossover(self.macd_hist, 0):
                close = Decimal(str(self.bars["close"].iloc[-1]))
                sl = close * (Decimal("1") - _SL_PCT)
                tp = close * (Decimal("1") + _TP_PCT)
                # Both sl and tp -> bracket / OCO children (the path A owns).
                return self.buy(ticker, sl=sl, tp=tp)
            if crossunder(self.macd_hist, 0):
                return self.sell(ticker)
        return None

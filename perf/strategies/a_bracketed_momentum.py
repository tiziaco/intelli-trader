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

Exit path — bracket-only (260623-f80):
A previously ALSO closed long on a downward ``macd_hist`` zero-cross via a
discretionary exit order. That exit was sized off this instrument's
``FractionOfCash(0.95)`` sizing policy — i.e. off CASH, NOT off the held position
quantity — so A over-sold: it built a net-short inventory that the spot LONG_ONLY
engine mislabeled LONG with a positive ``market_value``, yielding phantom ~$10M
equity on a $100k start. The net inventory never returned to 0, so the long never
closed; with ``max_positions=1`` every later entry was then blocked and fills
FROZE after January despite ~400 entry + ~400 exit signals/month through June.

The discretionary exit branch is therefore removed. The OCO bracket
(``sl``/``tp`` children, declared on EVERY entry) is now A's sole declared exit
path: its children close EXACTLY the entry quantity, so over-sell is impossible and
longs close cleanly — letting A recycle across the full window. This is the direct
analog of the 260623-bmg recycle fix applied to B/C/D.

Note: a SEPARATE engine-level anomaly (spot LONG_ONLY permitting over-sell into a
net-short inventory carrying a positive ``market_value`` / phantom equity) is being
investigated under a ``/gsd:debug`` session. THIS change does NOT attempt to fix
the engine — it only removes the cash-sized discretionary exit that triggered it.
"""

from decimal import Decimal

from itrader.core.enums import TradingDirection
from itrader.core.sizing import FractionOfCash, SignalIntent
from itrader.strategy_handler.base import Strategy
from itrader.strategy_handler.indicators import SMA, MACDHist
from itrader.strategy_handler.primitives import crossover, is_above

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
                # P5-D13a: the per-tick self.bars window is gone — read the decision
                # close off the latest pushed bar (bar.close is already Decimal).
                close = self.latest_bar(ticker).close  # IN-02: bar.close is already Decimal
                sl = close * (Decimal("1") - _SL_PCT)
                tp = close * (Decimal("1") + _TP_PCT)
                # Both sl and tp -> bracket / OCO children (the path A owns).
                # The OCO children are A's SOLE exit: they close EXACTLY the entry
                # quantity, so the long closes cleanly and A recycles. The old
                # discretionary downward-zero-cross exit was sized off FractionOfCash
                # (CASH), not the held quantity -> over-sold into a phantom net-short;
                # removed (260623-f80, see module docstring).
                return self.buy(ticker, sl=sl, tp=tp)
        return None

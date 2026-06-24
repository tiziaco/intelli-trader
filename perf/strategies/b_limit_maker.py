"""Coverage instrument B — limit-maker mean reversion (LONG_ONLY).

================================ COVERAGE INSTRUMENT ================================
This is NOT a real/product strategy. It exists ONLY to exercise engine paths for
the performance benchmark. Trade-density over alpha. Never tradeable.
====================================================================================

Engine path owned (PERF-BASELINE §6):
- **Resting-limit book at scale** (every entry is a resting ``buy_limit`` below
  the current price)
- Multi-symbol per-bar fan-out (ETHUSDT, SOLUSDT, BNBUSDT)
- **Order cancel / modify + mirror reconcile** — NOTE: the cancel/modify
  lifecycle is NOT reachable from ``generate_signal`` (the intent is order-ref
  -free, RECON §3). It lives in the W1 RUNNER's ``on_tick`` hook, which tracks
  this strategy's resting limit IDs and re-prices / cancels unfilled limits each
  bar. The strategy only EMITS the resting limit.

Signal: a cheap mean-reversion condition — price below a moving average by a
band -> rest a ``buy_limit`` a little below the current close, bracketed by a
TIGHT ``tp`` (above) AND ``sl`` (below). The tight exit leg makes the filled long
RECYCLE — close -> free a ``max_positions`` slot -> re-rest a new limit — which
keeps the resting-limit book churning every bar (density is the coverage here,
not alpha). Reuses the SMA init pattern. Instruments: ETHUSDT, SOLUSDT, BNBUSDT.
"""

from decimal import Decimal

from itrader.core.enums import TradingDirection
from itrader.core.sizing import FractionOfCash, SignalIntent
from itrader.strategy_handler.base import Strategy
from itrader.strategy_handler.indicators import SMA

__all__ = ["LimitMakerStrategy"]

# Mean-reversion band + resting-limit / tp offsets (fractions of close).
# Band kept loose (any dip below the MA) so the resting-limit book is densely
# populated each bar — the "resting-limit book at scale" path is the coverage,
# exercised by the many orders the runner's on_tick chases/cancels, not just the
# fills.
_BAND_PCT = Decimal("0.000")    # enter on any close below the MA
_LIMIT_BELOW = Decimal("0.001")  # rest the limit 0.1% below the current close
# Tight exit bracket so the filled long RECYCLES (close -> frees a max_positions
# slot -> re-rests a new limit) instead of resting forever — keeps the
# resting-limit book churning every bar (density is the coverage, not alpha).
_TP_ABOVE = Decimal("0.005")     # take profit ~0.5% above the limit (tight -> recycles)
_SL_BELOW = Decimal("0.01")      # stop ~1% below the limit (the other exit leg)


class LimitMakerStrategy(Strategy):
    """B: limit-maker mean reversion — rests buy_limit orders below price.

    The runner's ``on_tick`` re-prices / cancels this strategy's unfilled resting
    limits each bar (that is where the cancel/modify coverage is honestly owned).
    """

    name = "B_limit_maker"
    tickers = ["ETHUSDT", "SOLUSDT", "BNBUSDT"]
    # Smaller fraction than A/C so three symbols share the portfolio cash and many
    # limits can rest concurrently (resting-limit book at scale).
    sizing_policy = FractionOfCash(Decimal("0.15"))
    direction = TradingDirection.LONG_ONLY
    # Allow a position per symbol concurrently (the multi-symbol resting-limit
    # book at scale path); the default max_positions=1 would cap B at one open
    # position across all three symbols and starve the coverage.
    max_positions = 3
    ma_window: int = 50

    def init(self) -> None:
        self.ma = self.indicator(SMA, "close", self.ma_window)

    def generate_signal(self, ticker: str) -> SignalIntent | None:
        # P5-D13a: the per-tick self.bars window is gone — read the decision close
        # off the latest pushed bar (bar.close is already Decimal).
        close = Decimal(str(self.latest_bar(ticker).close))
        ma = Decimal(str(self.ma[-1]))
        # Mean reversion: when close sits a band below the MA, rest a limit a bit
        # lower still (a maker order that fills on a further dip).
        threshold = ma * (Decimal("1") - _BAND_PCT)
        if close <= threshold:
            limit_price = close * (Decimal("1") - _LIMIT_BELOW)
            # Both exit legs (tp above, sl below) so the filled long always closes
            # quickly and frees its slot to re-rest — recycling for density.
            tp = limit_price * (Decimal("1") + _TP_ABOVE)
            sl = limit_price * (Decimal("1") - _SL_BELOW)
            return self.buy_limit(ticker, price=limit_price, sl=sl, tp=tp)
        return None

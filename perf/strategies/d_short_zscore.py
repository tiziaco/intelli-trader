"""Coverage instrument D — short z-score (SHORT_ONLY).

================================ COVERAGE INSTRUMENT ================================
This is NOT a real/product strategy. It exists ONLY to exercise engine paths for
the performance benchmark. Cheap deterministic signal, never tradeable.
====================================================================================

Engine path owned (PERF-BASELINE §6):
- **Short-side admission** (the unfunded-short path)
- **1 strategy -> 3 portfolios fan-out** (D feeds P4/P5/P6 via
  ``subscribe_portfolio``; the SHORT-selling system wiring is the RUNNER's job,
  Task 4 recipe — the strategy only declares ``direction = SHORT_ONLY``)
- Short-side **rejections** (``FillEvent(REFUSED)``) under the fan-out

Signal — deliberately CHEAP (spec §4/§6: D's compute must add NO artificial CPU,
so the framework-CPU hotspots come from the matching engine / bar feed, not from
D's signal). A rolling z-score of the ETHUSDT close: when the close is an extreme
number of std-devs ABOVE its rolling mean, ``sell()`` (short the mean-reversion),
bracketed by a SHORT exit (``tp`` below entry to cover in profit, ``sl`` above to
cover the loss). The tight exit makes the short COVER and re-short repeatedly, so
short-side admission + the 3-portfolio fan-out + rejections fire many times per
portfolio instead of opening one short and capping at ``max_positions``.

DEVIATION (documented): the spec names a z-score of the ETHUSDT/SOLUSDT price
RATIO. A cross-symbol ratio is NOT reachable from the single-ticker
``generate_signal`` contract (the pure strategy only sees one ticker's window,
and the two-leg PairStrategy path is a heavier, separate machinery). To stay
within the cheap-single-signal intent while honestly tripping the short-side
admission + fan-out paths, D uses a rolling z-score of the ETHUSDT close itself
(same cost class, same SHORT_ONLY coverage). The ORDER is on ETHUSDT either way.
"""

from decimal import Decimal

import numpy as np

from itrader.core.enums import TradingDirection
from itrader.core.sizing import FractionOfCash, SignalIntent
from itrader.strategy_handler.base import Strategy

__all__ = ["ShortZScoreStrategy"]

_Z_WINDOW = 50            # rolling window for mean/std of the close
_Z_ENTRY = 1.0           # short when z-score >= this (close stretched ABOVE mean)
# Short-side exit bracket (SHORT semantics: tp BELOW entry = cover in profit when
# price falls; sl ABOVE entry = cover the loss when price rises). Tight so the
# short COVERS and re-shorts repeatedly — exercising short-side admission +
# fan-out + rejections many times per portfolio instead of one capped short.
_TP_BELOW = Decimal("0.01")    # cover ~1% BELOW entry (short profit)
_SL_ABOVE = Decimal("0.015")   # cover ~1.5% ABOVE entry (short stop)


class ShortZScoreStrategy(Strategy):
    """D: short-only rolling z-score of the ETHUSDT close (cheap signal).

    The short-selling wiring (handler/admission/validator/portfolio margin flags)
    is applied by the W1 runner (Task 4 recipe); the strategy only declares
    ``SHORT_ONLY``. Fanned out to P4/P5/P6 via ``subscribe_portfolio``.
    """

    name = "D_short_zscore"
    tickers = ["ETHUSDT"]
    # Modest fraction so the short fan-out across three portfolios can over-extend
    # some legs (exercising short-side rejections) without instantly busting all.
    sizing_policy = FractionOfCash(Decimal("0.30"))
    direction = TradingDirection.SHORT_ONLY
    # Allow repeated short entries (re-shorting after a cover) so the short-side
    # admission + fan-out paths fire more than once per portfolio; the default
    # max_positions=1 would cap D at a single short per portfolio.
    max_positions = 5
    z_window: int = _Z_WINDOW
    # D has NO declared indicators, so the base would auto-derive max_window == 0
    # and the feed would hand us an EMPTY window every tick (frame.iloc[pos:pos]).
    # Pin a fetch width >= the z-window so the feed gives us a real window; warmup
    # stays 0 (the rolling deque self-gates until it fills).
    max_window: int = _Z_WINDOW

    def init(self) -> None:
        # No heavy indicator / cointegration compute — the z-score is computed
        # directly off the bar window in generate_signal (cheap, stateless).
        ...

    def generate_signal(self, ticker: str) -> SignalIntent | None:
        # P5-D13a: the per-tick self.bars window is GONE — read the trailing closes
        # via the base's recent_closes(ticker) seam (depth == max_window == z_window).
        # Self-gate until z_window bars have arrived (the old len(self.bars) guard).
        closes_list = self.recent_closes(ticker)
        if len(closes_list) < self.z_window:
            return None
        # Rolling z-score of the close over the last z_window bars (cheap, pure
        # numpy off the bounded recent-close buffer).
        closes = np.asarray(closes_list[-self.z_window:], dtype=float)
        close = float(closes[-1])
        mean = float(closes.mean())
        std = float(closes.std())  # population std (ddof=0)
        if std == 0.0:
            return None
        z = (close - mean) / std
        # Short when the close is stretched ABOVE its rolling mean (revert down).
        if z >= _Z_ENTRY:
            # Build the SHORT exit bracket off the current close as Decimal (NEVER
            # Decimal(float)). tp BELOW / sl ABOVE for a short — the short covers
            # and re-shorts, firing short-side admission + fan-out repeatedly.
            close_d = Decimal(str(close))
            tp = close_d * (Decimal("1") - _TP_BELOW)
            sl = close_d * (Decimal("1") + _SL_ABOVE)
            return self.sell(ticker, sl=sl, tp=tp)
        return None

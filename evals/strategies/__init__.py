"""Coverage instruments A-D for the evals harness (NOT alpha).

Each strategy exists ONLY to exercise a set of engine paths for the performance
benchmark (PERF-BASELINE §4/§6). They deliberately trade at trade-density
thresholds (even at a loss) and must never be mistaken for real strategies — the
``evals/`` home makes that unambiguous.

- A — BracketedMomentumStrategy  (LONG_ONLY, every entry a bracket/OCO)
- B — LimitMakerStrategy         (LONG_ONLY, resting limits + runner cancel/modify)
- C — PyramidingTrendStrategy    (LONG_ONLY, allow_increase, CASH rejections)
- D — ShortZScoreStrategy        (SHORT_ONLY, short-side admission + fan-out)
"""

from .a_bracketed_momentum import BracketedMomentumStrategy
from .b_limit_maker import LimitMakerStrategy
from .c_pyramiding_trend import PyramidingTrendStrategy
from .d_short_zscore import ShortZScoreStrategy

__all__ = [
    "BracketedMomentumStrategy",
    "LimitMakerStrategy",
    "PyramidingTrendStrategy",
    "ShortZScoreStrategy",
]

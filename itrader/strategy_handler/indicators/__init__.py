"""
Declared-indicator framework package (IND-01, D-03/D-04/D-05/D-07/D-08).

The barrel for the first-party indicator subsystem (amended D-05 — a folder
package matching ``fee_model/``/``slippage_model/``/``exchanges/``). Authors do
``from itrader.strategy_handler.indicators import SMA, MACDHist`` and the base
does ``from itrader.strategy_handler.indicators import IndicatorHandle``.

- ``catalog.py`` — the typed adapter catalog (SMA/MACDHist/EMA/RSI + the
  ``IndicatorAdapter`` Protocol).
- ``handle.py`` — ``IndicatorHandle``, the thin positional-index wrapper (D-03),
  moved OUT of ``base.py`` (it belongs to the indicator subsystem, not the
  ``Strategy`` ABC; one-directional ``base -> indicators``, no cycle).
"""

from .catalog import EMA, MACDHist, RSI, SMA, IndicatorAdapter
from .handle import IndicatorHandle

__all__ = [
	"EMA",
	"MACDHist",
	"RSI",
	"SMA",
	"IndicatorAdapter",
	"IndicatorHandle",
]

"""
Declared-indicator framework package (IND-01, D-03/D-04/D-05/D-07/D-08).

The barrel for the first-party indicator subsystem (amended D-05 — a folder
package matching ``fee_model/``/``slippage_model/``/``exchanges/``). Authors do
``from itrader.strategy_handler.indicators import SMA, MACDHist`` and the base
does ``from itrader.strategy_handler.indicators import IndicatorHandle``.

- ``catalog.py`` — the typed adapter catalog (SMA/MACDHist/EMA/RSI + the
  ``IndicatorAdapter`` / ``IndicatorState`` Protocols; PERF-05 stateful recurrences,
  P5-D07/D11/D12 — ``ta`` dropped on the runtime path).
- ``handle.py`` — ``IndicatorHandle``, the thin positional-index wrapper over the
  ``update()``-driven bounded output buffer (D-03 / P5-D08), moved OUT of ``base.py``
  (it belongs to the indicator subsystem, not the ``Strategy`` ABC; one-directional
  ``base -> indicators``, no cycle).
"""

from .catalog import EMA, MACDHist, RSI, SMA, IndicatorAdapter, IndicatorState
from .handle import IndicatorHandle

__all__ = [
	"EMA",
	"MACDHist",
	"RSI",
	"SMA",
	"IndicatorAdapter",
	"IndicatorState",
	"IndicatorHandle",
]

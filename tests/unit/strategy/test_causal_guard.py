"""P5-D20 causal guard — the decision path rejects non-causal adapters.

All v1 adapters declare ``causal = True``; a registered adapter with
``causal = False`` is REJECTED at the ``Strategy.indicator()`` registration
boundary (raise explicitly — mirror the handle's RuntimeError-not-assert
discipline so the contract survives ``-O``).

Also covers the Task-2 per-symbol fan-out surfaces (update/is_ready/reset) and
independent per-symbol readiness (P5-D10/D10b). TAB-indented (Pitfall 6).
"""

from datetime import timedelta
from decimal import Decimal

import pytest

from itrader.core.sizing import FractionOfCash, TradingDirection
from itrader.strategy_handler.base import Strategy
from itrader.strategy_handler.indicators import EMA, MACDHist, RSI, SMA
from itrader.strategy_handler.indicators.catalog import (
	_EMA,
	_MACDHist,
	_RSI,
	_SMA,
)


class _NonCausalAdapter:
	"""A stub adapter that peeks the future (causal=False) — must be rejected."""

	causal = False

	def new_state(self):  # pragma: no cover - never reached (rejected at registration)
		raise AssertionError("non-causal adapter must be rejected before use")

	def min_period(self, params: tuple[int, ...]) -> int:
		return 1


# --- all v1 adapters are causal=True (P5-D20) ------------------------------

def test_v1_adapters_are_causal():
	assert _SMA().causal is True
	assert _EMA().causal is True
	assert _MACDHist().causal is True
	assert _RSI().causal is True
	# The exported singletons too.
	assert SMA.causal is True
	assert EMA.causal is True
	assert MACDHist.causal is True
	assert RSI.causal is True


# --- the decision path rejects a non-causal adapter (P5-D20) ----------------

class _SingleSMAStrategy(Strategy):
	name = "single_sma"
	sizing_policy = FractionOfCash(Decimal("0.95"))
	direction = TradingDirection.LONG_ONLY
	short_window: int = 50

	def init(self) -> None:
		self.sma = self.indicator(SMA, "close", self.short_window)

	def generate_signal(self, ticker):  # pragma: no cover - not exercised here
		return None


class _NonCausalStrategy(Strategy):
	name = "non_causal"
	sizing_policy = FractionOfCash(Decimal("0.95"))
	direction = TradingDirection.LONG_ONLY

	def init(self) -> None:
		# Registering a non-causal adapter must raise at the registration boundary.
		self.bad = self.indicator(_NonCausalAdapter(), "close", 1)

	def generate_signal(self, ticker):  # pragma: no cover
		return None


def test_non_causal_adapter_rejected_at_registration():
	with pytest.raises(RuntimeError):
		_NonCausalStrategy(timeframe="1d", tickers=["BTCUSD"])


def test_causal_adapter_registers_fine():
	strat = _SingleSMAStrategy(timeframe="1d", tickers=["BTCUSD"])
	assert strat.warmup == 50


# --- Task 2: per-symbol fan-out + independent readiness (P5-D10/D10b) -------

class _Bar:
	"""Minimal bar stub exposing the input columns the adapters read.

	Plan C (P5-D13a): ``update`` now also stashes the decision anchor
	``self.now = bar.time``, so the stub carries a ``time`` (a plain int tick here —
	readiness/fan-out is what these tests exercise, the anchor value is unused).
	"""

	def __init__(self, close: float, time: int = 0) -> None:
		self.close = close
		self.time = time


def _make_dual_sma():
	"""A strategy with a short+long SMA on close, two tickers."""

	class _DualSMA(Strategy):
		name = "dual_sma"
		sizing_policy = FractionOfCash(Decimal("0.95"))
		direction = TradingDirection.LONG_ONLY
		short_window: int = 3
		long_window: int = 5

		def init(self) -> None:
			self.short_sma = self.indicator(SMA, "close", self.short_window)
			self.long_sma = self.indicator(SMA, "close", self.long_window)

		def generate_signal(self, ticker):  # pragma: no cover
			return None

	return _DualSMA(timeframe="1d", tickers=["BTCUSD", "ETHUSD"])


def test_per_symbol_readiness_is_independent():
	strat = _make_dual_sma()
	# Warm BTCUSD fully (>= long_window 5); leave ETHUSD cold.
	for px in (100.0, 101.0, 102.0, 103.0, 104.0, 105.0):
		strat.update("BTCUSD", _Bar(px))
	assert strat.is_ready("BTCUSD") is True
	# ETHUSD never updated -> not ready (independent fan-out, P5-D10b).
	assert strat.is_ready("ETHUSD") is False
	# Feed ETHUSD a few bars (< long_window) -> still not ready.
	for px in (200.0, 201.0):
		strat.update("ETHUSD", _Bar(px))
	assert strat.is_ready("ETHUSD") is False
	# BTCUSD readiness is untouched by ETHUSD's updates.
	assert strat.is_ready("BTCUSD") is True


def test_reset_clears_fanout_map():
	strat = _make_dual_sma()
	for px in (100.0, 101.0, 102.0, 103.0, 104.0, 105.0):
		strat.update("BTCUSD", _Bar(px))
	assert strat.is_ready("BTCUSD") is True
	strat.reset()
	# After reset() the fan-out map is cleared — BTCUSD is cold again.
	assert strat.is_ready("BTCUSD") is False


def test_update_unknown_ticker_is_lazy():
	"""A ticker's handle-set is created lazily on its first bar (P5-D10a)."""
	strat = _make_dual_sma()
	# Before any update, no symbol is ready.
	assert strat.is_ready("BTCUSD") is False
	strat.update("BTCUSD", _Bar(100.0))
	# One bar < short_window -> created but not ready.
	assert strat.is_ready("BTCUSD") is False

"""WD-1/WD-2 — the ``mark_unwarm()`` re-warm seam on ``Strategy`` / ``PairStrategy``.

**WD-1.** 10-03 placed the D-07 ``is_active`` guard FIRST in the ``calculate_signals``
loop, so ``strategy.update`` never runs while a strategy is disabled and its indicator
state FREEZES. A strategy re-enabled after N disabled bars would therefore compute its
first signal from a window containing an N-bar HOLE — SMA/MACD spanning that
discontinuity silently produce wrong values. ``enable`` must force a re-warm; this module
pins the seam that makes that possible.

**WD-2 — where the seam lives, and what it must NOT be.**

* It is owned by ``Strategy`` (``base.py``), NOT by ``StrategiesHandler``. An
  ``_unwarm: set[str]`` on the handler would be a SECOND source of truth for warmth that
  can contradict ``is_ready``, desyncing on rename or removal.
* It is **NOT a boolean flag**. Warmth is DERIVED from the indicator handles
  (``is_ready`` = ``all(state.is_ready)``, P5-D06/D10b), so a ``self._warm = False`` flag
  would immediately diverge from the computed truth. ``mark_unwarm`` is a NAMED WRAPPER
  over the existing handle reset — ``is_ready`` stays the single computed truth.
* **It MUST cover the pair arm.** A ``PairStrategy``'s warmth is NOT handle-derived: per
  ``strategies_handler._dispatch_pair``, readiness is its own ``is_pair_ready()``
  (β fittable + z tail), explicitly NOT the handle-derived ``warmup`` — which is 0 for a
  handle-free pair, making ``is_ready`` ALWAYS True. A ``mark_unwarm`` that only reset
  handles would leave a pair reporting WARM INSTANTLY while its spread is still cold,
  trading on a cold β — WD-1's exact failure mode re-entering through the pair arm.

TAB-indented (matches ``base.py``/``pair_base.py``). NO ``__init__.py`` in this dir.
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pandas as pd
import pytest

from itrader.core.bar import Bar
from itrader.core.enums import Side
from itrader.core.sizing import FixedQuantity, FractionOfCash, SignalIntent
from itrader.strategy_handler.base import Strategy
from itrader.strategy_handler.indicators import SMA
from itrader.strategy_handler.pair_base import PairStrategy

pytestmark = pytest.mark.unit

_TICKER = "BTCUSD"
_WARMUP = 5


class _SmaStrategy(Strategy):
	"""A minimal handle-bearing strategy — warmth IS handle-derived here."""

	name = "sma_unwarm_probe"
	sizing_policy = FractionOfCash(Decimal("0.5"))

	def init(self) -> None:
		self.sma = self.indicator(SMA, "close", _WARMUP)

	def generate_signal(self, ticker: str) -> "SignalIntent | None":
		return None


class _StubPair(PairStrategy):
	"""A handle-FREE pair — ``is_ready`` is always True; warmth is ``is_pair_ready``."""

	name = "pair_unwarm_probe"
	sizing_policy = FixedQuantity(qty=Decimal("1"))
	beta_warmup = 4
	z_lookback = 2
	max_window = 6

	def evaluate_pair(self, win_A, win_B):  # type: ignore[no-untyped-def]
		return None


def _bar(price: float, *, offset: int = 0) -> Bar:
	stamp = datetime(2020, 1, 1, tzinfo=timezone.utc) + timedelta(days=offset)
	return Bar(
		time=stamp,
		open=Decimal(str(price)),
		high=Decimal(str(price)),
		low=Decimal(str(price)),
		close=Decimal(str(price)),
		volume=Decimal("1"),
	)


def _warm(strategy: Strategy, bars: int) -> None:
	for i in range(bars):
		strategy.update(_TICKER, _bar(100 + i, offset=i))


def _warm_pair(pair: PairStrategy, bars: int) -> None:
	for i in range(bars):
		pair.update_pair(_bar(100 + i, offset=i), _bar(200 + i, offset=i))


# --- the base (handle-derived) arm -----------------------------------------

def test_mark_unwarm_makes_a_warm_strategy_unwarm() -> None:
	"""WD-1 — after unwarm the strategy is NOT ready, so nothing may signal."""
	strategy = _SmaStrategy(timeframe="1d", tickers=[_TICKER])
	_warm(strategy, _WARMUP)
	assert strategy.is_ready(_TICKER) is True

	strategy.mark_unwarm()

	assert strategy.is_ready(_TICKER) is False


def test_mark_unwarm_is_not_a_flag_and_re_warms_from_bars() -> None:
	"""WD-2 — warmth stays DERIVED: feeding bars again re-warms with no flag to unset."""
	strategy = _SmaStrategy(timeframe="1d", tickers=[_TICKER])
	_warm(strategy, _WARMUP)
	strategy.mark_unwarm()
	assert strategy.is_ready(_TICKER) is False

	# Re-warm through the ordinary per-tick path — no special "re-warm" API.
	_warm(strategy, _WARMUP)

	assert strategy.is_ready(_TICKER) is True


def test_mark_unwarm_introduces_no_second_source_of_warmth_truth() -> None:
	"""WD-2 — a ``self._warm`` style flag would diverge from ``is_ready``; assert none exists."""
	strategy = _SmaStrategy(timeframe="1d", tickers=[_TICKER])
	_warm(strategy, _WARMUP)
	strategy.mark_unwarm()

	flags = [
		name for name in vars(strategy)
		if "warm" in name.lower() and isinstance(getattr(strategy, name), bool)
	]
	assert flags == []


def test_mark_unwarm_clears_the_bar_history_so_the_window_is_contiguous() -> None:
	"""WD-1 — an N-bar hole is impossible: the pre-unwarm history is gone entirely."""
	strategy = _SmaStrategy(timeframe="1d", tickers=[_TICKER])
	_warm(strategy, _WARMUP)

	strategy.mark_unwarm()

	assert strategy.bar_count(_TICKER) == 0
	assert strategy.latest_bar(_TICKER) is None


def test_mark_unwarm_is_idempotent() -> None:
	"""Unwarming an already-unwarm strategy is a no-op, not an error."""
	strategy = _SmaStrategy(timeframe="1d", tickers=[_TICKER])
	_warm(strategy, _WARMUP)

	strategy.mark_unwarm()
	strategy.mark_unwarm()

	assert strategy.is_ready(_TICKER) is False


def test_mark_unwarm_lets_a_replayed_warmup_land_after_it() -> None:
	"""The CR-01 monotonic guard must not reject the re-warm replay of OLD bars.

	``on_bars_loaded`` replays a historical window through ``strategy.update``. Without
	clearing ``_last_bar_time``, every replayed bar would be rejected as non-monotonic
	and the strategy would NEVER re-warm — a silent permanent dark strategy.
	"""
	strategy = _SmaStrategy(timeframe="1d", tickers=[_TICKER])
	_warm(strategy, _WARMUP)
	strategy.mark_unwarm()

	# Replay the SAME (now historical) bars, exactly as a warmup backfill would.
	_warm(strategy, _WARMUP)

	assert strategy.is_ready(_TICKER) is True


# --- the pair arm (WD-2's critical case) -----------------------------------

def test_mark_unwarm_covers_the_pair_arm() -> None:
	"""WD-2 — a handle-free pair reports ``is_ready`` True ALWAYS; the real warmth is the spread."""
	pair = _StubPair(timeframe="1d", tickers=["ETHUSD", "BTCUSD"])
	_warm_pair(pair, pair.beta_warmup + pair.z_lookback)
	assert pair.is_pair_ready() is True
	# The trap: handle-derived readiness is vacuously True for a handle-free pair,
	# so a handles-only unwarm would look like it worked while the spread stayed hot.
	assert pair.is_ready("ETHUSD") is True

	pair.mark_unwarm()

	assert pair.is_pair_ready() is False


def test_pair_mark_unwarm_clears_both_leg_buffers() -> None:
	"""A cold β must not be re-fittable from stale buffered closes."""
	pair = _StubPair(timeframe="1d", tickers=["ETHUSD", "BTCUSD"])
	_warm_pair(pair, pair.beta_warmup + pair.z_lookback)

	pair.mark_unwarm()

	win_A, win_B = pair._buffers_as_windows()
	assert len(win_A) == 0
	assert len(win_B) == 0


def test_pair_re_warms_through_the_ordinary_push_path() -> None:
	"""The pair arm re-warms the same way it warmed — no bespoke pipeline."""
	pair = _StubPair(timeframe="1d", tickers=["ETHUSD", "BTCUSD"])
	_warm_pair(pair, pair.beta_warmup + pair.z_lookback)
	pair.mark_unwarm()
	assert pair.is_pair_ready() is False

	_warm_pair(pair, pair.beta_warmup + pair.z_lookback)

	assert pair.is_pair_ready() is True


def test_pair_mark_unwarm_also_resets_the_base_handles() -> None:
	"""The pair arm EXTENDS the base seam — it does not replace it."""
	pair = _StubPair(timeframe="1d", tickers=["ETHUSD", "BTCUSD"])
	_warm_pair(pair, pair.beta_warmup + pair.z_lookback)
	assert pair.now is not None

	pair.mark_unwarm()

	assert pair.now is None
	assert pair.current_bar is None

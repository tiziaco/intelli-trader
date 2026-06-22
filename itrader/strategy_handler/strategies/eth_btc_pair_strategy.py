"""ETH/BTC reference pair strategy — the Phase 6 flagship (PAIR-01).

The concrete two-leg, market-neutral mean-reversion strategy on top of
``PairStrategy`` (Plan 06-01). This is the alpha:

- **β fit-then-freeze (D-04 RESOLVED / D-05).** β is the slope of an OLS fit of
  ``log(close_ETH)`` on ``log(close_BTC)`` over the FIRST ``beta_warmup``
  completed bars only, fit ONCE and cached on the instance — never re-fit. The
  Engle-Granger cointegration p-value is computed on the same warmup window and
  LOGGED as a diagnostic (D-10 RESOLVED — it NEVER gates the run; ETH/BTC does
  not pass strict cointegration but the rolling z-score delivers the round trips).
- **z-score band trigger (D-06).** ``spread = log(ETH) − β·log(BTC)``;
  ``z = (spread − rolling_mean) / rolling_std`` over a fixed ``z_lookback`` of
  completed bars (pandas ``rolling`` default ``ddof=1``).
- **crossing-based stateful firing (D-12/D-13).** ENTER only when ``|z|`` crosses
  INTO the band (was ``<= entry_z``, now ``> entry_z``) while FLAT; EXIT only when
  ``|z|`` crosses back INSIDE (``< exit_z``) while IN-PAIR. The strategy tracks its
  own ``_in_pair`` flag — no portfolio access (pure-alpha contract held).
- **β-weighted explicit-quantity entries (D-06/D-08).** On entry, short the RICH
  leg and long the CHEAP leg: for N units of ETH hold β·N units of BTC. Entries
  carry explicit ``quantity`` (via ``to_money`` — Pitfall 4).
- **quantity-free exits (RESEARCH Pitfall 1).** On exit, emit ``exit_fraction=1``
  intents with NO quantity — the resolver sizes the close from exchange truth and
  clamps to flat. An explicit quantity on an exit would open a NEW position.

Indentation: TABS (match ``SMA_MACD_strategy.py`` / ``base.py``; never normalize).
"""

from decimal import Decimal

import numpy as np
import pandas as pd
import statsmodels.api as sm
from statsmodels.tsa.stattools import coint

from itrader.core.enums import OrderType, Side, TradingDirection
from itrader.core.money import to_money
from itrader.core.sizing import FractionOfCash, SignalIntent
from itrader.strategy_handler.pair_base import PairStrategy

from itrader.logger import get_itrader_logger
logger = get_itrader_logger().bind(component="EthBtcPairStrategy")


class EthBtcPairStrategy(PairStrategy):
	"""Market-neutral ETH/BTC log-spread mean-reversion pair strategy (PAIR-01).

	``tickers[0]`` is the leg A (ETH, the rich-when-z>0 leg) and ``tickers[1]``
	is the leg B (BTC). The alpha is a frozen log-OLS hedge ratio β plus a
	rolling z-score band trigger fired on crossings, with an internal in-pair
	flag (D-12/D-13). It owns NO queue, NO portfolio access (pure-alpha, D-12).
	"""

	name = "ETH_BTC_PAIR"
	# D-08: per-leg quantity is EXPLICIT on entries (β-weighted), so the policy is
	# bypassed on the entry path — but the base requires a valid SizingPolicy. A
	# FractionOfCash placeholder is inert here. Pitfall 4: string-path literal.
	sizing_policy = FractionOfCash(Decimal("0.95"))
	tickers = ["ETHUSD", "BTCUSD"]
	# D-14: inherited from PairStrategy, pinned explicitly for clarity.
	direction = TradingDirection.LONG_SHORT
	# NOTE: ``timeframe`` is a REQUIRED kwarg (base annotates it as a resolved
	# timedelta; a str class-attr would conflict with that annotation). Supply
	# ``timeframe="1d"`` at construction, mirroring SMA_MACD_strategy.

	# Alpha knobs (Pitfall 4: every Decimal via the string path).
	entry_z = Decimal("2")          # |z| threshold to OPEN the spread (D-06)
	exit_z = Decimal("0.5")         # |z| threshold to CLOSE the spread (D-06)
	z_lookback: int = 30            # A3 measured: 30-60 gives a non-trivial count
	beta_warmup: int = 250          # offline: first-250 β≈0.53, R²≈0.57
	leverage = Decimal("1")         # D-09: unlevered legs
	# Pitfall 3: HAND-SET so the handle-free auto-warmup does not collapse the
	# feed window to 0-width. validate() asserts >= beta_warmup + z_lookback.
	max_window: int = 280           # beta_warmup (250) + z_lookback (30)

	# D-08: the number of units of leg A (ETH) opened per entry; leg B (BTC) is
	# β-weighted off it. A class-attr knob so it is overridable / introspectable.
	entry_units: Decimal = Decimal("1")

	def validate(self) -> None:
		# PairStrategy.validate() asserts: exactly two tickers, exit_z < entry_z,
		# max_window >= beta_warmup + z_lookback (Pitfall 3). Keep those.
		super().validate()

	def init(self) -> None:
		# Handle-FREE: the β/z alpha reads self.bars windows via statsmodels/numpy
		# directly (no IndicatorHandle). _run_init leaves warmup == 0; the dispatch
		# gates on beta_warmup + z_lookback (NOT the handle-derived warmup).
		# Reset the fit-once cache + in-pair flag so a reconfigure is idempotent.
		self._beta: float | None = None
		self._in_pair = False
		self._prev_z: Decimal | None = None
		# Sign of the z that opened the current pair: +1 (A shorted / B longed)
		# or -1 (A longed / B shorted). Lets the exit cover the correct side.
		self._entry_z_sign: int = 0

	# ------------------------------------------------------------------ helpers

	def _fit_beta(self, win_A: pd.DataFrame, win_B: pd.DataFrame) -> float:
		"""log-OLS hedge ratio: slope of log(close_A) on log(close_B) (D-04/D-05).

		Fit over the first ``beta_warmup`` completed bars of the handed windows
		(look-ahead-safe — the windows already contain completed bars only). The
		returned slope is a statsmodels float; it enters the Decimal domain ONLY
		via ``to_money`` downstream (Pitfall 4 — never ``Decimal(float)``).
		"""
		log_A = np.log(win_A["close"].to_numpy(dtype=float)[: self.beta_warmup])
		log_B = np.log(win_B["close"].to_numpy(dtype=float)[: self.beta_warmup])
		X = sm.add_constant(log_B)
		return float(sm.OLS(log_A, X).fit().params[1])

	def _coint_pvalue(self, win_A: pd.DataFrame, win_B: pd.DataFrame) -> float:
		"""Engle-Granger cointegration p-value over the warmup window (D-10).

		Computed on the SAME warmup window as β and LOGGED as a diagnostic only —
		it NEVER gates the run (ETH/BTC does not pass strict cointegration; the
		rolling z-score delivers the round trips).
		"""
		log_A = np.log(win_A["close"].to_numpy(dtype=float)[: self.beta_warmup])
		log_B = np.log(win_B["close"].to_numpy(dtype=float)[: self.beta_warmup])
		_, p_value, _ = coint(log_A, log_B)
		return float(p_value)

	def _zscore(self, spread: pd.Series, lookback: int) -> pd.Series:
		"""Rolling z-score of ``spread`` over ``lookback`` (pandas ddof=1, D-06)."""
		rolling_mean = spread.rolling(lookback).mean()
		rolling_std = spread.rolling(lookback).std()
		return (spread - rolling_mean) / rolling_std

	def _crosses_into(
		self, prev_z: Decimal, curr_z: Decimal, threshold: Decimal
	) -> bool:
		"""True only on the bar ``|z|`` crosses INTO the band (D-13 entry)."""
		return abs(prev_z) <= threshold and abs(curr_z) > threshold

	def _crosses_inside(
		self, prev_z: Decimal, curr_z: Decimal, threshold: Decimal
	) -> bool:
		"""True only on the bar ``|z|`` crosses back INSIDE the band (D-13 exit)."""
		return abs(prev_z) >= threshold and abs(curr_z) < threshold

	# ------------------------------------------------------------------ alpha

	def evaluate_pair(
		self, win_A: pd.DataFrame, win_B: pd.DataFrame
	) -> list[SignalIntent] | None:
		"""Two-leg alpha (D-06/D-08/D-12/D-13): both legs together, or None.

		Fits + freezes β on the first tick that has enough bars, logs the coint
		diagnostic, then each tick computes the rolling z-score and fires on a
		crossing into/out of the band against the internal in-pair flag.
		"""
		required = self.beta_warmup + self.z_lookback
		if len(win_A) < required or len(win_B) < required:
			# Not enough completed bars to fit β AND seed the z-score lookback.
			return None

		# β fit-once-then-freeze (D-05). Cache on the instance; never re-fit.
		if self._beta is None:
			self._beta = self._fit_beta(win_A, win_B)
			p_value = self._coint_pvalue(win_A, win_B)
			logger.info(
				"pair beta fit (frozen)",
				beta=self._beta,
				coint_pvalue=p_value,  # D-10: diagnostic only, never gates
				beta_warmup=self.beta_warmup,
				tickers=self.tickers,
			)

		beta = self._beta
		log_A = np.log(win_A["close"].astype(float))
		log_B = np.log(win_B["close"].astype(float))
		# spread = log(A) − β·log(B) (D-04/D-06). β is a float here (z is a pure
		# float diagnostic series); it enters the Decimal money domain ONLY at the
		# β-weighted quantity below, via to_money (Pitfall 4).
		spread = log_A - beta * log_B
		z_series = self._zscore(spread, self.z_lookback)
		curr_raw = z_series.iloc[-1]
		if pd.isna(curr_raw):
			return None
		curr_z = to_money(float(curr_raw))  # Decimal via the string path
		prev_z = self._prev_z
		self._prev_z = curr_z

		ticker_A, ticker_B = self.tickers[0], self.tickers[1]

		# Need a previous z to detect a crossing (D-13). First evaluable tick just
		# seeds _prev_z (handled above) and fires nothing.
		if prev_z is None:
			return None

		# EXIT (in-pair, |z| crosses back inside the band, D-13). Quantity-FREE —
		# the resolver sizes the close from exchange truth and clamps to flat
		# (RESEARCH Pitfall 1; an explicit quantity would open a NEW position).
		if self._in_pair:
			if self._crosses_inside(prev_z, curr_z, self.exit_z):
				sign = self._entry_z_sign
				self._in_pair = False
				self._entry_z_sign = 0
				# Exit is the INVERSE of the entry side each leg holds. A z>0 entry
				# shorted A / longed B → cover = BUY A, SELL B. A z<0 entry longed
				# A / shorted B → cover = SELL A, BUY B. Quantity-free: the
				# resolver sizes from exchange truth and clamps to flat.
				if sign > 0:
					return [self.buy(ticker_A), self.sell(ticker_B)]
				return [self.sell(ticker_A), self.buy(ticker_B)]
			return None

		# ENTRY (flat, |z| crosses INTO the band, D-13). Short the RICH leg, long
		# the CHEAP leg, β-weighted (D-06/D-08). z>0 ⇒ spread high ⇒ A (ETH) rich
		# vs β·B ⇒ short A / long B; z<0 ⇒ the mirror.
		if self._crosses_into(prev_z, curr_z, self.entry_z):
			n = self.entry_units
			qty_B = self.entry_units * to_money(beta)  # β·N, Decimal end-to-end
			self._in_pair = True
			if curr_z > 0:
				# A rich → short A, long B.
				self._entry_z_sign = 1
				return [
					self._entry(ticker_A, Side.SELL, n),
					self._entry(ticker_B, Side.BUY, qty_B),
				]
			# A cheap → long A, short B.
			self._entry_z_sign = -1
			return [
				self._entry(ticker_A, Side.BUY, n),
				self._entry(ticker_B, Side.SELL, qty_B),
			]

		return None

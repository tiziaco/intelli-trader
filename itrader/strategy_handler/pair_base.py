"""PairStrategy — the two-leg pure-alpha base for market-neutral pair trading.

Phase 6 (Pair-Trading Flagship), PAIR-01. ``PairStrategy`` is the ONLY net-new
engine surface this phase adds beside the dispatch type-branch in
``StrategiesHandler`` — a dedicated ``Strategy`` subclass declared with a PAIR of
tickers, dispatched ONCE per tick through ``evaluate_pair`` returning BOTH legs
together (D-01).

It is a thin, reuse-first extension of ``Strategy`` (``base.py``): the inherited
``_apply_params``/``validate``/``_run_init``/``evaluate`` machinery is reused
verbatim, NOT re-implemented. The only additions are:

- the alpha-knob class attrs (``entry_z``/``exit_z``/``z_lookback``/
  ``beta_warmup``/``leverage``/``use_log_prices``);
- ``direction`` pinned to ``LONG_SHORT`` (D-14) and ``use_log_prices = True``
  (D-04 RESOLVED — the spread is fit on log prices);
- the abstract ``evaluate_pair(win_A, win_B)`` two-leg seam returning both legs;
- an explicit-quantity ENTRY constructor (``_entry``) threading a β-weighted
  ``quantity`` (RESEARCH Pattern 2 — the inherited ``buy()``/``sell()``/
  ``_intent()`` sugar always builds ``quantity=None``, so it CANNOT express the
  per-leg β-weighting an entry needs; exits reuse the inherited sugar).

Pure-alpha contract (D-12, mirrors ``Strategy``): NO queue, NO portfolio access,
NO time/price stamping. The β/z statsmodels math lives in the CONCRETE reference
strategy (Plan 06-02), never here — this base is shape only.

⚠ max_window pitfall (RESEARCH Pitfall 3 / ``base.py`` auto-warmup): a handle-FREE
pair strategy gets ``warmup == 0`` and ``max_window == max(0, class value)`` from
``_run_init``. A 0-width ``max_window`` yields an EMPTY feed window forever
(``frame.iloc[pos:pos]``). The pair base therefore HAND-SETS ``max_window`` and
``validate()`` asserts it is ≥ ``beta_warmup + z_lookback`` so the fit/z window is
always usable; the warmup short-circuit in dispatch gates on
``beta_warmup + z_lookback`` (NOT the handle-derived ``warmup``, which is 0).

Indentation: TABS (match ``base.py``; never normalize — a mixed-indent diff breaks
a tab file).
"""

from abc import abstractmethod
from decimal import Decimal

import pandas as pd

from itrader.core.enums import OrderType, Side, TradingDirection
from itrader.core.money import to_money
from itrader.core.sizing import SignalIntent
from itrader.strategy_handler.base import Strategy


class PairStrategy(Strategy):
	"""Two-leg pure-alpha base for long/short pair trading (D-01/D-14).

	A concrete pair strategy declares its PAIR of tickers (exactly two), its
	sizing policy and the alpha knobs below, then implements
	``evaluate_pair(win_A, win_B)`` returning BOTH legs' intents together (or
	``None`` when there is nothing to do). The handler routes a ``PairStrategy``
	through ``StrategiesHandler._dispatch_pair`` (a typed ``isinstance`` branch),
	never the per-ticker ``generate_signal`` path.

	Responsibilities:

	- DECLARE the pair contract (``tickers`` of length 2) and the spread/z knobs.
	- pin ``direction = LONG_SHORT`` (D-14) and ``use_log_prices = True`` (D-04).
	- expose ``evaluate_pair`` as the two-leg alpha seam (abstract).
	- provide ``_entry`` — the explicit-β-weighted-quantity ENTRY constructor the
	  inherited sugar cannot express; exits reuse inherited ``buy()``/``sell()``.

	It owns NO statsmodels/β math (that lives in the concrete reference strategy,
	Plan 06-02), NO queue, NO portfolio knowledge.
	"""

	# D-14: a pair is long one leg and short the other — pin LONG_SHORT so the
	# registration gate (allow_short_selling + enable_margin) and the LONG_SHORT
	# admission path are exercised. Overrides the Strategy LONG_ONLY default.
	direction: TradingDirection = TradingDirection.LONG_SHORT

	# D-04 RESOLVED — the spread is fit on LOG prices (β from log-OLS, z from the
	# log-spread). A subclass may flip this, but the reference fits on log prices.
	use_log_prices: bool = True

	# Alpha knobs — overridable class attrs introspected by get_type_hints
	# (every knob is ANNOTATED so _apply_params sees it). Pitfall 4: every Decimal
	# knob enters via the string path — NEVER Decimal(float).
	entry_z: Decimal = Decimal("2")      # |z| threshold to OPEN the spread
	exit_z: Decimal = Decimal("0.5")     # |z| threshold to CLOSE the spread
	z_lookback: int = 0                  # rolling window for the z-score (subclass pins)
	beta_warmup: int = 0                 # OLS fit window for β (subclass pins)
	# D-09: the requested margin backing carried onto each leg's SignalEvent.
	# Default Decimal("1") (unlevered) keeps the leg inert beside the LONG_SHORT
	# direction; a subclass dials it up for levered pairs.
	leverage: Decimal = Decimal("1")
	# ⚠ Pitfall 3: HAND-SET so the handle-free auto-warmup does not collapse the
	# feed window to 0-width. validate() asserts it is ≥ beta_warmup + z_lookback;
	# a subclass pins a concrete value (≥ the required warmup).
	max_window: int = 0

	def validate(self) -> None:
		"""Cross-field pair invariants (D-09 hook; overridable).

		Asserts the pair contract beyond the base's ``list[str]`` ticker check
		(IN-02 already rejects a non-list[str] ``tickers``):

		- exactly two tickers (a pair has two legs);
		- ``exit_z < entry_z`` (you close inside the band you opened on);
		- ``max_window >= beta_warmup + z_lookback`` (Pitfall 3 — a too-narrow
		  fetch width yields a window that can never satisfy the fit/z warmup).

		A subclass overriding ``validate`` SHOULD call ``super().validate()`` to
		keep these invariants.
		"""
		if len(self.tickers) != 2:
			raise ValueError(
				f"PairStrategy requires exactly two tickers (the pair): "
				f"got {self.tickers!r}"
			)
		if not (self.exit_z < self.entry_z):
			raise ValueError(
				f"PairStrategy requires exit_z < entry_z: "
				f"got exit_z={self.exit_z!r}, entry_z={self.entry_z!r}"
			)
		required = self.beta_warmup + self.z_lookback
		if self.max_window < required:
			raise ValueError(
				f"PairStrategy.max_window must be >= beta_warmup + z_lookback "
				f"({self.beta_warmup} + {self.z_lookback} = {required}): "
				f"got max_window={self.max_window} (Pitfall 3 — a too-narrow "
				f"fetch width yields an unusable feed window)"
			)

	def generate_signal(self, ticker: str) -> SignalIntent | None:
		"""Single-leg seam — NEVER called for a pair strategy.

		The handler routes a ``PairStrategy`` through ``_dispatch_pair`` →
		``evaluate_pair`` (a typed ``isinstance`` branch), so the per-ticker
		``generate_signal`` path is structurally bypassed. This override exists
		only to satisfy the ``Strategy`` ABC; reaching it means the dispatch
		branch is missing — fail loudly rather than silently mis-route.
		"""
		raise NotImplementedError(
			"PairStrategy is dispatched via evaluate_pair, not generate_signal; "
			"reaching generate_signal means the StrategiesHandler pair branch is "
			"not wired."
		)

	@abstractmethod
	def evaluate_pair(
		self, win_A: pd.DataFrame, win_B: pd.DataFrame
	) -> list[SignalIntent] | None:
		"""Two-leg alpha seam (A4 — the pinned name) returning BOTH legs together.

		Given the completed-bar windows for leg A (``tickers[0]``) and leg B
		(``tickers[1]``), compute the spread/z and return a list of
		``SignalIntent`` covering BOTH legs (one per leg on an entry/exit), or
		``None`` when there is nothing to do this tick. The handler fans EACH
		returned intent out per subscribed portfolio.

		Pure function of the two windows: no queue, no portfolio access, no
		stamping. ENTRY intents carry an explicit β-weighted ``quantity`` (build
		them via ``self._entry``); EXIT intents carry NO quantity (reuse the
		inherited ``buy()``/``sell()`` sugar — ``quantity=None``,
		``exit_fraction=Decimal("1")``).
		"""
		raise NotImplementedError("Should implement evaluate_pair()")

	def _entry(
		self, ticker: str, action: Side, quantity: float | Decimal
	) -> SignalIntent:
		"""Build a MARKET ENTRY intent with an explicit β-weighted quantity.

		The inherited ``buy()``/``sell()``/``_intent()`` sugar always builds
		``SignalIntent(quantity=None, exit_fraction=Decimal("1"))`` — it CANNOT
		thread the per-leg β-weighted quantity a pair entry needs (RESEARCH
		Pattern 2). This constructor sets ``quantity`` directly so the two legs
		open at N vs β·N.

		``quantity`` enters the Decimal domain via ``to_money`` (the string path,
		``Decimal(str(x))``) — NEVER ``Decimal(float)`` (Pitfall 4: the binary-repr
		artifact breaks the determinism double-run). ``order_type`` is ``MARKET``
		(the leg fills at the decision-bar close, stamped by the handler) and
		``exit_fraction`` is the full-exit default — irrelevant for an entry, kept
		at ``Decimal("1")`` so the field is inert.
		"""
		return SignalIntent(
			ticker=ticker,
			action=action,
			order_type=OrderType.MARKET,
			quantity=to_money(quantity),
			exit_fraction=Decimal("1"),
			leverage=self.leverage,
		)

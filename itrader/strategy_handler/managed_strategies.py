"""
Roster state primitive — the single owner of the managed-strategy roster (DECOMP-01).

`ManagedStrategies` is the phase-10.1 analog of `BracketBook` (D-05): a thin
owner-class around the state that the DATA plane (`calculate_signals` iterates
the roster) and the CONTROL plane (every STRATEGY_COMMAND verb mutates it)
both reach for. Giving it one owner is what lets 10.1-03 lift the control plane
out without the two planes reaching into each other's attributes.

The four method bodies here are VERBATIM code motion out of
`strategies_handler.py` — docstrings and their decision tags moved with them.
The only edits were de-underscoring where a handler-private becomes this
class's public surface (`_direction_admissible` -> `direction_admissible`,
`_recompute_min_timeframe` -> `recompute_min_timeframe`,
`get_strategies_universe` -> `get_universe`).

State owned here (the handler now holds NONE of it, reaching it through
delegating accessors):
  - `strategies`          the roster list  (assigned ONCE, mutated in place)
  - `_pending_removals`   the D-11 pending-removal name set (likewise)
  - `min_timeframe`       the IN-06 derived minimum
  - `_allow_short_selling` / `_enable_margin`  the SHORT-01/D-07 gate flags

⚠ SAME-OBJECT INVARIANT. `strategies` and `_pending_removals` are assigned
exactly once, in `__init__`, and are NEVER rebound — every mutation is in
place. The handler's accessors hand back THESE objects, never a copy: 21 test
sites mutate the handler's roster with `.append` / `.extend`, and a
copy-returning accessor anywhere on the seam would silently turn every one of
them into a no-op.

⚠ SINGLE SOURCE OF TRUTH for the two flags. `_allow_short_selling` and
`_enable_margin` are a CAPABILITY gate, not style state — `direction_admissible`
is the shared predicate behind BOTH `add` and `reconfigure(direction=...)` so
the two cannot drift and admit a short-enabling reconfigure that `add` would
reject (the T-10-55 closure). They therefore live HERE only; the handler
exposes read/write properties that forward, rather than keeping a shadow copy
that could diverge from the copy the gate actually reads.

Negative invariants — this class is a PURE state owner: no `global_queue` / no
`EventBus`, no handler back-reference, and none of the live deps
(`registry_store`, `strategy_catalog`, `portfolio_read_model`) ever reach it.
Persistence, event emission, and flat-detection all stay on the handler.

The logger IS injected, deviating from the logger-free `BracketBook` analog:
`add_strategy` ends with an info log, and leaving that log behind on a handler
delegator would silently drop it in 10.1-03 when `_add_strategy_verb`'s call
target is repointed from `self.add_strategy(...)` to `managed.add_strategy(...)`
— a behaviour change disguised as code motion. Keeping the log inside the moved
body makes the motion genuinely verbatim.

`update_config` deliberately does NOT live here: it performs no roster
mutation and raises `ConfigurationError` (the config-surface contract) rather
than `ValueError` (the registration-gate contract), so it stays on the handler.

TABS file (matching `strategy_handler/` source).
"""

from datetime import timedelta
from typing import Any

from itrader.core.sizing import TradingDirection
from itrader.strategy_handler.base import Strategy


class ManagedStrategies:
	"""Single owner of the strategy roster and its registration rules (DECOMP-01).

	Constructible and testable in isolation — no handler, no queue, no live
	deps. See the module docstring for the same-object invariant and the
	single-source-of-truth rule on the two SHORT-01/D-07 flags.
	"""

	def __init__(
		self,
		allow_short_selling: bool,
		enable_margin: bool,
		logger: Any,
	) -> None:
		"""
		Parameters
		----------
		allow_short_selling: `bool`
			SHORT-01/D-07 registration flag. Together with ``enable_margin`` it
			gates ``add_strategy``: a non-``LONG_ONLY`` strategy is admitted ONLY
			when BOTH flags are on.
		enable_margin: `bool`
			SHORT-01/D-07 registration flag, coupled with ``allow_short_selling``
			because it turns on the lock-and-settle model (Phase 2 D-09) — the
			only model that can represent a short.
		logger: `Any`
			The bound logger the moved ``add_strategy`` body logs through. See
			the module docstring for why the log lives inside the moved body.
		"""
		self.logger = logger
		# D-11 pending-removal state. A `remove` force-flats FIRST and drops the object
		# only once the flat is OBSERVED on a later FILL cycle, so it is a PENDING state
		# (mirroring the pending-bracket / reconnect-resume precedents), not an inline
		# mutation. A name lives here from the `remove` command until `on_fill` sees its
		# positions flat; while pending, the derived universe excludes its tickers so
		# the poll's REMOVE branch drives the P7 force-close, but its registry ROW is KEPT
		# until flat (crash-safety: restart rehydrates and resumes managing the positions).
		self._pending_removals: set[str] = set()
		# SHORT-01/D-07 two-flag registration gate — read, never mutated here.
		self._allow_short_selling: bool = allow_short_selling
		self._enable_margin: bool = enable_margin
		# IN-06: initialize to None rather than a 100-week magic sentinel. A
		# downstream consumer reading min_timeframe before any strategy is
		# registered gets a clear "no strategies" signal (None) instead of
		# meaningless garbage. add_strategy computes the real min defensively.
		self.min_timeframe: timedelta | None = None
		self.strategies: list[Strategy] = []

	def by_name(self) -> dict[str, Strategy]:
		"""Return a fresh ``{strategy.name: strategy}`` view of the current roster.

		The identical comprehension appeared at three handler sites (``on_fill``,
		``on_strategy_command``, ``update_config``); this is the shared factoring.
		Fresh per call — the caller may mutate the mapping without touching the
		roster.
		"""
		return {strategy.name: strategy for strategy in self.strategies}

	def remove(self, strategy: Strategy) -> None:
		"""Drop ``strategy`` from the roster IN PLACE, guarded against absence.

		The list is mutated, never rebound (see the module docstring's
		same-object invariant). Removing an absent strategy is a no-op rather
		than a ``ValueError``.
		"""
		if strategy in self.strategies:
			self.strategies.remove(strategy)

	def mark_pending(self, name: str) -> None:
		"""Enter ``name`` into the D-11 pending-removal set (in place)."""
		self._pending_removals.add(name)

	def discard_pending(self, name: str) -> None:
		"""Clear ``name`` from the pending-removal set; idempotent (in place)."""
		self._pending_removals.discard(name)

	def is_pending(self, name: str) -> bool:
		"""True when ``name`` is awaiting a D-11 removal completion."""
		return name in self._pending_removals

	def get_universe(self) -> list[str]:
		"""
		Return a list with all the coins traded from the differents strategies.

		Returns
		-------
		traded_tickers: `list`
			List of strings with the traded symbols
		"""
		traded_tickers: list[str] = []
		for strategy in self.strategies:
			# D-11: a pending-removal strategy is EXCLUDED from the derived membership so
			# the poll's REMOVE branch force-closes its now-unmembered symbols — the trigger
			# that drives the P7 force-close machinery. The instance STAYS in
			# self.strategies (its row is kept until flat for crash-safety); it simply stops
			# CONTRIBUTING to membership. A symbol shared with a non-pending strategy stays a
			# member via that other strategy (correct: it is still needed) — the force-close
			# is symbol-scoped, so a shared symbol's position is not force-closed by removing
			# only one of its strategies (the accepted P10-scope limitation).
			if strategy.name in self._pending_removals:
				continue
			# IN-01: the declared config contract is `tickers: list[str]`, so
			# `tickers[0]` is always a `str` — the legacy pairs-trading branch
			# (`isinstance(tickers[0], tuple)`) was dead on every supported path
			# and has been removed. A typed pairs API will replace it if/when
			# pairs trading is reintroduced, rather than runtime isinstance
			# sniffing on the first element.
			traded_tickers += strategy.tickers

		return list(set(traded_tickers))

	def recompute_min_timeframe(self) -> None:
		"""Re-derive ``min_timeframe`` from the current roster after a drop (IN-01/IN-06).

		``min_timeframe`` is derived only in ``add_strategy`` and never recomputed on
		removal, so dropping the strategy at the minimum would leave it stale. An EMPTY
		roster returns to the ``None`` seed — the legal "no strategies" state (IN-06),
		mirroring the None-seed handling in ``add_strategy``.
		"""
		if not self.strategies:
			self.min_timeframe = None
			return
		self.min_timeframe = min(strategy.timeframe for strategy in self.strategies)

	def direction_admissible(self, direction: TradingDirection) -> bool:
		"""SHORT-01/D-07 two-flag registration predicate — the SHARED gate (audit 10-08 F1).

		A non-``LONG_ONLY`` direction is admissible ONLY when BOTH ``allow_short_selling``
		AND ``enable_margin`` are on. Factored out of ``add_strategy`` so the IDENTICAL
		predicate gates ``add`` AND ``reconfigure(direction=...)`` — the two cannot drift.

		Deliberately NOT pushed into ``Strategy.validate()``: the two flags are HANDLER
		policy state that a pure-alpha ``Strategy`` (D-12) must never see, and ``validate()``
		has no access to them. That is exactly why the plan's original "``validate()``
		re-runs the SHORT-01 gate" premise was false — ``validate()`` is a window-shape hook
		and never checks ``direction`` — so the trial construction alone CANNOT admit-gate a
		short-enabling reconfigure. This predicate, called on the reconfigure apply path
		against the trial's resolved direction, is what actually closes T-10-55.
		"""
		return direction is TradingDirection.LONG_ONLY or (
			self._allow_short_selling and self._enable_margin)

	def add_strategy(self, strategy: Strategy) -> None:
		"""
		Add a new strategy in the list of strategies to trade.
		At the same time, calculate the minimum timeframe among
		the different strategies to be traded.
		This timeframe will be used from the price handler to
		download historical prices

		Parameters
		----------
		strategy: `Strategy object`
			Strategy to be executed by the trading system

		Raises
		------
		ValueError
			If the strategy declares a direction other than
			``TradingDirection.LONG_ONLY`` while NOT both shorts-enabling flags
			are on (SHORT-01/D-07). A non-``LONG_ONLY`` strategy (LONG_SHORT or
			SHORT_ONLY) is admitted ONLY when ``allow_short_selling`` AND
			``enable_margin`` are both set; otherwise registration rejects the
			capability loudly. ``enable_margin`` is required (not just
			``allow_short_selling``) because it turns on the lock-and-settle
			model (Phase 2 D-09) — the only model that can represent a short
			(spot debit-notional cannot). With the default ``max_leverage == 1``
			this gives fully-collateralized shorts (no leverage); levered shorts
			are a separate opt-in dial. Both flags default off → the golden
			``LONG_ONLY`` path (SMA_MACD) is unaffected, oracle byte-exact.
		"""
		# SHORT-01/D-07 two-flag registration gate, via the SHARED predicate so `add` and
		# `reconfigure(direction=...)` cannot drift (audit 10-08 F1): a non-LONG_ONLY
		# direction is admissible ONLY when BOTH allow_short_selling AND enable_margin are on.
		# enable_margin is coupled in because it enables the lock-and-settle model that can
		# actually represent a short. Both default off → the golden LONG_ONLY path is
		# unaffected (oracle byte-exact).
		if not self.direction_admissible(strategy.direction):
			raise ValueError(
				"Non-LONG_ONLY strategies (LONG_SHORT / SHORT_ONLY) require "
				"BOTH allow_short_selling AND enable_margin to be enabled "
				"(SHORT-01/D-07) — enable_margin turns on the lock-and-settle "
				"model that can represent a short. Both flags default off."
			)

		# D-02 duplicate-name loud reject. `strategy_name` is the DURABLE
		# per-instance identity: the registry keys on it, STRATEGY_COMMAND
		# addresses by it, and rehydrate reconstructs by it. (The ephemeral
		# `strategy_id` UUIDv7 at base.py:192 is minted per construction and
		# is NOT restart-stable, so keying durability on it would corrupt
		# rehydrate.) A silent second registration under the same name would
		# shadow the first instance and overwrite its persisted state, so a
		# collision rejects loudly instead — including the rehydrate cases
		# (rehydrating twice, or rehydrating a name already hand-added).
		if any(existing.name == strategy.name for existing in self.strategies):
			raise ValueError(
				f"A strategy named {strategy.name!r} is already registered "
				"(D-02) — strategy_name is the durable per-instance identity, "
				"so a duplicate would silently shadow the existing instance "
				"and overwrite its persisted state. Rename one of them."
			)

		# Add the strategy in the strategies list
		self.strategies.append(strategy)

		# Find the minimum timeframe (IN-06: defensive against the None seed —
		# the first registered strategy establishes the baseline).
		if self.min_timeframe is None:
			self.min_timeframe = strategy.timeframe
		else:
			# IN-01: min_timeframe is guaranteed non-None here — the None seed
			# (IN-06) is handled by the branch above. This `else` arm is the
			# load-bearing non-None branch; moving min(...) out from under the
			# `is None` guard would feed min() a None and raise TypeError at
			# wiring time. Keep the guard and this arm coupled.
			self.min_timeframe = min(self.min_timeframe, strategy.timeframe)

		self.logger.info(f'New strategy added: {strategy.name}')

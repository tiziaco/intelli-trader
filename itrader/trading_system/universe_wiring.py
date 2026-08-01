"""Shared universe-wiring unit — the oracle-critical injection ordering.

``wire_universe(engine)`` is the ONE greppable home for the load-bearing cross-domain
universe-injection ordering. Both ``BacktestRunner._initialise_backtest_session`` and
the live ``SessionInitializer`` reuse this single unit so the
derive -> assert -> Universe -> inject(exchange/order/portfolio/strategies) -> feed.bind
ordering lives once and never desyncs between the two run modes.

It is a FREE FUNCTION homed here rather than in ``universe/``: the pure
``universe/membership.py`` + ``instruments.py`` derivations carry no queue, no state and
no feed/store import, while this helper does ``feed.bind`` + handler injection.
Orchestration is ``trading_system``'s job; ``universe/`` is kept clean of it.

ORACLE-SENSITIVE: move this unit ONLY as ONE intact block — never refactor its
internals. The SMA_MACD oracle must stay byte-exact ``134 / 46189.87730727451``.
"""

from itrader.core.exceptions import ConfigurationError
from itrader.execution_handler.execution_handler import COMPUTE_VENUE, DEFAULT_ACCOUNT_ID
from itrader.execution_handler.exchanges.simulated import SimulatedExchange
from itrader.trading_system.graph import Engine
from itrader.universe import Universe, derive_instruments, derive_membership


def wire_universe(engine: Engine) -> Universe:
	"""Derive membership + instruments, build the ``Universe``, inject it into the
	exchange/order/portfolio/strategies domains, and bind the feed factory.

	ORDER-SENSITIVE: membership derive -> desync assert -> Universe ->
	inject(exchange -> order -> portfolio -> strategies) -> feed.bind. Returns the built
	``Universe`` (also held on ``engine.universe``). Callers keep their own pre/post
	steps (backtest: ping-grid union + per-strategy precompute).
	"""
	# The union of strategy tickers and the screener set — used by the feed's factory
	# only for the missing-ticker warning loop.
	membership = derive_membership(
		engine.strategies_handler.strategies,
		# screeners_handler is a deferred subsystem (mypy ignore_errors) — untyped here.
		engine.screeners_handler.get_screeners_universe())  # type: ignore[no-untyped-call]
	# ``price_data`` is empty on the golden path — BTCUSD is DECLARED, so scale
	# inference is never consulted and the oracle stays byte-exact.
	instruments = derive_instruments(
		engine.strategies_handler.strategies,
		engine.screeners_handler.get_screeners_universe(),  # type: ignore[no-untyped-call]
		price_data={})
	# derive_instruments calls derive_membership internally over the same inputs, so its
	# key set must match the membership derived above. The two agree within one
	# interpreter today, but a future non-idempotent derive_membership would silently
	# desync universe.members from the instrument map — a member absent from
	# instrument_map raises KeyError on instrument(symbol) deep in a tick. Assert the
	# invariant at wiring so the desync fails loudly here instead.
	if set(membership) != set(instruments):
		raise ConfigurationError(
			reason=(
				"Universe membership desync: derive_membership and "
				"derive_instruments produced different symbol sets "
				f"(members={sorted(set(membership))}, "
				f"instruments={sorted(set(instruments))})"))
	universe = Universe(members=membership, instrument_map=instruments)
	engine.universe = universe
	# Inject the Universe into the simulated exchange so the admission gate resolves
	# min_order_size Instrument-first.
	#
	# Both lookups below are FAIL-LOUD by design. A soft `.get(...)` would resolve a
	# stale key to None and an isinstance guard that merely skips would leave
	# `set_universe` uncalled — min_order_size resolution silently changes and the money
	# arithmetic moves underneath a green suite, with no exception near the defect. The
	# subscript raises KeyError instead, and the isinstance check (retained as a mypy
	# narrowing) raises rather than skipping: a wired engine whose paper venue is not a
	# SimulatedExchange is a wiring bug, not an optional configuration.
	paper_exchange = engine.execution_handler.exchanges[
		(COMPUTE_VENUE, DEFAULT_ACCOUNT_ID)]
	if not isinstance(paper_exchange, SimulatedExchange):
		raise ConfigurationError(
			reason=(
				"Universe injection target is not a SimulatedExchange: the "
				f"('{COMPUTE_VENUE}', '{DEFAULT_ACCOUNT_ID}') venue resolved to "
				f"{type(paper_exchange).__name__}. The paper venue backs the "
				"simulated fill engine; a different object here means the "
				"engine was wired wrong, and skipping the injection would "
				"silently change min_order_size resolution."))
	paper_exchange.set_universe(universe)
	# Mirror the injection into the ORDER domain so the admission leverage cap can read
	# Instrument.max_leverage. Every mirror below depends on the Universe built above,
	# which is why they run AFTER it and never before their handler's construction.
	engine.order_handler.set_universe(universe)
	# The PORTFOLIO domain reads Instrument.maintenance_margin_rate for its
	# maintenance_margin/margin_ratio accessors. Query-only and oracle-dark on the
	# golden path — the accessors are never read during the SMA_MACD run.
	engine.portfolio_handler.set_universe(universe)
	# The STRATEGY injection is inert in backtest by construction: Universe.__init__
	# marks every member Readiness.READY and backtest membership derives FROM strategy
	# tickers, so the readiness gate in StrategiesHandler.on_bar never skips. Placed
	# after the portfolio injection and before feed.bind so the ordering is stable and
	# shared with the live SessionInitializer.
	engine.strategies_handler.set_universe(universe)
	# feed.bind receives universe.members — the SAME set-derived list derive_membership
	# produced.
	engine.feed.bind(engine.global_queue, universe.members)
	return universe

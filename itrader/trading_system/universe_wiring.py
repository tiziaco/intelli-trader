"""Shared universe-wiring unit — the oracle-critical injection ordering (RUN-04).

``wire_universe(engine)`` is the ONE greppable home for the load-bearing
cross-domain universe-injection ordering, extracted VERBATIM from the byte-exact
donor ``BacktestRunner._initialise_backtest_session`` (backtest_runner.py:64-113).
Both ``BacktestRunner`` (backtest, run-init) and the live ``SessionInitializer``
(plan 06-04, construction) reuse this single unit so the derive -> assert ->
Universe -> inject(exchange/order/portfolio/strategies) -> feed.bind ordering
lives once and never desyncs between the two run modes.

D-01: this unit is the FULL RUN-04 shape and it ADDS one call to the backtest
path — ``StrategiesHandler.set_universe(universe)`` — which the backtest did NOT
do before (backtest injected exchange/order/portfolio only). The addition is
INERT BY CONSTRUCTION, not fragile: ``Universe.__init__`` marks every member
``Readiness.READY`` at construction time and backtest membership is derived FROM
strategy tickers, so ``is_ready(ticker)`` is always True at the readiness gate
in ``StrategiesHandler.on_bar`` (the ``_universe.is_ready`` short-circuit in its
per-ticker loop) — the gate never skips. The byte-exact + determinism double-run
oracle gate on the extraction PLAN PROVES this.

WR-05: cited by SYMBOL, not by line number. The former positional citation had
already rotted onto an unrelated delegating property; a symbol reference survives
the next rename.

D-02: this is a FREE FUNCTION homed in ``trading_system/`` (NOT ``universe/``).
The pure ``universe/membership.py`` + ``instruments.py`` derivations are
documented "no class, no state, no queue, no feed/store import"; this helper does
``feed.bind`` + handler injection (composition wiring), which ``universe/`` is
kept clean of. It CALLS the pure derivations and orchestrates + injects —
orchestration is ``trading_system``'s job.

ORACLE-SENSITIVE: this is the milestone's HIGHEST oracle risk (analogous to the
v1.2 MOD-01 seam). Move this unit ONLY as ONE intact block — never refactor its
internals; the SMA_MACD oracle must stay byte-exact ``134 / 46189.87730727451``.

Indentation: TABS (``trading_system/`` package convention; verbatim transplant of
the TAB-indented donor block).
"""

from itrader.core.exceptions import ConfigurationError
from itrader.execution_handler.execution_handler import DEFAULT_ACCOUNT_ID
from itrader.execution_handler.exchanges.simulated import SimulatedExchange
from itrader.trading_system.compose import Engine
from itrader.universe import Universe, derive_instruments, derive_membership


def wire_universe(engine: Engine) -> Universe:
	"""Derive membership + instruments, build the ``Universe``, inject it into the
	exchange/order/portfolio/strategies domains, and bind the feed factory.

	The shared, oracle-critical universe-injection ordering (RUN-04, D-01/D-02).
	ORDER-SENSITIVE (Trap 4): membership derive -> WR-03 desync assert -> Universe
	-> inject(exchange -> order -> portfolio -> strategies) -> feed.bind. Returns
	the built ``Universe`` (also held on ``engine.universe``). Callers keep their
	own pre/post steps (backtest: ping-grid union + per-strategy precompute).
	"""
	# Membership derived at wiring time (M5-08, D-20): the union of strategy
	# tickers and the screener set — used by the feed's factory only for the
	# missing-ticker warning loop.
	membership = derive_membership(
		engine.strategies_handler.strategies,
		# D-screener deferred subsystem (ignore_errors override) — untyped to the gate.
		engine.screeners_handler.get_screeners_universe())  # type: ignore[no-untyped-call]
	# INST-02/INST-03 (D-03/D-06/D-08): build the symbol->Instrument map and
	# the Universe read-model at THIS Trap-4 point, then inject it into the
	# exchange for Instrument-first min_order_size resolution. price_data is
	# empty on the golden path — BTCUSD is DECLARED (D-10), so inference is
	# never consulted and the oracle stays byte-exact (Pitfall 1/Pitfall 4).
	instruments = derive_instruments(
		engine.strategies_handler.strategies,
		engine.screeners_handler.get_screeners_universe(),  # type: ignore[no-untyped-call]
		price_data={})
	# WR-03: derive_instruments calls derive_membership internally over the
	# same inputs, so its key set must match the membership derived above. The
	# two agree within one interpreter today, but a future non-idempotent
	# derive_membership would silently desync universe.members from the
	# instrument map (members holding a symbol absent from instrument_map ->
	# KeyError on instrument(symbol) mid-run). Assert the invariant at wiring
	# so a desync fails loudly here rather than deep in a tick.
	if set(membership) != set(instruments):
		raise ConfigurationError(
			reason=(
				"Universe membership desync: derive_membership and "
				"derive_instruments produced different symbol sets "
				f"(members={sorted(set(membership))}, "
				f"instruments={sorted(set(instruments))})"))
	universe = Universe(members=membership, instrument_map=instruments)
	engine.universe = universe
	# Inject the Universe into the simulated exchange so the admission gate
	# resolves min_order_size Instrument-first (BTCUSD undeclared -> venue
	# fallback 0.001 byte-identical, D-01a/Pitfall 2).
	# F-4/D-05 — this site WAS the phase's highest silent-corruption hazard, and
	# it is now FAIL-LOUD. It used to be a soft `.get(...)` plus an isinstance
	# guard that DECIDED whether the injection happened: a stale key returned
	# None, the guard skipped, `set_universe` never ran, min_order_size
	# resolution changed and the money arithmetic moved underneath a green
	# suite, with no exception raised anywhere near the defect.
	#
	# The subscript below raises KeyError on a stale key, matching the fail-loud
	# lookup idiom in `venues/registry.py`. The isinstance check is retained
	# ONLY as a mypy narrowing and it RAISES rather than skipping: a wired
	# engine whose paper venue is not a SimulatedExchange is a wiring bug, not
	# an optional configuration.
	paper_exchange = engine.execution_handler.exchanges[
		('paper', DEFAULT_ACCOUNT_ID)]
	if not isinstance(paper_exchange, SimulatedExchange):
		raise ConfigurationError(
			reason=(
				"Universe injection target is not a SimulatedExchange: the "
				f"('paper', '{DEFAULT_ACCOUNT_ID}') venue resolved to "
				f"{type(paper_exchange).__name__}. The paper venue backs the "
				"simulated fill engine; a different object here means the "
				"engine was wired wrong, and skipping the injection would "
				"silently change min_order_size resolution."))
	paper_exchange.set_universe(universe)
	# Plan 02-03 (Pitfall 1, BLOCKING): mirror the exchange injection into the
	# ORDER domain so the admission leverage cap (D-04) can read
	# Instrument.max_leverage. Same Trap-4 ordering — the Universe was just
	# built above, AFTER the order handler was constructed in compose_engine.
	engine.order_handler.set_universe(universe)
	# Plan 02-05 (D-13): mirror the injection into the PORTFOLIO domain so the
	# maintenance_margin/margin_ratio read-model can resolve each open
	# position's Instrument.maintenance_margin_rate. Same Trap-4 ordering — the
	# Universe was just built above, AFTER the portfolio handler was
	# constructed in compose_engine. Query-only and oracle-dark on the golden
	# path (the accessors are never read during the SMA_MACD run).
	engine.portfolio_handler.set_universe(universe)
	# D-01 (RUN-04): mirror the injection into the STRATEGY domain — the ONE
	# call new to the backtest path (backtest injected exchange/order/portfolio
	# only). INERT BY CONSTRUCTION: Universe.__init__ marks every member
	# Readiness.READY and backtest membership derives FROM strategy tickers, so
	# is_ready(ticker) is always True at the readiness gate in
	# StrategiesHandler.on_bar (its per-ticker _universe.is_ready short-circuit)
	# — the gate never skips (proven by the byte-exact oracle double-run).
	# Placed after the portfolio injection, before feed.bind, so the ordering is
	# stable and shared with the live SessionInitializer (plan 06-04).
	engine.strategies_handler.set_universe(universe)
	# feed.bind receives universe.members — the SAME set-derived list
	# derive_membership produced (Pitfall 4 — byte-identical to today).
	engine.feed.bind(engine.global_queue, universe.members)
	return universe

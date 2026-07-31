"""``SessionInitializer`` — the live session-wiring collaborator.

Owns the live session wiring, invoked from
``LiveTradingSystem._initialize_live_session``. It composes this phase's shared seams in
a load-bearing order:

1. ``wire_universe(engine)`` — the shared universe-injection unit, identical to the one
   the backtest runner uses.
2. ``register_strategy_warmup(engine.feed, strategies)``. Safe only AFTER
   ``wire_universe``'s ``feed.bind``: the ``LiveBarFeed`` rings are lazy at first
   ``_deliver``, ``cache_capacity`` reads the registered consumers at call time, and the
   warmup fetch depth is read in ``start()`` I/O after construction — do NOT re-invert
   this order.
3. the LIVE-ONLY subscription/membership mismatch guard — a fail-loud wiring-time
   invariant, not a trust boundary.
4. build + wire the first-class ``UniverseHandler``: ``set_selection_source``
   (strategy-derived), ``set_venue_metadata`` UNCONDITIONAL over the uniformly-resolved
   venue exchange (paper's ``SimulatedExchange`` satisfies
   ``validate_symbol``/``resolve_precision`` with permissive defaults, so there is zero
   OKX coupling), ``set_provider``, ``set_portfolio_read_model``,
   ``set_strategy_warmth`` and ``set_freeze_gate``.
5. compose the BUSINESS/live routes via ``LiveRouteRegistrar``.

Running this at construction time is what lets the routes be declared at construction
and the ``UniverseHandler`` be first-class at the root; the ``start()`` lifecycle then
does ONLY I/O (connect / subscribe / reconcile). Independently testable without standing
up a full facade.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any, cast

from itrader.price_handler.feed.cache_registration import register_strategy_warmup
from itrader.trading_system.route_registrar import LiveRouteRegistrar
from itrader.trading_system.universe_wiring import wire_universe
from itrader.universe.membership import StrategyDerivedSelectionModel
from itrader.universe.universe_handler import UniverseHandler, UniverseHandlerConfig

if TYPE_CHECKING:
    from itrader.execution_handler.exchanges.base import AbstractExchange
    from itrader.price_handler.feed.live_bar_feed import LiveBarFeed
    from itrader.trading_system.graph import Engine


class SessionInitializer:
    """Compose the live session wiring over the shared seams.

    Constructed with the built ``engine`` plus the facade-level collaborators the
    ``Engine`` holder does not carry: the ``UniverseHandlerConfig`` (the live-plane
    knobs), the uniformly-resolved venue exchange (for ``set_venue_metadata``), the
    data-plane provider (for ``set_provider`` + the subscription guard — ``None`` on
    paper), and the freeze-gate callable. ``initialize()`` performs the wiring in order
    and returns the built ``UniverseHandler`` for the facade + poll timer to reference.
    """

    def __init__(
        self,
        engine: "Engine",
        *,
        universe_config: "UniverseHandlerConfig",
        venue_exchange: "AbstractExchange | None",
        data_provider: Any = None,
        freeze_gate: Callable[[], bool],
        safety: Any,
        stream_recovery: Any,
        config_router: Any = None,
    ) -> None:
        self._engine = engine
        self._universe_config = universe_config
        self._venue_exchange = venue_exchange
        self._data_provider = data_provider
        self._freeze_gate = freeze_gate
        # The CONTROL-plane actuators threaded to the LiveRouteRegistrar so it can SET the
        # STREAM_STATE / CONNECTOR_FATAL routes to the engine-thread
        # SafetyController.pause_submission / StreamRecoveryHandler.on_reconnect /
        # SafetyController.halt.
        self._safety = safety
        self._stream_recovery = stream_recovery
        # The engine-thread ConfigRouter threaded to the LiveRouteRegistrar so it can SET
        # the CONFIG_UPDATE CONTROL route to ConfigRouter.apply. None when there is no SQL
        # spine, in which case that route stays the empty slot.
        self._config_router = config_router

    def initialize(self) -> "UniverseHandler":
        """Wire the live session in order; return the built ``UniverseHandler``.

        Order: ``wire_universe`` -> ``register_strategy_warmup`` -> subscription guard ->
        build + wire ``UniverseHandler`` -> ``LiveRouteRegistrar.install``.
        """
        engine = self._engine

        # (1) The shared universe unit: derive membership/instruments -> desync assert ->
        # Universe -> inject exchange/order/portfolio/strategies -> feed.bind. Held on
        # engine.universe.
        universe = wire_universe(engine)

        # (2) Warmup registration sizes the LIVE feed ring to the max strategy warmup. Safe
        # only AFTER wire_universe's feed.bind — do NOT re-invert.
        #
        # The depth is derived in BASE-bar units, scaled by each strategy's timeframe
        # multiple: the ring holds BASE bars while strategy.warmup counts STRATEGY-TIMEFRAME
        # bars, so a strategy coarser than the base cadence needs warmup * multiple base
        # bars. Without the scaling a 4h strategy on a 1h base, resampling a warmup-deep
        # ring, would never warm and never trade, silently. engine.feed is a LiveBarFeed on
        # this live-only path (the same cast as the UniverseHandler ctor below).
        register_strategy_warmup(
            engine.feed, engine.strategies_handler.strategies,
            base_timeframe=cast("LiveBarFeed", engine.feed).base_timeframe)

        # (3) Subscription/membership invariant — no guard needed TODAY. Subscription is
        # derived SOLELY from universe.members: start() runs
        # `for sym in universe.members: subscribe(sym)`, and the old single-symbol
        # start_stream() has no live call site, so the feed ring key and the strategy's
        # window() ticker cannot diverge by construction.
        # TODO: IF a future edit reintroduces an INDEPENDENT subscription source — an
        # operator-configured stream-symbol allowlist, a per-member/per-strategy timeframe,
        # or start_stream() re-wired into the live path — add a real wiring-time guard HERE
        # asserting that independent subscribed set is a subset of universe.members BEFORE
        # start() subscribes. Otherwise the mismatch surfaces as MissingPriceDataError only
        # at the FIRST window(), deep on the live path.

        # (4) Build the first-class UniverseHandler. engine.feed is a LiveBarFeed on the
        # live path, and the Engine holder types global_queue as EventBus while
        # UniverseHandler's bus contract is a raw queue.Queue — hence the two casts.
        universe_handler = UniverseHandler(
            bus=cast(Any, engine.global_queue),
            universe=universe,
            feed=cast("LiveBarFeed", engine.feed),
            config=self._universe_config,
        )
        # The poll selection source re-reads the live strategy universe on each select(), so
        # an operator ticker edit propagates on the next poll.
        universe_handler.set_selection_source(
            StrategyDerivedSelectionModel(engine.strategies_handler))
        # ONE unconditional set_venue_metadata wires BOTH validate_symbol and
        # resolve_precision off the resolved venue exchange — no OKX guard, since paper's
        # SimulatedExchange satisfies both with permissive defaults. The None-guard is purely
        # defensive: live and paper always resolve a non-None venue exchange.
        if self._venue_exchange is not None:
            universe_handler.set_venue_metadata(self._venue_exchange)
        # Data-plane provider the add/remove branch drives (guard None on paper).
        if self._data_provider is not None:
            universe_handler.set_provider(self._data_provider)
        # Open-position truth for the remove consumer + detach-on-flat.
        universe_handler.set_portfolio_read_model(engine.portfolio_handler)
        # on_bars_loaded re-checks is_warm before flipping a symbol READY, so a swallowed
        # partial warmup cannot make a half-warmed symbol tradeable.
        universe_handler.set_strategy_warmth(engine.strategies_handler)
        # While the engine is HALTED or submission-paused the poll freezes membership in
        # place.
        universe_handler.set_freeze_gate(self._freeze_gate)

        # (5) Compose the BUSINESS/live routes + the CONTROL-plane routes via the central
        # declarative registrar — list order = execution order, no runtime mutation. The
        # safety + stream_recovery collaborators resolve the STREAM_STATE / CONNECTOR_FATAL
        # routes.
        LiveRouteRegistrar(
            engine.strategies_handler,
            universe_handler,
            safety=self._safety,
            stream_recovery=self._stream_recovery,
            config_router=self._config_router,
        ).install(engine.event_handler)

        return universe_handler

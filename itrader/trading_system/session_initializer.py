"""``SessionInitializer`` — the live session-wiring collaborator (RUN-04 live / RUN-05 / RUN-06 / D-11 / D-12).

A distinct class (D-12) owning the live session wiring, extracted out of the
``LiveTradingSystem`` God object's ``_initialize_live_session``. It composes the
shared seams of this phase in the exact donor order:

1. ``wire_universe(engine)`` — the shared RUN-04 unit (06-01). The LIVE path now
   GAINS the WR-03 desync assert it previously lacked (a live-only safety upgrade,
   oracle-neutral since live is backtest-dark).
2. ``register_strategy_warmup(engine.feed, strategies)`` — the RUN-07/D-17 seam
   (06-03), replacing the old inline ``_LiveWarmupConsumer`` registration. Safe
   AFTER ``wire_universe``'s ``feed.bind`` (RESEARCH Landmine 3): the ``LiveBarFeed``
   rings are lazy at first ``_deliver``, ``cache_capacity`` reads the registered
   consumers at call time, and the warmup fetch depth is read in ``start()`` I/O
   after construction — do NOT re-invert this order.
3. the LIVE-ONLY subscription/membership mismatch guard (transplanted verbatim) —
   a fail-loud wiring-time invariant, not a trust boundary.
4. build + wire the first-class ``UniverseHandler`` (06-04) per the D-11 shape:
   ``set_selection_source`` (strategy-derived), ``set_venue_metadata`` UNCONDITIONAL
   over the uniformly-resolved venue exchange (paper's ``SimulatedExchange`` satisfies
   ``validate_symbol``/``resolve_precision`` with permissive defaults — zero OKX
   coupling), ``set_provider`` (guard-as-today), ``set_portfolio_read_model``,
   ``set_strategy_warmth``, and the interim ``set_freeze_gate`` callable (repointed to
   ``SafetyController`` in P7).
5. compose the BUSINESS/live routes via ``LiveRouteRegistrar`` (06-05 Task 1).

Running this at construction time is what makes RUN-05 (routes declared at
construction) + RUN-06 (``UniverseHandler`` first-class at the root) possible; the
``start()`` lifecycle then does ONLY I/O (connect / subscribe / reconcile — the last
being P7). Independently testable without standing up a full facade.

Behavior-preserving-interim: in 06-05 this is invoked via the existing
``_initialize_live_session`` delegation; the FLIP to construction-time invocation
(D-12) + the ``build_live_system`` wiring land in 06-06. Per D-04 this class does NOT
touch the facade's safety/reconcile/stream method bodies — the freeze-gate + the
WR-03/membership guards are wired, not reimplemented.

Indentation: 4 SPACES (matches ``live_trading_system.py`` — the facade that
delegates to this collaborator).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any, cast

from itrader.core.exceptions import ConfigurationError
from itrader.price_handler.feed.cache_registration import register_strategy_warmup
from itrader.trading_system.route_registrar import LiveRouteRegistrar
from itrader.trading_system.universe_wiring import wire_universe

if TYPE_CHECKING:
    from itrader.execution_handler.exchanges.base import AbstractExchange
    from itrader.price_handler.feed.live_bar_feed import LiveBarFeed
    from itrader.trading_system.compose import Engine
    from itrader.universe.universe_handler import (
        UniverseHandler,
        UniverseHandlerConfig,
    )


class SessionInitializer:
    """Compose the live session wiring over the shared phase seams (D-12).

    Constructed with the built ``engine`` (the compose ``Engine`` holder) plus the
    facade-level collaborators the ``Engine`` holder does not carry: the
    ``UniverseHandlerConfig`` (the RUN-06 live-plane knobs), the uniformly-resolved
    venue exchange (for ``set_venue_metadata``), the data-plane provider (for
    ``set_provider`` + the subscription guard — ``None`` on paper), and the interim
    freeze-gate callable. ``initialize()`` performs the wiring in donor order and
    returns the built ``UniverseHandler`` for the facade + poll timer to reference.
    """

    def __init__(
        self,
        engine: "Engine",
        *,
        universe_config: "UniverseHandlerConfig",
        venue_exchange: "AbstractExchange | None",
        data_provider: Any = None,
        freeze_gate: Callable[[], bool],
    ) -> None:
        self._engine = engine
        self._universe_config = universe_config
        self._venue_exchange = venue_exchange
        self._data_provider = data_provider
        self._freeze_gate = freeze_gate

    def initialize(self) -> "UniverseHandler":
        """Wire the live session in donor order; return the built ``UniverseHandler``.

        Order: ``wire_universe`` -> ``register_strategy_warmup`` -> subscription guard
        -> build + wire ``UniverseHandler`` (D-11) -> ``LiveRouteRegistrar.install``.
        The live-only concretions are lazy-imported here (backtest import path stays
        inert — the recurring ``tests/integration/test_okx_inertness.py`` gate).
        """
        # LAZY imports of the live-only concretions (mirrors the donor's lazy live
        # imports) so the backtest import path never pulls them onto its graph.
        from itrader.universe.membership import StrategyDerivedSelectionModel
        from itrader.universe.universe_handler import UniverseHandler

        engine = self._engine

        # (1) The shared RUN-04 unit (06-01): derive membership/instruments -> WR-03
        # desync assert (LIVE GAINS this) -> Universe -> inject exchange/order/
        # portfolio/strategies -> feed.bind. Held on engine.universe.
        universe = wire_universe(engine)

        # (2) RUN-07/D-17 warmup registration (06-03): sizes the LIVE feed ring to the
        # max strategy warmup so cache_capacity() derives to 100 (SMA_MACD). Safe
        # AFTER wire_universe's feed.bind (RESEARCH Landmine 3 — do NOT re-invert).
        register_strategy_warmup(
            engine.feed, engine.strategies_handler.strategies)

        # (3) WR-03 generalized (D-05): assert every symbol the engine will subscribe
        # is a universe member so the feed ring key and the strategy's window() ticker
        # can never diverge (else MissingPriceDataError only at the FIRST window(),
        # deep on the live path). start() subscribes exactly the members, so the check
        # is tautological today but fails loudly at wiring if a future edit subscribes
        # a symbol whose form diverges. Guarded on a non-empty membership (an empty
        # universe streams nothing) + a live data provider (paper streams nothing).
        if self._data_provider is not None and universe.members:
            members = universe.members
            subscribed = list(members)  # start() subscribes exactly the members
            mismatched = [s for s in subscribed if s not in members]
            if mismatched:
                raise ConfigurationError(
                    config_key="okx_stream_symbols",
                    config_value=repr(mismatched),
                    reason=(
                        f"subscribed symbol(s) {mismatched!r} are not members of "
                        f"the universe {members!r}; the feed ring key and the "
                        "strategy's window() ticker would mismatch "
                        "(MissingPriceDataError at first window()). Subscribe only "
                        "universe members."))

        # (4) Build the first-class UniverseHandler (RUN-06/D-11 ctor: bus, universe,
        # feed, config). engine.feed is a LiveBarFeed on the live path (the compose
        # Engine holder types it BacktestBarFeed — 06-06's live-feed-aware build
        # removes this interim cast).
        # bus: the compose Engine holder types global_queue as EventBus; the live
        # facade threads a raw queue.Queue (UniverseHandler's bus contract). Bridge
        # the interim typing (06-06's EventBus-native wiring supersedes this).
        universe_handler = UniverseHandler(
            bus=cast(Any, engine.global_queue),
            universe=universe,
            feed=cast("LiveBarFeed", engine.feed),
            config=self._universe_config,
        )
        # OP-SEAM: the poll selection source re-reads the live strategy universe each
        # select(), so an operator ticker edit propagates on the next poll.
        universe_handler.set_selection_source(
            StrategyDerivedSelectionModel(engine.strategies_handler))
        # RUN-06/D-11 venue metadata: ONE unconditional set_venue_metadata wires BOTH
        # validate_symbol (D-06) and resolve_precision (VENUE-04/D-09) off the resolved
        # venue exchange — NO OKX guard (paper's SimulatedExchange satisfies both with
        # permissive defaults). The None-guard is purely defensive: live/paper always
        # resolve a non-None venue exchange.
        if self._venue_exchange is not None:
            universe_handler.set_venue_metadata(self._venue_exchange)
        # Data-plane provider the add/remove branch drives (guard None on paper).
        if self._data_provider is not None:
            universe_handler.set_provider(self._data_provider)
        # Open-position truth for the remove consumer + detach-on-flat.
        universe_handler.set_portfolio_read_model(engine.portfolio_handler)
        # WR-02 strategy-warmth re-verify: on_bars_loaded re-checks is_warm before
        # flipping a symbol READY (a swallowed partial warmup can't make a half-warmed
        # symbol tradeable).
        universe_handler.set_strategy_warmth(engine.strategies_handler)
        # WR-05/D-07 freeze gate (interim callable): while the engine is HALTED or
        # submission-paused the poll freezes membership in place. Repointed to
        # SafetyController in P7 (mirrors the D-08 dispatch-gate pattern).
        universe_handler.set_freeze_gate(self._freeze_gate)

        # (5) Compose the BUSINESS/live routes via the central declarative registrar
        # (06-05 Task 1) — list order = execution order; no runtime mutation (LR-16).
        LiveRouteRegistrar(
            engine.strategies_handler, universe_handler).install(
                engine.event_handler)

        return universe_handler

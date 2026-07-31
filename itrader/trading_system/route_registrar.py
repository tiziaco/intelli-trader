"""``LiveRouteRegistrar`` — the ONE central declarative BUSINESS/live route table.

This is the LIVE analog of the single ``EventHandler.routes`` literal
(``full_event_handler.py``) where **list order IS execution order**. Instead of
spreading the correctness-load-bearing cross-handler ordering across the live init body,
it is declared ONCE here — greppable in one place, referencing the built handlers' and
``UniverseHandler``'s methods passed to the constructor, and installed into the single
``EventHandler`` ONCE via ``install(event_handler)``.

No subclass, no runtime mutation after install: the base ``EventHandler`` literal ships
the empty ``UNIVERSE_*`` / ``BARS_*`` routes and the base ``FILL`` list
``[portfolio.on_fill, order.on_fill]``; this registrar SETs the BUSINESS/live routes and
APPENDs to the base ``FILL`` consumers. The backtest ``EventHandler`` keeps the untouched
base literal, so the backtest per-tick path is inert by construction (proven by
``tests/integration/test_okx_inertness.py``).

The CONTROL-plane routes are where the indirection is: the connector's asyncio loop puts
a ``StreamStateEvent`` / ``ConnectorFatalEvent`` on the bus, and the private consumers
below actuate them on the engine thread —
``STREAM_STATE(down) -> SafetyController.pause_submission``,
``STREAM_STATE(up) -> StreamRecoveryHandler.on_reconnect``,
``CONNECTOR_FATAL -> SafetyController.halt``. Those collaborators are injected at
construction, so routing stays a construction-time declaration.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from itrader.core.enums import EventType

if TYPE_CHECKING:
    from itrader.events_handler.full_event_handler import EventHandler
    from itrader.strategy_handler.strategies_handler import StrategiesHandler
    from itrader.universe.universe_handler import UniverseHandler


class LiveRouteRegistrar:
    """Central declarative BUSINESS/live route table installed into ONE ``EventHandler``.

    Holds references to the built ``StrategiesHandler`` + ``UniverseHandler`` and, on
    ``install``, wires the BUSINESS/live routes into the single live
    ``EventHandler.routes`` dict ONCE. No subclass and no runtime mutation: all live
    route ordering lives here so it stays greppable in ONE place.
    """

    def __init__(
        self,
        strategies_handler: "StrategiesHandler",
        universe_handler: "UniverseHandler",
        *,
        safety: Any,
        stream_recovery: Any,
        config_router: Any = None,
    ) -> None:
        self._strategies_handler = strategies_handler
        self._universe_handler = universe_handler
        # The CONTROL-plane actuators. ``safety`` is the SafetyController
        # (pause_submission / halt); ``stream_recovery`` is the StreamRecoveryHandler
        # (on_reconnect). Held so the STREAM_STATE / CONNECTOR_FATAL routes below resolve
        # to a bound method at install().
        self._safety = safety
        self._stream_recovery = stream_recovery
        # The engine-thread ConfigRouter, held so the CONFIG_UPDATE route below resolves to
        # a bound method at install(). The registrar stays a thin delegator —
        # validate/persist/apply/push logic lives in the ConfigRouter, not here.
        self._config_router = config_router

    def install(self, event_handler: "EventHandler") -> None:
        """Install the BUSINESS/live routes into ``event_handler`` ONCE (no runtime mutation).

        SETs the live route entries to their exact method lists — list order IS execution
        order — and APPENDs to the existing ``FILL`` list, after the base portfolio + order
        FILL consumers.
        """
        routes = event_handler.routes

        # The poll rides its OWN dedicated UNIVERSE_POLL route, not the shared TIME route
        # that fans out to screeners and bar generation.
        routes[EventType.UNIVERSE_POLL] = [self._universe_handler.on_poll]
        # The add-side UniverseUpdateEvent consumer (warmup-before-subscribe).
        routes[EventType.UNIVERSE_UPDATE] = [
            self._universe_handler.on_universe_update]
        # An operator add/remove-ticker command edits the strategy universe.
        routes[EventType.STRATEGY_COMMAND] = [
            self._strategies_handler.on_strategy_command]
        # Strategies FIRST (warm indicators) THEN universe (absorb ring + mark_ready +
        # subscribe) — LIST ORDER = EXECUTION ORDER.
        routes[EventType.BARS_LOADED] = [
            self._strategies_handler.on_bars_loaded,
            self._universe_handler.on_bars_loaded,
        ]
        # BARS_LOAD_FAILED marks the symbol FAILED (kept, retried next poll).
        routes[EventType.BARS_LOAD_FAILED] = [
            self._universe_handler.on_bars_load_failed]
        # FILL = portfolio -> order -> universe -> strategies. universe.on_fill is APPENDED
        # after the base PortfolioHandler.on_fill + OrderHandler.on_fill so the read model
        # already reflects the settled (flat) position for detach-on-flat; strategies.on_fill
        # follows for the same reason — it re-scans _pending_removals and drops a
        # force-flatted strategy once the portfolio read model shows it flat. Both are added
        # ONLY on the live route: the backtest FILL list stays [portfolio, order].
        routes[EventType.FILL].append(self._universe_handler.on_fill)
        routes[EventType.FILL].append(self._strategies_handler.on_fill)

        # CONTROL-plane routes: the connector's asyncio loop puts a StreamStateEvent /
        # ConnectorFatalEvent on the bus, never touching engine state directly, and these
        # engine-thread routes actuate them. An unrouted CONTROL type still raises
        # NotImplementedError in EventHandler._dispatch, so nothing is silently dropped.
        routes[EventType.STREAM_STATE] = [self._on_stream_state]
        routes[EventType.CONNECTOR_FATAL] = [self._on_connector_fatal]

        # Populate the pre-declared empty CONFIG_UPDATE slot with its consumer: a scoped
        # runtime ConfigUpdateEvent is actuated HERE, on the engine thread, by delegating to
        # the injected ConfigRouter (validate -> persist -> apply -> push).
        #
        # Install the route ONLY when a ConfigRouter exists. build_live_system builds the
        # router exclusively when there IS a durable store; in the in-memory fallback the
        # router is None and there is nothing to persist to, so the slot stays EMPTY and a
        # stray CONFIG_UPDATE dispatches to [] as a no-op rather than to a None router.
        # Ingress rejects the update fail-closed upstream in add_event regardless.
        if self._config_router is not None:
            routes[EventType.CONFIG_UPDATE] = [self._on_config_update]

    def _on_stream_state(self, event: Any) -> None:
        """STREAM_STATE CONTROL consumer: up -> resume, down -> pause.

        ``up=True`` (a venue stream reconnected) drives the engine-thread reconnect-resume
        I/O (``StreamRecoveryHandler.on_reconnect`` — missed-fill catch-up + REST snapshot +
        all-streams-healthy gate -> resume). ``up=False`` (a disconnect) reversibly pauses
        NEW order submission. The connector loop only emitted the event; all reaction,
        including any blocking venue I/O, runs HERE on the engine thread.
        """
        if event.up:
            self._stream_recovery.on_reconnect()
        else:
            self._safety.pause_submission('paused-on-disconnect')

    def _on_connector_fatal(self, event: Any) -> None:
        """CONNECTOR_FATAL CONTROL consumer: freeze-in-place halt.

        The connector hit an unrecoverable condition and put a ``ConnectorFatalEvent``
        carrying a FIXED reason literal (never ``str(exc)``, which could leak a secret).
        Actuated on the engine thread so the blocking durable ``record_halt`` write runs off
        the connector's asyncio loop.
        """
        self._safety.halt(event.reason)

    def _on_config_update(self, event: Any) -> None:
        """CONFIG_UPDATE CONTROL consumer: delegate to the ConfigRouter.

        A ``ConfigUpdateEvent`` (scope, key, value) is actuated on the engine thread by the
        injected ``ConfigRouter.apply(event)`` — the single-writer validate -> persist ->
        apply -> push path. The registrar stays a thin delegator; no router business logic
        lives here.
        """
        # Defense-in-depth: with the route gated on a present router in install() this is
        # unreachable when the router is None, but NEVER dereference a None router — an
        # AttributeError on the engine thread would be caught by publish-and-continue and
        # the update silently dropped. A missing router means no durable store.
        if self._config_router is None:
            return
        self._config_router.apply(event)

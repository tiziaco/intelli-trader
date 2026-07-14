"""``LiveRouteRegistrar`` — the ONE central declarative BUSINESS/live route table (RUN-05/D-10/D-23).

This is the LIVE analog of the single ``EventHandler._routes`` literal
(``full_event_handler.py``) where **list order IS execution order**. Instead of
spreading the correctness-load-bearing cross-handler ordering across the live
init body, it is declared ONCE here — greppable in one place, referencing the
built handlers'/``UniverseHandler``'s methods passed to the constructor, and
installed into the single ``EventHandler`` ONCE via ``install(event_handler)``.

No subclass, no runtime mutation after install (LR-16): the base ``EventHandler``
literal ships the empty ``UNIVERSE_*`` / ``BARS_*`` routes and the base ``FILL``
list ``[portfolio.on_fill, order.on_fill]``; this registrar SETs the BUSINESS/live
routes and APPENDs ``universe.on_fill`` after the base ``FILL`` consumers. The
backtest ``EventHandler`` keeps the untouched base literal (empty ``UNIVERSE_*``),
so the backtest per-tick path is inert by construction (proven by
``tests/integration/test_okx_inertness.py``).

Registered set = the BUSINESS/live routes (D-10/D-23): ``UNIVERSE_POLL``,
``UNIVERSE_UPDATE``, ``STRATEGY_COMMAND``, ``BARS_LOADED``, ``BARS_LOAD_FAILED``,
and ``FILL`` (appended) — PLUS the CONTROL-plane routes ``STREAM_STATE`` /
``CONNECTOR_FATAL`` (SAFE-03/§11c, P7). The connector's asyncio loop puts a
``StreamStateEvent`` / ``ConnectorFatalEvent`` on the bus; these routes actuate them
on the engine thread: ``STREAM_STATE(down) -> SafetyController.pause_submission``,
``STREAM_STATE(up) -> StreamRecoveryHandler.on_reconnect``, ``CONNECTOR_FATAL ->
SafetyController.halt``. The safety + stream-recovery collaborators are injected at
construction (build_live_system, P7); routing stays a construction-time declaration,
never a runtime mutation (LR-16). The P9 ``CONFIG_UPDATE`` route populates the same way
when its consumer lands.

Load-bearing ordering (D-03b):
- ``BARS_LOADED`` = strategies FIRST (warm indicators) THEN universe (absorb ring +
  mark_ready + subscribe).
- ``FILL`` = portfolio -> order -> universe (``universe.on_fill`` APPENDED after the
  base ``FILL`` consumers, so the read model already reflects the settled/flat
  position for detach-on-flat).

Indentation: 4 SPACES (matches ``live_trading_system.py`` — the facade whose
``EventHandler`` this installs into).
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

    Holds references to the built ``StrategiesHandler`` + ``UniverseHandler`` (the
    collaborators ``SessionInitializer`` builds) and, on ``install``, wires the
    BUSINESS/live routes into the single live ``EventHandler.routes`` dict ONCE. It
    is a no-subclass / no-runtime-mutation table (LR-16): all live route ordering
    lives here so it stays greppable in ONE place (the live analog of the single
    ``_routes`` literal).
    """

    def __init__(
        self,
        strategies_handler: "StrategiesHandler",
        universe_handler: "UniverseHandler",
        *,
        safety: Any,
        stream_recovery: Any,
    ) -> None:
        self._strategies_handler = strategies_handler
        self._universe_handler = universe_handler
        # SAFE-03/§11c: the CONTROL-plane actuators (injected by build_live_system).
        # ``safety`` is the SafetyController (pause_submission / halt); ``stream_recovery``
        # is the StreamRecoveryHandler (on_reconnect). Held so the STREAM_STATE /
        # CONNECTOR_FATAL routes below resolve to a bound method at install().
        self._safety = safety
        self._stream_recovery = stream_recovery

    def install(self, event_handler: "EventHandler") -> None:
        """Install the BUSINESS/live routes into ``event_handler`` ONCE (no runtime mutation).

        SETs the live route entries (``UNIVERSE_POLL`` / ``UNIVERSE_UPDATE`` /
        ``STRATEGY_COMMAND`` / ``BARS_LOADED`` / ``BARS_LOAD_FAILED``) to the exact
        method lists — list order IS execution order (D-03b) — and APPENDs
        ``universe.on_fill`` to the existing ``FILL`` list (after the base
        portfolio + order FILL consumers). No CONTROL-plane route is registered
        (D-23 — see the module docstring).
        """
        routes = event_handler.routes

        # D-06/WR-06: the poll rides its OWN dedicated UNIVERSE_POLL route (not the
        # shared TIME route that fans to screeners/bar-gen).
        routes[EventType.UNIVERSE_POLL] = [self._universe_handler.on_poll]
        # The add-side UniverseUpdateEvent consumer (warmup-before-subscribe).
        routes[EventType.UNIVERSE_UPDATE] = [
            self._universe_handler.on_universe_update]
        # An operator add/remove-ticker command edits the strategy universe.
        routes[EventType.STRATEGY_COMMAND] = [
            self._strategies_handler.on_strategy_command]
        # BARS_LOADED runs strategies FIRST (warm indicators) THEN universe (absorb
        # ring + mark_ready + subscribe) — LIST ORDER = EXECUTION ORDER (D-03b).
        routes[EventType.BARS_LOADED] = [
            self._strategies_handler.on_bars_loaded,
            self._universe_handler.on_bars_loaded,
        ]
        # BARS_LOAD_FAILED marks the symbol FAILED (kept, retried next poll).
        routes[EventType.BARS_LOAD_FAILED] = [
            self._universe_handler.on_bars_load_failed]
        # FILL = portfolio -> order -> universe: APPEND universe.on_fill AFTER the
        # base PortfolioHandler.on_fill + OrderHandler.on_fill so the read model
        # already reflects the settled (flat) position for detach-on-flat.
        routes[EventType.FILL].append(self._universe_handler.on_fill)

        # CONTROL-plane routes (SAFE-03/§11c, P7): the connector's asyncio loop puts a
        # StreamStateEvent / ConnectorFatalEvent on the bus (never touching engine state
        # directly); these engine-thread routes actuate them. LIST ORDER = EXECUTION ORDER
        # (D-03b); SET entries, never runtime mutation (LR-16). Unrouted CONTROL types
        # still raise NotImplementedError in EventHandler._dispatch (no silent drop).
        routes[EventType.STREAM_STATE] = [self._on_stream_state]
        routes[EventType.CONNECTOR_FATAL] = [self._on_connector_fatal]

    def _on_stream_state(self, event: Any) -> None:
        """STREAM_STATE CONTROL consumer (SAFE-03/§11c): up -> resume, down -> pause.

        ``up=True`` (a venue stream reconnected) drives the engine-thread reconnect-resume
        I/O (``StreamRecoveryHandler.on_reconnect`` — missed-fill catch-up + REST snapshot +
        all-streams-healthy gate -> resume). ``up=False`` (a disconnect) reversibly pauses
        NEW order submission (``SafetyController.pause_submission``). The connector loop only
        emitted the event; all reaction (incl. any blocking venue I/O) runs HERE, on the
        engine thread (BUS-03 / Pitfall 9).
        """
        if event.up:
            self._stream_recovery.on_reconnect()
        else:
            self._safety.pause_submission('paused-on-disconnect')

    def _on_connector_fatal(self, event: Any) -> None:
        """CONNECTOR_FATAL CONTROL consumer (SAFE-03/§11c): freeze-in-place halt.

        The connector hit an unrecoverable condition and put a ``ConnectorFatalEvent``
        carrying a FIXED reason literal (V7 secret-scrub — never str(exc)). Actuated on the
        engine thread as ``SafetyController.halt(reason)`` so the blocking durable
        ``record_halt`` write runs off the connector asyncio loop (Pitfall 9).
        """
        self._safety.halt(event.reason)

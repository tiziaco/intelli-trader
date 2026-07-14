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

Registered set = the BUSINESS/live routes ONLY (D-10/D-23): ``UNIVERSE_POLL``,
``UNIVERSE_UPDATE``, ``STRATEGY_COMMAND``, ``BARS_LOADED``, ``BARS_LOAD_FAILED``,
and ``FILL`` (appended). The CONTROL-plane routes are deliberately NOT registered
here — their consumers do not exist yet (P7 ``SafetyController`` / stream recovery,
P9 config); they populate through THIS same declarative registrar when those
consumers land (construction-time declaration, never runtime mutation — LR-16).

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

from typing import TYPE_CHECKING

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
    ) -> None:
        self._strategies_handler = strategies_handler
        self._universe_handler = universe_handler

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

        # The CONTROL-plane routes are deliberately NOT registered here (D-23): their
        # consumers do not exist yet (P7 safety/stream-recovery, P9 config). They
        # populate through THIS same declarative registrar when those consumers land
        # — a construction-time declaration, never a runtime mutation (LR-16).

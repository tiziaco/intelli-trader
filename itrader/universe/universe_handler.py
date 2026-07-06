"""``UniverseHandler`` — the live-only dynamic-membership poll + add-side consumer (UNIV-01).

This handler-style file is **4-SPACE** indented to match its ``universe/`` package
(the 4-space core/config/feed family), NOT the tab-indented handler dirs
(``order_handler/`` / ``execution_handler/`` / ...). Match this file's indentation.

Why a dedicated handler (Claude's-Discretion divergence from PATTERNS.md §7): the
poll ``on_time`` COULD grow onto ``ScreenersHandler`` (which is already on the
backtest-shared ``_routes[TIME]``), but hosting it on a NEW ``UniverseHandler``
isolates the live-only route wiring from the backtest literal. Plan 05 mutates the
LIVE ``_routes[TIME]`` only, so the backtest per-tick path never pays the
source-guard / W1-measurement burden by construction (Pitfall 3 / A3).

Responsibilities (the selection/poll half of D-02 + the "screeners propose,
membership disposes" split, D-04):

- ``on_time``: source-guard (unwired route is a no-op) → poll the injected
  ``UniverseSelectionModel`` → D-06 ``validate_symbol`` filter BEFORE apply →
  ``Universe.apply`` → emit ONE ``UniverseUpdateEvent`` ONLY on a non-empty delta.
- ``on_universe_update``: the ADD branch — warmup-BEFORE-subscribe per added
  symbol (Pitfall 6). The REMOVE branch (policy), flat-detect detach, and
  admission gate are plan 04; the live timer + composition wiring are plan 05.

The handler holds ZERO membership duplication — it reads and mutates ONLY through
the injected ``Universe`` (the user's guiding constraint). ``Universe`` stays
connector-free (D-03): the D-06 filter is a DIRECT ``validate_symbol`` call here,
never handed to ``Universe``.
"""

from datetime import datetime
from queue import Queue
from typing import Any, Protocol, runtime_checkable

from itrader.events_handler.events.market import TimeEvent, UniverseUpdateEvent
from itrader.logger import get_itrader_logger
from itrader.universe.membership import UniverseSelectionModel
from itrader.universe.universe import Universe

__all__ = ["UniverseHandler"]


@runtime_checkable
class _SupportsWarmup(Protocol):
    """The feed shape the add branch drives: REST-replay warmup (LX-09/FEED-03)."""

    def warmup(self, symbol: str, timeframe: str, depth: int | None = ...) -> None: ...


class _SymbolValidator(Protocol):
    """The D-06 venue bound: an object exposing ``validate_symbol`` (e.g. OkxExchange)."""

    def validate_symbol(self, symbol: str) -> bool: ...


class _SupportsSubscribe(Protocol):
    """The data-plane provider shape the add branch drives (Arm B, plan 02)."""

    def subscribe(self, symbol: str) -> None: ...


class UniverseHandler:
    """Live-only poll host + add-side ``UniverseUpdateEvent`` consumer (Arm A).

    Constructed live-only (plan 05); nothing here is on the backtest import or
    per-tick path. Holds the queue + universe + feed + timeframe, plus three
    live-only injected seams (selection source, symbol validator, provider) that
    default to ``None`` so an unwired handler is inert.
    """

    def __init__(
        self,
        *,
        global_queue: "Queue[Any]",
        universe: Universe,
        feed: _SupportsWarmup,
        timeframe: str,
    ) -> None:
        """Hold the queue + universe read-model + feed + poll timeframe.

        Parameters
        ----------
        global_queue : Queue
            The trading-system event queue; ``on_time`` puts ``UniverseUpdateEvent``.
        universe : Universe
            The injected membership read-model — the SOLE source/sink of membership
            (the handler holds NO membership copy). Read via ``.members``, mutated
            via ``.apply``.
        feed : _SupportsWarmup
            The ``LiveBarFeed`` — warmed per added symbol BEFORE subscribe (Pitfall 6).
        timeframe : str
            The bar timeframe passed to ``feed.warmup`` on add.
        """
        self._global_queue = global_queue
        self._universe = universe
        self._feed = feed
        self._timeframe = timeframe

        # Live-only injected seams (plan 05 wires these on the live path). While
        # ``None`` the handler is inert: ``on_time`` short-circuits on the source
        # guard, so an unwired route is a near-free no-op.
        self._selection_source: UniverseSelectionModel | None = None
        self._symbol_validator: _SymbolValidator | None = None
        self._provider: _SupportsSubscribe | None = None

        self.logger = get_itrader_logger().bind(component="UniverseHandler")

    # --- live-only wiring seams (plan 05) --------------------------------------

    def set_selection_source(self, source: UniverseSelectionModel) -> None:
        """Wire the lean ``UniverseSelectionModel`` the poll consults (plan 05)."""
        self._selection_source = source

    def set_symbol_validator(self, validator: _SymbolValidator) -> None:
        """Wire the D-06 venue bound (``validate_symbol``) the poll filters through."""
        self._symbol_validator = validator

    def set_provider(self, provider: _SupportsSubscribe) -> None:
        """Wire the data-plane provider the add branch subscribes (plan 05)."""
        self._provider = provider

    # --- poll (Arm A) ----------------------------------------------------------

    def on_time(self, event: TimeEvent) -> None:
        """Poll → D-06 filter → apply → emit-only-on-non-empty (source-guarded).

        The single cheap inertness lever is the source guard: with no selection
        source wired the route returns immediately (backtest/paper wire none, so
        this is oracle-dark). Cadence itself is owned by the plan-05 live timer,
        decoupled from bars per D-02 — this method is invoked by that timer's
        ``TimeEvent`` on the live route only.
        """
        if self._selection_source is None:
            return

        desired = self._selection_source.select(event.time)

        # D-06 venue bound: filter the proposed set through ``validate_symbol``
        # BEFORE apply, so a non-listed/spoofed symbol never enters membership or
        # reaches ``provider.subscribe`` (T-06-03-SPOOF). Direct call — keeps
        # ``Universe`` connector-free (D-03).
        if self._symbol_validator is not None:
            validator = self._symbol_validator
            desired = {s for s in desired if validator.validate_symbol(s)}

        # Added-symbol precision is resolved by ``Universe.apply`` via the
        # plan-01 ``_DEFAULT_*`` ladder fallback (paper-correct, never KeyErrors).
        # Venue-correct precision resolution from the live markets map is a plan-05
        # composition-root wiring concern (where a real OKX markets map + its
        # precisionMode is available and testable); passing ``None`` here keeps the
        # handler from reaching into connector internals and honors D-03.
        delta = self._universe.apply(desired, None)

        # T-06-03-DOS: no empty-delta floods — put NOTHING when nothing changed.
        if delta.is_empty():
            return

        self._global_queue.put(
            UniverseUpdateEvent(
                time=event.time, added=delta.added, removed=delta.removed
            )
        )
        self.logger.info(
            "Universe delta applied: +%s -%s", delta.added, delta.removed
        )

    # --- add-side consumer (Arm A) --------------------------------------------

    def on_universe_update(self, event: UniverseUpdateEvent) -> None:
        """Consume a membership delta — ADD branch NOW (warmup-BEFORE-subscribe).

        For each added symbol, warm the feed FIRST (REST replay sets ``L`` on the
        ring) THEN subscribe the live socket, so the first live closed bar lands
        in-sequence rather than mis-ordered (Pitfall 6). ``provider is None``
        (paper/replay — no socket) is tolerated: warmup runs, subscribe is skipped.
        """
        for sym in event.added:
            # Warmup BEFORE subscribe (Pitfall 6) — never reorder these two.
            self._feed.warmup(sym, self._timeframe)
            if self._provider is not None:
                self._provider.subscribe(sym)

        # plan 04: REMOVE branch (policy) inserted here — ``event.removed`` handling
        # (orphan-and-track vs force-close: leaving-set mark + admission gate,
        # deferred unsubscribe until flat, force-close OrderEvent). This method is
        # extended in place; the ADD branch above stays unchanged.

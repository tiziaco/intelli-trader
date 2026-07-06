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
from decimal import Decimal
from queue import Queue
from typing import Any, Protocol, cast, runtime_checkable

from itrader.core.enums import OrderType, PositionSide, Side
from itrader.core.ids import PortfolioId, StrategyId
from itrader.core.portfolio_read_model import PortfolioReadModel, PositionView
from itrader.core.sizing import FractionOfCash, TradingDirection
from itrader.events_handler.events import SignalEvent
from itrader.events_handler.events.fill import FillEvent
from itrader.events_handler.events.market import TimeEvent, UniverseUpdateEvent
from itrader.logger import get_itrader_logger
from itrader.outils.id_generator import IDGenerator
from itrader.universe.membership import UniverseSelectionModel
from itrader.universe.universe import Universe

__all__ = ["UniverseHandler"]

# The two supported remove-policy dispositions (D-01). Default orphan-and-track.
_ORPHAN_AND_TRACK = "orphan-and-track"
_FORCE_CLOSE = "force-close"

# Engine-owned id generator for the fabricated force-close exit signal's
# strategy_id (single UUIDv7 scheme). Constructed once at import (live-only file).
_idgen = IDGenerator()


@runtime_checkable
class _SupportsWarmup(Protocol):
    """The feed shape the add branch drives: REST-replay warmup (LX-09/FEED-03)."""

    def warmup(self, symbol: str, timeframe: str, depth: int | None = ...) -> None: ...


class _SymbolValidator(Protocol):
    """The D-06 venue bound: an object exposing ``validate_symbol`` (e.g. OkxExchange)."""

    def validate_symbol(self, symbol: str) -> bool: ...


class _SupportsSubscribe(Protocol):
    """The data-plane provider shape the add/remove branch drives (Arm B, plan 02).

    The remove branch also calls ``unsubscribe`` (deferred until flat under
    orphan-and-track; immediate under force-close / when nothing is held).
    """

    def subscribe(self, symbol: str) -> None: ...

    def unsubscribe(self, symbol: str) -> None: ...


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
        remove_policy: str = _ORPHAN_AND_TRACK,
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
        remove_policy : str, optional
            The open-position-on-remove disposition (D-01). Default
            ``"orphan-and-track"`` (keep the WS/ring alive until the orphaned
            position goes flat, blocking new entries meanwhile); ``"force-close"``
            emits a market exit at removal then detaches. This flag lives in the
            LIVE/poll-seam config (wired by plan 05) — NOT
            ``SystemConfig.PerformanceSettings`` — so the backtest oracle is
            untouched (§8, D-01).
        """
        self._global_queue = global_queue
        self._universe = universe
        self._feed = feed
        self._timeframe = timeframe
        self._remove_policy = remove_policy

        # Live-only injected seams (plan 05 wires these on the live path). While
        # ``None`` the handler is inert: ``on_time`` short-circuits on the source
        # guard, so an unwired route is a near-free no-op. The read model is the
        # open-position truth the remove consumer / flat-detect read.
        self._selection_source: UniverseSelectionModel | None = None
        self._symbol_validator: _SymbolValidator | None = None
        self._provider: _SupportsSubscribe | None = None
        self._read_model: PortfolioReadModel | None = None

        self.logger = get_itrader_logger().bind(component="UniverseHandler")

    # --- live-only wiring seams (plan 05) --------------------------------------

    def set_selection_source(self, source: UniverseSelectionModel) -> None:
        """Wire the lean ``UniverseSelectionModel`` the poll consults (plan 05)."""
        self._selection_source = source

    def set_symbol_validator(self, validator: _SymbolValidator) -> None:
        """Wire the D-06 venue bound (``validate_symbol``) the poll filters through."""
        self._symbol_validator = validator

    def set_provider(self, provider: _SupportsSubscribe) -> None:
        """Wire the data-plane provider the add/remove branch drives (plan 05)."""
        self._provider = provider

    def set_portfolio_read_model(self, read_model: PortfolioReadModel) -> None:
        """Wire the ``PortfolioReadModel`` for open-position truth (plan 05).

        The remove consumer reads it to decide whether a removed symbol still
        holds a position (orphan-and-track defer vs unsubscribe-now / force-close
        exit); ``on_fill`` reads it to detect the leaving symbol reaching flat.
        With no read model wired a removed symbol is treated as no-open (paper
        add/remove of an untraded symbol).
        """
        self._read_model = read_model

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

        # REMOVE branch (D-01 policy, Pitfall 4 — do NOT unconditionally
        # unsubscribe). Branch on policy + open-position state so an orphaned
        # position's WS/ring stays alive until it goes flat.
        for sym in event.removed:
            self._on_symbol_removed(sym, event.time)

    # --- remove-policy consumer (D-01) -----------------------------------------

    def _on_symbol_removed(self, sym: str, asof: datetime) -> None:
        """Apply the remove policy to a single removed symbol (D-01, Pitfall 4).

        - No open position (either policy): unsubscribe NOW — nothing to keep
          alive (paper add/remove of an untraded symbol also lands here when no
          read model is wired).
        - orphan-and-track WITH an open position: ``mark_leaving`` and DO NOT
          unsubscribe — the WS/ring stays alive so the orphaned position's stop
          can fire; detach happens on the flat FILL (``on_fill``). New entries
          are blocked meanwhile by the plan-04 admission gate.
        - force-close WITH an open position: emit a market-exit ``SignalEvent``
          (opposite side, full exit) for each holding portfolio, ``mark_leaving``
          (so re-entry is blocked and the flat FILL clears the leaving set), then
          unsubscribe.
        """
        holders = self._holding_portfolios(sym)
        if not holders:
            self._unsubscribe(sym)
            return

        if self._remove_policy == _FORCE_CLOSE:
            for portfolio_id, snap in holders:
                self._emit_force_close_exit(sym, portfolio_id, snap, asof)
            self._universe.mark_leaving(sym)
            self._unsubscribe(sym)
            self.logger.info("Force-close removal: exit emitted + detached %s", sym)
            return

        # orphan-and-track WITH an open position: defer unsubscribe until flat.
        self._universe.mark_leaving(sym)
        self.logger.info("Orphan-and-track removal: %s kept alive until flat", sym)

    def on_fill(self, event: FillEvent) -> None:
        """Detach-on-flat: unsubscribe + clear a leaving symbol once it is flat.

        On each FILL, if the filled ticker is in ``Universe.leaving_symbols()``
        and no active portfolio holds an open position for it any more, the
        orphaned position has reached flat — unsubscribe the live socket and
        clear the symbol from the leaving set (detach-on-flat). A non-leaving
        symbol, or a leaving symbol still holding, is a no-op.

        Wired on the live FILL route only (plan 05), AFTER
        ``PortfolioHandler.on_fill`` so the read model already reflects the
        settled (flat) position.
        """
        if self._read_model is None:
            return
        ticker = event.ticker
        if ticker not in self._universe.leaving_symbols():
            return
        if self._holding_portfolios(ticker):
            return  # still held — not yet flat
        self._unsubscribe(ticker)
        self._universe.clear_leaving(ticker)
        self.logger.info("Detach-on-flat: %s reached flat, unsubscribed + cleared", ticker)

    # --- remove helpers --------------------------------------------------------

    def _holding_portfolios(
        self, sym: str
    ) -> list[tuple[PortfolioId, PositionView]]:
        """Return (portfolio_id, position) for every active portfolio holding ``sym``.

        Empty when no read model is wired (paper add/remove of an untraded
        symbol) or no portfolio holds an open position for the symbol.
        """
        if self._read_model is None:
            return []
        holders: list[tuple[PortfolioId, PositionView]] = []
        for portfolio_id in self._read_model.active_portfolio_ids():
            snap = self._read_model.get_position(portfolio_id, sym)
            if snap is not None:
                holders.append((portfolio_id, snap))
        return holders

    def _unsubscribe(self, sym: str) -> None:
        """Unsubscribe the live socket for ``sym`` (guard provider is None)."""
        if self._provider is not None:
            self._provider.unsubscribe(sym)

    def _emit_force_close_exit(
        self, sym: str, portfolio_id: PortfolioId, snap: PositionView, asof: datetime
    ) -> None:
        """Emit a market-exit ``SignalEvent`` closing ``snap`` fully (force-close).

        Opposite side from the open position (LONG -> SELL, SHORT -> BUY),
        ``exit_fraction=Decimal("1")`` (full exit). ``LONG_SHORT`` direction so
        the direction gate always passes; the leaving admission gate passes it as
        a sanctioned exit. Money is Decimal end-to-end — the indicative
        ``price`` is the position's Decimal ``avg_price`` (a MARKET order fills at
        the current bar, so the carried price is only indicative).
        """
        exit_action = Side.SELL if snap.side is PositionSide.LONG else Side.BUY
        signal = SignalEvent(
            time=asof,
            order_type=OrderType.MARKET,
            ticker=sym,
            action=exit_action,
            price=snap.avg_price,
            stop_loss=Decimal("0"),
            take_profit=Decimal("0"),
            strategy_id=cast(StrategyId, _idgen.generate_strategy_id()),
            portfolio_id=portfolio_id,
            sizing_policy=FractionOfCash(fraction=Decimal("1")),
            direction=TradingDirection.LONG_SHORT,
            exit_fraction=Decimal("1"),
        )
        self._global_queue.put(signal)

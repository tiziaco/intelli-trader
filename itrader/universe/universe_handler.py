"""``UniverseHandler`` — the live-only dynamic-membership poll + add-side consumer.

**4-SPACE** indented to match its ``universe/`` package, NOT the tab-indented handler
dirs (``order_handler/`` / ``execution_handler/`` / ...). Match this file's indentation.

Why a dedicated handler rather than growing ``on_poll`` onto ``ScreenersHandler``
(already on the backtest-shared ``_routes[TIME]``): a separate handler isolates the
live-only route wiring from the backtest literal. The poll consumes a DEDICATED
``UniversePollEvent``, never the shared business ``TIME`` route, so it cannot ride a
route reaching screeners/bar-gen and the backtest per-tick path is untouched by
construction.

Responsibilities — the selection/poll half, plus the "screeners propose, membership
disposes" split:

- ``on_poll``: freeze-gate (early-return while the engine is halted or
  submission-paused, membership freezes in place) → source-guard (an unwired route is
  a no-op) → poll the injected ``UniverseSelectionModel`` → ``validate_symbol`` filter
  BEFORE apply → precision-resolve added symbols → ``Universe.apply`` → emit ONE
  ``UniverseUpdateEvent`` ONLY on a non-empty delta.
- ``on_universe_update``: the ADD branch (warmup BEFORE subscribe per added symbol)
  and the REMOVE branch (the disposition policy); ``on_fill`` completes detach-on-flat.

The handler holds ZERO membership duplication — it reads and mutates ONLY through the
injected ``Universe``. ``Universe`` stays connector-free: the venue filter is a DIRECT
``validate_symbol`` call here, never handed to ``Universe``.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from queue import Queue
from typing import Any, Protocol, cast, runtime_checkable

from itrader.core.bar import Bar
from itrader.core.enums import OrderType, PositionSide, Side
from itrader.core.ids import PortfolioId, StrategyId
from itrader.core.instrument import Instrument
from itrader.core.portfolio_read_model import PortfolioReadModel, PositionView
from itrader.core.sizing import FractionOfCash, TradingDirection
from itrader.events_handler.events import (
    BarsLoaded,
    BarsLoadFailed,
    SignalEvent,
    UniversePollEvent,
)
from itrader.events_handler.events.fill import FillEvent
from itrader.events_handler.events.universe import UniverseUpdateEvent
from itrader.logger import get_itrader_logger
from itrader.outils.id_generator import IDGenerator
from itrader.outils.time_parser import to_timedelta
from itrader.universe.membership import UniverseSelectionModel
from itrader.universe.universe import Universe

__all__ = ["UniverseHandler", "UniverseHandlerConfig"]

# The two supported remove-policy dispositions. Default orphan-and-track.
_ORPHAN_AND_TRACK = "orphan-and-track"
_FORCE_CLOSE = "force-close"


@dataclass(frozen=True)
class UniverseHandlerConfig:
    """The two live-plane knobs the ``UniverseHandler`` reads.

    One injected object rather than two ctor params, so the handler holds no OKX
    coupling and no dependency on the config-root internals.

    - ``poll_timeframe`` — the bar timeframe passed to ``feed.warmup`` on add, and the
      interval the re-warm cadence gate measures against.
    - ``remove_policy`` — the open-position-on-remove disposition
      (``"orphan-and-track"`` default vs ``"force-close"``).

    Both live on the LIVE plane, never the backtest config, so the oracle is untouched.
    """

    poll_timeframe: str
    remove_policy: str = _ORPHAN_AND_TRACK

# Engine-owned id generator for the fabricated force-close exit signal's strategy_id
# (the single UUIDv7 scheme). Constructed once at import — this file is live-only.
_idgen = IDGenerator()


@runtime_checkable
class _SupportsWarmup(Protocol):
    """The feed shape the add branch drives.

    - ``warmup`` — the synchronous REST-replay warmup, used ONLY on the
      paper/no-provider path where there is no async stream to gate against.
    - ``absorb_warmup`` — the non-emitting ring/``L`` absorb the ``on_bars_loaded``
      consumer feeds the ``BarsLoaded`` payload into, so no tradeable ``BarEvent`` is
      emitted during warmup.
    - ``cache_capacity`` — the derived ring depth the async ``spawn_warmup`` limit is
      computed from (``cache_capacity() + config.feed_provider.warmup_margin``).
    """

    def warmup(self, symbol: str, timeframe: str, depth: int | None = ...) -> None: ...

    def absorb_warmup(
        self, symbol: str, timeframe: str, bars: tuple[Bar, ...]
    ) -> None: ...

    def cache_capacity(self) -> int: ...


class _SymbolValidator(Protocol):
    """The venue bound: an object exposing ``validate_symbol`` (e.g. ``OkxExchange``)."""

    def validate_symbol(self, symbol: str) -> bool: ...


class _SupportsResolvePrecision(Protocol):
    """The venue-precision bound: an object exposing ``resolve_precision``.

    Returns a fully-built ``Instrument`` carrying venue-correct precision for a
    freshly-added symbol, or ``None`` when the symbol is unresolvable — the caller then
    falls to ``Universe.apply``'s ``_DEFAULT_*`` ladder, which is also where every
    added symbol lands on paper/replay since neither wires a resolver. Resolution
    happens on the exchange capability, never inside ``Universe``, which stays
    connector-free.
    """

    def resolve_precision(self, symbol: str) -> Instrument | None: ...


class _VenueMetadataSource(Protocol):
    """The venue capability set ``set_venue_metadata`` reads.

    Both ``validate_symbol`` (the poll filter) and ``resolve_precision`` (added-symbol
    precision) are abstract ``AbstractExchange`` capabilities, so the live
    ``OkxExchange`` AND paper/replay's ``SimulatedExchange`` both satisfy this Protocol
    — the simulated exchange returning permissive defaults. That is what lets the seam
    be wired UNCONDITIONALLY: no OKX ``None``-guard, zero OKX coupling.
    """

    def validate_symbol(self, symbol: str) -> bool: ...

    def resolve_precision(self, symbol: str) -> Instrument | None: ...


class _SupportsSubscribe(Protocol):
    """The data-plane provider shape the add/remove branch drives.

    - ``spawn_warmup`` — the async loop-native REST warmup fetch (I/O only, no state)
      the add branch kicks off per added symbol; it emits ONE ``BarsLoaded`` /
      ``BarsLoadFailed`` back onto the queue.
    - ``subscribe`` — the live candle socket, subscribed ONLY from ``on_bars_loaded``
      AFTER the ring is warmed.
    - ``unsubscribe`` — the remove-branch teardown: deferred until flat under
      orphan-and-track, immediate under force-close or when nothing is held.
    """

    def spawn_warmup(self, symbol: str, timeframe: str, limit: int) -> None: ...

    def subscribe(self, symbol: str) -> None: ...

    def unsubscribe(self, symbol: str) -> None: ...


class _StrategyWarmthReadModel(Protocol):
    """The strategy-warmth bound (``StrategiesHandler`` satisfies it).

    ``is_warm(symbol)`` means: for EVERY strategy whose ``.tickers`` include
    ``symbol``, that strategy's per-symbol indicators have seen at least their warmup
    period. Aggregate — warm means ALL concerned strategies are warm, vacuously True
    when none are concerned. ``on_bars_loaded`` re-verifies it before flipping a symbol
    READY, so a swallowed partial strategy warmup can no longer let a half-warmed
    symbol become tradeable.
    """

    def is_warm(self, symbol: str) -> bool: ...


class UniverseHandler:
    """Live-only poll host + add-side ``UniverseUpdateEvent`` consumer.

    Constructed at the live composition root with the explicit, OKX-free dep list
    ``(bus, universe, feed, config)``. Live-only: nothing here is on the backtest
    import or per-tick path.

    Venue metadata (``validate_symbol`` + ``resolve_precision``) is wired through the
    single ``set_venue_metadata(exchange)`` seam; both are abstract
    ``AbstractExchange`` capabilities, so there is NO OKX coupling. The four
    cross-domain read-model seams (selection source, provider, portfolio read-model,
    strategy warmth) plus the ``set_freeze_gate`` callable stay explicit setters,
    defaulting to ``None`` so an unwired handler is inert.
    """

    def __init__(
        self,
        *,
        bus: "Queue[Any]",
        universe: Universe,
        feed: _SupportsWarmup,
        config: UniverseHandlerConfig,
    ) -> None:
        """Hold the bus + universe read-model + feed; read poll knobs from ``config``.

        Parameters
        ----------
        bus : Queue
            The trading-system event bus; ``on_poll`` puts ``UniverseUpdateEvent``.
        universe : Universe
            The injected membership read-model — the SOLE source and sink of
            membership, the handler holding NO copy. Read via ``.members``, mutated
            via ``.apply``.
        feed : _SupportsWarmup
            The ``LiveBarFeed``, warmed per added symbol BEFORE subscribe.
        config : UniverseHandlerConfig
            The live-plane config carrying ``poll_timeframe`` and ``remove_policy``.
        """
        self._bus = bus
        self._universe = universe
        self._feed = feed
        self._timeframe = config.poll_timeframe
        self._remove_policy = config.remove_policy

        # Handler-local live-only retry state. Both are pure hygiene: a retry cannot
        # corrupt state, so these only stop pointless re-fetches and surface a stuck
        # symbol.
        #   _last_rewarm_at: the poll ``event.time`` a FAILED symbol was last re-warmed
        #     at, so the cadence gate can skip re-warming more than once per bar
        #     interval — no new venue data closes before then.
        #   _rewarm_fail_streak: consecutive failed re-warms per symbol; warn at >= 3,
        #     reset on a mark_ready success. NEVER auto-drop.
        self._last_rewarm_at: dict[str, datetime] = {}
        self._rewarm_fail_streak: dict[str, int] = {}

        # Live-only injected seams. While ``None`` the handler is inert: ``on_poll``
        # short-circuits on the source guard, so an unwired route is a near-free no-op.
        # The read model is the open-position truth the remove consumer and flat-detect
        # read. An unwired freeze gate never freeze-skips.
        self._selection_source: UniverseSelectionModel | None = None
        self._symbol_validator: _SymbolValidator | None = None
        self._provider: _SupportsSubscribe | None = None
        self._read_model: PortfolioReadModel | None = None
        self._freeze_gate: Callable[[], bool] | None = None
        self._precision_resolver: _SupportsResolvePrecision | None = None
        # Strategy-warmth re-verify seam. While None (paper/backtest, or an unwired
        # handler) on_bars_loaded skips the re-verify and flips READY — inert by
        # default. Live wires it to the StrategiesHandler.
        self._warmth: _StrategyWarmthReadModel | None = None

        self.logger = get_itrader_logger().bind(component="UniverseHandler")

    # --- live-only wiring seams -------------------------------------------------

    def set_selection_source(self, source: UniverseSelectionModel) -> None:
        """Wire the ``UniverseSelectionModel`` the poll consults."""
        self._selection_source = source

    def set_freeze_gate(self, gate: Callable[[], bool]) -> None:
        """Wire the freeze predicate the poll early-returns on.

        The wired callable returns ``True`` when membership must freeze in place — the
        engine being HALTED or submission-paused. While it returns ``True``, ``on_poll``
        skips the whole poll: no select, no apply, no event. Membership is
        level-triggered, so the skipped poll self-heals on the next unfrozen tick, with
        NO replay and NO buffering. An unwired gate never freeze-skips, leaving
        paper/backtest inert.
        """
        self._freeze_gate = gate

    def set_venue_metadata(self, exchange: _VenueMetadataSource) -> None:
        """Wire both venue-metadata seams from ONE exchange object.

        Unconditional, with no OKX ``None``-guard: ``validate_symbol`` and
        ``resolve_precision`` are both abstract ``AbstractExchange`` capabilities, and
        paper/replay's ``SimulatedExchange`` returns permissive defaults. An
        unresolvable symbol still falls to ``Universe.apply``'s ``_DEFAULT_*`` ladder,
        so ``Universe`` stays connector-free.
        """
        self._symbol_validator = exchange
        self._precision_resolver = exchange

    def set_provider(self, provider: _SupportsSubscribe) -> None:
        """Wire the data-plane provider the add/remove branch drives."""
        self._provider = provider

    def set_portfolio_read_model(self, read_model: PortfolioReadModel) -> None:
        """Wire the ``PortfolioReadModel`` for open-position truth.

        The remove consumer reads it to decide whether a removed symbol still holds a
        position (orphan-and-track defer vs unsubscribe-now / force-close exit), and
        ``on_fill`` reads it to detect a leaving symbol reaching flat. With no read
        model wired a removed symbol is treated as no-open.
        """
        self._read_model = read_model

    def set_strategy_warmth(self, read_model: _StrategyWarmthReadModel) -> None:
        """Wire the strategy-warmth read-model (``StrategiesHandler``).

        ``on_bars_loaded`` re-verifies ``is_warm(symbol)`` before flipping the symbol
        READY and subscribing; a MISS marks it FAILED instead, so a partially-warmed
        symbol is never tradeable and is retried on the next poll. Live-only wiring, so
        the seam stays ``None`` in backtest and the re-verify is inert there.
        """
        self._warmth = read_model

    # --- poll -------------------------------------------------------------------

    def on_poll(self, event: UniversePollEvent) -> None:
        """Freeze-gate → poll → venue filter → apply → emit-only-on-non-empty.

        Consumes the DEDICATED ``UniversePollEvent``, not the shared business ``TIME``
        route, so the poll never rides a route reaching screeners/bar-gen. Cadence is
        owned by the live timer and decoupled from bars.

        Two inertness levers: the freeze gate, which while wired-and-True skips the
        whole poll so membership FREEZES IN PLACE (level-triggered — it self-heals on
        the next unfrozen tick, with no replay); and the source guard, which returns
        immediately when no selection source is wired. Backtest and paper wire neither.
        """
        # Freeze-in-place MUST precede any select/apply.
        if self._freeze_gate is not None and self._freeze_gate():
            return

        if self._selection_source is None:
            return

        desired = self._selection_source.select(event.time)

        # Filter through ``validate_symbol`` BEFORE apply, so a non-listed or spoofed
        # symbol never enters membership or reaches ``provider.subscribe``. A direct
        # call, which is what keeps ``Universe`` connector-free.
        if self._symbol_validator is not None:
            validator = self._symbol_validator
            desired = {s for s in desired if validator.validate_symbol(s)}

        instruments = self._resolve_added_instruments(desired)
        delta = self._universe.apply(desired, instruments)

        # FAILED-retry: any still-desired member whose warmup previously FAILED must be
        # re-warmed on this poll. ``apply`` never re-adds an existing member, so a FAILED
        # member never re-enters ``delta.added`` — collect them here, intersected with
        # ``desired`` so a symbol being REMOVED this poll is not retried, flip each back
        # to PENDING, and FOLD them into ``added`` so they ride the SAME warmup trigger a
        # genuinely new add uses. This MUST run even on the empty-delta fast path, which
        # is where a FAILED-retry with no other membership change lands.
        #
        # CADENCE GATE: do NOT re-warm a FAILED symbol more often than its bar interval.
        # No new venue data closes before then, so a faster poll only churns pointless
        # REST re-fetches. A symbol with no recorded prior attempt passes immediately;
        # otherwise skip while ``event.time - last_at < interval``.
        interval = to_timedelta(self._timeframe)
        collected: list[str] = []
        for sym in sorted(self._universe.failed_symbols() & desired):
            last_at = self._last_rewarm_at.get(sym)
            if last_at is not None and event.time - last_at < interval:
                continue
            self._universe.mark_pending(sym)
            self._last_rewarm_at[sym] = event.time
            collected.append(sym)
        retry = tuple(collected)
        added = delta.added + retry

        # No empty-delta floods: put NOTHING when nothing changed AND nothing needs
        # re-warming.
        if not added and not delta.removed:
            return

        self._bus.put(
            UniverseUpdateEvent(
                time=event.time, added=added, removed=delta.removed
            )
        )
        self.logger.info(
            "Universe delta applied: +%s -%s (retried %s)",
            added, delta.removed, retry
        )

    def _resolve_added_instruments(
        self, desired: set[str]
    ) -> dict[str, Instrument] | None:
        """Resolve venue-precision ``Instrument``s for the newly-added symbols.

        Returns a ``{symbol: Instrument}`` dict for the symbols in ``desired`` that are
        NOT already members and that the wired resolver resolves to a non-``None``
        ``Instrument``, or ``None`` when no resolver is wired (paper/replay) so
        ``Universe.apply`` falls entirely to the ``_DEFAULT_*`` ladder. An unresolvable
        added symbol is simply omitted — ``apply``'s ``resolved.get(sym) or default``
        lands it on the ladder without a KeyError. Resolution happens HERE, never inside
        ``Universe``, which stays connector-free.
        """
        if self._precision_resolver is None:
            return None
        resolver = self._precision_resolver
        added = desired - set(self._universe.members)
        instruments: dict[str, Instrument] = {}
        for sym in added:
            resolved = resolver.resolve_precision(sym)
            if resolved is not None:
                instruments[sym] = resolved
        return instruments

    # --- add-side consumer ------------------------------------------------------

    def on_universe_update(self, event: UniverseUpdateEvent) -> None:
        """Consume a membership delta — the ADD branch spawns async warmup.

        For each added symbol the add branch KICKS OFF warmup only. It does NOT flip
        readiness or subscribe here: both move to ``on_bars_loaded``, so a symbol is
        only tradeable once its ring is warmed. Two paths, each with one deterministic
        behaviour:

        - Live (provider wired): ``spawn_warmup`` — an async loop-native REST fetch
          mutating no feed/universe state, which later emits ONE ``BarsLoaded`` /
          ``BarsLoadFailed``. Subscribe is DEFERRED to ``on_bars_loaded``.
        - Paper (provider is ``None``, no live stream): absorb SYNCHRONOUSLY via
          ``feed.warmup`` THEN ``mark_ready`` immediately. A no-provider symbol is
          NEVER left PENDING — with the strategy and admission gates in front of it,
          PENDING would PERMANENTLY block trading a poll-added paper symbol.

        Each added symbol's warmup runs in its OWN ``try``, so one symbol's spawn
        failure never aborts the remaining adds nor the remove branch.
        """
        for sym in event.added:
            try:
                self._begin_warmup(sym)
            except Exception:
                # Log and continue — the failed symbol simply never reaches READY and
                # is retried next poll, while the batch and the remove branch below
                # still process.
                self.logger.error(
                    "Warmup kickoff failed for added symbol %s — skipped "
                    "(remaining adds + remove branch still processed)",
                    sym, exc_info=True)

        # REMOVE branch — do NOT unconditionally unsubscribe. Branch on policy and
        # open-position state so an orphaned position's WS/ring stays alive until flat.
        for sym in event.removed:
            self._on_symbol_removed(sym, event.time)

    def _begin_warmup(self, sym: str) -> None:
        """Kick off warmup for one added symbol (live async vs paper synchronous).

        Live (provider wired): async ``spawn_warmup`` — I/O only, no state mutated —
        at an EXPLICIT depth of ``feed.cache_capacity() +
        config.feed_provider.warmup_margin``. Subscribe is NOT called here; it moves to
        ``on_bars_loaded``. Paper (provider is ``None``): synchronous ``feed.warmup``
        then immediate ``mark_ready``, since there is no live stream to subscribe and
        the symbol must never be left PENDING.
        """
        if self._provider is not None:
            from itrader import config
            depth = self._feed.cache_capacity() + config.feed_provider.warmup_margin
            self._provider.spawn_warmup(sym, self._timeframe, depth)
            return
        # Paper / no-provider path: synchronous absorb + immediate READY.
        self._feed.warmup(sym, self._timeframe)
        self._universe.mark_ready(sym)

    # --- readiness-gated warmup consumers ---------------------------------------

    def on_bars_loaded(self, event: BarsLoaded) -> None:
        """Warmup bars landed — absorb → mark_ready → subscribe, in THAT order.

        The sequence completing the async warmup pipeline for one symbol:

        1. ``feed.absorb_warmup`` — silently warm the ring and advance ``L`` from the
           ``BarsLoaded`` payload, emitting NO tradeable ``BarEvent``.
        2. ``universe.mark_ready`` — flip the readiness gate so the symbol becomes
           tradeable and the strategy + admission gates pass it.
        3. ``provider.subscribe`` — subscribe the live candle socket LAST, so the first
           live closed bar lands in-sequence on the just-warmed ring.

        THE ORDER IS CORRECTNESS: mark_ready must follow the ring absorb, and subscribe
        must follow mark_ready. ``StrategiesHandler`` warms its indicators off the SAME
        ``BarsLoaded`` earlier in the route list, so indicators are warm before this
        flip. A ``None`` provider (paper) is tolerated — subscribe is skipped.

        That route-order guarantee is BACKED by an explicit strategy-warmth re-verify,
        because per-handler route isolation means a swallowed partial strategy warmup
        would otherwise still reach this flip. When a warmth read-model is wired,
        ``is_warm(symbol)`` is re-checked AFTER the ring absorb and BEFORE mark_ready; a
        MISS marks the symbol FAILED and skips BOTH mark_ready and subscribe, so a
        half-warmed symbol is never tradeable and is re-warmed on the next poll.
        """
        self._feed.absorb_warmup(event.symbol, event.timeframe, event.bars)
        # A partially-warmed symbol — a strategy indicator not yet at its warmup depth
        # — must NOT become tradeable. On a MISS mark FAILED, not READY, and return; the
        # next-poll retry re-attempts the full warmup.
        if self._warmth is not None and not self._warmth.is_warm(event.symbol):
            self._universe.mark_failed(event.symbol)
            self._record_rewarm_failure(event.symbol)
            self.logger.warning(
                "Warm-verify MISS for %s — strategy indicators not warm after "
                "warmup; marked FAILED (retried next poll)",
                event.symbol)
            return
        self._universe.mark_ready(event.symbol)
        self._reset_rewarm_streak(event.symbol)
        if self._provider is not None:
            self._provider.subscribe(event.symbol)

    def on_bars_load_failed(self, event: BarsLoadFailed) -> None:
        """Warmup backfill failed — mark FAILED, keep in membership.

        The symbol flips to ``Readiness.FAILED``, which the readiness gate keeps DARK,
        but it is NEVER removed from membership: rollback is redundant with the gate,
        and the next poll re-spawns warmup. ``reason`` is already scrubbed at the emit
        site (exception TYPE only) and is logged as-is.
        """
        self._universe.mark_failed(event.symbol)
        self._record_rewarm_failure(event.symbol)
        self.logger.warning(
            "Warmup backfill failed for %s (reason=%s) — marked FAILED "
            "(kept in membership, retried next poll)",
            event.symbol, event.reason)

    def _record_rewarm_failure(self, symbol: str) -> None:
        """Increment ``symbol``'s consecutive-failed-re-warm streak; warn at >= 3.

        Called at BOTH failure sites — the ``on_bars_loaded`` warm-verify MISS and
        ``on_bars_load_failed``. The guard is ``>=``, not ``==``, so the warning
        surfaces at the 3rd failure AND every one after it; the ``on_poll`` cadence gate
        bounds that to at most once per bar interval, giving ongoing visibility on a
        persistently stuck symbol without a log flood. The symbol is NEVER auto-dropped,
        removed from membership or quarantined — delisting is markets-freshness's job.
        """
        streak = self._rewarm_fail_streak.get(symbol, 0) + 1
        self._rewarm_fail_streak[symbol] = streak
        if streak >= 3:
            self.logger.warning(
                "Symbol %s has failed re-warm %d times consecutively — still retrying "
                "(never auto-dropped; investigate a possible delisting / stuck feed)",
                symbol, streak)

    def _reset_rewarm_streak(self, symbol: str) -> None:
        """Clear ``symbol``'s failed-re-warm streak on a genuine re-warm success.

        Deliberately does NOT clear ``_last_rewarm_at``: a LATER failure then compares
        against an old poll time and passes the cadence gate immediately, which is
        correct — a symbol that warmed successfully and only fails much later should be
        retried without waiting out an interval.
        """
        self._rewarm_fail_streak.pop(symbol, None)

    # --- remove-policy consumer -------------------------------------------------

    def _on_symbol_removed(self, sym: str, asof: datetime) -> None:
        """Apply the remove policy to a single removed symbol.

        - No open position, either policy: unsubscribe NOW — nothing to keep alive. An
          untraded symbol with no read model wired also lands here.
        - orphan-and-track WITH an open position: ``mark_leaving`` and DO NOT
          unsubscribe, so the WS/ring stays alive and the orphaned position's stop can
          still fire. Detach happens on the flat FILL; the admission gate blocks new
          entries meanwhile.
        - force-close WITH an open position: emit a market-exit ``SignalEvent``
          (opposite side, full exit) per holding portfolio, ``mark_leaving`` so re-entry
          is blocked and the flat FILL clears the leaving set, then unsubscribe.
        """
        holders = self._holding_portfolios(sym)
        if not holders:
            # Final-teardown point 1: nothing references the symbol, so tear its record
            # down atomically alongside the unsubscribe — instrument lifetime IS stream
            # lifetime.
            self._unsubscribe(sym)
            self._universe.discard_instrument(sym)
            return

        if self._remove_policy == _FORCE_CLOSE:
            for portfolio_id, snap in holders:
                self._emit_force_close_exit(sym, portfolio_id, snap, asof)
            self._universe.mark_leaving(sym)
            self._unsubscribe(sym)
            # The detach is NOT complete here: the exit order is only emitted and the
            # socket unsubscribed, while the record teardown happens later on the flat
            # FILL. The log wording must not imply full teardown already happened.
            self.logger.info(
                "Force-close removal for %s: exit order emitted, unsubscribed; "
                "detach completes on flat fill", sym)
            return

        # orphan-and-track WITH an open position: defer unsubscribe until flat.
        self._universe.mark_leaving(sym)
        self.logger.info("Orphan-and-track removal: %s kept alive until flat", sym)

    def on_fill(self, event: FillEvent) -> None:
        """Detach-on-flat: unsubscribe + clear a leaving symbol once it is flat.

        On each FILL, if the filled ticker is in ``Universe.leaving_symbols()`` and no
        active portfolio holds an open position for it any more, the orphaned position
        has reached flat: unsubscribe the live socket and clear the symbol from the
        leaving set. A non-leaving symbol, or a leaving symbol still held, is a no-op.

        Wired on the live FILL route only, AFTER ``PortfolioHandler.on_fill``, so the
        read model already reflects the settled (flat) position.
        """
        if self._read_model is None:
            return
        ticker = event.ticker
        if ticker not in self._universe.leaving_symbols():
            return
        if self._holding_portfolios(ticker):
            return  # still held — not yet flat
        # Final-teardown point 2: the orphan just went flat — unsubscribe, clear the
        # leaving flag and discard the record atomically. Keep-until-flat ends HERE, and
        # force-close discards on flat too.
        self._unsubscribe(ticker)
        self._universe.clear_leaving(ticker)
        self._universe.discard_instrument(ticker)
        self.logger.info(
            "Detach-on-flat: %s reached flat, unsubscribed + discarded", ticker)

    # --- remove helpers --------------------------------------------------------

    def _holding_portfolios(
        self, sym: str
    ) -> list[tuple[PortfolioId, PositionView]]:
        """Return (portfolio_id, position) for every active portfolio holding ``sym``.

        Empty when no read model is wired, or when no portfolio holds an open position
        for the symbol.
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

        Opposite side from the open position (LONG -> SELL, SHORT -> BUY) at
        ``exit_fraction=1``. ``LONG_SHORT`` direction so the direction gate always
        passes, and the leaving admission gate passes it as a sanctioned exit. The
        carried ``price`` is the position's ``avg_price`` and is only INDICATIVE — a
        MARKET order fills at the current bar.
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
        self._bus.put(signal)

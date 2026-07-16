"""``UniverseHandler`` — the live-only dynamic-membership poll + add-side consumer (UNIV-01).

This handler-style file is **4-SPACE** indented to match its ``universe/`` package
(the 4-space core/config/feed family), NOT the tab-indented handler dirs
(``order_handler/`` / ``execution_handler/`` / ...). Match this file's indentation.

Why a dedicated handler (Claude's-Discretion divergence from PATTERNS.md §7): the
poll ``on_poll`` COULD grow onto ``ScreenersHandler`` (which is already on the
backtest-shared ``_routes[TIME]``), but hosting it on a NEW ``UniverseHandler``
isolates the live-only route wiring from the backtest literal. The poll consumes a
DEDICATED ``UniversePollEvent`` (``EventType.UNIVERSE_POLL``) — NOT the shared
business ``TIME`` route (WR-06/D-06) — so the poll never rides a route that reaches
screeners/bar-gen, and the backtest per-tick path is untouched by construction.

Responsibilities (the selection/poll half of D-02 + the "screeners propose,
membership disposes" split, D-04):

- ``on_poll``: freeze-gate (WR-05/D-07 — early-return while the engine is halted or
  submission-paused, membership freezes in place) → source-guard (unwired route is a
  no-op) → poll the injected ``UniverseSelectionModel`` → D-06 ``validate_symbol``
  filter BEFORE apply → precision-resolve added symbols (WR-04) → ``Universe.apply``
  → emit ONE ``UniverseUpdateEvent`` ONLY on a non-empty delta.
- ``on_universe_update``: the ADD branch — warmup-BEFORE-subscribe per added
  symbol (Pitfall 6). The REMOVE branch (policy), flat-detect detach, and
  admission gate are plan 04; the live timer + composition wiring are plan 05.

The handler holds ZERO membership duplication — it reads and mutates ONLY through
the injected ``Universe`` (the user's guiding constraint). ``Universe`` stays
connector-free (D-03): the D-06 filter is a DIRECT ``validate_symbol`` call here,
never handed to ``Universe``.
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
from itrader.events_handler.events.market import UniverseUpdateEvent
from itrader.logger import get_itrader_logger
from itrader.outils.id_generator import IDGenerator
from itrader.outils.time_parser import to_timedelta
from itrader.universe.membership import UniverseSelectionModel
from itrader.universe.universe import Universe

__all__ = ["UniverseHandler", "UniverseHandlerConfig"]

# The two supported remove-policy dispositions (D-01). Default orphan-and-track.
_ORPHAN_AND_TRACK = "orphan-and-track"
_FORCE_CLOSE = "force-close"


@dataclass(frozen=True)
class UniverseHandlerConfig:
    """RUN-06/D-11: the two live-plane knobs the first-class ``UniverseHandler`` reads.

    Collapses the two former ctor params (``timeframe`` + ``remove_policy``) into the
    single injected ``config`` of the RUN-06 literal dep list ``(bus, universe, feed,
    config)`` — the handler reads BOTH values off this object, holding no OKX coupling
    and no dependency on the config-root internals.

    Provenance (the live/monitoring plane — NEVER ``PerformanceSettings``, so the
    backtest oracle config is untouched, §8/D-01):

    - ``poll_timeframe`` — was ``_STREAM_SETTINGS.okx_stream_timeframe``; the bar
      timeframe passed to ``feed.warmup`` on add and used for the CR-01 re-warm
      cadence gate.
    - ``remove_policy`` — was the legacy monitoring config's
      ``universe_remove_policy``; the open-position-on-remove disposition
      (``"orphan-and-track"`` default vs ``"force-close"``).
    """

    poll_timeframe: str
    remove_policy: str = _ORPHAN_AND_TRACK

# Engine-owned id generator for the fabricated force-close exit signal's
# strategy_id (single UUIDv7 scheme). Constructed once at import (live-only file).
_idgen = IDGenerator()


@runtime_checkable
class _SupportsWarmup(Protocol):
    """The feed shape the add branch drives (WR-02 async warmup pipeline).

    - ``warmup`` — the synchronous REST-replay warmup (LX-09/FEED-03), used ONLY
      on the paper/no-provider path where there is no async stream to gate against.
    - ``absorb_warmup`` — the non-emitting ring/``L`` absorb (D-03b) the
      ``on_bars_loaded`` consumer feeds the ``BarsLoaded`` payload into (no
      tradeable ``BarEvent`` during warmup).
    - ``cache_capacity`` — the derived ring depth the async ``spawn_warmup``
      ``limit`` is computed from
      (``cache_capacity() + config.feed_provider.warmup_margin``).
    """

    def warmup(self, symbol: str, timeframe: str, depth: int | None = ...) -> None: ...

    def absorb_warmup(
        self, symbol: str, timeframe: str, bars: tuple[Bar, ...]
    ) -> None: ...

    def cache_capacity(self) -> int: ...


class _SymbolValidator(Protocol):
    """The D-06 venue bound: an object exposing ``validate_symbol`` (e.g. OkxExchange)."""

    def validate_symbol(self, symbol: str) -> bool: ...


class _SupportsResolvePrecision(Protocol):
    """The VENUE-04/D-09 venue-precision bound: an object exposing ``resolve_precision``.

    ``resolve_precision`` returns a fully-built ``Instrument`` carrying venue-correct
    precision (from the venue markets map) for a freshly-added symbol, or ``None``
    when the symbol is unresolvable — the caller then falls to ``Universe.apply``'s
    ``_DEFAULT_*`` ladder (paper/replay wire no resolver, so an added symbol lands
    on the default ladder). ``Universe`` stays connector-free (D-09): resolution
    happens on the exchange capability (``OkxExchange.resolve_precision`` reads the
    connector markets map), never inside ``Universe``. This mirrors the sibling
    ``_SymbolValidator`` bound — the exchange itself now satisfies both.
    """

    def resolve_precision(self, symbol: str) -> Instrument | None: ...


class _VenueMetadataSource(Protocol):
    """The venue capability set ``set_venue_metadata`` reads (RUN-06/D-11).

    Both ``validate_symbol`` (D-06 poll filter) and ``resolve_precision``
    (VENUE-04/D-09 poll-added-symbol precision) are abstract ``AbstractExchange``
    capabilities since P5 VENUE-04 — the live ``OkxExchange`` AND paper/replay's
    ``SimulatedExchange`` BOTH satisfy this Protocol (the simulated exchange returns
    permissive defaults per P5 D-09). So the seam collapse is UNCONDITIONAL: no OKX
    ``None``-guard, zero OKX coupling.
    """

    def validate_symbol(self, symbol: str) -> bool: ...

    def resolve_precision(self, symbol: str) -> Instrument | None: ...


class _SupportsSubscribe(Protocol):
    """The data-plane provider shape the add/remove branch drives (Arm B, plan 02).

    - ``spawn_warmup`` — the async loop-native REST warmup fetch (I/O only, no
      state) the add branch kicks off per added symbol; it emits ONE
      ``BarsLoaded`` / ``BarsLoadFailed`` back onto the queue (plan 03).
    - ``subscribe`` — the live candle socket, subscribed ONLY from
      ``on_bars_loaded`` AFTER the ring is warmed (D-03b ordering).
    - ``unsubscribe`` — the remove branch teardown (deferred until flat under
      orphan-and-track; immediate under force-close / when nothing is held).
    """

    def spawn_warmup(self, symbol: str, timeframe: str, limit: int) -> None: ...

    def subscribe(self, symbol: str) -> None: ...

    def unsubscribe(self, symbol: str) -> None: ...


class _StrategyWarmthReadModel(Protocol):
    """The WR-02 strategy-warmth bound (``StrategiesHandler`` satisfies it).

    ``is_warm(symbol)`` means "for EVERY strategy concerned with ``symbol`` (its
    ``.tickers`` include it), that strategy's per-symbol indicators have seen
    >= their warmup period" (aggregate: warm = ALL concerned strategies warm;
    vacuously True when none are concerned). ``UniverseHandler.on_bars_loaded``
    re-verifies this before flipping a symbol READY — so a swallowed partial
    strategy warmup (per-handler route isolation) can no longer let a half-warmed
    symbol become tradeable. Mirrors the injected-seam Protocol pattern used by
    ``PortfolioReadModel`` / ``_SymbolValidator``.
    """

    def is_warm(self, symbol: str) -> bool: ...


class UniverseHandler:
    """Live-only poll host + add-side ``UniverseUpdateEvent`` consumer (Arm A).

    First-class handler (RUN-06/D-11): constructed at the live composition root with
    the explicit, OKX-free dep list ``(bus, universe, feed, config)`` — the poll
    ``timeframe`` and ``remove_policy`` are READ FROM ``config`` (a
    ``UniverseHandlerConfig``), not passed as separate params. Constructed live-only
    (plan 05); nothing here is on the backtest import or per-tick path.

    Venue metadata (``validate_symbol`` + ``resolve_precision``) is wired through the
    single ``set_venue_metadata(exchange)`` seam (D-11) — both are abstract
    ``AbstractExchange`` capabilities since P5 VENUE-04, so there is NO OKX coupling.
    The 4 cross-domain read-model seams (selection source, provider, portfolio
    read-model, strategy warmth) plus the interim ``set_freeze_gate`` callable stay as
    explicit setters (D-11), defaulting to ``None`` so an unwired handler is inert.
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
            The trading-system event bus/queue; ``on_poll`` puts ``UniverseUpdateEvent``.
        universe : Universe
            The injected membership read-model — the SOLE source/sink of membership
            (the handler holds NO membership copy). Read via ``.members``, mutated
            via ``.apply``.
        feed : _SupportsWarmup
            The ``LiveBarFeed`` — warmed per added symbol BEFORE subscribe (Pitfall 6).
        config : UniverseHandlerConfig
            The RUN-06/D-11 live-plane config the handler reads the poll
            ``poll_timeframe`` (was ``_STREAM_SETTINGS.okx_stream_timeframe``) and
            ``remove_policy`` (was the legacy monitoring config's
            ``universe_remove_policy``) from. These knobs live on the LIVE/monitoring
            plane — NOT the retired performance config — so the backtest oracle is
            untouched (§8, D-01).
        """
        self._bus = bus
        self._universe = universe
        self._feed = feed
        self._timeframe = config.poll_timeframe
        self._remove_policy = config.remove_policy

        # CR-01-retry (Level 2) handler-local live-only state (oracle-dark — the
        # backtest composition root never constructs UniverseHandler). Both are pure
        # hygiene/observability once idempotency (07-10 Tasks 2-3) landed — a retry can
        # no longer corrupt state, so this only stops pointless re-fetches + surfaces a
        # stuck symbol.
        #   _last_rewarm_at: last poll ``event.time`` a FAILED symbol was re-warmed at —
        #     the cadence gate skips re-warming more than once per bar interval (no new
        #     venue data closes before then).
        #   _rewarm_fail_streak: consecutive failed re-warms per symbol — warn at >= 3,
        #     reset on a mark_ready success. NEVER auto-drop (Level 3 is explicitly OUT).
        self._last_rewarm_at: dict[str, datetime] = {}
        self._rewarm_fail_streak: dict[str, int] = {}

        # Live-only injected seams (plan 07 wires these on the live path). While
        # ``None`` the handler is inert: ``on_poll`` short-circuits on the source
        # guard, so an unwired route is a near-free no-op. The read model is the
        # open-position truth the remove consumer / flat-detect read. The freeze
        # gate (WR-05/D-07) is None -> never freeze-skip on paper/backtest.
        self._selection_source: UniverseSelectionModel | None = None
        self._symbol_validator: _SymbolValidator | None = None
        self._provider: _SupportsSubscribe | None = None
        self._read_model: PortfolioReadModel | None = None
        self._freeze_gate: Callable[[], bool] | None = None
        self._precision_resolver: _SupportsResolvePrecision | None = None
        # WR-02 strategy-warmth re-verify seam. While None (paper/backtest, or an
        # unwired handler) on_bars_loaded skips the re-verify and flips READY as
        # before — inert by default. Live wires it to the StrategiesHandler.
        self._warmth: _StrategyWarmthReadModel | None = None

        self.logger = get_itrader_logger().bind(component="UniverseHandler")

    # --- live-only wiring seams (plan 05) --------------------------------------

    def set_selection_source(self, source: UniverseSelectionModel) -> None:
        """Wire the lean ``UniverseSelectionModel`` the poll consults (plan 07)."""
        self._selection_source = source

    def set_freeze_gate(self, gate: Callable[[], bool]) -> None:
        """Wire the WR-05/D-07 freeze predicate the poll early-returns on (plan 07).

        The wired callable returns ``True`` when membership must freeze in place —
        i.e. the engine is HALTED or submission-paused (plan 07 wires it to
        ``lambda: engine._is_halted() or engine._is_submission_paused()``). While
        it returns ``True`` ``on_poll`` skips the whole poll (no select, no apply,
        no event): membership is level-triggered, so the skipped poll self-heals on
        the next unfrozen tick — NO replay, NO buffering (D-07 freeze-in-place). An
        unwired gate (``None``) never freeze-skips, so paper/backtest are inert.
        """
        self._freeze_gate = gate

    def set_venue_metadata(self, exchange: _VenueMetadataSource) -> None:
        """Wire the venue-metadata seams (RUN-06/D-11) from ONE exchange object.

        Collapses the two former OKX-guarded symbol-validator + precision-resolver
        setters into a single UNCONDITIONAL call: the exchange's ``validate_symbol``
        (D-06 poll filter) and ``resolve_precision`` (VENUE-04/D-09 poll-added-symbol
        precision) are BOTH abstract ``AbstractExchange`` capabilities
        since P5 VENUE-04, and paper/replay's ``SimulatedExchange`` returns permissive
        defaults (P5 D-09) — so there is NO OKX ``None``-guard = zero OKX coupling. Sets
        both ``_symbol_validator`` and ``_precision_resolver`` to the exchange; the
        on_poll validate/resolve behavior is unchanged (with an unresolvable symbol
        still falling to ``Universe.apply``'s ``_DEFAULT_*`` ladder, ``Universe`` stays
        connector-free — D-09).
        """
        self._symbol_validator = exchange
        self._precision_resolver = exchange

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

    def set_strategy_warmth(self, read_model: _StrategyWarmthReadModel) -> None:
        """Wire the WR-02 strategy-warmth read-model (``StrategiesHandler``).

        ``on_bars_loaded`` re-verifies ``read_model.is_warm(symbol)`` before it
        flips the symbol READY + subscribes; a warm-check MISS marks the symbol
        FAILED instead (skip mark_ready/subscribe), so a partially-warmed symbol
        is never tradeable and is retried on the next poll (composes with the
        CR-02 FAILED-retry). Live-only wiring — the backtest composition root
        never constructs the ``UniverseHandler``, so this seam stays ``None``
        there and the re-verify is inert.
        """
        self._warmth = read_model

    # --- poll (Arm A) ----------------------------------------------------------

    def on_poll(self, event: UniversePollEvent) -> None:
        """Freeze-gate → poll → D-06 filter → apply → emit-only-on-non-empty.

        Consumes the DEDICATED ``UniversePollEvent`` (``EventType.UNIVERSE_POLL``),
        NOT the shared business ``TIME`` route (WR-06/D-06) — the poll never rides a
        route reaching screeners/bar-gen. Cadence is owned by the plan-07 live timer,
        decoupled from bars per D-02 — this method is invoked by that timer's
        ``UniversePollEvent`` on the live route only.

        Two inertness levers: (1) the WR-05/D-07 freeze gate — while wired-and-True
        (engine halted or submission-paused) the whole poll is skipped so membership
        FREEZES IN PLACE (level-triggered: self-heals next unfrozen tick, no replay);
        (2) the source guard — with no selection source wired the route returns
        immediately (backtest/paper wire neither, so both are oracle-dark).
        """
        # WR-05 / D-07 freeze-in-place: skip the poll entirely while the engine is
        # halted or submission-paused — MUST precede any select/apply. Unwired gate
        # (None) never freeze-skips (paper/backtest inert).
        if self._freeze_gate is not None and self._freeze_gate():
            return

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

        # WR-04/D-16 venue precision: resolve the ADDED symbols (those not already
        # members) to venue-precision ``Instrument``s from the markets map when a
        # resolver is wired, keeping only non-None results — ``Universe.apply``'s
        # ``resolved.get(sym) or default`` fallback (plan-02) handles an
        # unresolvable symbol, so no KeyError. Resolution happens HERE, never inside
        # ``Universe`` (D-03/D-16 connector-free). With no resolver wired (paper) the
        # dict is None and every add falls to the ``_DEFAULT_*`` ladder.
        instruments = self._resolve_added_instruments(desired)
        delta = self._universe.apply(desired, instruments)

        # CR-02 FAILED-retry ("kept in membership, retried next poll"): any
        # still-desired member whose warmup previously FAILED must be re-warmed on
        # this poll. ``apply`` never re-adds an existing member, so a FAILED member
        # never re-enters ``delta.added`` — collect them here (intersected with
        # ``desired`` so a symbol being REMOVED this poll is not retried), flip each
        # back to PENDING (the WR-02 gate keeps it dark until the re-warm lands), and
        # FOLD them into ``added`` so they ride the SAME warmup trigger a genuinely
        # new add uses (``on_universe_update`` -> ``_begin_warmup``). This MUST run
        # even on the empty-delta fast path (a FAILED-retry with no other membership
        # change). Live-only: ``on_poll`` is a live route and backtest members
        # default READY (never FAILED), so this path is oracle-inert.
        # CR-01-retry (Level 2) CADENCE GATE: do NOT re-warm a FAILED symbol more often
        # than its bar interval — no new venue data closes before then, so a faster poll
        # would only churn pointless REST re-fetches (T-07-10-CHURN). A symbol with no
        # recorded prior attempt passes immediately (first retry is allowed at once);
        # otherwise skip this poll while ``event.time - last_at < interval``. Record the
        # attempt time on each admitted re-warm so the next poll compares against it.
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

        # T-06-03-DOS: no empty-delta floods — put NOTHING when nothing changed AND
        # nothing needs re-warming.
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
        """Resolve venue-precision ``Instrument``s for the newly-added symbols (WR-04).

        Returns a ``{symbol: Instrument}`` dict for the symbols in ``desired`` that
        are NOT already members and that the wired resolver resolves to a non-None
        ``Instrument``; returns ``None`` when no resolver is wired (paper/replay) so
        ``Universe.apply`` falls entirely to the ``_DEFAULT_*`` ladder. An
        unresolvable added symbol is simply omitted — ``apply``'s ``resolved.get(sym)
        or default`` fallback lands it on the ladder without a KeyError.
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

    # --- add-side consumer (Arm A) --------------------------------------------

    def on_universe_update(self, event: UniverseUpdateEvent) -> None:
        """Consume a membership delta — ADD branch spawns async warmup (WR-02).

        For each added symbol the add branch KICKS OFF warmup only (I/O), it does
        NOT flip readiness or subscribe here — the readiness flip + subscribe move
        to ``on_bars_loaded`` so a symbol is only tradeable once its ring is warmed
        (D-03b). Two paths, resolved to ONE deterministic behavior each (no open
        OR):

        - Live (provider wired): ``provider.spawn_warmup(sym, tf, K)`` — an async
          loop-native REST fetch (no feed/universe state mutated here) that later
          emits ONE ``BarsLoaded`` / ``BarsLoadFailed``. Subscribe is DEFERRED to
          ``on_bars_loaded`` (D-03b ordering).
        - Paper (provider is None — no live stream): absorb the warmup
          SYNCHRONOUSLY via ``feed.warmup`` (which already works on the paper
          path today) THEN ``universe.mark_ready(sym)`` IMMEDIATELY. A no-provider
          symbol is NEVER left PENDING — leaving it PENDING would (with the plan-04
          strategy gate AND the plan-08 admission gate) PERMANENTLY block trading a
          poll-added paper symbol.

        Per-symbol isolation (D-04): each added symbol's warmup runs in its OWN
        ``try`` so one symbol's spawn failure never aborts the remaining adds NOR
        the remove branch (fixes the naked-remove-branch bug).
        """
        for sym in event.added:
            try:
                self._begin_warmup(sym)
            except Exception:
                # D-04 per-symbol isolation: log and continue — the failed symbol
                # simply never reaches READY (retried next poll); the batch and the
                # remove branch below still process.
                self.logger.error(
                    "Warmup kickoff failed for added symbol %s — skipped "
                    "(remaining adds + remove branch still processed)",
                    sym, exc_info=True)

        # REMOVE branch (D-01 policy, Pitfall 4 — do NOT unconditionally
        # unsubscribe). Branch on policy + open-position state so an orphaned
        # position's WS/ring stays alive until it goes flat.
        for sym in event.removed:
            self._on_symbol_removed(sym, event.time)

    def _begin_warmup(self, sym: str) -> None:
        """Kick off warmup for one added symbol (live async vs paper synchronous).

        Live (provider wired): async ``spawn_warmup`` (I/O only, no state mutated)
        with an EXPLICIT depth ``K = feed.cache_capacity() +
        config.feed_provider.warmup_margin`` (CFG-03/D-08/IN-01 folded the margin into
        config/stream.py; RESEARCH OQ4 — SAFE for the SMA_MACD-only roster). Subscribe is NOT called
        here — it moves to ``on_bars_loaded`` (D-03b). Paper (provider is None):
        synchronous ``feed.warmup`` fallback + immediate ``mark_ready`` (no live
        stream to subscribe, never left PENDING).
        """
        if self._provider is not None:
            from itrader import config
            depth = self._feed.cache_capacity() + config.feed_provider.warmup_margin
            self._provider.spawn_warmup(sym, self._timeframe, depth)
            return
        # Paper / no-provider path: synchronous absorb + immediate READY.
        self._feed.warmup(sym, self._timeframe)
        self._universe.mark_ready(sym)

    # --- readiness-gated warmup consumers (WR-02, D-03b / D-04) ----------------

    def on_bars_loaded(self, event: BarsLoaded) -> None:
        """Warmup bars landed — absorb → mark_ready → subscribe, in THAT order (D-03b).

        The deterministic route-order sequence that completes the async warmup
        pipeline for one symbol:

        1. ``feed.absorb_warmup`` — silently warm the ring + advance ``L`` from the
           ``BarsLoaded`` payload (NO tradeable ``BarEvent`` emitted).
        2. ``universe.mark_ready`` — flip the readiness gate so the symbol becomes
           tradeable (strategy + admission gates now pass it).
        3. ``provider.subscribe`` — subscribe the live candle socket LAST, so the
           first live closed bar lands in-sequence on the just-warmed ring.

        The order is correctness (T-07-06-ORDER): mark_ready MUST follow the ring
        absorb, and subscribe MUST follow mark_ready. ``StrategiesHandler`` warms
        its indicators off the SAME ``BarsLoaded`` earlier in the route list
        (list-order guarantee, plan 07), so indicators are warm before this flip.
        ``provider is None`` (paper) is tolerated — subscribe is skipped.

        WR-02: the list-order guarantee is now BACKED by an explicit strategy-warmth
        re-verify. Per-handler route isolation means a swallowed partial strategy
        warmup would otherwise still reach this flip; so when a warmth read-model is
        wired, ``is_warm(symbol)`` is re-checked AFTER the ring absorb and BEFORE
        mark_ready. A MISS marks the symbol FAILED (skip BOTH mark_ready and
        subscribe) so a half-warmed symbol is never tradeable and is re-warmed on
        the next poll (composes with the CR-02 FAILED-retry). With no warmth wired
        (paper/backtest) the re-verify is skipped — inert.
        """
        self._feed.absorb_warmup(event.symbol, event.timeframe, event.bars)
        # WR-02 warm-verify: a partially-warmed symbol (a strategy indicator not yet
        # at its warmup depth) must NOT become tradeable. On a MISS mark FAILED (not
        # READY) and return — the CR-02 next-poll retry re-attempts the full warmup.
        if self._warmth is not None and not self._warmth.is_warm(event.symbol):
            self._universe.mark_failed(event.symbol)
            # CR-01-retry (Level 2) 3-strike: a warm-verify MISS is a failed re-warm.
            self._record_rewarm_failure(event.symbol)
            self.logger.warning(
                "Warm-verify MISS for %s — strategy indicators not warm after "
                "warmup; marked FAILED (retried next poll)",
                event.symbol)
            return
        self._universe.mark_ready(event.symbol)
        # CR-01-retry (Level 2): a genuine re-warm success clears the failure streak.
        self._reset_rewarm_streak(event.symbol)
        if self._provider is not None:
            self._provider.subscribe(event.symbol)

    def on_bars_load_failed(self, event: BarsLoadFailed) -> None:
        """Warmup backfill failed — mark FAILED, keep in membership (D-04/D-05).

        The symbol is flipped to ``Readiness.FAILED`` (the readiness gate keeps it
        DARK — no trading) but is NEVER removed from membership: rollback is
        redundant with the gate, and the symbol is retried on the next poll (which
        re-spawns warmup). ``reason`` is already scrubbed at the emit site
        (exception TYPE only, T-05-27) — logged as-is.
        """
        self._universe.mark_failed(event.symbol)
        # CR-01-retry (Level 2) 3-strike: the backfill errored — a failed re-warm.
        self._record_rewarm_failure(event.symbol)
        self.logger.warning(
            "Warmup backfill failed for %s (reason=%s) — marked FAILED "
            "(kept in membership, retried next poll)",
            event.symbol, event.reason)

    def _record_rewarm_failure(self, symbol: str) -> None:
        """Increment ``symbol``'s consecutive-failed-re-warm streak; warn at >= 3 (Level 2).

        Called at BOTH failure sites (the on_bars_loaded WR-02 warm-verify MISS and
        on_bars_load_failed). The guard is ``if streak >= 3``, so a warning surfaces the
        stuck symbol + its streak at the 3rd AND every subsequent consecutive failure
        (streak 3, 4, 5, ...) — not a one-time notification, but bounded to at most once
        per bar interval by the ``on_poll`` cadence gate (so ongoing visibility for a
        persistently stuck symbol without a log flood). The symbol is NEVER auto-dropped /
        removed from membership / quarantined (Level 3 is explicitly OUT; delisting is
        handled by markets-freshness). The streak resets to 0 on a genuine re-warm success
        (``_reset_rewarm_streak``).
        """
        streak = self._rewarm_fail_streak.get(symbol, 0) + 1
        self._rewarm_fail_streak[symbol] = streak
        if streak >= 3:
            self.logger.warning(
                "Symbol %s has failed re-warm %d times consecutively — still retrying "
                "(never auto-dropped; investigate a possible delisting / stuck feed)",
                symbol, streak)

    def _reset_rewarm_streak(self, symbol: str) -> None:
        """Clear ``symbol``'s failed-re-warm streak on a genuine re-warm success (Level 2).

        Does NOT clear ``_last_rewarm_at`` — a LATER failure then compares against an old
        poll time and passes the cadence gate immediately (correct: a symbol that warmed
        successfully and only fails much later should be retried without waiting).
        """
        self._rewarm_fail_streak.pop(symbol, None)

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
            # Final-teardown point 1 (D-13): nothing references the symbol, so tear
            # its record down atomically (instrument + readiness + leaving) alongside
            # the unsubscribe — instrument lifetime == stream lifetime.
            self._unsubscribe(sym)
            self._universe.discard_instrument(sym)
            return

        if self._remove_policy == _FORCE_CLOSE:
            for portfolio_id, snap in holders:
                self._emit_force_close_exit(sym, portfolio_id, snap, asof)
            self._universe.mark_leaving(sym)
            self._unsubscribe(sym)
            # IN-01: the detach is NOT complete here — the exit order is only
            # emitted and the socket unsubscribed; the record teardown (discard)
            # happens later on the flat FILL (on_fill). Word the log accordingly so
            # it does not imply full teardown already happened.
            self.logger.info(
                "Force-close removal for %s: exit order emitted, unsubscribed; "
                "detach completes on flat fill", sym)
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
        # Final-teardown point 2 (D-13): the orphan just went flat — unsubscribe,
        # clear the leaving flag, and discard the record atomically (keep-until-flat
        # ends HERE; force-close discards on flat too, same as orphan-and-track).
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
        self._bus.put(signal)

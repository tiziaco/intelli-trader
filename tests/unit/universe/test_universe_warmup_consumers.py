"""``UniverseHandler`` async warmup consumers + strategy-derived selection (07-06).

The WR-02 handler-side centrepiece: the add branch KICKS OFF warmup (async
``spawn_warmup`` on the live path, synchronous ``feed.warmup`` + immediate
``mark_ready`` on the paper/no-provider path) and the readiness-gated consumers
complete the pipeline:

- ``on_bars_loaded`` — absorb the warmup ring → ``mark_ready`` → ``subscribe``, in
  EXACTLY that order (D-03b): the readiness flip only after the ring is warmed, the
  subscribe only after the flip.
- ``on_bars_load_failed`` — mark the symbol ``FAILED`` (stays a member, dark,
  retried next poll — D-04), NEVER rolled out of membership.

Per-symbol isolation (D-04): one symbol's spawn raising never aborts the remaining
adds nor the remove branch.

Plus the D-12 ``StrategyDerivedSelectionModel``: ``select`` re-reads the live
strategy universe each call, so an operator ticker edit propagates on the next poll.
"""

from datetime import datetime, timezone
from decimal import Decimal
from queue import Queue

import pytest

from itrader.core.bar import Bar
from itrader.core.enums import Readiness
from itrader.core.instrument import Instrument
from itrader.events_handler.events import BarsLoaded, BarsLoadFailed
from itrader.events_handler.events.market import UniverseUpdateEvent
from itrader.universe.membership import StrategyDerivedSelectionModel
from itrader.universe.universe import Universe
from itrader.config.stream import FeedProviderSettings
from itrader.universe.universe_handler import UniverseHandler, UniverseHandlerConfig

pytestmark = pytest.mark.unit


_ASOF = datetime(2024, 1, 1, tzinfo=timezone.utc)
_CACHE_CAPACITY = 100


# --- fakes -----------------------------------------------------------------


class _WarmupFeed:
    """A feed recording warmup/absorb calls into a shared ordered log.

    Satisfies the ``_SupportsWarmup`` seam: ``warmup`` (paper synchronous),
    ``absorb_warmup`` (ring absorb), ``cache_capacity`` (the async depth basis).
    """

    def __init__(self, log: list[tuple[str, str]]) -> None:
        self._log = log

    def warmup(self, symbol: str, timeframe: str, depth: int | None = None) -> None:
        self._log.append(("warmup", symbol))

    def absorb_warmup(
        self, symbol: str, timeframe: str, bars: tuple[Bar, ...]
    ) -> None:
        self._log.append(("absorb", symbol))

    def cache_capacity(self) -> int:
        return _CACHE_CAPACITY


class _WarmupProvider:
    """A provider recording spawn/subscribe/unsubscribe; optionally raises on spawn.

    Satisfies the extended ``_SupportsSubscribe`` seam (``spawn_warmup`` +
    ``subscribe`` + ``unsubscribe``). ``spawn_calls`` captures every spawn attempt
    (even a raising one); the shared ``log`` records successful spawns/subscribes.
    """

    def __init__(
        self, log: list[tuple[str, str]], raise_on: frozenset[str] = frozenset()
    ) -> None:
        self._log = log
        self._raise_on = raise_on
        self.spawn_calls: list[tuple[str, str, int]] = []

    def spawn_warmup(self, symbol: str, timeframe: str, limit: int) -> None:
        self.spawn_calls.append((symbol, timeframe, limit))
        if symbol in self._raise_on:
            raise RuntimeError(f"spawn failed for {symbol}")
        self._log.append(("spawn", symbol))

    def subscribe(self, symbol: str) -> None:
        self._log.append(("subscribe", symbol))

    def unsubscribe(self, symbol: str) -> None:
        self._log.append(("unsubscribe", symbol))


class _SpyUniverse(Universe):
    """A ``Universe`` logging its readiness/teardown mutations into a shared log.

    Lets the ordered-spy tests assert the exact ``absorb → mark_ready → subscribe``
    interleaving across the feed, universe, and provider seams.
    """

    def __init__(self, log: list[tuple[str, str]], **kwargs: object) -> None:
        super().__init__(**kwargs)  # type: ignore[arg-type]
        self._log = log

    def mark_ready(self, symbol: str) -> None:
        self._log.append(("mark_ready", symbol))
        super().mark_ready(symbol)

    def mark_failed(self, symbol: str) -> None:
        self._log.append(("mark_failed", symbol))
        super().mark_failed(symbol)


# --- helpers ---------------------------------------------------------------


def _inst(symbol: str) -> Instrument:
    return Instrument(
        symbol=symbol,
        price_precision=Decimal("0.01"),
        quantity_precision=Decimal("0.00000001"),
        maintenance_margin_rate=Decimal("0.005"),
        max_leverage=Decimal("1"),
    )


def _universe(*symbols: str) -> Universe:
    members = sorted(symbols)
    return Universe(members=members, instrument_map={s: _inst(s) for s in members})


def _spy_universe(log: list[tuple[str, str]], *symbols: str) -> _SpyUniverse:
    members = sorted(symbols)
    return _SpyUniverse(
        log, members=members, instrument_map={s: _inst(s) for s in members}
    )


def _handler(
    universe: Universe,
    *,
    feed: object,
    provider: object | None = None,
) -> UniverseHandler:
    handler = UniverseHandler(
        bus=Queue(),
        universe=universe,
        feed=feed,  # type: ignore[arg-type]
        config=UniverseHandlerConfig(poll_timeframe="1d"),
    )
    if provider is not None:
        handler.set_provider(provider)  # type: ignore[arg-type]
    return handler


def _bar(price: str) -> Bar:
    return Bar(
        time=_ASOF,
        open=Decimal(price),
        high=Decimal(price),
        low=Decimal(price),
        close=Decimal(price),
        volume=Decimal("1"),
    )


# --- add branch: async spawn (live) ----------------------------------------


def test_add_branch_spawns_warmup_no_synchronous_subscribe() -> None:
    """The add branch calls spawn_warmup (K depth) and does NOT subscribe."""
    log: list[tuple[str, str]] = []
    universe = _universe("BTC/USDC")
    # ETH/USDC arrives as a PENDING record via apply (the on_poll precursor).
    universe.apply({"BTC/USDC", "ETH/USDC"})
    feed = _WarmupFeed(log)
    provider = _WarmupProvider(log)
    handler = _handler(universe, feed=feed, provider=provider)

    handler.on_universe_update(
        UniverseUpdateEvent(time=_ASOF, added=("ETH/USDC",), removed=())
    )

    # spawn_warmup fired with the explicit depth K = cache_capacity + margin.
    assert provider.spawn_calls == [
        ("ETH/USDC", "1d", _CACHE_CAPACITY + FeedProviderSettings().warmup_margin)]
    # No synchronous subscribe on the add branch — subscribe moves to on_bars_loaded.
    assert ("subscribe", "ETH/USDC") not in log
    # The add branch did NOT flip readiness (that is on_bars_loaded's job).
    assert not universe.is_ready("ETH/USDC")


# --- on_bars_loaded: absorb → mark_ready → subscribe (D-03b) ----------------


def test_on_bars_loaded_absorb_then_ready_then_subscribe_in_order() -> None:
    """on_bars_loaded runs absorb → mark_ready → subscribe in EXACTLY that order."""
    log: list[tuple[str, str]] = []
    universe = _spy_universe(log, "BTC/USDC")
    universe.apply({"BTC/USDC", "ETH/USDC"})  # ETH pending
    feed = _WarmupFeed(log)
    provider = _WarmupProvider(log)
    handler = _handler(universe, feed=feed, provider=provider)

    handler.on_bars_loaded(
        BarsLoaded(time=_ASOF, symbol="ETH/USDC", timeframe="1d", bars=(_bar("100"),))
    )

    assert log == [
        ("absorb", "ETH/USDC"),
        ("mark_ready", "ETH/USDC"),
        ("subscribe", "ETH/USDC"),
    ]
    assert universe.is_ready("ETH/USDC")


def test_on_bars_loaded_provider_none_skips_subscribe() -> None:
    """on_bars_loaded with no provider still absorbs + marks ready (subscribe skipped)."""
    log: list[tuple[str, str]] = []
    universe = _universe("BTC/USDC")
    universe.apply({"BTC/USDC", "ETH/USDC"})
    feed = _WarmupFeed(log)
    handler = _handler(universe, feed=feed)  # no provider

    handler.on_bars_loaded(
        BarsLoaded(time=_ASOF, symbol="ETH/USDC", timeframe="1d", bars=(_bar("100"),))
    )

    assert log == [("absorb", "ETH/USDC")]
    assert universe.is_ready("ETH/USDC")


# --- on_bars_load_failed: FAILED, kept in membership (D-04) -----------------


def test_on_bars_load_failed_marks_failed_and_keeps_member() -> None:
    """on_bars_load_failed marks FAILED, keeps the symbol a member (never rolled out)."""
    universe = _universe("BTC/USDC")
    universe.apply({"BTC/USDC", "ETH/USDC"})  # ETH pending member
    feed = _WarmupFeed([])
    handler = _handler(universe, feed=feed)

    handler.on_bars_load_failed(
        BarsLoadFailed(time=_ASOF, symbol="ETH/USDC", reason="MissingPriceDataError")
    )

    # Marked FAILED — the readiness gate keeps it dark.
    assert not universe.is_ready("ETH/USDC")
    assert universe._entries["ETH/USDC"].readiness is Readiness.FAILED
    # NEVER removed from membership — retried next poll.
    assert "ETH/USDC" in universe.members
    # The record survives (not discarded) — instrument still resolves.
    assert universe.instrument("ETH/USDC").symbol == "ETH/USDC"


# --- per-symbol isolation (D-04) -------------------------------------------


def test_one_spawn_failure_does_not_abort_batch_or_remove_branch() -> None:
    """A spawn raising for one symbol still processes the other adds AND the removes."""
    log: list[tuple[str, str]] = []
    universe = _universe("KEEP/USDC")
    universe.apply({"KEEP/USDC", "AAA/USDC", "BBB/USDC"})  # AAA, BBB pending
    feed = _WarmupFeed(log)
    provider = _WarmupProvider(log, raise_on=frozenset({"AAA/USDC"}))
    handler = _handler(universe, feed=feed, provider=provider)

    handler.on_universe_update(
        UniverseUpdateEvent(
            time=_ASOF, added=("AAA/USDC", "BBB/USDC"), removed=("KEEP/USDC",)
        )
    )

    # Both symbols were spawn-attempted despite AAA raising first.
    spawned = {sym for sym, _, _ in provider.spawn_calls}
    assert spawned == {"AAA/USDC", "BBB/USDC"}
    # BBB's spawn succeeded (logged); AAA's raised (not logged) but did not abort.
    assert ("spawn", "BBB/USDC") in log
    # The remove branch still ran: KEEP/USDC (no holder) was unsubscribed.
    assert ("unsubscribe", "KEEP/USDC") in log


# --- paper path (WARNING 1): provider None → synchronous absorb + READY ------


def test_paper_path_no_provider_absorbs_synchronously_and_marks_ready() -> None:
    """provider is None → synchronous feed.warmup + immediate mark_ready (never PENDING)."""
    log: list[tuple[str, str]] = []
    universe = _universe("BTC/USDC")
    universe.apply({"BTC/USDC", "ETH/USDC"})  # ETH pending
    assert not universe.is_ready("ETH/USDC")  # PENDING before the add branch
    feed = _WarmupFeed(log)
    handler = _handler(universe, feed=feed)  # NO provider wired

    handler.on_universe_update(
        UniverseUpdateEvent(time=_ASOF, added=("ETH/USDC",), removed=())
    )

    # Synchronous warmup ran, no subscribe (no live stream on paper).
    assert log == [("warmup", "ETH/USDC")]
    # The symbol reached READY — NEVER left PENDING (would permanently block trading).
    assert universe.is_ready("ETH/USDC")


# --- strategy-derived selection model (D-12 / OP-SEAM) ---------------------


class _FakeStrategiesSource:
    """A live strategy-universe source whose set can be mutated between reads."""

    def __init__(self, tickers: list[str]) -> None:
        self._tickers = tickers

    def get_strategies_universe(self) -> list[str]:
        return list(self._tickers)

    def edit(self, tickers: list[str]) -> None:
        self._tickers = tickers


def test_strategy_derived_select_reads_current_universe() -> None:
    """select() returns the CURRENT get_strategies_universe() set."""
    source = _FakeStrategiesSource(["BTC/USDC", "ETH/USDC"])
    model = StrategyDerivedSelectionModel(source)
    assert model.select(_ASOF) == {"BTC/USDC", "ETH/USDC"}


def test_strategy_derived_select_reflects_ticker_edit_no_stale_snapshot() -> None:
    """Mutating the source between two select() calls changes the result (no snapshot)."""
    source = _FakeStrategiesSource(["BTC/USDC"])
    model = StrategyDerivedSelectionModel(source)
    assert model.select(_ASOF) == {"BTC/USDC"}

    # Operator ticker edit (Plan 04 mutating .tickers) — propagates on next select.
    source.edit(["BTC/USDC", "SOL/USDC"])
    assert model.select(_ASOF) == {"BTC/USDC", "SOL/USDC"}

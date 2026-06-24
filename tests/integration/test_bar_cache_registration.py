"""Plan-A shared recent-bars feed coverage (P5-D16/P5-D16a/P5-D16b/P5-D22).

The four Plan-A plumbing assertions for the shared recent-bars feed data layer
(05-01-VALIDATION Per-Task Verification Map row):

1. **Capacity-derivation deferral (P5-D16/P5-D22):** ``cache_registration.derive``
   over an EMPTY raw-bar-consumer set returns the newest-bar-only capacity
   (depth 1) — the deep multi-bar cache is NOT built.
2. **Capacity ladder (P5-D16):** ``derive`` composes/ladders ``max`` over
   registered raw-bar consumers (sorted/deduped depth view), mirroring the
   ``derive_instruments`` "compose, ladder per member" shape.
3. **G5 newest-bar unify (P5-D16a):** after ``generate_bar_event`` for a tick,
   the feed's ``newest_bar(ticker)`` equals the corresponding
   ``BarEvent.bars[ticker]`` for every present symbol — ONE source of truth.
4. **G1 trigger-seam guard (P5-D16b):** wiring a trigger seam with
   ``base_timeframe > min(timeframe)`` raises (the ``base_timeframe <=
   min(timeframe)`` causality guard).

This is plumbing coverage, not a full backtest: a tiny synthetic in-memory
store seeds two symbols' bars. Respects ``filterwarnings=["error"]``.

Indentation: 4 SPACES (``tests/`` convention + the ``price_handler/feed/`` package).
"""

from datetime import timedelta

import pandas as pd
import pytest

from itrader.config import TIMEZONE
from itrader.events_handler.events import TimeEvent
from itrader.price_handler.feed import BacktestBarFeed
from itrader.price_handler.feed import cache_registration
from itrader.price_handler.feed.base import assert_update_trigger
from itrader.price_handler.store.base import PriceStore

pytestmark = pytest.mark.integration


# -- Synthetic store + stub consumers --------------------------------------


class _StubConsumer:
    """A raw-bar consumer declaring a required history depth (RawBarConsumer)."""

    def __init__(self, depth: int) -> None:
        self._depth = depth

    @property
    def required_history_depth(self) -> int:
        return self._depth


class _SyntheticStore(PriceStore):
    """A tiny in-memory two-symbol store — no CSV/file I/O.

    Each ticker gets ``n_bars`` daily bars stamped on a shared date grid so a
    single ``current_bars(time)`` walk produces a bar for every symbol present
    at that stamp (the G5 unify shape).
    """

    def __init__(self, symbols: list[str], n_bars: int = 5) -> None:
        index = pd.date_range("2020-01-01", periods=n_bars, freq="D",
                              tz=TIMEZONE)
        index.name = "date"
        self._frames: dict[str, pd.DataFrame] = {}
        for s, base in zip(symbols, (100.0, 200.0)):
            self._frames[s] = pd.DataFrame(
                {
                    "open": [base + i for i in range(n_bars)],
                    "high": [base + 10 + i for i in range(n_bars)],
                    "low": [base - 10 + i for i in range(n_bars)],
                    "close": [base + 5 + i for i in range(n_bars)],
                    "volume": [1000 + i for i in range(n_bars)],
                },
                index=index,
            ).astype(float)

    def read_bars(self, ticker: str) -> pd.DataFrame:
        return self._frames[ticker]

    def has(self, ticker: str) -> bool:
        return ticker in self._frames

    def symbols(self) -> list[str]:
        return list(self._frames)

    def index(self, ticker: str) -> pd.DatetimeIndex:
        idx = self._frames[ticker].index
        assert isinstance(idx, pd.DatetimeIndex)
        return idx

    def write_bars(self, ticker: str, frame: pd.DataFrame) -> None:  # noqa: D102
        raise NotImplementedError


@pytest.fixture
def feed() -> BacktestBarFeed:
    """A two-symbol 1d synthetic feed (BTCUSD/ETHUSD)."""
    store = _SyntheticStore(["BTCUSD", "ETHUSD"], n_bars=5)
    return BacktestBarFeed(store, timedelta(days=1))


# -- (1) Capacity-derivation deferral (P5-D16/P5-D22) ----------------------


def test_empty_consumer_set_yields_newest_bar_only_capacity(feed):
    """An EMPTY raw-bar-consumer set derives the newest-bar-only depth (1).

    Proves the deferral: with no raw-bar consumer registered the deep multi-bar
    cache is NOT built — capacity is the newest-bar floor (P5-D16/P5-D22).
    """
    # Pure-function level.
    assert cache_registration.derive() == cache_registration.NEWEST_BAR_ONLY
    assert cache_registration.derive(()) == 1
    assert cache_registration.derive_required_depths(()) == []
    # Feed level — no consumer registered yet.
    assert feed.cache_capacity() == cache_registration.NEWEST_BAR_ONLY


# -- (2) Capacity ladder / compose (P5-D16) --------------------------------


def test_derive_ladders_max_over_registered_consumers(feed):
    """``derive`` returns the MAX declared depth; depths view is sorted/deduped."""
    consumers = [_StubConsumer(3), _StubConsumer(7), _StubConsumer(3)]
    # Ladder: max over declared depths.
    assert cache_registration.derive(consumers) == 7
    # Sorted + deduped depth view (mirrors derive_membership's sorted(set(...))).
    assert cache_registration.derive_required_depths(consumers) == [3, 7]
    # Never below the newest-bar floor.
    assert cache_registration.derive([_StubConsumer(1)]) == 1

    # Registration through the ABC seam re-derives capacity from all consumers.
    feed.register_raw_bar_consumer(_StubConsumer(4))
    feed.register_raw_bar_consumer(_StubConsumer(9))
    assert feed.cache_capacity() == 9


# -- (3) G5 newest-bar unify — one source of truth (P5-D16a) ---------------


def test_newest_bar_equals_bar_event_payload(feed):
    """After a tick, newest_bar(ticker) == BarEvent.bars[ticker] for each symbol."""
    tick_time = pd.Timestamp("2020-01-03", tz=TIMEZONE)
    bar_event = feed.generate_bar_event(TimeEvent(time=tick_time))

    assert bar_event is not None
    # Both symbols have a bar at this stamp (shared grid).
    assert set(bar_event.bars) == {"BTCUSD", "ETHUSD"}
    for ticker, bar in bar_event.bars.items():
        # SAME object/value the single G5 walk wrote to the cache row.
        assert feed.newest_bar(ticker) is bar

    # A symbol with no bar produced yet returns None (pre-first-bar).
    assert feed.newest_bar("UNSEEN") is None


def test_newest_bar_tracks_latest_tick(feed):
    """newest_bar advances to the latest tick's bar (newest-row semantics)."""
    first = feed.generate_bar_event(TimeEvent(
        time=pd.Timestamp("2020-01-02", tz=TIMEZONE)))
    second = feed.generate_bar_event(TimeEvent(
        time=pd.Timestamp("2020-01-04", tz=TIMEZONE)))
    assert first is not None and second is not None
    # newest_bar reflects the SECOND (latest) tick, not the first.
    assert feed.newest_bar("BTCUSD") is second.bars["BTCUSD"]
    assert feed.newest_bar("BTCUSD") is not first.bars["BTCUSD"]


# -- (4) G1 trigger-seam causality guard (P5-D16b) -------------------------


def test_trigger_seam_rejects_base_coarser_than_finest_timeframe(feed):
    """base_timeframe > min(timeframe) raises (non-causal sub-base trigger)."""
    # Feed base is 1d; a consumer driving off a 1h timeframe is finer than base
    # -> base_timeframe (1d) > min(timeframe) (1h) -> raises.
    with pytest.raises(ValueError, match="base_timeframe"):
        feed.assert_update_trigger([timedelta(hours=1)])

    # Module-level guard, same contract.
    with pytest.raises(ValueError, match="min\\(timeframe\\)"):
        assert_update_trigger(timedelta(days=1), [timedelta(hours=12)])


def test_trigger_seam_allows_base_le_min_timeframe(feed):
    """base_timeframe <= min(timeframe) is allowed — golden 1d==base collapses."""
    # Golden case: 1d == base == 1d -> 'every tick', holds trivially.
    feed.assert_update_trigger([timedelta(days=1)])
    # Coarser consumed timeframe (7d) over a 1d base is fine.
    feed.assert_update_trigger([timedelta(days=1), timedelta(days=7)])
    # Empty consumed set is a no-op (nothing to order against).
    feed.assert_update_trigger([])

"""07-09 remediation: LiveBarFeed per-thread replay guard (WR-04) + timeframe-keyed _find_ring (WR-05).

WR-04: ``_replaying_backfill`` is now per-thread scoped (a property over
``threading.local``). An engine-thread gap arriving mid connector-loop replay
reads its OWN thread-local False (not the connector's True), so it is NOT
misclassified as a nested in-replay gap — no cross-thread poison, no spurious
connector HALT. The three original call sites (read / set-True / set-False) are
unchanged.

WR-05: ``_find_ring`` honors the base timeframe — it returns ONLY the ring at the
feed's base timeframe for a symbol (a same-symbol ring at another timeframe is not
returned), and raises ``MissingPriceDataError`` on a miss. Offline / socket-free.

Folder-derived ``unit`` marker; respects filterwarnings=["error"]. 4-SPACE.
"""

from __future__ import annotations

import threading
from collections import deque
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from itrader.core.bar import Bar
from itrader.core.exceptions import MissingPriceDataError
from itrader.outils.time_parser import to_timedelta
from itrader.price_handler.feed.live_bar_feed import LiveBarFeed

pytestmark = pytest.mark.unit

_ASOF = datetime(2024, 1, 1, tzinfo=timezone.utc)


def _feed() -> LiveBarFeed:
    return LiveBarFeed(provider=None, base_timeframe=to_timedelta("1d"))


def _bar() -> Bar:
    px = Decimal("100")
    return Bar(time=_ASOF, open=px, high=px, low=px, close=px, volume=Decimal("1"))


# --------------------------------------------------------------------------- #
# (i) WR-04 — per-thread replay guard (no cross-thread poison).
# --------------------------------------------------------------------------- #


def test_wr04_default_false_on_current_thread() -> None:
    """A fresh feed reads the guard False on the calling thread (thread-local default)."""
    feed = _feed()
    assert feed._replaying_backfill is False


def test_wr04_set_true_is_local_to_the_setting_thread() -> None:
    """Setting True on this thread reads True here — round-trips through the property."""
    feed = _feed()
    feed._replaying_backfill = True
    try:
        assert feed._replaying_backfill is True
    finally:
        feed._replaying_backfill = False
    assert feed._replaying_backfill is False


def test_wr04_other_thread_true_does_not_poison_current_thread() -> None:
    """A SEPARATE thread setting the guard True leaves the current thread reading False."""
    feed = _feed()
    set_on_other = threading.Event()
    release = threading.Event()
    other_view: dict[str, bool] = {}

    def _worker() -> None:
        feed._replaying_backfill = True  # set on the worker thread
        other_view["worker"] = feed._replaying_backfill  # its OWN view is True
        set_on_other.set()
        release.wait(timeout=5)

    t = threading.Thread(target=_worker)
    t.start()
    try:
        assert set_on_other.wait(timeout=5)
        # The connector thread has the guard True; the engine (this) thread must
        # read its OWN thread-local False — no cross-thread poison (WR-04).
        assert feed._replaying_backfill is False
        assert other_view["worker"] is True
    finally:
        release.set()
        t.join(timeout=5)


# --------------------------------------------------------------------------- #
# (ii) WR-05 — _find_ring honors the base timeframe.
# --------------------------------------------------------------------------- #


def test_wr05_find_ring_returns_base_timeframe_ring() -> None:
    """With rings for the same symbol at two timeframes, _find_ring returns the base one."""
    feed = _feed()  # base timeframe 1d
    base_ring: "deque[Bar]" = deque([_bar()])
    other_ring: "deque[Bar]" = deque([_bar(), _bar()])
    # Same symbol, two base-timeframe rings — the old first-match loop could return
    # whichever iterated first; WR-05 must return the 1d (base) one.
    feed._ring[("BTC-USDT", "4h")] = other_ring  # NOT the base timeframe
    feed._ring[("BTC-USDT", "1d")] = base_ring    # the base timeframe (alias 1D)

    assert feed._find_ring("BTC-USDT") is base_ring


def test_wr05_find_ring_matches_regardless_of_tf_string_case() -> None:
    """The ring tf string is normalized ('1d'/'1D' both map to the base alias)."""
    feed = _feed()
    ring: "deque[Bar]" = deque([_bar()])
    feed._ring[("ETH-USDT", "1D")] = ring  # uppercase venue-style string

    assert feed._find_ring("ETH-USDT") is ring


def test_wr05_find_ring_raises_on_missing_symbol() -> None:
    """A symbol with no ring raises MissingPriceDataError."""
    feed = _feed()
    with pytest.raises(MissingPriceDataError):
        feed._find_ring("NOPE-USDT")


def test_wr05_find_ring_raises_when_only_other_timeframe_present() -> None:
    """A symbol present ONLY at a non-base timeframe is treated as absent at base."""
    feed = _feed()
    feed._ring[("SOL-USDT", "4h")] = deque([_bar()])  # only a non-base ring
    with pytest.raises(MissingPriceDataError):
        feed._find_ring("SOL-USDT")

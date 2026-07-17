"""F-1 — timeframe-aware warmup ring depth + the shared warmability boundary.

The unit defect this locks: the ``LiveBarFeed`` ring holds **BASE** bars and
``window()`` resamples them on read, while ``strategy.warmup`` counts
**STRATEGY-TIMEFRAME** bars (auto-derived from indicator ``min_period``,
base.py:391). ``derive_warmup_depth`` reconciled neither unit — it returned a
bare ``max(s.warmup)``. So a strategy COARSER than the base cadence needs
``warmup * multiple`` base bars but got ``warmup``: a 4h strategy with
``warmup=100`` on a 1h base feed resamples a 100-bar ring down to 25 bars, never
reaches 100, and **silently never trades, forever** — registered, ``is_ready``
False for good, emitting nothing, raising nothing.

``required_base_depth`` is the single place the two units are reconciled, and the
shared boundary the D-10 ``add`` (Plan 07) and D-15 ``reconfigure`` (Plan 08) arms
call to decide whether a configuration is warmable at all. An unwarmable timeframe
is a LOUD reject, never a silently-accepted fractional depth.

Folder-derived ``unit`` marker (do NOT hand-apply). 4-space indented, matching the
``price_handler/feed/`` package convention.
"""

from datetime import timedelta

import pytest

from itrader.price_handler.feed.cache_registration import (
    StrategyWarmupConsumer,
    UnwarmableTimeframeError,
    derive_warmup_depth,
    register_strategy_warmup,
    required_base_depth,
)

pytestmark = pytest.mark.unit

_1H = timedelta(hours=1)
_4H = timedelta(hours=4)
_1D = timedelta(days=1)
_15M = timedelta(minutes=15)
_90M = timedelta(minutes=90)


class _StubStrategy:
    """The minimal ``_SupportsWarmup`` shape: ``warmup`` + ``timeframe``.

    Deliberately NOT a real ``Strategy`` — the Protocol reads exactly two members,
    and constructing a real strategy would drag in indicator registration that has
    nothing to do with the depth derivation.
    """

    def __init__(self, warmup: int, timeframe: timedelta) -> None:
        self.warmup = warmup
        self.timeframe = timeframe


class _StubFeed:
    """A feed stand-in carrying the registration + capacity surface."""

    def __init__(self) -> None:
        self.consumers: list[object] = []

    def register_raw_bar_consumer(self, consumer: object) -> None:
        self.consumers.append(consumer)

    def cache_capacity(self) -> int:
        from itrader.price_handler.feed.cache_registration import derive

        return derive(self.consumers)  # type: ignore[arg-type]


# --- required_base_depth: the adjacency cases -------------------------------


def test_required_base_depth_equal_timeframes_is_unscaled() -> None:
    """F-1 adjacency: strategy timeframe == base cadence -> multiple 1 -> the depth
    is byte-identical to the old max(warmup). This is the SMA_MACD live shape and
    it must not move."""
    assert required_base_depth(warmup=100, strategy_timeframe=_1D, base_timeframe=_1D) == 100


def test_required_base_depth_coarser_strategy_scales_by_multiple() -> None:
    """F-1, the defect case: a 4h strategy on a 1h base needs 4x the base bars.

    100 strategy-timeframe bars == 400 base bars. The old body returned 100 — a
    ring that resamples to 25 bars and never warms."""
    assert required_base_depth(warmup=100, strategy_timeframe=_4H, base_timeframe=_1H) == 400


# --- required_base_depth: the loud rejects ----------------------------------


def test_required_base_depth_rejects_finer_than_base() -> None:
    """F-1/D-15: a strategy FINER than the base cadence cannot be served — the feed
    holds base bars and its off-grid guard would actively DROP finer bars. Reject
    loudly rather than return a fractional/floored depth."""
    with pytest.raises(UnwarmableTimeframeError) as exc:
        required_base_depth(warmup=100, strategy_timeframe=_15M, base_timeframe=_1H)

    message = str(exc.value)
    assert "0:15:00" in message, "the reject names the strategy timeframe"
    assert "1:00:00" in message, "the reject names the base timeframe"


def test_required_base_depth_rejects_non_multiple() -> None:
    """F-1: a 90m strategy on a 1h base is a non-multiple — its resample buckets
    straddle base-bar boundaries with partial data. Never silently floor to 1."""
    with pytest.raises(UnwarmableTimeframeError) as exc:
        required_base_depth(warmup=100, strategy_timeframe=_90M, base_timeframe=_1H)

    message = str(exc.value)
    assert "1:30:00" in message, "the reject names the strategy timeframe"
    assert "1:00:00" in message, "the reject names the base timeframe"


# --- derive_warmup_depth ----------------------------------------------------


def test_derive_warmup_depth_ladders_max_over_base_bar_requirements() -> None:
    """The backstop: two strategies with DIFFERENT timeframes on one feed derive a
    single ring depth == the MAXIMUM of their individual base-bar requirements, so
    neither is starved.

    (warmup=100, 1h) needs 100 base bars; (warmup=50, 4h) needs 200. The 4h
    strategy wins despite its SMALLER warmup — which is exactly the inversion the
    unscaled max(warmup) got wrong (it would have picked 100 and starved the 4h)."""
    strategies = [_StubStrategy(100, _1H), _StubStrategy(50, _4H)]

    assert derive_warmup_depth(strategies, base_timeframe=_1H) == 200


def test_derive_warmup_depth_without_base_timeframe_is_unchanged() -> None:
    """Backward compat: base_timeframe omitted -> the exact prior behaviour
    (unscaled max(s.warmup)), so no existing caller changes."""
    strategies = [_StubStrategy(100, _1H), _StubStrategy(50, _4H)]

    assert derive_warmup_depth(strategies) == 100


def test_derive_warmup_depth_empty_defaults_to_one() -> None:
    """The existing empty-set default (1) is preserved under the scaled path."""
    assert derive_warmup_depth([], base_timeframe=_1H) == 1


# --- register_strategy_warmup ------------------------------------------------


def test_register_strategy_warmup_registers_scaled_depth() -> None:
    """The registration seam threads base_timeframe through to the derivation:
    ONE StrategyWarmupConsumer whose required_history_depth is the SCALED depth,
    and feed.cache_capacity() then derives to it."""
    feed = _StubFeed()
    strategies = [_StubStrategy(100, _4H)]

    register_strategy_warmup(feed, strategies, base_timeframe=_1H)

    assert len(feed.consumers) == 1, "exactly one warmup consumer is registered"
    consumer = feed.consumers[0]
    assert isinstance(consumer, StrategyWarmupConsumer)
    assert consumer.required_history_depth == 400, "the depth is scaled to base bars"
    assert feed.cache_capacity() == 400, "cache_capacity() derives to the scaled depth"


# --- LiveBarFeed.base_timeframe ---------------------------------------------


def test_live_bar_feed_exposes_base_timeframe() -> None:
    """The public read accessor exists (the class docstring already documents
    base_timeframe as part of the public contract) and is read-only — it is what
    SessionInitializer reads to derive the ring depth in base-bar units."""
    from itrader.price_handler.feed.live_bar_feed import LiveBarFeed

    feed = LiveBarFeed(None, _1H)

    assert feed.base_timeframe == _1H
    with pytest.raises(AttributeError):
        feed.base_timeframe = _4H  # type: ignore[misc]

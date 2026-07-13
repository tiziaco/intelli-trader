"""Offline unit coverage for ``TestLiveDataProvider`` — the RELOCATED paper-path replay
fixture (TEST-01/D-18; formerly ``ReplayDataProvider`` in the ``itrader`` package).

Fully offline: drives the provider over the committed golden ``CsvPriceStore`` (no network,
no async, no wall-clock) and asserts the seam the Phase-3 ``LiveBarFeed`` depends on —
symbol/timeframe stamping (the symbol-form guard, D-12), the Decimal edge, the monotonic
epoch-ms bar-open ``ts`` grid (D-09), and the ``set_bar_sink``/``replay_bar`` push. The
provider left ``itrader/`` for ``tests/support/replay_harness`` (D-18); production paper
re-points to the OKX live feed (D-21), so this concretion is test-only now.

This directory is package-less (NO ``__init__.py``, per the two-same-named-top-level-package
collection hazard). No hand-added markers — the ``tests/unit/`` path auto-applies ``unit``.
Indentation is 4-SPACE (matched to the ``price_handler`` tree).
"""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import Callable

import pytest

from itrader.price_handler.providers.live_provider import LiveDataProvider
from itrader.price_handler.providers.okx_provider import ClosedBar
from tests.support.replay_harness import TestLiveDataProvider


@pytest.fixture(scope="module")
def provider() -> TestLiveDataProvider:
    """A default ``TestLiveDataProvider`` over the committed golden BTCUSD store (offline)."""
    return TestLiveDataProvider()


@pytest.fixture(scope="module")
def bars(provider: TestLiveDataProvider) -> list[ClosedBar]:
    """The full golden replay materialized once (module-scoped — one store read)."""
    return list(provider.iter_closed_bars())


def test_iter_stamps_universe_symbol_and_timeframe(bars: list[ClosedBar]) -> None:
    # D-12 symbol-form guard: a 'BTC/USDT' stamp would raise MissingPriceDataError deep in
    # the feed's window() — every bar MUST carry the universe-member form 'BTCUSD'/'1d'.
    assert len(bars) > 0
    assert all(cb["symbol"] == "BTCUSD" for cb in bars)
    assert all(cb["timeframe"] == "1d" for cb in bars)


def test_ohlcv_cross_the_decimal_edge(bars: list[ClosedBar]) -> None:
    # The Decimal edge is held at the provider: OHLCV are Decimal (never float).
    first = bars[0]
    assert isinstance(first["open"], Decimal)
    for cb in bars:
        assert isinstance(cb["open"], Decimal)
        assert isinstance(cb["high"], Decimal)
        assert isinstance(cb["low"], Decimal)
        assert isinstance(cb["close"], Decimal)
        assert isinstance(cb["volume"], Decimal)


def test_ts_is_strictly_increasing_epoch_ms(bars: list[ClosedBar]) -> None:
    # D-09: ts is a monotonic int epoch-ms bar-open grid (the parity anchor).
    stamps = [cb["ts"] for cb in bars]
    assert all(isinstance(t, int) for t in stamps)
    assert all(later > earlier for earlier, later in zip(stamps, stamps[1:]))


def test_set_bar_sink_and_replay_bar_deliver_in_order(
    provider: TestLiveDataProvider, bars: list[ClosedBar]
) -> None:
    # set_bar_sink + replay_bar deliver each bar to the registered sink, in order.
    received: list[ClosedBar] = []
    provider.set_bar_sink(received.append)
    handful = bars[:5]
    for cb in handful:
        provider.replay_bar(cb)
    assert received == handful


def test_replay_bar_without_sink_warns_and_drops(caplog: pytest.LogCaptureFixture) -> None:
    # No sink registered is a legitimate mis-wired state: WARN and drop, never raise.
    fresh = TestLiveDataProvider()
    synthetic: ClosedBar = {
        "ts": 1514764800000,
        "open": Decimal("13715.65"),
        "high": Decimal("13715.65"),
        "low": Decimal("13715.65"),
        "close": Decimal("13715.65"),
        "volume": Decimal("0.0"),
        "symbol": "BTCUSD",
        "timeframe": "1d",
    }
    with caplog.at_level(logging.WARNING):
        fresh.replay_bar(synthetic)  # must not raise
    assert "no bar sink registered" in caplog.text


# -- Uniform provider surface (VENUE-05 / D-10) -------------------------------


def test_replay_provider_is_a_uniform_live_data_provider(
    provider: TestLiveDataProvider,
) -> None:
    # Implements the no-op streaming seams inline AND keeps its real set_bar_sink →
    # structurally a LiveDataProvider (the runtime_checkable Protocol) so the
    # VenueLifecycle can wire it unconditionally with no venue branch.
    assert isinstance(provider, LiveDataProvider)


def test_replay_provider_inline_streaming_seams_are_noops(
    provider: TestLiveDataProvider,
) -> None:
    # Offline replay does not stream: the provider's own inline seams are safe
    # no-ops (no longer inherited) and the provider is trivially healthy.
    assert provider.set_global_queue(object()) is None
    assert provider.set_halt_signal(lambda reason: None) is None
    assert provider.set_stream_state_listener(lambda s: None, lambda s: None) is None
    assert provider.subscribe("BTCUSD") is None
    assert provider.unsubscribe("BTCUSD") is None
    assert provider.spawn_warmup("BTCUSD", "1d", 10) is None
    assert provider.is_streaming_healthy() is True

"""Smoke tests for the shared LiveBarFeed offline fixtures (Phase 3 / 03-01).

Exercises ``tests/unit/price/conftest.py`` so the fixtures have a green automated verify
rather than being collected-but-unexercised: the ``closed_bar`` factory shape + Decimal
edge, the ``closed_bar_sequence`` one-timeframe advance, and the ``stub_provider``
programmable backfill + captured-call log.
"""

from decimal import Decimal
from typing import Any, Callable

import pytest

from itrader.price_handler.providers.okx_provider import ClosedBar

pytestmark = pytest.mark.unit

_OHLCV_KEYS = ("open", "high", "low", "close", "volume")


def test_closed_bar_factory_shape_and_decimal_edge(
    closed_bar: Callable[..., ClosedBar],
) -> None:
    """The factory returns the full ClosedBar key set with Decimal (never float) OHLCV."""
    bar = closed_bar()
    assert set(bar) == {"ts", "symbol", "timeframe", *_OHLCV_KEYS}
    assert isinstance(bar["ts"], int)
    assert bar["symbol"] == "BTC-USDT"
    assert bar["timeframe"] == "1d"
    for key in _OHLCV_KEYS:
        assert isinstance(bar[key], Decimal)
        assert not isinstance(bar[key], float)


def test_closed_bar_factory_varies_only_ts(
    closed_bar: Callable[..., ClosedBar],
) -> None:
    """Passing just ts_ms keeps the deterministic defaults for everything else."""
    a = closed_bar()
    b = closed_bar(1704153600000)
    assert b["ts"] == 1704153600000
    assert a["ts"] != b["ts"]
    assert a["close"] == b["close"]  # defaults unchanged


def test_closed_bar_sequence_advances_one_timeframe(
    closed_bar_sequence: Callable[..., list[ClosedBar]],
) -> None:
    """N consecutive bars advance ts by exactly one timeframe (1d == 86_400_000 ms)."""
    bars = closed_bar_sequence(3)
    assert len(bars) == 3
    step = 86_400_000
    assert [b["ts"] for b in bars] == [
        bars[0]["ts"],
        bars[0]["ts"] + step,
        bars[0]["ts"] + 2 * step,
    ]
    assert {b["timeframe"] for b in bars} == {"1d"}


def test_stub_provider_returns_programmed_list_and_logs_call(
    stub_provider: Any,
    closed_bar_sequence: Callable[..., list[ClosedBar]],
) -> None:
    """The stub returns the per-test programmed list and records the call args."""
    programmed = closed_bar_sequence(2)
    stub_provider.backfill_bars = programmed

    got = stub_provider.fetch_ohlcv_backfill("BTC-USDT", "1d", since=1704067200000, limit=100)

    assert got == programmed
    assert stub_provider.calls == [
        {"symbol": "BTC-USDT", "timeframe": "1d", "since": 1704067200000, "limit": 100}
    ]


def test_stub_provider_empty_by_default(stub_provider: Any) -> None:
    """Un-programmed, the stub yields an empty backfill (no accidental live data)."""
    assert stub_provider.fetch_ohlcv_backfill("ETH-USDT", "1h") == []
    assert stub_provider.calls[-1]["symbol"] == "ETH-USDT"
    assert stub_provider.calls[-1]["limit"] == 1000

from datetime import datetime

import pandas as pd
import pytest

from itrader.events_handler.events import BarEvent


@pytest.fixture
def bar():
    bars = {
        "BTCUSDT": pd.DataFrame(
            {"open": [30], "high": [60], "low": [20], "close": [40], "volume": [1000]}
        )
    }
    return BarEvent(time=datetime(2024, 1, 1), bars=bars)


def test_get_last_high(bar):
    assert bar.get_last_high("BTCUSDT") == 60.0


def test_get_last_low(bar):
    assert bar.get_last_low("BTCUSDT") == 20.0


def test_missing_ticker_returns_none(bar):
    assert bar.get_last_high("ETHUSDT") is None
    assert bar.get_last_low("ETHUSDT") is None

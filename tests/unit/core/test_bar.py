"""Tests for the immutable Decimal Bar value object (M5-02, D-14/D-04).

Locks the contracts ``itrader/core/bar.py`` must satisfy:

1. Construction from kwargs carries Decimal OHLCV fields unchanged.
2. ``from_row`` on a pandas Series of float64 values yields
   ``Decimal(str(value))`` per field — the inertness argument (D-21):
   identical to the previous ``to_money(float)`` path, so downstream
   Decimals are bit-identical.
3. Micro-price precision survives: ``0.000005`` enters as exactly
   ``Decimal("0.000005")`` (renders as 5E-6 — compare with ``==``).
4. Frozen immutability: assignment raises ``FrozenInstanceError``.
5. ``slots=True``: setting an unknown attribute raises.
"""

import dataclasses
from datetime import datetime
from decimal import Decimal

import pandas as pd
import pytest

from itrader.core.bar import Bar

pytestmark = pytest.mark.unit


def _make_bar(**overrides):
    kwargs = dict(
        time=datetime(2024, 1, 1),
        open=Decimal("100.5"),
        high=Decimal("105.0"),
        low=Decimal("99.25"),
        close=Decimal("104.75"),
        volume=Decimal("12.5"),
    )
    kwargs.update(overrides)
    return Bar(**kwargs)


def test_construction_from_kwargs():
    bar = _make_bar()
    assert bar.time == datetime(2024, 1, 1)
    assert bar.open == Decimal("100.5")
    assert bar.high == Decimal("105.0")
    assert bar.low == Decimal("99.25")
    assert bar.close == Decimal("104.75")
    assert bar.volume == Decimal("12.5")


def test_from_row_pandas_series_float64_uses_str_path():
    # D-14: each float64 enters via Decimal(str(x)) — identical to the
    # to_money(float) path used before the cutover (D-21 inertness).
    row = pd.Series(
        {"open": 10.1, "high": 10.5, "low": 9.9, "close": 10.3, "volume": 3.7},
        dtype="float64",
    )
    bar = Bar.from_row(datetime(2024, 1, 1), row)
    assert bar.open == Decimal(str(10.1)) == Decimal("10.1")
    assert bar.high == Decimal(str(10.5)) == Decimal("10.5")
    assert bar.low == Decimal(str(9.9)) == Decimal("9.9")
    assert bar.close == Decimal(str(10.3)) == Decimal("10.3")
    assert bar.volume == Decimal(str(3.7)) == Decimal("3.7")
    # Decimal(float) would NOT round-trip exactly — the string path does.
    assert bar.open != Decimal(10.1)


def test_from_row_stamps_open_time():
    # D-04: the bar covering [T, T+tf) is stamped T.
    row = pd.Series({"open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0, "volume": 0.0})
    t = datetime(2024, 3, 15, 12, 0)
    assert Bar.from_row(t, row).time == t


def test_from_row_micro_price_precision():
    # Micro prices are never rounded to the cash quantum (D-14 companion
    # rule): 0.000005 enters as exactly Decimal("0.000005") (renders as
    # 5E-6 — compare with ==, not str).
    row = pd.Series(
        {
            "open": 0.000005,
            "high": 0.000005,
            "low": 0.000005,
            "close": 0.000005,
            "volume": 1.0,
        },
        dtype="float64",
    )
    bar = Bar.from_row(datetime(2024, 1, 1), row)
    assert bar.close == Decimal("0.000005")


def test_frozen_immutability():
    bar = _make_bar()
    with pytest.raises(dataclasses.FrozenInstanceError):
        bar.close = Decimal("1")  # type: ignore[misc]


def test_slots_rejects_unknown_attribute():
    bar = _make_bar()
    with pytest.raises((AttributeError, TypeError)):
        bar.not_a_field = 1  # type: ignore[attr-defined]

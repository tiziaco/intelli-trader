"""Hand-computed β-fit / z-score math for the ETH/BTC pair strategy (PAIR-01).

These are the D-11 hand-verified unit tests: the expected β and z values are
computed by an INLINE reference (numpy / statsmodels / pandas) right here — the
test is the oracle, NOT a value copied from a strategy run. They assert the pure
β/z helpers on the concrete reference strategy directly, with no engine wiring.

Selectors (06-VALIDATION.md): ``-k beta`` → ``test_beta_log_ols_fixture``;
``-k zscore`` → ``test_zscore_rolling_and_crossing``. Folder-derived ``unit``
marker only (tests/conftest.py). 4-SPACE indentation.

Design facts pinned here (the contract Task 2 implements):
- ``EthBtcPairStrategy._fit_beta(win_A, win_B)`` fits log-price OLS of A on B and
  returns the slope (a statsmodels float consumed downstream via ``to_money``).
- ``EthBtcPairStrategy._zscore(spread, lookback)`` returns the rolling z-score
  Series: ``(spread - spread.rolling(lookback).mean()) / spread.rolling(lookback).std()``
  (pandas default ``ddof=1``).
- ``EthBtcPairStrategy._crosses_into(prev_z, curr_z, threshold)`` is True only on
  the bar where ``|z|`` transitions from inside (``|prev| <= threshold``) to
  outside (``|curr| > threshold``); ``_crosses_inside`` is the mirror for exits.
"""

from decimal import Decimal

import numpy as np
import pandas as pd
import statsmodels.api as sm

from itrader.core.sizing import FractionOfCash, TradingDirection
from itrader.strategy_handler.strategies.eth_btc_pair_strategy import (
    EthBtcPairStrategy,
)


def _strategy() -> EthBtcPairStrategy:
    """A constructed strategy used purely to exercise the pure β/z helpers."""
    return EthBtcPairStrategy(
        timeframe="1d",
        tickers=["ETHUSD", "BTCUSD"],
        sizing_policy=FractionOfCash(Decimal("0.95")),
        direction=TradingDirection.LONG_SHORT,
    )


def _window(prices: list[float]) -> pd.DataFrame:
    """A completed-bar window with a single ``close`` column (feed shape)."""
    idx = pd.date_range("2021-01-01", periods=len(prices), freq="D")
    return pd.DataFrame({"close": prices}, index=idx)


def test_beta_log_ols_fixture() -> None:
    """log-OLS β on a fixture where log(A) = 1.0 + 0.5·log(B) recovers β = 0.5.

    The fixture is a PERFECT log-linear relation, so the OLS slope is exactly
    0.5 (within float tolerance). The inline statsmodels fit is the reference
    oracle — the strategy helper must reproduce it.
    """
    b_prices = [100.0, 110.0, 121.0, 133.1, 146.41, 161.05, 177.16, 194.87]
    log_b = np.log(np.array(b_prices, dtype=float))
    a_prices = list(np.exp(1.0 + 0.5 * log_b))  # log(A) = 1.0 + 0.5·log(B)

    win_a = _window(a_prices)
    win_b = _window(b_prices)

    # Inline reference (the oracle): log-OLS slope of A on B.
    x = sm.add_constant(log_b)
    expected_beta = float(sm.OLS(np.log(np.array(a_prices)), x).fit().params[1])

    strat = _strategy()
    beta = strat._fit_beta(win_a, win_b)

    assert expected_beta == 0.5 or abs(expected_beta - 0.5) < 1e-9
    assert abs(beta - 0.5) < 1e-9
    assert abs(beta - expected_beta) < 1e-12
    # β is a statsmodels float (consumed via to_money downstream — Pitfall 4).
    assert isinstance(beta, float)


def test_zscore_rolling_and_crossing() -> None:
    """Rolling z-score (ddof=1) at the last bar + crossing helpers on a fixture.

    Hand-built spread series; the last-bar rolling mean/std and z are computed
    inline (pandas ``rolling`` with the default ``ddof=1``) as the reference.
    The crossing helpers fire only on the transition bar.
    """
    spread = pd.Series([1.0, 2.0, 3.0, 2.0, 1.0, 0.0, -1.0, 5.0])
    lookback = 4

    # Inline reference: last window is [1, 0, -1, 5] → mean 1.25, std(ddof=1)
    # ≈ 2.62995564, z ≈ 1.42587956.
    last_window = np.array([1.0, 0.0, -1.0, 5.0])
    expected_mean = float(last_window.mean())          # 1.25
    expected_std = float(last_window.std(ddof=1))      # 2.6299556...
    expected_z = (5.0 - expected_mean) / expected_std  # 1.4258795...
    assert expected_mean == 1.25
    assert abs(expected_z - 1.4258795636800752) < 1e-12

    strat = _strategy()
    z_series = strat._zscore(spread, lookback)
    assert abs(float(z_series.iloc[-1]) - expected_z) < 1e-12
    # The first (lookback-1) entries are NaN (insufficient window).
    assert z_series.iloc[: lookback - 1].isna().all()

    # Crossing INTO the band at entry threshold 2.0: prev |z|<=2, curr |z|>2.
    assert strat._crosses_into(Decimal("1.5"), Decimal("2.5"), Decimal("2")) is True
    assert strat._crosses_into(Decimal("-1.0"), Decimal("-2.5"), Decimal("2")) is True
    # Stays inside → no entry crossing.
    assert strat._crosses_into(Decimal("0.5"), Decimal("1.5"), Decimal("2")) is False
    # Already outside on prev → not a fresh crossing.
    assert strat._crosses_into(Decimal("2.5"), Decimal("3.0"), Decimal("2")) is False

    # Crossing back INSIDE the band at exit threshold 0.5: prev |z|>=0.5, curr |z|<0.5.
    assert strat._crosses_inside(Decimal("1.0"), Decimal("0.3"), Decimal("0.5")) is True
    assert strat._crosses_inside(Decimal("-1.0"), Decimal("-0.2"), Decimal("0.5")) is True
    # Still outside → no exit crossing.
    assert strat._crosses_inside(Decimal("2.0"), Decimal("1.5"), Decimal("0.5")) is False
    # Already inside on prev → not a fresh crossing.
    assert strat._crosses_inside(Decimal("0.3"), Decimal("0.2"), Decimal("0.5")) is False

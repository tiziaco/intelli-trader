"""Hand-computed fixture tests for ``itrader.reporting.metrics`` (M5-09 / TC4, D-22).

Every expected value here is derived by hand (the arithmetic is spelled out in
comments or computed step-by-step with stdlib ``math``) so the fixtures are an
independent check on the D-16 formula pins:

* drawdown sign NEGATIVE (matching backtesting.py ``dd.min()`` where dd <= 0)
* ddof=1 (sample std — pinned explicitly; ``np.std`` defaults ddof=0)
* PERIODS = 365 (daily crypto bars; the old periods=355 died)
* risk_free_rate = 0

The frozen ``summary.json`` metrics block (plan 07-07 re-freeze) doubles as the
golden-level regression; these unit fixtures are the hand-verified layer (D-15/D-22).

The ``unit`` marker is folder-derived (tests/unit/) — not hand-added here.
"""

import inspect
import math

import numpy as np
import pandas as pd
import pytest

import itrader.reporting.metrics as metrics_module
from itrader.reporting.metrics import (
    PERIODS,
    cagr,
    compute_returns,
    format_metrics,
    max_drawdown,
    profit_factor,
    rolling_sharpe,
    sharpe,
    sortino,
    win_rate,
)


# --- The RESEARCH hand-computable fixture -----------------------------------
#
# Synthetic equity: 100 -> 110 -> 99 -> 121
#   returns : [0.0, 0.10, -0.10, 22/99 = 0.2222...]
#   cummax  : [100, 110, 110, 121]
#   drawdown: [0, 0, -0.10, 0]  ->  max_drawdown == -0.10 exactly
EQUITY = pd.Series([100.0, 110.0, 99.0, 121.0])

# The same return series computed BY HAND with stdlib floats (independent of
# pandas internals): r_t = p_t / p_{t-1} - 1, leading element filled with 0.0.
HAND_RETURNS = [0.0, 110.0 / 100.0 - 1.0, 99.0 / 110.0 - 1.0, 121.0 / 99.0 - 1.0]

# Trades fixture: realised pnl [+10, -5, +20]
#   gross profit = 30, gross loss = 5 -> profit factor 6.0
#   winners 2 of 3 -> win rate 2/3
TRADES = pd.DataFrame({"realised_pnl": [10.0, -5.0, 20.0]})
EMPTY_TRADES = pd.DataFrame({"realised_pnl": pd.Series(dtype=float)})


def test_periods_is_365():
    # D-16: annualization for daily crypto bars; periods=355 died with performance.py.
    assert PERIODS == 365


def test_compute_returns_matches_hand_fixture():
    returns = compute_returns(EQUITY)
    assert len(returns) == len(EQUITY)
    assert list(returns) == pytest.approx(HAND_RETURNS)
    # Leading element is filled with 0.0, never NaN.
    assert returns.iloc[0] == 0.0


def test_max_drawdown_hand_fixture():
    # cummax [100, 110, 110, 121]; trough 99/110 - 1 = -0.10 (NEGATIVE sign pin).
    assert max_drawdown(EQUITY) == pytest.approx(-0.10)


def test_max_drawdown_is_negative_convention():
    assert max_drawdown(EQUITY) < 0


def test_max_drawdown_empty_returns_zero():
    assert max_drawdown(pd.Series(dtype=float)) == 0.0


def test_max_drawdown_monotonic_equity_is_zero():
    assert max_drawdown(pd.Series([100.0, 110.0, 120.0])) == 0.0


def test_sharpe_hand_fixture():
    # Hand computation, step by step (ddof=1 sample std, rf=0, annualized sqrt(365)):
    #   mean = (0 + 0.10 - 0.0909... + 0.2222...) / 4
    #   var  = sum((r - mean)^2) / (n - 1)        # ddof=1
    #   sharpe = sqrt(365) * mean / sqrt(var)
    mean = sum(HAND_RETURNS) / 4
    var = sum((r - mean) ** 2 for r in HAND_RETURNS) / (4 - 1)
    expected = math.sqrt(365) * mean / math.sqrt(var)
    assert sharpe(compute_returns(EQUITY)) == pytest.approx(expected)


def test_sharpe_constant_series_returns_zero():
    # Zero std -> guarded denominator returns 0.0, no warning/raise.
    returns = compute_returns(pd.Series([100.0, 100.0, 100.0]))
    assert sharpe(returns) == 0.0


def test_sharpe_too_short_returns_zero():
    assert sharpe(pd.Series([0.1])) == 0.0
    assert sharpe(pd.Series(dtype=float)) == 0.0


def test_sortino_hand_fixture():
    # Textbook/backtesting.py downside deviation — FULL-period denominator, target 0:
    #   downside = sqrt(mean(clip(r, -inf, 0)^2))
    #            = sqrt((0^2 + 0^2 + (-0.0909..)^2 + 0^2) / 4)
    #   sortino  = sqrt(365) * mean / downside
    clipped = [min(r, 0.0) for r in HAND_RETURNS]
    downside = math.sqrt(sum(c**2 for c in clipped) / 4)
    mean = sum(HAND_RETURNS) / 4
    expected = math.sqrt(365) * mean / downside
    assert sortino(compute_returns(EQUITY)) == pytest.approx(expected)


def test_sortino_zero_downside_returns_zero():
    returns = compute_returns(pd.Series([100.0, 110.0, 121.0]))
    assert sortino(returns) == 0.0


def test_sortino_empty_returns_zero():
    # Guarded: np.mean of an empty slice would raise RuntimeWarning (suite-fatal).
    assert sortino(pd.Series(dtype=float)) == 0.0


def test_profit_factor_hand_fixture():
    # gross profit 30 / gross loss 5 == 6.0 (true PF — the count-ratio died).
    assert profit_factor(TRADES) == pytest.approx(6.0)


def test_profit_factor_all_winners_is_inf():
    all_winners = pd.DataFrame({"realised_pnl": [10.0, 20.0]})
    result = profit_factor(all_winners)  # must not raise (old code ZeroDivisionError'd)
    assert result == float("inf")


def test_profit_factor_all_losers_is_zero():
    all_losers = pd.DataFrame({"realised_pnl": [-10.0, -20.0]})
    assert profit_factor(all_losers) == 0.0


def test_profit_factor_empty_returns_zero():
    assert profit_factor(EMPTY_TRADES) == 0.0


def test_cagr_hand_fixture():
    # equity [100 -> 121] over 2 bars => years = 2/365
    #   cagr = (121/100) ** (1/years) - 1
    equity = pd.Series([100.0, 121.0])
    years = 2 / 365
    expected = (121.0 / 100.0) ** (1.0 / years) - 1.0
    assert cagr(equity) == pytest.approx(expected)


def test_cagr_empty_returns_zero():
    assert cagr(pd.Series(dtype=float)) == 0.0


def test_cagr_zero_start_returns_zero():
    assert cagr(pd.Series([0.0, 100.0])) == 0.0


def test_win_rate_hand_fixture():
    assert win_rate(TRADES) == pytest.approx(2.0 / 3.0)


def test_win_rate_empty_returns_zero():
    assert win_rate(EMPTY_TRADES) == 0.0


def test_rolling_sharpe_window():
    # D-18: one pure rolling expression — same length, NaN head (window-1 entries).
    returns = compute_returns(EQUITY)
    result = rolling_sharpe(returns, window=2)
    assert isinstance(result, pd.Series)
    assert len(result) == len(returns)
    assert math.isnan(result.iloc[0])
    # Window [0.0, 0.10]: mean 0.05, std(ddof=1) = sqrt(2*(0.05^2)) = 0.0707...
    w = [HAND_RETURNS[0], HAND_RETURNS[1]]
    mean = sum(w) / 2
    sd = math.sqrt(sum((r - mean) ** 2 for r in w) / (2 - 1))
    expected = math.sqrt(365) * mean / sd
    assert result.iloc[1] == pytest.approx(expected)


def test_rolling_sharpe_constant_returns_no_raise():
    # 0/0 windows yield NaN without raising under filterwarnings=error.
    returns = compute_returns(pd.Series([100.0, 100.0, 100.0]))
    result = rolling_sharpe(returns, window=2)
    assert len(result) == 3


def test_format_metrics_renders_names_and_values():
    block = format_metrics({"sharpe": 1.2345, "max_drawdown": -0.1})
    assert isinstance(block, str)
    assert "sharpe" in block
    assert "1.2345" in block
    assert "max_drawdown" in block
    assert "-0.1000" in block  # %.4f rendering
    assert "\n" in block  # multi-line block


def test_format_metrics_passes_inf_through():
    block = format_metrics({"profit_factor": float("inf")})
    assert "inf" in block


def test_metrics_module_is_pure_no_print():
    # format_metrics builds a string only — print/log decisions belong to callers.
    source = inspect.getsource(metrics_module)
    assert "print(" not in source


def test_metrics_module_imports_numpy_pandas_only():
    # D-14 anti-pattern guard: no itrader handler imports may reappear.
    source = inspect.getsource(metrics_module)
    for line in source.splitlines():
        stripped = line.strip()
        if stripped.startswith(("import ", "from ")):
            assert "itrader" not in stripped, f"forbidden itrader import: {stripped}"

"""Unit tests for the pure results serializers (RESULT-01, D-06/D-08/D-11/D-14).

Covers the five serializer functions in ``itrader.results.serializers``:

1. ``curate_run_settings`` — exact curated key set + ``{"type","params"}`` fee/slippage
   shape + the credential-leak guard (no ``database_url``/``password`` key, no
   ``SecretStr`` value) — T-02-03.
2. ``curate_portfolio_params`` — per-strategy windows + risk knobs, ``json.dumps``-safe.
3. ``build_aggregate_equity_curve`` — matched-timeframe exact sum + 1d/1h ffill (no NaN).
4. ``build_run_metrics`` — derived ``total_return == final/start - 1``.
5. ``annual_periods`` — 365 all-daily, finest periods-per-year for a mixed run.

Built on small in-line pandas frames + a duck-typed fake exchange — no DB, no engine
run. ``filterwarnings=["error"]`` must stay green (the RED-phase failures are
``NotImplementedError``/assertion, never warnings).

No ``__init__.py`` in this directory: ``tests/unit/`` is package-less (prepend import
mode), matching the sibling ``tests/unit/order`` / ``tests/unit/results`` convention.
"""

import json
from decimal import Decimal

import pandas as pd
import pytest

from itrader.config.order import OrderConfig
from itrader.core.enums import TradingDirection
from itrader.core.sizing import FractionOfCash
from itrader.results.records import METRIC_NAMES, RunMetrics
from itrader.results.serializers import (
    annual_periods,
    build_aggregate_equity_curve,
    build_run_metrics,
    curate_portfolio_params,
    curate_run_settings,
)
from itrader.strategy_handler.strategies.SMA_MACD_strategy import SMAMACDStrategy


# --- duck-typed fakes --------------------------------------------------------


class _FakeFeeModel:
    """A duck-typed fee model with public scalar params (mirrors PercentFeeModel)."""

    def __init__(self) -> None:
        self.fee_rate = Decimal("0.001")
        self.buy_rate = Decimal("0.001")
        self.sell_rate = Decimal("0.001")


class _FakeSlippageModel:
    """A duck-typed slippage model with a public scalar param."""

    def __init__(self) -> None:
        self.slippage_factor = Decimal("0.0")


class _FakeExchange:
    """A lightweight duck-typed exchange exposing only the curated-settings surface."""

    def __init__(self) -> None:
        self.fee_model = _FakeFeeModel()
        self.slippage_model = _FakeSlippageModel()
        self._min_order_size = Decimal("0.0001")
        self._max_order_size = Decimal("1000000")
        self._supported_symbols = {"ETHUSD", "BTCUSD"}
        self.simulate_failures = False
        self.failure_rate = 0.0


def _settings_kwargs() -> dict:
    return dict(
        tickers=["BTCUSD"],
        timeframe="1d",
        start_date="2020-01-01 00:00:00",
        end_date="2021-01-01 00:00:00",
        starting_cash=Decimal("100000"),
        rng_seed=42,
    )


def _sma_strategy() -> SMAMACDStrategy:
    return SMAMACDStrategy(
        timeframe="1d",
        tickers=["BTCUSD"],
        sizing_policy=FractionOfCash(Decimal("0.95")),
        direction=TradingDirection.LONG_ONLY,
        allow_increase=False,
    )


# --- (1) curated run settings -----------------------------------------------

_EXPECTED_SETTINGS_KEYS = {
    "tickers",
    "timeframe",
    "start_date",
    "end_date",
    "starting_cash",
    "rng_seed",
    "fee_model",
    "slippage_model",
    "market_execution",
    "min_order_size",
    "max_order_size",
    "supported_symbols",
    "simulate_failures",
    "failure_rate",
}


def test_curate_run_settings_exact_key_set() -> None:
    settings = curate_run_settings(
        _FakeExchange(), OrderConfig.default(), **_settings_kwargs())
    assert set(settings) == _EXPECTED_SETTINGS_KEYS


def test_curate_run_settings_model_envelope_shape() -> None:
    settings = curate_run_settings(
        _FakeExchange(), OrderConfig.default(), **_settings_kwargs())
    for key in ("fee_model", "slippage_model"):
        envelope = settings[key]
        assert set(envelope) == {"type", "params"}
        assert isinstance(envelope["type"], str)
        assert isinstance(envelope["params"], dict)
    # fee model type name + a float-narrowed param (Decimal must not survive).
    assert settings["fee_model"]["type"] == "_FakeFeeModel"
    assert settings["fee_model"]["params"]["fee_rate"] == 0.001
    assert isinstance(settings["fee_model"]["params"]["fee_rate"], float)


def test_curate_run_settings_scalar_values() -> None:
    settings = curate_run_settings(
        _FakeExchange(), OrderConfig.default(), **_settings_kwargs())
    assert settings["tickers"] == ["BTCUSD"]
    assert settings["timeframe"] == "1d"
    assert settings["starting_cash"] == 100000.0
    assert isinstance(settings["starting_cash"], float)
    assert settings["rng_seed"] == 42
    assert settings["market_execution"] == "immediate"
    assert settings["min_order_size"] == 0.0001
    assert settings["max_order_size"] == 1000000.0
    # supported_symbols is sorted for determinism.
    assert settings["supported_symbols"] == ["BTCUSD", "ETHUSD"]
    assert settings["simulate_failures"] is False
    assert settings["failure_rate"] == 0.0


def test_curate_run_settings_is_json_safe() -> None:
    settings = curate_run_settings(
        _FakeExchange(), OrderConfig.default(), **_settings_kwargs())
    # json.dumps succeeds → no Decimal/SecretStr/datetime leaked.
    json.dumps(settings)


def test_curate_run_settings_no_credentials() -> None:
    settings = curate_run_settings(
        _FakeExchange(), OrderConfig.default(), **_settings_kwargs())
    serialized = json.dumps(settings).lower()
    assert "database_url" not in serialized
    assert "password" not in serialized
    assert "secret" not in serialized
    # No key (at any nesting) named like a credential.
    assert "database_url" not in settings
    assert "password" not in settings


# --- (2) per-strategy params -------------------------------------------------


def test_curate_portfolio_params_single_strategy_keys() -> None:
    params = curate_portfolio_params([_sma_strategy()])
    for key in ("strategy_name", "fast_window", "slow_window", "signal_window",
                "direction", "sizing_policy"):
        assert key in params
    assert params["strategy_name"] == "SMA_MACD"
    assert params["fast_window"] == 6
    assert params["slow_window"] == 12
    assert params["signal_window"] == 3


def test_curate_portfolio_params_is_json_safe() -> None:
    params = curate_portfolio_params([_sma_strategy()])
    json.dumps(params)  # must not raise


def test_curate_portfolio_params_multi_strategy_wraps() -> None:
    params = curate_portfolio_params([_sma_strategy(), _sma_strategy()])
    assert set(params) == {"strategies"}
    assert len(params["strategies"]) == 2
    assert params["strategies"][0]["strategy_name"] == "SMA_MACD"


# --- (3) aggregate equity curve ----------------------------------------------


def _equity_frame(timestamps: list[str], values: list[float]) -> pd.DataFrame:
    return pd.DataFrame({
        "timestamp": pd.to_datetime(timestamps),
        "total_equity": [float(v) for v in values],
    })


def test_aggregate_curve_matched_timeframes_exact_sum() -> None:
    ts = ["2020-01-01", "2020-01-02", "2020-01-03"]
    f1 = _equity_frame(ts, [100.0, 110.0, 120.0])
    f2 = _equity_frame(ts, [200.0, 190.0, 210.0])
    aggregate = build_aggregate_equity_curve([f1, f2])
    assert list(aggregate.values) == [300.0, 300.0, 330.0]


def test_aggregate_curve_single_frame_is_itself() -> None:
    ts = ["2020-01-01", "2020-01-02"]
    f1 = _equity_frame(ts, [100.0, 105.0])
    aggregate = build_aggregate_equity_curve([f1])
    assert list(aggregate.values) == [100.0, 105.0]


def test_aggregate_curve_mixed_timeframe_ffill_no_nan() -> None:
    # A coarse 1d series and a fine (intraday) series over the same span.
    daily = _equity_frame(
        ["2020-01-01 00:00:00", "2020-01-02 00:00:00"], [100.0, 110.0])
    hourly = _equity_frame(
        ["2020-01-01 00:00:00", "2020-01-01 12:00:00", "2020-01-02 00:00:00"],
        [50.0, 55.0, 60.0])
    aggregate = build_aggregate_equity_curve([daily, hourly])
    # Union index size == 3 (the fine grid), no row dropped, no NaN.
    assert len(aggregate) == 3
    assert not aggregate.isna().any()
    # Leading region of the coarse series = its first observed value (100) — the
    # 12:00 bar carries the daily 100 forward and sums with the hourly 55.
    assert aggregate.iloc[1] == 100.0 + 55.0


# --- (4) RunMetrics builder --------------------------------------------------


def _trades_frame(pnls: list[float]) -> pd.DataFrame:
    return pd.DataFrame({"realised_pnl": [float(p) for p in pnls]})


def test_build_run_metrics_returns_all_eleven() -> None:
    equity = _equity_frame(
        ["2020-01-01", "2020-01-02", "2020-01-03"], [100.0, 110.0, 120.0])
    trades = _trades_frame([10.0, -5.0, 15.0])
    metrics = build_run_metrics(equity, trades)
    assert isinstance(metrics, RunMetrics)
    for name in METRIC_NAMES:
        assert isinstance(getattr(metrics, name), float)


def test_build_run_metrics_derived_total_return() -> None:
    equity = _equity_frame(["2020-01-01", "2020-01-02"], [100.0, 150.0])
    trades = _trades_frame([50.0])
    metrics = build_run_metrics(equity, trades)
    assert metrics.total_return == pytest.approx(150.0 / 100.0 - 1.0)
    assert metrics.final_equity == 150.0
    assert metrics.total_realised_pnl == 50.0
    assert metrics.trade_count == 1.0


# --- (5) annualization basis -------------------------------------------------


def test_annual_periods_all_daily() -> None:
    assert annual_periods(["1d", "1d"]) == 365


def test_annual_periods_mixed_uses_finest() -> None:
    assert annual_periods(["1d", "1h"]) == round(31_536_000 / 3600)


def test_annual_periods_empty_defaults_to_365() -> None:
    assert annual_periods([]) == 365

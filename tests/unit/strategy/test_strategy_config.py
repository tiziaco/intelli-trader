"""HARD-01 / HARD-02 strategy-config validation tests (Plan 05-01, D-01..D-06).

Covers the engine-facing declaration contract (BaseStrategyConfig) and the
per-strategy params subclass (SMA_MACDConfig): fail-loud pydantic validation at
construction (positivity, cross-field short<long, timeframe vocabulary), frozen
immutability (D-03), and the queryable snapshot under arbitrary_types_allowed
(D-05 / SIG-02). These are leaf contracts — nothing is wired into base.py or the
handler yet (Plan 02), so the oracle is dark.
"""

from decimal import Decimal

import pytest
from pydantic import ValidationError

from itrader.core.enums import OrderType, TradingDirection, Timeframe
from itrader.core.sizing import FractionOfCash
from itrader.config import BaseStrategyConfig
from itrader.strategy_handler.strategies.empty_strategy import EmptyStrategyConfig
from itrader.strategy_handler.strategies.SMA_MACD_strategy import SMA_MACDConfig


def _golden_sizing() -> FractionOfCash:
    """The golden string-path Decimal literal (Pitfall 1 — byte-exact)."""
    return FractionOfCash(Decimal("0.95"))


def test_sma_macd_config_defaults_construct() -> None:
    """SMA_MACDConfig with default params carries the golden declarations."""
    cfg = SMA_MACDConfig(
        timeframe="1d",
        tickers=["BTCUSD"],
        sizing_policy=_golden_sizing(),
    )
    assert cfg.timeframe is Timeframe.D1
    assert cfg.short_window == 50
    assert cfg.long_window == 100
    assert cfg.fast_window == 6
    assert cfg.slow_window == 12
    assert cfg.signal_window == 3
    assert cfg.order_type is OrderType.MARKET
    assert cfg.direction is TradingDirection.LONG_ONLY
    assert cfg.allow_increase is False
    assert cfg.sizing_policy == FractionOfCash(Decimal("0.95"))


def test_short_window_ge_long_window_raises() -> None:
    """short_window >= long_window is a cross-field violation (HARD-02)."""
    with pytest.raises(ValidationError):
        SMA_MACDConfig(
            timeframe="1d",
            tickers=["BTCUSD"],
            sizing_policy=_golden_sizing(),
            short_window=100,
            long_window=50,
        )


def test_non_positive_window_raises() -> None:
    """A zero/negative window violates Field(gt=0) positivity (HARD-02)."""
    with pytest.raises(ValidationError):
        SMA_MACDConfig(
            timeframe="1d",
            tickers=["BTCUSD"],
            sizing_policy=_golden_sizing(),
            short_window=0,
        )


def test_invalid_timeframe_raises() -> None:
    """An unsupported timeframe string is rejected at the boundary (HARD-01)."""
    with pytest.raises(ValidationError):
        BaseStrategyConfig(
            timeframe="3mo",
            tickers=["BTCUSD"],
            sizing_policy=_golden_sizing(),
        )


def test_config_is_frozen() -> None:
    """A constructed config is immutable (frozen=True, D-03)."""
    cfg = SMA_MACDConfig(
        timeframe="1d",
        tickers=["BTCUSD"],
        sizing_policy=_golden_sizing(),
    )
    with pytest.raises(ValidationError):
        cfg.short_window = 10  # type: ignore[misc]


def test_model_dump_recurses_into_sizing() -> None:
    """model_dump() recurses into the frozen sizing dataclass (SIG-02 snapshot)."""
    cfg = SMA_MACDConfig(
        timeframe="1d",
        tickers=["BTCUSD"],
        sizing_policy=_golden_sizing(),
    )
    dumped = cfg.model_dump()
    assert isinstance(dumped["sizing_policy"], dict)
    assert dumped["sizing_policy"]["fraction"] == Decimal("0.95")


def test_empty_strategy_config_constructs() -> None:
    """EmptyStrategyConfig is a no-extra-params BaseStrategyConfig subclass."""
    cfg = EmptyStrategyConfig(
        timeframe="1d",
        tickers=["BTCUSD"],
        sizing_policy=_golden_sizing(),
    )
    assert isinstance(cfg, BaseStrategyConfig)
    assert cfg.timeframe is Timeframe.D1

"""Contract tests for ``StrategiesHandler.update_config`` (D-09, COMP-02).

The handler's NON-config-model ``update_config`` (D-09 forbids a
``StrategiesHandlerConfig``): a PINNED dict shape keyed by ``strategy.name``,
each value forwarded verbatim as ``reconfigure(**value)`` to that named
strategy — re-applying params, re-validating, re-running ``init()`` and
re-deriving warmup/max_window (consuming Phase 2's idempotent ``reconfigure``
+ Phase 3's auto-warmup). The single-catch error contract (D-08) wraps every
failure into ``core.ConfigurationError``.

Covered behaviors:

- pinned shape: ``update_config({name: {"long_window": ...}})`` re-applies to
  THAT strategy and re-derives its warmup/max_window from the new declaration;
- an unknown strategy-name key raises ``ConfigurationError`` (config_key =
  the unknown name) — the shape is ENFORCED, not silently skipped;
- an unknown PARAM inside the inner dict surfaces as ``ConfigurationError``
  (the base ``UnknownParamError`` wrapped — single-catch contract, D-08);
- a valid reconfigure is idempotent — re-running with the same params yields
  the same warmup (Phase 2/3 idempotency).
"""

from decimal import Decimal
from queue import Queue

import pytest

from itrader.core.exceptions import ConfigurationError
from itrader.core.sizing import FractionOfCash, TradingDirection
from itrader.strategy_handler.storage import InMemorySignalStore
from itrader.strategy_handler.strategies.SMA_MACD_strategy import SMAMACDStrategy
from itrader.strategy_handler.strategies_handler import StrategiesHandler

pytestmark = pytest.mark.unit


def _sma_kwargs() -> dict:
    """Golden SMA_MACD construction kwargs (warmup auto-derives to 100)."""
    return dict(
        timeframe="1d",
        tickers=["BTCUSDT"],
        sizing_policy=FractionOfCash(Decimal("0.95")),
        direction=TradingDirection.LONG_ONLY,
        allow_increase=False,
    )


class _StubFeed:
    """A minimal BarFeed stand-in — update_config never touches the feed."""

    def symbols(self) -> list[str]:
        return ["BTCUSDT"]


def _make_handler() -> StrategiesHandler:
    return StrategiesHandler(Queue(), _StubFeed(), InMemorySignalStore())


def test_update_config_reconfigures_named_strategy_and_rederives_warmup():
    """PINNED SHAPE: a name-keyed kwargs dict re-applies to THAT strategy.

    SMA_MACD warmup auto-derives to 100 (= max(SMA50, SMA100, MACDHist15)).
    Reconfiguring long_window=60 (and a complementary short_window) re-runs
    init() and re-derives warmup/max_window to max(50, 60, 15) == 60.
    """
    handler = _make_handler()
    strategy = SMAMACDStrategy(**_sma_kwargs())
    handler.add_strategy(strategy)
    assert strategy.warmup == 100
    assert strategy.max_window == 100

    handler.update_config({strategy.name: {"short_window": 40, "long_window": 60}})

    assert strategy.short_window == 40
    assert strategy.long_window == 60
    # warmup/max_window re-derived from the new declared indicators.
    assert strategy.warmup == 60
    assert strategy.max_window == 60


def test_unknown_strategy_name_raises_configuration_error():
    """A key matching no managed strategy's .name raises ConfigurationError."""
    handler = _make_handler()
    handler.add_strategy(SMAMACDStrategy(**_sma_kwargs()))

    with pytest.raises(ConfigurationError) as exc:
        handler.update_config({"NoSuchStrategy": {"short_window": 5}})

    assert exc.value.config_key == "NoSuchStrategy"


def test_unknown_param_inside_inner_dict_surfaces_as_configuration_error():
    """An unknown param inside the inner dict wraps into ConfigurationError (D-08)."""
    handler = _make_handler()
    strategy = SMAMACDStrategy(**_sma_kwargs())
    handler.add_strategy(strategy)

    with pytest.raises(ConfigurationError) as exc:
        handler.update_config({strategy.name: {"bogus_param": 1}})

    assert exc.value.config_key == strategy.name


def test_valid_reconfigure_is_idempotent():
    """Re-running with the same params yields the same warmup (Phase 2/3)."""
    handler = _make_handler()
    strategy = SMAMACDStrategy(**_sma_kwargs())
    handler.add_strategy(strategy)

    handler.update_config({strategy.name: {"short_window": 40, "long_window": 60}})
    warmup_first = strategy.warmup
    handler.update_config({strategy.name: {"short_window": 40, "long_window": 60}})

    assert strategy.warmup == warmup_first == 60

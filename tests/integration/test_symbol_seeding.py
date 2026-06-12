"""Construction-time symbol-set seeding integration test (D-13, Trap 1).

Pins the PATTERNS-A2 replacement-safe seeding: after ``build_backtest_system(spec)``
the SimulatedExchange's ``_supported_symbols`` equals the COMPLETE union
``default preset ∪ {BTCUSD} ∪ spec tickers`` — the full set seeded at construction
(NOT relying on an additive ``register_symbol`` that a later ``update_config``
re-derivation would wipe).

The exchange is inspected directly off the built holder; no run is required (the
symbol set is fixed at construction).

Indentation: 4 SPACES (``tests/`` convention).
"""

import pytest

from itrader.config import get_exchange_preset
from itrader.trading_system.backtest_trading_system import build_backtest_system
from itrader.trading_system.system_spec import SystemSpec

pytestmark = pytest.mark.integration


_DEFAULT_PRESET = set(get_exchange_preset("default").limits.supported_symbols)
#: The committed golden BTCUSD dataset.
_GOLDEN_CSV = "data/BTCUSD_1d_ohlcv_2018_2026.csv"


def _btcusd_spec() -> SystemSpec:
    """A minimal single-ticker (BTCUSD) spec — no strategies/portfolios needed."""
    return SystemSpec(
        start="2018-01-01",
        end="2026-06-03",
        timeframe="1d",
        ticker="BTCUSD",
        starting_cash=10_000,
        data={"BTCUSD": _GOLDEN_CSV},
        strategies=[],
        portfolios=[],
    )


def test_btcusd_spec_seeds_default_preset_union_btcusd():
    """A BTCUSD-only spec seeds default preset ∪ {BTCUSD} exactly (Trap 1)."""
    system = build_backtest_system(_btcusd_spec())
    exchange = system.execution_handler.exchanges["simulated"]
    expected = _DEFAULT_PRESET | {"BTCUSD"}
    assert exchange._supported_symbols == expected


def test_spec_tickers_are_unioned_upper_cased():
    """Extra spec data tickers fold into the supported set, upper-cased (Trap 1)."""
    spec = SystemSpec(
        start="2018-01-01",
        end="2026-06-03",
        timeframe="1d",
        ticker="BTCUSD",
        starting_cash=10_000,
        # A lower-cased extra ticker proves the upper-casing + the union.
        data={"BTCUSD": _GOLDEN_CSV, "ethusd": "data/ETHUSD_1d_ohlcv.csv"},
        strategies=[],
        portfolios=[],
    )
    system = build_backtest_system(spec)
    exchange = system.execution_handler.exchanges["simulated"]
    expected = _DEFAULT_PRESET | {"BTCUSD", "ETHUSD"}
    assert exchange._supported_symbols == expected


def test_seeded_set_is_replacement_safe_against_update_config():
    """The seeded set survives an unrelated update_config (replacement-safe, Trap 1).

    ``update_config`` re-derives ``_supported_symbols`` from ``config.limits`` by
    REPLACEMENT. Because the COMPLETE set was folded into the config at
    construction, a config swap that does NOT touch symbols leaves the full union
    intact — never silently dropping BTCUSD.
    """
    system = build_backtest_system(_btcusd_spec())
    exchange = system.execution_handler.exchanges["simulated"]
    expected = _DEFAULT_PRESET | {"BTCUSD"}
    # A fee-only reconfigure re-runs the limits re-derivation path off config.limits.
    exchange.update_config(supported_symbols=exchange.config.limits.supported_symbols)
    assert exchange._supported_symbols == expected
    assert "BTCUSD" in exchange._supported_symbols

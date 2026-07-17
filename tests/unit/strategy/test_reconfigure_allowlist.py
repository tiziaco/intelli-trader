"""D-15/F-1/D-17 reconfigure allowlist — immutable / verb-only / mutable partitions.

The D-15 mutability contract. ``reconfigure`` MUTATES the authoring surface, but three closed
sets are refused loudly BEFORE any throwaway is built: ``strategy_type`` and ``name`` are
IMMUTABLE (identity — the store PK; changing them is ``remove`` + ``add``, audit 10-08 F2), and
``tickers`` is VERB-ONLY (``add_ticker``/``remove_ticker`` own it). Everything else is mutable,
including ``direction`` — but ``direction`` re-runs the SHORT-01/D-07 two-flag registration gate
(audit 10-08 F1: ``validate()`` does NOT check direction, so the gate is factored into a shared
handler predicate and called from the reconfigure apply path, NOT from ``Strategy.validate()``).

``timeframe`` is CONSTRAINED-mutable (D-15/F-1): coarser-or-equal whole multiples within ring
capacity are accepted; finer-than-base and over-capacity are loud rejects (the fixed-maxlen ring
cannot resize). NB: the ``Timeframe`` vocab (1m/5m/15m/1h/4h/1d/1w) has NO coarser NON-multiple
pair, so the non-multiple reject is unreachable via a valid alias; the reachable analog — an
UNKNOWN alias — is tested instead.

A ``PairStrategy`` refuses reconfigure entirely (D-17, via the Plan 06 ``_PAIR_REFUSED_VERBS``
guard). Assertions read STATE + the STORE, never log capture. NO ``__init__.py`` in this dir.
"""

from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from queue import Queue
from typing import Any, Iterator

import pandas as pd
import pytest

from itrader.config.sql import SqlSettings
from itrader.core.bar import Bar
from itrader.core.enums import TradingDirection
from itrader.events_handler.events import StrategyCommandEvent
from itrader.storage import SqlEngine
from itrader.storage.strategy_registry_store import StrategyRegistryStore
from itrader.strategy_handler.storage import InMemorySignalStore
from itrader.strategy_handler.strategies.eth_btc_pair_strategy import EthBtcPairStrategy
from itrader.strategy_handler.strategies.SMA_MACD_strategy import SMAMACDStrategy
from itrader.strategy_handler.strategies_handler import StrategiesHandler
from tests.support.schema import provision_schema
from tests.support.strategy_catalog import test_catalog

pytestmark = pytest.mark.unit

_T = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
_TICKER = "BTCUSD"
_NAME = "SMA_MACD"


class _StubFeed:
    """Backtest-shaped feed — no ``base_timeframe`` -> the timeframe gate skips cleanly."""

    def symbols(self) -> list[str]:
        return [_TICKER]

    def window(self, ticker, timeframe, max_window, asof):  # type: ignore[no-untyped-def]
        return pd.DataFrame(
            {"open": [], "high": [], "low": [], "close": [], "volume": []},
            index=pd.DatetimeIndex([], tz="UTC"),
        )


class _RingFeed(_StubFeed):
    """A live-shaped feed carrying ``base_timeframe`` + a fixed ring ``cache_capacity``."""

    def __init__(self, base_timeframe: timedelta, capacity: int) -> None:
        self.base_timeframe = base_timeframe
        self._capacity = capacity

    def cache_capacity(self) -> int:
        return self._capacity


@pytest.fixture()
def store() -> Iterator[StrategyRegistryStore]:
    registry = StrategyRegistryStore(SqlEngine(SqlSettings.default()))
    provision_schema(registry.backend)
    try:
        yield registry
    finally:
        registry.dispose()


def _bar(price: float, *, offset: int = 0) -> Bar:
    stamp = datetime(2020, 1, 1, tzinfo=timezone.utc) + timedelta(days=offset)
    return Bar(
        time=stamp, open=Decimal(str(price)), high=Decimal(str(price)),
        low=Decimal(str(price)), close=Decimal(str(price)), volume=Decimal("1"))


def _warm(strategy: SMAMACDStrategy, ticker: str = _TICKER, n: int = 105) -> None:
    for i in range(n):
        strategy.update(ticker, _bar(100 + i, offset=i))


def _handler(
    registry: Any,
    *,
    feed: Any = None,
    allow_short: bool = False,
    margin: bool = False,
    timeframe: str = "1d",
) -> tuple[StrategiesHandler, SMAMACDStrategy]:
    handler = StrategiesHandler(
        Queue(), feed if feed is not None else _StubFeed(), InMemorySignalStore(),
        allow_short_selling=allow_short, enable_margin=margin)
    handler.registry_store = registry
    handler.strategy_catalog = test_catalog()
    strategy = SMAMACDStrategy(timeframe=timeframe, tickers=[_TICKER])
    handler.add_strategy(strategy)
    return handler, strategy


def _reconfigure(handler: StrategiesHandler, config: dict[str, Any], name: str = _NAME) -> None:
    handler.on_strategy_command(
        StrategyCommandEvent.reconfigure(strategy_name=name, config=config, time=_T))


# --- D-15 immutable (identity) ---------------------------------------------

def test_strategy_type_is_immutable(store: StrategyRegistryStore) -> None:
    """Test 12 (D-15) — a ``strategy_type`` reconfigure is a loud reject; nothing mutates."""
    handler, strategy = _handler(store)
    _warm(strategy)

    _reconfigure(handler, {"strategy_type": "EmptyStrategy"})

    assert type(strategy).__name__ == "SMAMACDStrategy"
    assert store.get(_NAME) is None


def test_name_is_immutable_cannot_orphan_the_store_pk(store: StrategyRegistryStore) -> None:
    """Audit 10-08 F2 — a ``name`` reconfigure is refused: renaming would ORPHAN the PK row."""
    handler, strategy = _handler(store)
    _warm(strategy)

    _reconfigure(handler, {"name": "renamed"})

    assert strategy.name == _NAME, "name is the durable identity — reconfigure cannot change it"
    assert store.get(_NAME) is None
    assert store.get("renamed") is None, "no orphan row is created under a new PK"


# --- D-15 verb-only ---------------------------------------------------------

def test_tickers_is_verb_only(store: StrategyRegistryStore) -> None:
    """Test 13 (D-15) — a ``tickers`` reconfigure is a loud reject naming the dedicated verbs."""
    handler, strategy = _handler(store)
    _warm(strategy)

    _reconfigure(handler, {"tickers": ["ETHUSD"]})

    assert strategy.tickers == [_TICKER]
    assert store.get(_NAME) is None


# --- D-15 mutable set -------------------------------------------------------

def test_mutable_set_reconfigures_and_persists(store: StrategyRegistryStore) -> None:
    """Test 14 (D-15) — ``sizing_policy``/``allow_increase``/``max_positions``/windows mutate."""
    handler, strategy = _handler(store)
    _warm(strategy)

    _reconfigure(handler, {"allow_increase": True, "max_positions": 4, "short_window": 20})

    assert strategy.allow_increase is True
    assert strategy.max_positions == 4
    assert strategy.short_window == 20
    row = store.get(_NAME)
    assert row is not None
    assert row["config"]["max_positions"] == 4


def test_direction_to_short_rejected_without_short_flags(store: StrategyRegistryStore) -> None:
    """Test 15a (D-15/F1) — ``direction`` re-runs SHORT-01: rejected with the flags off.

    The audit's most dangerous fix: ``validate()`` does NOT check direction, so the trial
    construction cannot catch a short-enabling change. The shared handler predicate rejects it.
    """
    handler, strategy = _handler(store, allow_short=False, margin=False)
    _warm(strategy)

    _reconfigure(handler, {"direction": "SHORT_ONLY"})

    assert strategy.direction is TradingDirection.LONG_ONLY, (
        "a short direction must be refused on a no-margin engine — the SHORT-01 gate")
    assert store.get(_NAME) is None


def test_direction_to_short_accepted_with_both_flags(store: StrategyRegistryStore) -> None:
    """Test 15b (D-15/F1) — a short direction IS admitted when both flags are on."""
    handler, strategy = _handler(store, allow_short=True, margin=True)
    _warm(strategy)

    _reconfigure(handler, {"direction": "SHORT_ONLY"})

    assert strategy.direction is TradingDirection.SHORT_ONLY
    row = store.get(_NAME)
    assert row is not None
    assert row["config"]["direction"] == "SHORT_ONLY"


# --- D-15/F-1 timeframe constrained-mutable --------------------------------

def test_timeframe_to_base_cadence_is_accepted_and_reaches_warm(
    store: StrategyRegistryStore,
) -> None:
    """Test 16 (D-15/F-1) — a coarser->base whole-multiple within capacity is accepted + warmable.

    Driven all the way to ``is_ready`` so the F-1 never-warm defect cannot pass this test.
    """
    feed = _RingFeed(base_timeframe=timedelta(hours=1), capacity=500)
    handler, strategy = _handler(store, feed=feed, timeframe="4h")

    _reconfigure(handler, {"timeframe": "1h"})  # exactly the base cadence, multiple 1

    assert strategy.timeframe == timedelta(hours=1)
    # Re-warm from a contiguous window: feed warmup bars and confirm it actually reaches ready.
    for i in range(105):
        strategy.update(_TICKER, _bar(200 + i, offset=i))
    assert strategy.is_ready(_TICKER) is True


def test_timeframe_finer_than_base_is_rejected(store: StrategyRegistryStore) -> None:
    """Test 17 (D-15/F-1) — a finer-than-base timeframe is a loud reject (unwarmable)."""
    feed = _RingFeed(base_timeframe=timedelta(hours=1), capacity=500)
    handler, strategy = _handler(store, feed=feed, timeframe="4h")

    _reconfigure(handler, {"timeframe": "15m"})  # finer than the 1h base

    assert strategy.timeframe == timedelta(hours=4), "the live timeframe is untouched"
    assert store.get(_NAME) is None


def test_timeframe_unknown_alias_is_rejected(store: StrategyRegistryStore) -> None:
    """Test 18 (D-15) — an unknown/unsupported timeframe alias is a loud reject.

    The reachable analog of the non-multiple reject: the ``Timeframe`` vocab has no coarser
    non-multiple pair, so a non-multiple can only arrive as an UNKNOWN alias, which the trial
    construction rejects at ``Timeframe`` coercion.
    """
    feed = _RingFeed(base_timeframe=timedelta(hours=1), capacity=500)
    handler, strategy = _handler(store, feed=feed, timeframe="4h")

    _reconfigure(handler, {"timeframe": "2h"})  # not in the Timeframe vocabulary

    assert strategy.timeframe == timedelta(hours=4)
    assert store.get(_NAME) is None


def test_timeframe_over_ring_capacity_is_rejected_boundary(store: StrategyRegistryStore) -> None:
    """Test 19 (F-1) — a depth over ring capacity is a loud reject; at-capacity is accepted.

    SMA_MACD warmup == 100; a 1h->4h reconfigure needs ``100 * 4 == 400`` base bars. Pin the
    boundary from both sides: capacity 400 accepts, capacity 399 rejects.
    """
    # Exactly-at-capacity -> accepted.
    feed_ok = _RingFeed(base_timeframe=timedelta(hours=1), capacity=400)
    handler_ok, strategy_ok = _handler(store, feed=feed_ok, timeframe="1h")
    _reconfigure(handler_ok, {"timeframe": "4h"})
    assert strategy_ok.timeframe == timedelta(hours=4), "at-capacity must be accepted"

    # One over capacity -> rejected. A distinct store row per handler (same PK) is fine: the
    # second handler's strategy is a separate object; assert against its live state.
    feed_over = _RingFeed(base_timeframe=timedelta(hours=1), capacity=399)
    handler_over = StrategiesHandler(
        Queue(), feed_over, InMemorySignalStore())
    handler_over.registry_store = None
    handler_over.strategy_catalog = test_catalog()
    strategy_over = SMAMACDStrategy(timeframe="1h", tickers=[_TICKER])
    handler_over.add_strategy(strategy_over)
    handler_over.on_strategy_command(
        StrategyCommandEvent.reconfigure(strategy_name=_NAME, config={"timeframe": "4h"}, time=_T))
    assert strategy_over.timeframe == timedelta(hours=1), "one over capacity must be rejected"


# --- D-17 pair refusal ------------------------------------------------------

def test_pair_reconfigure_is_refused(store: StrategyRegistryStore) -> None:
    """Test 20 (D-17) — a PairStrategy reconfigure is refused; nothing mutates or persists."""
    handler = StrategiesHandler(
        Queue(), _StubFeed(), InMemorySignalStore(),
        allow_short_selling=True, enable_margin=True)  # the pair is LONG_SHORT (SHORT-01 gate)
    handler.registry_store = store
    handler.strategy_catalog = test_catalog()
    pair = EthBtcPairStrategy(timeframe="1d")
    handler.add_strategy(pair)
    before_entry = pair.entry_z

    handler.on_strategy_command(
        StrategyCommandEvent.reconfigure(
            strategy_name=pair.name, config={"entry_z": "3"}, time=_T))

    assert pair.entry_z == before_entry, "a pair refuses reconfigure (D-17)"
    assert store.get(pair.name) is None

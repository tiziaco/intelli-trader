"""D-07/D-08/D-09 light-verb dispatch — apply live AND persist, with idempotency.

The STRAT-02 dispatch surface. "Light" = no force-flat and no instance construction: the
heavy lifecycle verbs (``add``/``remove``) land in Plan 07 on this skeleton and
``reconfigure`` in Plan 08.

**D-09** — every verb persists, gated on a REAL mutation (IN-02: no control-plane churn on
a no-op). ``at`` for every persist comes from ``event.time``, the event's BUSINESS time —
the store is clock-free by contract. Persistence degrades to a clean no-op when no registry
store is injected (the backtest/in-memory path). An unknown ``strategy_name`` or verb is a
LOUD no-op — ``logger.warning`` + return, never a raise into the queue.

**D-07 + WD-1** — ``enable`` sets ``is_active=True`` and persists ``enabled=True``, then
FORCES A RE-WARM. It does NOT trade the next bar. The D-07 guard is FIRST in the
``on_bar`` loop, so a disabled strategy's indicator state FREEZES; re-enabling
without a re-warm would fire from a window with an N-bar hole. ``disable`` sets
``is_active=False``, persists ``enabled=False``, and leaves the object in the roster with
its open positions and resting brackets running to natural exit — it stops NEW entries only.

Assertions read STATE and the STORE, never log capture: ``make test`` exports
``ITRADER_DISABLE_LOGS=true``, so a log-capture assertion would false-green.

4-space indentation (matches ``test_strategies_live_membership.py``, the sibling
``on_strategy_command`` suite). NO ``__init__.py`` in this dir.
"""

from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from queue import Queue
from types import SimpleNamespace
from typing import Any, Iterator
from uuid import UUID

import pandas as pd
import pytest

from itrader.config.sql import SqlSettings
from itrader.core.bar import Bar
from itrader.core.sizing import FractionOfCash
from itrader.events_handler.events import StrategyCommandEvent, UniversePollEvent
from itrader.storage import SqlEngine
from itrader.storage.strategy_registry_store import StrategyRegistryStore
from itrader.strategy_handler.base import Strategy
from itrader.strategy_handler.indicators import SMA
from itrader.strategy_handler.registry import encode_strategy_config
from itrader.strategy_handler.storage import InMemorySignalStore
from itrader.strategy_handler.strategies.eth_btc_pair_strategy import EthBtcPairStrategy
from itrader.strategy_handler.strategies.SMA_MACD_strategy import SMAMACDStrategy
from itrader.strategy_handler.strategies_handler import StrategiesHandler
from tests.support.schema import provision_schema
from tests.support.strategy_catalog import test_catalog

pytestmark = pytest.mark.unit

_T = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
_TICKER = "BTCUSD"
_OTHER = "ETHUSD"
_NAME = "verb_probe"
_WARMUP = 3
# Portfolio ids arrive as STRINGS in the untrusted payload (and are stored as String),
# but `subscribed_portfolios` is typed `list[PortfolioId | int]` and on_bar
# casts each entry straight onto SignalEvent.portfolio_id. So the dispatch must PARSE
# them; a bare str would fan signals at a portfolio matching nothing.
_P1 = "550e8400-e29b-41d4-a716-446655440000"
_P2 = "550e8400-e29b-41d4-a716-446655440001"


class _Probe(Strategy):
    """A minimal handle-bearing strategy addressed by the verbs."""

    name = _NAME
    sizing_policy = FractionOfCash(Decimal("0.5"))

    def init(self) -> None:
        self.sma = self.indicator(SMA, "close", _WARMUP)

    def generate_signal(self, ticker: str) -> Any:
        return None


class _StubFeed:
    """A minimal ``BarFeed`` stand-in — never queried by the command path."""

    def symbols(self) -> list[str]:
        return [_TICKER, _OTHER]

    def window(self, ticker, timeframe, max_window, asof):  # type: ignore[no-untyped-def]
        return pd.DataFrame(
            {"open": [], "high": [], "low": [], "close": [], "volume": []},
            index=pd.DatetimeIndex([], tz="UTC"),
        )


@pytest.fixture()
def store() -> Iterator[StrategyRegistryStore]:
    """An in-memory SQLite registry store (the ``test_strategy_registry_store`` shape).

    ``filterwarnings=["error"]`` -> always dispose.
    """
    registry = StrategyRegistryStore(SqlEngine(SqlSettings.default()))
    provision_schema(registry.backend)
    try:
        yield registry
    finally:
        registry.dispose()


def _bar(price: float, *, offset: int = 0) -> Bar:
    stamp = datetime(2020, 1, 1, tzinfo=timezone.utc) + timedelta(days=offset)
    return Bar(
        time=stamp,
        open=Decimal(str(price)),
        high=Decimal(str(price)),
        low=Decimal(str(price)),
        close=Decimal(str(price)),
        volume=Decimal("1"),
    )


def _handler(
    registry: StrategyRegistryStore | None, *, tickers: list[str] | None = None
) -> tuple[StrategiesHandler, _Probe]:
    handler = StrategiesHandler(Queue(), _StubFeed(), InMemorySignalStore())
    handler.registry_store = registry
    strategy = _Probe(timeframe="1d", tickers=list(tickers or [_TICKER]))
    handler.add_strategy(strategy)
    return handler, strategy


def _warm(strategy: Strategy, ticker: str = _TICKER) -> None:
    for i in range(_WARMUP):
        strategy.update(ticker, _bar(100 + i, offset=i))


def _drain(queue: "Queue[Any]") -> list[Any]:
    drained = []
    while not queue.empty():
        drained.append(queue.get(False))
    return drained


# --- enable / disable (D-07, WD-1) -----------------------------------------

def test_enable_applies_live_and_persists(store: StrategyRegistryStore) -> None:
    """Test 1 — ``is_active`` flips True AND the row records ``enabled=True``."""
    handler, strategy = _handler(store)
    strategy.deactivate_strategy()

    handler.on_strategy_command(
        StrategyCommandEvent.enable(strategy_name=_NAME, time=_T))

    assert strategy.is_active is True
    row = store.get(_NAME)
    assert row is not None
    assert row["enabled"] is True


def test_disable_applies_live_and_persists(store: StrategyRegistryStore) -> None:
    """Test 2 — ``is_active`` flips False, the row records it, the object STAYS in the roster."""
    handler, strategy = _handler(store)
    _warm(strategy)

    handler.on_strategy_command(
        StrategyCommandEvent.disable(strategy_name=_NAME, time=_T))

    assert strategy.is_active is False
    row = store.get(_NAME)
    assert row is not None
    assert row["enabled"] is False
    # D-07: it stays in the list — disable stops NEW entries only; open positions
    # and resting brackets run to natural exit via the execution layer.
    assert strategy in handler.strategies


def test_disable_does_not_unwarm(store: StrategyRegistryStore) -> None:
    """D-07 — disable must NOT reset indicator state; only ``enable`` re-warms (WD-1)."""
    handler, strategy = _handler(store)
    _warm(strategy)
    assert strategy.is_ready(_TICKER) is True

    handler.on_strategy_command(
        StrategyCommandEvent.disable(strategy_name=_NAME, time=_T))

    assert strategy.is_ready(_TICKER) is True


def test_enable_forces_a_re_warm_before_the_strategy_may_signal(
    store: StrategyRegistryStore,
) -> None:
    """WD-1 — the load-bearing one. A re-enabled strategy must NOT fire from a holed window.

    The D-07 guard is first in ``on_bar``, so a disabled strategy's indicator
    state FREEZES. Trading the next bar after enable would compute SMA/MACD across an
    N-bar discontinuity — silently wrong values, invisible because warmth is monotone.
    """
    handler, strategy = _handler(store)
    _warm(strategy)
    handler.on_strategy_command(
        StrategyCommandEvent.disable(strategy_name=_NAME, time=_T))

    handler.on_strategy_command(
        StrategyCommandEvent.enable(strategy_name=_NAME, time=_T))

    assert strategy.is_active is True
    assert strategy.is_ready(_TICKER) is False, (
        "enable must unwarm: the frozen window has a hole spanning the disabled period")


def test_enable_re_warms_through_the_ordinary_bar_path(
    store: StrategyRegistryStore,
) -> None:
    """WD-1 — warmth is re-EARNED from a contiguous window, with no bespoke pipeline."""
    handler, strategy = _handler(store)
    _warm(strategy)
    handler.on_strategy_command(
        StrategyCommandEvent.disable(strategy_name=_NAME, time=_T))
    handler.on_strategy_command(
        StrategyCommandEvent.enable(strategy_name=_NAME, time=_T))

    for i in range(_WARMUP):
        strategy.update(_TICKER, _bar(500 + i, offset=100 + i))

    assert strategy.is_ready(_TICKER) is True


# --- idempotency (D-09 / IN-02) --------------------------------------------

def test_enable_on_an_enabled_strategy_is_an_idempotent_no_op(
    store: StrategyRegistryStore,
) -> None:
    """Test 4 — the ``mutated`` gate governs the persist arm the same way (IN-02).

    Critical under WD-1: a no-op enable that still unwarmed would silently dark a healthy
    strategy for a full warmup period every time an operator re-sent the command.
    """
    handler, strategy = _handler(store)
    _warm(strategy)
    assert strategy.is_active is True

    handler.on_strategy_command(
        StrategyCommandEvent.enable(strategy_name=_NAME, time=_T))

    assert store.get(_NAME) is None, "an idempotent no-op must not persist"
    assert _drain(handler.global_queue) == []
    assert strategy.is_ready(_TICKER) is True, "a no-op enable must not unwarm"


def test_disable_on_a_disabled_strategy_is_an_idempotent_no_op(
    store: StrategyRegistryStore,
) -> None:
    """The symmetric arm — no mutation, no persist, no follow-on."""
    handler, strategy = _handler(store)
    strategy.deactivate_strategy()

    handler.on_strategy_command(
        StrategyCommandEvent.disable(strategy_name=_NAME, time=_T))

    assert store.get(_NAME) is None
    assert _drain(handler.global_queue) == []


# --- portfolio fan-out (D-06/D-09) -----------------------------------------

def test_subscribe_portfolio_applies_live_and_writes_the_child_row(
    store: StrategyRegistryStore,
) -> None:
    """Test 5 — the fan-out edge is runtime-mutable, symmetric with D-06's first-class edge."""
    handler, strategy = _handler(store)

    handler.on_strategy_command(StrategyCommandEvent.subscribe_portfolio(
        strategy_name=_NAME, portfolio_id=_P1, time=_T))

    assert UUID(_P1) in strategy.subscribed_portfolios
    assert store.portfolio_subscriptions(_NAME) == [_P1]


def test_subscribed_portfolio_id_is_a_portfolio_id_not_a_str(
    store: StrategyRegistryStore,
) -> None:
    """The payload id must be PARSED, not passed through (the 10-05 trap, one arm over).

    ``on_bar`` casts each entry of ``subscribed_portfolios`` straight onto
    ``SignalEvent.portfolio_id`` (FL-02: "the runtime value is always a UUIDv7-backed
    PortfolioId"). A bare ``str`` sails through that cast and reaches the portfolio
    lookup matching NOTHING — the subscription looks healthy and fans into the void.
    Only a TYPE assertion catches it: value equality passes while the type is wrong.
    """
    handler, strategy = _handler(store)

    handler.on_strategy_command(StrategyCommandEvent.subscribe_portfolio(
        strategy_name=_NAME, portfolio_id=_P1, time=_T))

    subscribed = strategy.subscribed_portfolios[0]
    assert isinstance(subscribed, UUID)
    assert not isinstance(subscribed, str)


def test_a_malformed_portfolio_id_is_a_loud_no_op(
    store: StrategyRegistryStore,
) -> None:
    """An unparseable id never reaches live state or SQL, and never raises (T-10-35)."""
    handler, strategy = _handler(store)

    handler.on_strategy_command(StrategyCommandEvent.subscribe_portfolio(
        strategy_name=_NAME, portfolio_id="not-a-uuid", time=_T))

    assert strategy.subscribed_portfolios == []
    assert store.portfolio_subscriptions(_NAME) == []


def test_the_legacy_int_portfolio_id_arm_still_works(
    store: StrategyRegistryStore,
) -> None:
    """``PortfolioId | int`` — the union's int arm is legal and must not be rejected."""
    handler, strategy = _handler(store)

    handler.on_strategy_command(StrategyCommandEvent.subscribe_portfolio(
        strategy_name=_NAME, portfolio_id="7", time=_T))

    assert strategy.subscribed_portfolios == [7]
    assert store.portfolio_subscriptions(_NAME) == ["7"]


def test_subscribe_portfolio_twice_is_idempotent(
    store: StrategyRegistryStore,
) -> None:
    """One row, one list entry — a duplicate would fan one decision out twice."""
    handler, strategy = _handler(store)
    event = StrategyCommandEvent.subscribe_portfolio(
        strategy_name=_NAME, portfolio_id=_P1, time=_T)

    handler.on_strategy_command(event)
    handler.on_strategy_command(event)

    assert strategy.subscribed_portfolios.count(UUID(_P1)) == 1
    assert store.portfolio_subscriptions(_NAME) == [_P1]


def test_unsubscribe_portfolio_applies_live_and_deletes_the_child_row(
    store: StrategyRegistryStore,
) -> None:
    """Test 6 — the id leaves the live list AND the row goes."""
    handler, strategy = _handler(store)
    handler.on_strategy_command(StrategyCommandEvent.subscribe_portfolio(
        strategy_name=_NAME, portfolio_id=_P1, time=_T))
    handler.on_strategy_command(StrategyCommandEvent.subscribe_portfolio(
        strategy_name=_NAME, portfolio_id=_P2, time=_T))

    handler.on_strategy_command(StrategyCommandEvent.unsubscribe_portfolio(
        strategy_name=_NAME, portfolio_id=_P1, time=_T))

    assert UUID(_P1) not in strategy.subscribed_portfolios
    assert store.portfolio_subscriptions(_NAME) == [_P2]


def test_unsubscribe_of_an_unsubscribed_id_is_an_idempotent_no_op(
    store: StrategyRegistryStore,
) -> None:
    """Test 6b — not an error."""
    handler, strategy = _handler(store)

    handler.on_strategy_command(StrategyCommandEvent.unsubscribe_portfolio(
        strategy_name=_NAME, portfolio_id="ghost", time=_T))

    assert strategy.subscribed_portfolios == []
    assert store.portfolio_subscriptions(_NAME) == []


def test_unsubscribing_the_last_portfolio_is_a_legal_empty_state(
    store: StrategyRegistryStore,
) -> None:
    """Test 7 — the strategy computes but fans out to nobody. Legal, not an error."""
    handler, strategy = _handler(store)
    handler.on_strategy_command(StrategyCommandEvent.subscribe_portfolio(
        strategy_name=_NAME, portfolio_id=_P1, time=_T))

    handler.on_strategy_command(StrategyCommandEvent.unsubscribe_portfolio(
        strategy_name=_NAME, portfolio_id=_P1, time=_T))

    assert strategy.subscribed_portfolios == []
    assert store.portfolio_subscriptions(_NAME) == []


def test_subscribe_portfolio_without_a_portfolio_id_is_a_loud_no_op(
    store: StrategyRegistryStore,
) -> None:
    """A missing/invalid payload key never reaches live state (T-10-35)."""
    handler, strategy = _handler(store)

    handler.on_strategy_command(StrategyCommandEvent(
        time=_T, strategy_name=_NAME, verb="subscribe_portfolio", config=None))

    assert strategy.subscribed_portfolios == []
    assert store.portfolio_subscriptions(_NAME) == []


# --- ticker verbs now persist too (D-09) -----------------------------------

def test_add_ticker_persists_and_still_emits_the_poll(
    store: StrategyRegistryStore,
) -> None:
    """Test 8 — a ticker change IS a reconfigure of the ``tickers`` authoring param."""
    handler, strategy = _handler(store)

    handler.on_strategy_command(StrategyCommandEvent.add_ticker(
        strategy_name=_NAME, symbol=_OTHER, time=_T))

    assert _OTHER in strategy.tickers
    row = store.get(_NAME)
    assert row is not None
    assert _OTHER in row["config"]["tickers"]
    assert [type(e) for e in _drain(handler.global_queue)] == [UniversePollEvent]


def test_remove_ticker_persists_and_still_emits_the_poll(
    store: StrategyRegistryStore,
) -> None:
    """The symmetric arm."""
    handler, strategy = _handler(store, tickers=[_TICKER, _OTHER])

    handler.on_strategy_command(StrategyCommandEvent.remove_ticker(
        strategy_name=_NAME, symbol=_OTHER, time=_T))

    assert _OTHER not in strategy.tickers
    row = store.get(_NAME)
    assert row is not None
    assert _OTHER not in row["config"]["tickers"]
    assert [type(e) for e in _drain(handler.global_queue)] == [UniversePollEvent]


def test_an_idempotent_ticker_no_op_persists_nothing_and_emits_nothing(
    store: StrategyRegistryStore,
) -> None:
    """Test 8b — IN-02 governs the new persist arm exactly as it governs the poll."""
    handler, _strategy = _handler(store)

    handler.on_strategy_command(StrategyCommandEvent.add_ticker(
        strategy_name=_NAME, symbol=_TICKER, time=_T))  # already present

    assert store.get(_NAME) is None
    assert _drain(handler.global_queue) == []


def test_a_refused_last_ticker_removal_persists_nothing() -> None:
    """The non-empty ticker invariant holds and the refusal writes nothing."""
    registry = StrategyRegistryStore(SqlEngine(SqlSettings.default()))
    provision_schema(registry.backend)
    try:
        handler, strategy = _handler(registry)

        handler.on_strategy_command(StrategyCommandEvent.remove_ticker(
            strategy_name=_NAME, symbol=_TICKER, time=_T))

        assert strategy.tickers == [_TICKER]
        assert registry.get(_NAME) is None
    finally:
        registry.dispose()


# --- provenance, degradation and unknown input (D-09) ----------------------

def test_persisted_updated_at_is_the_event_business_time(
    store: StrategyRegistryStore,
) -> None:
    """Test 10 — never wall clock; the store is clock-free by contract."""
    handler, strategy = _handler(store)
    strategy.deactivate_strategy()

    handler.on_strategy_command(
        StrategyCommandEvent.enable(strategy_name=_NAME, time=_T))

    row = store.get(_NAME)
    assert row is not None
    stamped = row["updated_at"]
    if stamped.tzinfo is None:
        stamped = stamped.replace(tzinfo=UTC)
    assert stamped == _T


def test_persisted_strategy_type_is_the_catalog_key(
    store: StrategyRegistryStore,
) -> None:
    """The row must rehydrate: ``strategy_type`` is the D-01 catalog key."""
    handler, strategy = _handler(store)
    strategy.deactivate_strategy()

    handler.on_strategy_command(
        StrategyCommandEvent.enable(strategy_name=_NAME, time=_T))

    row = store.get(_NAME)
    assert row is not None
    assert row["strategy_type"] == "_Probe"


def test_every_verb_applies_live_with_no_store_injected() -> None:
    """Test 9 — the backtest/in-memory path degrades to a clean no-op, raising nothing."""
    handler, strategy = _handler(None)
    strategy.deactivate_strategy()

    handler.on_strategy_command(
        StrategyCommandEvent.enable(strategy_name=_NAME, time=_T))
    assert strategy.is_active is True

    handler.on_strategy_command(
        StrategyCommandEvent.disable(strategy_name=_NAME, time=_T))
    assert strategy.is_active is False

    handler.on_strategy_command(StrategyCommandEvent.subscribe_portfolio(
        strategy_name=_NAME, portfolio_id=_P1, time=_T))
    assert UUID(_P1) in strategy.subscribed_portfolios

    handler.on_strategy_command(StrategyCommandEvent.unsubscribe_portfolio(
        strategy_name=_NAME, portfolio_id=_P1, time=_T))
    assert strategy.subscribed_portfolios == []

    handler.on_strategy_command(StrategyCommandEvent.add_ticker(
        strategy_name=_NAME, symbol=_OTHER, time=_T))
    assert _OTHER in strategy.tickers


def test_registry_store_defaults_to_none() -> None:
    """The backtest composition root injects nothing — persistence must be opt-in."""
    handler = StrategiesHandler(Queue(), _StubFeed(), InMemorySignalStore())

    assert handler.registry_store is None


def test_unknown_strategy_name_is_a_loud_no_op(store: StrategyRegistryStore) -> None:
    """Test 3 — mutates nothing, persists nothing, raises nothing into the queue."""
    handler, strategy = _handler(store)
    strategy.deactivate_strategy()

    handler.on_strategy_command(
        StrategyCommandEvent.enable(strategy_name="ghost", time=_T))

    assert strategy.is_active is False
    assert store.get("ghost") is None
    assert store.get(_NAME) is None
    assert _drain(handler.global_queue) == []


def test_unknown_verb_is_a_loud_no_op(store: StrategyRegistryStore) -> None:
    """Test 11 — an unrecognized verb never raises into the queue."""
    handler, strategy = _handler(store)

    handler.on_strategy_command(StrategyCommandEvent(
        time=_T, strategy_name=_NAME, verb="teleport"))

    assert store.get(_NAME) is None
    assert _drain(handler.global_queue) == []
    assert strategy.is_active is True


def test_reconfigure_is_still_a_no_op_here(
    store: StrategyRegistryStore,
) -> None:
    """``reconfigure`` lands in Plan 08 — inert here, never a raise. (``add``/``remove``
    are implemented in Plan 07 and covered by their own suites.)"""
    handler, _strategy = _handler(store)

    handler.on_strategy_command(StrategyCommandEvent.reconfigure(
        strategy_name=_NAME, config={"timeframe": "1h"}, time=_T))

    assert store.get(_NAME) is None
    assert _drain(handler.global_queue) == []


# ===========================================================================
# Plan 07 — D-10 `add` (catalog-gate, register dark, persist, warm via P7)
# ===========================================================================
#
# `add` targets a NEW name not yet in the roster, so it is dispatched BEFORE the
# by-name lookup guard. The injected `strategy_catalog` IS the access-control
# allowlist (D-10): without it, nothing may be instantiated from an external
# payload. Construction runs through the IDENTICAL `build_strategy` path rehydrate
# uses (D-01) — one reconstruction path, not two that drift.


class _CapFeed:
    """A feed exposing `base_timeframe` + a controllable `cache_capacity` (F-1).

    The F-1 warmability gate keys on `getattr(self.feed, "base_timeframe", None)`;
    `_StubFeed` has neither, so it skips the gate cleanly (the backtest/in-memory
    degrade arm). This stand-in drives the gate.
    """

    def __init__(self, base_timeframe: timedelta, capacity: int) -> None:
        self._bt = base_timeframe
        self._cap = capacity

    @property
    def base_timeframe(self) -> timedelta:
        return self._bt

    def cache_capacity(self) -> int:
        return self._cap

    def symbols(self) -> list[str]:
        return []

    def window(self, ticker, timeframe, max_window, asof):  # type: ignore[no-untyped-def]
        return pd.DataFrame(
            {"open": [], "high": [], "low": [], "close": [], "volume": []},
            index=pd.DatetimeIndex([], tz="UTC"),
        )


class _LogSpy:
    """Records ``warning``/``error`` calls so the TIER is assertable without ``caplog``.

    The module docstring bans log-capture assertions because ``make test`` exports
    ``ITRADER_DISABLE_LOGS=true``, which would false-green a ``caplog`` assertion. A
    COLLABORATOR SPY honours that intent: replacing the lifecycle manager's ``logger``
    object records calls deterministically under BOTH runners, independent of any logging
    configuration, while still proving WARNING (bad operator payload) is distinct from
    ERROR (a defect in our construction path).
    """

    def __init__(self) -> None:
        self.warnings: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
        self.errors: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

    def warning(self, *args: Any, **kwargs: Any) -> None:
        self.warnings.append((args, kwargs))

    def error(self, *args: Any, **kwargs: Any) -> None:
        self.errors.append((args, kwargs))


class _BoomStrategy(Strategy):
    """A catalog strategy whose ``init()`` raises an arbitrary, non-validation type.

    WHY this exists: ``build_strategy`` -> ``cls(**params)`` -> ``_apply_params`` ->
    ``validate()`` -> ``_run_init()`` -> ``self.init()``, and ``init()`` is ARBITRARY
    USER-AUTHORED strategy code (``my_strategies/``). The set of exceptions escaping
    construction is therefore unbounded BY CONSTRUCTION — no finite catch tuple can be
    complete. This stands in for a buggy ``my_strategies/`` entry and proves the zone-1
    guard covers the whole class of failures, not just the enumerated validation kinds.
    """

    sizing_policy = FractionOfCash(Decimal("0.5"))

    def init(self) -> None:
        raise ZeroDivisionError("arbitrary failure inside user-authored init()")

    def generate_signal(self, ticker: str) -> Any:
        return None


def _add_handler(
    registry: StrategyRegistryStore | None,
    *,
    feed: Any = None,
    catalog: Any = "DEFAULT",
    short_enabled: bool = False,
) -> StrategiesHandler:
    """A handler with a strategy_catalog injected (the D-10 add allowlist)."""
    handler = StrategiesHandler(
        Queue(),
        feed or _StubFeed(),
        InMemorySignalStore(),
        allow_short_selling=short_enabled,
        enable_margin=short_enabled,
        strategy_catalog=(test_catalog() if catalog == "DEFAULT" else catalog),
    )
    handler.registry_store = registry
    return handler


def _sma_add_config(tickers: list[str] | None = None, *, timeframe: str = "1d") -> dict:
    """A decode-ready config_json blob for an SMAMACDStrategy add payload."""
    built = SMAMACDStrategy(timeframe=timeframe, tickers=list(tickers or ["ETHUSD"]))
    return encode_strategy_config(built)


def test_add_registers_dark_persists_and_emits_the_poll(
    store: StrategyRegistryStore,
) -> None:
    """Test 1 (D-10) — instance registered, row present, a UniversePollEvent emitted."""
    handler = _add_handler(store)

    handler.on_strategy_command(StrategyCommandEvent.add(
        strategy_name="new1", strategy_type="SMAMACDStrategy",
        config=_sma_add_config(["ETHUSD"]), time=_T))

    names = [s.name for s in handler.strategies]
    assert "new1" in names
    row = store.get("new1")
    assert row is not None
    assert row["strategy_type"] == "SMAMACDStrategy"
    assert row["enabled"] is True
    assert [type(e) for e in _drain(handler.global_queue)] == [UniversePollEvent]


def test_add_of_an_unknown_type_is_a_loud_no_op(store: StrategyRegistryStore) -> None:
    """Test 2 (D-10) — an off-allowlist strategy_type registers/persists nothing."""
    handler = _add_handler(store)

    handler.on_strategy_command(StrategyCommandEvent.add(
        strategy_name="bad", strategy_type="NoSuchStrategy",
        config={"config_version": 1, "timeframe": "1d", "tickers": ["BTCUSD"]},
        time=_T))

    assert [s.name for s in handler.strategies] == []
    assert store.get("bad") is None
    assert _drain(handler.global_queue) == []


def test_add_of_a_duplicate_name_is_a_loud_no_op(store: StrategyRegistryStore) -> None:
    """Test 3 (D-02) — a name collision leaves the existing instance + row untouched."""
    handler = _add_handler(store)
    handler.on_strategy_command(StrategyCommandEvent.add(
        strategy_name="dup", strategy_type="SMAMACDStrategy",
        config=_sma_add_config(["ETHUSD"]), time=_T))
    first = next(s for s in handler.strategies if s.name == "dup")
    row_before = store.get("dup")
    _drain(handler.global_queue)

    handler.on_strategy_command(StrategyCommandEvent.add(
        strategy_name="dup", strategy_type="SMAMACDStrategy",
        config=_sma_add_config(["BTCUSD"]), time=_T))

    # The existing instance object is the SAME one (not shadowed) and its row is
    # unchanged (still the ETHUSD config, not the second BTCUSD payload).
    survivors = [s for s in handler.strategies if s.name == "dup"]
    assert survivors == [first]
    assert store.get("dup") == row_before
    assert _drain(handler.global_queue) == []


def test_add_uses_the_same_reconstruction_path_as_build_strategy(
    store: StrategyRegistryStore,
) -> None:
    """Test 4 (D-01) — the added instance matches build_strategy on its declared surface."""
    from itrader.strategy_handler.registry.rehydrate import build_strategy

    handler = _add_handler(store)
    config = _sma_add_config(["ETHUSD"])

    handler.on_strategy_command(StrategyCommandEvent.add(
        strategy_name="twin", strategy_type="SMAMACDStrategy",
        config=config, time=_T))

    added = next(s for s in handler.strategies if s.name == "twin")
    direct = build_strategy(
        {"strategy_name": "twin", "strategy_type": "SMAMACDStrategy",
         "config_json": config},
        catalog=test_catalog())
    assert encode_strategy_config(added) == encode_strategy_config(direct)


def test_add_with_a_missing_required_param_registers_nothing(
    store: StrategyRegistryStore,
) -> None:
    """Test 5 (degenerate) — MissingParamError from _apply_params; nothing enters the roster."""
    handler = _add_handler(store)

    handler.on_strategy_command(StrategyCommandEvent.add(
        strategy_name="half", strategy_type="EmptyStrategy",
        config={"config_version": 1, "timeframe": "1d", "tickers": ["BTCUSD"]},
        time=_T))  # EmptyStrategy needs sizing_policy — omitted

    assert [s.name for s in handler.strategies] == []
    assert store.get("half") is None
    assert _drain(handler.global_queue) == []


def test_add_with_an_unknown_param_registers_nothing(
    store: StrategyRegistryStore,
) -> None:
    """Test 5b (degenerate) — UnknownParamError; a smuggled key never enters the roster."""
    handler = _add_handler(store)
    config = _sma_add_config(["ETHUSD"])
    config["nonsense_param"] = 7

    handler.on_strategy_command(StrategyCommandEvent.add(
        strategy_name="smuggle", strategy_type="SMAMACDStrategy",
        config=config, time=_T))

    assert [s.name for s in handler.strategies] == []
    assert store.get("smuggle") is None


def test_add_with_empty_tickers_is_a_loud_no_op(
    store: StrategyRegistryStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """CR-01 — a bare ``ValueError`` from ``validate()`` must NOT escape into the queue.

    ``STRATEGY_COMMAND`` is externally admitted (D-10). An escape here reaches
    ``ErrorPolicy.record_failure`` -> the failure-rate tripwire -> ``halt()``, and
    ``HALTED`` has no legal exit except operator ``reset_halt()``. So a payload as routine
    as ``tickers: []`` could latch live trading into HALT.
    """
    handler = _add_handler(store)
    spy = _LogSpy()
    monkeypatch.setattr(handler._lifecycle, "logger", spy)
    config = _sma_add_config(["ETHUSD"])
    config["tickers"] = []

    handler.on_strategy_command(StrategyCommandEvent.add(
        strategy_name="empty_tickers", strategy_type="SMAMACDStrategy",
        config=config, time=_T))

    assert [s.name for s in handler.strategies] == []
    assert store.get("empty_tickers") is None
    assert _drain(handler.global_queue) == []
    assert spy.warnings, "a bad operator payload must be a LOUD no-op at the WARNING tier"
    assert spy.errors == [], "operator junk is not a defect in our construction path"


def test_add_with_an_invalid_window_pair_is_a_loud_no_op(
    store: StrategyRegistryStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """CR-01 — the second bare-``ValueError`` site (``SMA_MACD_strategy.py`` ``validate()``).

    Same halt-latch consequence: an externally-admitted ``add`` whose windows are
    misordered must be a logged no-op, never a raise that feeds the failure-rate tripwire.
    """
    handler = _add_handler(store)
    spy = _LogSpy()
    monkeypatch.setattr(handler._lifecycle, "logger", spy)
    config = _sma_add_config(["ETHUSD"])
    config["short_window"] = 100
    config["long_window"] = 50

    handler.on_strategy_command(StrategyCommandEvent.add(
        strategy_name="bad_windows", strategy_type="SMAMACDStrategy",
        config=config, time=_T))

    assert [s.name for s in handler.strategies] == []
    assert store.get("bad_windows") is None
    assert _drain(handler.global_queue) == []
    assert spy.warnings, "a bad operator payload must be a LOUD no-op at the WARNING tier"
    assert spy.errors == []


def test_add_whose_init_raises_an_arbitrary_type_is_a_loud_no_op_at_the_error_tier(
    store: StrategyRegistryStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """CR-01 — an UNBOUNDED exception type from user-authored ``init()`` still cannot halt.

    ``init()`` is arbitrary user code, so enumerating catch types fixes the instance and
    not the class. This must still be a no-op — but at the ERROR tier with ``exc_info``,
    because an unexpected type means a defect in OUR construction path and must stay
    visibly distinct from "the operator sent junk".
    """
    handler = _add_handler(store, catalog={"_BoomStrategy": _BoomStrategy})
    spy = _LogSpy()
    monkeypatch.setattr(handler._lifecycle, "logger", spy)

    handler.on_strategy_command(StrategyCommandEvent.add(
        strategy_name="boom", strategy_type="_BoomStrategy",
        config={"config_version": 1, "timeframe": "1d", "tickers": ["BTCUSD"]},
        time=_T))

    assert [s.name for s in handler.strategies] == []
    assert store.get("boom") is None
    assert _drain(handler.global_queue) == []
    assert spy.errors, "an unexpected construction failure belongs at the ERROR tier"
    assert spy.warnings == [], "it must not be laundered into the operator-junk tier"
    assert spy.errors[0][1].get("exc_info") is True, (
        "the ERROR tier carries the traceback; the message itself names no payload values")


def test_add_beyond_ring_capacity_is_a_loud_reject(store: StrategyRegistryStore) -> None:
    """Test 6 (F-1) — required_base_depth > cache_capacity rejects loudly (ring can't resize)."""
    handler = _add_handler(store, feed=_CapFeed(timedelta(days=1), capacity=5))

    handler.on_strategy_command(StrategyCommandEvent.add(
        strategy_name="deep", strategy_type="SMAMACDStrategy",
        config=_sma_add_config(["ETHUSD"]), time=_T))  # warmup 100 base bars > 5

    assert [s.name for s in handler.strategies] == []
    assert store.get("deep") is None
    assert _drain(handler.global_queue) == []


def test_add_within_ring_capacity_succeeds(store: StrategyRegistryStore) -> None:
    """Test 6b (F-1) — a warmup that fits the ring registers normally."""
    handler = _add_handler(store, feed=_CapFeed(timedelta(days=1), capacity=200))

    handler.on_strategy_command(StrategyCommandEvent.add(
        strategy_name="fits", strategy_type="SMAMACDStrategy",
        config=_sma_add_config(["ETHUSD"]), time=_T))  # warmup 100 <= 200

    assert "fits" in [s.name for s in handler.strategies]
    assert store.get("fits") is not None


def test_add_of_a_finer_than_base_timeframe_is_a_loud_reject(
    store: StrategyRegistryStore,
) -> None:
    """Test 7 (F-1) — a strategy timeframe finer than base raises UnwarmableTimeframeError."""
    handler = _add_handler(store, feed=_CapFeed(timedelta(days=1), capacity=1000))

    handler.on_strategy_command(StrategyCommandEvent.add(
        strategy_name="finer", strategy_type="SMAMACDStrategy",
        config=_sma_add_config(["ETHUSD"], timeframe="1h"), time=_T))  # 1h < 1d base

    assert [s.name for s in handler.strategies] == []
    assert store.get("finer") is None


def test_add_of_a_pair_strategy_succeeds(store: StrategyRegistryStore) -> None:
    """Test 8 (D-16) — a pair adds as a full registry instance with both legs."""
    handler = _add_handler(store, short_enabled=True)
    built = EthBtcPairStrategy(timeframe="1d")
    config = encode_strategy_config(built)

    handler.on_strategy_command(StrategyCommandEvent.add(
        strategy_name="spread1", strategy_type="EthBtcPairStrategy",
        config=config, time=_T))

    added = next((s for s in handler.strategies if s.name == "spread1"), None)
    assert added is not None
    assert set(added.tickers) == {"ETHUSD", "BTCUSD"}
    assert store.get("spread1") is not None


def test_add_degrades_cleanly_with_no_store(store: StrategyRegistryStore) -> None:
    """Test 9 (degrade-clean) — with registry_store None, add registers live, persists nothing."""
    handler = _add_handler(None)

    handler.on_strategy_command(StrategyCommandEvent.add(
        strategy_name="live_only", strategy_type="SMAMACDStrategy",
        config=_sma_add_config(["ETHUSD"]), time=_T))

    assert "live_only" in [s.name for s in handler.strategies]
    assert handler.registry_store is None


def test_add_with_no_catalog_is_a_loud_no_op(store: StrategyRegistryStore) -> None:
    """Test 10 (D-10) — no injected catalog means no external payload may be instantiated."""
    handler = _add_handler(store, catalog=None)

    handler.on_strategy_command(StrategyCommandEvent.add(
        strategy_name="denied", strategy_type="SMAMACDStrategy",
        config=_sma_add_config(["ETHUSD"]), time=_T))

    assert [s.name for s in handler.strategies] == []
    assert store.get("denied") is None
    assert _drain(handler.global_queue) == []


# ===========================================================================
# Plan 07 — D-11 `remove` (force-flat first, pending state, drop child-then-parent)
# ===========================================================================
#
# `remove` deactivates (D-07 gate stops NEW entries), holds the name PENDING across
# event cycles while the P7 universe force-close plays out, and drops the object +
# deletes child-then-parent rows only once the positions are OBSERVED flat on a FILL.
# The registry ROW survives a mid-removal crash so restart can resume ownership.


class _FakeReadModel:
    """A PortfolioReadModel stand-in for the D-11 flat-detect (`get_position` only)."""

    def __init__(self, held: set[str] | None = None) -> None:
        self.held: set[str] = set(held or set())

    def get_position(self, portfolio_id: Any, ticker: str) -> Any:
        # A non-None sentinel means "open position"; None means flat (the contract).
        return object() if ticker in self.held else None


def _fill(ticker: str = _TICKER) -> Any:
    """A minimal FILL trigger — `on_fill` re-scans pending removals, not the event."""
    return SimpleNamespace(ticker=ticker)


class _FaultyDeleteStore:
    """Registry-store wrapper whose ``delete`` raises while ``fail`` is set.

    ``delete`` is defined explicitly so attribute lookup finds it BEFORE
    ``__getattr__``; every other call the remove path makes (the
    ``_persist_strategy`` upsert, ``get``, the subscription writers) delegates
    to the real store unchanged.
    """

    def __init__(self, wrapped: StrategyRegistryStore) -> None:
        self._wrapped = wrapped
        self.fail = True

    def delete(self, strategy_name: str) -> None:
        if self.fail:
            raise RuntimeError("registry store delete faulted")
        self._wrapped.delete(strategy_name)

    def __getattr__(self, item: str) -> Any:
        return getattr(self._wrapped, item)


def test_remove_with_an_open_position_does_not_drop_immediately(
    store: StrategyRegistryStore,
) -> None:
    """Test 1 (D-11) — force-flat FIRST: deactivate, go pending, emit the poll, keep the row."""
    handler, strategy = _handler(store)
    strategy.subscribe_portfolio(UUID(_P1))
    handler.portfolio_read_model = _FakeReadModel(held={_TICKER})

    handler.on_strategy_command(StrategyCommandEvent.remove(strategy_name=_NAME, time=_T))

    assert strategy in handler.strategies
    assert strategy.is_active is False
    assert _NAME in handler._pending_removals
    row = store.get(_NAME)
    assert row is not None
    assert row["enabled"] is False
    assert [type(e) for e in _drain(handler.global_queue)] == [UniversePollEvent]


def test_remove_completes_and_deletes_child_then_parent_once_flat(
    store: StrategyRegistryStore,
) -> None:
    """Test 2 (D-11) — on the flat FILL the object drops and BOTH rows go (no FK error)."""
    handler, strategy = _handler(store)
    read_model = _FakeReadModel(held={_TICKER})
    handler.portfolio_read_model = read_model
    handler.on_strategy_command(StrategyCommandEvent.subscribe_portfolio(
        strategy_name=_NAME, portfolio_id=_P1, time=_T))
    _drain(handler.global_queue)

    handler.on_strategy_command(StrategyCommandEvent.remove(strategy_name=_NAME, time=_T))
    assert store.portfolio_subscriptions(_NAME) == [_P1]  # child row still present, pending

    read_model.held.clear()  # positions went flat
    handler.on_fill(_fill(_TICKER))

    assert strategy not in handler.strategies
    assert _NAME not in handler._pending_removals
    assert store.get(_NAME) is None
    assert store.portfolio_subscriptions(_NAME) == []


def test_remove_with_no_open_position_completes_on_the_same_cycle(
    store: StrategyRegistryStore,
) -> None:
    """Test 3 (D-11) — the flat condition already holds, so it drops + deletes immediately."""
    handler, strategy = _handler(store)
    strategy.subscribe_portfolio(UUID(_P1))
    handler.portfolio_read_model = _FakeReadModel(held=set())  # flat

    handler.on_strategy_command(StrategyCommandEvent.remove(strategy_name=_NAME, time=_T))

    assert strategy not in handler.strategies
    assert _NAME not in handler._pending_removals
    assert store.get(_NAME) is None


def test_remove_keeps_the_row_while_pending_for_crash_safety(
    store: StrategyRegistryStore,
) -> None:
    """Test 4 (D-11) — the row survives while pending; a mid-force-close crash rehydrates it."""
    handler, strategy = _handler(store)
    strategy.subscribe_portfolio(UUID(_P1))
    handler.portfolio_read_model = _FakeReadModel(held={_TICKER})

    handler.on_strategy_command(StrategyCommandEvent.remove(strategy_name=_NAME, time=_T))

    assert store.get(_NAME) is not None  # still present -> restart resumes ownership


def test_second_remove_while_pending_is_a_no_op(store: StrategyRegistryStore) -> None:
    """Test 5 (D-11 idempotency) — no second force-close, no second poll."""
    handler, strategy = _handler(store)
    strategy.subscribe_portfolio(UUID(_P1))
    handler.portfolio_read_model = _FakeReadModel(held={_TICKER})
    handler.on_strategy_command(StrategyCommandEvent.remove(strategy_name=_NAME, time=_T))
    _drain(handler.global_queue)

    handler.on_strategy_command(StrategyCommandEvent.remove(strategy_name=_NAME, time=_T))

    assert _drain(handler.global_queue) == []
    assert strategy in handler.strategies


def test_remove_of_an_unknown_name_is_a_loud_no_op(store: StrategyRegistryStore) -> None:
    """Test 6 (D-11) — an unknown target mutates nothing and never raises."""
    handler, strategy = _handler(store)

    handler.on_strategy_command(StrategyCommandEvent.remove(strategy_name="ghost", time=_T))

    assert strategy in handler.strategies
    assert handler._pending_removals == set()
    assert _drain(handler.global_queue) == []


def test_remove_of_a_pair_force_flats_both_legs_before_dropping(
    store: StrategyRegistryStore,
) -> None:
    """Test 7 (D-16) — a pair holding an open spread stays pending until BOTH legs are flat."""
    handler = StrategiesHandler(
        Queue(), _StubFeed(), InMemorySignalStore(),
        allow_short_selling=True, enable_margin=True)
    handler.registry_store = store
    pair = EthBtcPairStrategy(timeframe="1d")
    handler.add_strategy(pair)
    pair.subscribe_portfolio(UUID(_P1))
    read_model = _FakeReadModel(held={"ETHUSD", "BTCUSD"})
    handler.portfolio_read_model = read_model

    handler.on_strategy_command(StrategyCommandEvent.remove(
        strategy_name=pair.name, time=_T))
    assert pair in handler.strategies  # both legs still held -> pending

    read_model.held.discard("ETHUSD")  # only one leg flat
    handler.on_fill(_fill("ETHUSD"))
    assert pair in handler.strategies  # STILL pending — the other leg is open

    read_model.held.clear()  # both legs flat
    handler.on_fill(_fill("BTCUSD"))
    assert pair not in handler.strategies


def test_disable_neither_force_flats_nor_drops(store: StrategyRegistryStore) -> None:
    """Test 8 (D-11 vs D-07) — the three lifecycle behaviours stay distinct."""
    handler, strategy = _handler(store)
    strategy.subscribe_portfolio(UUID(_P1))
    handler.portfolio_read_model = _FakeReadModel(held={_TICKER})

    handler.on_strategy_command(StrategyCommandEvent.disable(strategy_name=_NAME, time=_T))

    assert strategy in handler.strategies  # NOT dropped
    assert _NAME not in handler._pending_removals  # NOT force-flatting


def test_remove_degrades_cleanly_with_no_store(store: StrategyRegistryStore) -> None:
    """Test 9 (degrade-clean) — with registry_store None, remove drops the live object."""
    handler, strategy = _handler(None)
    # No read model wired either -> nothing to observe, drops directly (backtest arm).

    handler.on_strategy_command(StrategyCommandEvent.remove(strategy_name=_NAME, time=_T))

    assert strategy not in handler.strategies
    assert handler.registry_store is None


def test_a_store_fault_during_removal_completion_mutates_nothing(
    store: StrategyRegistryStore,
) -> None:
    """WR-01 — a store fault at ``delete()`` leaves the removal fully retryable.

    The store delete is the ONLY call in the completion sequence that can raise, so
    it runs BEFORE every in-memory mutation. A fault therefore leaves the strategy
    fully intact — still in the roster AND still pending — rather than half-applied,
    and the next FILL retries cleanly.
    """
    faulty = _FaultyDeleteStore(store)
    handler, strategy = _handler(faulty)
    # Flat -> completion is attempted synchronously on the verb.
    handler.portfolio_read_model = _FakeReadModel(held=set())

    with pytest.raises(RuntimeError):
        handler.on_strategy_command(
            StrategyCommandEvent.remove(strategy_name=_NAME, time=_T))

    # THE falsifying pair: before the raising call was ordered first, the roster drop
    # had already run by the time delete() faulted, so both of these were FALSE.
    assert strategy in handler.strategies
    assert _NAME in handler._pending_removals

    # Once the store recovers, the next FILL completes the removal cleanly.
    faulty.fail = False
    handler.on_fill(_fill())

    assert strategy not in handler.strategies
    assert _NAME not in handler._pending_removals
    assert store.get(_NAME) is None


def test_min_timeframe_is_recomputed_after_a_remove(store: StrategyRegistryStore) -> None:
    """Removing the only strategy at the minimum must not leave min_timeframe stale."""
    handler, strategy = _handler(store)
    handler.portfolio_read_model = _FakeReadModel(held=set())  # flat -> immediate drop
    assert handler.min_timeframe == timedelta(days=1)

    handler.on_strategy_command(StrategyCommandEvent.remove(strategy_name=_NAME, time=_T))

    assert handler.min_timeframe is None  # empty roster -> legal None seed (IN-06)

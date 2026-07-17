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
``calculate_signals`` loop, so a disabled strategy's indicator state FREEZES; re-enabling
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
from itrader.strategy_handler.storage import InMemorySignalStore
from itrader.strategy_handler.strategies_handler import StrategiesHandler
from tests.support.schema import provision_schema

pytestmark = pytest.mark.unit

_T = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
_TICKER = "BTCUSD"
_OTHER = "ETHUSD"
_NAME = "verb_probe"
_WARMUP = 3
# Portfolio ids arrive as STRINGS in the untrusted payload (and are stored as String),
# but `subscribed_portfolios` is typed `list[PortfolioId | int]` and calculate_signals
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

    The D-07 guard is first in ``calculate_signals``, so a disabled strategy's indicator
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

    ``calculate_signals`` casts each entry of ``subscribed_portfolios`` straight onto
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


def test_verbs_deferred_to_later_plans_are_no_ops_here(
    store: StrategyRegistryStore,
) -> None:
    """``add``/``remove``/``reconfigure`` land in Plans 07/08 — inert, never a raise."""
    handler, _strategy = _handler(store)

    for event in (
        StrategyCommandEvent.remove(strategy_name=_NAME, time=_T),
        StrategyCommandEvent.reconfigure(
            strategy_name=_NAME, config={"timeframe": "1h"}, time=_T),
    ):
        handler.on_strategy_command(event)

    assert store.get(_NAME) is None
    assert _drain(handler.global_queue) == []

from datetime import datetime
from decimal import Decimal
from queue import Queue

import pytest

from itrader.execution_handler.base import AbstractExecutionHandler
from itrader.execution_handler.execution_handler import (
    DEFAULT_ACCOUNT_ID,
    ExecutionHandler,
)
from itrader.events_handler.events import FillEvent, OrderEvent
from itrader.core.enums import FillStatus, OrderType, Side
from itrader.core.exceptions.portfolio import PortfolioNotFoundError


@pytest.fixture
def env():
    """ExecutionHandler with its queue plus a market BUY order event."""
    queue = Queue()
    execution_handler = ExecutionHandler(queue)
    order_event = OrderEvent(
        time=datetime(2024, 1, 1),
        ticker="BTCUSDT",
        action=Side.BUY,
        price=100.0,
        quantity=1.0,
        exchange="paper",
        strategy_id=1,
        portfolio_id=1,
        order_type=OrderType.MARKET,
        order_id=1,
    )
    yield queue, execution_handler, order_event
    while not queue.empty():
        queue.get_nowait()


def test_execution_handler_initialization(env):
    _queue, execution_handler, _order_event = env
    assert isinstance(execution_handler, ExecutionHandler)


def test_on_order_rests_then_fill_arrives_with_next_bar(env, make_bar):
    """D-01/D-13: routing a NEW market order produces NO same-drain fill —
    the order rests and fills at the next routed bar's open."""
    queue, execution_handler, order_event = env
    execution_handler.on_order(order_event)
    assert queue.qsize() == 0          # rests; no immediate FillEvent

    bar = make_bar(open_=101.5, high=103, low=99, close=102,
                   time=datetime(2024, 1, 2))
    execution_handler.on_market_data(bar)
    fill_event: FillEvent = queue.get(False)
    assert isinstance(fill_event, FillEvent)
    assert fill_event.action is Side.BUY
    assert fill_event.status is FillStatus.EXECUTED
    assert fill_event.price == Decimal("101.5")   # the bar's open, exact
    assert fill_event.time == bar.time            # stamped T+1tf


def test_abstract_execution_handler_is_real_abc():
    """AbstractExecutionHandler is a real ABC (D-21/#39): both event hooks
    are abstract and the base class cannot be instantiated."""
    with pytest.raises(TypeError):
        AbstractExecutionHandler()  # type: ignore[abstract]

    assert getattr(AbstractExecutionHandler.on_order, '__isabstractmethod__', False)
    assert getattr(AbstractExecutionHandler.on_market_data, '__isabstractmethod__', False)


def test_execution_handler_implements_both_hooks(env):
    """The concrete ExecutionHandler satisfies the ABC contract."""
    _queue, execution_handler, _order_event = env
    assert isinstance(execution_handler, AbstractExecutionHandler)


def test_no_config_construction_admits_btcusd(env):
    """TEMPORARY BTCUSD backward-compat fallback (D-13, Trap 1; Wave 4 removes it).

    With NO ``exchange_config`` supplied, ``ExecutionHandler(global_queue)`` must
    still seed the COMPLETE default-preset ∪ {BTCUSD} set at construction so the
    direct-construction oracle/integration path (which lost the removed hardcoded
    ``register_symbol('BTCUSD')`` line) stays byte-exact. Seeding the complete set
    at construction is replacement-safe: a later ``update_config`` re-derivation
    can never silently wipe BTCUSD.
    """
    _queue, execution_handler, _order_event = env
    exchange = execution_handler.exchanges[('paper', DEFAULT_ACCOUNT_ID)]
    assert 'BTCUSD' in exchange._supported_symbols
    # The default preset symbols must remain admitted (the union, not a replacement).
    assert {'BTCUSDT', 'ETHUSDT', 'ADAUSDT', 'DOTUSDT', 'SOLUSDT'} <= exchange._supported_symbols


# --------------------------------------------------------------------------
# D-27 / MPORT-07 — the exchange registry is keyed on the (venue, account_id)
# PAIR. These unit cases pin the registry shape and the account-resolving
# route; the full cross-account routing gate (positive + negative + miss +
# refusal + dedup non-collapse) lives in
# tests/integration/test_per_account_exchange_routing.py.
# --------------------------------------------------------------------------


class _RecordingExchange:
    """A real recording object — deliberately NOT a Mock.

    A ``Mock`` satisfies ``assert_called_once`` while proving nothing about
    WHICH key resolved, so these tests use distinct instances with
    per-instance lists and assert on list contents.
    """

    def __init__(self):
        self.orders = []
        self.bars = []

    def on_order(self, event):
        self.orders.append(event)

    def on_market_data(self, bar):
        self.bars.append(bar)


class _StubReadModel:
    """Minimal ``PortfolioReadModel`` stand-in exposing only ``account_for``."""

    def __init__(self, mapping):
        self._mapping = mapping

    def account_for(self, portfolio_id):
        if portfolio_id not in self._mapping:
            raise PortfolioNotFoundError(portfolio_id)
        return self._mapping[portfolio_id]


def _order_for(portfolio_id, exchange='paper'):
    return OrderEvent(
        time=datetime(2024, 1, 1),
        ticker="BTCUSDT",
        action=Side.BUY,
        price=100.0,
        quantity=1.0,
        exchange=exchange,
        strategy_id=1,
        portfolio_id=portfolio_id,
        order_type=OrderType.MARKET,
        order_id=1,
    )


def test_registry_is_pair_keyed_with_no_venue_aliases(env):
    """D-05: venue ALIASING is retired — one venue name, one key, one object.

    This test asserts the INVERSE of what it did before the rename. It used to
    pin that ``'simulated'`` and ``'csv'`` resolved to the SAME object; D-05
    deleted that aliasing in full (along with the dead ``'ccxt': None``
    placeholder), so the registry ``init_exchanges`` returns is a SINGLE
    ``('paper', DEFAULT_ACCOUNT_ID)`` entry and no two keys may share an
    exchange object.

    It goes RED if a future phase reintroduces a venue synonym — which is the
    point: an alias is invisible in a single-account backtest (both keys reach
    the same object, every number is identical) and only bites under
    multi-account live.
    """
    _queue, execution_handler, _order_event = env
    assert all(isinstance(key, tuple) and len(key) == 2
               for key in execution_handler.exchanges)
    assert list(execution_handler.exchanges) == [('paper', DEFAULT_ACCOUNT_ID)]
    assert execution_handler.exchanges[('paper', DEFAULT_ACCOUNT_ID)] is not None
    # No two keys resolve to one object — stated structurally so it still holds
    # if a later plan legitimately registers more venues.
    resolved = [ex for ex in execution_handler.exchanges.values() if ex is not None]
    assert len({id(ex) for ex in resolved}) == len(resolved)


def test_dedup_drives_an_object_shared_by_two_accounts_once_per_bar(env, make_bar):
    """The identity dedup's REMAINING case: one object under two ACCOUNTS.

    D-05 deleted the venue-alias case this test used to cover (two venue names
    onto one object). What survives is the account case — a caller may register
    the same exchange object under two accounts of one venue — and that object
    must still be driven exactly ONCE per bar, or its resting-order book is
    matched twice and every backtest number moves.
    """
    _queue, execution_handler, _order_event = env
    shared = _RecordingExchange()
    execution_handler.exchanges = {
        ('paper', 'a'): shared,
        ('paper', 'b'): shared,
    }
    execution_handler.on_market_data(
        make_bar(open_=1, high=2, low=1, close=2, time=datetime(2024, 1, 2)))
    assert len(shared.bars) == 1


def test_distinct_per_account_exchanges_are_both_driven(env, make_bar):
    """Two ACCOUNTS on one venue are two distinct objects with distinct
    identity — the dedup must NOT collapse them; each account has its own
    resting state and must see every bar."""
    _queue, execution_handler, _order_event = env
    ex_a, ex_b = _RecordingExchange(), _RecordingExchange()
    execution_handler.exchanges = {
        ('paper', 'a'): ex_a,
        ('paper', 'b'): ex_b,
    }
    execution_handler.on_market_data(
        make_bar(open_=1, high=2, low=1, close=2, time=datetime(2024, 1, 2)))
    assert len(ex_a.bars) == 1
    assert len(ex_b.bars) == 1


def test_on_order_routes_to_the_resolved_accounts_exchange(env):
    """An order for the portfolio mapped to account 'a' reaches exchange A and
    provably NOT exchange B."""
    _queue, execution_handler, _order_event = env
    ex_a, ex_b = _RecordingExchange(), _RecordingExchange()
    execution_handler.exchanges = {
        ('paper', 'a'): ex_a,
        ('paper', 'b'): ex_b,
    }
    execution_handler._portfolio_read_model = _StubReadModel({1: 'a', 2: 'b'})

    execution_handler.on_order(_order_for(1))
    assert len(ex_a.orders) == 1
    assert ex_b.orders == []


def test_on_order_unknown_pair_touches_no_exchange(env):
    """MPORT-07: an unresolvable pair must NEVER fall back to a bare-venue
    match — that fallback IS the vulnerability this requirement closes."""
    _queue, execution_handler, _order_event = env
    ex_a, ex_b = _RecordingExchange(), _RecordingExchange()
    execution_handler.exchanges = {
        ('paper', 'a'): ex_a,
        ('paper', 'b'): ex_b,
    }
    execution_handler._portfolio_read_model = _StubReadModel({1: 'c'})

    execution_handler.on_order(_order_for(1))
    assert ex_a.orders == []
    assert ex_b.orders == []


def test_on_order_refuses_when_the_portfolio_names_no_account(env):
    """``account_for`` returning ``None`` is a LOUD REFUSAL, never a silent
    fall-through to the default account's session."""
    _queue, execution_handler, _order_event = env
    ex_default = _RecordingExchange()
    execution_handler.exchanges = {
        ('paper', DEFAULT_ACCOUNT_ID): ex_default,
    }
    execution_handler._portfolio_read_model = _StubReadModel({1: None})

    execution_handler.on_order(_order_for(1))
    assert ex_default.orders == []


def test_on_order_without_read_model_uses_the_default_account(env):
    """The backtest path injects no read-model and resolves the default
    account unconditionally — the oracle route is untouched."""
    _queue, execution_handler, _order_event = env
    ex_default = _RecordingExchange()
    execution_handler.exchanges = {
        ('paper', DEFAULT_ACCOUNT_ID): ex_default,
    }
    assert execution_handler._portfolio_read_model is None

    execution_handler.on_order(_order_for(1))
    assert len(ex_default.orders) == 1


def test_on_order_unknown_portfolio_is_distinguishable_from_a_fault(env, caplog):
    """``account_for`` raising ``PortfolioNotFoundError`` gets its OWN logged
    branch — the broad handler would otherwise report it as an internal fault."""
    _queue, execution_handler, _order_event = env
    ex_a = _RecordingExchange()
    execution_handler.exchanges = {('paper', 'a'): ex_a}
    execution_handler._portfolio_read_model = _StubReadModel({1: 'a'})

    execution_handler.on_order(_order_for(99))
    assert ex_a.orders == []

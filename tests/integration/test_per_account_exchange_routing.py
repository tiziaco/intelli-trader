"""The MPORT-07 routing gate: an account's orders never reach another account's exchange.

**The gap this closes.** Before D-27 the execution registry was keyed by bare
VENUE NAME while a live exchange holds exactly ONE authenticated connector. Two
portfolios trading one venue under two different accounts therefore resolved to
the SAME exchange object, and account B's orders were submitted through account
A's authenticated session — with per-account credentials, per-account venue
accounts and the distinct-account invariant all correct. That is a real-money
wrong answer, and it is silent.

**The mechanism under test.** ``ExecutionHandler.exchanges`` is keyed on the
``(venue, account_id)`` PAIR, and ``on_order`` resolves the account half from
the order's PORTFOLIO through the injected ``PortfolioReadModel``. Every failure
path is fail-closed: an unregistered pair, or a portfolio naming no account,
logs and returns rather than falling back to a bare-venue-name match.

**Why this test does NOT use the paper venue.** The live composition root takes
ONE venue string, builds ONE venue spec and performs a SINGLE registration write
gated on a non-None connector. It structurally cannot register two accounts on
one venue — that capability is plan 11-07 — and a paper-shaped bundle
(``connector=None``) never reaches the registration write at all. A paper-based
test here would pass while proving nothing, which is worse than no test. So the
gate constructs ``ExecutionHandler`` DIRECTLY and writes two recording exchanges
under two account halves of one venue. Plan 11-11 owns the paper lifecycle and
restart path; it cannot gate MPORT-07.

**Why the doubles are real objects, not Mocks.** A ``Mock`` satisfies
``assert_called_once`` while proving nothing about WHICH key resolved. These
doubles are real classes with per-instance lists, so every assertion is about
the contents of a specific instance's list.

Indentation: 4-space. The ``integration`` marker is folder-derived, so this file
declares no marker of its own, and ``tests/integration/`` has no ``__init__.py``.
"""

from datetime import datetime
from queue import Queue

import pytest

from itrader.core.enums import OrderType, Side
from itrader.core.exceptions.portfolio import PortfolioNotFoundError
from itrader.events_handler.events import OrderEvent
from itrader.execution_handler.execution_handler import (
    DEFAULT_ACCOUNT_ID,
    ExecutionHandler,
)

from tests.support.venue_wiring import backtest_venue_bundles

_VENUE = "okxlike"
_PF_A = 101
_PF_B = 202
_PF_UNMAPPED = 303
_PF_NO_ACCOUNT = 404
_PF_UNKNOWN = 505


class _RecordingExchange:
    """A per-account exchange stand-in that records what it was handed.

    One instance per ACCOUNT — distinct objects with distinct identity, which
    is exactly what the pair-keyed registry produces and what the identity
    dedup in ``on_market_data`` must NOT collapse.
    """

    def __init__(self, label):
        self.label = label
        self.orders = []
        self.bars = []

    def on_order(self, event):
        self.orders.append(event)

    def on_market_data(self, bar):
        self.bars.append(bar)


class _StubReadModel:
    """A ``PortfolioReadModel`` stand-in exposing only ``account_for``.

    Maps TWO portfolios to TWO accounts. A one-account stub could not fail
    this test — the whole point is that two portfolios resolve differently.
    """

    def __init__(self, mapping):
        self._mapping = mapping

    def account_for(self, portfolio_id):
        if portfolio_id not in self._mapping:
            raise PortfolioNotFoundError(portfolio_id)
        return self._mapping[portfolio_id]


@pytest.fixture
def routing_env():
    """An ExecutionHandler with TWO accounts registered on ONE venue.

    Built by direct construction — see the module docstring for why the live
    composition root cannot produce this shape until plan 11-07.
    """
    queue = Queue()
    handler = ExecutionHandler(queue, venue_bundles=backtest_venue_bundles(queue))
    exchange_a = _RecordingExchange("a")
    exchange_b = _RecordingExchange("b")
    handler.exchanges = {
        (_VENUE, "a"): exchange_a,
        (_VENUE, "b"): exchange_b,
    }
    handler._portfolio_read_model = _StubReadModel({
        _PF_A: "a",
        _PF_B: "b",
        _PF_UNMAPPED: "c",        # an account with NO registered exchange
        _PF_NO_ACCOUNT: None,     # a portfolio naming no account at all
    })
    yield handler, exchange_a, exchange_b
    while not queue.empty():
        queue.get_nowait()


def _order_for(portfolio_id, venue=_VENUE):
    return OrderEvent(
        time=datetime(2024, 1, 1),
        ticker="BTCUSDT",
        action=Side.BUY,
        price=100.0,
        quantity=1.0,
        exchange=venue,
        strategy_id=1,
        portfolio_id=portfolio_id,
        order_type=OrderType.MARKET,
        order_id=1,
    )


def test_two_accounts_on_one_venue_are_two_distinct_exchange_objects(routing_env):
    """The registry holds two SEPARATE objects, not one shared one.

    This is the structural premise of MPORT-07: a shared object cannot
    subscribe to two accounts' private fill streams at all.
    """
    handler, exchange_a, exchange_b = routing_env
    assert handler.exchanges[(_VENUE, "a")] is not handler.exchanges[(_VENUE, "b")]
    assert handler.exchanges[(_VENUE, "a")] is exchange_a
    assert handler.exchanges[(_VENUE, "b")] is exchange_b


def test_order_for_account_a_reaches_a_and_provably_not_b(routing_env):
    """POSITIVE + NEGATIVE. The negative is the load-bearing half: asserting
    only that A received the order would pass even if BOTH received it."""
    handler, exchange_a, exchange_b = routing_env
    handler.on_order(_order_for(_PF_A))
    assert len(exchange_a.orders) == 1
    assert exchange_b.orders == []


def test_order_for_account_b_reaches_b_and_provably_not_a(routing_env):
    """The reverse direction. Both directions are required: an implementation
    that hardcoded the first registered exchange would pass the A case alone."""
    handler, exchange_a, exchange_b = routing_env
    handler.on_order(_order_for(_PF_B))
    assert len(exchange_b.orders) == 1
    assert exchange_a.orders == []


def test_unregistered_account_reaches_neither_exchange(routing_env):
    """THE MOST IMPORTANT ASSERTION IN THIS FILE.

    A portfolio resolving to account 'c', which has no registered exchange,
    must reach NEITHER exchange. This is what kills a future "fall back to the
    bare venue name to be safe" regression — such a fallback would find a
    ``(venue, *)`` match and submit the order through some other account's
    authenticated session. Failing closed is correct: not submitting is
    strictly better than submitting through a guessed session.
    """
    handler, exchange_a, exchange_b = routing_env
    handler.on_order(_order_for(_PF_UNMAPPED))
    assert exchange_a.orders == []
    assert exchange_b.orders == []


def test_portfolio_naming_no_account_is_refused_not_defaulted(routing_env):
    """``account_for`` returning ``None`` is a LOUD REFUSAL.

    Pins the policy against the natural-looking
    ``account_for(...) or DEFAULT_ACCOUNT_ID`` repair, which would route a
    live portfolio that names no account through whatever session is
    registered as the default. Plan 11-08 makes ``account_id`` mandatory at
    composition time; until then this refusal IS the guard.
    """
    handler, exchange_a, exchange_b = routing_env
    default_exchange = _RecordingExchange("default")
    handler.exchanges[(_VENUE, DEFAULT_ACCOUNT_ID)] = default_exchange

    handler.on_order(_order_for(_PF_NO_ACCOUNT))

    assert default_exchange.orders == []
    assert exchange_a.orders == []
    assert exchange_b.orders == []


def test_unknown_portfolio_reaches_no_exchange(routing_env):
    """An unresolvable portfolio fails closed rather than escaping as an
    unhandled exception out of the event route."""
    handler, exchange_a, exchange_b = routing_env
    handler.on_order(_order_for(_PF_UNKNOWN))
    assert exchange_a.orders == []
    assert exchange_b.orders == []


def test_identity_dedup_does_not_collapse_distinct_per_account_exchanges(
        routing_env, make_bar):
    """The ``on_market_data`` identity dedup exists to collapse ALIASES (two
    keys pointing at ONE object). Two ACCOUNTS are two objects with distinct
    identity, so BOTH must see every bar — each owns its own resting-order
    book and correlation index."""
    handler, exchange_a, exchange_b = routing_env
    bar = make_bar(open_=101.5, high=103, low=99, close=102,
                   time=datetime(2024, 1, 2))
    handler.on_market_data(bar)
    assert len(exchange_a.bars) == 1
    assert len(exchange_b.bars) == 1


def test_dedup_still_collapses_two_keys_onto_one_object(
        routing_env, make_bar):
    """The complement of the case above, and the reason the dedup must stay
    identity-based: driving one shared exchange twice per bar would double-match
    its resting-order book and silently change every backtest number.

    D-05 retired venue ALIASING (two venue names, one object), so the two keys
    here are two ACCOUNTS on the paper venue — the shape that still exists. They
    MUST be distinct keys: writing the same key twice would collapse the literal
    to a single entry and the test would pass without the dedup running at all.
    """
    handler, _exchange_a, _exchange_b = routing_env
    shared = _RecordingExchange("shared")
    handler.exchanges = {
        ("paper", "acct-1"): shared,
        ("paper", "acct-2"): shared,
    }
    # Guard the premise: two DISTINCT keys really did survive into the registry.
    assert len(handler.exchanges) == 2
    handler.on_market_data(
        make_bar(open_=1, high=2, low=1, close=2, time=datetime(2024, 1, 2)))
    assert len(shared.bars) == 1

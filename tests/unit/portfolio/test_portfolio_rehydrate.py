"""``rehydrate_portfolios`` — definition rows become live portfolios (D-08/MPORT-03).

The collaborator is driven against a REAL ``PortfolioHandler`` (the thing whose
``add_portfolio`` contract is under test) with a FAKE store (a plain object satisfying the
``PortfolioDefinitionReader`` Protocol), so these stay unit tests with no SQL. The boot-level
wiring — that ``build_live_system`` actually CALLS this — is gated separately in
``tests/integration/test_distinct_account_invariant.py``; a library function proven correct
while production never calls it is the exact trap this phase keeps setting.

4-space indentation. ``tests/unit/portfolio/`` HAS an ``__init__.py`` (do not remove it);
the ``unit`` marker is folder-derived.
"""

import queue
import uuid
from decimal import Decimal
from typing import Any, Mapping

import pytest

from itrader.core.enums import PortfolioState
from itrader.core.ids import PortfolioId
from itrader.portfolio_handler.portfolio_handler import PortfolioHandler
from itrader.portfolio_handler.rehydrate.portfolio_rehydrate import rehydrate_portfolios
from tests.support.venue_wiring import backtest_portfolio_handler


class _FakeDefinitionStore:
    """A ``PortfolioDefinitionReader`` over hand-built rows (no SQL).

    ``read_all()`` mirrors the real store's public dict shape, including its
    ``portfolio_id`` ASC ordering contract — the rows are handed over pre-sorted so a
    reordering regression in the caller would be visible.
    """

    def __init__(self, rows: list[Mapping[str, Any]]) -> None:
        self._rows = rows
        self.read_count = 0

    def read_all(self) -> list[Mapping[str, Any]]:
        self.read_count += 1
        return list(self._rows)


def _row(
    *,
    portfolio_id: uuid.UUID,
    name: str = "pf",
    venue_name: str = "okx",
    account_id: str = "acct-a",
    initial_cash: Decimal = Decimal("10000.00"),
    enabled: bool = True,
) -> dict[str, Any]:
    """One definition row in the store's public read shape."""
    return {
        "portfolio_id": portfolio_id,
        "name": name,
        "venue_name": venue_name,
        "account_id": account_id,
        "initial_cash": initial_cash,
        "enabled": enabled,
        "config": None,
        "updated_at": None,
    }


@pytest.fixture()
def handler() -> PortfolioHandler:
    """A real handler on the BACKTEST arm — no SQL, no definition store, no writer.

    The rehydrate contract under test is "rows in, portfolios out"; the durable write-back
    is 11-08's separate writer gate. Using the backtest arm keeps these tests SQL-free.
    """
    return backtest_portfolio_handler(queue.Queue(), environment="backtest", sql_engine=None)


# --------------------------------------------------------------------------- #
# MPORT-03 — the empty edge
# --------------------------------------------------------------------------- #
def test_zero_definition_rows_creates_nothing_and_does_not_raise(handler) -> None:
    """A fresh database is a VALID first-start state, not a failure.

    This is today's behaviour for every existing live test, which is what makes
    construction-time rehydrate safe to land — but it must not regress into a raise.
    """
    store = _FakeDefinitionStore([])

    assert rehydrate_portfolios(store=store, portfolio_handler=handler) == []
    assert handler._portfolios == {}
    assert store.read_count == 1


# --------------------------------------------------------------------------- #
# T-11-41 — the PERSISTED id is the whole point
# --------------------------------------------------------------------------- #
def test_a_rehydrated_portfolio_keeps_its_persisted_id(handler) -> None:
    """THE gate: the rebuilt portfolio's id EQUALS the row's id.

    A rehydrate that minted fresh ids would look completely healthy — right count, right
    names, right cash — while every child-table row from the previous run orphaned and
    every persisted strategy subscription dangled.
    """
    persisted = uuid.uuid4()
    store = _FakeDefinitionStore([_row(portfolio_id=persisted, name="pf-a")])

    rehydrated = rehydrate_portfolios(store=store, portfolio_handler=handler)

    assert rehydrated == [PortfolioId(persisted)]
    assert list(handler._portfolios) == [PortfolioId(persisted)]
    portfolio = handler.get_portfolio(PortfolioId(persisted))
    assert portfolio.portfolio_id == persisted
    assert portfolio.name == "pf-a"


def test_the_account_reference_and_venue_come_from_the_row(handler) -> None:
    """``account_id`` / ``venue_name`` are threaded through, and venue drives exchange.

    D-07: there is deliberately no ``exchange`` column, so ``venue_name`` is the single
    source of truth for the portfolio's venue — a second source could drift with no
    tiebreaker.
    """
    persisted = uuid.uuid4()
    store = _FakeDefinitionStore([
        _row(portfolio_id=persisted, venue_name="okx", account_id="acct-live"),
    ])

    rehydrate_portfolios(store=store, portfolio_handler=handler)

    portfolio = handler.get_portfolio(PortfolioId(persisted))
    assert portfolio.account_id == "acct-live"
    assert portfolio.venue_name == "okx"
    assert portfolio.exchange == "okx"


def test_initial_cash_arrives_as_exact_decimal(handler) -> None:
    """Money enters through ``to_money``, never a float constructor."""
    persisted = uuid.uuid4()
    store = _FakeDefinitionStore([
        _row(portfolio_id=persisted, initial_cash=Decimal("12345.67")),
    ])

    rehydrate_portfolios(store=store, portfolio_handler=handler)

    cash = handler.get_portfolio(PortfolioId(persisted)).cash
    assert isinstance(cash, Decimal)
    assert cash == Decimal("12345.67")


# --------------------------------------------------------------------------- #
# MPORT-03 — the adjacency edge
# --------------------------------------------------------------------------- #
def test_two_same_venue_different_account_rows_both_rehydrate(handler) -> None:
    """Same-venue portfolios SEPARATE, they do not collide.

    Identity is the ``(venue_name, account_id)`` PAIR. Two portfolios on one venue under
    two different accounts are two different accounts, and both must trade.
    """
    first, second = sorted([uuid.uuid4(), uuid.uuid4()])
    store = _FakeDefinitionStore([
        _row(portfolio_id=first, name="pf-a", venue_name="okx", account_id="acct-a"),
        _row(portfolio_id=second, name="pf-b", venue_name="okx", account_id="acct-b"),
    ])

    rehydrated = rehydrate_portfolios(store=store, portfolio_handler=handler)

    assert rehydrated == [PortfolioId(first), PortfolioId(second)]
    assert len(handler._portfolios) == 2
    assert {
        handler.get_portfolio(PortfolioId(pid)).account_id for pid in (first, second)
    } == {"acct-a", "acct-b"}


def test_registration_order_follows_the_stores_ordering_contract(handler) -> None:
    """Rows are registered in the order ``read_all()`` yields them (portfolio_id ASC).

    The store documents that ordering so registration — and therefore anything derived
    from it — is reproducible across runs and dialects.
    """
    ids = sorted([uuid.uuid4() for _ in range(3)])
    store = _FakeDefinitionStore([
        _row(portfolio_id=pid, name=f"pf-{index}", account_id=f"acct-{index}")
        for index, pid in enumerate(ids)
    ])

    rehydrated = rehydrate_portfolios(store=store, portfolio_handler=handler)

    assert rehydrated == [PortfolioId(pid) for pid in ids]
    assert list(handler._portfolios) == [PortfolioId(pid) for pid in ids]


# --------------------------------------------------------------------------- #
# CR-01 — `enabled` is runtime state, not a load filter
# --------------------------------------------------------------------------- #
def test_a_disabled_row_loads_present_but_inactive(handler) -> None:
    """A disabled row is reconstructed INACTIVE, never dropped.

    Dropping it would orphan its open positions and its cash and make the portfolio
    unreachable across the restart — the same reasoning the strategy registry applies to
    a disabled strategy, with more force because a portfolio holds money.
    """
    persisted = uuid.uuid4()
    store = _FakeDefinitionStore([_row(portfolio_id=persisted, enabled=False)])

    rehydrated = rehydrate_portfolios(store=store, portfolio_handler=handler)

    assert rehydrated == [PortfolioId(persisted)]
    portfolio = handler.get_portfolio(PortfolioId(persisted))
    assert portfolio.state is PortfolioState.INACTIVE


def test_an_enabled_row_loads_active(handler) -> None:
    """The control for the case above — the enabled path is untouched."""
    persisted = uuid.uuid4()
    store = _FakeDefinitionStore([_row(portfolio_id=persisted, enabled=True)])

    rehydrate_portfolios(store=store, portfolio_handler=handler)

    assert handler.get_portfolio(PortfolioId(persisted)).state is PortfolioState.ACTIVE


# --------------------------------------------------------------------------- #
# Idempotence within a boot
# --------------------------------------------------------------------------- #
def test_rehydrating_twice_does_not_duplicate_or_raise(handler) -> None:
    """A second pass skips already-registered ids.

    ``add_portfolio`` loud-rejects a duplicate id (11-05, so a re-add cannot silently
    destroy the first portfolio's cash and positions), which means without the skip guard
    a second rehydrate would RAISE rather than no-op.
    """
    persisted = uuid.uuid4()
    store = _FakeDefinitionStore([_row(portfolio_id=persisted)])

    first = rehydrate_portfolios(store=store, portfolio_handler=handler)
    second = rehydrate_portfolios(store=store, portfolio_handler=handler)

    assert first == [PortfolioId(persisted)]
    assert second == []
    assert len(handler._portfolios) == 1


# --------------------------------------------------------------------------- #
# Infrastructure failures are LOUD
# --------------------------------------------------------------------------- #
def test_an_unreadable_store_propagates_rather_than_booting_empty(handler) -> None:
    """A store fault is a WIRING problem — it must not degrade into zero portfolios.

    An engine that boots holding no portfolios reconciles nothing and cannot manage out
    the positions it actually owns, while looking entirely healthy.
    """
    class _BrokenStore:
        def read_all(self) -> list[Mapping[str, Any]]:
            raise RuntimeError("store is unreachable")

    with pytest.raises(RuntimeError, match="unreachable"):
        rehydrate_portfolios(store=_BrokenStore(), portfolio_handler=handler)

    assert handler._portfolios == {}

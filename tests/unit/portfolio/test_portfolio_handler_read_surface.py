"""PortfolioHandler public read surface — ACCT-08 / D-41 / 11-REVIEW WR-09.

Every consumer that reached for the handler's private ``_portfolios`` dict wanted one
of two questions answered that no PUBLIC accessor gave: *all* portfolios (regardless of
state) or *is this id registered*. ``get_active_portfolios()`` answers a DIFFERENT
question (ACTIVE only). This suite pins ``all_portfolios()`` / ``has_portfolio()`` as the
public read surface — the same surface the FastAPI layer reads through — including the
mutation-isolation guarantee that an accessor must not hand out a mutable alias of the
private registry.
"""

from queue import Queue

import pytest

from itrader.core.enums import PortfolioState
from tests.support.venue_wiring import backtest_portfolio_handler


@pytest.fixture
def handler():
    """A backtest PortfolioHandler over an empty in-memory registry."""
    return backtest_portfolio_handler(
        global_queue=Queue(),
        config_dir="settings",
        environment="test",
    )


def test_all_portfolios_empty_returns_empty_mapping_not_none(handler):
    """An empty registry yields an empty mapping, never ``None``."""
    result = handler.all_portfolios()
    assert result is not None
    assert len(result) == 0


def test_all_portfolios_returns_every_state_keyed_by_id(handler):
    """``all_portfolios()`` returns EVERY registered portfolio, active or not, keyed by id."""
    p_active = handler.add_portfolio("Active", "NYSE", 10000.0)
    p_inactive = handler.add_portfolio("Inactive", "NYSE", 20000.0)
    handler.get_portfolio(p_inactive).set_state(PortfolioState.INACTIVE)

    result = handler.all_portfolios()

    assert set(result.keys()) == {p_active, p_inactive}
    assert result[p_active].portfolio_id == p_active
    assert result[p_inactive].portfolio_id == p_inactive


def test_all_portfolios_is_superset_of_active(handler):
    """``all_portfolios()`` includes portfolios ``get_active_portfolios()`` filters out."""
    p_active = handler.add_portfolio("Active", "NYSE", 10000.0)
    p_inactive = handler.add_portfolio("Inactive", "NYSE", 20000.0)
    handler.get_portfolio(p_inactive).set_state(PortfolioState.INACTIVE)

    active_ids = {p.portfolio_id for p in handler.get_active_portfolios()}
    all_ids = set(handler.all_portfolios().keys())

    assert active_ids == {p_active}
    assert all_ids == {p_active, p_inactive}


def test_all_portfolios_mutation_isolation(handler):
    """Mutating the returned mapping must NOT mutate the handler's registry.

    An accessor that lets a caller mutate the private dict is the reach-in with extra
    steps — the exact prohibition D-41 pins.
    """
    p = handler.add_portfolio("One", "NYSE", 10000.0)

    returned = handler.all_portfolios()
    returned.clear()  # nuke the caller's copy
    returned["poison"] = "not a portfolio"

    # Registry is untouched.
    assert handler.has_portfolio(p)
    assert set(handler.all_portfolios().keys()) == {p}
    assert "poison" not in handler.all_portfolios()


def test_has_portfolio_true_only_for_registered_id(handler):
    """``has_portfolio(pid)`` is True iff ``pid`` is a key of ``all_portfolios()``."""
    p = handler.add_portfolio("One", "NYSE", 10000.0)

    assert handler.has_portfolio(p) is True
    assert (p in handler.all_portfolios()) is True

    # An id that was never registered.
    assert handler.has_portfolio(999999) is False
    assert (999999 in handler.all_portfolios()) is False


def test_has_portfolio_false_for_deleted_id(handler):
    """A registered-then-deleted id reports False and drops from ``all_portfolios()``."""
    p = handler.add_portfolio("Doomed", "NYSE", 10000.0)
    assert handler.has_portfolio(p) is True

    handler.delete_portfolio(p, force=True)

    assert handler.has_portfolio(p) is False
    assert p not in handler.all_portfolios()
    # Adjacency invariant holds across the delete.
    assert handler.has_portfolio(p) == (p in handler.all_portfolios())

"""ACCT-10 / D-30 / D-32 — pause, resume and retire PERSIST and survive a restart.

The defect this closes (WR-04). Before this plan the ``enabled=True`` hardcode in the
definition write was the ONLY writer of the column, nothing ever wrote ``enabled=False``, and
``delete_portfolio`` flipped to ARCHIVED and dropped the in-memory entry but NEVER touched the
definition store. So a portfolio an operator DELIBERATELY stopped came back ACTIVE and trading
on the next restart, and a "deleted" portfolio returned with its persisted id and its child
tables reattached. Both are money-relevant and silent.

This exercises the full round trip on the REAL SQL spine (a "restart" is a second
``PortfolioHandler`` over the SAME engine + ``rehydrate_portfolios``):

  create -> deactivate -> restart -> rehydrates INACTIVE
         -> activate   -> restart -> rehydrates ACTIVE
         -> delete     -> restart -> does NOT rehydrate (row + history survive)
         -> a SUCCESSOR portfolio claims the released (venue, account_id) pair.

D-30: pause/resume is ONE handler operation (durable write + in-memory flip), ordered so the
state surviving any crash is always "stopped". D-32: ``enabled`` = PAUSED (keeps its account),
``is_deleted`` = RETIRED (releases the pair). D-33: disabling a portfolio never touches its
venue account.

4-space indentation (matches ``tests/integration/*``); NO ``__init__.py`` in this dir.
Folder-derived ``integration`` marker.
"""

import queue
import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from itrader.config.sql import SqlSettings
from itrader.core.enums import PortfolioState
from itrader.portfolio_handler.portfolio_handler import PortfolioHandler
from itrader.portfolio_handler.rehydrate.portfolio_rehydrate import (
    rehydrate_portfolios,
)
from itrader.portfolio_handler.storage.sql_storage import SqlPortfolioStateStorage
from itrader.storage import SqlEngine
from itrader.storage.portfolio_definition_store import PortfolioDefinitionStore
from tests.support.schema import provision_schema
from tests.support.venue_wiring import backtest_portfolio_handler

_AT = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
_VENUE = "paper"


@pytest.fixture()
def wiring():
    """An in-memory SQLite spine with the full portfolio schema.

    ``SqlPortfolioStateStorage`` is constructed FIRST purely to register the seven
    portfolio-scoped tables (plus ``portfolios`` / ``venue_accounts``) on the shared MetaData
    before ``provision_schema`` creates them — the stores are schema-pure (WR-03/D-14).
    """
    engine = SqlEngine(SqlSettings.default())
    SqlPortfolioStateStorage(engine, uuid.uuid4())
    definitions = PortfolioDefinitionStore(engine)
    provision_schema(engine)
    return engine, definitions


def _seed_account(engine, account_id: str) -> None:
    """Insert the ``venue_accounts`` parent the definition row's composite FK requires."""
    accounts = engine.metadata.tables["venue_accounts"]
    with engine.engine.begin() as connection:
        connection.execute(accounts.insert(), [{
            "venue_name": _VENUE, "account_id": account_id, "secret_ref": None,
            "venue_uid": None, "enabled": True, "config_json": {}, "updated_at": _AT,
        }])


def _account_row(engine, account_id: str) -> dict:
    """Read one ``venue_accounts`` row back as a plain dict (for byte-identity assertions)."""
    accounts = engine.metadata.tables["venue_accounts"]
    with engine.engine.connect() as connection:
        row = connection.execute(
            accounts.select().where(accounts.c.account_id == account_id)
        ).mappings().first()
    return dict(row) if row is not None else {}


def _live_handler(engine) -> PortfolioHandler:
    """A PortfolioHandler on the LIVE arm — the only arm that owns a definition store."""
    return backtest_portfolio_handler(queue.Queue(), environment="live", sql_engine=engine)


def _restart_and_rehydrate(engine, definitions):
    """Simulate a restart: a FRESH handler over the SAME database, then rehydrate."""
    handler = _live_handler(engine)
    rehydrate_portfolios(store=definitions, portfolio_handler=handler)
    return handler


def test_deactivate_then_restart_rehydrates_inactive(wiring) -> None:
    """ACCT-10 — a paused portfolio persists enabled=False and comes back INACTIVE, not ACTIVE."""
    engine, definitions = wiring
    _seed_account(engine, "acct-a")
    handler = _live_handler(engine)
    portfolio_id = handler.add_portfolio(
        name="pf-a", exchange=_VENUE, cash=Decimal("10000.00"),
        account_id="acct-a", venue_name=_VENUE)

    handler.deactivate_portfolio(portfolio_id)

    # Durable: enabled=False persisted (crash-safety ordering — persist before flip).
    assert definitions.get(portfolio_id)["enabled"] is False
    # In-memory: flipped INACTIVE.
    assert handler.get_portfolio(portfolio_id).state == PortfolioState.INACTIVE

    # Restart: the present-but-inactive branch reconstructs it INACTIVE from the row.
    handler2 = _restart_and_rehydrate(engine, definitions)
    assert handler2.has_portfolio(portfolio_id)
    assert handler2.get_portfolio(portfolio_id).state == PortfolioState.INACTIVE


def test_activate_after_deactivate_restarts_active(wiring) -> None:
    """ACCT-10 — resume persists enabled=True; the portfolio rehydrates ACTIVE."""
    engine, definitions = wiring
    _seed_account(engine, "acct-a")
    handler = _live_handler(engine)
    portfolio_id = handler.add_portfolio(
        name="pf-a", exchange=_VENUE, cash=Decimal("10000.00"),
        account_id="acct-a", venue_name=_VENUE)

    handler.deactivate_portfolio(portfolio_id)
    handler.activate_portfolio(portfolio_id)

    assert definitions.get(portfolio_id)["enabled"] is True
    assert handler.get_portfolio(portfolio_id).state == PortfolioState.ACTIVE

    handler2 = _restart_and_rehydrate(engine, definitions)
    assert handler2.get_portfolio(portfolio_id).state == PortfolioState.ACTIVE


def test_deactivate_is_idempotent(wiring) -> None:
    """ACCT-10 idempotency — deactivating twice leaves enabled=False and does not raise."""
    engine, definitions = wiring
    _seed_account(engine, "acct-a")
    handler = _live_handler(engine)
    portfolio_id = handler.add_portfolio(
        name="pf-a", exchange=_VENUE, cash=Decimal("10000.00"),
        account_id="acct-a", venue_name=_VENUE)

    handler.deactivate_portfolio(portfolio_id)
    handler.deactivate_portfolio(portfolio_id)  # must not raise

    assert definitions.get(portfolio_id)["enabled"] is False


def test_deactivate_leaves_the_venue_account_row_byte_identical(wiring) -> None:
    """D-33 — disabling a PORTFOLIO never touches its venue ACCOUNT (independent flags)."""
    engine, definitions = wiring
    _seed_account(engine, "acct-a")
    handler = _live_handler(engine)
    portfolio_id = handler.add_portfolio(
        name="pf-a", exchange=_VENUE, cash=Decimal("10000.00"),
        account_id="acct-a", venue_name=_VENUE)

    before = _account_row(engine, "acct-a")
    handler.deactivate_portfolio(portfolio_id)
    after = _account_row(engine, "acct-a")

    assert before == after
    assert after["enabled"] is True  # the account is still enabled


def test_delete_retires_the_row_survives_and_a_successor_claims_the_pair(wiring) -> None:
    """ACCT-10/D-32 — delete persists is_deleted=True; the row survives, never rehydrates, and
    a successor can run on the released (venue, account_id) pair."""
    engine, definitions = wiring
    _seed_account(engine, "acct-a")
    handler = _live_handler(engine)
    portfolio_id = handler.add_portfolio(
        name="pf-a", exchange=_VENUE, cash=Decimal("10000.00"),
        account_id="acct-a", venue_name=_VENUE)

    # force=True bypasses the remaining-cash guard; the retirement semantics are what is
    # under test here, not the delete precondition.
    handler.delete_portfolio(portfolio_id, force=True)

    # Durable: is_deleted=True persisted; the row (and its history) SURVIVES via get().
    retired = definitions.get(portfolio_id)
    assert retired is not None and retired["is_deleted"] is True
    # Invisible to rehydrate.
    assert definitions.read_all() == []

    # Restart: the retired portfolio does NOT rehydrate.
    handler2 = _restart_and_rehydrate(engine, definitions)
    assert not handler2.has_portfolio(portfolio_id)

    # A SUCCESSOR claims the released pair on the SAME (venue, account_id).
    successor_id = handler2.add_portfolio(
        name="pf-successor", exchange=_VENUE, cash=Decimal("5000.00"),
        account_id="acct-a", venue_name=_VENUE)
    assert successor_id != portfolio_id
    successor_row = definitions.get(successor_id)
    assert successor_row is not None
    assert successor_row["is_deleted"] is False
    assert successor_row["account_id"] == "acct-a"
    # The retired predecessor's row is still there for audit.
    assert definitions.get(portfolio_id)["is_deleted"] is True


def test_retire_while_paused_cannot_be_resurrected(wiring) -> None:
    """ACCT-10 backstop — pause then retire releases the account once; no resurrection.

    A portfolio retired while paused (enabled=False then is_deleted=True) leaves the registry
    and the rehydrate set. Flipping enabled back is impossible because the object is gone —
    ``activate_portfolio`` raises ``PortfolioNotFoundError`` rather than resurrecting it.
    """
    from itrader.core.exceptions import PortfolioNotFoundError

    engine, definitions = wiring
    _seed_account(engine, "acct-a")
    handler = _live_handler(engine)
    portfolio_id = handler.add_portfolio(
        name="pf-a", exchange=_VENUE, cash=Decimal("10000.00"),
        account_id="acct-a", venue_name=_VENUE)

    handler.deactivate_portfolio(portfolio_id)          # enabled=False
    handler.delete_portfolio(portfolio_id, force=True)  # is_deleted=True + registry removal

    assert definitions.get(portfolio_id)["is_deleted"] is True
    with pytest.raises(PortfolioNotFoundError):
        handler.activate_portfolio(portfolio_id)
    # A restart still does not bring it back.
    handler2 = _restart_and_rehydrate(engine, definitions)
    assert not handler2.has_portfolio(portfolio_id)

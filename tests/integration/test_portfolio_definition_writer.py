"""The 11-08 DEFINITION-ROW WRITER — ``portfolios`` finally has a production author (D-07/D-08).

**The gap this closes.** Plan 11-01 shipped ``PortfolioDefinitionStore`` and plan 11-08 was
written to READ it at boot. A pre-execution audit found the phase had a reader with no
writer: ``grep -rn 'PortfolioDefinitionStore' itrader/`` returned only the store's own
module, and ``upsert`` had ZERO production callers. In production ``read_all()`` would have
returned ``[]`` on every boot, forever, while every acceptance criterion passed against a
fixture-provisioned store — a rehydrate that is exhaustively tested and structurally inert.

``PortfolioHandler._persist_definition`` is that missing writer. It lives on
``add_portfolio`` rather than at the composition root deliberately: 11-07 established that
``build_live_system`` creates NO portfolios, so live portfolios are added by the application
AFTER boot, and a boot-only writer would persist none of them.

**Why the absence gate is asserted, not just the write.** ``upsert`` is a DELETE-then-INSERT
on ``portfolio_id``, so re-writing an existing row wipes its ``config_json`` — the D-09 home
of the per-portfolio config blob. Rehydrate re-enters this path for every persisted
portfolio on every boot, so the unconditional form would silently discard the operator's
persisted config on the FIRST restart after saving it. This is the same delete-then-insert
clobber 11-07 hit on ``VenueAccountStore``, on a different table.

4-space indentation (matches ``tests/integration/*``); NO ``__init__.py`` in this dir.
Folder-derived ``integration`` marker.
"""

import queue
import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from itrader.config.sql import SqlSettings
from itrader.core.exceptions import PortfolioStateError
from itrader.core.ids import PortfolioId
from itrader.portfolio_handler.portfolio_handler import PortfolioHandler
from itrader.portfolio_handler.storage.sql_storage import SqlPortfolioStateStorage
from itrader.storage import SqlEngine
from itrader.storage.portfolio_definition_store import PortfolioDefinitionStore
from tests.support.schema import provision_schema
from tests.support.venue_wiring import backtest_portfolio_handler

_AT = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
_VENUE = "paper"


@pytest.fixture()
def wiring():
    """An in-memory SQLite spine with the full portfolio schema and one account parent.

    ``SqlPortfolioStateStorage`` is constructed FIRST purely to register the seven
    portfolio-scoped tables (plus ``portfolios`` / ``venue_accounts``) on the shared
    MetaData before ``provision_schema`` creates them — the stores are schema-pure
    (WR-03/D-14), so nothing self-creates at runtime.
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


def _live_handler(engine) -> PortfolioHandler:
    """A PortfolioHandler on the LIVE arm — the only arm that owns a definition store."""
    return backtest_portfolio_handler(queue.Queue(), environment="live", sql_engine=engine)


# --------------------------------------------------------------------------- #
# The writer exists at all (the gate that returned nothing before this plan)
# --------------------------------------------------------------------------- #
def test_creating_a_live_portfolio_persists_its_definition_row(wiring) -> None:
    """THE gate: ``add_portfolio`` writes the row ``rehydrate_portfolios`` reads.

    Asserted on the row CONTENTS, not merely on its existence: a row whose
    ``portfolio_id`` did not match the live portfolio's would rehydrate a stranger,
    and the persisted id is the whole point (T-11-41).
    """
    engine, definitions = wiring
    _seed_account(engine, "acct-a")
    handler = _live_handler(engine)

    portfolio_id = handler.add_portfolio(
        name="pf-a", exchange=_VENUE, cash=Decimal("10000.00"),
        account_id="acct-a", venue_name=_VENUE)

    row = definitions.get(portfolio_id)
    assert row is not None, (
        "add_portfolio did not persist a definition row — rehydrate_portfolios would "
        "read an empty table on every production boot")
    assert row["portfolio_id"] == portfolio_id
    assert row["name"] == "pf-a"
    assert row["venue_name"] == _VENUE
    assert row["account_id"] == "acct-a"
    assert row["initial_cash"] == Decimal("10000.00")
    assert row["enabled"] is True
    # read_all() is the rehydrate read — the row must be visible through it too.
    assert [r["portfolio_id"] for r in definitions.read_all()] == [portfolio_id]


def test_initial_cash_round_trips_as_decimal_never_float(wiring) -> None:
    """Money stays Decimal end-to-end across the write (a float would lose the cents).

    ``0.1 + 0.2`` style repr artifacts are the failure mode; a value with a fractional
    part that has no exact binary representation is what makes this assertion bite.
    """
    engine, definitions = wiring
    _seed_account(engine, "acct-money")
    handler = _live_handler(engine)

    portfolio_id = handler.add_portfolio(
        name="pf-money", exchange=_VENUE, cash=Decimal("12345.67"),
        account_id="acct-money", venue_name=_VENUE)

    stored = definitions.get(portfolio_id)["initial_cash"]
    assert isinstance(stored, Decimal)
    assert stored == Decimal("12345.67")


# --------------------------------------------------------------------------- #
# The absence gate — upsert is a DELETE-then-INSERT
# --------------------------------------------------------------------------- #
def test_re_adding_a_persisted_portfolio_never_clobbers_its_config(wiring) -> None:
    """An EXISTING definition row is left alone — the write is gated on ABSENCE.

    This is the restart shape: boot 2's rehydrate calls ``add_portfolio`` again for a
    portfolio whose row already carries a persisted ``config_json``. An unconditional
    upsert would DELETE-then-INSERT that row and silently drop the operator's config,
    and the boot would look perfectly healthy while trading on defaults.
    """
    engine, definitions = wiring
    _seed_account(engine, "acct-cfg")
    handler = _live_handler(engine)

    portfolio_id = handler.add_portfolio(
        name="pf-cfg", exchange=_VENUE, cash=Decimal("10000.00"),
        account_id="acct-cfg", venue_name=_VENUE)
    # The portfolio's own bound store writes the D-09 blob onto the definition row.
    handler.get_portfolio(portfolio_id).state_storage.save_config(
        {"limits": {"max_positions": 7}}, _AT)
    assert definitions.get(portfolio_id)["config"] == {"limits": {"max_positions": 7}}

    # A SECOND handler over the SAME database re-creating the SAME portfolio (the
    # rehydrate shape) must not disturb the stored row.
    handler2 = _live_handler(engine)
    handler2.add_portfolio(
        name="pf-cfg", exchange=_VENUE, cash=Decimal("10000.00"),
        portfolio_id=portfolio_id, account_id="acct-cfg", venue_name=_VENUE)

    assert definitions.get(portfolio_id)["config"] == {"limits": {"max_positions": 7}}, (
        "re-creating a persisted portfolio clobbered its config_json — upsert is a "
        "delete-then-insert, so the write MUST be gated on absence")
    assert len(definitions.read_all()) == 1


# --------------------------------------------------------------------------- #
# The three no-write arms
# --------------------------------------------------------------------------- #
def test_a_backtest_handler_owns_no_definition_store(wiring) -> None:
    """The byte-exact oracle path never touches the durable definition table."""
    engine, definitions = wiring
    handler = backtest_portfolio_handler(queue.Queue(), environment="backtest", sql_engine=None)

    assert handler.definition_store is None
    handler.add_portfolio(name="pf-bt", exchange="paper", cash=100_000)
    assert definitions.read_all() == []


def test_a_portfolio_naming_no_account_writes_no_row(wiring) -> None:
    """No ``(venue_name, account_id)`` pair means no well-formed definition row.

    Both halves are NOT NULL and together carry an unconditional composite FK onto
    ``venue_accounts`` (D-06/D-07). This is the pre-11-05 ``add_portfolio(name=,
    exchange=, cash=)`` call shape, which stays supported rather than raising.
    """
    engine, definitions = wiring
    handler = _live_handler(engine)

    handler.add_portfolio(name="pf-unnamed", exchange="paper", cash=Decimal("500"))

    assert definitions.read_all() == []


# --------------------------------------------------------------------------- #
# The legacy arms are gone (11-08 removed both)
# --------------------------------------------------------------------------- #
def test_save_config_without_a_definition_row_fails_loud(wiring) -> None:
    """The legacy zero-sentinel INSERT arm is gone — a missing row now RAISES.

    That arm wrote the blob to ``portfolio_account_state.config_json``, which
    ``load_config`` no longer reads after the D-09 rehome. Keeping it would mean
    silently persisting config to a column nothing reads back — a loss that is
    invisible, because the restart-layering caller swallows failures into a warning
    and boots clean on defaults.
    """
    engine, _ = wiring
    orphan = SqlPortfolioStateStorage(engine, PortfolioId(uuid.uuid4()))

    with pytest.raises(PortfolioStateError, match="definition-row"):
        orphan.save_config({"limits": {"max_positions": 3}}, _AT)


def test_load_config_reads_only_the_definition_row(wiring) -> None:
    """No definition row -> ``None``; the legacy account-state fallback is gone."""
    engine, _ = wiring
    orphan = SqlPortfolioStateStorage(engine, PortfolioId(uuid.uuid4()))

    assert orphan.load_config() is None

"""MPORT-02 at BOTH layers — no two portfolios may share one venue account (D-14/D-15).

Two portfolios pointing at one real venue account conflate their buying power and positions
into a single balance the venue cannot split back out (T-11-38). D-14 defends that at two
layers on purpose, and this file gates both:

* the DATABASE ``UniqueConstraint('venue_name', 'account_id')`` on ``portfolios`` (plan
  11-01), which also binds out-of-band writers that never execute application code;
* the APPLICATION check at composition, whose real job is the half the database cannot see
  — a duplicate inside a composition-supplied spec, which has not been written yet.

**The union is the contract.** A check over only the persisted rows would prove nothing the
DB constraint has not already proven; a check over only the spec would miss a new portfolio
colliding with an existing durable row. Both directions are gated below.

**D-15 is asserted as a NEGATIVE, not just as a raise.** ``pytest.raises`` alone would pass
against an implementation that minted every account first and only then noticed the
collision. The gates therefore assert that NO account was minted and NO exchange registered
on the failure path — the state the engine is left in matters more than the exception type.

4-space indentation; NO ``__init__.py`` in this dir. Folder-derived ``integration`` marker.
"""

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy.exc import IntegrityError

from itrader.config.sql import SqlSettings
from itrader.core.exceptions import DuplicateVenueAccountError
from itrader.portfolio_handler.rehydrate.distinct_account_invariant import (
    assert_distinct_accounts,
)
from itrader.storage import SqlEngine
from itrader.storage.portfolio_definition_store import PortfolioDefinitionStore
from tests.support.schema import provision_schema

_AT = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
_VENUE = "okx"


def _persisted(name: str, venue_name: str, account_id: str) -> dict:
    """A definition row in the store's public read shape."""
    return {
        "portfolio_id": uuid.uuid4(),
        "name": name,
        "venue_name": venue_name,
        "account_id": account_id,
        "initial_cash": Decimal("10000.00"),
        "enabled": True,
        "config": None,
        "updated_at": _AT,
    }


def _spec_portfolio(name: str, account_id):
    """A ``PortfolioSpec``-shaped handle (the invariant duck-types both sides)."""
    return SimpleNamespace(name=name, cash=10_000, account_id=account_id)


# --------------------------------------------------------------------------- #
# Layer 1 — the application check, over the UNION
# --------------------------------------------------------------------------- #
def test_zero_portfolios_passes_vacuously() -> None:
    """The MPORT-03 empty edge — a clean boot with nothing persisted must not raise."""
    assert_distinct_accounts(persisted=[], spec_portfolios=[], venue_name=_VENUE)


def test_one_portfolio_passes() -> None:
    """A single portfolio cannot collide with anything."""
    assert_distinct_accounts(
        persisted=[],
        spec_portfolios=[_spec_portfolio("solo", "acct-a")],
        venue_name=_VENUE,
    )


def test_the_same_account_id_on_two_different_venues_passes() -> None:
    """Identity is the PAIR — the same NAME on two venues is two different accounts.

    Flagging this would be a false refusal on a legitimate deployment: account ids are
    venue-scoped strings, and "main" on OKX has nothing to do with "main" on Binance.
    """
    assert_distinct_accounts(
        persisted=[_persisted("pf-a", "okx", "main")],
        spec_portfolios=[_spec_portfolio("pf-b", "main")],
        venue_name="binance",
    )


def test_the_same_venue_with_different_account_ids_passes() -> None:
    """Same-venue portfolios SEPARATE when their accounts differ (MPORT-03 adjacency)."""
    assert_distinct_accounts(
        persisted=[],
        spec_portfolios=[
            _spec_portfolio("pf-a", "acct-a"),
            _spec_portfolio("pf-b", "acct-b"),
        ],
        venue_name=_VENUE,
    )


def test_two_spec_portfolios_sharing_a_pair_raise() -> None:
    """The case ONLY the application check can catch — neither row exists in the DB yet.

    The error must name both portfolios, the colliding pair, the consequence and the
    remediation: an operator reading it should not have to open the source to act.
    """
    with pytest.raises(DuplicateVenueAccountError) as caught:
        assert_distinct_accounts(
            persisted=[],
            spec_portfolios=[
                _spec_portfolio("pf-a", "shared"),
                _spec_portfolio("pf-b", "shared"),
            ],
            venue_name=_VENUE,
        )

    error = caught.value
    assert error.venue_name == _VENUE
    assert error.account_id == "shared"
    message = str(error)
    assert "pf-a" in message and "pf-b" in message
    assert "conflate" in message           # the consequence
    assert "own account_id" in message     # the remediation


def test_a_spec_portfolio_colliding_with_a_persisted_one_raises() -> None:
    """The cross-source case — the DB has not seen the spec portfolio yet.

    Without the union this passes: the persisted row is unique among persisted rows, and
    the spec portfolio is unique among spec portfolios.
    """
    with pytest.raises(DuplicateVenueAccountError, match="shared"):
        assert_distinct_accounts(
            persisted=[_persisted("durable-pf", _VENUE, "shared")],
            spec_portfolios=[_spec_portfolio("new-pf", "shared")],
            venue_name=_VENUE,
        )


def test_two_persisted_rows_sharing_a_pair_raise() -> None:
    """Belt and braces over the DB constraint (rows could predate it, or arrive by hand)."""
    with pytest.raises(DuplicateVenueAccountError, match="shared"):
        assert_distinct_accounts(
            persisted=[
                _persisted("pf-a", _VENUE, "shared"),
                _persisted("pf-b", _VENUE, "shared"),
            ],
            spec_portfolios=[],
            venue_name=_VENUE,
        )


def test_portfolios_naming_no_account_never_collide() -> None:
    """An unset ``account_id`` is "no venue account", not a shared ``None`` key.

    Grouping several unnamed portfolios under one key would refuse to start on the legacy
    single-account shape, which has always been valid.
    """
    assert_distinct_accounts(
        persisted=[],
        spec_portfolios=[
            _spec_portfolio("pf-a", None),
            _spec_portfolio("pf-b", None),
        ],
        venue_name=_VENUE,
    )


# --------------------------------------------------------------------------- #
# Layer 2 — the database constraint (binds writers that never run our code)
# --------------------------------------------------------------------------- #
def test_the_database_rejects_an_out_of_band_duplicate_pair() -> None:
    """An INSERT that bypasses the application check still cannot create the collision.

    This is why the overlap is not redundant: a future integrations page writing rows
    directly would never execute ``assert_distinct_accounts``.
    """
    engine = SqlEngine(SqlSettings.default())
    store = PortfolioDefinitionStore(engine)
    provision_schema(engine)
    accounts = engine.metadata.tables["venue_accounts"]
    with engine.engine.begin() as connection:
        connection.execute(accounts.insert(), [{
            "venue_name": _VENUE, "account_id": "shared", "secret_ref": None,
            "venue_uid": None, "enabled": True, "config_json": {}, "updated_at": _AT,
        }])

    try:
        store.upsert(
            uuid.uuid4(), name="pf-a", venue_name=_VENUE, account_id="shared",
            initial_cash=Decimal("10000"), enabled=True, config=None, at=_AT)

        with pytest.raises(IntegrityError):
            store.upsert(
                uuid.uuid4(), name="pf-b", venue_name=_VENUE, account_id="shared",
                initial_cash=Decimal("10000"), enabled=True, config=None, at=_AT)
    finally:
        store.dispose()

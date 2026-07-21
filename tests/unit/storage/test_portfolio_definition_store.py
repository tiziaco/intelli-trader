"""Unit tests for the ``PortfolioDefinitionStore`` — what a portfolio IS (D-07/D-08/D-14).

Exercises the definition row seven portfolio-scoped child tables never had, over an in-memory
SQLite ``SqlEngine``: the ``portfolio_id``-keyed round trip with ``initial_cash`` returning as
``Decimal``, the D-14 PLAIN unique constraint on ``(venue_name, account_id)``, the MPORT-03
adjacency case (same venue + DIFFERENT ``account_id`` both insert), and the unconditional
composite FK to ``venue_accounts``.

The FK/unique cases genuinely fire because ``SqlEngine`` registers a dialect-guarded
``PRAGMA foreign_keys=ON`` connect-hook (WR-02) — SQLite ignores declared FKs without it.

4-space indentation. NO ``__init__.py`` in this dir (package-collision hazard).
``filterwarnings=["error"]`` → every store wrapped in ``try/finally: store.dispose()``.
"""

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

import pytest
from sqlalchemy.exc import IntegrityError

from itrader.config.sql import SqlSettings
from itrader.storage import SqlEngine
from itrader.storage.portfolio_definition_store import (
    PortfolioDefinitionStore,
    build_portfolio_definition_tables,
)
from itrader.storage.venue_account_store import VenueAccountStore
from tests.support.schema import provision_schema

_AT = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)

_PID_A = UUID("01930000-0000-7000-8000-00000000000a")
_PID_B = UUID("01930000-0000-7000-8000-00000000000b")


def _make_stores() -> tuple[PortfolioDefinitionStore, VenueAccountStore]:
    """Both stores on ONE shared ``SqlEngine`` so the composite FK resolves and is enforced.

    WR-03/D-14 — schema-pure stores, so provision explicitly after construction.
    """
    backend = SqlEngine(SqlSettings.default())
    accounts = VenueAccountStore(backend)
    portfolios = PortfolioDefinitionStore(backend)
    provision_schema(backend)
    return portfolios, accounts


def _seed_account(accounts: VenueAccountStore, venue: str, account_id: str) -> None:
    """A parent ``venue_accounts`` row so a portfolio referencing it satisfies the FK."""
    accounts.upsert(
        venue,
        account_id,
        secret_ref=None,
        venue_uid=None,
        enabled=True,
        config={},
        at=_AT,
    )


def test_upsert_get_round_trip_with_decimal_cash() -> None:
    """upsert(...) → get(portfolio_id) round-trips every column; initial_cash is Decimal."""
    portfolios, accounts = _make_stores()
    try:
        _seed_account(accounts, "okx", "main")
        config = {"type": "spot", "leverage": 1}
        portfolios.upsert(
            _PID_A,
            name="growth",
            venue_name="okx",
            account_id="main",
            initial_cash=Decimal("10000.50"),
            enabled=True,
            config=config,
            at=_AT,
        )
        row = portfolios.get(_PID_A)
        assert row is not None
        assert row["portfolio_id"] == _PID_A
        assert row["name"] == "growth"
        assert row["venue_name"] == "okx"
        assert row["account_id"] == "main"
        # Numeric round-trips through SQLite with an expanded scale, so compare as Decimal
        # values (==), never against a string or a repr.
        assert row["initial_cash"] == Decimal("10000.50")
        assert isinstance(row["initial_cash"], Decimal)
        assert row["enabled"] is True
        assert row["config"] == config
        assert row["updated_at"] == _AT
    finally:
        portfolios.dispose()


def test_duplicate_venue_account_pair_raises_integrity_error() -> None:
    """D-14 — a SECOND portfolio on the SAME (venue_name, account_id) is rejected by the DB.

    Two portfolios sharing one venue account would conflate buying power the venue cannot
    split back out; the constraint is PLAIN (not partial/conditional) so an out-of-band write
    cannot bypass it either.
    """
    portfolios, accounts = _make_stores()
    try:
        _seed_account(accounts, "okx", "main")
        portfolios.upsert(
            _PID_A,
            name="first",
            venue_name="okx",
            account_id="main",
            initial_cash=Decimal("1000"),
            enabled=True,
            config=None,
            at=_AT,
        )
        with pytest.raises(IntegrityError):
            portfolios.upsert(
                _PID_B,
                name="second",
                venue_name="okx",
                account_id="main",
                initial_cash=Decimal("2000"),
                enabled=True,
                config=None,
                at=_AT,
            )
    finally:
        portfolios.dispose()


def test_same_venue_distinct_account_ids_both_insert() -> None:
    """MPORT-03 adjacency — same venue, DIFFERENT account_id: both rows land, no collision."""
    portfolios, accounts = _make_stores()
    try:
        _seed_account(accounts, "okx", "main")
        _seed_account(accounts, "okx", "hedge")
        portfolios.upsert(
            _PID_A,
            name="growth",
            venue_name="okx",
            account_id="main",
            initial_cash=Decimal("1000"),
            enabled=True,
            config=None,
            at=_AT,
        )
        portfolios.upsert(
            _PID_B,
            name="hedging",
            venue_name="okx",
            account_id="hedge",
            initial_cash=Decimal("2000"),
            enabled=True,
            config=None,
            at=_AT,
        )
        pairs = {(r["venue_name"], r["account_id"]) for r in portfolios.read_all()}
        assert pairs == {("okx", "main"), ("okx", "hedge")}
    finally:
        portfolios.dispose()


def test_missing_venue_account_parent_raises_integrity_error() -> None:
    """The composite FK is UNCONDITIONAL (D-06 NOT NULL): an orphan portfolio is rejected."""
    portfolios, _accounts = _make_stores()
    try:
        with pytest.raises(IntegrityError):
            portfolios.upsert(
                _PID_A,
                name="orphan",
                venue_name="okx",
                account_id="nonexistent",
                initial_cash=Decimal("1000"),
                enabled=True,
                config=None,
                at=_AT,
            )
    finally:
        portfolios.dispose()


def test_upsert_replaces_row_for_same_portfolio_id() -> None:
    """A second upsert on the SAME portfolio_id replaces rather than duplicating."""
    portfolios, accounts = _make_stores()
    try:
        _seed_account(accounts, "okx", "main")
        portfolios.upsert(
            _PID_A,
            name="before",
            venue_name="okx",
            account_id="main",
            initial_cash=Decimal("1000"),
            enabled=True,
            config=None,
            at=_AT,
        )
        portfolios.upsert(
            _PID_A,
            name="after",
            venue_name="okx",
            account_id="main",
            initial_cash=Decimal("2500"),
            enabled=False,
            config={"type": "margin"},
            at=_AT,
        )
        rows = portfolios.read_all()
        assert len(rows) == 1
        assert rows[0]["name"] == "after"
        assert rows[0]["initial_cash"] == Decimal("2500")
        assert rows[0]["enabled"] is False
        assert rows[0]["config"] == {"type": "margin"}
    finally:
        portfolios.dispose()


def test_null_config_round_trips_as_none() -> None:
    """config_json is nullable (D-09) — ``load_config()`` explicitly handles ``None``."""
    portfolios, accounts = _make_stores()
    try:
        _seed_account(accounts, "paper", "acct_a")
        portfolios.upsert(
            _PID_A,
            name="paper-pf",
            venue_name="paper",
            account_id="acct_a",
            initial_cash=Decimal("500"),
            enabled=True,
            config=None,
            at=_AT,
        )
        row = portfolios.get(_PID_A)
        assert row is not None
        assert row["config"] is None
    finally:
        portfolios.dispose()


def test_get_unknown_id_returns_none_and_read_all_empty() -> None:
    """An absent id is None; an empty table reads back as an empty sequence, not an error."""
    portfolios, _accounts = _make_stores()
    try:
        assert portfolios.get(_PID_A) is None
        assert portfolios.read_all() == []
    finally:
        portfolios.dispose()


def test_read_all_order_is_stable_across_calls() -> None:
    """MPORT-03 — ``read_all`` has a documented, explicit ORDER BY so rehydrate is stable."""
    portfolios, accounts = _make_stores()
    try:
        _seed_account(accounts, "okx", "main")
        _seed_account(accounts, "okx", "hedge")
        portfolios.upsert(
            _PID_B,
            name="second",
            venue_name="okx",
            account_id="hedge",
            initial_cash=Decimal("2000"),
            enabled=True,
            config=None,
            at=_AT,
        )
        portfolios.upsert(
            _PID_A,
            name="first",
            venue_name="okx",
            account_id="main",
            initial_cash=Decimal("1000"),
            enabled=True,
            config=None,
            at=_AT,
        )
        first = [r["portfolio_id"] for r in portfolios.read_all()]
        second = [r["portfolio_id"] for r in portfolios.read_all()]
        assert first == second
        assert first == [_PID_A, _PID_B]
    finally:
        portfolios.dispose()


def test_build_portfolio_definition_tables_is_idempotent_and_shaped() -> None:
    """The registrar reuses registered tables and declares the D-07 shape + both constraints."""
    backend = SqlEngine(SqlSettings.default())
    try:
        first = build_portfolio_definition_tables(backend.metadata)
        second = build_portfolio_definition_tables(backend.metadata)
        assert first["portfolios"] is second["portfolios"]
        portfolios = first["portfolios"]
        assert portfolios.c.portfolio_id.primary_key is True
        # D-07 — a portfolio's venue is the venue_name half of its account reference; a
        # second `exchange` column would be a second source of truth that can drift.
        assert "exchange" not in portfolios.c
        assert portfolios.c.account_id.nullable is False
        assert portfolios.c.config_json.nullable is True
        # D-14 — the unique constraint is PLAIN over exactly the pair.
        unique_pairs = [
            tuple(column.name for column in constraint.columns)
            for constraint in portfolios.constraints
            if constraint.__class__.__name__ == "UniqueConstraint"
        ]
        assert ("venue_name", "account_id") in unique_pairs
        foreign_key_targets = {
            foreign_key.target_fullname for foreign_key in portfolios.foreign_keys
        }
        assert foreign_key_targets == {
            "venue_accounts.venue_name",
            "venue_accounts.account_id",
        }
    finally:
        backend.dispose()

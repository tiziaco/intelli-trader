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
from sqlalchemy import Boolean, Column, Index, MetaData, String, Table
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
    """D-14/D-32 — a second LIVE portfolio on the SAME (venue_name, account_id) is rejected.

    Two portfolios sharing one venue account SIMULTANEOUSLY would conflate buying power the
    venue cannot split back out. D-32 narrowed the index to ``WHERE NOT is_deleted`` but this
    case is unchanged: both rows here are live. Enforcement stays at the DB layer, so an
    out-of-band write that never reaches the application cannot bypass it either.
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


# --------------------------------------------------------------------------------------
# D-32 — is_deleted (RETIRED) vs enabled (PAUSED), and the partial unique index
# --------------------------------------------------------------------------------------


def test_retired_portfolio_releases_its_account_for_a_successor() -> None:
    """D-32 — RETIRE then reuse: a retired row and a live row share one pair.

    The owner's workflow: retire a portfolio, run a NEW one on the SAME real venue account.
    The plain constraint blocked it; the partial index (``WHERE NOT is_deleted``) permits it
    because the retired row has left the indexed set. Its row, history and child tables all
    survive — deletion is SOFT.
    """
    portfolios, accounts = _make_stores()
    try:
        _seed_account(accounts, "okx", "main")
        portfolios.upsert(
            _PID_A,
            name="retired",
            venue_name="okx",
            account_id="main",
            initial_cash=Decimal("1000"),
            enabled=True,
            config=None,
            at=_AT,
            is_deleted=True,
        )
        portfolios.upsert(
            _PID_B,
            name="successor",
            venue_name="okx",
            account_id="main",
            initial_cash=Decimal("2000"),
            enabled=True,
            config=None,
            at=_AT,
        )
        retired = portfolios.get(_PID_A)
        successor = portfolios.get(_PID_B)
        assert retired is not None and retired["is_deleted"] is True
        assert successor is not None and successor["is_deleted"] is False
    finally:
        portfolios.dispose()


def test_paused_portfolio_keeps_its_account() -> None:
    """D-32 — ``enabled=False`` is PAUSED, NOT retired: it does NOT release its pair.

    This is the distinction D-31 collapsed and D-32 splits. Because a paused portfolio still
    holds its account, a second live portfolio on the same pair is still refused — which is
    what makes re-enabling it always work rather than collide.
    """
    portfolios, accounts = _make_stores()
    try:
        _seed_account(accounts, "okx", "main")
        portfolios.upsert(
            _PID_A,
            name="paused",
            venue_name="okx",
            account_id="main",
            initial_cash=Decimal("1000"),
            enabled=False,
            config=None,
            at=_AT,
        )
        with pytest.raises(IntegrityError):
            portfolios.upsert(
                _PID_B,
                name="intruder",
                venue_name="okx",
                account_id="main",
                initial_cash=Decimal("2000"),
                enabled=True,
                config=None,
                at=_AT,
            )
    finally:
        portfolios.dispose()


def test_read_all_omits_retired_portfolios() -> None:
    """D-32 — ``read_all`` is the REHYDRATE read, so a retired portfolio must not come back."""
    portfolios, accounts = _make_stores()
    try:
        _seed_account(accounts, "okx", "main")
        _seed_account(accounts, "okx", "hedge")
        portfolios.upsert(
            _PID_A,
            name="retired",
            venue_name="okx",
            account_id="main",
            initial_cash=Decimal("1000"),
            enabled=True,
            config=None,
            at=_AT,
            is_deleted=True,
        )
        portfolios.upsert(
            _PID_B,
            name="live",
            venue_name="okx",
            account_id="hedge",
            initial_cash=Decimal("2000"),
            enabled=True,
            config=None,
            at=_AT,
        )
        rows = portfolios.read_all()
        assert [row["portfolio_id"] for row in rows] == [_PID_B]
        # get() is id-addressed, NOT the rehydrate read — it still returns the retired row so
        # a caller holding the handle can see WHY it is gone.
        assert portfolios.get(_PID_A) is not None
    finally:
        portfolios.dispose()


def test_upsert_defaults_is_deleted_to_false_and_exposes_it() -> None:
    """A definition written without the flag is LIVE, and every read exposes ``is_deleted``."""
    portfolios, accounts = _make_stores()
    try:
        _seed_account(accounts, "paper", "acct_a")
        portfolios.upsert(
            _PID_A,
            name="fresh",
            venue_name="paper",
            account_id="acct_a",
            initial_cash=Decimal("500"),
            enabled=True,
            config=None,
            at=_AT,
        )
        row = portfolios.get(_PID_A)
        assert row is not None
        assert row["is_deleted"] is False
        assert portfolios.read_all()[0]["is_deleted"] is False
    finally:
        portfolios.dispose()


# --------------------------------------------------------------------------------------
# ACCT-10 / D-32 / D-33 — targeted set_enabled / set_deleted writers + the D-33 live read
# --------------------------------------------------------------------------------------


_AT2 = datetime(2026, 2, 2, 9, 0, 0, tzinfo=UTC)


def _seed_portfolio(
    portfolios: PortfolioDefinitionStore,
    accounts: VenueAccountStore,
    portfolio_id: UUID,
    *,
    venue: str = "okx",
    account_id: str = "main",
    enabled: bool = True,
    config: object = None,
) -> None:
    """A parent account + one LIVE portfolio definition row for the lifecycle-writer tests."""
    _seed_account(accounts, venue, account_id)
    portfolios.upsert(
        portfolio_id,
        name="lifecycle",
        venue_name=venue,
        account_id=account_id,
        initial_cash=Decimal("1000"),
        enabled=enabled,
        config=config,
        at=_AT,
    )


def test_set_enabled_updates_only_enabled_and_leaves_every_other_column() -> None:
    """ACCT-10/D-32 — set_enabled(False) is a TARGETED update; operator columns untouched."""
    portfolios, accounts = _make_stores()
    try:
        config = {"type": "spot", "leverage": 3}
        _seed_portfolio(portfolios, accounts, _PID_A, config=config)
        before = portfolios.get(_PID_A)
        assert before is not None

        portfolios.set_enabled(_PID_A, False, _AT2)

        after = portfolios.get(_PID_A)
        assert after is not None
        assert after["enabled"] is False
        # Every OTHER column is byte-identical (the DELETE-then-INSERT upsert would clobber).
        assert after["config"] == config
        assert after["venue_name"] == before["venue_name"]
        assert after["account_id"] == before["account_id"]
        assert after["initial_cash"] == before["initial_cash"]
        assert after["is_deleted"] is False
        assert after["updated_at"] == _AT2
    finally:
        portfolios.dispose()


def test_set_enabled_is_idempotent_and_never_raises() -> None:
    """ACCT-10 idempotency — pausing twice leaves the row identical and does not raise."""
    portfolios, accounts = _make_stores()
    try:
        _seed_portfolio(portfolios, accounts, _PID_A)
        portfolios.set_enabled(_PID_A, False, _AT2)
        portfolios.set_enabled(_PID_A, False, _AT2)
        row = portfolios.get(_PID_A)
        assert row is not None and row["enabled"] is False
    finally:
        portfolios.dispose()


def test_set_deleted_true_removes_the_row_from_read_all_but_keeps_it_in_get() -> None:
    """ACCT-10/D-32 — set_deleted(True) RETIRES: gone from rehydrate, still in the audit read."""
    portfolios, accounts = _make_stores()
    try:
        config = {"type": "margin"}
        _seed_portfolio(portfolios, accounts, _PID_A, config=config)

        portfolios.set_deleted(_PID_A, True, _AT2)

        assert portfolios.read_all() == []  # invisible to rehydrate
        row = portfolios.get(_PID_A)  # SOFT: id-addressed read still sees it
        assert row is not None
        assert row["is_deleted"] is True
        # Targeted: config survives the retire.
        assert row["config"] == config
        assert row["enabled"] is True
        assert row["updated_at"] == _AT2
    finally:
        portfolios.dispose()


def test_set_enabled_and_set_deleted_on_unknown_id_are_silent_no_ops() -> None:
    """Both writers agree: an unknown portfolio_id matches zero rows and does not raise."""
    portfolios, _accounts = _make_stores()
    try:
        portfolios.set_enabled(_PID_A, False, _AT2)
        portfolios.set_deleted(_PID_A, True, _AT2)
        assert portfolios.get(_PID_A) is None
    finally:
        portfolios.dispose()


def test_live_portfolio_ids_for_account_returns_only_active_claimants() -> None:
    """D-33 — the disable-refusal read: enabled AND NOT is_deleted; paused/retired excluded."""
    portfolios, accounts = _make_stores()
    try:
        _seed_account(accounts, "okx", "shared")
        _seed_account(accounts, "okx", "other")
        # A LIVE portfolio on ('okx','shared').
        portfolios.upsert(
            _PID_A, name="live", venue_name="okx", account_id="shared",
            initial_cash=Decimal("1000"), enabled=True, config=None, at=_AT)
        # A portfolio on a DIFFERENT account — must not be reported for ('okx','shared').
        portfolios.upsert(
            _PID_B, name="elsewhere", venue_name="okx", account_id="other",
            initial_cash=Decimal("1000"), enabled=True, config=None, at=_AT)

        assert portfolios.live_portfolio_ids_for_account("okx", "shared") == [_PID_A]

        # PAUSE it → no longer a live claimant (pausing releases the block, D-33).
        portfolios.set_enabled(_PID_A, False, _AT2)
        assert portfolios.live_portfolio_ids_for_account("okx", "shared") == []

        # Re-enable then RETIRE → still not a live claimant (retired released its pair).
        portfolios.set_enabled(_PID_A, True, _AT2)
        portfolios.set_deleted(_PID_A, True, _AT2)
        assert portfolios.live_portfolio_ids_for_account("okx", "shared") == []
    finally:
        portfolios.dispose()


# --------------------------------------------------------------------------------------
# D-32 partial-unique-index MECHANISM spike (11.2-02 task 1)
# --------------------------------------------------------------------------------------
#
# RESEARCH Assumption A6 (MED risk): partial-index kwargs have ZERO in-tree usage, so
# SQLAlchemy 2.0's ``Index(..., unique=True, sqlite_where=..., postgresql_where=...)`` was
# unproven on the dialect the WHOLE suite runs. This spike converts that assumption into
# evidence against a throwaway table BEFORE the registrar commits to the shape, and is KEPT
# so a future SQLAlchemy bump that silently degrades the predicate fails here — loudly, on a
# 6-line table — rather than in production where it would mean two live portfolios quietly
# sharing one venue account.
#
# The predicate is a SQLAlchemy column EXPRESSION (``~column``, i.e. ``NOT is_deleted``), not
# a raw string, so ONE object serves both dialect kwargs and no dialect can drift.


def _spike_table(metadata: MetaData) -> Table:
    """A minimal (venue_name, account_id, is_deleted) table with the D-32 partial index."""
    table = Table(
        "spike_portfolios",
        metadata,
        Column("row_id", String, primary_key=True),
        Column("venue_name", String, nullable=False),
        Column("account_id", String, nullable=False),
        Column("is_deleted", Boolean, nullable=False),
    )
    Index(
        "uq_spike_live",
        table.c.venue_name,
        table.c.account_id,
        unique=True,
        postgresql_where=~table.c.is_deleted,
        sqlite_where=~table.c.is_deleted,
    )
    return table


def _spike_engine() -> tuple[SqlEngine, Table]:
    """An in-memory SQLite engine carrying only the spike table."""
    backend = SqlEngine(SqlSettings.default())
    table = _spike_table(MetaData())
    table.metadata.create_all(backend.engine)
    return backend, table


def _insert(backend: SqlEngine, table: Table, row_id: str, deleted: bool) -> None:
    """Insert one ``('okx', 'main')`` row with the given retirement flag."""
    with backend.engine.begin() as connection:
        connection.execute(
            table.insert(),
            [{
                "row_id": row_id,
                "venue_name": "okx",
                "account_id": "main",
                "is_deleted": deleted,
            }],
        )


def test_spike_partial_index_permits_retired_plus_live_pair() -> None:
    """(a) A RETIRED row and a LIVE row on the same pair BOTH persist — sequential reuse."""
    backend, table = _spike_engine()
    try:
        _insert(backend, table, "retired", deleted=True)
        _insert(backend, table, "live", deleted=False)
        with backend.engine.connect() as connection:
            rows = connection.execute(table.select()).mappings().all()
        assert {row["row_id"] for row in rows} == {"retired", "live"}
    finally:
        backend.dispose()


def test_spike_partial_index_refuses_two_live_rows_on_one_pair() -> None:
    """(b) TWO LIVE rows on one pair raise ``IntegrityError`` — simultaneous sharing refused.

    The predicate must actually reach SQLite: if ``sqlite_where`` were ignored the index
    would be PLAIN and case (a) above would fail instead; if the index were dropped entirely
    this case would pass silently. Both halves are asserted, so neither degradation is green.
    """
    backend, table = _spike_engine()
    try:
        _insert(backend, table, "first", deleted=False)
        with pytest.raises(IntegrityError):
            _insert(backend, table, "second", deleted=False)
    finally:
        backend.dispose()


def test_spike_partial_index_refuses_un_retiring_into_a_live_successor() -> None:
    """(c) Flipping a RETIRED row back live while a successor holds the pair is refused.

    The index is self-enforcing in BOTH directions — an UPDATE that moves a row INTO the
    indexed set is checked exactly like an INSERT, so a resurrected portfolio cannot collide
    with the one that took over its account.
    """
    backend, table = _spike_engine()
    try:
        _insert(backend, table, "retired", deleted=True)
        _insert(backend, table, "successor", deleted=False)
        with pytest.raises(IntegrityError):
            with backend.engine.begin() as connection:
                connection.execute(
                    table.update()
                    .where(table.c.row_id == "retired")
                    .values(is_deleted=False)
                )
    finally:
        backend.dispose()


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
        # D-32 — is_deleted is NOT NULL and declares NO server_default, so the registrar and
        # the migrated schema agree (the migration drops its backfill default inside a batch).
        assert portfolios.c.is_deleted.nullable is False
        assert portfolios.c.is_deleted.server_default is None
        # D-32 — the PLAIN table-level UniqueConstraint on the pair is GONE ...
        unique_pairs = [
            tuple(column.name for column in constraint.columns)
            for constraint in portfolios.constraints
            if constraint.__class__.__name__ == "UniqueConstraint"
        ]
        assert ("venue_name", "account_id") not in unique_pairs
        # ... replaced by a PARTIAL unique index carrying BOTH dialect predicates. A
        # single-dialect predicate silently degrades to a plain index on the other engine —
        # and the suite runs SQLite while production runs Postgres, so a missing
        # ``sqlite_where`` would never be observed by any test.
        live_index = next(
            index for index in portfolios.indexes
            if index.name == "uq_portfolios_live_account"
        )
        assert live_index.unique is True
        assert [column.name for column in live_index.columns] == [
            "venue_name",
            "account_id",
        ]
        assert live_index.dialect_options["postgresql"]["where"] is not None
        assert live_index.dialect_options["sqlite"]["where"] is not None
        foreign_key_targets = {
            foreign_key.target_fullname for foreign_key in portfolios.foreign_keys
        }
        assert foreign_key_targets == {
            "venue_accounts.venue_name",
            "venue_accounts.account_id",
        }
    finally:
        backend.dispose()

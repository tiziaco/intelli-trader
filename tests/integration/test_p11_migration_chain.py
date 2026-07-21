"""The Phase 11 migration chain + the D-09 config rehome (11-03, D-28/D-29/D-09).

Covers the two revisions this plan adds (``p11_venue_accounts_portfolios`` then
``p11_b2_uuid_fk_config_move``) and the ``save_config`` / ``load_config`` rehome from the
STATE row onto the DEFINITION row.

**Why the by-VALUE assertion in ``test_upgrade_moves_the_config_blob_by_value`` is the point
of this whole file.** ``load_config()`` returning ``None`` is guarded by a truthiness check
and wrapped in a warning-only degrade-clean on the restart-layering path, so a migration that
repointed the READS without actually MOVING the data would produce no exception, no warning, a
clean boot and a fully green suite — while every live portfolio silently traded on default
configuration. A ``is not None`` assertion does not close that gap; only comparing the
migrated VALUE does. ``test_negative_control_*`` exists to prove that claim rather than assert
it: it runs the identical staging with the move step disabled and shows the destination stays
empty, so the positive test cannot be passing vacuously.

Indentation: 4 spaces (tests/integration/* convention). This directory is deliberately
package-LESS (no ``__init__.py``).
"""

import pathlib
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict

import pytest
from sqlalchemy import MetaData, create_engine, inspect, insert, select, text

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory

from itrader.config.sql import SqlDriver, SqlSettings
from itrader.portfolio_handler.storage.sql_storage import SqlPortfolioStateStorage
from itrader.storage import SqlEngine
from itrader.storage.engine import NAMING_CONVENTION
from itrader.storage.portfolio_definition_store import build_portfolio_definition_tables
from itrader.storage.venue_account_store import build_venue_accounts_table
from tests.support.schema import provision_schema

_NOW = datetime(2026, 7, 21, 12, 0, tzinfo=timezone.utc)

# The head after BOTH Phase 11 revisions, and the revision that creates the two new tables
# but has NOT yet moved the config (the staging point for the data-movement tests).
_HEAD = "p11_b2_uuid_fk_config_move"
_REVISION_ONE = "p11_venue_accounts_portfolios"

# A distinctive, NESTED, NON-DEFAULT blob. Nested on purpose: a shallow dict could survive a
# reshaping bug that a nested one exposes, and a value equal to some default would let a
# "config never moved, defaults applied" outcome pass as a success.
_CONFIG_BLOB: Dict[str, Any] = {
    "risk_management": {"max_concentration_pct": 37.5, "max_positions": 9},
    "limits": {"max_notional": "12345.67"},
    "tags": ["phase-11", "d-09"],
}

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
_ALEMBIC_INI = _REPO_ROOT / "alembic.ini"
_MIGRATIONS_DIR = _REPO_ROOT / "migrations"


def _alembic_config(url: str) -> Config:
    """Alembic ``Config`` with an EXPLICIT url — never resolves a live Postgres.

    ``migrations/env.py`` falls back to ``SqlSettings(...).engine_url()`` when the Config
    carries no url, which would make these tests depend on ``ITRADER_DATABASE_*`` being set.
    Injecting the SQLite url here keeps them offline and env-free (and writes no credential
    into ``alembic.ini`` — SEC-01).
    """
    cfg = Config(str(_ALEMBIC_INI))
    cfg.set_main_option("script_location", str(_MIGRATIONS_DIR))
    cfg.set_main_option("sqlalchemy.url", url)
    return cfg


def _seed_for_the_move(url: str, portfolio_id: uuid.UUID) -> None:
    """Stage the D-09 move: a definition row with NULL config + a state row holding the blob.

    Run at ``_REVISION_ONE`` — ``portfolios`` exists but the move has not happened yet. The
    destination deliberately starts NULL so that a non-NULL destination AFTER the upgrade can
    only have come FROM the migration.
    """
    engine = create_engine(url)
    try:
        with engine.begin() as conn:
            conn.execute(text(
                "INSERT INTO venue_accounts "
                "(venue_name, account_id, secret_ref, venue_uid, enabled, config_json, updated_at) "
                "VALUES ('paper', 'main', NULL, NULL, 1, '{}', '2026-07-21T12:00:00+00:00')"))
            conn.execute(
                text(
                    "INSERT INTO portfolios (portfolio_id, name, venue_name, account_id, "
                    "initial_cash, enabled, config_json, updated_at) "
                    "VALUES (:pid, 'p11', 'paper', 'main', 10000.50, 1, NULL, "
                    "'2026-07-21T12:00:00+00:00')"
                ),
                {"pid": portfolio_id.hex},
            )
            conn.execute(
                text(
                    "INSERT INTO portfolio_account_state (portfolio_id, cash_balance, "
                    "realized_pnl, total_equity, peak_equity, open_positions_count, "
                    "updated_time, config_json) "
                    "VALUES (:pid, 0, 0, 0, 0, 0, '2026-07-21T12:00:00+00:00', :cfg)"
                ),
                {"pid": portfolio_id.hex, "cfg": __import__("json").dumps(_CONFIG_BLOB)},
            )
    finally:
        engine.dispose()


def _read_portfolios_config(url: str, portfolio_id: uuid.UUID) -> Any:
    """The raw ``portfolios.config_json`` value for ``portfolio_id``, decoded."""
    metadata = MetaData(naming_convention=NAMING_CONVENTION)
    portfolios = build_portfolio_definition_tables(metadata)["portfolios"]
    engine = create_engine(url)
    try:
        with engine.connect() as conn:
            return conn.execute(
                select(portfolios.c.config_json).where(
                    portfolios.c.portfolio_id == portfolio_id
                )
            ).scalar()
    finally:
        engine.dispose()


# --------------------------------------------------------------------------------------
# Chain shape
# --------------------------------------------------------------------------------------


def test_chain_has_exactly_one_head() -> None:
    """D-29: both revisions chain linearly — ``alembic heads`` yields exactly ONE head."""
    heads = ScriptDirectory.from_config(
        _alembic_config("sqlite+pysqlite:///:memory:")
    ).get_heads()
    assert tuple(heads) == (_HEAD,)


def test_revision_one_creates_both_tables_in_fk_order(tmp_path: pathlib.Path) -> None:
    """D-29: revision 1 creates ``venue_accounts`` AND ``portfolios``, FK intact."""
    url = f"sqlite+pysqlite:///{tmp_path / 'rev1.db'}"
    command.upgrade(_alembic_config(url), _REVISION_ONE)

    engine = create_engine(url)
    try:
        inspector = inspect(engine)
        names = set(inspector.get_table_names())
        assert {"venue_accounts", "portfolios"} <= names
        # The composite FK actually resolved (a reversed create order would have failed).
        fks = inspector.get_foreign_keys("portfolios")
        assert any(
            fk["referred_table"] == "venue_accounts"
            and set(fk["constrained_columns"]) == {"venue_name", "account_id"}
            for fk in fks
        )
    finally:
        engine.dispose()


def test_revision_two_retypes_portfolio_id_and_adds_the_cascade_fk(
    tmp_path: pathlib.Path,
) -> None:
    """B2: ``portfolio_id`` becomes ``Uuid`` and gains the ON DELETE CASCADE FK."""
    url = f"sqlite+pysqlite:///{tmp_path / 'rev2.db'}"
    command.upgrade(_alembic_config(url), "head")

    engine = create_engine(url)
    try:
        inspector = inspect(engine)
        columns = {
            c["name"]: c["type"]
            for c in inspector.get_columns("strategy_portfolio_subscriptions")
        }
        # sa.Uuid compiles to CHAR(32) on SQLite (native UUID on Postgres) — NOT VARCHAR.
        assert "CHAR(32)" in str(columns["portfolio_id"]).upper()
        cascade = [
            fk
            for fk in inspector.get_foreign_keys("strategy_portfolio_subscriptions")
            if fk["referred_table"] == "portfolios"
        ]
        assert len(cascade) == 1
        assert cascade[0]["options"].get("ondelete") == "CASCADE"
    finally:
        engine.dispose()


def test_upgrade_refuses_when_subscriptions_hold_data(tmp_path: pathlib.Path) -> None:
    """A1 GUARD (T-11-11): a populated subscriptions table makes ``upgrade`` RAISE, not retype.

    Asserts BOTH halves — the raise happens AND the operator's row survives untouched.
    """
    url = f"sqlite+pysqlite:///{tmp_path / 'guard.db'}"
    cfg = _alembic_config(url)
    command.upgrade(cfg, _REVISION_ONE)  # stop BEFORE the retype

    engine = create_engine(url)
    try:
        with engine.begin() as conn:
            conn.execute(text(
                "INSERT INTO strategy_registry "
                "(strategy_name, strategy_type, enabled, config_json, updated_at) "
                "VALUES ('legacy', 'SMA_MACD', 1, '{}', '2026-01-01T00:00:00+00:00')"))
            conn.execute(text(
                "INSERT INTO strategy_portfolio_subscriptions "
                "(strategy_name, portfolio_id) VALUES ('legacy', 'a-legacy-string-id')"))

        with pytest.raises(RuntimeError) as excinfo:
            command.upgrade(cfg, "head")
        message = str(excinfo.value)
        assert "1" in message  # the row count — the operator's blast radius
        assert "strategy_portfolio_subscriptions" in message

        with engine.connect() as conn:
            count = conn.execute(
                text("SELECT count(*) FROM strategy_portfolio_subscriptions")
            ).scalar()
        assert count == 1  # REFUSED — never auto-cleared
    finally:
        engine.dispose()


# --------------------------------------------------------------------------------------
# D-09 — the config data move. THE test of this plan.
# --------------------------------------------------------------------------------------


def test_upgrade_moves_the_config_blob_by_value(tmp_path: pathlib.Path) -> None:
    """D-09: the blob seeded on the STATE row is byte-identical on the DEFINITION row after.

    Asserts EQUALITY against the seeded blob, never ``is not None`` — see the module
    docstring for why a non-null assertion is worthless for this specific failure mode.
    """
    url = f"sqlite+pysqlite:///{tmp_path / 'move.db'}"
    cfg = _alembic_config(url)
    command.upgrade(cfg, _REVISION_ONE)
    portfolio_id = uuid.uuid4()
    _seed_for_the_move(url, portfolio_id)

    # Precondition: the DESTINATION starts empty, so anything found there afterwards can
    # only have been put there by the migration.
    assert _read_portfolios_config(url, portfolio_id) is None

    command.upgrade(cfg, "head")

    assert _read_portfolios_config(url, portfolio_id) == _CONFIG_BLOB


def test_negative_control_destination_stays_empty_without_the_move_step(
    tmp_path: pathlib.Path,
) -> None:
    """NEGATIVE CONTROL: with the move step NOT run, the by-value assertion FAILS.

    Proves ``test_upgrade_moves_the_config_blob_by_value`` is load-bearing rather than
    vacuous. Without a control the likeliest silent failure is a test that seeds BOTH sides
    itself and would pass even if the migration moved nothing at all.

    The control is an A/B on the migration step itself: identical staging, but the chain
    stops at ``_REVISION_ONE`` so the revision carrying the D-09 move never runs. Deliberately
    NOT done by monkeypatching ``_move_config`` — Alembic re-imports each revision module per
    ``ScriptDirectory``, so a patched module object is NOT the one ``command.upgrade``
    executes, and the "disabled" step would quietly run anyway (observed: the stub had no
    effect and the blob moved regardless). An A/B on the chain has no such failure mode.
    """
    url = f"sqlite+pysqlite:///{tmp_path / 'nomove.db'}"
    cfg = _alembic_config(url)
    command.upgrade(cfg, _REVISION_ONE)
    portfolio_id = uuid.uuid4()
    _seed_for_the_move(url, portfolio_id)

    # The move step has NOT run. The destination is empty, so the positive test's EQUALITY
    # assertion is false here — which is exactly what makes it a real gate rather than a
    # tautology. A ``is not None`` check would be equally false, but it would ALSO be false
    # for a migration that wrote garbage; only the equality form pins the value.
    migrated = _read_portfolios_config(url, portfolio_id)
    assert migrated is None
    assert migrated != _CONFIG_BLOB


def test_load_config_returns_the_migrated_blob_through_the_store(
    tmp_path: pathlib.Path,
) -> None:
    """D-09 end-to-end: after the migration, ``load_config()`` reads the DEFINITION row.

    The legacy ``portfolio_account_state.config_json`` is deliberately CLEARED after the
    upgrade before the read. Revision 2 does not drop the old column (by design — it keeps the
    move recoverable), so a store still reading the STATE row would return the right blob for
    entirely the wrong reason and this test would pass vacuously. Blanking the old column is
    what forces the value to come from ``portfolios``.
    """
    db_path = tmp_path / "store.db"
    url = f"sqlite+pysqlite:///{db_path}"
    cfg = _alembic_config(url)
    command.upgrade(cfg, _REVISION_ONE)
    portfolio_id = uuid.uuid4()
    _seed_for_the_move(url, portfolio_id)
    command.upgrade(cfg, "head")

    scrub = create_engine(url)
    try:
        with scrub.begin() as conn:
            conn.execute(text("UPDATE portfolio_account_state SET config_json = NULL"))
    finally:
        scrub.dispose()

    # File-backed (not ``default()``'s ``:memory:``) so the store opens the SAME database the
    # migration just wrote. The schema is Alembic-owned here — no ``provision_schema`` call.
    backend = SqlEngine(
        SqlSettings(driver=SqlDriver.SQLITE_PYSQLITE, database=str(db_path))
    )
    try:
        store = SqlPortfolioStateStorage(backend, portfolio_id)
        assert store.load_config() == _CONFIG_BLOB
    finally:
        backend.dispose()


# --------------------------------------------------------------------------------------
# The rehomed save_config / load_config contract
# --------------------------------------------------------------------------------------


def _store_with_definition_row(portfolio_id: uuid.UUID) -> SqlPortfolioStateStorage:
    """An in-memory store whose portfolio HAS a ``portfolios`` definition row."""
    backend = SqlEngine(SqlSettings.default())
    store = SqlPortfolioStateStorage(backend, portfolio_id)
    provision_schema(backend)
    metadata = backend.metadata
    with backend.engine.begin() as conn:
        conn.execute(
            insert(metadata.tables["venue_accounts"]),
            [{
                "venue_name": "paper", "account_id": "main", "secret_ref": None,
                "venue_uid": None, "enabled": True, "config_json": {}, "updated_at": _NOW,
            }],
        )
        conn.execute(
            insert(metadata.tables["portfolios"]),
            [{
                "portfolio_id": portfolio_id, "name": "p11", "venue_name": "paper",
                "account_id": "main", "initial_cash": Decimal("10000.50"),
                "enabled": True, "config_json": None, "updated_at": _NOW,
            }],
        )
    return store


def test_save_then_load_config_round_trips_verbatim() -> None:
    """The blob returns with the same shape and type — no reshaping, no typed model."""
    store = _store_with_definition_row(uuid.uuid4())
    try:
        store.save_config(_CONFIG_BLOB, _NOW)
        loaded = store.load_config()
        assert loaded == _CONFIG_BLOB
        assert isinstance(loaded, dict)  # NOT coerced into a typed model (partial-merge)
    finally:
        store.dispose()


def test_load_config_is_none_when_the_definition_row_has_null_config() -> None:
    """``load_config()`` returns None (never raises) when nothing has been persisted."""
    store = _store_with_definition_row(uuid.uuid4())
    try:
        assert store.load_config() is None
    finally:
        store.dispose()


def test_save_config_writes_the_definition_row_not_the_state_row() -> None:
    """D-09: the WRITE lands on ``portfolios``, proving the rehome (not just the read)."""
    portfolio_id = uuid.uuid4()
    store = _store_with_definition_row(portfolio_id)
    try:
        store.save_config(_CONFIG_BLOB, _NOW)
        metadata = store.backend.metadata
        with store.engine.connect() as conn:
            on_definition = conn.execute(
                select(metadata.tables["portfolios"].c.config_json).where(
                    metadata.tables["portfolios"].c.portfolio_id == portfolio_id
                )
            ).scalar()
            state_rows = conn.execute(
                select(metadata.tables["portfolio_account_state"].c.config_json).where(
                    metadata.tables["portfolio_account_state"].c.portfolio_id
                    == portfolio_id
                )
            ).all()
        assert on_definition == _CONFIG_BLOB      # the DEFINITION row got it ...
        assert state_rows == []                    # ... and no state row was created at all
    finally:
        store.dispose()


def test_save_config_falls_back_to_the_state_row_without_a_definition_row() -> None:
    """The zero-sentinel arm SURVIVES this plan (owner decision, deferred to 11-08).

    Nothing constructs ``PortfolioDefinitionStore`` yet, so no ``portfolios`` row exists for
    a portfolio built in waves 2-4. Deleting the sentinel arm now — as the original plan text
    proposed, on the premise that "a definition row is guaranteed to exist" — would turn
    every ``save_config`` in that window into a hard error. 11-08 removes the arm once it
    creates the guarantee it depends on.
    """
    backend = SqlEngine(SqlSettings.default())
    portfolio_id = uuid.uuid4()
    try:
        store = SqlPortfolioStateStorage(backend, portfolio_id)
        provision_schema(backend)
        # No portfolios row for this id — the legacy arm must carry the write.
        store.save_config(_CONFIG_BLOB, _NOW)
        assert store.load_config() == _CONFIG_BLOB
    finally:
        backend.dispose()


# --------------------------------------------------------------------------------------
# create_all / migration parity for the two NEW tables
# --------------------------------------------------------------------------------------


def test_create_all_and_migration_agree_on_both_new_tables(
    tmp_path: pathlib.Path,
) -> None:
    """The registrars and the migration produce the SAME columns for both new tables.

    Extended BY HAND to name each table explicitly — the "the gate widens itself by dynamic
    enumeration" assumption was proven FALSE in Phase 9 and had to be corrected manually
    there too.
    """
    metadata = MetaData(naming_convention=NAMING_CONVENTION)
    build_venue_accounts_table(metadata)
    build_portfolio_definition_tables(metadata)
    declared = {
        name: {column.name for column in metadata.tables[name].columns}
        for name in ("venue_accounts", "portfolios")
    }

    url = f"sqlite+pysqlite:///{tmp_path / 'parity.db'}"
    command.upgrade(_alembic_config(url), "head")

    engine = create_engine(url)
    try:
        inspector = inspect(engine)
        for name, declared_columns in declared.items():
            reflected = {c["name"] for c in inspector.get_columns(name)}
            assert declared_columns == reflected, f"registrar/migration drift on {name}"
    finally:
        engine.dispose()

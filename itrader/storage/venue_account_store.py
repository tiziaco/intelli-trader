"""Durable per-ACCOUNT venue store — the ``(venue_name, account_id)`` home (MPORT-02 / D-05).

One flat row per venue ACCOUNT on the shared ``SqlEngine`` spine. The row is addressed by the
COMPOSITE NATURAL key ``(venue_name, account_id)`` (D-01): ``account_id`` alone can never
derive its venue — ``"main"`` on ``okx`` and ``"main"`` on a future venue are different
accounts by design — so an account reference is inherently two columns. There is no surrogate
id column and no UUIDv7 id generator is imported here, matching the natural-key shape of
``VenueStore`` (D-06) and the ``ConnectorProvider._memo`` pair key.

**The three-lifecycle column split (D-05).** The three things a row carries change on three
different schedules, so they are three columns rather than one blob:

* ``secret_ref`` — a POINTER at wherever the credential actually lives; operator-rotated,
  nullable (D-06: a paper account has no credential at all).
* ``venue_uid`` — the engine-written trust-on-first-use value (D-04). Written by plan 11-04,
  never by an operator; nullable until first observation.
* ``config_json`` — operator-authored connection config (``sandbox``, ``region``, and whatever
  a future venue kind needs). Absorbing venue-kind variation here means a new venue's knobs
  never require a migration.

SECURITY — this row holds a POINTER, never a credential (D-02, T-11-01). The column is named
``secret_ref`` and MUST NOT be named ``credentials``: the shared denylist matches on EXACT
lowercased membership, so ``"credential"`` (singular) is denied while ``"credentials"``
(plural) would pass by one letter and land live exchange keys in every ``pg_dump``, read
replica and backup snapshot. The recursive guard ``_assert_no_secret_keys`` is REUSED from
``venue_store`` (never rebuilt as a second denylist that could drift) and fires as the FIRST
statement of ``upsert``, BEFORE the transaction opens, so a rejected write persists NOTHING.

A disciplined clone of the ``VenueStore`` template (STORE-02 / STORE-04 / D-01): composes
``SqlEngine`` by reference, owns its ``build_venue_accounts_table`` registrar (single source of
truth for BOTH the test-path provisioning helper and ``migrations/env.py``), schema-pure
(WR-03/D-14 — this module never creates its own schema at runtime; the durable schema is
Alembic-owned in production and provisioned by ``provision_schema`` in tests),
caller-supplied ``at`` via ``UtcIsoText`` (D-07 — clock-free), parameterized Core only
(SEC-01 / T-11-01).

4-space indentation (matches the ``itrader/storage`` spine layer).
"""

from datetime import datetime
from typing import Any, Mapping, Optional

from sqlalchemy import (
    Boolean,
    Column,
    MetaData,
    String,
    Table,
    delete,
    insert,
    select,
    update,
)
from sqlalchemy.engine import Engine, RowMapping

from itrader.logger import get_itrader_logger
from itrader.storage import SqlEngine, UtcIsoText, json_variant
from itrader.storage.venue_store import _assert_no_secret_keys


def build_venue_accounts_table(metadata: MetaData) -> Table:
    """Register (idempotently) the single ``venue_accounts`` table on ``metadata``.

    Idempotent on a shared backend (reuse an already-registered table). Single source of
    truth for the ``venue_accounts`` schema, feeding both the test-path provisioning helper
    and the Alembic ``target_metadata`` in ``migrations/env.py``: a divergence between this registrar
    and a migration silently splits the test-path and prod schemas.

    Columns: ``venue_name`` + ``account_id`` (the COMPOSITE natural PK — D-01, no surrogate
    id), the three-lifecycle split ``secret_ref`` (operator-rotated pointer, nullable for
    D-06 paper rows) / ``venue_uid`` (engine-written TOFU, nullable until first observation —
    D-04) / ``config_json`` (operator-authored, portable JSON), plus the typed ``enabled``
    Boolean and the ``updated_at`` UTC-isoformat business timestamp (D-07).
    """
    if "venue_accounts" in metadata.tables:
        return metadata.tables["venue_accounts"]
    return Table(
        "venue_accounts",
        metadata,
        # D-01 — the PAIR is the identity. Both halves are the PK; no surrogate id column.
        Column("venue_name", String, primary_key=True),
        Column("account_id", String, primary_key=True),
        # D-02/D-05 — a POINTER at the credential, never the credential. NULL for paper
        # accounts (D-06), which have nothing to point at.
        Column("secret_ref", String, nullable=True),
        # D-04/D-05 — engine-written trust-on-first-use; plan 11-04 writes it, never an
        # operator. NULL until the venue identity is first observed.
        Column("venue_uid", String, nullable=True),
        Column("enabled", Boolean, nullable=False),
        # D-05 — operator-authored connection config (sandbox, region, future venue knobs).
        Column("config_json", json_variant(), nullable=False),
        Column("updated_at", UtcIsoText, nullable=False),
    )


class VenueAccountStore:
    """Per-``(venue_name, account_id)`` account definitions — upsert / get / read-all.

    Parameters
    ----------
    sql_engine:
        The shared spine (Engine + MetaData). The driver/URL is config-selected at wiring;
        this store registers its one table on ``sql_engine.metadata`` but does NOT create it
        — the durable schema is Alembic-owned in production (WR-03/D-14) and provisioned by
        the shared ``provision_schema`` test fixture in tests.
    """

    def __init__(self, sql_engine: SqlEngine) -> None:
        self.backend = sql_engine
        self.engine: Engine = sql_engine.engine
        self.venue_accounts: Table = build_venue_accounts_table(sql_engine.metadata)
        # WR-03/D-14 — schema-pure: register the table, never create it here (Alembic-owned
        # in production; tests provision via tests.support.schema.provision_schema).
        self.logger = get_itrader_logger().bind(component="VenueAccountStore")

    def dispose(self) -> None:
        """Dispose the shared backend engine (WR-03 — delegate, never engine.dispose())."""
        self.backend.dispose()

    def upsert(
        self,
        venue_name: str,
        account_id: str,
        *,
        secret_ref: Optional[str],
        venue_uid: Optional[str],
        enabled: bool,
        config: dict[str, Any],
        at: datetime,
    ) -> None:
        """Persist (or overwrite) one account row with ``updated_at`` ``at``.

        The REUSED recursive secret-denylist guard (D-02) fires FIRST, so a rejected write
        persists NOTHING (the delete-then-insert never runs). Portable delete-then-insert on
        the composite key in ONE transaction; parameterized Core against the constant
        ``Table`` (SEC-01).
        """
        _assert_no_secret_keys(config)
        with self.engine.begin() as connection:
            connection.execute(
                delete(self.venue_accounts).where(
                    self.venue_accounts.c.venue_name == venue_name,
                    self.venue_accounts.c.account_id == account_id,
                )
            )
            connection.execute(
                insert(self.venue_accounts),
                [
                    {
                        "venue_name": venue_name,
                        "account_id": account_id,
                        "secret_ref": secret_ref,
                        "venue_uid": venue_uid,
                        "enabled": enabled,
                        "config_json": config,
                        "updated_at": at,
                    }
                ],
            )

    def record_venue_uid(
        self,
        venue_name: str,
        account_id: str,
        venue_uid: str,
        at: datetime,
    ) -> None:
        """Write the engine-observed ``venue_uid`` for one pair (D-04 trust-on-first-use).

        A TARGETED UPDATE of ``venue_uid`` (and ``updated_at``) only, leaving
        ``secret_ref`` / ``config_json`` / ``enabled`` untouched. ``venue_uid`` is
        ENGINE-written on first observation, so it must NOT travel through the
        operator-authored ``upsert`` path: routing it there would make the engine
        restate — and therefore able to clobber — the operator's own columns from a
        connect-time code path.

        Parameterized Core against the constant ``Table`` (SEC-01 / T-11-01). A pair
        with no row is a silent no-op (zero rows matched): account MINTING is plan
        11-07's job, not this write's.
        """
        with self.engine.begin() as connection:
            connection.execute(
                update(self.venue_accounts)
                .where(
                    self.venue_accounts.c.venue_name == venue_name,
                    self.venue_accounts.c.account_id == account_id,
                )
                .values(venue_uid=venue_uid, updated_at=at)
            )

    def get(self, venue_name: str, account_id: str) -> Optional[Mapping[str, Any]]:
        """The account row for the ``(venue_name, account_id)`` pair, or None when absent."""
        statement = self._select_columns().where(
            self.venue_accounts.c.venue_name == venue_name,
            self.venue_accounts.c.account_id == account_id,
        )
        with self.engine.connect() as connection:
            row = connection.execute(statement).mappings().first()
        if row is None:
            return None
        return self._row_to_dict(row)

    def read_all(self) -> list[Mapping[str, Any]]:
        """Every account row — the rehydrate read.

        ORDERING CONTRACT: ``venue_name`` ASC then ``account_id`` ASC, so the rehydrate order
        is deterministic and reproducible across runs and dialects rather than
        driver-dependent (an unordered SELECT has no guaranteed row order).
        """
        statement = self._select_columns().order_by(
            self.venue_accounts.c.venue_name.asc(),
            self.venue_accounts.c.account_id.asc(),
        )
        with self.engine.connect() as connection:
            rows = connection.execute(statement).mappings().all()
        return [self._row_to_dict(row) for row in rows]

    def _select_columns(self) -> Any:
        """The shared column projection every read uses (one place to keep them in sync)."""
        return select(
            self.venue_accounts.c.venue_name,
            self.venue_accounts.c.account_id,
            self.venue_accounts.c.secret_ref,
            self.venue_accounts.c.venue_uid,
            self.venue_accounts.c.enabled,
            self.venue_accounts.c.config_json,
            self.venue_accounts.c.updated_at,
        )

    @staticmethod
    def _row_to_dict(row: "RowMapping") -> dict[str, Any]:
        """Map a result row to the store's public dict shape (bool coerced from the driver)."""
        return {
            "venue_name": row["venue_name"],
            "account_id": row["account_id"],
            "secret_ref": row["secret_ref"],
            "venue_uid": row["venue_uid"],
            "enabled": bool(row["enabled"]),
            "config": row["config_json"],
            "updated_at": row["updated_at"],
        }

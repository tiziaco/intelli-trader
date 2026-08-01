"""Durable per-ACCOUNT venue store — the ``(venue_name, account_id)`` home.

One flat row per venue ACCOUNT on the shared ``SqlEngine`` spine. The row is addressed by the
COMPOSITE NATURAL key ``(venue_name, account_id)``: ``account_id`` alone can never derive its
venue — ``"main"`` on ``okx`` and ``"main"`` on a future venue are different accounts by
design — so an account reference is inherently two columns. There is no surrogate id column
and no UUIDv7 id generator is imported here, matching the natural-key shape of ``VenueStore``
and the ``ConnectorPool`` session key.

**The three-lifecycle column split.** The three things a row carries change on three
different schedules, so they are three columns rather than one blob:

* ``secret_ref`` — a POINTER at wherever the credential actually lives; operator-rotated,
  nullable (a paper account has no credential at all).
* ``venue_uid`` — the engine-written trust-on-first-use value; never written by an operator;
  nullable until first observation.
* ``config_json`` — operator-authored connection config (``sandbox``, ``region``, and whatever
  a future venue kind needs). Absorbing venue-kind variation here means a new venue's knobs
  never require a migration.

SECURITY — this row holds a POINTER, never a credential. The column is named ``secret_ref``
and MUST NOT be named ``credentials``: the shared denylist matches on EXACT lowercased
membership, so ``"credential"`` (singular) is denied while ``"credentials"`` (plural) would
pass by one letter and land live exchange keys in every ``pg_dump``, read replica and backup
snapshot. The recursive guard ``_assert_no_secret_keys`` is REUSED from ``venue_store`` (never
rebuilt as a second denylist that could drift) and fires as the FIRST statement of ``upsert``,
BEFORE the transaction opens, so a rejected write persists NOTHING.

A disciplined clone of the ``VenueStore`` template: composes ``SqlEngine`` by reference, owns
its ``build_venue_accounts_table`` registrar (single source of truth for BOTH the test-path
provisioning helper and ``migrations/env.py``), schema-pure (this module never creates its own
schema at runtime; the durable schema is Alembic-owned in production and provisioned by
``provision_schema`` in tests), caller-supplied ``at`` via ``UtcIsoText`` (clock-free),
parameterized Core only.
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

    Columns: ``venue_name`` + ``account_id`` (the COMPOSITE natural PK, no surrogate
    id), the three-lifecycle split ``secret_ref`` (operator-rotated pointer, nullable for
    paper rows) / ``venue_uid`` (engine-written TOFU, nullable until first observation) /
    ``config_json`` (operator-authored, portable JSON), plus the typed ``enabled``
    Boolean and the ``updated_at`` UTC-isoformat business timestamp.
    """
    if "venue_accounts" in metadata.tables:
        return metadata.tables["venue_accounts"]
    return Table(
        "venue_accounts",
        metadata,
        # The PAIR is the identity. Both halves are the PK; no surrogate id column.
        Column("venue_name", String, primary_key=True),
        Column("account_id", String, primary_key=True),
        # A POINTER at the credential, never the credential. NULL for paper accounts,
        # which have nothing to point at.
        Column("secret_ref", String, nullable=True),
        # Engine-written trust-on-first-use, never an operator. NULL until the venue
        # identity is first observed.
        Column("venue_uid", String, nullable=True),
        Column("enabled", Boolean, nullable=False),
        # Operator-authored connection config (sandbox, region, future venue knobs).
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
        — the durable schema is Alembic-owned in production and provisioned by
        the shared ``provision_schema`` test fixture in tests.
    """

    def __init__(self, sql_engine: SqlEngine) -> None:
        self.backend = sql_engine
        self.engine: Engine = sql_engine.engine
        self.venue_accounts: Table = build_venue_accounts_table(sql_engine.metadata)
        self.logger = get_itrader_logger().bind(component="VenueAccountStore")

    def dispose(self) -> None:
        """Dispose the shared backend engine (delegate, never engine.dispose())."""
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

        The REUSED recursive secret-denylist guard fires FIRST, so a rejected write
        persists NOTHING (the delete-then-insert never runs). Portable delete-then-insert on
        the composite key in ONE transaction; parameterized Core against the constant
        ``Table``.
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

    def create(
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
        """CREATE one account row; the DATABASE refuses a duplicate pair.

        The create-only sibling of ``upsert``, and it exists because ``upsert`` CANNOT
        express this contract: ``upsert`` is a DELETE-then-INSERT on the composite key, so
        a second write always succeeds and silently CLOBBERS the operator's ``secret_ref``
        and ``config_json`` while resetting the engine-written ``venue_uid`` to NULL —
        disarming the trust-on-first-use venue-identity guard for that account. A
        provisioning verb built on ``upsert`` would therefore overwrite rather than refuse,
        and a caller trying to classify a duplicate would wait forever for an
        ``IntegrityError`` that never arrives.

        A plain ``INSERT``: the composite primary key ``(venue_name, account_id)`` is the
        arbiter, so a duplicate raises ``IntegrityError`` out of the driver. Refusing here
        rather than in front of the write is deliberate — a pre-check ``SELECT`` is
        TOCTOU and, decisively, does not bind the out-of-band writers a durable table
        always has. Classification of that error into a typed refusal belongs to the
        CALLER (``VenueAccountManager``); this store stays a store.

        The REUSED recursive secret-denylist guard fires FIRST — the same single
        control ``upsert`` runs, never a second denylist that could drift — so a rejected
        write persists NOTHING.
        """
        _assert_no_secret_keys(config)
        with self.engine.begin() as connection:
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
        """Write the engine-observed ``venue_uid`` for one pair (trust-on-first-use).

        A TARGETED UPDATE of ``venue_uid`` (and ``updated_at``) only, leaving
        ``secret_ref`` / ``config_json`` / ``enabled`` untouched. ``venue_uid`` is
        ENGINE-written on first observation, so it must NOT travel through the
        operator-authored ``upsert`` path: routing it there would make the engine
        restate — and therefore able to clobber — the operator's own columns from a
        connect-time code path.

        Parameterized Core against the constant ``Table``. A pair with no row is a
        silent no-op (zero rows matched): account MINTING happens through ``create``,
        not this write.
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

    def set_enabled(
        self,
        venue_name: str,
        account_id: str,
        enabled: bool,
        at: datetime,
    ) -> None:
        """Enable/disable one account — a TARGETED UPDATE of ``enabled`` only.

        The durable half of the account-level enable flag. A TARGETED UPDATE of
        ``enabled`` (and ``updated_at``) only, leaving ``secret_ref`` / ``venue_uid`` /
        ``config_json`` UNTOUCHED — same reasoning as ``record_venue_uid``: it must NOT
        travel through the operator-authored ``upsert`` (a DELETE-then-INSERT that would
        restate, and therefore be able to clobber, the operator's own columns and reset the
        trust-on-first-use ``venue_uid`` to NULL). The REFUSAL that guards a disable
        (a live portfolio still depends on this account) is the CALLER's job
        (``VenueAccountManager.set_enabled``), never this store's — this store stays a
        store.

        Clock-free: caller-supplied ``at``. A pair with no row is a silent no-op
        (zero rows matched), matching ``record_venue_uid``. Parameterized Core against the
        constant ``Table``.
        """
        with self.engine.begin() as connection:
            connection.execute(
                update(self.venue_accounts)
                .where(
                    self.venue_accounts.c.venue_name == venue_name,
                    self.venue_accounts.c.account_id == account_id,
                )
                .values(enabled=enabled, updated_at=at)
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

    def read_enabled_for(self, venue_name: str) -> list[Mapping[str, Any]]:
        """Every ENABLED account row for one venue — the bring-up read.

        The venue-scoped, enabled-only sibling of ``read_all``, sharing its projection
        and its ordering guarantee. It is what turns boot into
        ``for row in read_enabled_for(venue): bring_online(row)``, so the account SET a
        venue comes up with is derived from durable rows rather than re-derived from a spec.

        Venue scoping is not a convenience filter: ``account_id`` alone can never derive
        its venue, so an unscoped read would hand one venue another venue's accounts and
        assemble them against the wrong plugin.

        ORDERING CONTRACT: ``venue_name`` ASC then ``account_id`` ASC — identical to
        ``read_all``, so bring-up order is deterministic and reproducible across runs and
        dialects rather than driver-dependent (an unordered SELECT has no guaranteed row
        order). The ``venue_name`` key is redundant under the equality filter and is kept
        anyway so the two reads cannot drift apart.

        NO degrade policy lives here. A missing ``venue_accounts`` table is the
        fresh-deployment state and is handled ONE layer up in ``VenueAccountManager``,
        where the whole policy is unit-testable without booting a system; this method
        propagates every fault to that owner.
        """
        statement = (
            self._select_columns()
            .where(
                self.venue_accounts.c.venue_name == venue_name,
                self.venue_accounts.c.enabled.is_(True),
            )
            .order_by(
                self.venue_accounts.c.venue_name.asc(),
                self.venue_accounts.c.account_id.asc(),
            )
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

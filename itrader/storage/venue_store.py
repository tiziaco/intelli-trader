"""Durable per-venue config store — enabled flag + JSON config, secret-scrub guarded (STORE-02).

A per-venue durable store on the shared ``SqlEngine`` spine: ``upsert(venue_name, config,
enabled, at)`` persists one row per NATURAL ``venue_name`` (D-06 — no UUIDv7 surrogate,
``idgen`` never imported), with a typed ``enabled`` Boolean column (queryable — serves
``list_enabled``) alongside the portable JSON ``config_json`` (D-08). A disciplined clone of
the ``HaltRecordStore`` template (STORE-04 / D-01): composes ``SqlEngine`` by reference, owns
its ``build_venue_store_table`` registrar (single source of truth for BOTH the test-path
``create_all`` and Plan 04-03's ``migrations/env.py``), schema-pure (WR-03/D-14 — no runtime
``create_all``; Alembic-owned in production, ``provision_schema`` in tests), caller-supplied
``at`` via ``UtcIsoText`` (D-07 — clock-free), parameterized Core only (SEC-01 / T-04-02).

SECURITY — never store secrets (D-05, T-04-01). Two arms:

* **Structural.** Credentials are connector / ``OkxSettings`` (``SecretStr``)-owned and are
  NEVER passed to this store — venue config here is the non-secret operational surface
  (region, sandbox flag, rate limits, symbol filters).
* **Defensive (this module).** A write-time recursive denylist guard walks ``config_json``
  (dicts AND lists-of-dicts, any depth — Pitfall 6) and raises ``ValidationError`` when any
  key's lowercased name is in ``_SECRET_KEY_DENYLIST``. It fires at the TOP of ``upsert``
  BEFORE the delete-then-insert, so a rejected write persists NOTHING.

4-space indentation (matches the ``itrader/storage`` spine layer).
"""

from datetime import datetime
from typing import Any, Mapping, Optional

from sqlalchemy import Boolean, Column, MetaData, String, Table, delete, insert, select
from sqlalchemy.engine import Engine, RowMapping

from itrader.core.exceptions import ValidationError
from itrader.logger import get_itrader_logger
from itrader.storage import SqlEngine, UtcIsoText, json_variant

# The secret-like key denylist (D-05 defensive arm). Lowercased-name membership; the guard
# below walks every nested key at any depth. Pinned to at least the milestone-named set; a
# superset is welcome — a false-positive is a loud, safe failure (the caller must not put a
# credential in venue config anyway, since credentials are connector-owned).
_SECRET_KEY_DENYLIST: frozenset[str] = frozenset(
    {
        "api_key",
        "apikey",
        "secret",
        "secret_key",
        "password",
        "passphrase",
        "token",
        "access_token",
        "private_key",
        "credential",
    }
)


def _assert_no_secret_keys(config: Any, *, path: str = "config_json") -> None:
    """Recursively reject a secret-like key anywhere in ``config`` (dicts + lists, any depth).

    Walks dict keys (checking the lowercased name against ``_SECRET_KEY_DENYLIST``) and
    recurses into dict values and list items (Pitfall 6 — a nested or list-of-dicts secret
    must not slip past a top-level-only check). Raises ``ValidationError`` on the first hit.
    """
    if isinstance(config, dict):
        for key, value in config.items():
            if isinstance(key, str) and key.lower() in _SECRET_KEY_DENYLIST:
                raise ValidationError(
                    field="config_json",
                    message=(
                        f"secret-like key {key!r} is not allowed at {path}; credentials "
                        "are connector-owned and must never be persisted to VenueStore"
                    ),
                )
            _assert_no_secret_keys(value, path=f"{path}.{key}")
        return
    if isinstance(config, list):
        for index, item in enumerate(config):
            _assert_no_secret_keys(item, path=f"{path}[{index}]")


def build_venue_store_table(metadata: MetaData) -> Table:
    """Register (idempotently) the single ``venue_store`` table on ``metadata`` and return it.

    Idempotent on a shared backend (reuse an already-registered table). Single source of
    truth for the ``venue_store`` schema feeding both the test-path ``create_all`` and the
    Plan 04-03 Alembic autogenerate.

    Columns: ``venue_name`` (natural String PK — D-06), ``enabled`` (typed Boolean — serves
    ``list_enabled``), ``config_json`` (portable JSON — D-08), ``updated_at`` (UTC-isoformat
    business timestamp — D-07).
    """
    if "venue_store" in metadata.tables:
        return metadata.tables["venue_store"]
    return Table(
        "venue_store",
        metadata,
        Column("venue_name", String, primary_key=True),
        Column("enabled", Boolean, nullable=False),
        Column("config_json", json_variant(), nullable=False),
        Column("updated_at", UtcIsoText, nullable=False),
    )


class VenueStore:
    """Per-venue config + enabled upsert / get / delete / list_enabled / read-all.

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
        self.venue_store: Table = build_venue_store_table(sql_engine.metadata)
        # WR-03/D-14 — schema-pure: register the table, never create it (Alembic-owned in
        # production; tests provision via tests.support.schema.provision_schema).
        self.logger = get_itrader_logger().bind(component="VenueStore")

    def dispose(self) -> None:
        """Dispose the shared backend engine (WR-03 — delegate, never engine.dispose())."""
        self.backend.dispose()

    def upsert(
        self, venue_name: str, config: dict[str, Any], enabled: bool, at: datetime
    ) -> None:
        """Persist (or overwrite) a venue's config + enabled flag with ``updated_at`` ``at``.

        The recursive secret-denylist guard (D-05) fires FIRST, so a rejected write persists
        NOTHING (the delete-then-insert never runs). Portable delete-then-insert in ONE
        transaction; parameterized Core against the constant ``Table`` (SEC-01).
        """
        _assert_no_secret_keys(config)
        with self.engine.begin() as connection:
            connection.execute(
                delete(self.venue_store).where(
                    self.venue_store.c.venue_name == venue_name
                )
            )
            connection.execute(
                insert(self.venue_store),
                [
                    {
                        "venue_name": venue_name,
                        "enabled": enabled,
                        "config_json": config,
                        "updated_at": at,
                    }
                ],
            )

    def get(self, venue_name: str) -> Optional[Mapping[str, Any]]:
        """The ``{"venue_name", "config", "enabled", "updated_at"}`` row, or None when absent."""
        statement = select(
            self.venue_store.c.venue_name,
            self.venue_store.c.enabled,
            self.venue_store.c.config_json,
            self.venue_store.c.updated_at,
        ).where(self.venue_store.c.venue_name == venue_name)
        with self.engine.connect() as connection:
            row = connection.execute(statement).mappings().first()
        if row is None:
            return None
        return self._row_to_dict(row)

    def delete(self, venue_name: str) -> None:
        """Remove the row for ``venue_name`` (no-op when absent)."""
        with self.engine.begin() as connection:
            connection.execute(
                delete(self.venue_store).where(
                    self.venue_store.c.venue_name == venue_name
                )
            )

    def list_enabled(self) -> list[Mapping[str, Any]]:
        """Every venue row with ``enabled=True`` — the typed-column query (D-09)."""
        statement = select(
            self.venue_store.c.venue_name,
            self.venue_store.c.enabled,
            self.venue_store.c.config_json,
            self.venue_store.c.updated_at,
        ).where(self.venue_store.c.enabled.is_(True))
        with self.engine.connect() as connection:
            rows = connection.execute(statement).mappings().all()
        return [self._row_to_dict(row) for row in rows]

    def read_all(self) -> list[Mapping[str, Any]]:
        """Every venue row — the rehydrate read."""
        statement = select(
            self.venue_store.c.venue_name,
            self.venue_store.c.enabled,
            self.venue_store.c.config_json,
            self.venue_store.c.updated_at,
        )
        with self.engine.connect() as connection:
            rows = connection.execute(statement).mappings().all()
        return [self._row_to_dict(row) for row in rows]

    @staticmethod
    def _row_to_dict(row: "RowMapping") -> dict[str, Any]:
        """Map a result row to the store's public dict shape (bool coerced from the driver)."""
        return {
            "venue_name": row["venue_name"],
            "config": row["config_json"],
            "enabled": bool(row["enabled"]),
            "updated_at": row["updated_at"],
        }

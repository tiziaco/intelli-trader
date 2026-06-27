"""Cross-dialect SQL type helpers for the spine (SPINE-03, D-13).

One canonical encoding per type, applied uniformly so a value written under SQLite
reads back equal under Postgres. The whole module is three primitives — the SPINE-03
"lossless + equal" guarantee lives here:

- ``Uuid(as_uuid=True)`` is used directly at columns (re-exported below for convenience):
  it compiles to ``CHAR(32)`` on SQLite and native ``UUID`` on Postgres, and a UUIDv7 from
  ``idgen`` / ``uuid_utils.compat.uuid7()`` round-trips back as an *equal* ``uuid.UUID`` on
  both dialects (D-03). Do NOT hand-roll a per-dialect TEXT/BLOB switch — that reintroduces
  the inconsistent-encoding bug.
- ``UtcIsoText`` stores business-time as ISO-8601 UTC TEXT on both dialects (D-04/D-05).
  Native Postgres ``timestamp`` is microsecond precision and would silently truncate finer
  pandas precision; an explicit UTC-isoformat encoding dodges that and yields *identical
  bytes across runs* (determinism). The round-trip is instant-preserving and UTC-normalized.
- ``json_variant()`` is a portable JSON column — ``JSON`` on SQLite, ``JSONB`` on Postgres.

There is deliberately no money / Decimal-as-text TypeDecorator (D-13): money never lands
on a SQLite-family backend this milestone (the results store is all-``Float``; operational
money is Postgres-native exact-precision in a later phase).
"""

from datetime import datetime, timezone

from sqlalchemy import JSON, String, TypeDecorator, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.engine.interfaces import Dialect

__all__ = ["Uuid", "UuidType", "UtcIsoText", "json_variant"]

# Ids: use the built-in directly at the column — ``Uuid(as_uuid=True)`` compiles to
# CHAR(32) on SQLite and native UUID on Postgres, value-equal both ways (D-03). The
# instance alias is provided for documentation; ``Uuid`` is re-exported for column use.
UuidType = Uuid(as_uuid=True)


class UtcIsoText(TypeDecorator[datetime]):
    """Business-time as ISO-8601 UTC TEXT — uniform on both dialects (D-04/D-05).

    ``process_bind_param`` normalizes any aware datetime to UTC then emits
    ``datetime.isoformat()`` → identical bytes across runs (determinism). ``process_result_value``
    reconstructs the instant via ``datetime.fromisoformat()`` (lossless, microsecond precision).
    ``cache_ok = True`` is REQUIRED for SQLAlchemy statement caching and mypy --strict.
    """

    impl = String
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Dialect) -> str | None:
        if value is None:
            return None
        return value.astimezone(timezone.utc).isoformat()

    def process_result_value(self, value: str | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        return datetime.fromisoformat(value)


def json_variant() -> JSON:
    """Portable JSON column — ``JSONB`` on Postgres, ``JSON`` (TEXT) on SQLite."""
    return JSON().with_variant(JSONB(), "postgresql")

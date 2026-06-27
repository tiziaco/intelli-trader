"""Unit tests for ``itrader/storage/types.py`` — cross-dialect type helpers (SPINE-03).

Asserts the five D-13 behaviors of the spine's encoding layer:

1. ``UtcIsoText.process_bind_param`` is deterministic — two binds of the same aware
   datetime produce byte-identical UTC isoformat text.
2. A non-UTC business time stored through ``UtcIsoText`` into in-process SQLite reads
   back instant-equal (UTC-normalized).
3. ``json_variant()`` compiles to ``JSON`` on sqlite and ``JSONB`` on postgresql.
4. ``Uuid(as_uuid=True)`` compiles to ``CHAR(32)`` on sqlite and a UUIDv7 round-trips
   through a SQLite column as an equal ``uuid.UUID``.
5. There is NO ``DecimalAsText`` / money TypeDecorator anywhere in the module (D-13 —
   money never touches a SQLite-family backend this milestone).
"""

import uuid
from datetime import datetime, timedelta, timezone

import uuid_utils.compat as uc
from sqlalchemy import Column, MetaData, Table, Uuid, create_engine, insert, select
from sqlalchemy.dialects import postgresql, sqlite

from itrader.storage import types as storage_types
from itrader.storage.types import UtcIsoText, json_variant


def test_utc_iso_text_bind_is_deterministic() -> None:
    """Two binds of the same aware datetime produce byte-identical UTC isoformat text."""
    decorator = UtcIsoText()
    aware = datetime(2018, 1, 1, 1, 0, 0, tzinfo=timezone(timedelta(hours=1)))
    first = decorator.process_bind_param(aware, sqlite.dialect())
    second = decorator.process_bind_param(aware, sqlite.dialect())
    assert first == second
    assert first == "2018-01-01T00:00:00+00:00"


def test_utc_iso_text_roundtrips_instant_equal_via_sqlite() -> None:
    """A non-UTC business time stored through UtcIsoText reads back instant-equal (UTC)."""
    metadata = MetaData()
    table = Table("ts_probe", metadata, Column("ts", UtcIsoText, primary_key=True))
    engine = create_engine("sqlite+pysqlite:///:memory:")
    metadata.create_all(engine)
    paris = datetime(2018, 1, 1, 1, 0, 0, tzinfo=timezone(timedelta(hours=1)))
    with engine.begin() as conn:
        conn.execute(insert(table).values(ts=paris))
    with engine.connect() as conn:
        got = conn.execute(select(table.c.ts)).scalar_one()
    assert got == paris  # aware-datetime == compares the UTC instant
    assert got.utcoffset() == timedelta(0)  # +01:00 normalized to +00:00


def test_utc_iso_text_passes_through_none() -> None:
    decorator = UtcIsoText()
    assert decorator.process_bind_param(None, sqlite.dialect()) is None
    assert decorator.process_result_value(None, sqlite.dialect()) is None


def test_json_variant_compiles_per_dialect() -> None:
    variant = json_variant()
    assert str(variant.compile(dialect=sqlite.dialect())) == "JSON"
    assert str(variant.compile(dialect=postgresql.dialect())) == "JSONB"


def test_uuid_compiles_char32_on_sqlite_and_roundtrips_equal() -> None:
    assert str(Uuid(as_uuid=True).compile(dialect=sqlite.dialect())) == "CHAR(32)"
    metadata = MetaData()
    table = Table("id_probe", metadata, Column("id", Uuid(as_uuid=True), primary_key=True))
    engine = create_engine("sqlite+pysqlite:///:memory:")
    metadata.create_all(engine)
    run_id = uc.uuid7()
    with engine.begin() as conn:
        conn.execute(insert(table).values(id=run_id))
    with engine.connect() as conn:
        got = conn.execute(select(table.c.id)).scalar_one()
    assert got == run_id
    assert isinstance(got, uuid.UUID)


def test_no_money_type_in_module() -> None:
    """D-13 — money never touches SQLite this milestone; no money TypeDecorator exists."""
    assert not hasattr(storage_types, "DecimalAsText")
    assert not hasattr(storage_types, "Numeric")

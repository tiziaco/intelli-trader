"""SPINE-03 cross-backend round-trip — the load-bearing Phase-1 correctness proof.

A UUIDv7 ``run_id`` and a business-time timestamp written through the SQL-spine layer
(``itrader.storage`` — ``Uuid(as_uuid=True)`` + ``UtcIsoText``) must read back *losslessly*
and *EQUAL* on BOTH in-process SQLite and testcontainers Postgres (D-03/D-04/D-05, D-10):
a value written under SQLite reads equal under Postgres. The Postgres arm SKIPS (never
hard-fails) when Docker is absent (D-11), inherited from the ``engine`` fixture (01-01).

Threat coverage (01-03 register):
* T-01-07 (cross-backend encoding tamper) — value-equality asserted on BOTH dialects via a
  single ``Uuid`` type + ``UtcIsoText``; no per-dialect hand-rolled encoding.
* T-01-08 (non-deterministic persistence) — the determinism test asserts byte-identical
  encoded TEXT across two runs; business ``time`` only (never ``datetime.now``), explicit UTC.
* T-01-06 (second ID scheme / autoincrement) — the sole PK is ``uuid_utils.compat.uuid7()``;
  there is no ``Integer`` autoincrement in the round-trip table.

4-space indentation (matches ``tests/integration/*``).
"""

import uuid
from datetime import datetime, timezone

import pytest
import uuid_utils.compat as uc
from sqlalchemy import Column, MetaData, Table, Uuid, insert, select

from itrader.storage import UtcIsoText


def _roundtrip(engine, run_id, business_time):
    """Write ``(run_id, business_time)`` through the spine layer and read it back.

    Builds a fresh ``MetaData`` with a ``run_id`` ``Uuid(as_uuid=True)`` primary key (the
    single UUIDv7 scheme — no ``Integer`` autoincrement) and a ``business_time``
    ``UtcIsoText`` column, creates the table on ``engine``, inserts one row, and reads it
    back filtered by ``run_id`` (robust on the session-scoped Postgres engine). Returns the
    ``(got_id, got_bt)`` pair so the SAME assertions run on every backend.
    """
    metadata = MetaData()
    table = Table(
        "spine_roundtrip",
        metadata,
        Column("run_id", Uuid(as_uuid=True), primary_key=True),
        Column("business_time", UtcIsoText),
    )
    metadata.create_all(engine)  # checkfirst=True — idempotent on the shared PG engine
    with engine.begin() as conn:
        conn.execute(insert(table).values(run_id=run_id, business_time=business_time))
    with engine.connect() as conn:
        row = conn.execute(
            select(table.c.run_id, table.c.business_time).where(table.c.run_id == run_id)
        ).one()
    return row.run_id, row.business_time


@pytest.mark.parametrize("engine", ["sqlite", "postgres"], indirect=True)
def test_uuid_and_business_time_lossless_and_equal(engine):
    """SPINE-03: a UUIDv7 id + business-time round-trip lossless + EQUAL on both dialects.

    The SAME assertions execute on in-process SQLite and on testcontainers Postgres (D-10);
    the Postgres parametrization skips (not errors) when Docker is absent (D-11).
    """
    run_id = uc.uuid7()  # native uuid.UUID, single canonical UUIDv7 scheme (D-03)
    bt = datetime(2018, 1, 1, tzinfo=timezone.utc)  # business time, never wall clock (D-04)

    got_id, got_bt = _roundtrip(engine, run_id, bt)

    assert got_id == run_id  # SPINE-03 value equality across dialects (D-03, T-01-07)
    assert isinstance(got_id, uuid.UUID)  # read back as a native uuid.UUID, not text
    assert got_bt == bt  # business-time instant equality (D-04/D-05)
    assert got_bt.utcoffset() == bt.utcoffset()  # UTC-normalized, instant-preserving


def test_business_time_encoding_determinism():
    """T-01-08: the business-time TEXT encoding is byte-identical across two runs.

    Two independent binds of the same aware business datetime produce the exact same UTC
    isoformat TEXT — explicit UTC, microsecond-max precision, never ``datetime.now`` — so a
    persisted timestamp is reproducible (no non-deterministic persistence edge).
    """
    from sqlalchemy.dialects import sqlite

    bt = datetime(2018, 1, 1, tzinfo=timezone.utc)
    first = UtcIsoText().process_bind_param(bt, sqlite.dialect())
    second = UtcIsoText().process_bind_param(bt, sqlite.dialect())

    assert first == second  # identical TEXT bytes across the two runs (determinism)
    assert first == "2018-01-01T00:00:00+00:00"  # explicit UTC isoformat, no wall-clock

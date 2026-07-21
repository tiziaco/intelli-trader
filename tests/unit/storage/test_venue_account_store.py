"""Unit tests for the ``VenueAccountStore`` per-ACCOUNT durable store (MPORT-02 / D-05).

Exercises the ``VenueStore``-template clone over an in-memory SQLite ``SqlEngine``: the
composite ``(venue_name, account_id)`` natural-key round trip (D-01), the three-lifecycle
column split (``secret_ref`` / ``venue_uid`` / ``config_json`` — D-05), the D-06 paper row
with a NULL ``secret_ref``, and the REUSED ``_assert_no_secret_keys`` denylist guard firing
on a ``config_json`` secret before any write (D-02).

Also pins the one-letter hazard D-02 exists for: ``"secret"`` is denied by the exact-membership
denylist while ``"secret_ref"`` passes — which is precisely why the column is NOT named
``credentials``.

4-space indentation. NO ``__init__.py`` in this dir (package-collision hazard).
``filterwarnings=["error"]`` → every store wrapped in ``try/finally: store.dispose()``.
"""

from datetime import UTC, datetime

import pytest

from itrader.config.sql import SqlSettings
from itrader.core.exceptions import ValidationError
from itrader.storage import SqlEngine
from itrader.storage.venue_account_store import (
    VenueAccountStore,
    build_venue_accounts_table,
)
from tests.support.schema import provision_schema

_AT = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)


def _make_store() -> VenueAccountStore:
    """An in-memory durable double — the shared ``SqlEngine`` on ``:memory:`` SQLite.

    WR-03/D-14 — the store is schema-pure, so provision the schema explicitly after
    construction (before the first query) via the shared ``provision_schema`` helper.
    """
    store = VenueAccountStore(SqlEngine(SqlSettings.default()))
    provision_schema(store.backend)
    return store


def test_upsert_get_round_trip() -> None:
    """upsert(...) → get(venue, account) round-trips every column (D-05)."""
    store = _make_store()
    try:
        config = {"region": "eea", "sandbox": True}
        store.upsert(
            "okx",
            "main",
            secret_ref="vault://okx/main",
            venue_uid="uid-123",
            enabled=True,
            config=config,
            at=_AT,
        )
        row = store.get("okx", "main")
        assert row is not None
        assert row["venue_name"] == "okx"
        assert row["account_id"] == "main"
        assert row["secret_ref"] == "vault://okx/main"
        assert row["venue_uid"] == "uid-123"
        assert row["enabled"] is True
        assert row["config"] == config
        assert row["updated_at"] == _AT
    finally:
        store.dispose()


def test_upsert_replaces_row_for_same_pair() -> None:
    """A second upsert on the SAME (venue_name, account_id) replaces rather than duplicates."""
    store = _make_store()
    try:
        store.upsert(
            "okx",
            "main",
            secret_ref="vault://one",
            venue_uid=None,
            enabled=True,
            config={"region": "eea"},
            at=_AT,
        )
        store.upsert(
            "okx",
            "main",
            secret_ref="vault://two",
            venue_uid="uid-9",
            enabled=False,
            config={"region": "global"},
            at=_AT,
        )
        rows = store.read_all()
        assert len(rows) == 1
        assert rows[0]["secret_ref"] == "vault://two"
        assert rows[0]["venue_uid"] == "uid-9"
        assert rows[0]["enabled"] is False
        assert rows[0]["config"] == {"region": "global"}
    finally:
        store.dispose()


def test_same_account_id_on_two_venues_are_distinct_rows() -> None:
    """D-01 — ``account_id`` alone is not an identity: the PAIR is (two rows, not a clash)."""
    store = _make_store()
    try:
        store.upsert(
            "okx",
            "main",
            secret_ref="vault://okx",
            venue_uid=None,
            enabled=True,
            config={},
            at=_AT,
        )
        store.upsert(
            "paper",
            "main",
            secret_ref=None,
            venue_uid=None,
            enabled=True,
            config={},
            at=_AT,
        )
        pairs = {(r["venue_name"], r["account_id"]) for r in store.read_all()}
        assert pairs == {("okx", "main"), ("paper", "main")}
    finally:
        store.dispose()


def test_paper_row_with_null_secret_ref_round_trips() -> None:
    """D-06 — a paper account has no credential pointer; NULL ``secret_ref`` is legal."""
    store = _make_store()
    try:
        store.upsert(
            "paper",
            "acct_a",
            secret_ref=None,
            venue_uid=None,
            enabled=True,
            config={"sandbox": True},
            at=_AT,
        )
        row = store.get("paper", "acct_a")
        assert row is not None
        assert row["secret_ref"] is None
        assert row["venue_uid"] is None
        assert row["enabled"] is True
    finally:
        store.dispose()


def test_secret_key_in_config_rejected_and_writes_nothing() -> None:
    """D-02 — the reused denylist guard fires BEFORE the write, so nothing persists."""
    store = _make_store()
    try:
        with pytest.raises(ValidationError):
            store.upsert(
                "okx",
                "main",
                secret_ref="vault://okx",
                venue_uid=None,
                enabled=True,
                config={"secret": "leaked", "region": "eea"},
                at=_AT,
            )
        assert store.get("okx", "main") is None
        assert store.read_all() == []
    finally:
        store.dispose()


def test_nested_secret_key_in_config_rejected() -> None:
    """The guard is the RECURSIVE one from ``venue_store`` — a nested secret is caught."""
    store = _make_store()
    try:
        with pytest.raises(ValidationError):
            store.upsert(
                "okx",
                "main",
                secret_ref=None,
                venue_uid=None,
                enabled=True,
                config={"nested": {"deeper": {"passphrase": "leaked"}}},
                at=_AT,
            )
        assert store.get("okx", "main") is None
    finally:
        store.dispose()


def test_secret_ref_key_in_config_is_allowed() -> None:
    """``secret_ref`` is a POINTER name, not a secret name — it passes the denylist (D-02).

    This is the one-letter hazard the D-02 naming decision exists for: exact-membership
    membership denies ``"secret"`` but admits ``"secret_ref"``.
    """
    store = _make_store()
    try:
        store.upsert(
            "okx",
            "main",
            secret_ref="vault://okx/main",
            venue_uid=None,
            enabled=True,
            config={"secret_ref": "vault://x"},
            at=_AT,
        )
        row = store.get("okx", "main")
        assert row is not None
        assert row["config"] == {"secret_ref": "vault://x"}
    finally:
        store.dispose()


def test_get_unknown_pair_returns_none_and_read_all_empty() -> None:
    """An absent pair is None; an empty table reads back as an empty sequence, not an error."""
    store = _make_store()
    try:
        assert store.get("okx", "nope") is None
        assert store.read_all() == []
    finally:
        store.dispose()


def test_read_all_order_is_stable_across_calls() -> None:
    """MPORT-03 — ``read_all`` has a documented, explicit ORDER BY on the natural key."""
    store = _make_store()
    try:
        for venue, account in (("okx", "b"), ("okx", "a"), ("paper", "a")):
            store.upsert(
                venue,
                account,
                secret_ref=None,
                venue_uid=None,
                enabled=True,
                config={},
                at=_AT,
            )
        first = [(r["venue_name"], r["account_id"]) for r in store.read_all()]
        second = [(r["venue_name"], r["account_id"]) for r in store.read_all()]
        assert first == second
        assert first == [("okx", "a"), ("okx", "b"), ("paper", "a")]
    finally:
        store.dispose()


def test_record_venue_uid_updates_only_the_uid_column() -> None:
    """11-04 (D-04): the engine-written ``venue_uid`` write touches NOTHING else.

    ``venue_uid`` is written by the engine on first connect while ``secret_ref`` /
    ``config_json`` / ``enabled`` are operator-authored. Routing the engine's write
    through the operator ``upsert`` path would let a connect-time code path restate —
    and therefore clobber — the operator's own columns.
    """
    store = _make_store()
    try:
        config = {"region": "eea", "sandbox": True}
        store.upsert(
            "okx",
            "main",
            secret_ref="env:OKX_ACCT_MAIN",
            venue_uid=None,
            enabled=True,
            config=config,
            at=_AT,
        )
        later = datetime(2026, 2, 2, 9, 30, 0, tzinfo=UTC)

        store.record_venue_uid("okx", "main", "uid-777", later)

        row = store.get("okx", "main")
        assert row is not None
        assert row["venue_uid"] == "uid-777"
        assert row["updated_at"] == later
        # Untouched operator columns.
        assert row["secret_ref"] == "env:OKX_ACCT_MAIN"
        assert row["enabled"] is True
        assert row["config"] == config
    finally:
        store.dispose()


def test_record_venue_uid_on_a_missing_pair_is_a_silent_no_op() -> None:
    """No row for the pair -> zero rows matched; the guard never MINTS an account row.

    Account minting is plan 11-07's job. A guard that created rows would invent an
    operator record (with a NULL ``secret_ref``) from a connect-time code path.
    """
    store = _make_store()
    try:
        store.record_venue_uid("okx", "never-minted", "uid-777", _AT)
        assert store.get("okx", "never-minted") is None
        assert store.read_all() == []
    finally:
        store.dispose()


def test_build_venue_accounts_table_is_idempotent() -> None:
    """The registrar reuses an already-registered table; the PK is the composite pair (D-01)."""
    backend = SqlEngine(SqlSettings.default())
    try:
        first = build_venue_accounts_table(backend.metadata)
        second = build_venue_accounts_table(backend.metadata)
        assert first is second
        assert first.c.venue_name.primary_key is True
        assert first.c.account_id.primary_key is True
        assert {column.name for column in first.primary_key} == {
            "venue_name",
            "account_id",
        }
        assert first.c.secret_ref.nullable is True
        assert first.c.venue_uid.nullable is True
        assert "config_json" in first.c
        assert "credentials" not in first.c
    finally:
        backend.dispose()

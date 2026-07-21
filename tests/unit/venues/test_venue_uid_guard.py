"""Unit contract for the trust-on-first-use venue-UID guard (11-04, D-04, T-11-15).

D-04 exists because per-account credentials make the MISROUTE reachable: a mistyped
``secret_ref`` or a swapped vault entry means an ``account_id`` connects with a
DIFFERENT account's keys, orders route to the wrong REAL account, and reconciliation
then succeeds cleanly against it. The venue's self-reported account UID is the only
external evidence that the session belongs to the account the engine thinks it does.

The guard's contract, all asserted here:

  - FIRST connect for a pair RECORDS the UID (trust-on-first-use — no operator data
    entry, therefore no typo surface).
  - A matching later connect is silent.
  - A MISMATCH emits exactly ONE critical alert, does NOT overwrite the stored value
    (T-11-20 — overwriting would make the guard self-healing and therefore useless),
    and RETURNS NORMALLY (T-11-19 — observe-only; a venue reporting its UID
    differently across endpoints must not take a correctly-configured account
    offline).
  - A store outage is swallowed, never propagated.
  - The alert payload carries a FIXED LITERAL reason and no credential material.

The last test in this file is the one that matters most: it drives the guard through
the REAL ``assemble_venue`` production path, because a guard that only ever runs
under a hand-built unit fixture is dead code in production while every other
assertion here passes green.

This directory is package-less (NO ``__init__.py``, per MEMORY: two same-named
top-level test packages break full-suite collection).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from itrader.venues.venue_uid_guard import (
    VENUE_UID_MISMATCH_REASON,
    assert_venue_uid,
)

_AT = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)

# A sentinel a leak assertion can search for verbatim.
_SEEDED_SECRET = "seeded-key-8f21"


class _FakePlugin:
    """A venue plugin that reports a fixed UID and DECLARES a credential model.

    ``credential_model`` being non-``None`` is what marks this venue as one that
    SHOULD expose a UID — the guard uses it to decide whether a ``None`` UID is a
    clean no-op (paper) or a silent-degradation warning (a renamed venue field).
    """

    credential_model = object

    def __init__(self, uid: str | None) -> None:
        self._uid = uid
        self.calls: list[Any] = []

    def build_bundle(self, ctx: Any, spec: Any, connectors: Any) -> Any:  # pragma: no cover
        return None

    def fetch_venue_uid(self, connector: Any) -> str | None:
        self.calls.append(connector)
        return self._uid


class _PaperLikePlugin(_FakePlugin):
    """A venue with NO credentials and no venue-side UID (the paper shape)."""

    credential_model = None


class _FakeStore:
    """An in-memory ``VenueAccountStore`` double recording every write."""

    def __init__(self, venue_uid: str | None = None, exists: bool = True) -> None:
        self._row: dict[str, Any] | None = (
            {
                "venue_name": "okx",
                "account_id": "acct-a",
                "secret_ref": "env:OKX_ACCT_A",
                "venue_uid": venue_uid,
                "enabled": True,
                "config": {},
                "updated_at": _AT,
            }
            if exists
            else None
        )
        self.recorded: list[tuple[str, str, str, datetime]] = []

    def get(self, venue_name: str, account_id: str) -> dict[str, Any] | None:
        return self._row

    def record_venue_uid(
        self, venue_name: str, account_id: str, venue_uid: str, at: datetime
    ) -> None:
        self.recorded.append((venue_name, account_id, venue_uid, at))
        if self._row is not None:
            self._row["venue_uid"] = venue_uid


class _ExplodingStore:
    """A store whose every read/write fails — the storage-outage case."""

    def get(self, venue_name: str, account_id: str) -> dict[str, Any] | None:
        raise RuntimeError("database is unreachable")

    def record_venue_uid(
        self, venue_name: str, account_id: str, venue_uid: str, at: datetime
    ) -> None:
        raise RuntimeError("database is unreachable")


class _RecordingAlertSink:
    """An ``AlertSink`` double capturing every escalated ``ErrorEvent``."""

    def __init__(self) -> None:
        self.events: list[Any] = []

    def alert(self, event: Any) -> None:
        self.events.append(event)


def _guard(
    *,
    plugin: Any,
    store: Any,
    alert_sink: Any,
    account_id: str | None = "acct-a",
) -> None:
    """Drive the guard with the standard okx/acct-a pair."""
    assert_venue_uid(
        plugin=plugin,
        connector=object(),
        venue_name="okx",
        account_id=account_id,
        store=store,
        alert_sink=alert_sink,
        at=_AT,
    )


# --------------------------------------------------------------------------- #
# Trust on first use (D-04)
# --------------------------------------------------------------------------- #
def test_first_connect_records_the_uid_and_emits_zero_alerts() -> None:
    """A NULL stored ``venue_uid`` is the first connect: RECORD it, alert nothing.

    Trust-on-first-use is the half of D-04 that removes the operator from the loop:
    the first connect establishes the expected value, so there is no field to look up
    and mistype. The rejected alternative — an operator-declared expected UID — adds
    a typo surface whose failure mode is blocking a correctly-configured account.
    """
    store = _FakeStore(venue_uid=None)
    sink = _RecordingAlertSink()

    _guard(plugin=_FakePlugin("uid-111"), store=store, alert_sink=sink)

    assert store.recorded == [("okx", "acct-a", "uid-111", _AT)]
    assert sink.events == []


def test_matching_later_connect_writes_nothing_and_alerts_nothing() -> None:
    """The steady state: a UID equal to the stored one is completely silent."""
    store = _FakeStore(venue_uid="uid-111")
    sink = _RecordingAlertSink()

    _guard(plugin=_FakePlugin("uid-111"), store=store, alert_sink=sink)

    assert store.recorded == []
    assert sink.events == []


# --------------------------------------------------------------------------- #
# Mismatch: alert, do NOT overwrite, do NOT halt (T-11-15/T-11-19/T-11-20)
# --------------------------------------------------------------------------- #
def test_mismatch_emits_exactly_one_critical_alert_and_returns_normally() -> None:
    """THE spoofing detector (T-11-15): one CRITICAL alert, no raise, no halt.

    Returning normally is the explicit D-04 decision. A venue that reports its UID
    differently across endpoints would otherwise take a correctly-configured account
    offline (T-11-19), which is a worse failure than the false negative.
    """
    from itrader.core.enums import ErrorSeverity

    store = _FakeStore(venue_uid="uid-111")
    sink = _RecordingAlertSink()

    # No pytest.raises wrapper: the call returning at all IS the assertion.
    _guard(plugin=_FakePlugin("uid-999"), store=store, alert_sink=sink)

    assert len(sink.events) == 1
    event = sink.events[0]
    assert event.severity is ErrorSeverity.CRITICAL
    # A FIXED LITERAL reason, never a stringified exception or an interpolated payload
    # (the reconciliation-coordinator discipline).
    assert event.error_type == VENUE_UID_MISMATCH_REASON
    # The operator needs the pair and both UIDs to act on the alert.
    assert event.details is not None
    assert event.details["venue_name"] == "okx"
    assert event.details["account_id"] == "acct-a"
    assert event.details["recorded_venue_uid"] == "uid-111"
    assert event.details["observed_venue_uid"] == "uid-999"


def test_mismatch_does_not_overwrite_the_recorded_uid() -> None:
    """T-11-20: the RECORDED value is the trusted one and survives the mismatch.

    Overwriting on mismatch would make the guard self-healing — it would alert once
    and then happily accept the impostor forever.
    """
    store = _FakeStore(venue_uid="uid-111")
    sink = _RecordingAlertSink()

    _guard(plugin=_FakePlugin("uid-999"), store=store, alert_sink=sink)

    assert store.recorded == []
    assert store.get("okx", "acct-a")["venue_uid"] == "uid-111"


def test_mismatch_alert_carries_no_credential_material(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """T-11-17: the alert payload leaks no secret and no ``secret_ref`` VALUE."""
    monkeypatch.setenv("OKX_ACCT_A_API_KEY", _SEEDED_SECRET)

    store = _FakeStore(venue_uid="uid-111")
    sink = _RecordingAlertSink()

    _guard(plugin=_FakePlugin("uid-999"), store=store, alert_sink=sink)

    rendered = repr(sink.events[0]) + repr(sink.events[0].details)
    assert _SEEDED_SECRET not in rendered
    assert "env:OKX_ACCT_A" not in rendered


# --------------------------------------------------------------------------- #
# Fail-safe paths (T-11-19)
# --------------------------------------------------------------------------- #
def test_a_plugin_returning_no_uid_is_a_clean_no_op_for_a_credential_less_venue() -> None:
    """Paper (``credential_model is None``) yields ``None``: nothing recorded, nothing alerted."""
    store = _FakeStore(venue_uid=None)
    sink = _RecordingAlertSink()

    _guard(plugin=_PaperLikePlugin(None), store=store, alert_sink=sink)

    assert store.recorded == []
    assert sink.events == []


def test_a_credentialed_venue_yielding_no_uid_warns_rather_than_failing_silently(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A venue that SHOULD expose a UID but yields ``None`` must not degrade silently.

    Otherwise a renamed venue field or a revoked read scope permanently disables the
    only spoofing detector with zero signal — the guard would keep "passing" forever.
    """
    store = _FakeStore(venue_uid=None)
    sink = _RecordingAlertSink()

    with caplog.at_level("WARNING"):
        _guard(plugin=_FakePlugin(None), store=store, alert_sink=sink)

    assert store.recorded == []
    assert sink.events == []
    assert any("venue-uid" in record.getMessage().lower() for record in caplog.records)


def test_a_store_outage_is_swallowed_and_never_breaks_a_healthy_connect() -> None:
    """A storage failure logs and returns — the guard cannot abort a good connect."""
    sink = _RecordingAlertSink()

    # The call completing without raising IS the assertion.
    _guard(plugin=_FakePlugin("uid-111"), store=_ExplodingStore(), alert_sink=sink)

    assert sink.events == []


def test_a_missing_account_row_is_a_no_op() -> None:
    """No row for the pair yet (11-07 mints them): record nothing, alert nothing."""
    store = _FakeStore(exists=False)
    sink = _RecordingAlertSink()

    _guard(plugin=_FakePlugin("uid-111"), store=store, alert_sink=sink)

    assert store.recorded == []
    assert sink.events == []


def test_a_none_account_id_is_normalized_to_the_default_account() -> None:
    """``VenueSpec.account_id`` is Optional[str]; the guard must NOT write a NULL PK half.

    Both plugins apply ``spec.account_id or "default"`` INSIDE ``build_bundle`` — a
    normalization the lifecycle never sees. Handing the raw ``None`` to the store
    would write a ``None`` PK half whose row then silently never matches on any later
    connect, permanently disabling the guard for that account.
    """
    store = _FakeStore(venue_uid=None)
    sink = _RecordingAlertSink()

    _guard(plugin=_FakePlugin("uid-111"), store=store, alert_sink=sink, account_id=None)

    assert store.recorded == [("okx", "default", "uid-111", _AT)]


# --------------------------------------------------------------------------- #
# THE test that proves the guard is not dead code (audit correction #1)
# --------------------------------------------------------------------------- #
def test_guard_runs_on_the_real_assemble_venue_production_path() -> None:
    """``assemble_venue`` -> ``VenueLifecycle.start()`` -> the guard, with a REAL store.

    Every other test in this file drives ``assert_venue_uid`` DIRECTLY with fakes, so
    all of them would still pass if the guard were never called in production. The
    only production construction site for ``VenueLifecycle`` is ``assemble_venue``;
    this test goes through it end to end against a real SQLite-backed
    ``VenueAccountStore``, so a regression that unwires the guard reddens here.
    """
    from itrader.config.sql import SqlSettings
    from itrader.storage import SqlEngine
    from itrader.storage.venue_account_store import VenueAccountStore
    from itrader.trading_system.venue_spec import VenueSpec
    from itrader.venues.assemble import assemble_venue
    from itrader.venues.bundle import VenueBundle
    from itrader.venues.registry import DataProviderRegistry, ExecutionVenueRegistry
    from tests.support.schema import provision_schema

    class _Connector:
        def connect(self) -> None:
            return None

        def disconnect(self) -> None:
            return None

    class _ExecPlugin(_FakePlugin):
        def build_bundle(self, ctx: Any, spec: Any, connectors: Any) -> VenueBundle:
            return VenueBundle(
                exchange=object(),
                account_factory=lambda *a, **k: object(),
                connector=_Connector(),
            )

    class _DataPlugin:
        def build_provider(self, ctx: Any, spec: Any, connectors: Any) -> Any:
            return object()

    store = VenueAccountStore(SqlEngine(SqlSettings.default()))
    try:
        provision_schema(store.backend)
        store.upsert(
            "okx",
            "acct-a",
            secret_ref="env:OKX_ACCT_A",
            venue_uid=None,
            enabled=True,
            config={},
            at=_AT,
        )

        exec_registry = ExecutionVenueRegistry()
        data_registry = DataProviderRegistry()
        exec_registry.register("okx", _ExecPlugin("uid-from-venue"))
        data_registry.register("okx", _DataPlugin())
        sink = _RecordingAlertSink()

        _bundle, lifecycle = assemble_venue(
            object(),
            VenueSpec(execution_venue="okx", data_provider="okx", account_id="acct-a"),
            connectors=None,
            exec_registry=exec_registry,
            data_registry=data_registry,
            account_store=store,
            alert_sink=sink,
        )
        lifecycle.start()

        # FIRST connect through the REAL path recorded the venue's UID.
        assert store.get("okx", "acct-a")["venue_uid"] == "uid-from-venue"
        assert sink.events == []

        # A SECOND start reporting a DIFFERENT uid escalates through the same path.
        exec_registry_2 = ExecutionVenueRegistry()
        exec_registry_2.register("okx", _ExecPlugin("uid-IMPOSTOR"))
        _bundle2, lifecycle2 = assemble_venue(
            object(),
            VenueSpec(execution_venue="okx", data_provider="okx", account_id="acct-a"),
            connectors=None,
            exec_registry=exec_registry_2,
            data_registry=data_registry,
            account_store=store,
            alert_sink=sink,
        )
        lifecycle2.start()

        assert len(sink.events) == 1
        assert sink.events[0].error_type == VENUE_UID_MISMATCH_REASON
        # T-11-20: still the trusted first-seen value.
        assert store.get("okx", "acct-a")["venue_uid"] == "uid-from-venue"
    finally:
        store.dispose()


def test_build_live_system_threads_the_store_and_sink_into_assemble_venue() -> None:
    """The production composition root actually SUPPLIES the guard's dependencies.

    ``assemble_venue`` accepts ``account_store`` / ``alert_sink`` as OPTIONAL kwargs so
    existing call sites keep working — which means the guard silently no-ops if the
    ONE production caller forgets them. Asserted by source inspection because building
    the live system requires credentials and a database.
    """
    import inspect

    from itrader.trading_system import live_trading_system as _lts

    source = inspect.getsource(_lts.build_live_system)

    assert "account_store=" in source, (
        "build_live_system must pass account_store= to assemble_venue, or the D-04 "
        "UID guard never runs in production (it would be dead code behind a green suite)"
    )
    assert "alert_sink=alert_sink" in source, (
        "build_live_system must pass alert_sink= to assemble_venue, or a UID mismatch "
        "has no egress channel"
    )

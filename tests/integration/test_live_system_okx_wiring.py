"""LiveTradingSystem OKX-wiring gate (CR-02) — construction is credential/IO-free for non-OKX.

Locks in the CR-02 fix: constructing a ``LiveTradingSystem`` for a non-OKX venue (the
default ``'binance'``) must

- NOT require the ``OKX_API_*`` credential triple (``OkxSettings()`` is only constructed
  on the ``exchange == 'okx'`` arm),
- NOT perform any OKX network I/O in the constructor (``connect()`` is deferred to
  ``start()``), and
- leave the OKX arms unwired (``_okx_connector is None``, no ``'okx'`` execution arm).

Before the fix, ``__init__`` unconditionally built ``OkxSettings()`` (raising
``pydantic.ValidationError`` with no creds) and called ``connect()`` (a blocking
``load_markets()`` REST round-trip) regardless of the requested venue — so constructing
the live system for ANY venue hard-required OKX credentials + reachability. No test
constructed a ``LiveTradingSystem``, so the defect was uncaught.

This suite does NOT assert on ``sys.modules`` (the sibling connector/execution suites in
the same session may already have imported ``ccxt.pro``); the credential-free construction
+ unwired-arm assertions are the load-bearing gate.
"""

from unittest.mock import MagicMock, patch

import pytest

from itrader.core.enums import ExchangeConnectionStatus, HaltReason, SystemStatus
from itrader.events_handler.events import ConnectorFatalEvent, StreamStateEvent
from itrader.execution_handler.exchanges.okx import OkxExchange
from itrader.execution_handler.result_objects import ConnectionResult
from itrader import config as _live_config
from itrader.trading_system.live.build import (
    build_live_system,
    emit_connector_fatal,
    emit_stream_down,
    emit_stream_up,
)
from tests.support.live_okx import (
    bring_okx_online,
    stub_data_session,
    stub_okx_session,
    the_feed_provider,
)


def _strip_okx_env(monkeypatch) -> None:
    """Remove the OKX credential triple so a stray requirement surfaces as a failure."""
    for var in ("OKX_API_KEY", "OKX_API_SECRET", "OKX_API_PASSPHRASE"):
        monkeypatch.delenv(var, raising=False)


def _set_okx_env(monkeypatch) -> None:
    """Set a dummy OKX credential triple so the OKX arm's ``OkxSettings()`` constructs.

    The connector constructor is I/O-free (``connect()`` is deferred to ``start()``),
    so a stubbed credential triple is enough to build ``build_live_system(execution_venue="okx")``
    fully offline — no socket, no ``load_markets`` round-trip.
    """
    monkeypatch.setenv("OKX_API_KEY", "test-key")
    monkeypatch.setenv("OKX_API_SECRET", "test-secret")
    monkeypatch.setenv("OKX_API_PASSPHRASE", "test-pass")


def test_construct_non_okx_venue_needs_no_okx_credentials(monkeypatch) -> None:
    """A non-OKX LiveTradingSystem constructs with the OKX creds absent (CR-02)."""
    _strip_okx_env(monkeypatch)

    # Must NOT raise pydantic.ValidationError for missing OKX_API_* — the OKX arm is gated.
    system = build_live_system(
        _live_config, execution_venue="binance", data_venue="okx")

    # "Unwired" is now an EMPTY online-account enumeration. An unregistered venue — and
    # any boot without a durable venue_accounts row — brings nothing online at all.
    assert system._online_account_records() == []
    # The OKX execution arm is not registered for a non-OKX venue.
    # D-27: the registry is pair-keyed, so assert over the VENUE HALF. Checking
    # only ("okx", DEFAULT_ACCOUNT_ID) would silently weaken this test — an OKX
    # arm registered under a NAMED account would satisfy it.
    assert not any(venue == "okx"
                   for venue, _account_id in system.execution_handler.exchanges)


def test_construct_does_not_connect_in_constructor(monkeypatch) -> None:
    """Constructing performs no OKX network connect — connect() is deferred to start() (CR-02).

    A non-OKX system has no connector at all, so stop() (which tears the connector down
    unconditionally, CR-01) is a clean no-op that does not raise.
    """
    _strip_okx_env(monkeypatch)

    system = build_live_system(
        _live_config, execution_venue="binance", data_venue="okx")

    # No session was built, so there is nothing connected and nothing to leak.
    assert system._online_account_records() == []
    # stop() before any start() must not raise even though nothing is wired/running.
    assert system.stop() is True


def test_okx_live_feed_capacity_derives_to_strategy_warmup(monkeypatch) -> None:
    """After session init the LIVE feed's cache_capacity() derives to the max strategy warmup (D-13).

    The D-13 consumer registration in ``_initialize_live_session`` makes
    ``cache_capacity()`` equal the deepest registered strategy warmup — for the golden
    SMA_MACD that is 100, not the newest-bar floor (1). Drives the session init directly
    (offline; no OKX connect, no stream).
    """
    _set_okx_env(monkeypatch)

    system = build_live_system(_live_config, execution_venue="okx")
    # Pre-registration: no raw-bar consumer yet -> the newest-bar floor.
    assert system.feed.cache_capacity() == 1

    # Run only the session-init wiring (membership derive + D-13 registration + bind);
    # this performs no network I/O (the OKX connect lives in start(), not here).
    system._initialize_live_session()

    expected = max(
        (s.warmup for s in system.strategies_handler.strategies), default=1)
    assert system.feed.cache_capacity() == expected


def _provision_empty_order_tables(engine) -> None:
    """Create the order working-set tables on the shared test database, and EMPTY them.

    ``start()``'s venue reconcile reads the rehydrated order working set for every account
    the manager reports ONLINE, so the ``orders`` tables must EXIST even when they hold
    nothing. The ``provisioned_okx`` spine registers the venue/portfolio/system stores
    only, so the order registrar is added here — the same register-then-``create_all``
    sequence.

    Purging is not hygiene, it is the premise: the Postgres container is SESSION-scoped, so
    a restart-rehydration sibling's persisted order rows are still there, and a resting
    bracket leg in the working set makes the reconcile halt on an unconfident re-link
    against this test's empty venue. These tests boot with nothing outstanding.
    """
    from itrader.order_handler.storage.models import build_order_tables
    from tests.support.schema import provision_schema

    tables = build_order_tables(engine.metadata)
    provision_schema(engine)
    with engine.engine.begin() as connection:
        # Child first: order_state_changes carries an FK onto orders.
        connection.execute(tables["order_state_changes"].delete())
        connection.execute(tables["orders"].delete())


def test_the_boot_brings_the_provisioned_okx_account_online_and_routable(
    provisioned_okx,
) -> None:
    """One durable row -> a connected adapter, registered under the EXACT pair.

    The whole bring-up in one assertion chain: the session opened, the adapter spawned its
    streams (``connect()`` is their SOLE spawn site — without it no real FillEvent ever
    streams back and every order mirror stays PENDING forever while looking healthy), the
    identity guard ran, the halt seam is armed, and only THEN is the pair routable.
    """
    _provision_empty_order_tables(provisioned_okx)
    system = build_live_system(_live_config, execution_venue="okx")
    try:
        record = bring_okx_online(system)

        assert record.connector is not None
        record.connector.connect.assert_called_once()
        assert record.adapter.is_connected() is True
        assert record.adapter._halt_signal is not None
        assert record.connector._halt_signal is not None
        assert system.execution_handler.exchanges[("okx", record.spec.account_id)] \
            is record.adapter
    finally:
        system.stop()


def test_the_one_feed_is_wired_to_a_data_adapter_on_its_own_session(
    provisioned_okx,
) -> None:
    """The feed's provider is the data adapter, wired to its ingest seam and the bus.

    It is built by the composition root over the venue's PUBLIC session, so it exists
    before any account is brought online and is not derived from one. A dead-attribute
    mis-wire (``feed.provider = ...``) would leave ``feed._provider`` None; a dropped
    ``set_global_queue`` would make ``spawn_warmup`` raise a typed ``StateError`` far from
    the cause.
    """
    system = build_live_system(_live_config, execution_venue="okx")
    try:
        provider = the_feed_provider(system)
        assert provider is not None
        assert system.feed._provider is provider
        assert provider._bar_sink == system.feed.update
        assert provider._global_queue is system.global_queue

        # Bringing the account online changes order routing only — the data arm is
        # untouched, and its session is not the account's.
        record = bring_okx_online(system)
        assert the_feed_provider(system) is provider
        assert system._data_connector is not record.connector
    finally:
        system.stop()


def test_a_failed_adapter_connect_quarantines_the_account_not_the_boot(
    provisioned_okx, caplog,
) -> None:
    """A row whose bring-up fails is SKIPPED with a CRITICAL alert; the boot still runs.

    ``connect()`` RETURNS a ``ConnectionResult`` and never raises, so a bring-up that
    ignored it would register an adapter whose streams never spawned — every order mirror
    PENDING forever behind a healthy-looking account. Instead the failure aborts THAT
    account's bring-up, and because registration is its last step the pair is left
    unroutable rather than half-online. One unreachable venue account must not take an
    entire deployment offline, and the alert is what stops the skip from being silent.
    """
    _provision_empty_order_tables(provisioned_okx)
    system = build_live_system(_live_config, execution_venue="okx")
    stub_okx_session(system)
    # start() opens the data adapter's own session too; stub it so the run stays offline.
    stub_data_session(system)
    system.feed.warmup = MagicMock(name="feed.warmup")

    failed = ConnectionResult(
        success=False,
        status=ExchangeConnectionStatus.ERROR,
        exchange_name="okx",
        error_message="stream spawn failed")
    with patch.object(OkxExchange, "connect", return_value=failed), \
            caplog.at_level("CRITICAL"):
        try:
            started = system.start()

            assert started is True
            assert system.get_status()["status"] == SystemStatus.RUNNING.value
            # Unroutable: the failed bring-up registered nothing under the OKX venue.
            assert system._online_account_records() == []
            assert not any(
                venue == "okx"
                for venue, _account in system.execution_handler.exchanges)
            # Loud, not silent — an operator is told which account is not trading.
            escalated = [
                record.getMessage() for record in caplog.records
                if "venue-account-quarantined" in record.getMessage()]
            assert escalated, "the quarantine was silent — no CRITICAL alert escalated"
            assert "'account_id': 'default'" in escalated[0]
        finally:
            system.stop()


# --- MPORT-05: the single-account link is GONE; the coordinator takes no scalars ----


def test_the_coordinator_the_facade_builds_carries_no_venue_scalars(monkeypatch) -> None:
    """The facade builds a coordinator with no account / connector / exchange scalar.

    A per-account scalar on this collaborator would be a single-portfolio-live assumption:
    ONE account, ONE connector, ONE exchange handed to every active portfolio's reconcile,
    so portfolio B would be judged against account A's venue truth and its rehydrated
    orders would repopulate A's correlation map. The absences are asserted by NAME so a
    re-added scalar reddens here rather than surfacing as a cross-account wrong answer.

    Two portfolios sharing one account is refused earlier and more widely by
    ``assert_distinct_accounts``, before any account is minted.
    """
    _set_okx_env(monkeypatch)
    system = build_live_system(_live_config, execution_venue="okx")

    coordinator = system._build_reconciliation_coordinator()

    assert not hasattr(coordinator, "_venue_account")
    assert not hasattr(coordinator, "_connector")
    assert not hasattr(coordinator, "_exchange")
    assert not hasattr(coordinator, "_link_venue_account_to_portfolios")
    # What it carries instead is the facade's own online-record ENUMERATION, read at call
    # time. A per-account enumeration is what makes "compare portfolio A against account
    # B" unexpressible: each record supplies its own adapter and connector. Reading it
    # LIVE also means an account brought online after this coordinator was built is still
    # covered — a build-time snapshot of the records would silently skip it.
    # (== not is: each bound-method access is a fresh object, and bound methods compare
    # equal by function + instance.)
    assert coordinator._records == system._online_account_records


def test_a_facade_with_no_portfolios_reconciles_nothing(monkeypatch) -> None:
    """Zero active portfolios: run_startup_reconcile rehydrates and returns cleanly.

    The MPORT-05 empty edge through the facade's OWN coordinator — no portfolios means
    no accounts means nothing to snapshot, stream, reconcile or halt on.
    """
    _set_okx_env(monkeypatch)
    system = build_live_system(_live_config, execution_venue="okx")
    assert system.portfolio_handler.get_active_portfolios() == []

    # Must not raise, must not touch the venue.
    system._build_reconciliation_coordinator().run_startup_reconcile()


# --- SAFE-03/§11c: connector stream/fatal arrive as CONTROL events on the engine ---
# --- thread; the flag side-channel is deleted. -------------------------------------


def test_connector_control_events_route_to_safety_and_recovery(monkeypatch) -> None:
    """Connector callbacks emit CONTROL events routed on the engine thread (SAFE-03/§11c).

    The three connector-loop emitters (``emit_stream_down`` / ``emit_stream_up`` /
    ``emit_connector_fatal``) put ``StreamStateEvent(down/up)`` / ``ConnectorFatalEvent``
    on the bus instead of flipping flags; the engine-thread STREAM_STATE / CONNECTOR_FATAL
    routes actuate ``SafetyController.pause_submission`` (down), ``StreamRecoveryHandler.
    on_reconnect`` (up), and ``SafetyController.halt`` (fatal). The ``_pending_*`` flag
    side-channel is GONE — the connector handoff is CONTROL events only.
    """
    _set_okx_env(monkeypatch)
    system = build_live_system(_live_config, execution_venue="okx")
    # Install the live routes (STREAM_STATE / CONNECTOR_FATAL onto the event handler),
    # offline — no OKX connect (that lives in start()).
    system._initialize_live_session()

    # The flag side-channel is deleted (Pitfall 3) — no _pending_* fields exist.
    assert not hasattr(system, "_pending_stream_resume")
    assert not hasattr(system, "_pending_connector_halt")
    assert not hasattr(system, "_pending_connector_halt_reason")

    # Spy the collaborator route targets (the registrar holds these SAME objects).
    system._safety.pause_submission = MagicMock(name="pause_submission")
    system._stream_recovery.on_reconnect = MagicMock(name="on_reconnect")
    system._safety.halt = MagicMock(name="halt")

    # Drain any wiring-time events, then fire the three connector callbacks: each PUTS a
    # CONTROL event (no flag flip, no blocking I/O).
    while not system.global_queue.empty():
        system.global_queue.get_nowait()
    emit_stream_down(system.global_queue, "fills")
    emit_stream_up(system.global_queue, "fills")
    emit_connector_fatal(system.global_queue, "secret-bearing venue error")

    # The queued events are the fixed-shape CONTROL facts — V7 scrub: the fatal reason is
    # the FIXED literal, never the connector payload passed to the callback.
    queued = []
    while not system.global_queue.empty():
        queued.append(system.global_queue.get_nowait())
    down = next(e for e in queued if isinstance(e, StreamStateEvent) and not e.up)
    up = next(e for e in queued if isinstance(e, StreamStateEvent) and e.up)
    fatal = next(e for e in queued if isinstance(e, ConnectorFatalEvent))
    assert down.stream_name == "fills" and up.stream_name == "fills"
    assert fatal.reason == HaltReason.CONNECTOR_FATAL.value
    assert "secret" not in fatal.reason

    # Re-enqueue + drain through the engine-thread routing -> the collaborator targets.
    for ev in queued:
        system.global_queue.put(ev)
    system.event_handler.process_events()

    system._safety.pause_submission.assert_called_once_with("paused-on-disconnect")
    system._stream_recovery.on_reconnect.assert_called_once_with()
    system._safety.halt.assert_called_once_with(HaltReason.CONNECTOR_FATAL.value)

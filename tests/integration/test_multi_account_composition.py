"""Multi-account wiring through the REAL composition root (MPORT-01, 11.2-07 store-derived).

Plan 11-06 keyed ``ExecutionHandler.exchanges`` on the ``(venue, account_id)`` pair and
made ``on_order`` resolve the account from the order's portfolio; 11-07 gave the live boot
the ability to register more than one account on one venue. **11.2-07 (ACCT-01/D-20) makes
that account set STORE-DERIVED**: the boot no longer computes accounts from the spec — it
reads the enabled ``venue_accounts`` rows through ``VenueAccountManager`` and brings each
online. So this file provisions durable rows and asserts the engine ``build_live_system``
returns, with NOTHING in the minting/assembly path monkeypatched.

**Why OKX and not paper.** ``connector is None`` is the streaming-venue discriminator, and
a paper bundle carries no connector — so a paper-based test would never reach the
registration write. ``OkxConnector`` construction is I/O-free (``connect()`` is deferred to
``start()``), so a stubbed credential triple drives the whole composition root with no
socket.

**Why the Postgres spine.** Under DB-as-sole-truth there is no account without a durable
row, so a store is mandatory — the account SET can no longer be conjured from the spec
offline. The account-DERIVATION logic itself (ordering, venue-scoping, the exact-pair key,
per-account ``secret_ref``) is unit-tested on ``VenueAccountManager`` without a boot
(``tests/unit/venues/test_accounts.py`` / ``test_account_provisioning_loop.py`` /
``test_feed_binder.py``); this file's unique job is proving production actually GOES through
that manager.

**Why the boot is driven explicitly.** Bring-up CONNECTS, so it is a step of ``start()``
rather than of construction. These tests stub each account's session offline and then run
``_bootstrap_session`` — the exact call ``start()`` makes — so the production bring-up runs
with no socket.

Indentation: 4-space. The ``integration`` marker is folder-derived; ``tests/integration/``
has no ``__init__.py``. Postgres-gated (skips without Docker).
"""

from datetime import UTC, datetime

import pytest

from itrader.config.sql import SqlDriver, SqlSettings
from itrader.storage import SqlEngine
from itrader.storage.portfolio_definition_store import PortfolioDefinitionStore
from itrader.storage.venue_account_store import VenueAccountStore
from itrader.trading_system.live_trading_system import build_live_system
from itrader.trading_system.system_spec import SystemSpec
from tests.support.live_okx import stub_every_okx_session
from tests.support.schema import provision_schema

_AT = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
_VENUE = "okx"


@pytest.fixture
def okx_env(monkeypatch):
    """A stubbed OKX credential triple — enough to construct connectors offline."""
    monkeypatch.setenv("OKX_API_KEY", "test-key")
    monkeypatch.setenv("OKX_API_SECRET", "test-secret")
    monkeypatch.setenv("OKX_API_PASSPHRASE", "test-pass")


@pytest.fixture
def live_db(pg_database_env):
    """A handle on the SAME database ``build_live_system`` builds its engine on.

    The Postgres arm resolves ``ITRADER_DATABASE_URL`` verbatim, so this points at the
    shared testcontainers instance ``pg_database_env`` exports. Purges before and after —
    the container is session-scoped, so a leaked row would bleed across tests.
    """
    engine = SqlEngine(SqlSettings(driver=SqlDriver.POSTGRESQL_PSYCOPG2))
    # Register BOTH tables on the shared MetaData before provisioning the schema — the
    # ``portfolios`` FK references ``venue_accounts``, and the purge touches both.
    PortfolioDefinitionStore(engine)
    VenueAccountStore(engine)
    provision_schema(engine)
    _purge(engine)
    try:
        yield engine
    finally:
        _purge(engine)
        engine.dispose()


def _purge(engine: SqlEngine) -> None:
    metadata = engine.metadata
    with engine.engine.begin() as connection:
        connection.execute(metadata.tables["portfolios"].delete())
        connection.execute(metadata.tables["venue_accounts"].delete())


def _provision(engine: SqlEngine, *account_ids: str, secret_ref=None) -> None:
    """Write enabled ``venue_accounts`` rows the store-derived boot will bring online."""
    store = VenueAccountStore(engine)
    for account_id in account_ids:
        store.upsert(
            _VENUE, account_id, secret_ref=secret_ref, venue_uid=None,
            enabled=True, config={}, at=_AT)


def _spec() -> SystemSpec:
    """A minimal live spec — its portfolios no longer drive the account set (ACCT-01)."""
    return SystemSpec(
        start="2024-01-01", end="2024-01-02", timeframe="1d", ticker="BTCUSDT",
        starting_cash=10_000, data={}, strategies=[],
        portfolios=[], execution_venue=_VENUE)


def _booted(system):
    """Run the production boot over stubbed sessions; return the system."""
    stub_every_okx_session(system)
    system._bootstrap_session()
    return system


def _okx_entries(system):
    """The ``(venue, account_id) -> exchange`` entries for the OKX venue only."""
    return {
        key: exchange
        for key, exchange in system.execution_handler.exchanges.items()
        if key[0] == _VENUE
    }


# --------------------------------------------------------------------------- #
# The store-derived account set through build_live_system (MPORT-01 / D-20)
# --------------------------------------------------------------------------- #
def test_two_provisioned_rows_produce_two_exchanges_over_two_connectors(
    live_db, okx_env,
) -> None:
    """THE gate: two enabled rows -> two distinct exchanges over two distinct connectors.

    Everything below is read off the engine the real ``build_live_system`` returned, and
    the accounts came from the STORE, not the spec.
    """
    _provision(live_db, "acct-a", "acct-b")
    system = _booted(build_live_system(_spec()))
    try:
        entries = _okx_entries(system)
        assert set(entries) == {(_VENUE, "acct-a"), (_VENUE, "acct-b")}

        exchange_a = entries[(_VENUE, "acct-a")]
        exchange_b = entries[(_VENUE, "acct-b")]
        # Two DISTINCT exchange objects over two DISTINCT connectors — the isolation
        # premise (D-12). A shared connector means account B's orders traverse account A's
        # authenticated session, a silent real-money wrong answer.
        assert exchange_a is not exchange_b
        assert exchange_a._connector is not exchange_b._connector
    finally:
        system.stop()


def test_a_single_provisioned_row_registers_exactly_one_exchange(live_db, okx_env) -> None:
    """The N=1 path — one enabled row, one exchange, under its own pair key."""
    _provision(live_db, "acct-solo")
    system = _booted(build_live_system(_spec()))
    try:
        assert set(_okx_entries(system)) == {(_VENUE, "acct-solo")}
    finally:
        system.stop()


def test_zero_provisioned_rows_boot_up_empty(live_db, okx_env) -> None:
    """D-09 — a fresh deployment with no venue accounts comes up RUNNING and empty."""
    system = _booted(build_live_system(_spec()))
    try:
        assert _okx_entries(system) == {}
        assert system._venue_manager.online_records() == []
    finally:
        system.stop()


def test_the_manager_holds_one_online_record_per_account(live_db, okx_env) -> None:
    """ONE online record PER ACCOUNT, and no privileged first entry.

    There is no primary-account concept: the feed is bound to a CONNECTION, not handed to
    a privileged account, so the records carry no ordering meaning beyond bring-up order.
    The deleted scalar aliases stay gone.
    """
    _provision(live_db, "acct-a", "acct-b")
    system = _booted(build_live_system(_spec()))
    try:
        records = {r.spec.account_id: r for r in system._venue_manager.online_records()}
        assert set(records) == {"acct-a", "acct-b"}
        entries = _okx_entries(system)
        for account_id in ("acct-a", "acct-b"):
            record = records[account_id]
            assert record.adapter is entries[(_VENUE, account_id)]
            assert record.connector is not None

        # The deleted scalar aliases + the deleted primary accessor stay gone, not renamed.
        for gone in ("_venue_bundle", "_okx_connector", "_okx_exchange",
                     "_venue_account", "_okx_data_provider", "_primary_lifecycle"):
            assert not hasattr(system, gone), f"{gone} was resurrected"
    finally:
        system.stop()


# --------------------------------------------------------------------------- #
# 11.1-08 / D-08 — EXACTLY ONE build per boot (bundles), and D-36 ONE provider
# --------------------------------------------------------------------------- #
def _count_class_calls(monkeypatch, cls, method_name):
    """Wrap ``cls.method_name`` with a call counter, delegating to the original."""
    calls = []
    original = getattr(cls, method_name)

    def _counting(self, *args, **kwargs):
        calls.append(args)
        return original(self, *args, **kwargs)

    monkeypatch.setattr(cls, method_name, _counting)
    return calls


def test_a_two_account_boot_opens_exactly_two_sessions(live_db, okx_env):
    """Two accounts -> exactly TWO sessions and TWO adapters, one memoized pair each.

    A count of two with the SAME object reaching both arms would still be the defect, so
    the identity of what the order path resolves is asserted alongside the count. The pool
    is the single memo: a second memo on any other key is how two registries end up
    disagreeing about one real account.
    """
    _provision(live_db, "acct-a", "acct-b")

    system = _booted(build_live_system(_spec()))
    try:
        entries = _okx_entries(system)
        records = {r.spec.account_id: r for r in system._venue_manager.online_records()}
        assert set(records) == {"acct-a", "acct-b"}
        for account_id in ("acct-a", "acct-b"):
            assert records[account_id].adapter is entries[(_VENUE, account_id)]
        # ONE session per account, and the adapter holds exactly the one memoized for it.
        assert set(system._connector_pool._sessions) == {
            (_VENUE, "acct-a"), (_VENUE, "acct-b")}
        for account_id in ("acct-a", "acct-b"):
            assert (records[account_id].connector
                    is system._connector_pool._sessions[(_VENUE, account_id)])
    finally:
        system.stop()


def test_a_two_account_boot_binds_exactly_one_data_provider(monkeypatch, live_db, okx_env):
    """D-14/D-36: two accounts -> exactly ONE ``build_provider`` call, bound to the feed.

    ONE feed means ONE data provider. D-36 builds it in the FeedConnectionBinder for the
    first streaming connection (not a "primary" account) and binds it to the feed; the
    second account's provider is never constructed (WR-07 — a discarded credential-bearing
    provider with no owner is exactly what is avoided).
    """
    from itrader.venues.okx_plugin import OkxDataPlugin

    build_calls = _count_class_calls(monkeypatch, OkxDataPlugin, "build_provider")
    _provision(live_db, "acct-a", "acct-b")

    system = _booted(build_live_system(_spec()))
    try:
        assert len(build_calls) == 1, (
            f"ONE feed means ONE data provider per boot (D-14/D-36); got {len(build_calls)}")
        # The one provider reached the one feed (read the feed's private provider slot).
        assert system.feed._provider is not None
    finally:
        system.stop()

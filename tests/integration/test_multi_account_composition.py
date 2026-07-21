"""The MPORT-01/MPORT-06 gate: two accounts assemble through the REAL composition root.

**The gap this closes.** Plan 11-06 keyed ``ExecutionHandler.exchanges`` on the
``(venue, account_id)`` pair and made ``on_order`` resolve the account from the
order's portfolio. Its own gate had to construct ``ExecutionHandler`` DIRECTLY and
hand-write two entries, and said so in its docstring: the live composition root
built ONE venue spec, called ``assemble_venue`` ONCE and performed a SINGLE
registration write, so it *structurally could not* register two accounts on one
venue. Plan 11-07 is where that capability lands, so this is the first test in the
phase that can assert multi-account wiring through ``build_live_system`` itself.

**Why that distinction is the whole point of this file.** A test that patches
``new_account`` — or one that builds the registry by hand — proves the library
function works while saying nothing about whether production ever calls it. Before
this plan ``grep -rn 'new_account' itrader/`` returned nothing at all. So NOTHING
in the minting path is monkeypatched here: the real ``build_live_system`` runs, the
real plugins build the real bundles, and the assertions read the resulting engine.

**Why OKX and not paper.** ``connector is None`` is the streaming-venue
discriminator, and a paper bundle carries no connector — so a paper-based test
would never reach the registration write and would pass while proving nothing
(the same trap 11-06 documented). OKX is used OFFLINE: ``OkxConnector``
construction is I/O-free (``connect()`` is deferred to ``start()``), so a stubbed
credential triple is enough to drive the whole composition root with no socket.

Indentation: 4-space. The ``integration`` marker is folder-derived, so this file
declares no marker of its own, and ``tests/integration/`` has no ``__init__.py``.
"""

from datetime import UTC, datetime

import pytest

import uuid
from decimal import Decimal
from types import SimpleNamespace

from itrader.config.sql import SqlDriver, SqlSettings
from itrader.core.exceptions import ValidationError
from itrader.core.ids import PortfolioId
from itrader.storage import SqlEngine
from itrader.storage.portfolio_definition_store import PortfolioDefinitionStore
from itrader.storage.venue_account_store import VenueAccountStore
from itrader.trading_system.live_trading_system import (
    _account_ids_for_spec,
    _attach_venue_accounts,
    _build_account_specs,
    build_live_system,
)
from itrader.trading_system.system_spec import PortfolioSpec, SystemSpec
from tests.support.schema import provision_schema

_AT = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
_VENUE = "okx"


@pytest.fixture
def okx_env(monkeypatch):
    """A stubbed OKX credential triple — enough to construct connectors offline."""
    monkeypatch.setenv("OKX_API_KEY", "test-key")
    monkeypatch.setenv("OKX_API_SECRET", "test-secret")
    monkeypatch.setenv("OKX_API_PASSPHRASE", "test-pass")


def _spec(account_ids, primary=None):
    """A ``SystemSpec`` whose PORTFOLIOS name the accounts (MPORT-05)."""
    return SystemSpec(
        start="2024-01-01",
        end="2024-01-02",
        timeframe="1d",
        ticker="BTCUSDT",
        starting_cash=10_000,
        data={},
        strategies=[],
        portfolios=[
            PortfolioSpec(name=f"pf-{account_id}", cash=10_000, account_id=account_id)
            for account_id in account_ids
        ],
        execution_venue=_VENUE,
        account_id=primary,
    )


def _okx_entries(system):
    """The ``(venue, account_id) -> exchange`` entries for the OKX venue only.

    Filtered by VENUE rather than asserting on ``len(exchanges)``: the registry also
    holds the compose-built ``('simulated', 'default')`` and ``('csv', 'default')``
    entries, so a bare length assertion would be counting unrelated rows.
    """
    return {
        key: exchange
        for key, exchange in system.execution_handler.exchanges.items()
        if key[0] == _VENUE
    }


# --------------------------------------------------------------------------- #
# The account set (MPORT-01)
# --------------------------------------------------------------------------- #
def test_account_set_is_derived_from_the_portfolios() -> None:
    """Two portfolios naming two accounts yield two accounts, in spec order."""
    assert _account_ids_for_spec(_spec(["acct-a", "acct-b"])) == ["acct-a", "acct-b"]


def test_two_portfolios_on_one_account_share_one_bundle() -> None:
    """One account is assembled ONCE however many portfolios name it (D-12).

    One connector per ``(venue, account_id)`` pair — not one per portfolio. A
    per-portfolio connector would open N authenticated sessions against the same
    venue account and multiply that account's rate-limit budget by N.
    """
    assert _account_ids_for_spec(_spec(["acct-a", "acct-a"])) == ["acct-a"]


def test_spec_level_account_is_primary_and_never_duplicated() -> None:
    """The spec-level account leads (deterministic primary) and is de-duplicated."""
    spec = _spec(["acct-b", "acct-a"], primary="acct-a")
    assert _account_ids_for_spec(spec) == ["acct-a", "acct-b"]


def test_a_spec_naming_no_account_is_the_unchanged_single_account_path() -> None:
    """N=1 is the SAME code path, not a separate branch.

    A ``VenueSpec`` (the ``for_exchange`` shape) carries no ``portfolios`` at all,
    which is the pre-11-07 call shape and must keep resolving to exactly one
    unnamed account.
    """
    from itrader.trading_system.venue_spec import build_venue_spec

    assert _account_ids_for_spec(build_venue_spec(_VENUE)) == [None]
    assert _account_ids_for_spec(_spec([])) == [None]


# --------------------------------------------------------------------------- #
# The composition root (MPORT-01) — NO monkeypatching of the minting path
# --------------------------------------------------------------------------- #
def test_two_accounts_produce_two_exchanges_over_two_connectors(okx_env) -> None:
    """THE gate: two accounts -> two distinct exchanges over two distinct connectors.

    Everything below is read off the engine the real ``build_live_system`` returned.
    """
    system = build_live_system(_spec(["acct-a", "acct-b"]))
    try:
        entries = _okx_entries(system)

        # Two entries under two DISTINCT pair keys.
        assert len(entries) == 2
        assert set(entries) == {(_VENUE, "acct-a"), (_VENUE, "acct-b")}

        exchange_a = entries[(_VENUE, "acct-a")]
        exchange_b = entries[(_VENUE, "acct-b")]

        # Two DISTINCT exchange objects. One shared object cannot subscribe to two
        # accounts' private fill streams at all.
        assert exchange_a is not exchange_b

        # Over two DISTINCT connectors — the isolation premise (D-12). A shared
        # connector means account B's orders traverse account A's authenticated
        # session, which is a real-money wrong answer and a silent one.
        assert exchange_a._connector is not exchange_b._connector
    finally:
        system.stop()


def test_the_facade_holds_one_lifecycle_per_account_primary_first(okx_env) -> None:
    """The facade holds ONE lifecycle PER ACCOUNT, keyed by account id (D-07/11-09).

    11-09 replaced the facade's six scalar venue aliases — ``_venue_lifecycle`` /
    ``_venue_bundle`` / ``_okx_connector`` / ``_okx_exchange`` / ``_venue_account`` /
    ``_okx_data_provider``, five of which were pre-derived ``lifecycle.<something>``
    reads — with this single map. Six scalars cannot describe two accounts; one
    lifecycle per account can, and every former alias is now a read THROUGH the
    lifecycle.

    Insertion order is load-bearing, not incidental: the PRIMARY is the first entry,
    and exactly one data provider is bound to the one feed, so a primary that moved
    between boots would re-point the feed at a different account's stream.
    """
    system = build_live_system(_spec(["acct-a", "acct-b"], primary="acct-a"))
    try:
        assert set(system._venue_lifecycles) == {"acct-a", "acct-b"}
        # PRIMARY FIRST — the spec-level account leads.
        assert list(system._venue_lifecycles)[0] == "acct-a"
        assert system._primary_lifecycle is system._venue_lifecycles["acct-a"]

        # Every former alias is reachable through the account's own lifecycle, and each
        # account's is its OWN — which is precisely what a scalar could not express.
        entries = _okx_entries(system)
        for account_id in ("acct-a", "acct-b"):
            lifecycle = system._venue_lifecycles[account_id]
            assert lifecycle.bundle.exchange is entries[(_VENUE, account_id)]
            assert lifecycle.bundle.connector is not None

        # The five deleted scalar aliases are GONE, not renamed. Asserted explicitly so
        # a future "convenience" read-through property cannot quietly restore them.
        for alias in ("_venue_bundle", "_okx_connector", "_okx_exchange",
                      "_venue_account", "_okx_data_provider"):
            assert not hasattr(system, alias), f"{alias} was resurrected"
    finally:
        system.stop()


def test_a_single_account_spec_registers_exactly_one_exchange(okx_env) -> None:
    """The N=1 path is unchanged — one account, one exchange, under its own key."""
    system = build_live_system(_spec(["acct-solo"]))
    try:
        assert set(_okx_entries(system)) == {(_VENUE, "acct-solo")}
    finally:
        system.stop()


# --------------------------------------------------------------------------- #
# MPORT-06 — per-account credentials stop being dormant
# --------------------------------------------------------------------------- #
def _store_with(rows):
    """A real ``VenueAccountStore`` on in-memory SQLite holding the given rows."""
    store = VenueAccountStore(SqlEngine(SqlSettings.default()))
    provision_schema(store.backend)
    for account_id, secret_ref in rows:
        store.upsert(
            _VENUE, account_id, secret_ref=secret_ref, venue_uid=None,
            enabled=True, config={}, at=_AT)
    return store


def test_each_account_spec_carries_its_own_credential_pointer() -> None:
    """Two rows with DIFFERENT secret_refs produce two specs with those pointers.

    This is the read that was previously performed ONCE, for a single spec-level
    account. Performing it per account is what gives the 11-04 resolver two
    different pointers to resolve instead of one.

    The store is constructed by the test rather than by the SQL arm of
    ``build_live_system`` (which requires Postgres); ``_build_account_specs`` itself
    is production code, called by ``build_live_system``, and is not stubbed.
    """
    store = _store_with([("acct-a", "env:OKX_A"), ("acct-b", "env:OKX_B")])
    try:
        specs = _build_account_specs(
            _spec(["acct-a", "acct-b"]), store, _VENUE)

        assert [s.account_id for s in specs] == ["acct-a", "acct-b"]
        assert [s.secret_ref for s in specs] == ["env:OKX_A", "env:OKX_B"]
    finally:
        store.dispose()


def test_two_accounts_build_connectors_from_different_credential_material(
    monkeypatch,
) -> None:
    """THE MPORT-06 gate: different pointers -> different RESOLVED credentials.

    Asserted on the resolved credential VALUES, not on the row count. Row count
    proves only that data exists; the defect MPORT-06 closes is two accounts sharing
    the one ambient ``OKX_API_*`` triple while the system believes they are separate
    — which is invisible unless the credentials the connectors actually carry are
    compared.

    The resolver short-circuit (``secret_ref is None -> OkxConnector(OkxSettings())``)
    is what kept this dormant. Both branches are covered: the two named accounts must
    NOT take it, and the assertion below would hold trivially if they did (both
    connectors would carry the ambient key), which is why the ambient value is set to
    something distinct from both.
    """
    from itrader.config.credential_resolver import EnvCredentialResolver
    from itrader.connectors.provider import ConnectorProvider
    from itrader.venues.okx_plugin import OkxConnectorPlugin

    monkeypatch.setenv("OKX_API_KEY", "ambient-key")
    monkeypatch.setenv("OKX_API_SECRET", "ambient-secret")
    monkeypatch.setenv("OKX_API_PASSPHRASE", "ambient-pass")
    for prefix, key in (("OKX_A", "key-a"), ("OKX_B", "key-b")):
        monkeypatch.setenv(f"{prefix}_API_KEY", key)
        monkeypatch.setenv(f"{prefix}_API_SECRET", f"secret-{key}")
        monkeypatch.setenv(f"{prefix}_API_PASSPHRASE", f"pass-{key}")

    store = _store_with([("acct-a", "env:OKX_A"), ("acct-b", "env:OKX_B")])
    try:
        specs = _build_account_specs(_spec(["acct-a", "acct-b"]), store, _VENUE)
        connectors = ConnectorProvider(
            {_VENUE: OkxConnectorPlugin(resolver=EnvCredentialResolver())})

        connector_a = connectors.get(_VENUE, "acct-a", specs[0])
        connector_b = connectors.get(_VENUE, "acct-b", specs[1])

        key_a = connector_a._settings.api_key.get_secret_value()
        key_b = connector_b._settings.api_key.get_secret_value()

        assert key_a == "key-a"
        assert key_b == "key-b"
        assert key_a != key_b
        # Neither took the short-circuit back to the ambient single-account triple.
        assert "ambient-key" not in (key_a, key_b)
    finally:
        store.dispose()


def test_an_absent_account_row_is_minted_so_the_uid_guard_has_a_home() -> None:
    """A missing row is minted with a NULL secret_ref (MPORT-01).

    ``record_venue_uid`` is a targeted UPDATE and a silent no-op when no row
    matches, so without minting, the D-04 trust-on-first-use identity guard has
    nowhere to record and stays permanently inert for that account.
    """
    store = _store_with([])
    try:
        _build_account_specs(_spec(["acct-new"]), store, _VENUE)

        row = store.get(_VENUE, "acct-new")
        assert row is not None
        assert row["secret_ref"] is None
    finally:
        store.dispose()


def test_minting_never_clobbers_an_operators_configured_pointer() -> None:
    """An EXISTING row is left alone — minting is gated on absence.

    ``VenueAccountStore.upsert`` is a delete-then-insert over the composite key, so
    an unconditional mint would silently revert a configured per-account credential
    pointer to the ambient path on every boot. That failure is invisible: the system
    keeps running, authenticated as the wrong account.
    """
    store = _store_with([("acct-a", "env:OKX_A")])
    try:
        _build_account_specs(_spec(["acct-a"]), store, _VENUE)

        row = store.get(_VENUE, "acct-a")
        assert row is not None
        assert row["secret_ref"] == "env:OKX_A"
    finally:
        store.dispose()


# --------------------------------------------------------------------------- #
# MPORT-05 — THE ATTACH: each portfolio holds the account its own account_id names
#
# These are the gates that make plan 11-07b's deletion safe, and they are the reason
# Task 0 exists at all. Dropping the coordinator's scalar `venue_account` without an
# attach path would leave every portfolio on the SimulatedCashAccount leaf that
# Portfolio._initialize_components builds — `is_venue_truth` False for all of them, so
# `run_startup_reconcile` would skip snapshot(), start_streaming(), VenueReconciler AND
# the D-04 baseline HALT gate for every portfolio, silently, behind a green suite.
#
# Fake portfolios with a test-assigned `.account` cannot gate this: they would prove the
# assertion, not the wiring. Everything below drives the REAL build_live_system with the
# minting and attach paths unstubbed.
# --------------------------------------------------------------------------- #


@pytest.fixture
def live_db(pg_database_env):
    """A handle on the SAME database ``build_live_system`` builds its own engine on.

    Purges before and after: the container is session-scoped, and because ``portfolios``
    carries a composite FK onto ``venue_accounts`` a row leaked by a sibling test makes
    the NEXT test's account upsert fail with a foreign-key violation rather than
    anything that points at the real cause.
    """
    engine = SqlEngine(SqlSettings(driver=SqlDriver.POSTGRESQL_PSYCOPG2))
    PortfolioDefinitionStore(engine)
    VenueAccountStore(engine)
    provision_schema(engine)
    _purge(engine)
    try:
        yield engine
    finally:
        _purge(engine)
        engine.dispose()


def _purge(engine) -> None:
    """Drop every portfolio + account row so the session-scoped container stays clean."""
    metadata = engine.metadata
    with engine.engine.begin() as connection:
        connection.execute(metadata.tables["portfolios"].delete())
        connection.execute(metadata.tables["venue_accounts"].delete())


def _seed_definition(engine, *, name: str, account_id: str) -> PortfolioId:
    """Persist ONE definition row plus the ``venue_accounts`` parent its FK needs."""
    store = PortfolioDefinitionStore(engine)
    accounts = VenueAccountStore(engine)
    portfolio_id = PortfolioId(uuid.uuid4())
    accounts.upsert(
        _VENUE, account_id, secret_ref=None, venue_uid=None, enabled=True,
        config={}, at=_AT)
    store.upsert(
        portfolio_id, name=name, venue_name=_VENUE, account_id=account_id,
        initial_cash=Decimal("10000.00"), enabled=True, config=None, at=_AT)
    return portfolio_id


def test_two_portfolios_hold_two_distinct_venue_accounts(okx_env, live_db) -> None:
    """THE MPORT-05 attach gate: each portfolio holds ITS OWN account, by IDENTITY.

    Asserted on object identity rather than on equality or on account_id alone. Two
    portfolios sharing ONE account object is the conflation the whole phase exists to
    prevent, and it is invisible to an equality check: both would report the "right"
    account_id while reading and reserving against a single real venue balance.
    """
    _seed_definition(live_db, name="pf-a", account_id="acct-a")
    _seed_definition(live_db, name="pf-b", account_id="acct-b")

    system = build_live_system(_spec([]))
    try:
        portfolios = {
            p.name: p for p in system.portfolio_handler._portfolios.values()}
        assert set(portfolios) == {"pf-a", "pf-b"}
        pf_a, pf_b = portfolios["pf-a"], portfolios["pf-b"]

        # Two DISTINCT account objects — not one shared instance.
        assert pf_a.account is not pf_b.account
        # Each holds the account ITS OWN account_id names.
        assert pf_a.account.account_id == "acct-a"
        assert pf_b.account.account_id == "acct-b"
        # And each is venue-cached truth, NOT the simulated leaf Portfolio builds at
        # construction. This is the direct guard against the silent-regression mode:
        # a False here means the entire venue reconcile no-ops for that portfolio.
        assert pf_a.account.is_venue_truth is True
        assert pf_b.account.is_venue_truth is True
        # Two accounts, two authenticated sessions (the D-12 isolation premise).
        assert pf_a.account.connector is not pf_b.account.connector
    finally:
        system.stop()


def test_a_rehydrated_portfolios_account_is_assembled_and_attached(
    okx_env, live_db,
) -> None:
    """A portfolio restored from a definition row — with NO spec entry — gets its account.

    11-08 flagged this deliberately rather than building a second path: the account set
    was derived from the SPEC alone, so a rehydrated portfolio had no account assembled
    for it at all. Deriving from the UNION is what closes it, and the spec here is
    EMPTY on purpose — a spec portfolio naming the persisted account would be a genuine
    cross-source collision that 11-08's invariant refuses.

    Reverting ``_account_ids_for_spec`` to spec-only turns this RED: the rehydrated
    portfolio names an account with no assembled lifecycle, so the attach refuses loudly.
    """
    _seed_definition(live_db, name="pf-restored", account_id="acct-restored")

    system = build_live_system(_spec([]))
    try:
        assert "acct-restored" in system._venue_lifecycles
        portfolio = next(iter(system.portfolio_handler._portfolios.values()))
        assert portfolio.name == "pf-restored"
        assert portfolio.account.account_id == "acct-restored"
        assert portfolio.account.is_venue_truth is True
    finally:
        system.stop()


def test_a_portfolio_naming_an_unassembled_account_is_refused() -> None:
    """A named account with no assembled lifecycle FAILS LOUD — no fallback, no leaf.

    Both silent outcomes are worse than the raise, in different ways. Falling back to
    the PRIMARY wires this portfolio to another portfolio's real venue balance. Leaving
    it on its simulated leaf makes ``is_venue_truth`` False, which silently disables
    snapshot, streaming, the VenueReconciler and the D-04 baseline HALT gate for it —
    the engine then trades that portfolio believing it has reconciled.

    Driven against the attach function directly: through the real composition root the
    union derivation ALWAYS assembles an account for every portfolio, so the refusal
    branch is unreachable there by construction. That is the desired production posture;
    the guard still has to hold if a future caller supplies a partial map.
    """
    primary = SimpleNamespace(
        bundle=SimpleNamespace(
            connector=object(),
            account_factory=lambda portfolio: SimpleNamespace(
                account_id="acct-primary")))
    orphan = SimpleNamespace(name="pf-orphan", account_id="acct-missing", account=None)
    handler = SimpleNamespace(_portfolios={1: orphan})

    with pytest.raises(ValidationError) as exc_info:
        _attach_venue_accounts(handler, {"acct-primary": primary})

    assert "acct-missing" in str(exc_info.value)
    # The refusal happened BEFORE any assignment — the portfolio was never quietly
    # handed the primary's account on the way to raising.
    assert orphan.account is None


def test_a_portfolio_naming_no_account_keeps_its_construction_time_leaf() -> None:
    """A portfolio that names NO venue account is left alone — that is the paper shape.

    Re-minting here would be actively harmful, not merely redundant: the compute arm's
    ``account_factory`` builds a fresh leaf whose ``initial_cash`` defaults to zero, so
    an "attach everything" loop would silently reset the portfolio's opening balance.
    """
    original = object()
    portfolio = SimpleNamespace(name="pf-paper", account_id=None, account=original)
    handler = SimpleNamespace(_portfolios={1: portfolio})

    assert _attach_venue_accounts(handler, {}) == {}
    assert portfolio.account is original


def test_the_account_set_unions_spec_portfolios_with_rehydrated_ones() -> None:
    """The union, in the documented order: spec-level, then spec portfolios, then rehydrated.

    Order is the primary-selection contract. A set would be correct on membership and
    wrong on which account the one feed provider belongs to.
    """
    rehydrated = [
        SimpleNamespace(account_id="acct-r1"),
        SimpleNamespace(account_id="acct-a"),   # already named by the spec — deduped
        SimpleNamespace(account_id="acct-r2"),
    ]
    assert _account_ids_for_spec(
        _spec(["acct-a"], primary="acct-p"), rehydrated,
    ) == ["acct-p", "acct-a", "acct-r1", "acct-r2"]


def test_every_accounts_exchange_is_wired_to_the_halt_signal(okx_env) -> None:
    """A NON-primary account's exchange gets the same halt wiring as the primary.

    Registering a second account's exchange without wiring its halt signal would
    leave it accepting orders after a connector-fatal halt latched the primary. A
    partially-halted engine is worse than a single-account one, because the
    surviving arm looks healthy — nothing reports that half the venue is still live.
    """
    system = build_live_system(_spec(["acct-a", "acct-b"], primary="acct-a"))
    try:
        entries = _okx_entries(system)

        for key, exchange in entries.items():
            assert exchange._halt_signal is not None, f"{key} has no halt signal"
            assert exchange._connector._halt_signal is not None, (
                f"{key}'s connector has no halt signal")
    finally:
        system.stop()

"""MPORT-02 at BOTH layers — no two portfolios may share one venue account (D-14/D-15).

Two portfolios pointing at one real venue account conflate their buying power and positions
into a single balance the venue cannot split back out (T-11-38). D-14 defends that at two
layers on purpose, and this file gates both:

* the DATABASE ``UniqueConstraint('venue_name', 'account_id')`` on ``portfolios`` (plan
  11-01), which also binds out-of-band writers that never execute application code;
* the APPLICATION check at composition, whose real job is the half the database cannot see
  — a duplicate inside a composition-supplied spec, which has not been written yet.

**The union is the contract.** A check over only the persisted rows would prove nothing the
DB constraint has not already proven; a check over only the spec would miss a new portfolio
colliding with an existing durable row. Both directions are gated below.

**D-15 is asserted as a NEGATIVE, not just as a raise.** ``pytest.raises`` alone would pass
against an implementation that minted every account first and only then noticed the
collision. The gates therefore assert that NO account was minted and NO exchange registered
on the failure path — the state the engine is left in matters more than the exception type.

4-space indentation; NO ``__init__.py`` in this dir. Folder-derived ``integration`` marker.
"""

import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError

from itrader.config.sql import SqlDriver, SqlSettings
from itrader.core.exceptions import DuplicateVenueAccountError
from itrader.core.ids import PortfolioId
from itrader.portfolio_handler.rehydrate.distinct_account_invariant import (
    assert_distinct_accounts,
)
from itrader.storage import SqlEngine
from itrader.storage.portfolio_definition_store import PortfolioDefinitionStore
from itrader.storage.venue_account_store import VenueAccountStore
from itrader.trading_system.live_trading_system import build_live_system
from itrader.trading_system.system_spec import PortfolioSpec, SystemSpec
from tests.support.live_okx import stub_every_okx_session
from tests.support.schema import provision_schema

_AT = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
_VENUE = "okx"


def _persisted(name: str, venue_name: str, account_id: str) -> dict:
    """A definition row in the store's public read shape."""
    return {
        "portfolio_id": uuid.uuid4(),
        "name": name,
        "venue_name": venue_name,
        "account_id": account_id,
        "initial_cash": Decimal("10000.00"),
        "enabled": True,
        "config": None,
        "updated_at": _AT,
    }


# --------------------------------------------------------------------------- #
# Layer 1 — the application check, over the PERSISTED rows (11.2-07, ACCT-01/D-20)
#
# The account set is now STORE-DERIVED, so the spec-derived arm (``spec_portfolios`` +
# ``venue_name``) is GONE and the check reads ONLY the persisted definition rows. The
# spec-side collision cases it used to catch cannot occur any more — the live boot no
# longer derives account identity from the spec. What remains is the persisted x persisted
# belt-and-braces over the database's own UNIQUE constraint.
# --------------------------------------------------------------------------- #
def test_zero_portfolios_passes_vacuously() -> None:
    """The MPORT-03 empty edge — a clean boot with nothing persisted must not raise."""
    assert_distinct_accounts(persisted=[])


def test_one_portfolio_passes() -> None:
    """A single portfolio cannot collide with anything."""
    assert_distinct_accounts(persisted=[_persisted("solo", _VENUE, "acct-a")])


def test_the_same_account_id_on_two_different_venues_passes() -> None:
    """Identity is the PAIR — the same NAME on two venues is two different accounts.

    Flagging this would be a false refusal on a legitimate deployment: account ids are
    venue-scoped strings, and "main" on OKX has nothing to do with "main" on Binance.
    """
    assert_distinct_accounts(
        persisted=[
            _persisted("pf-a", "okx", "main"),
            _persisted("pf-b", "binance", "main"),
        ])


def test_the_same_venue_with_different_account_ids_passes() -> None:
    """Same-venue portfolios SEPARATE when their accounts differ (MPORT-03 adjacency)."""
    assert_distinct_accounts(
        persisted=[
            _persisted("pf-a", _VENUE, "acct-a"),
            _persisted("pf-b", _VENUE, "acct-b"),
        ])


def test_two_persisted_rows_sharing_a_pair_raise() -> None:
    """Belt and braces over the DB constraint (rows could predate it, or arrive by hand).

    The error must name both portfolios, the colliding pair, the consequence and the
    remediation: an operator reading it should not have to open the source to act.
    """
    with pytest.raises(DuplicateVenueAccountError) as caught:
        assert_distinct_accounts(
            persisted=[
                _persisted("pf-a", _VENUE, "shared"),
                _persisted("pf-b", _VENUE, "shared"),
            ])

    error = caught.value
    assert error.venue_name == _VENUE
    assert error.account_id == "shared"
    message = str(error)
    assert "pf-a" in message and "pf-b" in message
    assert "conflate" in message           # the consequence
    assert "own account_id" in message     # the remediation


def test_persisted_rows_naming_no_account_never_collide() -> None:
    """An unset ``account_id`` is "no venue account", not a shared ``None`` key.

    Persisted rows carry a NOT NULL ``account_id`` in production, but the ``_claim``
    None-guard remains — grouping several unnamed rows under one ``None`` key would refuse
    to start on a configuration the guard is meant to allow.
    """
    a = _persisted("pf-a", _VENUE, "x"); a["account_id"] = None
    b = _persisted("pf-b", _VENUE, "y"); b["account_id"] = None
    assert_distinct_accounts(persisted=[a, b])


# --------------------------------------------------------------------------- #
# Layer 2 — the database constraint (binds writers that never run our code)
# --------------------------------------------------------------------------- #
def test_the_database_rejects_an_out_of_band_duplicate_pair() -> None:
    """An INSERT that bypasses the application check still cannot create the collision.

    This is why the overlap is not redundant: a future integrations page writing rows
    directly would never execute ``assert_distinct_accounts``.
    """
    engine = SqlEngine(SqlSettings.default())
    store = PortfolioDefinitionStore(engine)
    provision_schema(engine)
    accounts = engine.metadata.tables["venue_accounts"]
    with engine.engine.begin() as connection:
        connection.execute(accounts.insert(), [{
            "venue_name": _VENUE, "account_id": "shared", "secret_ref": None,
            "venue_uid": None, "enabled": True, "config_json": {}, "updated_at": _AT,
        }])

    try:
        store.upsert(
            uuid.uuid4(), name="pf-a", venue_name=_VENUE, account_id="shared",
            initial_cash=Decimal("10000"), enabled=True, config=None, at=_AT)

        with pytest.raises(IntegrityError):
            store.upsert(
                uuid.uuid4(), name="pf-b", venue_name=_VENUE, account_id="shared",
                initial_cash=Decimal("10000"), enabled=True, config=None, at=_AT)
    finally:
        store.dispose()


# --------------------------------------------------------------------------- #
# The BOOT gates — everything below drives the REAL build_live_system
#
# The application check above is a pure function, and a pure function can be
# exhaustively tested while production never calls it. In production BOTH of its
# inputs were empty before this plan (no writer, no spec portfolios reaching a
# portfolio), which is precisely how a well-tested orphan happens. These gates
# therefore assert against the engine the real composition root returned, with
# nothing in the rehydrate or minting path monkeypatched.
#
# Plan 11-07b (Wave 6) deletes the single-portfolio RuntimeError guard in
# reconciliation_coordinator and is GATED on this invariant being live — these are
# the tests that make that deletion safe.
# --------------------------------------------------------------------------- #


@pytest.fixture
def okx_env(monkeypatch):
    """A stubbed OKX credential triple — enough to construct connectors offline.

    OKX rather than paper because ``connector is None`` is the streaming-venue
    discriminator: a paper bundle carries no connector and would never reach the
    registration write, so a paper-based gate would pass while proving nothing.
    ``OkxConnector`` construction is I/O-free (``connect()`` is deferred to
    ``start()``), so this drives the whole composition root with no socket.
    """
    monkeypatch.setenv("OKX_API_KEY", "test-key")
    monkeypatch.setenv("OKX_API_SECRET", "test-secret")
    monkeypatch.setenv("OKX_API_PASSPHRASE", "test-pass")


def _spec(account_ids, primary=None):
    """A ``SystemSpec`` whose PORTFOLIOS name the accounts (MPORT-05)."""
    return SystemSpec(
        start="2024-01-01", end="2024-01-02", timeframe="1d", ticker="BTCUSDT",
        starting_cash=10_000, data={}, strategies=[],
        portfolios=[
            PortfolioSpec(name=f"pf-{index}", cash=10_000, account_id=account_id)
            for index, account_id in enumerate(account_ids)
        ],
        execution_venue=_VENUE,
        account_id=primary,
    )


def _booted(system):
    """Run the production restart sequence over stubbed sessions; return the system.

    Bring-up CONNECTS, so it is a step of ``start()`` rather than of construction. Each
    enabled account's session is pre-built and stubbed first, so the REAL bring-up runs
    with no socket.
    """
    stub_every_okx_session(system)
    system._bootstrap_session()
    return system


@pytest.fixture
def live_db(pg_database_env):
    """A handle on the SAME database ``build_live_system`` will build its own engine on.

    The Postgres arm resolves ``ITRADER_DATABASE_URL`` verbatim, so this points at the
    shared testcontainers instance ``pg_database_env`` exports.

    Purges BOTH before and after. The container is session-scoped, so a row leaked by a
    sibling test would bleed in here — and because ``portfolios`` carries a composite FK
    onto ``venue_accounts``, a stale portfolio row makes the NEXT test's account upsert
    (a delete-then-insert) fail with a foreign-key violation rather than anything that
    points at the real cause.
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


def _seed_definition(engine: SqlEngine, *, name: str, account_id: str) -> PortfolioId:
    """Persist ONE definition row together with the ``venue_accounts`` parent its FK needs."""
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


def _purge(engine: SqlEngine) -> None:
    """Drop every portfolio + account row so the session-scoped container stays clean."""
    metadata = engine.metadata
    with engine.engine.begin() as connection:
        connection.execute(metadata.tables["portfolios"].delete())
        connection.execute(metadata.tables["venue_accounts"].delete())


def _okx_entries(system):
    """The ``(venue, account_id) -> exchange`` entries for the OKX venue only."""
    return {
        key: value
        for key, value in system.execution_handler.exchanges.items()
        if key[0] == _VENUE
    }


# --- spec-side collision gates DELETED (11.2-07, ACCT-01/D-20) --------------- #
# The former gates (a)/(b)/(e) drove ``build_live_system(_spec(["shared", "shared"]))``
# and asserted the boot REFUSED a spec-side duplicate. The account set is now
# STORE-DERIVED: the live boot no longer computes account identity from the spec, so a
# spec-side collision cannot exist to refuse. The persisted x persisted duplicate is
# prevented by the database UNIQUE constraint (``test_the_database_rejects_an_out_of_band_
# duplicate_pair`` above) and belt-and-braced by the Layer-1 pure-function check
# (``test_two_persisted_rows_sharing_a_pair_raise``).


# --- (c) same venue, DIFFERENT account ids -> BOOTS ------------------------ #
def test_two_persisted_portfolios_on_one_venue_both_rehydrate(live_db, okx_env) -> None:
    """(c) MPORT-03 adjacency, persisted side — same-venue portfolios SEPARATE.

    The false-refusal guard: an invariant that keyed on ``account_id`` alone, or one
    that treated "same venue" as the collision, would break a legitimate deployment —
    and it would break it at BOOT, taking the whole engine down.

    The spec deliberately names NO account here. A spec portfolio naming either of
    these accounts would be a genuine cross-source collision (gate (b)), so pairing the
    persisted rows with matching spec entries would be asserting the opposite thing.
    """
    first = _seed_definition(live_db, name="pf-a", account_id="acct-a")
    second = _seed_definition(live_db, name="pf-b", account_id="acct-b")

    system = _booted(build_live_system(_spec([])))
    try:
        assert set(system.portfolio_handler._portfolios) == {first, second}
        accounts = {
            system.portfolio_handler.get_portfolio(pid).account_id
            for pid in (first, second)
        }
        assert accounts == {"acct-a", "acct-b"}
    finally:
        system.stop(timeout=5.0)


# The spec-side two-account assembly gate (``build_live_system(_spec(["acct-a",
# "acct-b"]))`` -> two exchanges) is DELETED: the account set is store-derived now, so the
# multi-account boot is gated store-first in ``test_multi_account_composition.py`` (two
# provisioned rows -> two exchanges).


# --- (d) same account id, DIFFERENT venues -> BOOTS ------------------------ #
def test_the_same_account_id_on_two_venues_boots(live_db, okx_env) -> None:
    """(d) Identity is the PAIR — a persisted row on another venue does not collide.

    The persisted portfolio lives on ``binance``; the OKX boot brings up its own ``main``
    account (11.2-07: store-derived, so it is provisioned as a durable row rather than
    named in the spec). Both name the account id "main", and that is two different real
    accounts on two venues.
    """
    other = PortfolioId(uuid.uuid4())
    # The OKX 'main' account is provisioned so the store-derived boot assembles it.
    VenueAccountStore(live_db).upsert(
        _VENUE, "main", secret_ref=None, venue_uid=None, enabled=True,
        config={}, at=_AT)
    VenueAccountStore(live_db).upsert(
        "binance", "main", secret_ref=None, venue_uid=None, enabled=True,
        config={}, at=_AT)
    PortfolioDefinitionStore(live_db).upsert(
        other, name="pf-binance", venue_name="binance", account_id="main",
        initial_cash=Decimal("10000.00"), enabled=True, config=None, at=_AT)

    system = _booted(build_live_system(_spec([])))
    try:
        # The binance portfolio rehydrated; the okx durable account assembled.
        assert other in system.portfolio_handler._portfolios
        assert set(_okx_entries(system)) == {(_VENUE, "main")}
    finally:
        system.stop(timeout=5.0)


def test_a_binance_portfolio_does_not_receive_the_okx_venue_account(
    live_db, okx_env
) -> None:
    """CR-01 at the BOOT: the foreign-venue portfolio is not handed OKX's account.

    Same seeding as the test above — a persisted ``binance``/``main`` portfolio while the
    boot brings up ``okx``/``main`` — because that is the shape a BARE-``account_id``
    resolution gets wrong: both accounts answer to "main", so any lookup that drops the
    venue half hands the binance portfolio OKX's account. The consequence is not local —
    the coordinator would judge one venue's positions against the other's and
    ``VenueReconciler`` would emit reconciling fills into the wrong portfolio.

    The OKX-side assertion is deliberately IDENTICAL to the sibling test: the OKX account
    still legitimately names "main", so the bundle and the registry entry are not what is
    under test here — only which portfolio ends up bound to which account is.
    """
    from itrader.portfolio_handler.account import (
        SimulatedCashAccount,
        SimulatedMarginAccount,
    )

    other = PortfolioId(uuid.uuid4())
    # The OKX 'main' account is provisioned so the store-derived boot assembles it.
    VenueAccountStore(live_db).upsert(
        _VENUE, "main", secret_ref=None, venue_uid=None, enabled=True,
        config={}, at=_AT)
    VenueAccountStore(live_db).upsert(
        "binance", "main", secret_ref=None, venue_uid=None, enabled=True,
        config={}, at=_AT)
    PortfolioDefinitionStore(live_db).upsert(
        other, name="pf-binance", venue_name="binance", account_id="main",
        initial_cash=Decimal("10000.00"), enabled=True, config=None, at=_AT)

    system = _booted(build_live_system(_spec([])))
    try:
        portfolio = system.portfolio_handler.get_portfolio(other)
        # Identity is the PAIR, and the leaf is its ONE storage site (``Portfolio``'s two
        # properties read straight off it). The pair — not the bare account id — is what
        # discriminates here: BOTH accounts are named "main". A leaf reading
        # ``("okx", "main")`` would mean this portfolio's orders and reconciliation route
        # to the OKX balance, so the coordinator would judge one venue's positions against
        # the other's and ``VenueReconciler`` would emit reconciling fills into the wrong
        # portfolio.
        assert (portfolio.venue_name, portfolio.account_id) == ("binance", "main")
        # Every live portfolio sits on a COMPUTE leaf: venue truth is read from the venue
        # by the execution adapter that owns the authenticated session, so there is no
        # venue-cached leaf a boot could hand to the wrong portfolio in the first place.
        assert isinstance(
            portfolio.account, (SimulatedCashAccount, SimulatedMarginAccount))
        # The OKX durable account still assembles and registers.
        assert set(_okx_entries(system)) == {(_VENUE, "main")}
    finally:
        system.stop(timeout=5.0)


# --------------------------------------------------------------------------- #
# The rehydrate boot gates (D-08) — placement and ordering, executably
# --------------------------------------------------------------------------- #
def test_a_boot_with_zero_persisted_portfolios_succeeds_cleanly(live_db, okx_env) -> None:
    """MPORT-03 empty edge at the boot — a fresh database is a valid first start."""
    system = _booted(build_live_system(_spec(["acct-solo"])))
    try:
        assert system.portfolio_handler._portfolios == {}
    finally:
        system.stop(timeout=5.0)


def test_a_persisted_portfolio_rehydrates_before_start_with_its_id(
    live_db, okx_env
) -> None:
    """D-08 — the portfolio is registered when the FACTORY RETURNS, with its stored id.

    Asserting the roster is already populated before ``start()`` is what pins the
    placement: a rehydrate inside ``_initialize_live_session`` would leave this empty
    (and would be monkeypatched away entirely in the restart tests).
    """
    from itrader.portfolio_handler.account import (
        SimulatedCashAccount,
        SimulatedMarginAccount,
    )

    persisted = _seed_definition(live_db, name="pf-durable", account_id="acct-a")

    # The spec names NO account: a spec portfolio on "acct-a" would collide with the
    # persisted row by design (gate (b)).
    system = _booted(build_live_system(_spec([])))
    try:
        # start() has NOT been called — construction alone rebuilt the portfolio.
        assert list(system.portfolio_handler._portfolios) == [persisted]
        portfolio = system.portfolio_handler.get_portfolio(persisted)
        assert portfolio.portfolio_id == persisted
        assert portfolio.name == "pf-durable"
        assert portfolio.account_id == "acct-a"
        # The stored ``initial_cash`` is asserted at the STORE (a definition, not a balance).
        assert PortfolioDefinitionStore(live_db).read_all()[0]["initial_cash"] == (
            Decimal("10000.00"))
        # The rehydrated portfolio holds a COMPUTE leaf carrying the stored account
        # identity. That leaf is what makes the two assertions above readable at all: a
        # portfolio is CONSTRUCTED with its account and construction reads the balance, so
        # a leaf whose balance only arrives after a venue round trip could not answer here.
        assert isinstance(
            portfolio.account, (SimulatedCashAccount, SimulatedMarginAccount))
        assert (portfolio.venue_name, portfolio.account_id) == (_VENUE, "acct-a")
    finally:
        system.stop(timeout=5.0)


def test_a_persisted_portfolio_survives_a_full_teardown_and_rebuild(
    live_db, okx_env
) -> None:
    """THE end-to-end restart proof — and NO fixture provisions the row.

    The portfolio is created through the real ``add_portfolio`` on a real booted
    engine, so the definition row comes from PRODUCTION's writer. The second boot then
    has to find it and return the SAME id. Without the writer this test cannot pass at
    all, which is the point: the plan as written was a reader with no writer.
    """
    VenueAccountStore(live_db).upsert(
        _VENUE, "acct-a", secret_ref=None, venue_uid=None, enabled=True,
        config={}, at=_AT)

    # --- first boot: create the portfolio through the live handler --------------
    system = _booted(build_live_system(_spec([])))
    try:
        first_id = system.portfolio_handler.add_portfolio(
            name="pf-restart", exchange=_VENUE, cash=Decimal("25000.00"),
            account_id="acct-a", venue_name=_VENUE)
    finally:
        system.stop(timeout=5.0)

    # --- restart: a brand-new engine over the SAME database ---------------------
    system2 = _booted(build_live_system(_spec([])))
    try:
        assert list(system2.portfolio_handler._portfolios) == [first_id], (
            "the portfolio did not survive the restart — either add_portfolio "
            "persisted no definition row, or rehydrate minted a fresh id")
        portfolio = system2.portfolio_handler.get_portfolio(first_id)
        assert portfolio.name == "pf-restart"
        assert portfolio.account_id == "acct-a"
        # 11-09: read the surviving cash off the DEFINITION ROW rather than through
        # ``portfolio.cash``. The rebuilt portfolio holds a venue-truth account
        # (MPORT-05 attach), so ``cash`` is venue truth and is deliberately unreadable
        # until the first snapshot — the persisted figure is a definition, not a balance.
        row = next(
            r for r in PortfolioDefinitionStore(live_db).read_all()
            if r["portfolio_id"] == first_id)
        assert row["initial_cash"] == Decimal("25000.00")
    finally:
        system2.stop(timeout=5.0)


def test_a_persisted_portfolio_config_override_is_applied_on_the_rehydrated_portfolio(
    live_db, okx_env
) -> None:
    """The BOOT-ORDERING gate, executable — layering must run AFTER rehydrate.

    ``layer_persisted_overrides`` iterates ``portfolio_handler._portfolios``. If
    rehydrate ran after it, that collection would be empty at layering time and the
    persisted config would be silently never applied — no exception, no warning, and
    invisible in any test that only counts portfolios. This test reddens in exactly
    that case, which is why it replaces the plan's "read the builder and check the
    steps appear in order" criterion.
    """
    persisted = _seed_definition(live_db, name="pf-cfg", account_id="acct-a")
    # Persist a portfolio-scope override on the DEFINITION row (D-09).
    PortfolioDefinitionStore(live_db).upsert(
        persisted, name="pf-cfg", venue_name=_VENUE, account_id="acct-a",
        initial_cash=Decimal("10000.00"), enabled=True,
        config={"limits": {"max_positions": 7}}, at=_AT)

    system = _booted(build_live_system(_spec([])))
    try:
        portfolio = system.portfolio_handler.get_portfolio(persisted)
        assert portfolio.config.limits.max_positions == 7, (
            "the persisted portfolio config was not applied — the layering call "
            "iterated an empty collection, meaning rehydrate ran after it")
    finally:
        system.stop(timeout=5.0)

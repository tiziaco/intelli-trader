"""A1 — parametrized 3-leaf account-conformance RED test (D-01/D-02, V17-01/AUD-1 §1d).

The permanent conformance gate (D-02): drives all THREE ``Account`` leaves —
``SimulatedCashAccount``, ``SimulatedMarginAccount``, ``VenueAccount`` — through the
AUD-1 §1d settlement surface every live portfolio depends on:

* (a) admission read via ``available_balance`` (``PortfolioHandler.on_signal``, :300);
* (b) ``reserve`` / ``release`` (the order-admission overlay);
* (c) a BUY settle through ``Portfolio.transact_shares`` (exercises
  ``assert_funds_invariant`` then ``apply_fill_cash_flow``);
* (d) a SELL settle against an existing position (atomicity of the half-applied fill);
* (e) serialization via ``to_dict`` reading ``available_balance`` + ``reserved_balance``.

RED CONTRACT (this is the SUCCESS condition, not a broken build — D-19 CONF-A):
today ``VenueAccount`` implements only ``balance`` / ``available`` / ``reserve`` /
``release`` — it is MISSING ``available_balance`` / ``reserved_balance`` /
``assert_funds_invariant`` / ``apply_fill_cash_flow`` (the V17-01 silent-settlement-loss
defect). So the venue parameter FAILS: the admission read (a), the BUY (c) and the
serialization (e) raise ``AttributeError`` before/around mutation, and the SELL (d)
leaves a PARTIAL mutation (position moved, no cash-ledger entry, no transaction). The
two ``Simulated*`` leaves PASS. The fix that turns the venue leaf GREEN lands in
05.1-04/05/06 (D-01 settlement surface on ``VenueAccount``).

Fully offline — no ``OKX_API_*`` credentials, no network. The venue leaf is built on the
credential-free ``FakeLiveConnector`` snapshotted from the AUD-7 Tier-1 SPOT fixture; the
``venue_connectors`` fixture guarantees ``disconnect()`` teardown so no
ResourceWarning/RuntimeWarning escapes into the strict suite (Pitfall 4,
``filterwarnings=["error"]``).
"""

import json
import uuid
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import pytest
import uuid_utils.compat as uuid_compat

from itrader import idgen
from itrader.core.exceptions import StateError
from itrader.core.ids import OrderId
from itrader.config import PortfolioConfig, get_portfolio_preset
from itrader.outils.dict_merge import recursive_merge
from itrader.portfolio_handler.portfolio import Portfolio
from itrader.portfolio_handler.transaction import Transaction, TransactionType
from itrader.portfolio_handler.account.venue import VenueAccount

_TICKER = "BTC/USDC"
_SPOT_FIXTURE = Path(__file__).parent / "okx_recon_payloads_spot.json"


def _spot_payloads() -> dict:
    """Load the AUD-7 Tier-1 SPOT recon fixture (credential-free, ccxt-unified)."""
    return json.loads(_SPOT_FIXTURE.read_text())


def _margin_config() -> PortfolioConfig:
    """A ``PortfolioConfig`` with ``enable_margin=True`` (selects the margin leaf).

    01-03 selects the account leaf at CONSTRUCTION (cash vs margin), so margin must
    be set in the constructor config — the former post-construction ``update_config``
    toggle no longer rebuilds the leaf.
    """
    return PortfolioConfig.model_validate(recursive_merge(
        get_portfolio_preset("default").model_dump(),
        {"trading_rules": {"enable_margin": True, "max_leverage": Decimal("10")}},
    ))


def _txn(ttype: TransactionType, qty: str, price: str,
         commission: str = "0") -> Transaction:
    """Build a settlement ``Transaction`` (Decimal money entered at the boundary)."""
    return Transaction(
        datetime.now(), ttype, _TICKER, Decimal(price), Decimal(qty),
        Decimal(commission), None, idgen.generate_transaction_id(),
        fill_id=uuid_compat.uuid7(),
    )


@pytest.fixture
def venue_connectors():
    """Factory yielding CONNECTED ``FakeLiveConnector``s with guaranteed teardown.

    Each created connector runs its loop on a daemon thread; every one is
    ``disconnect()``-ed in teardown (cancelling spawned tasks + closing the client)
    so the strict suite sees no ResourceWarning/RuntimeWarning (Pitfall 4). The
    import is deferred so early collection never depends on ``tests.support``.
    """
    from tests.support.fake_venue_connector import make_fake_venue_connector

    created = []

    def _make(payloads=None):
        connector = make_fake_venue_connector(sandbox=True, payloads=payloads)
        connector.connect()
        created.append(connector)
        return connector

    try:
        yield _make
    finally:
        for connector in created:
            connector.disconnect()


def _build_cash_leaf(_venue_connectors):
    portfolio = Portfolio("cash_pf", "paper", Decimal("150000"), datetime.now())
    return portfolio, portfolio.account


def _build_margin_leaf(_venue_connectors):
    portfolio = Portfolio("margin_pf", "paper", Decimal("150000"),
                          datetime.now(), config=_margin_config())
    return portfolio, portfolio.account


def _build_venue_leaf(venue_connectors):
    # A real Portfolio whose account leaf is swapped for a VenueAccount snapshotted
    # from the SPOT fixture (quote from wiring == USDC, never the USDT default).
    portfolio = Portfolio("venue_pf", "okx", Decimal("150000"), datetime.now())
    connector = venue_connectors(_spot_payloads())
    account = VenueAccount(connector, quote_currency="USDC", account_id="acct-test")
    account.snapshot()
    portfolio.account = account
    return portfolio, account


_LEAF_BUILDERS = {
    "cash": _build_cash_leaf,
    "margin": _build_margin_leaf,
    "venue": _build_venue_leaf,
}


@pytest.fixture(params=["cash", "margin", "venue"])
def leaf(request, venue_connectors):
    """Parametrized ``(portfolio, account)`` across the three ``Account`` leaves."""
    return _LEAF_BUILDERS[request.param](venue_connectors)


# --- (a) admission read via available_balance --------------------------------


def test_admission_read_available_balance(leaf):
    """The admission read (``account.available_balance``) is on the ABC surface.

    RED on ``VenueAccount``: it has no ``available_balance`` → ``AttributeError``
    (V17-01). With no reservations, buying power equals the ledger balance.
    """
    portfolio, account = leaf
    assert account.available_balance == portfolio.cash


# --- (b) reserve / release (venue conforms here — isolates the RED surface) ---


def test_reserve_release_conforms(leaf):
    """``reserve`` then ``release`` restores available on EVERY leaf (incl. venue).

    Documents that reserve/release DO conform on all three leaves — the venue RED
    is specifically the settlement surface, not the admission overlay.
    """
    portfolio, account = leaf
    before = account.available_balance
    order_id = OrderId(uuid.uuid4())

    account.reserve(order_id, Decimal("1000"))
    assert account.available_balance == before - Decimal("1000")

    account.release(order_id)
    assert account.available_balance == before


# --- (c) BUY settle through Portfolio.transact_shares ------------------------


def test_buy_settlement_through_transact_shares(leaf):
    """A BUY settle exercises ``assert_funds_invariant`` then ``apply_fill_cash_flow``.

    RED on ``VenueAccount``: the spot settle path calls ``assert_funds_invariant``
    on the debit side → ``AttributeError`` BEFORE any mutation (V17-01). All three
    leaves settle identically here: a 0.1 @ 100 open commits exactly 10 of buying
    power (cash leaf debits balance, margin leaf locks notional, venue leaf moves
    its local fill-ledger). Asserting the delta (``before − 10``) rather than an
    absolute figure holds uniformly across leaves with different starting balances
    (the two Simulated leaves start at 150000 → 149990; the venue leaf starts at
    its snapshotted venue balance).
    """
    portfolio, account = leaf
    before = account.available_balance
    portfolio.transact_shares(_txn(TransactionType.BUY, qty="0.1", price="100"))

    position = portfolio.get_open_position(_TICKER)
    assert position is not None
    assert position.net_quantity == Decimal("0.1")
    assert account.available_balance == before - Decimal("10")


# --- (d) SELL settle against an existing position (atomicity) ----------------


def test_sell_settlement_is_atomic(leaf):
    """A SELL settle must be ATOMIC — never a half-applied fill.

    Seeds a base position directly (account-independent), then settles a full-close
    SELL. RED on ``VenueAccount``: the position mutates first, then
    ``apply_fill_cash_flow`` raises ``AttributeError`` → a PARTIAL mutation (position
    moved, no cash-ledger entry, no transaction). A correct leaf either settles fully
    (position closed AND a transaction recorded) or leaves nothing moved.
    """
    portfolio, account = leaf
    portfolio.position_manager.process_position_update(
        _txn(TransactionType.BUY, qty="1", price="100"))
    prior_qty = portfolio.get_open_position(_TICKER).net_quantity
    prior_txns = len(portfolio.transactions)

    settled = True
    try:
        portfolio.process_transaction(_txn(TransactionType.SELL, qty="1", price="110"))
    except AttributeError:
        settled = False

    post = portfolio.get_open_position(_TICKER)
    post_qty = post.net_quantity if post is not None else Decimal("0")

    if settled:
        # A conforming leaf fully settled the close: position moved AND recorded.
        assert post_qty != prior_qty
        assert len(portfolio.transactions) > prior_txns
    else:
        # A leaf that raised MUST NOT have half-applied the settlement (atomicity).
        # RED on VenueAccount today: the position moved but no cash/txn settled.
        assert post_qty == prior_qty, (
            "partial mutation: position moved but the cash-ledger/transaction did "
            "not settle (V17-01 half-applied fill)"
        )


# --- (e) serialization via to_dict reading the ABC surface -------------------


def test_serialization_reads_account_surface(leaf):
    """``to_dict`` reads ``available_balance`` + ``reserved_balance`` off the account.

    RED on ``VenueAccount``: ``to_dict`` dereferences ``account.available_balance``
    (portfolio.py:888-889) → ``AttributeError`` (V17-01). With no reservations,
    available equals balance and reserved is zero.
    """
    portfolio, account = leaf
    snapshot = portfolio.to_dict()
    assert snapshot["available_cash"] == account.balance
    assert snapshot["reserved_cash"] == Decimal("0")


# --- (f) D-02 margin op on a non-margin (venue) account fails loud, no mutation ---


def test_margin_op_on_venue_account_raises_before_mutation(venue_connectors):
    """D-02: a venue-linked + margin-configured portfolio fails LOUD at the guard.

    Re-typing ``Portfolio.account`` to the ABC lets a ``VenueAccount`` wire onto a
    margin-configured portfolio (the V17-14 hazard surface). Driving a margin BUY
    through ``_process_transaction_margin`` used to hit a bare ``cast`` no-op and
    then ``AttributeError`` mid-settlement — AFTER the position had mutated. The
    ``_require_margin_account`` isinstance guard now raises a typed ``StateError``
    BEFORE any mutation; the untouched position + transaction ledger assert the
    settlement did not partially apply (closes the V17-14 cast arm).
    """
    portfolio = Portfolio("venue_margin_pf", "okx", Decimal("150000"),
                          datetime.now(), config=_margin_config())
    connector = venue_connectors(_spot_payloads())
    account = VenueAccount(connector, quote_currency="USDC", account_id="acct-test")
    account.snapshot()
    portfolio.account = account

    prior_txns = len(portfolio.transactions)
    with pytest.raises(StateError):
        portfolio.transact_shares(_txn(TransactionType.BUY, qty="0.1", price="100"))

    # No partial mutation: no position opened, no transaction recorded.
    assert portfolio.get_open_position(_TICKER) is None
    assert len(portfolio.transactions) == prior_txns

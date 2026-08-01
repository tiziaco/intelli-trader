"""Adapter-owned venue truth: ``snapshot()`` on both exchanges.

Venue truth now belongs to whatever owns the authenticated session — the execution
adapter. These tests pin the derivation rules that moved onto it, and they matter for a
specific reason: the snapshot feeds the drift compare, and a wrong answer there either
halts a healthy engine or fails to halt a diverged one.

The rules with teeth:

  - **Per-market-type position truth.** A spot account has no position rows, so reading
    the positions channel would report FLAT for an account holding coins. Spot truth is
    derived from the base-currency balance instead, and the positions RPC is skipped.
  - **Flat is an ABSENT key, never a zero entry.** Both channels agree, so a consumer
    never has to treat "no key" and "zero" as different answers.
  - **Decimal edge.** Every venue number crosses via ``to_money(str(x))``, never
    ``Decimal(float)`` — this value sits directly on a money compare.
  - **Engine-thread I/O.** Fetches go through the connector's synchronous RPC, so they run
    on the engine thread rather than the loop whose streams are being reconciled against.

This directory is package-less (NO ``__init__.py``); the ``unit`` marker is folder-derived.
Indentation: 4-space (tests/unit convention), even though the modules under test are TAB.
"""

import queue
from decimal import Decimal
from typing import Any

import pytest

from itrader.execution_handler.exchanges.base import AbstractExchange, AccountSnapshot
from itrader.execution_handler.exchanges.okx import OkxExchange
from itrader.execution_handler.exchanges.simulated import SimulatedExchange


class _FakeClient:
    """Returns canned ccxt-unified payloads and records which endpoints were asked."""

    def __init__(self, balance: Any, positions: Any) -> None:
        self._balance = balance
        self._positions = positions
        self.calls: list[str] = []

    def fetch_balance(self) -> Any:
        self.calls.append("fetch_balance")
        return self._balance

    def fetch_positions(self) -> Any:
        self.calls.append("fetch_positions")
        return self._positions


class _FakeConnector:
    """A session whose ``call`` is a straight pass-through — no loop, no I/O."""

    def __init__(self, client: _FakeClient) -> None:
        self.client = client
        self.call_count = 0

    def call(self, result: Any) -> Any:
        # The fake client's methods are synchronous, so ``call`` receives their RESULT.
        # That is exactly the seam being asserted: the adapter must route venue reads
        # through the connector rather than touching a loop itself.
        self.call_count += 1
        return result


def _okx(
    *,
    balance: Any = None,
    positions: Any = None,
    market_type: str = "derivative",
    symbol: str | None = None,
    quote: str = "USDT",
) -> tuple[OkxExchange, _FakeClient]:
    client = _FakeClient(balance if balance is not None else {}, positions or [])
    exchange = OkxExchange(
        queue.Queue(), _FakeConnector(client),
        quote_currency=quote, market_type=market_type, symbol=symbol)
    return exchange, client


# --------------------------------------------------------------------------- #
# The uniform contract
# --------------------------------------------------------------------------- #
def test_both_exchanges_satisfy_the_adapter_protocol() -> None:
    """``snapshot`` is part of the structural seam, so both arms must carry it.

    A consumer forced to ask "does this exchange support snapshots?" would be re-deriving
    account KIND from the adapter type — the coupling this surface exists to remove.
    """
    assert isinstance(SimulatedExchange(queue.Queue()), AbstractExchange)
    okx, _ = _okx()
    assert isinstance(okx, AbstractExchange)


def test_the_simulated_exchange_reports_nothing() -> None:
    """Simulated cash and positions are engine-computed — there is no external truth."""
    snapshot = SimulatedExchange(queue.Queue()).snapshot()
    assert snapshot == AccountSnapshot.empty()
    assert snapshot.balances == {}
    assert snapshot.positions == {}


def test_a_snapshot_is_frozen() -> None:
    """A value object on the drift-compare path must not be mutable in flight."""
    snapshot = AccountSnapshot.empty()
    with pytest.raises(Exception):
        snapshot.balances = {"USDT": Decimal("1")}  # type: ignore[misc]


# --------------------------------------------------------------------------- #
# Balances
# --------------------------------------------------------------------------- #
def test_the_settled_quote_total_is_read_as_decimal() -> None:
    """``total`` is the settled figure the engine compares against."""
    okx, _ = _okx(balance={"total": {"USDT": "1234.56"}, "free": {"USDT": "1000"}})
    snapshot = okx.snapshot()
    assert snapshot.balances["USDT"] == Decimal("1234.56")
    assert isinstance(snapshot.balances["USDT"], Decimal)


def test_the_venue_free_figure_is_never_read() -> None:
    """Admission is governed by the engine's own pending reservations.

    Netting against a venue-side ``free`` would double-count the engine's reservations —
    the venue has already deducted its own hold, and the engine deducts it again.
    """
    okx, _ = _okx(balance={"total": {"USDT": "1000"}, "free": {"USDT": "250"}})
    snapshot = okx.snapshot()
    assert snapshot.balances["USDT"] == Decimal("1000")
    assert "250" not in str(snapshot.balances)


def test_a_missing_balance_key_yields_no_entry_rather_than_decimal_none() -> None:
    """None/missing is guarded BEFORE the Decimal edge."""
    okx, _ = _okx(balance={"total": {}})
    assert okx.snapshot().balances == {}


def test_a_malformed_balance_payload_is_survived() -> None:
    """A venue answering something unexpected must not crash the reconcile path."""
    for payload in (None, [], "nonsense", {"total": None}):
        okx, _ = _okx(balance=payload)
        assert okx.snapshot().balances == {}


def test_only_the_configured_currencies_are_lifted() -> None:
    """Dust in fifty coins must not become a fifty-entry map the compare has to filter."""
    okx, _ = _okx(
        balance={"total": {"USDT": "100", "DOGE": "9999", "SHIB": "1"}},
        quote="USDT")
    assert set(okx.snapshot().balances) == {"USDT"}


def test_a_spot_account_lifts_both_legs_of_its_pair() -> None:
    """The base leg is a balance too — it IS the spot position."""
    okx, _ = _okx(
        balance={"total": {"USDC": "500", "BTC": "0.25"}},
        market_type="spot", symbol="BTC/USDC", quote="USDC")
    balances = okx.snapshot().balances
    assert balances == {"USDC": Decimal("500"), "BTC": Decimal("0.25")}


# --------------------------------------------------------------------------- #
# Derivative position truth
# --------------------------------------------------------------------------- #
def test_derivative_positions_come_from_the_position_channel() -> None:
    okx, client = _okx(
        balance={"total": {"USDT": "1000"}},
        positions=[{"symbol": "BTC/USDT:USDT", "contracts": "3", "side": "long"}])
    snapshot = okx.snapshot()
    assert snapshot.positions == {"BTC/USDT:USDT": Decimal("3")}
    assert "fetch_positions" in client.calls


def test_a_short_side_flips_the_sign() -> None:
    """Sign is the whole point: an unsigned short reads as a long of the same size."""
    okx, _ = _okx(
        positions=[{"symbol": "BTC/USDT:USDT", "contracts": "2.5", "side": "short"}])
    assert okx.snapshot().positions == {"BTC/USDT:USDT": Decimal("-2.5")}


def test_position_rows_missing_a_symbol_or_size_are_skipped() -> None:
    """A partial row must not become a phantom position or a Decimal('None')."""
    okx, _ = _okx(positions=[
        {"symbol": "BTC/USDT:USDT", "contracts": None},
        {"contracts": "1"},
        "nonsense",
        {"symbol": "ETH/USDT:USDT", "contracts": "1", "side": "long"},
    ])
    assert okx.snapshot().positions == {"ETH/USDT:USDT": Decimal("1")}


def test_a_malformed_positions_payload_is_survived() -> None:
    for payload in (None, {}, "nonsense"):
        okx, _ = _okx(positions=payload)
        assert okx.snapshot().positions == {}


# --------------------------------------------------------------------------- #
# Spot position truth — derived from the base balance
# --------------------------------------------------------------------------- #
def test_spot_position_is_derived_from_the_base_balance() -> None:
    """Holding the base currency IS the spot position."""
    okx, _ = _okx(
        balance={"total": {"USDC": "500", "BTC": "0.4"}},
        market_type="spot", symbol="BTC/USDC", quote="USDC")
    assert okx.snapshot().positions == {"BTC/USDC": Decimal("0.4")}


def test_a_spot_snapshot_never_asks_the_position_channel() -> None:
    """``fetch_positions`` yields ``[]`` on spot, so reading it would report FLAT.

    An account holding coins reported as flat is the dangerous direction: the drift sweep
    would see venue-qty 0 against a live engine position.
    """
    okx, client = _okx(
        balance={"total": {"USDC": "500", "BTC": "0.4"}},
        positions=[{"symbol": "BTC/USDC", "contracts": "99", "side": "long"}],
        market_type="spot", symbol="BTC/USDC", quote="USDC")
    okx.snapshot()
    assert client.calls == ["fetch_balance"]
    assert "fetch_positions" not in client.calls


def test_a_zero_base_total_is_flat_as_an_absent_key() -> None:
    """The authoritative-zero case: a real flat clears the holding, as an ABSENT key.

    Mirrors the derivative channel, which reports no row when flat — so both channels
    answer "flat" the same way and no consumer distinguishes absent from zero.
    """
    okx, _ = _okx(
        balance={"total": {"USDC": "500", "BTC": "0"}},
        market_type="spot", symbol="BTC/USDC", quote="USDC")
    assert okx.snapshot().positions == {}


def test_an_absent_base_key_is_flat_too() -> None:
    """No base key in a REST snapshot means the venue holds none of it."""
    okx, _ = _okx(
        balance={"total": {"USDC": "500"}},
        market_type="spot", symbol="BTC/USDC", quote="USDC")
    assert okx.snapshot().positions == {}


def test_an_unconfigured_spot_pair_is_structurally_inert() -> None:
    """No symbol wired means no holding can be keyed — an unwired adapter reports nothing."""
    okx, _ = _okx(
        balance={"total": {"USDC": "500", "BTC": "1"}},
        market_type="spot", symbol=None, quote="USDC")
    assert okx.snapshot().positions == {}


def test_spot_quantities_cross_the_decimal_edge_exactly() -> None:
    """``to_money(str(x))``, never ``Decimal(float)`` — a repr artifact here is a defect.

    ``0.1`` chosen deliberately: ``Decimal(0.1)`` is 0.1000000000000000055511151231…
    and would fail this equality, so the assertion distinguishes the two constructions.
    """
    okx, _ = _okx(
        balance={"total": {"USDC": "1", "BTC": "0.1"}},
        market_type="spot", symbol="BTC/USDC", quote="USDC")
    assert okx.snapshot().positions["BTC/USDC"] == Decimal("0.1")


# --------------------------------------------------------------------------- #
# The threading seam
# --------------------------------------------------------------------------- #
def test_venue_reads_go_through_the_connector_rpc() -> None:
    """Blocking venue I/O must run on the ENGINE thread, not the connector loop.

    A fetch scheduled onto the loop would block the very streams the caller is
    reconciling against, so every read is routed through the synchronous RPC.
    """
    client = _FakeClient({"total": {"USDT": "1"}}, [])
    connector = _FakeConnector(client)
    exchange = OkxExchange(queue.Queue(), connector, market_type="derivative")
    exchange.snapshot()
    assert connector.call_count == 2, "both the balance and positions read use call()"


def test_a_snapshot_retains_no_state_between_calls() -> None:
    """No cache behind the value — fresh truth is another call, not a refresh.

    Nothing retained means no stale-cache state to reason about and no lock to hold.
    """
    client = _FakeClient({"total": {"USDT": "100"}}, [])
    exchange = OkxExchange(queue.Queue(), _FakeConnector(client), market_type="derivative")
    first = exchange.snapshot()
    client._balance = {"total": {"USDT": "250"}}
    second = exchange.snapshot()
    assert first.balances["USDT"] == Decimal("100")
    assert second.balances["USDT"] == Decimal("250")

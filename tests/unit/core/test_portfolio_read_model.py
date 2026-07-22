"""M4-04 conformance tests: PortfolioReadModel Protocol + frozen PositionView.

These lock the narrow cross-handler read boundary (D-13..D-17, Plan 05-03):

1. ``PositionView`` is a frozen/slots dataclass — mutation raises
   ``FrozenInstanceError`` (D-15: live objects inside a module, immutable
   snapshots across the boundary).
2. ``PositionView`` carries exactly the four fields consumers read today
   (ticker, side, net_quantity, avg_price) with Decimal money types.
3. ``PortfolioReadModel`` is ``runtime_checkable`` — a minimal fake
   implementing all eight members passes ``isinstance``; an object missing
   ``reserve`` fails (narrowness is enforced, not just satisfied).

The real-handler conformance assertion (``isinstance(PortfolioHandler(...),
PortfolioReadModel)``) is added in Task 2 of the same plan.

Plan 07-01 (M5-06) widens the Protocol by ONE member: ``total_equity`` —
the RiskPercent sizing input (RESEARCH Pitfall 8). D-14's "equity excluded"
rule is narrowly amended for it; oracle-dark (the golden FractionOfCash
policy never reads it).

Phase 06 (WR-02, LIFE-01) widens it by ONE further member:
``active_portfolio_ids`` — the run-end time-in-force sweep enumerates active
portfolios to expire their resting orders (replaces a ``# type: ignore``
call to a non-Protocol method).

Plan 05.3-04 (D-15, V17-13) widens it by ONE further member: ``drop_pending``
— the venue ORDER-ACK drops the local pending-reservation overlay (routed
through the same read/write seam reserve/release use), closing the
buying-power double-count. Eleven members total.
"""

import dataclasses
from decimal import Decimal

import pytest

from itrader.core.enums import PositionSide
from itrader.core.ids import OrderId, PortfolioId
from itrader.core.portfolio_read_model import PortfolioReadModel, PositionView

pytestmark = pytest.mark.unit


def _make_view() -> PositionView:
    return PositionView(
        ticker="BTCUSD",
        side=PositionSide.LONG,
        net_quantity=Decimal("1.23456789"),
        avg_price=Decimal("40123.45"),
    )


# ---------------------------------------------------------------------------
# PositionView: frozen, slots, Decimal-typed
# ---------------------------------------------------------------------------


def test_position_view_is_frozen():
    """D-15: assigning to any field raises FrozenInstanceError."""
    view = _make_view()
    with pytest.raises(dataclasses.FrozenInstanceError):
        view.net_quantity = Decimal("99")  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        view.ticker = "ETHUSD"  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        view.side = PositionSide.SHORT  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        view.avg_price = Decimal("0")  # type: ignore[misc]


def test_position_view_fields_exact():
    """D-15: exactly ticker/side/net_quantity/avg_price — no extra surface."""
    field_names = [f.name for f in dataclasses.fields(PositionView)]
    assert field_names == ["ticker", "side", "net_quantity", "avg_price"]


def test_position_view_money_types_are_decimal():
    """Money is Decimal end-to-end (locked decision): values cross as Decimal."""
    view = _make_view()
    assert isinstance(view.net_quantity, Decimal)
    assert isinstance(view.avg_price, Decimal)
    assert isinstance(view.side, PositionSide)
    assert view.net_quantity == Decimal("1.23456789")
    assert view.avg_price == Decimal("40123.45")


def test_position_view_uses_slots():
    """slots=True: no __dict__, so no attribute smuggling across the boundary."""
    view = _make_view()
    assert not hasattr(view, "__dict__")


# ---------------------------------------------------------------------------
# PortfolioReadModel: runtime_checkable Protocol, eleven members, narrow
# ---------------------------------------------------------------------------


class _ConformingFake:
    """Minimal fake implementing all twelve Protocol members."""

    def active_portfolio_ids(self) -> list[PortfolioId]:
        return []

    def available_cash(self, portfolio_id: PortfolioId) -> Decimal:
        return Decimal("100000.00")

    def get_position(self, portfolio_id: PortfolioId, ticker: str) -> PositionView | None:
        return None

    def reserve(self, portfolio_id: PortfolioId, order_id: OrderId, amount: Decimal) -> None:
        return None

    def release(self, portfolio_id: PortfolioId, order_id: OrderId) -> None:
        return None

    def drop_pending(self, portfolio_id: PortfolioId, order_id: OrderId) -> None:
        return None

    def exchange_for(self, portfolio_id: PortfolioId) -> str:
        return "paper"

    def account_for(self, portfolio_id: PortfolioId) -> str | None:
        return "acct_a"

    def open_position_count(self, portfolio_id: PortfolioId) -> int:
        return 0

    def total_equity(self, portfolio_id: PortfolioId) -> Decimal:
        return Decimal("100000.00")

    def maintenance_margin(self, portfolio_id: PortfolioId) -> Decimal:
        return Decimal("0")

    def margin_ratio(self, portfolio_id: PortfolioId) -> Decimal:
        return Decimal("0")


class _MissingReserveFake:
    """Implements all but `reserve` (which is deliberately absent)."""

    def active_portfolio_ids(self) -> list[PortfolioId]:
        return []

    def available_cash(self, portfolio_id: PortfolioId) -> Decimal:
        return Decimal("0")

    def get_position(self, portfolio_id: PortfolioId, ticker: str) -> PositionView | None:
        return None

    def release(self, portfolio_id: PortfolioId, order_id: OrderId) -> None:
        return None

    def drop_pending(self, portfolio_id: PortfolioId, order_id: OrderId) -> None:
        return None

    def exchange_for(self, portfolio_id: PortfolioId) -> str:
        return "paper"

    def open_position_count(self, portfolio_id: PortfolioId) -> int:
        return 0

    def total_equity(self, portfolio_id: PortfolioId) -> Decimal:
        return Decimal("0")

    def maintenance_margin(self, portfolio_id: PortfolioId) -> Decimal:
        return Decimal("0")

    def margin_ratio(self, portfolio_id: PortfolioId) -> Decimal:
        return Decimal("0")


def test_protocol_is_runtime_checkable_and_fake_conforms():
    """D-16: structural typing — a fake with all twelve methods passes isinstance."""
    assert isinstance(_ConformingFake(), PortfolioReadModel)


def test_object_missing_reserve_fails_isinstance():
    """Narrowness is enforced: a missing member breaks conformance."""
    assert not isinstance(_MissingReserveFake(), PortfolioReadModel)


def test_protocol_declares_exactly_twelve_methods():
    """OQ1 + Plan 07-01 + Phase 06 WR-02 + Plan 02-05 + Plan 05.3-04 + Plan 11-05:
    six original members + total_equity (RiskPercent input) + active_portfolio_ids
    (run-end TIF sweep) + maintenance_margin/margin_ratio (D-13/MARGIN-03
    compute-on-demand accessors) + drop_pending (D-15/V17-13 venue-ack overlay
    drop) + account_for (D-27 account-routing half of the (venue, account_id)
    order target)."""
    expected = {
        "active_portfolio_ids",
        "available_cash",
        "get_position",
        "reserve",
        "release",
        "drop_pending",
        "exchange_for",
        "account_for",
        "open_position_count",
        "total_equity",
        "maintenance_margin",
        "margin_ratio",
    }
    declared = {
        name
        for name in vars(PortfolioReadModel)
        if not name.startswith("_") and callable(vars(PortfolioReadModel)[name])
    }
    assert declared == expected


# ---------------------------------------------------------------------------
# Real-handler conformance (D-16: structural, no inheritance) — Task 2
# ---------------------------------------------------------------------------


@pytest.fixture
def handler_with_portfolio():
    from queue import Queue

    from itrader.portfolio_handler.portfolio_handler import PortfolioHandler

    handler = PortfolioHandler(Queue())
    portfolio_id = handler.add_portfolio("Conformance", "paper", 100000)
    return handler, portfolio_id


def test_portfolio_handler_satisfies_protocol(handler_with_portfolio):
    """D-16: PortfolioHandler passes isinstance — structurally, no inheritance."""
    handler, _ = handler_with_portfolio
    assert isinstance(handler, PortfolioReadModel)
    # No inheritance: the Protocol is not in the MRO.
    assert PortfolioReadModel not in type(handler).__mro__


def test_handler_get_position_none_when_flat(handler_with_portfolio):
    """D-15: no open position -> None (not an empty view)."""
    handler, portfolio_id = handler_with_portfolio
    assert handler.get_position(portfolio_id, "BTCUSD") is None


def test_handler_get_position_returns_frozen_view(handler_with_portfolio):
    """D-15: an open position crosses the boundary as a frozen PositionView."""
    from datetime import datetime

    import uuid_utils.compat as uuid_compat

    from itrader import idgen
    from itrader.core.enums import TransactionType
    from itrader.core.ids import TransactionId
    from itrader.portfolio_handler.transaction import Transaction

    handler, portfolio_id = handler_with_portfolio
    portfolio = handler.get_portfolio(portfolio_id)
    portfolio.transact_shares(
        Transaction(
            time=datetime(2024, 1, 1),
            type=TransactionType.BUY,
            ticker="BTCUSD",
            price=Decimal("40000.00"),
            quantity=Decimal("1.5"),
            commission=Decimal("0"),
            portfolio_id=portfolio_id,
            id=TransactionId(idgen.generate_transaction_id()),
            fill_id=uuid_compat.uuid7(),
        )
    )

    view = handler.get_position(portfolio_id, "BTCUSD")
    assert isinstance(view, PositionView)
    assert view.ticker == "BTCUSD"
    assert view.side is PositionSide.LONG
    assert view.net_quantity == Decimal("1.5")
    assert isinstance(view.avg_price, Decimal)
    with pytest.raises(dataclasses.FrozenInstanceError):
        view.net_quantity = Decimal("0")  # type: ignore[misc]


def test_handler_available_cash_and_metadata(handler_with_portfolio):
    """available_cash/exchange_for/open_position_count delegate to the portfolio."""
    handler, portfolio_id = handler_with_portfolio
    assert handler.available_cash(portfolio_id) == Decimal("100000.00")
    assert handler.exchange_for(portfolio_id) == "paper"
    assert handler.open_position_count(portfolio_id) == 0


def test_handler_reserve_and_release_round_trip(handler_with_portfolio):
    """reserve/release delegate to CashManager's per-reference machinery."""
    import uuid

    handler, portfolio_id = handler_with_portfolio
    order_id = OrderId(uuid.uuid4())

    handler.reserve(portfolio_id, order_id, Decimal("250.12345678"))
    assert handler.available_cash(portfolio_id) == Decimal("100000.00") - Decimal(
        "250.12345678"
    )

    handler.release(portfolio_id, order_id)
    assert handler.available_cash(portfolio_id) == Decimal("100000.00")
    # Idempotent: releasing again is a silent no-op.
    handler.release(portfolio_id, order_id)
    assert handler.available_cash(portfolio_id) == Decimal("100000.00")


# ---------------------------------------------------------------------------
# total_equity (Plan 07-01 — RiskPercent input, RESEARCH Pitfall 8)
# ---------------------------------------------------------------------------


def test_handler_total_equity_cash_only_is_full_balance(handler_with_portfolio):
    """Cash-only portfolio: total_equity equals the FULL ledger balance.

    The full balance includes reservations (available cash + reservations) —
    equity is a metrics figure, not buying power (contrast D-14's
    available_cash).
    """
    handler, portfolio_id = handler_with_portfolio
    equity = handler.total_equity(portfolio_id)
    assert isinstance(equity, Decimal)
    assert equity == Decimal("100000.00")


def test_handler_total_equity_unchanged_by_reservation(handler_with_portfolio):
    """A reservation reduces available_cash but NOT total_equity (full balance)."""
    import uuid

    handler, portfolio_id = handler_with_portfolio
    order_id = OrderId(uuid.uuid4())
    handler.reserve(portfolio_id, order_id, Decimal("500.00"))
    assert handler.available_cash(portfolio_id) == Decimal("99500.00")
    assert handler.total_equity(portfolio_id) == Decimal("100000.00")
    handler.release(portfolio_id, order_id)


def test_handler_total_equity_unknown_portfolio_raises(handler_with_portfolio):
    """Unknown portfolio_id raises the same not-found error as sibling reads."""
    import uuid

    from itrader.core.exceptions import PortfolioNotFoundError

    handler, _ = handler_with_portfolio
    with pytest.raises(PortfolioNotFoundError):
        handler.total_equity(PortfolioId(uuid.uuid4()))

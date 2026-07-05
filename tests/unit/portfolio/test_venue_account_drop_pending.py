"""D-15 unit tests — drop the local ``_pending`` overlay on the venue ORDER-ACK.

Closes V17-13 (buying-power double-count): today ``VenueAccount._pending`` is only
popped on terminal ``release``. Between the venue ORDER-ACK and terminal release the
same hold is counted twice — once by the local overlay, once by the venue's own
netting — so every resting order understates available buying power. D-15 drops the
overlay the moment the ack arrives (``VenueAccount.drop_pending``), routed through the
existing ``PortfolioReadModel`` seam the order domain already uses for reserve/release
and getattr-guarded so paper/simulated accounts are a clean skip.

Offline — the ``fake_venue_connector`` double (05-02) owns connect/disconnect so every
spawned push stream is cancelled and the client closed in teardown (clean under
``filterwarnings=["error"]``).
"""

import uuid
from decimal import Decimal
from typing import Optional

from itrader.core.ids import OrderId, PortfolioId
from itrader.core.money import to_money
from itrader.portfolio_handler.account.base import Account
from itrader.portfolio_handler.account.simulated import SimulatedCashAccount
from itrader.portfolio_handler.account.venue import VenueAccount
from tests.support.fake_venue_connector import FakeLiveConnector


def test_ack_drops_pending_overlay(
    fake_venue_connector: FakeLiveConnector,
) -> None:
    """D-15: the ORDER-ACK drops the local ``_pending`` overlay immediately.

    RED on current code — ``drop_pending`` does not exist, so the overlay stays held
    (available understated: the double-count). GREEN — the ack pops the overlay and
    available is restored to the settled balance (the venue ``free`` already excludes
    the resting hold, so the local overlay must not linger).
    """
    account = VenueAccount(fake_venue_connector)
    account.snapshot()  # available == 78999.79

    order_id = OrderId(uuid.uuid4())
    account.reserve(order_id, Decimal("1000"))
    # Overlay held: available understated by the reservation (pre-ack).
    assert str(order_id) in account._pending
    assert account.available_balance == Decimal("77999.79")

    # ORDER-ACK arrives -> drop the overlay (non-terminal; ledger untouched).
    account.drop_pending(order_id)

    assert str(order_id) not in account._pending
    assert account.available_balance == Decimal("78999.79")
    # The drop is NON-terminal: it does not settle a fill (ledger delta stays zero).
    assert account.balance == Decimal("78999.79")


def test_drop_pending_is_idempotent(
    fake_venue_connector: FakeLiveConnector,
) -> None:
    """Dropping an unknown / already-dropped order id is a silent no-op (mirrors release)."""
    account = VenueAccount(fake_venue_connector)
    account.snapshot()

    order_id = OrderId(uuid.uuid4())
    # Never reserved — the drop must not raise (KeyError-free pop).
    account.drop_pending(order_id)
    assert account.available_balance == Decimal("78999.79")

    account.reserve(order_id, Decimal("500"))
    account.drop_pending(order_id)
    # Second drop of the same id is still a clean no-op.
    account.drop_pending(order_id)
    assert account.available_balance == Decimal("78999.79")


def test_simulated_account_has_no_drop_pending() -> None:
    """Paper/simulated accounts expose NO ``drop_pending`` — the seam getattr-skips them.

    The PortfolioHandler delegate is ``getattr(account, "drop_pending", None)``; this
    pins the contract that a non-VenueAccount leaf has no ``drop_pending`` attribute
    (it lives ONLY on VenueAccount, not the base ``Account`` ABC), so the ack path is a
    clean no-op for simulated portfolios (oracle-dark). Asserted at the class level to
    avoid the portfolio/storage wiring a concrete instance needs.
    """
    assert not hasattr(SimulatedCashAccount, "drop_pending")
    assert not hasattr(Account, "drop_pending")


class _RecordingReadModel:
    """Minimal ``PortfolioReadModel``-shaped double recording ``drop_pending`` calls."""

    def __init__(self) -> None:
        self.dropped: list[tuple[PortfolioId, OrderId]] = []

    def drop_pending(self, portfolio_id: PortfolioId, order_id: OrderId) -> None:
        self.dropped.append((portfolio_id, order_id))


class _FakeOrder:
    def __init__(self) -> None:
        self.venue_order_id: Optional[str] = None


class _FakeStorage:
    """Fake ``OrderStorage`` exposing only the two members ``stamp_venue_order_id`` touches."""

    def __init__(self, order: Optional[_FakeOrder]) -> None:
        self._order = order
        self.updated = False

    def get_order_by_id(
        self, order_id: OrderId, portfolio_id: Optional[PortfolioId] = None
    ) -> Optional[_FakeOrder]:
        return self._order

    def update_order(self, order: _FakeOrder) -> bool:
        self.updated = True
        return True


def test_stamp_venue_order_id_drops_overlay_via_readmodel_seam() -> None:
    """The ORDER-ACK path drops the overlay through the injected read-model seam (D-15).

    ``stamp_venue_order_id`` must call ``PortfolioReadModel.drop_pending(portfolio_id,
    order_id)`` after stamping — the SAME injected seam the order domain uses for
    reserve/release (queue-only cross-domain contract, not a direct account import).
    """
    import logging

    from itrader.order_handler.order_manager import OrderManager

    read_model = _RecordingReadModel()
    storage = _FakeStorage(_FakeOrder())
    manager = OrderManager(
        storage,  # type: ignore[arg-type]
        logging.getLogger("test"),
        portfolio_handler=read_model,  # type: ignore[arg-type]
    )

    order_id = OrderId(uuid.uuid4())
    portfolio_id = PortfolioId(1)
    result = manager.stamp_venue_order_id(order_id, "venue-123", portfolio_id)

    assert result is True
    assert storage.updated is True
    assert read_model.dropped == [(portfolio_id, order_id)]


def test_stamp_venue_order_id_no_readmodel_is_safe() -> None:
    """Without an injected read-model the ack path stamps but skips the drop (no crash)."""
    import logging

    from itrader.order_handler.order_manager import OrderManager

    storage = _FakeStorage(_FakeOrder())
    manager = OrderManager(storage, logging.getLogger("test"))  # type: ignore[arg-type]

    order_id = OrderId(uuid.uuid4())
    result = manager.stamp_venue_order_id(order_id, "venue-123", PortfolioId(1))
    assert result is True
    assert storage.updated is True


def test_drop_pending_uses_string_key_edge(
    fake_venue_connector: FakeLiveConnector,
) -> None:
    """``drop_pending`` pops with ``str(order_id)`` — matching the ``reserve`` write key."""
    account = VenueAccount(fake_venue_connector)
    account.snapshot()

    order_id = OrderId(uuid.uuid4())
    account.reserve(order_id, to_money(Decimal("250")))
    assert account._pending == {str(order_id): Decimal("250")}

    account.drop_pending(order_id)
    assert account._pending == {}

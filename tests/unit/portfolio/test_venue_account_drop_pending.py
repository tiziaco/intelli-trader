"""D-15 / D-24 unit tests — the ``_pending`` overlay drop is gated per market type.

D-15 drops the local ``_pending`` overlay on the venue ORDER-ACK
(``VenueAccount.drop_pending``), routed through the existing ``PortfolioReadModel``
seam the order domain already uses for reserve/release and getattr-guarded so
paper/simulated accounts are a clean skip.

D-24 / CR-01 (gap remediation): the drop-on-ack is only correct on a cash channel
that actually nets the venue-side hold into ``_venue_balance`` (a stream-refreshed
margin/swap leaf). On the WIRED single-channel **spot** leaf
(``market_type='spot'``, ``live_trading_system.py:471``) ``_write_balance_stream``
is positions-only and ``_venue_balance`` is re-baselined solely by ``snapshot()`` —
so the ``_pending`` overlay is the SOLE tracker of a resting order's cash hold for
its entire life. Dropping it on ack there snaps ``available_balance`` back to the
full settled balance while the order is still open on the venue — a buying-power
OVER-statement that would admit a second order against already-committed cash. D-24
gates ``drop_pending`` to a no-op on the spot leaf (overlay held until terminal
``release``); the derivative leaf keeps the drop-on-ack (D-15 stays dormant-valid).

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
    """D-15 (derivative control arm): the ORDER-ACK drops the ``_pending`` overlay.

    On the ``derivative`` leaf (the default ``market_type``) the venue cash channel
    nets the hold into ``_venue_balance``, so dropping the local overlay on ack
    removes a genuine double-count and restores the settled available. This is the
    control arm for D-24 — it proves ``drop_pending`` is GATED per market type, not
    blanket-disabled: the derivative drop must still fire.
    """
    account = VenueAccount(fake_venue_connector)  # market_type defaults to 'derivative'
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


def _spot_account(connector: FakeLiveConnector) -> VenueAccount:
    """A snapshotted single-channel spot ``VenueAccount`` (the WIRED leaf, D-24).

    Mirrors the ``live_trading_system.py:471`` construction: ``market_type='spot'``
    with a wired ``symbol`` so the balance-derived position channel is configured.
    The canned REST snapshot carries ``total[USDT] == 78999.79`` (settled quote
    balance) and ``total[BTC] == 0.5`` (the spot holding derived from the base leg).
    """
    account = VenueAccount(
        connector, quote_currency="USDT", market_type="spot", symbol="BTC/USDT"
    )
    account.snapshot()  # settled available == 78999.79
    return account


def test_spot_ack_holds_pending_overlay(
    fake_venue_connector: FakeLiveConnector,
) -> None:
    """D-24 / CR-01: on the spot leaf the ack does NOT drop the overlay (over-statement).

    RED on the pre-fix unconditional ``drop_pending``: dropping the overlay on ack
    snaps ``available_balance`` back to the full settled balance (78999.79) while the
    order is still open on the venue — the buying-power OVER-statement CR-01 flags,
    because on the single-channel spot leaf ``_venue_balance`` is never refreshed to
    net the hold, so the overlay is the SOLE cash-hold tracker. GREEN: the overlay is
    HELD, available stays reduced by the reservation until terminal ``release``.
    """
    account = _spot_account(fake_venue_connector)

    order_id = OrderId(uuid.uuid4())
    account.reserve(order_id, Decimal("1000"))
    assert account.available_balance == Decimal("77999.79")

    # ORDER-ACK arrives. On the single-channel spot leaf this MUST be a no-op — the
    # hold is not reflected anywhere else, so the overlay is held until terminal release.
    account.drop_pending(order_id)

    # Over-statement guard: available is STILL reduced by the reservation (order open).
    assert str(order_id) in account._pending
    assert account.available_balance == Decimal("77999.79")
    # The ledger is untouched — the settled balance itself is unchanged.
    assert account.balance == Decimal("78999.79")


def test_spot_terminal_release_still_pops_overlay(
    fake_venue_connector: FakeLiveConnector,
) -> None:
    """D-24: terminal ``release`` still clears the spot overlay (the hold is never leaked).

    The ack is gated to a no-op on spot, but the terminal fill/cancel ``release`` path
    is UNCHANGED — it pops the overlay unconditionally, restoring settled available.
    Proves the spot hold is released at terminal, not leaked forever.
    """
    account = _spot_account(fake_venue_connector)

    order_id = OrderId(uuid.uuid4())
    account.reserve(order_id, Decimal("1000"))
    account.drop_pending(order_id)  # ack — no-op on spot, overlay held
    assert account.available_balance == Decimal("77999.79")

    account.release(order_id)  # terminal — pops on BOTH leaves
    assert str(order_id) not in account._pending
    assert account.available_balance == Decimal("78999.79")


def test_derivative_terminal_release_still_pops_overlay(
    fake_venue_connector: FakeLiveConnector,
) -> None:
    """D-24: terminal ``release`` still pops on the derivative leaf too (both leaves).

    Even though the derivative ack already dropped the overlay, a terminal ``release``
    on a still-held reservation (e.g. cancel before ack) remains an unconditional pop.
    """
    account = VenueAccount(fake_venue_connector)  # derivative
    account.snapshot()

    order_id = OrderId(uuid.uuid4())
    account.reserve(order_id, Decimal("1000"))
    assert account.available_balance == Decimal("77999.79")

    account.release(order_id)
    assert str(order_id) not in account._pending
    assert account.available_balance == Decimal("78999.79")

"""
ReconcileManager EXPIRED arm + D-09 idempotency LANDMINE (LIFE-01, Plan 06-03).

The EXPIRED arm is the parallel peer of the CANCELLED arm: a returning
``FillEvent(EXPIRED)`` transitions the mirror to EXPIRED and releases the
reservation in the byte-identical ``try``/``finally``/``should_release``
skeleton (NO custom guard added — the skeleton stays unchanged).

Two behaviors are pinned:
1. A ``FillEvent(EXPIRED)`` for a still-PENDING mirror order transitions it to
   EXPIRED and releases the reservation exactly once.
2. D-09 LANDMINE — a ``FillEvent(EXPIRED)`` for an ALREADY-EXPIRED mirror is a
   no-op: ``order.expire_order`` returns False (``add_state_change`` rejects the
   EXPIRED->EXPIRED transition via ``VALID_ORDER_TRANSITIONS[EXPIRED] == []``)
   so there is NO exception and NO invalid-transition raise; the terminal
   release still runs but a second release pops nothing (idempotent — no
   double-release error).

Drives ``on_fill`` against the same lightweight fakes as
``test_reconcile_manager.py`` (a fake storage, a recording ``portfolio_handler``,
a fake order, a fake fill) so the assertions isolate the control flow. Folder-
derived ``unit`` marker (no decorator).
"""

from decimal import Decimal
from unittest.mock import Mock

from itrader.order_handler.reconcile.reconcile_manager import ReconcileManager
from itrader.core.enums import FillStatus, OrderStatus


# --- fakes ------------------------------------------------------------------


class _FakeOrder:
    """Minimal order mirror with a realistic ``expire_order`` idempotency.

    ``expire_order`` mirrors the real ``Order`` contract: it transitions
    PENDING -> EXPIRED returning True, and an already-EXPIRED order returns
    False with NO state change and NO raise (``add_state_change`` return-False
    on the invalid EXPIRED->EXPIRED transition — VALID_ORDER_TRANSITIONS[EXPIRED]
    == []).
    """

    def __init__(self, order_id="O-1", portfolio_id="P-1", status=OrderStatus.PENDING):
        self.id = order_id
        self.portfolio_id = portfolio_id
        self.status = status
        self.child_order_ids = []
        self.filled_quantity = Decimal("0")
        self.expire_calls = 0
        self.expire_results = []

    def expire_order(self, reason="order expired"):
        self.expire_calls += 1
        if self.status == OrderStatus.EXPIRED:
            # EXPIRED -> EXPIRED is an invalid transition: add_state_change
            # returns False (no raise). Idempotency is free.
            self.expire_results.append(False)
            return False
        self.status = OrderStatus.EXPIRED
        self.expire_results.append(True)
        return True


class _FakeStorage:
    """Returns a single fixed order and records update_order calls."""

    def __init__(self, order):
        self._order = order
        self.update_calls = 0

    def get_order_by_id(self, order_id, portfolio_id=None):
        return self._order

    def update_order(self, order):
        self.update_calls += 1
        return True


class _FakeBrackets:
    """consume() returns None — no pending bracket (no fill-anchored children)."""

    def consume(self, order_id):
        return None


class _RecordingPortfolio:
    """Records release() calls; release is idempotent (a re-release pops nothing)."""

    def __init__(self):
        self.release_calls = []

    def release(self, portfolio_id, order_id):
        # Idempotent in the real CashManager: a second release for the same
        # order pops nothing and silently no-ops (it never raises).
        self.release_calls.append((portfolio_id, order_id))


class _FakeFill:
    """Minimal fill carrying only the attributes on_fill reads."""

    def __init__(self, status, order_id="O-1", portfolio_id="P-1"):
        self.status = status
        self.order_id = order_id
        self.portfolio_id = portfolio_id
        self.quantity = Decimal("1")
        self.price = Decimal("100")
        self.time = None


def _make_manager(order, portfolio, storage=None):
    return ReconcileManager(
        order_storage=storage if storage is not None else _FakeStorage(order),
        logger=Mock(),
        portfolio_handler=portfolio,
        brackets=_FakeBrackets(),
        bracket_manager=Mock(),
        cancel_order=Mock(),
    )


# --- EXPIRED arm: PENDING -> EXPIRED, releases exactly once ------------------


def test_expired_transitions_pending_mirror_and_releases_once():
    """A FillEvent(EXPIRED) for a still-PENDING mirror transitions it to EXPIRED
    and releases the reservation exactly once."""
    order = _FakeOrder(status=OrderStatus.PENDING)
    portfolio = _RecordingPortfolio()
    manager = _make_manager(order, portfolio)

    out = manager.on_fill(_FakeFill(FillStatus.EXPIRED))

    assert out == []
    assert order.expire_calls == 1
    assert order.expire_results == [True]
    assert order.status == OrderStatus.EXPIRED
    assert portfolio.release_calls == [(order.portfolio_id, order.id)]


# --- D-09 LANDMINE: already-EXPIRED returning fill is a no-op -----------------


def test_expired_idempotent_on_already_expired_mirror():
    """D-09 LANDMINE: a FillEvent(EXPIRED) for an ALREADY-EXPIRED mirror is a
    no-op — expire_order returns False (no transition error, no invalid-
    transition raise) and the second release pops nothing (no double-release
    error). This proves idempotency is FREE via add_state_change return-False
    (VALID_ORDER_TRANSITIONS[EXPIRED] == []) with NO custom guard."""
    # The order was already locally EXPIRED (e.g. by the run-end sweep) before
    # the exchange's FillEvent(EXPIRED) returns to reconcile.
    order = _FakeOrder(status=OrderStatus.EXPIRED)
    portfolio = _RecordingPortfolio()
    manager = _make_manager(order, portfolio)

    # No exception, no invalid-transition raise.
    out = manager.on_fill(_FakeFill(FillStatus.EXPIRED))

    assert out == []
    # expire_order was called and returned False (the already-EXPIRED no-op).
    assert order.expire_calls == 1
    assert order.expire_results == [False]
    # Status unchanged — stays EXPIRED.
    assert order.status == OrderStatus.EXPIRED
    # The terminal release still ran (idempotent — a second release for the
    # same already-released order pops nothing and never raises).
    assert portfolio.release_calls == [(order.portfolio_id, order.id)]

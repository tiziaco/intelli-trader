"""
Branch-coverage safety net for ``ReconcileManager.on_fill`` (RECON-01, Plan 05-03).

These tests pin the two load-bearing exception-safety branches BEFORE the
clarity refactor (Task 2) so the extract cannot silently regress them:

1. WR-04 — a terminal fill whose reconciliation body RAISES still RELEASES the
   reservation AND propagates the ORIGINAL body exception (never masked by a
   release failure; release runs in the ``finally``).
2. T-05-10 — an unknown / non-terminal ``FillStatus`` early-returns and does NOT
   release: ``should_release`` stays ``False`` so the reservation is
   intentionally HELD.

Plus the three happy-path terminal transitions release EXACTLY ONCE
(EXECUTED -> FILLED, CANCELLED -> CANCELLED, REFUSED -> REJECTED — the
idempotent terminal-release invariant, D-06).

The tests drive ``on_fill`` against lightweight fakes (a fake storage, a fake
``portfolio_handler`` recording ``release`` calls, a fake order, and a fake
fill) so the assertions isolate the ``should_release`` / ``try`` / ``finally``
control flow from the full Order/FillEvent construction machinery. Folder-derived
``unit`` marker (no decorator).
"""

from decimal import Decimal
from unittest.mock import Mock

import pytest

from itrader.order_handler.reconcile.reconcile_manager import ReconcileManager
from itrader.core.enums import FillStatus


# --- fakes ------------------------------------------------------------------


class _FakeOrder:
    """Minimal order mirror exposing only what on_fill touches."""

    def __init__(self, order_id="O-1", portfolio_id="P-1"):
        self.id = order_id
        self.portfolio_id = portfolio_id
        self.child_order_ids = []
        self.filled_quantity = Decimal("0")
        self.add_fill_calls = 0
        self.cancel_calls = 0
        self.reject_calls = 0

    def add_fill(self, quantity, price, time, reason="exchange fill"):
        self.add_fill_calls += 1
        self.filled_quantity += quantity
        return True

    def cancel_order(self, reason="exchange cancellation"):
        self.cancel_calls += 1
        return True

    def reject_order(self, reason):
        self.reject_calls += 1
        return True


class _FakeStorage:
    """Returns a single fixed order and records update_order calls.

    ``update_order`` runs AFTER the ``should_release = True`` arm point inside
    ``on_fill``, so injecting a raise here exercises the WR-04 contract: a body
    that raises AFTER the terminal status was set must still release.
    """

    def __init__(self, order, update_raises=None):
        self._order = order
        self.update_calls = 0
        self._update_raises = update_raises

    def get_order_by_id(self, order_id, portfolio_id=None):
        return self._order

    def update_order(self, order):
        self.update_calls += 1
        if self._update_raises is not None:
            raise self._update_raises
        return True


class _FakeBrackets:
    """consume() returns None — no pending bracket (no fill-anchored children)."""

    def consume(self, order_id):
        return None


class _RecordingPortfolio:
    """Records release() calls; optionally raises to test the WR-03 gate."""

    def __init__(self, release_raises=None):
        self.release_calls = []
        self._release_raises = release_raises

    def release(self, portfolio_id, order_id):
        self.release_calls.append((portfolio_id, order_id))
        if self._release_raises is not None:
            raise self._release_raises


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
    """Wire a ReconcileManager around the fakes (bracket_manager/cancel unused)."""
    return ReconcileManager(
        order_storage=storage if storage is not None else _FakeStorage(order),
        logger=Mock(),
        portfolio_handler=portfolio,
        brackets=_FakeBrackets(),
        bracket_manager=Mock(),
        cancel_order=Mock(),
    )


# --- WR-04: body raises -> still releases, original exception propagates -----


def test_body_raise_still_releases_and_propagates_original_exception():
    """A terminal fill whose body RAISES *after the terminal status is set*
    still RELEASES (finally) and the ORIGINAL body exception propagates
    unmasked (WR-04 / T-05-09).

    The raise is injected at ``update_order`` — which runs AFTER the
    ``should_release = True`` arm point — exactly the window WR-04 protects:
    the order has already reached a terminal status, so the reservation MUST
    be released even though the body then raised.
    """
    order = _FakeOrder()
    original = ValueError("reconciliation body blew up post-arm")
    storage = _FakeStorage(order, update_raises=original)
    portfolio = _RecordingPortfolio()
    manager = _make_manager(order, portfolio, storage=storage)

    with pytest.raises(ValueError) as excinfo:
        manager.on_fill(_FakeFill(FillStatus.EXECUTED))

    # The ORIGINAL body exception propagates (not masked).
    assert excinfo.value is original
    # The reservation was released in the finally despite the post-arm raise.
    assert portfolio.release_calls == [(order.portfolio_id, order.id)]


def test_body_raise_then_release_failure_does_not_mask_original():
    """If the body raises (post-arm) AND the release also raises, the ORIGINAL
    body exception is the one that propagates — the release failure is only
    logged (WR-03: never mask the original)."""
    order = _FakeOrder()
    original = ValueError("body exception post-arm")
    storage = _FakeStorage(order, update_raises=original)
    portfolio = _RecordingPortfolio(release_raises=RuntimeError("release blew up"))
    manager = _make_manager(order, portfolio, storage=storage)

    with pytest.raises(ValueError) as excinfo:
        manager.on_fill(_FakeFill(FillStatus.EXECUTED))

    assert excinfo.value is original
    # Release was still ATTEMPTED in the finally.
    assert portfolio.release_calls == [(order.portfolio_id, order.id)]


# --- T-05-10: unknown / non-terminal status HOLDS the reservation -----------


def test_unknown_status_holds_reservation_and_does_not_release():
    """An unknown / non-terminal FillStatus early-returns and does NOT release:
    should_release stays False, the reservation is intentionally HELD."""
    order = _FakeOrder()
    portfolio = _RecordingPortfolio()
    manager = _make_manager(order, portfolio)

    # A sentinel status that is none of EXECUTED/CANCELLED/REFUSED -> else arm.
    out = manager.on_fill(_FakeFill(status=object()))

    assert out == []
    # No release: the reservation is HELD (the non-terminal path).
    assert portfolio.release_calls == []
    # No terminal transition was applied either.
    assert order.cancel_calls == 0
    assert order.reject_calls == 0


# --- terminal transitions release EXACTLY ONCE ------------------------------


def test_executed_releases_exactly_once():
    """EXECUTED -> FILLED reconciliation releases the reservation exactly once."""
    order = _FakeOrder()
    portfolio = _RecordingPortfolio()
    manager = _make_manager(order, portfolio)

    manager.on_fill(_FakeFill(FillStatus.EXECUTED))

    assert order.add_fill_calls == 1
    assert portfolio.release_calls == [(order.portfolio_id, order.id)]


def test_cancelled_releases_exactly_once():
    """CANCELLED -> CANCELLED reconciliation releases the reservation exactly once."""
    order = _FakeOrder()
    portfolio = _RecordingPortfolio()
    manager = _make_manager(order, portfolio)

    manager.on_fill(_FakeFill(FillStatus.CANCELLED))

    assert order.cancel_calls == 1
    assert portfolio.release_calls == [(order.portfolio_id, order.id)]


def test_refused_releases_exactly_once():
    """REFUSED -> REJECTED reconciliation releases the reservation exactly once."""
    order = _FakeOrder()
    portfolio = _RecordingPortfolio()
    manager = _make_manager(order, portfolio)

    manager.on_fill(_FakeFill(FillStatus.REFUSED))

    assert order.reject_calls == 1
    assert portfolio.release_calls == [(order.portfolio_id, order.id)]

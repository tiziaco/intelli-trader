"""CF-7 typed fail-loud guard + ReconciliationCoordinator startup sequence (07-02, SAFE-05).

Two concerns pinned here:

* **CF-7 (Task 1)** — ``VenueReconciler._relink_bracket`` must raise a typed
  ``ReconciliationError`` (not a silent ``KeyError``/naked coercion) when a matched venue
  resting-order payload carries no coercible ``'id'``. The error message references ONLY
  the leg id, never the full venue payload (ASVS V7 / T-07-09). Tests carry ``cf7`` in
  their name so ``pytest -k cf7`` selects exactly this arm.
* **Coordinator (Task 2)** — ``ReconciliationCoordinator.run_startup_reconcile`` owns the
  startup ``rehydrate -> venue-reconcile (venue-truth accounts ONLY) -> baseline-guard``
  sequence, keyed on account KIND (a venue-truth discriminator), NOT on ``exchange=='okx'``.
  A compute (non-venue-truth) account NEVER constructs a ``VenueReconciler``; a venue-truth
  account with an unexplained base-asset residual latches HALT via the injected callable with
  the FIXED literal ``HaltReason.BASELINE_RESIDUAL.value`` (never ``str(exc)``, V7 / T-07-01).

Credential-free synchronous doubles (no event loop, no async warnings under
``filterwarnings=["error"]``). 4-space indentation (matches ``tests/unit/*`` + the
``reconcile/`` production siblings); NO ``__init__.py`` in this dir (auto-memory:
same-named-package collision hazard).
"""

import queue
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional

import pytest
import uuid_utils.compat as uc

from itrader.core.enums import OrderStatus, OrderType, Side
from itrader.core.exceptions import ReconciliationError
from itrader.core.exceptions.base import ITraderError
from itrader.core.ids import PortfolioId, StrategyId
from itrader.order_handler.order import Order
from itrader.portfolio_handler.reconcile.venue_reconciler import VenueReconciler

_SYMBOL = "BTC/USDC"
_NOW = datetime(2026, 7, 1, tzinfo=timezone.utc)


# ---------------------------------------------------------------- shared doubles


class _SyncConnector:
    """Minimal ``LiveConnector`` double: ``call`` returns its (already-computed) arg."""

    def __init__(self, client: Any = None) -> None:
        self.client = client

    def call(self, value: Any) -> Any:
        return value


class _FakeStore:
    """Minimal rehydratable store double exposing the reconcile working set."""

    def __init__(self, orders: Optional[List[Order]] = None) -> None:
        self._orders = orders if orders is not None else []
        self.updated: List[Order] = []

    def rehydrate(self) -> None:
        pass

    def get_active_orders(self, _portfolio_id: Any) -> List[Order]:
        return [o for o in self._orders if o.is_active]

    def get_order_by_id(self, order_id: Any, *_args: Any) -> Optional[Order]:
        for order in self._orders:
            if order.id == order_id:
                return order
        return None

    def update_order(self, order: Order) -> bool:
        self.updated.append(order)
        return True


def _make_order(**overrides: Any) -> Order:
    """Build an active BTC/USDC ``Order`` (overridable per field)."""
    base: Dict[str, Any] = dict(
        time=_NOW,
        type=OrderType.LIMIT,
        status=OrderStatus.PENDING,
        ticker=_SYMBOL,
        action=Side.BUY,
        price=Decimal("42000"),
        quantity=Decimal("1.0"),
        exchange="okx",
        strategy_id=StrategyId(uc.uuid7()),
        portfolio_id=PortfolioId(uc.uuid7()),
    )
    base.update(overrides)
    return Order(**base)


def _relink_reconciler(orders: List[Order]) -> VenueReconciler:
    """A VenueReconciler over synchronous fakes for the _relink_bracket CF-7 path."""
    return VenueReconciler(
        store=_FakeStore(orders),
        venue_account=None,  # type: ignore[arg-type]
        connector=_SyncConnector(),
        global_queue=queue.Queue(),
        halt_signal=lambda _reason: None,
    )


# ================================================================ Task 1: CF-7 guard


def test_cf7_reconciliation_error_is_itrader_error():
    """ReconciliationError subclasses the ITraderError root (typed, catchable domain error)."""
    assert issubclass(ReconciliationError, ITraderError)


def test_cf7_relink_bracket_raises_on_missing_id():
    """A matched venue resting payload with no 'id' fails loud with ReconciliationError."""
    child = _make_order()
    parent = _make_order(child_order_ids=[child.id])
    reconciler = _relink_reconciler([parent, child])
    # Resting order matches the leg on symbol+side+price+qty but carries NO 'id' key —
    # the fallback attribute match returns it, and the CF-7 guard must trip.
    resting = [{"symbol": _SYMBOL, "side": "buy", "price": 42000, "amount": 1.0}]

    with pytest.raises(ReconciliationError) as exc_info:
        reconciler._relink_bracket(parent, resting, {})

    # The message references the leg id, NEVER the full venue payload (V7 scrub).
    message = str(exc_info.value)
    assert str(child.id) in message
    assert "amount" not in message and "price" not in message


def test_cf7_relink_bracket_succeeds_with_id():
    """A matched resting payload WITH an 'id' re-links cleanly (no false positive)."""
    child = _make_order()
    parent = _make_order(child_order_ids=[child.id])
    reconciler = _relink_reconciler([parent, child])
    resting = [{"id": "venue-123", "symbol": _SYMBOL, "side": "buy",
                "price": 42000, "amount": 1.0}]

    assert reconciler._relink_bracket(parent, resting, {}) is True
    assert child.venue_order_id == "venue-123"

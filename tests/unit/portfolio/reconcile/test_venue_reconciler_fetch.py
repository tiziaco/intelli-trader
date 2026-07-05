"""D-09 / V17-10 — VenueReconciler fill-fetch shape + F/U-13 window loud-log (05.2-02).

These unit tests pin the CONF-B-corrected venue-trade fetch shape (SUPERSEDES the
provisional ``params={'paginate':True}`` text): the reconciler MUST call the ccxt client's
``fetch_my_trades`` per working-set symbol with ``since = the oldest active order's business
time (epoch-ms)`` and an explicit ``limit=100`` — and NEVER ``params={'paginate':True}``
(OKX rejects it with sCode 51000 'Parameter limit error', CONF-B online run 2026-07-05).

Task 2 adds the F/U-13 rehydrate-window guard: when the derived ``since`` predates the
venue's ~3-month ``/trade/fills-history`` window (a named 90-day constant) the reconciler
emits a WARNING naming the symbol so an operator sees the incomplete catch-up; an in-window
``since`` is silent.

Observable behavior only (the actual ``fetch_my_trades`` call args + a caplog WARNING) — not
storage shape, so a later CONF posture flip cannot invalidate the suite. Credential-free
synchronous doubles (no event loop, no async warnings under ``filterwarnings=["error"]``).

4-space indentation (matches ``tests/unit/*`` + the ``reconcile/`` production siblings); NO
``__init__.py`` in this dir (auto-memory: same-named-package collision hazard).
"""

import logging
import queue
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

import uuid_utils.compat as uc

from itrader.core.enums import OrderStatus, OrderType, Side
from itrader.core.ids import PortfolioId, StrategyId
from itrader.order_handler.order import Order
from itrader.portfolio_handler.reconcile.venue_reconciler import VenueReconciler

# A business time (never wall clock) well INSIDE the venue's ~3-month window is derived
# relative to real now so the in-window assertion is stable regardless of the run date.
_RECENT = datetime.now(timezone.utc) - timedelta(days=1)
# A business time far OUTSIDE the ~3-month window (F/U-13 out-of-window case).
_ANCIENT = datetime(2020, 1, 1, tzinfo=timezone.utc)

_SYMBOL = "BTC/USDT"


class _RecordingClient:
    """Fake ccxt client recording every ``fetch_my_trades`` call (args + kwargs).

    Synchronous by design: the paired ``_SyncConnector.call`` returns its argument
    verbatim, so the client methods return their canned list directly (no coroutine, no
    event loop — nothing to leak a ResourceWarning under the strict filter).
    """

    def __init__(
        self,
        trades: Optional[List[Dict[str, Any]]] = None,
        open_orders: Optional[List[Dict[str, Any]]] = None,
    ) -> None:
        self._trades = trades if trades is not None else []
        self._open_orders = open_orders if open_orders is not None else []
        self.trades_calls: List[Tuple[tuple, dict]] = []
        self.open_orders_calls: List[Tuple[tuple, dict]] = []

    def fetch_my_trades(self, *args: Any, **kwargs: Any) -> List[Dict[str, Any]]:
        self.trades_calls.append((args, kwargs))
        return self._trades

    def fetch_open_orders(self, *args: Any, **kwargs: Any) -> List[Dict[str, Any]]:
        self.open_orders_calls.append((args, kwargs))
        return self._open_orders


class _SyncConnector:
    """Minimal ``LiveConnector`` double: ``call`` returns its (already-computed) arg."""

    def __init__(self, client: _RecordingClient) -> None:
        self.client = client

    def call(self, value: Any) -> Any:
        return value


class _FakeStore:
    """Minimal rehydratable store double exposing the reconcile working set."""

    def __init__(self, orders: List[Order]) -> None:
        self._orders = orders

    def rehydrate(self) -> None:
        pass

    def get_active_orders(self, _portfolio_id: Any) -> List[Order]:
        return [o for o in self._orders if o.is_active]

    def get_order_by_id(self, order_id: Any, *_args: Any) -> Optional[Order]:
        for order in self._orders:
            if order.id == order_id:
                return order
        return None

    def update_order(self, _order: Order) -> bool:
        return True


class _FakeVenueAccount:
    """Minimal ``VenueAccount`` double: no-op snapshot + a canned positions map."""

    def __init__(self, positions: Optional[Dict[str, Decimal]] = None) -> None:
        self._positions = positions if positions is not None else {}

    def snapshot(self) -> None:
        pass

    @property
    def positions(self) -> Dict[str, Decimal]:
        return self._positions


def _make_order(**overrides: Any) -> Order:
    """Build an active BTC/USDT ``Order`` (overridable per field)."""
    base: Dict[str, Any] = dict(
        time=_RECENT,
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


def _build_reconciler(orders, client, positions=None):
    """Wire a VenueReconciler over the synchronous fakes; return (reconciler, halt_calls)."""
    halt_calls: List[str] = []
    reconciler = VenueReconciler(
        store=_FakeStore(orders),
        venue_account=_FakeVenueAccount(positions),
        connector=_SyncConnector(client),
        global_queue=queue.Queue(),
        halt_signal=halt_calls.append,
    )
    return reconciler, halt_calls


def _trades_call_symbol(args: tuple, kwargs: dict) -> Any:
    """The symbol passed to fetch_my_trades, positionally or by keyword."""
    return args[0] if args else kwargs.get("symbol")


# ---------------------------------------------------------------- Task 1: fetch shape


def test_fetch_my_trades_called_with_symbol_since_and_limit_100():
    """reconcile() calls fetch_my_trades(symbol, since=oldest-active-ms, limit=100)."""
    order = _make_order(time=_RECENT)
    client = _RecordingClient()
    reconciler, _ = _build_reconciler([order], client)

    reconciler.reconcile()

    assert len(client.trades_calls) == 1
    args, kwargs = client.trades_calls[0]
    assert _trades_call_symbol(args, kwargs) == _SYMBOL
    assert kwargs.get("since") == int(_RECENT.timestamp() * 1000)
    assert kwargs.get("limit") == 100


def test_fetch_my_trades_never_passes_paginate():
    """CONF-B: params={'paginate':True} trips OKX sCode 51000 — it must NEVER be sent."""
    order = _make_order(time=_RECENT)
    client = _RecordingClient()
    reconciler, _ = _build_reconciler([order], client)

    reconciler.reconcile()

    _args, kwargs = client.trades_calls[0]
    assert "params" not in kwargs
    assert "paginate" not in kwargs


def test_fetch_open_orders_keeps_its_no_arg_form():
    """The fetch_open_orders read is unaffected — still called with no args."""
    order = _make_order(time=_RECENT)
    client = _RecordingClient()
    reconciler, _ = _build_reconciler([order], client)

    reconciler.reconcile()

    assert client.open_orders_calls == [((), {})]


# ------------------------------------------------ Task 2: F/U-13 window loud-log

# A distinctive substring the window-bound WARNING must carry so the no-warn case can
# assert its ABSENCE without coupling to the full message text.
_WINDOW_WARN_MARKER = "fills-history"


def test_warns_when_since_predates_fills_history_window(caplog):
    """since older than the ~3-month /trade/fills-history window → WARNING naming the symbol."""
    order = _make_order(time=_ANCIENT)   # 2020 — far outside the ~90-day window
    client = _RecordingClient()
    reconciler, _ = _build_reconciler([order], client)

    with caplog.at_level(logging.WARNING):
        reconciler.reconcile()

    window_warnings = [
        r for r in caplog.records
        if r.levelno == logging.WARNING and _WINDOW_WARN_MARKER in r.getMessage()
    ]
    assert window_warnings, "expected a fills-history window WARNING for an out-of-window since"
    assert _SYMBOL in caplog.text   # the warning names the uncovered symbol


def test_no_warn_when_since_within_window(caplog):
    """since inside the ~3-month window → no window-bound warning (silent catch-up)."""
    order = _make_order(time=_RECENT)   # now − 1 day — well inside the window
    client = _RecordingClient()
    reconciler, _ = _build_reconciler([order], client)

    with caplog.at_level(logging.WARNING):
        reconciler.reconcile()

    assert _WINDOW_WARN_MARKER not in caplog.text


def test_window_bound_is_a_named_constant():
    """The venue window bound is a named module constant, not a magic literal."""
    from itrader.portfolio_handler.reconcile import venue_reconciler as vr

    assert vr._FILLS_HISTORY_WINDOW_DAYS == 90

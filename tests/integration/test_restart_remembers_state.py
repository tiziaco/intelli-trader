"""D-07 / D-08 — restart remembers portfolio state + a durable, collision-safe dedup ledger.

Two observable behaviours proven OFFLINE (Dockerless — no testcontainers, no OKX):

* **Restart remembers positions + cash (D-07 / V17-05).** A FRESH ``Portfolio`` whose
  ``state_storage`` is the shared durable store rehydrates its open positions into the
  live ``PositionManager`` read surface AND restores the persisted cash scalar into the
  ``Account`` — the engine remembers its state. RED before Task 1: the restore path was
  unbuilt (``rehydrate()`` read the account-state scalars back and DISCARDED them; there
  was no ``Account.restore_cash``), so a fresh handler reported its construction-time
  initial cash, not the persisted balance.

* **Cross-restart dedup ledger (D-07 + D-08 Layer 2 / V17-12).** A FRESH
  ``PortfolioHandler`` seeds ``_settled_venue_trade_ids`` from the durable
  ``transactions.venue_trade_id`` on ``rehydrate()``, keyed ``f"{ticker}:{venue_trade_id}"``.
  A re-delivered venue trade after the restart is a no-op; the SAME numeric trade id on a
  DIFFERENT symbol still settles (collision-safe).

The "durable store" is an in-memory DOUBLE (``_DurableStoreDouble``) that mirrors the
``CachedSqlPortfolioStateStorage`` contract used by rehydrate — it splits DURABLE
(persisted-before-restart) state from the LIVE working set: a fresh instance's working set
is EMPTY (the fresh handler remembers nothing) until ``rehydrate(account)`` loads the
durable positions into the working set + restores the durable cash into the account.
"restart" == constructing a fresh ``Portfolio`` / ``PortfolioHandler`` sharing the same
backing store object. Offline seam pattern modelled on ``test_halt_latch.py``.

4-space indentation (matches ``tests/integration/*``); NO ``__init__.py`` in this dir
(auto-memory: package-collision hazard). Folder-derived ``integration`` marker.
"""

import queue
from contextlib import contextmanager
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, Iterable, Iterator, List, Optional
from unittest.mock import Mock

import pytest
import uuid_utils.compat as uc

from itrader.core.enums import OrderStatus, OrderType, Side, FillStatus, TransactionType
from itrader.core.ids import PortfolioId, TransactionId, OrderId, StrategyId
from itrader.events_handler.events import FillEvent
from itrader.order_handler.order import Order
from itrader.order_handler.reconcile.reconcile_manager import ReconcileManager
from itrader.portfolio_handler.portfolio import Portfolio
from itrader.portfolio_handler.portfolio_handler import PortfolioHandler
from itrader.portfolio_handler.position.position import Position
from itrader.portfolio_handler.storage.in_memory_storage import (
    InMemoryPortfolioStateStorage,
)
from itrader.portfolio_handler.transaction.transaction import Transaction

# A business time (never wall clock) reused so derived timestamps are deterministic.
_BT = datetime(2024, 1, 1, tzinfo=timezone.utc)


class _DurableStoreDouble(InMemoryPortfolioStateStorage):
    """Offline durable-store stand-in for ``CachedSqlPortfolioStateStorage`` (D-07).

    Splits DURABLE state (positions/cash/transactions persisted before the restart)
    from the LIVE working set the managers read. On a fresh instance the working set
    (``get_positions``) is EMPTY — the fresh Portfolio remembers nothing — until
    ``rehydrate(account)`` loads the durable positions into the working set AND restores
    the durable cash scalar into the account (mirroring the real CachedSql
    ``rehydrate`` → ``account.restore_cash`` contract). Durable transactions are exposed
    through ``get_transaction_history`` so the settled-ledger seed can read them.
    """

    def __init__(
        self,
        *,
        durable_positions: Optional[Dict[str, Position]] = None,
        durable_cash: Optional[Decimal] = None,
        durable_transactions: Optional[List[Transaction]] = None,
        durable_realized_pnl: Decimal = Decimal("0"),
    ) -> None:
        super().__init__()
        self._durable_positions: Dict[str, Position] = dict(durable_positions or {})
        self._durable_cash: Optional[Decimal] = durable_cash
        # WR-03: the persisted realised-PnL accumulator scalar (defaults to zero so
        # existing callers are unchanged). Restored into the PositionManager on
        # rehydrate so a post-restart fill does not overwrite the durable value with 0.
        self._durable_realized_pnl: Decimal = durable_realized_pnl
        # Durable transactions ARE the persisted history — expose them via the
        # inherited get_transaction_history() read-through (the ledger seed reads it).
        for txn in durable_transactions or []:
            self._transaction_history.append(txn)

    def load_account_state(self) -> Optional[Dict[str, Any]]:
        """Return the persisted account-state row, or None if none was persisted."""
        if self._durable_cash is None:
            return None
        return {
            "cash_balance": self._durable_cash,
            "realized_pnl": self._durable_realized_pnl,
            "total_equity": self._durable_cash,
            "peak_equity": self._durable_cash,
            "open_positions_count": len(self._durable_positions),
            "updated_time": _BT,
        }

    def rehydrate(self, account: Any = None) -> None:
        """Load durable positions into the live working set + restore the cash scalar."""
        for ticker, position in self._durable_positions.items():
            self._positions[ticker] = position
        state = self.load_account_state()
        if account is not None and state is not None:
            account.restore_cash(state["cash_balance"])


def _buy_transaction(ticker: str, quantity: Decimal, price: Decimal,
                     portfolio_id: PortfolioId, *,
                     venue_trade_id: Optional[str] = None) -> Transaction:
    """Build a settled BUY ``Transaction`` (optionally carrying a venue trade id)."""
    return Transaction(
        time=_BT,
        type=TransactionType.BUY,
        ticker=ticker,
        price=price,
        quantity=quantity,
        commission=Decimal("0"),
        portfolio_id=portfolio_id,
        id=TransactionId(uc.uuid7()),
        fill_id=uc.uuid7(),
        venue_trade_id=venue_trade_id,
    )


def _durable_long_position(ticker: str, quantity: Decimal, price: Decimal,
                          portfolio_id: PortfolioId) -> Position:
    """Build an OPEN long ``Position`` as it would have been persisted pre-restart."""
    return Position.open_position(
        _buy_transaction(ticker, quantity, price, portfolio_id)
    )


def _rebind_storage(portfolio: Portfolio, store: Any) -> None:
    """Point a fresh Portfolio's managers at the shared durable store (restart wiring).

    Models a fresh live Portfolio whose ``state_storage`` IS the durable CachedSql live
    store: every manager seam reads/writes through the ONE shared backing store object.
    """
    portfolio.state_storage = store
    portfolio.account._storage = store
    portfolio.position_manager._storage = store
    portfolio.transaction_manager._storage = store
    portfolio.metrics_manager._storage = store


def test_restart_restores_position_and_cash_into_live_managers() -> None:
    """A fresh Portfolio sharing the durable store remembers its position + cash (D-07)."""
    portfolio_id = PortfolioId(uc.uuid7())
    saved_position = _durable_long_position(
        "BTC/USDT", Decimal("0.5"), Decimal("42000"), portfolio_id
    )
    store = _DurableStoreDouble(
        durable_positions={"BTC/USDT": saved_position},
        durable_cash=Decimal("99934.53"),
    )

    # "Restart": a FRESH Portfolio constructed at its original initial cash, sharing the
    # durable backing store. Before rehydrate it remembers nothing.
    fresh = Portfolio(name="restart_pf", exchange="simulated",
                      cash=Decimal("100000.00"), time=_BT)
    _rebind_storage(fresh, store)

    # Pre-rehydrate: the fresh handler has NOT remembered its state.
    assert fresh.position_manager.get_position("BTC/USDT") is None
    assert fresh.account.balance == Decimal("100000.00")

    # Rehydrate restores positions into the live PositionManager read surface AND the
    # persisted cash scalar into the Account (observable via the public read surface —
    # NOT via storage internals).
    fresh.state_storage.rehydrate(fresh.account)

    restored = fresh.position_manager.get_position("BTC/USDT")
    assert restored is not None
    assert restored.net_quantity == Decimal("0.5")
    assert fresh.account.balance == Decimal("99934.53")


def _handler_with_portfolio_on(store: Any, cash: Decimal = Decimal("100000")):
    """Build a fresh PortfolioHandler + one portfolio wired to the shared durable store."""
    handler = PortfolioHandler(queue.Queue())
    portfolio_id = handler.add_portfolio(name="restart_pf", exchange="simulated", cash=cash)
    portfolio = handler.get_portfolio(portfolio_id)
    _rebind_storage(portfolio, store)
    return handler, portfolio_id, portfolio


def _executed_fill(ticker: str, portfolio_id: PortfolioId, venue_trade_id: str,
                   quantity: Decimal = Decimal("0.1"),
                   price: Decimal = Decimal("42000")) -> FillEvent:
    """Build an EXECUTED venue BUY fill carrying a venue trade id (the dedup key)."""
    return FillEvent(
        time=_BT,
        status=FillStatus.EXECUTED,
        ticker=ticker,
        action=Side.BUY,
        price=price,
        quantity=quantity,
        commission=Decimal("0"),
        portfolio_id=portfolio_id,
        fill_id=uc.uuid7(),
        order_id=OrderId(uc.uuid7()),
        strategy_id=StrategyId(uc.uuid7()),
        venue_trade_id=venue_trade_id,
    )


def test_redelivered_venue_trade_after_restart_is_noop() -> None:
    """The settled-trade dedup ledger survives a restart (D-07 + D-08 Layer 2)."""
    # Durable transaction already recorded venue_trade_id "T1" for BTC/USDT pre-restart.
    seed = _buy_transaction(
        "BTC/USDT", Decimal("0.1"), Decimal("42000"), PortfolioId(uc.uuid7()),
        venue_trade_id="T1",
    )
    store = _DurableStoreDouble(durable_transactions=[seed])

    handler, portfolio_id, portfolio = _handler_with_portfolio_on(store)
    # Restart seed: the fresh handler's ledger starts EMPTY; rehydrate seeds it from the
    # durable transactions.venue_trade_id, keyed f"{ticker}:{venue_trade_id}".
    handler.rehydrate()
    assert "BTC/USDT:T1" in handler._settled_venue_trade_ids

    # Re-delivering the SAME (BTC/USDT, "T1") after the restart is a no-op — the dedup
    # ledger rehydrated, so no position is booked.
    handler.on_fill(_executed_fill("BTC/USDT", portfolio_id, "T1"))
    assert portfolio.position_manager.get_position("BTC/USDT") is None


def test_same_trade_id_different_symbol_still_settles() -> None:
    """A numeric venue tradeId collision across instruments settles (V17-12 collision-safe)."""
    seed = _buy_transaction(
        "BTC/USDT", Decimal("0.1"), Decimal("42000"), PortfolioId(uc.uuid7()),
        venue_trade_id="T1",
    )
    store = _DurableStoreDouble(durable_transactions=[seed])

    handler, portfolio_id, portfolio = _handler_with_portfolio_on(store)
    handler.rehydrate()

    # SAME numeric trade id "T1" but a DIFFERENT symbol — a distinct economic trade that
    # must settle (the dedup key is symbol-scoped, not the raw id).
    handler.on_fill(_executed_fill("ETH/USDT", portfolio_id, "T1"))
    settled = portfolio.position_manager.get_position("ETH/USDT")
    assert settled is not None
    assert settled.net_quantity == Decimal("0.1")
    # And its symbol-scoped key is now recorded.
    assert "ETH/USDT:T1" in handler._settled_venue_trade_ids


def test_restart_restores_realised_pnl_accumulator() -> None:
    """A fresh handler rehydrates the persisted realised-PnL accumulator (WR-03).

    The running ``PositionManager._realised_pnl_accumulator`` (fed only via
    ``apply_realised_increment``) is NOT one of the position/cash containers the
    working-set cache carries — it starts at ``Decimal('0.00')`` on a fresh handler.
    Before the WR-03 fix ``rehydrate()`` never re-seeded it, so after a restart
    ``total_realised_pnl`` reported 0 (dropping all pre-restart realised PnL — including
    the fully-closed positions rehydrate deliberately does not load), and the very next
    ``_persist_account_state`` write OVERWROTE the durable ``realized_pnl`` column with
    that undercounted value.

    RED (before fix): ``total_realised_pnl == Decimal('0.00')``. GREEN: the persisted
    accumulator is restored so the durable figure survives a restart.
    """
    persisted_realised = Decimal("1234.56")
    store = _DurableStoreDouble(
        durable_cash=Decimal("100000.00"),
        durable_realized_pnl=persisted_realised,
    )

    handler, portfolio_id, portfolio = _handler_with_portfolio_on(store)
    # Pre-rehydrate: a fresh handler remembers no realised PnL.
    assert portfolio.total_realised_pnl == Decimal("0.00")

    handler.rehydrate()

    # The persisted accumulator is restored at full precision (WR-03) — a subsequent
    # _persist_account_state would now write the correct realized_pnl back.
    assert portfolio.total_realised_pnl == persisted_realised


# ---------------------------------------------------------------------------
# D-19 (WR-04) — the on_fill durable persist of position (set_position) + the
# cash-scalar account-state (save_account_state) must commit in ONE transaction
# so a crash BETWEEN them can never leave the durable position one fill ahead of
# the durable cash (a torn restore, PERMANENT on the SimulatedAccount path — no
# venue heals it). Modelled offline with an atomic-transaction store double.
# ---------------------------------------------------------------------------


class _AtomicDurableStoreDouble(InMemoryPortfolioStateStorage):
    """Offline durable store modelling the D-19 single-transaction fill persist.

    Splits DURABLE (committed, restart-visible) state from the LIVE working set,
    exactly like ``_DurableStoreDouble``, but additionally models the REAL SQL
    transaction boundary that D-19 introduces:

    * ``set_position`` and ``save_account_state`` are the two durable writes on
      the fill path. Outside a ``fill_transaction`` they commit INDEPENDENTLY
      (the pre-D-19 two-commit seam) — a failure of the second leaves the first
      committed (TORN). Inside a ``fill_transaction`` they STAGE onto a pending
      buffer that is flushed atomically on a clean exit and DISCARDED on any
      exception (the D-19 single-transaction seam — both or neither).
    * ``save_account_state`` optionally raises to simulate a crash between the
      position commit and the cash upsert.

    The in-memory backtest backend exposes no ``fill_transaction`` / no
    ``save_account_state``, so the atomic seam is oracle-dark (the on_fill call
    getattr-skips it) — this double opts INTO the live behaviour under test.
    """

    def __init__(
        self,
        *,
        durable_cash: Decimal,
        fail_account_state: bool = False,
    ) -> None:
        super().__init__()
        # Committed durable state (what a restart's rehydrate reads back).
        self._committed_positions: Dict[str, Position] = {}
        self._committed_cash: Decimal = durable_cash
        self._committed_realized_pnl: Decimal = Decimal("0")
        # Staging buffer active only inside a fill_transaction (the SQL txn).
        self._in_fill_txn: bool = False
        self._staged_positions: Dict[str, Position] = {}
        self._staged_cash: Optional[Decimal] = None
        self._staged_realized: Optional[Decimal] = None
        # Inject a crash between the position commit and the cash upsert.
        self._fail_account_state: bool = fail_account_state

    @contextmanager
    def fill_transaction(self) -> Iterator[None]:
        """Stage the fill's durable writes and commit them atomically (D-19)."""
        self._in_fill_txn = True
        self._staged_positions = {}
        self._staged_cash = None
        self._staged_realized = None
        try:
            yield
        except Exception:
            # Rollback: discard everything staged in this transaction.
            self._staged_positions = {}
            self._staged_cash = None
            self._staged_realized = None
            raise
        else:
            # Commit: apply the staged writes to the durable state atomically.
            self._committed_positions.update(self._staged_positions)
            if self._staged_cash is not None:
                self._committed_cash = self._staged_cash
            if self._staged_realized is not None:
                self._committed_realized_pnl = self._staged_realized
        finally:
            self._in_fill_txn = False

    def set_position(self, ticker: str, position: Position) -> None:
        # Working set update (the managers read this) — always immediate.
        super().set_position(ticker, position)
        # Durable position write: staged inside a fill txn, else committed now
        # (the pre-D-19 independent commit that could be left torn).
        if self._in_fill_txn:
            self._staged_positions[ticker] = position
        else:
            self._committed_positions[ticker] = position

    def save_account_state(self, *, cash_balance: Decimal, realized_pnl: Decimal,
                           **_kwargs: Any) -> None:
        if self._fail_account_state:
            raise RuntimeError("injected crash before the cash-scalar upsert (D-19)")
        if self._in_fill_txn:
            self._staged_cash = cash_balance
            self._staged_realized = realized_pnl
        else:
            self._committed_cash = cash_balance
            self._committed_realized_pnl = realized_pnl

    def load_account_state(self) -> Optional[Dict[str, Any]]:
        return {
            "cash_balance": self._committed_cash,
            "realized_pnl": self._committed_realized_pnl,
            "total_equity": self._committed_cash,
            "peak_equity": self._committed_cash,
            "open_positions_count": len(self._committed_positions),
            "updated_time": _BT,
        }

    def rehydrate(self, account: Any = None) -> None:
        """Restore the COMMITTED durable state into a fresh working set.

        A restart is a new process with an EMPTY working set rebuilt from durable
        truth — so the working set is reset to the committed positions (any dirty
        working-set write from a rolled-back fill is discarded, exactly as a real
        restart drops the in-memory cache and reloads from the store).
        """
        self._positions.clear()
        for ticker, position in self._committed_positions.items():
            self._positions[ticker] = position
        state = self.load_account_state()
        if account is not None and state is not None:
            account.restore_cash(state["cash_balance"])


def test_on_fill_position_and_cash_persist_atomically_single_txn() -> None:
    """A crash between the position commit and the cash upsert must not tear (D-19).

    The fill drives the durable position write (``set_position``) then the
    cash-scalar upsert (``save_account_state``), which is injected to fail. On the
    pre-D-19 two-commit seam the position is durably committed while the cash is
    not, so a restart rehydrates a position with STALE cash (torn — position one
    fill ahead of cash). With the D-19 single-transaction persist the failed cash
    upsert rolls the position write back too, so a restart reads a CONSISTENT
    (no position, unchanged cash) pair — neither, never a torn half.

    RED (pre-fix): the fill is NOT wrapped in a single transaction, so the
    position survives the failed cash write → ``get_position`` returns the torn
    position and the assertion below fails. GREEN: on_fill wraps both writes in
    ``fill_transaction`` → the position rolls back → ``get_position`` is None.
    """
    initial_cash = Decimal("100000.00")
    store = _AtomicDurableStoreDouble(
        durable_cash=initial_cash, fail_account_state=True
    )
    handler, portfolio_id, _portfolio = _handler_with_portfolio_on(
        store, cash=initial_cash
    )

    # Drive one EXECUTED BUY fill; the cash-scalar upsert crashes mid-persist.
    fill = _executed_fill("BTC/USDT", portfolio_id, "T1")
    with pytest.raises(RuntimeError):
        handler.on_fill(fill)

    # "Restart": a fresh Portfolio sharing the same durable store.
    fresh = Portfolio(name="restart_pf", exchange="simulated",
                      cash=initial_cash, time=_BT)
    _rebind_storage(fresh, store)
    fresh.state_storage.rehydrate(fresh.account)

    # Atomic (D-19): the failed cash upsert rolled the position write back too —
    # the durable pair is consistent (no position, cash unchanged), NOT torn.
    assert fresh.position_manager.get_position("BTC/USDT") is None
    assert fresh.account.balance == initial_cash


# ---------------------------------------------------------------------------
# D-22 (WR-05) — the ORDER-mirror dedup ring must be restart-seeded SYMMETRICALLY
# with the portfolio ledger's _settled_venue_trade_ids. On a restart the
# ReconcileManager's _applied_trade_keys starts EMPTY, so a venue trade
# re-delivered AFTER the restart re-books the mirror unless the ring is seeded
# from the durable transactions.venue_trade_id history (Pitfall 8: driven FROM
# PortfolioHandler.rehydrate — ReconcileManager has no durable transaction store).
# ---------------------------------------------------------------------------


class _FixedOrderStorage:
    """Returns a single fixed order; records update_order calls (mirror moved)."""

    def __init__(self, order: Order) -> None:
        self._order = order
        self.update_calls = 0

    def get_order_by_id(self, order_id: Any, portfolio_id: Any = None) -> Order:
        return self._order

    def update_order(self, order: Order) -> bool:
        self.update_calls += 1
        return True

    def get_active_orders(self, portfolio_id: Any) -> List[Order]:
        return []


def _reconcile_manager_for(order: Order) -> ReconcileManager:
    """Wire a ReconcileManager around a real Order + a fixed storage (Mock rest)."""
    return ReconcileManager(
        order_storage=_FixedOrderStorage(order),
        logger=Mock(),
        portfolio_handler=Mock(),
        brackets=Mock(),
        bracket_manager=Mock(),
        cancel_order=Mock(),
    )


def _resting_order(ticker: str, portfolio_id: PortfolioId) -> Order:
    """A PENDING BUY LIMIT order (quantity 1.0) whose mirror a partial fill moves."""
    return Order(
        time=_BT,
        type=OrderType.LIMIT,
        status=OrderStatus.PENDING,
        ticker=ticker,
        action=Side.BUY,
        price=Decimal("42000.0"),
        quantity=Decimal("1.0"),
        exchange="okx",
        strategy_id=1,
        portfolio_id=portfolio_id,
        id=OrderId(uc.uuid7()),
    )


def _fill_for(order: Order, venue_trade_id: str,
              quantity: Decimal = Decimal("0.1")) -> FillEvent:
    """An EXECUTED partial fill for ``order`` carrying ``venue_trade_id``."""
    return FillEvent(
        time=_BT,
        status=FillStatus.EXECUTED,
        ticker=order.ticker,
        action=Side.BUY,
        price=Decimal("42000.0"),
        quantity=quantity,
        commission=Decimal("0"),
        portfolio_id=order.portfolio_id,
        fill_id=uc.uuid7(),
        order_id=order.id,
        strategy_id=order.strategy_id,
        venue_trade_id=venue_trade_id,
    )


def test_reconcile_ring_restart_seeded_redelivered_trade_is_noop() -> None:
    """The order-mirror dedup ring survives a restart, seeded from rehydrate (D-22).

    A venue trade "T1" for BTC/USDT was durably recorded pre-restart. After the
    restart the ReconcileManager's ring is EMPTY; ``PortfolioHandler.rehydrate``
    drives the SAME single ``transactions.venue_trade_id`` history pass into the
    ring via the seed sink (``ReconcileManager.seed_applied_trades``), keyed
    ``f"{ticker}:{venue_trade_id}"`` — symmetric with the portfolio arm's
    ``_settled_venue_trade_ids`` seed. A re-delivered "T1" is then a mirror no-op.

    RED (pre-fix): the ring is not restart-seeded (no ``seed_applied_trades`` seam,
    ``rehydrate`` takes no sink) so the re-delivery re-accumulates the mirror.
    GREEN: the seeded ring recognizes "BTC/USDT:T1" and the increment is ignored.
    """
    portfolio_id = PortfolioId(uc.uuid7())
    # Durable transaction recorded venue_trade_id "T1" for BTC/USDT pre-restart.
    seed = _buy_transaction(
        "BTC/USDT", Decimal("0.1"), Decimal("42000"), portfolio_id,
        venue_trade_id="T1",
    )
    store = _DurableStoreDouble(durable_transactions=[seed])
    handler, _pid, _portfolio = _handler_with_portfolio_on(store)

    # The order the re-delivered fill targets after the restart.
    order = _resting_order("BTC/USDT", portfolio_id)
    reconcile_manager = _reconcile_manager_for(order)

    # Restart seed: rehydrate drives the durable venue_trade_id history into BOTH
    # the portfolio ledger AND the order-mirror ring (single history pass).
    handler.rehydrate(reconcile_manager.seed_applied_trades)
    assert "BTC/USDT:T1" in handler._settled_venue_trade_ids
    assert "BTC/USDT:T1" in reconcile_manager._applied_trade_keys

    # Re-delivering the SAME (BTC/USDT, "T1") after the restart must be a mirror
    # no-op — the restart-seeded ring recognizes it as already-applied.
    reconcile_manager.on_fill(_fill_for(order, "T1"))
    assert order.filled_quantity == Decimal("0")
    assert order.status == OrderStatus.PENDING


def test_reconcile_ring_seed_symbol_scoped_other_symbol_still_books() -> None:
    """A restart-seeded ring is symbol-scoped: a different symbol still books (V17-12)."""
    portfolio_id = PortfolioId(uc.uuid7())
    seed = _buy_transaction(
        "BTC/USDT", Decimal("0.1"), Decimal("42000"), portfolio_id,
        venue_trade_id="T1",
    )
    store = _DurableStoreDouble(durable_transactions=[seed])
    handler, _pid, _portfolio = _handler_with_portfolio_on(store)

    # A DIFFERENT symbol sharing the numeric trade id "T1" — a distinct trade.
    order = _resting_order("ETH/USDT", portfolio_id)
    reconcile_manager = _reconcile_manager_for(order)

    handler.rehydrate(reconcile_manager.seed_applied_trades)
    # Only the BTC key was seeded — the ETH key is absent, so ETH:T1 still books.
    assert "ETH/USDT:T1" not in reconcile_manager._applied_trade_keys

    reconcile_manager.on_fill(_fill_for(order, "T1"))
    assert order.filled_quantity == Decimal("0.1")
    assert order.status == OrderStatus.PARTIALLY_FILLED

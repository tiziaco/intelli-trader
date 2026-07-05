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
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional

import uuid_utils.compat as uc

from itrader.core.enums import Side, FillStatus, TransactionType
from itrader.core.ids import PortfolioId, TransactionId, OrderId, StrategyId
from itrader.events_handler.events import FillEvent
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
    ) -> None:
        super().__init__()
        self._durable_positions: Dict[str, Position] = dict(durable_positions or {})
        self._durable_cash: Optional[Decimal] = durable_cash
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
            "realized_pnl": Decimal("0"),
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

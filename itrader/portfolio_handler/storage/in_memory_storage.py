"""In-memory PortfolioStateStorage backend (D-10, M2-08).

Mirrors ``order_handler/storage/in_memory_storage.py``: dict/list-backed state,
one instance per Portfolio, single-threaded backtest path. The containers here
are the EXACT ones relocated out of the four portfolio managers — working state
(open positions, reserved cash) is mutable/removable; append-only history
(closed positions, transaction history, cash operations, snapshots) only grows
(snapshots additionally replaceable for the manager's max-size trim).
"""

from decimal import Decimal
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from ..base import PortfolioStateStorage

if TYPE_CHECKING:
    from ..position import Position
    from ..transaction import Transaction


class InMemoryPortfolioStateStorage(PortfolioStateStorage):
    """Dict/list-backed in-memory portfolio state. One instance per Portfolio."""

    def __init__(self) -> None:
        # Open positions (working state, keyed by ticker) — was PositionManager._positions
        self._positions: Dict[str, 'Position'] = {}
        # Closed positions (append-only history) — was PositionManager._closed_positions
        self._closed_positions: List['Position'] = []
        # Pending transaction contexts (working state) — was TransactionManager._pending_transactions
        self._pending_transactions: Dict[Any, Any] = {}
        # Transaction history (append-only) — was TransactionManager._transaction_history
        self._transaction_history: List['Transaction'] = []
        # Reserved cash (working state, per reference id — Plan 05-03) —
        # was a single aggregate Decimal; now a flat {reference_id: amount}
        # dict mirroring order storage's _by_id shape. Full precision (OQ4).
        self._reservations: Dict[str, Decimal] = {}
        # Cash operations (append-only audit) — was CashManager._cash_operations
        self._cash_operations: List[Any] = []
        # Metrics snapshots (append-only history) — was MetricsManager._snapshots
        self._snapshots: List[Any] = []

    # -- Positions -----------------------------------------------------------

    def set_position(self, ticker: str, position: 'Position') -> None:
        self._positions[ticker] = position

    def get_position(self, ticker: str) -> Optional['Position']:
        return self._positions.get(ticker)

    def get_positions(self) -> Dict[str, 'Position']:
        return self._positions.copy()

    def remove_position(self, ticker: str) -> None:
        self._positions.pop(ticker, None)

    def add_closed_position(self, position: 'Position') -> None:
        self._closed_positions.append(position)

    def get_closed_positions(self) -> List['Position']:
        return self._closed_positions.copy()

    # -- Transactions --------------------------------------------------------

    def set_pending_transaction(self, transaction_id: Any, context: Any) -> None:
        self._pending_transactions[transaction_id] = context

    def remove_pending_transaction(self, transaction_id: Any) -> None:
        self._pending_transactions.pop(transaction_id, None)

    def get_pending_transactions(self) -> Dict[Any, Any]:
        return self._pending_transactions.copy()

    def add_transaction(self, transaction: 'Transaction') -> None:
        self._transaction_history.append(transaction)

    def get_transaction_history(self) -> List['Transaction']:
        return self._transaction_history.copy()

    # -- Cash ----------------------------------------------------------------

    def get_reserved_cash(self) -> Decimal:
        return sum(self._reservations.values(), Decimal("0.00"))

    def add_reservation(self, reference_id: str, amount: Decimal) -> None:
        self._reservations[reference_id] = amount

    def pop_reservation(self, reference_id: str) -> Optional[Decimal]:
        return self._reservations.pop(reference_id, None)

    def add_cash_operation(self, operation: Any) -> None:
        self._cash_operations.append(operation)

    def get_cash_operations(self) -> List[Any]:
        return self._cash_operations.copy()

    # -- Metrics snapshots ---------------------------------------------------

    def add_snapshot(self, snapshot: Any) -> None:
        self._snapshots.append(snapshot)

    def get_snapshots(self) -> List[Any]:
        return self._snapshots.copy()

    def set_snapshots(self, snapshots: List[Any]) -> None:
        self._snapshots = list(snapshots)

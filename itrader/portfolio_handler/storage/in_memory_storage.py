"""In-memory PortfolioStateStorage backend (D-10, M2-08).

Mirrors ``order_handler/storage/in_memory_storage.py``: dict/list-backed state,
one instance per Portfolio, single-threaded backtest path. The containers here
are the EXACT ones relocated out of the four portfolio managers — working state
(open positions, reserved cash) is mutable/removable; append-only history
(closed positions, transaction history, cash operations, snapshots) only grows
(snapshots additionally replaceable for the manager's max-size trim).

Plan 05-05 (D-11): the pending-transaction container died with the saga
machinery — settlements are validate-first atomic, no in-flight context.
"""

from collections import deque
from decimal import Decimal
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from ..base import PortfolioStateStorage

if TYPE_CHECKING:
    from ..position import Position
    from ..transaction import Transaction


class InMemoryPortfolioStateStorage(PortfolioStateStorage):
    """Dict/list-backed in-memory portfolio state. One instance per Portfolio."""

    def __init__(self, max_snapshots: int = 10000) -> None:
        # D-03: snapshot retention bound. Stored so set_snapshots can rebuild a
        # bounded deque (Pitfall 2 — a plain-list reassignment drops maxlen).
        # Default 10000 matches MetricsManager.max_snapshots byte-for-byte and
        # keeps both storage-factory construction sites unchanged.
        self._max_snapshots = max_snapshots
        # Open positions (working state, keyed by ticker) — was PositionManager._positions
        self._positions: Dict[str, 'Position'] = {}
        # Closed positions (append-only history) — was PositionManager._closed_positions
        self._closed_positions: List['Position'] = []
        # Transaction history (append-only) — was TransactionManager._transaction_history
        self._transaction_history: List['Transaction'] = []
        # Reserved cash (working state, per reference id — Plan 05-03) —
        # was a single aggregate Decimal; now a flat {reference_id: amount}
        # dict mirroring order storage's _by_id shape. Full precision (OQ4).
        self._reservations: Dict[str, Decimal] = {}
        # Locked margin (working state, per position id — Plan 02-04 / D-10).
        # A DISTINCT container from reservations (Pitfall 2): held for the
        # lifetime of a position, full precision. Empty → clean Decimal("0").
        self._locked_margin: Dict[str, Decimal] = {}
        # Cash operations (append-only audit) — was CashManager._cash_operations
        self._cash_operations: List[Any] = []
        # Metrics snapshots (append-only history) — was MetricsManager._snapshots.
        # D-03: bounded deque(maxlen) — O(1) append + automatic oldest-eviction.
        # The maxlen IS the retention trim now (the per-bar slice-copy trim in
        # MetricsManager.record_snapshot is removed).
        self._snapshots: deque[Any] = deque(maxlen=max_snapshots)

    # -- Positions -----------------------------------------------------------

    def set_position(self, ticker: str, position: 'Position') -> None:
        self._positions[ticker] = position

    def get_position(self, ticker: str) -> Optional['Position']:
        return self._positions.get(ticker)

    def get_positions(self) -> Dict[str, 'Position']:
        # D-03/D-19: live read-only view, no per-tick copy (single-writer contract).
        return self._positions

    def remove_position(self, ticker: str) -> None:
        self._positions.pop(ticker, None)

    def add_closed_position(self, position: 'Position') -> None:
        self._closed_positions.append(position)

    def get_closed_positions(self) -> List['Position']:
        # D-03/D-19: live read-only view, no per-tick copy (single-writer contract).
        return self._closed_positions

    # -- Transactions (append-only history; pending state died with the saga,
    # Plan 05-05 D-11) -------------------------------------------------------

    def add_transaction(self, transaction: 'Transaction') -> None:
        self._transaction_history.append(transaction)

    def get_transaction_history(self) -> List['Transaction']:
        # D-03/D-19: live read-only view, no per-tick copy (single-writer contract).
        return self._transaction_history

    # -- Cash ----------------------------------------------------------------

    def get_reserved_cash(self) -> Decimal:
        return sum(self._reservations.values(), Decimal("0.00"))

    def add_reservation(self, reference_id: str, amount: Decimal) -> None:
        self._reservations[reference_id] = amount

    def pop_reservation(self, reference_id: str) -> Optional[Decimal]:
        return self._reservations.pop(reference_id, None)

    # -- Locked margin (position-keyed working state — Plan 02-04 / D-10) ----

    def get_locked_margin(self) -> Decimal:
        # Clean Decimal("0") when empty (Pitfall 6): sum() with a Decimal("0")
        # start yields a clean zero so the spot available_balance subtraction is
        # byte-exact (x - Decimal("0") == x).
        return sum(self._locked_margin.values(), Decimal("0"))

    def get_locked_margin_for(self, position_id: str) -> Decimal:
        # WR-01: clean Decimal("0") when the position holds no lock.
        return self._locked_margin.get(position_id, Decimal("0"))

    def add_locked_margin(self, position_id: str, amount: Decimal) -> None:
        self._locked_margin[position_id] = amount

    def pop_locked_margin(self, position_id: str) -> Optional[Decimal]:
        return self._locked_margin.pop(position_id, None)

    def add_cash_operation(self, operation: Any) -> None:
        self._cash_operations.append(operation)

    def get_cash_operations(self) -> List[Any]:
        # D-03/D-19: live read-only view, no per-tick copy (single-writer contract).
        return self._cash_operations

    # -- Metrics snapshots ---------------------------------------------------

    def add_snapshot(self, snapshot: Any) -> None:
        self._snapshots.append(snapshot)

    def get_snapshots(self) -> List[Any]:
        # D-03: the ONE accessor that copies (diverges from the four sibling
        # "return the live container" accessors). The deque is bounded and
        # auto-evicts on append; handing the live deque to a reader is a
        # mutation-during-iteration hazard under the live RLock model, and the
        # -> List[Any] ABC contract requires a list (deque raises on slices).
        # Readers get a stable materialized snapshot. Not on the per-bar path
        # (the trim that used to call this is removed), so the copy is immaterial.
        return list(self._snapshots)

    def set_snapshots(self, snapshots: List[Any]) -> None:
        # D-03: rebuild a bounded deque, never a plain list (Pitfall 2 — a list
        # reassignment silently drops maxlen and re-opens the unbounded-growth class).
        self._snapshots = deque(snapshots, maxlen=self._max_snapshots)

    def snapshot_count(self) -> int:
        # D-06: count-only accessor — lets the metrics-manager per-tick trim guard
        # check the size without copying the whole list.
        return len(self._snapshots)

    def get_latest_snapshot(self) -> Optional[Any]:
        # D-06: last-only accessor — the metrics-manager per-tick read needs only
        # the most-recent snapshot, never the whole copied list.
        return self._snapshots[-1] if self._snapshots else None

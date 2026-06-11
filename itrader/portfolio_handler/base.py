import uuid
from abc import ABC, abstractmethod
from decimal import Decimal
from typing import Any, Dict, List, Optional, Union, TYPE_CHECKING

# Portfolio ids may arrive as UUID (native scheme, D-14) or legacy str/int.
IdLike = Union[str, int, uuid.UUID]

if TYPE_CHECKING:
	from .position import Position
	from .transaction import Transaction


class PortfolioStateStorage(ABC):
    """Abstract base class for portfolio-manager state storage (D-09/D-10, M2-08).

    Provides a unified interface for managing portfolio state across different
    storage backends (in-memory for backtesting, PostgreSQL for live trading),
    generalizing the proven ``order_handler/base.py::OrderStorage`` pattern.

    This is a SINGLE unified interface (D-09) covering every container the four
    portfolio managers used to own:

      * open positions (working state, keyed by ticker) + closed positions (history)
      * transaction history (append-only)
      * reserved cash (working state) + cash operations (append-only audit trail)
      * metrics snapshots (append-only history)

    Following the order-storage split (active vs. all/history), working state is
    mutable/removable while history is append-only. The backend is pluggable via
    ``PortfolioStateStorageFactory``. Durable record shapes carry Decimal money +
    native UUID ids + event-derived time — there is NO DB code here.
    """

    # -- Positions (open = working state, closed = append-only history) ------

    @abstractmethod
    def set_position(self, ticker: str, position: 'Position') -> None:
        """Store (insert or replace) the open position for a ticker.

        Parameters
        ----------
        ticker : str
            The ticker the open position is keyed by.
        position : Position
            The open position to store.
        """
        pass

    @abstractmethod
    def get_position(self, ticker: str) -> Optional['Position']:
        """Return the open position for a ticker, or ``None`` if absent.

        Parameters
        ----------
        ticker : str
            The ticker to look up.

        Returns
        -------
        Optional[Position]
            The open position if present, else ``None``.
        """
        pass

    @abstractmethod
    def get_positions(self) -> Dict[str, 'Position']:
        """Return a shallow copy of all open positions keyed by ticker.

        Returns
        -------
        Dict[str, Position]
            All currently open positions.
        """
        pass

    @abstractmethod
    def remove_position(self, ticker: str) -> None:
        """Remove the open position for a ticker (no error if absent).

        Parameters
        ----------
        ticker : str
            The ticker whose open position is removed.
        """
        pass

    @abstractmethod
    def add_closed_position(self, position: 'Position') -> None:
        """Append a position to the closed-positions history.

        Parameters
        ----------
        position : Position
            The position that has just been closed.
        """
        pass

    @abstractmethod
    def get_closed_positions(self) -> List['Position']:
        """Return a shallow copy of the closed-positions history.

        Returns
        -------
        List[Position]
            All closed positions, in close order.
        """
        pass

    # -- Transactions (append-only history) ----------------------------------
    # Plan 05-05 (D-11): the pending-transaction working state is gone with
    # the saga machinery — settlements are validate-first atomic, so there is
    # no in-flight context to store. Only the append-only history remains.

    @abstractmethod
    def add_transaction(self, transaction: 'Transaction') -> None:
        """Append a transaction to the append-only history.

        Parameters
        ----------
        transaction : Transaction
            The executed transaction to record.
        """
        pass

    @abstractmethod
    def get_transaction_history(self) -> List['Transaction']:
        """Return a shallow copy of the transaction history.

        Returns
        -------
        List[Transaction]
            All recorded transactions, in execution order.
        """
        pass

    # -- Cash (reserved = working state, operations = append-only audit) -----

    @abstractmethod
    def get_reserved_cash(self) -> Decimal:
        """Return the total currently reserved cash amount.

        Plan 05-03: reservations are tracked per reference id (flat
        ``dict[str, Decimal]`` — mirrors the order storage's flat ``_by_id``
        shape); this returns their sum.

        Returns
        -------
        Decimal
            The sum of all per-reference reservations.
        """
        pass

    @abstractmethod
    def add_reservation(self, reference_id: str, amount: Decimal) -> None:
        """Store (insert or replace) a cash reservation keyed by reference id.

        Amounts are stored at FULL precision (OQ4): the released amount must
        equal the reserved amount exactly, so no quantization happens here.

        Parameters
        ----------
        reference_id : str
            The reference (e.g. order id) the reservation is keyed by.
        amount : Decimal
            The reserved amount (full precision).
        """
        pass

    @abstractmethod
    def pop_reservation(self, reference_id: str) -> Optional[Decimal]:
        """Remove and return the reservation for a reference id.

        Parameters
        ----------
        reference_id : str
            The reference whose reservation is removed.

        Returns
        -------
        Optional[Decimal]
            The reserved amount if a reservation existed, else ``None``
            (no error when absent — release is idempotent).
        """
        pass

    @abstractmethod
    def add_cash_operation(self, operation: Any) -> None:
        """Append a cash operation to the audit trail.

        Parameters
        ----------
        operation : Any
            The ``CashOperation`` record to append.
        """
        pass

    @abstractmethod
    def get_cash_operations(self) -> List[Any]:
        """Return a shallow copy of the cash-operation audit trail.

        Returns
        -------
        List[Any]
            All recorded cash operations, in order.
        """
        pass

    # -- Metrics snapshots (append-only history) -----------------------------

    @abstractmethod
    def add_snapshot(self, snapshot: Any) -> None:
        """Append a portfolio metrics snapshot to the history.

        Parameters
        ----------
        snapshot : Any
            The ``PortfolioSnapshot`` to append.
        """
        pass

    @abstractmethod
    def get_snapshots(self) -> List[Any]:
        """Return a shallow copy of the metrics-snapshot history.

        Returns
        -------
        List[Any]
            All recorded snapshots, in record order.
        """
        pass

    @abstractmethod
    def set_snapshots(self, snapshots: List[Any]) -> None:
        """Replace the metrics-snapshot history (e.g. to trim to a max size).

        Parameters
        ----------
        snapshots : List[Any]
            The replacement snapshot list.
        """
        pass
	

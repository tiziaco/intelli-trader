import uuid
from abc import ABC, abstractmethod
from decimal import Decimal
from typing import Any, Dict, List, Optional, Union, TYPE_CHECKING

# Portfolio ids may arrive as UUID (native scheme, D-14) or legacy str/int.
IdLike = Union[str, int, uuid.UUID]

if TYPE_CHECKING:
	from .position import Position
	from .transaction import Transaction


class AbstractPortfolioHandler(ABC):
	"""
	AbstractPortfolioHandler is a base class providing an interface for
	all subsequent (inherited) portfolio handlers.

	The goal of a derived PortfolioHandler is to provide a standardized
	interface for managing and interacting with portfolios. 
	Subclasses should implement specific functionality for
	managing portfolios, such as adding assets, adjusting positions,
	calculating portfolio metrics, and handling transactions.
	"""

	@abstractmethod
	def get_last_close(self, ticker: str) -> Any:
		raise NotImplementedError("Should implement get_last_close()")


class AbstractPortfolio(ABC):
	"""
	AbstractPortfolioHandler is a base class providing an interface for
	all subsequent (inherited) portfolio handlers.

	The goal of a derived PortfolioHandler is to provide a standardized
	interface for managing and interacting with portfolios. 
	Subclasses should implement specific functionality for
	managing portfolios, such as adding assets, adjusting positions,
	calculating portfolio metrics, and handling transactions.
	"""

	@abstractmethod
	def create(self, user_id: Any, name: str, exchange: str, initial_cash: Any) -> Any:
		raise NotImplementedError("Should implement create()")

	@abstractmethod
	def deposit(self, cash: Any) -> Any:
		"""
		Deposit money in the portfolio.
		"""
		raise NotImplementedError("Should implement deposit()")

	@abstractmethod
	def withdraw(self, cash: Any) -> Any:
		"""
		Withdraw money from the portfolio.
		"""
		raise NotImplementedError("Should implement withdraw()")

	@abstractmethod
	def process_transaction(self, transaction: Any) -> Any:
		"""
		Calculate the transaction cost and update the portfolio balance.
		Process the transaction updating or opening a new position.
		"""
		raise NotImplementedError("Should implement process_transaction()")

class AbstractPosition(ABC):

	@abstractmethod
	def create(self, date: Any, symbol: str, side: Any, quantity: Any, price: Any) -> Any:
		"""
		Create a new instance of the Position object.
		"""
		raise NotImplementedError("Should implement create()")

	@abstractmethod
	def transact_buy(self, date: Any, symbol: str, side: Any, quantity: Any, price: Any) -> Any:
		"""
		Update the position attributes after a buy transaction.
		"""
		raise NotImplementedError("Should implement transact_buy()")

	@abstractmethod
	def transact_sell(self, date: Any, symbol: str, side: Any, quantity: Any, price: Any) -> Any:
		"""
		Update the position attributes after a sell transaction.
		"""
		raise NotImplementedError("Should implement transact_sell()")


class PortfolioStateStorage(ABC):
    """Abstract base class for portfolio-manager state storage (D-09/D-10, M2-08).

    Provides a unified interface for managing portfolio state across different
    storage backends (in-memory for backtesting, PostgreSQL for live trading),
    generalizing the proven ``order_handler/base.py::OrderStorage`` pattern.

    This is a SINGLE unified interface (D-09) covering every container the four
    portfolio managers used to own:

      * open positions (working state, keyed by ticker) + closed positions (history)
      * pending transactions (working state) + transaction history (append-only)
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

    # -- Transactions (pending = working state, history = append-only) -------

    @abstractmethod
    def set_pending_transaction(self, transaction_id: Any, context: Any) -> None:
        """Store the in-flight context for a pending transaction.

        Parameters
        ----------
        transaction_id : Any
            The transaction id (native ``TransactionId``) keying the context.
        context : Any
            The ``TransactionContext`` for the in-flight transaction.
        """
        pass

    @abstractmethod
    def remove_pending_transaction(self, transaction_id: Any) -> None:
        """Remove a pending transaction context (no error if absent).

        Parameters
        ----------
        transaction_id : Any
            The transaction id whose pending context is removed.
        """
        pass

    @abstractmethod
    def get_pending_transactions(self) -> Dict[Any, Any]:
        """Return a shallow copy of all pending transaction contexts.

        Returns
        -------
        Dict[Any, Any]
            Pending transaction contexts keyed by transaction id.
        """
        pass

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
        """Return the currently reserved cash amount.

        Returns
        -------
        Decimal
            The reserved cash balance.
        """
        pass

    @abstractmethod
    def set_reserved_cash(self, amount: Decimal) -> None:
        """Set the reserved cash amount.

        Parameters
        ----------
        amount : Decimal
            The new reserved cash balance.
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
	

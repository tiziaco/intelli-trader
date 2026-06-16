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
        """Return a read-only view of all open positions keyed by ticker
        (callers MUST NOT mutate — D-19 single-writer; copy yourself if you
        need ownership).

        D-03: the backtest backend returns the live internal container (no
        per-tick copy) — the defensive copy never protected correctness under
        the single-writer contract, it only added per-tick cost.

        Returns
        -------
        Dict[str, Position]
            All currently open positions (read-only view).
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
        """Return a read-only view of the closed-positions history (callers
        MUST NOT mutate — D-19 single-writer; copy yourself if you need
        ownership).

        D-03: the backtest backend returns the live internal container (no
        per-tick copy).

        Returns
        -------
        List[Position]
            All closed positions, in close order (read-only view).
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
        """Return a read-only view of the transaction history (callers MUST
        NOT mutate — D-19 single-writer; copy yourself if you need ownership).

        D-03: the backtest backend returns the live internal container (no
        per-tick copy).

        Returns
        -------
        List[Transaction]
            All recorded transactions, in execution order (read-only view).
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

    # -- Locked margin (position-keyed working state — Plan 02-04, D-10) ------
    # A DISTINCT lifecycle from the order-keyed reservation (Pitfall 2): the
    # lock is held for the lifetime of a position (open → scale-in → close),
    # not for a pending order. Stored at FULL precision (no quantize) so the
    # release equals the lock exactly.

    @abstractmethod
    def get_locked_margin(self) -> Decimal:
        """Return the total currently locked margin across all positions.

        Mirrors ``get_reserved_cash`` but for the position-keyed locked-margin
        container (margin mode, D-10). Returns a CLEAN ``Decimal('0')`` when
        nothing is locked (Pitfall 6) so the spot ``available_balance``
        subtraction is byte-exact.

        Returns
        -------
        Decimal
            The sum of all per-position locked-margin amounts (clean zero when
            empty).
        """
        pass

    @abstractmethod
    def get_locked_margin_for(self, position_id: str) -> Decimal:
        """Return the margin currently locked for a single position id.

        WR-01 (T-03-15) reads this so a scale-in's own prior lock is added back
        to buying power before the settlement-side solvency assertion (the
        position replaces its own lock, so its already-locked amount must not be
        double-counted against the new lock). Returns a CLEAN ``Decimal('0')``
        when the position holds no lock.

        Parameters
        ----------
        position_id : str
            The position whose locked margin is read.

        Returns
        -------
        Decimal
            The locked amount for the position, or ``Decimal('0')`` if none.
        """
        pass

    @abstractmethod
    def add_locked_margin(self, position_id: str, amount: Decimal) -> None:
        """Store (insert or replace) the locked margin for a position id.

        Amounts are stored at FULL precision (no quantize) so the released
        amount equals the locked amount exactly. A scale-in replaces the prior
        lock with the recomputed ``new_aggregate_notional / L``.

        Parameters
        ----------
        position_id : str
            The position the locked margin is keyed by.
        amount : Decimal
            The locked margin amount (full precision).
        """
        pass

    @abstractmethod
    def pop_locked_margin(self, position_id: str) -> Optional[Decimal]:
        """Remove and return the locked margin for a position id.

        Parameters
        ----------
        position_id : str
            The position whose locked margin is removed.

        Returns
        -------
        Optional[Decimal]
            The locked amount if a lock existed, else ``None`` (no error when
            absent — release is idempotent).
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
        """Return a read-only view of the cash-operation audit trail (callers
        MUST NOT mutate — D-19 single-writer; copy yourself if you need
        ownership).

        D-03: the backtest backend returns the live internal container (no
        per-tick copy).

        Returns
        -------
        List[Any]
            All recorded cash operations, in order (read-only view).
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
        """Return a read-only view of the metrics-snapshot history (callers
        MUST NOT mutate — D-19 single-writer; copy yourself if you need
        ownership).

        D-03: the backtest backend returns the live internal container (no
        per-tick copy). D-06: the per-tick trim/last reads in
        ``MetricsManager`` consume ``snapshot_count()`` / ``get_latest_snapshot()``
        instead of this whole-list accessor.

        Returns
        -------
        List[Any]
            All recorded snapshots, in record order (read-only view).
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

    @abstractmethod
    def snapshot_count(self) -> int:
        """Return the number of recorded metrics snapshots (count-only — no copy).

        D-06: the ``MetricsManager`` per-tick trim guard checks the snapshot
        count without copying the whole list (the never-firing trim no longer
        pays the per-tick copy cost).

        Returns
        -------
        int
            The number of recorded snapshots.
        """
        pass

    @abstractmethod
    def get_latest_snapshot(self) -> Optional[Any]:
        """Return the most-recent snapshot, or ``None`` if none recorded
        (last-only — no copy).

        D-06: the ``MetricsManager`` per-tick read needs only the latest
        snapshot, not the whole copied list.

        Returns
        -------
        Optional[Any]
            The most-recent snapshot, or ``None`` if no snapshot is recorded.
        """
        pass
	

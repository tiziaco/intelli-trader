"""``CachedSqlPortfolioStateStorage`` — the live-only portfolio-state decorator (D-04, A2/A3).

The portfolio-state member of the per-concern ``CachedSql<Concern>Storage`` triple. It
*composes* (never modifies — D-04) the gate-passed Phase-3 ``SqlPortfolioStateStorage``
(system of record, one instance per ``Portfolio`` with a bound ``portfolio_id``) with an
in-memory ``InMemoryPortfolioStateStorage`` working set, and implements the 21-method
``PortfolioStateStorage`` ABC store-first (Pitfall 8 persist-then-acknowledge):

* **Mutating ABC methods** persist to the store FIRST, then — under ``self._lock`` — mirror
  the open/current portion into the cache. The store commit returns before the cache is
  touched; the cache is always rebuildable from the store, the inverse is not.
* **Open/current reads** (positions, reserved cash, locked margin, snapshot count / latest)
  are served cache-only.
* **History reads** (closed positions, transaction history, cash operations, snapshots) read
  through to the store — they are intentionally NOT resident in the working set (D-02).
* **Append-only history mutations** (closed positions, transactions, cash operations) are
  store-only — never mirrored into the working set (read-through serves them).

Beyond the ABC it adds the dedicated single-row ``portfolio_account_state`` carrier (A2):
``save_account_state`` synchronously upserts the two purge-derived accumulators
(``cash_balance``, ``realized_pnl``) + the latest account snapshot, and ``load_account_state``
returns them — so the latest persisted account state is never behind the working set after a
crash (D-03). ``rehydrate()`` reloads the open positions + reservations + locked margin +
account-state scalars on restart, open-only, never replaying closed positions / transactions /
cash-ops.

Bound ``portfolio_id`` (Pitfall 1 / V4 access control): the wrapper carries the store's bound
id and scopes the account-state + rehydration row-reads to it (``.where(col == self._portfolio_id)``),
so reads never cross the portfolio boundary. All SQL is parameterized Core against the constant
``Table`` objects — never f-string SQL (T-04-01 / SEC-01).

A3 / D-01: Phase 4 builds + component-tests the wrapper's *ability* to persist / return /
rehydrate these scalars. Restoring them INTO ``CashManager._balance`` /
``PositionManager._realised_pnl_accumulator`` (and wiring ``save_account_state`` on every fill)
is **N+4** — and the live composition root is NOT rewired this phase (``portfolio.py:93`` stays
``"backtest"``); the factory ``'live'`` arm is wired so the wrapper is constructable.

The module stays quarantined: it is NOT re-exported from any ``__init__`` (importing it pulls
SQLAlchemy), so the backtest import path stays SQL-free (GATE-01 inertness). 4-space
indentation (matches the ``sql_storage.py`` sibling — Pitfall 12).
"""

import threading
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from sqlalchemy import delete, insert, select

from itrader.logger import get_itrader_logger

from ..base import PortfolioStateStorage
from .in_memory_storage import InMemoryPortfolioStateStorage

if TYPE_CHECKING:
    from ..account import Account
    from ..position import Position
    from ..transaction import Transaction
    from .sql_storage import SqlPortfolioStateStorage


class CachedSqlPortfolioStateStorage(PortfolioStateStorage):
    """Store-first write-through portfolio-state cache over a bound ``SqlPortfolioStateStorage``.

    Parameters
    ----------
    store:
        The Phase-3 ``SqlPortfolioStateStorage`` system of record (bound ``portfolio_id``).
        Composed by reference (has-a, D-04) — never modified.
    max_snapshots:
        Retention bound for the in-memory working-set snapshot deque (D-03). Threaded into
        the composed ``InMemoryPortfolioStateStorage`` so the caller's retention bound governs
        the working set.
    """

    def __init__(
        self, store: "SqlPortfolioStateStorage", max_snapshots: int = 10000
    ) -> None:
        self._store = store
        # Carry the store's bound portfolio id — the cross-portfolio-isolation boundary
        # (Pitfall 1 / V4): the account-state + rehydration row-reads scope to it.
        self._portfolio_id: uuid.UUID = store._portfolio_id
        # CACHE-CLASS: (d) live-retention working-set cache (built in Phase 4) — see docs/CACHE-CLASSIFICATION.md
        self._cache = InMemoryPortfolioStateStorage(max_snapshots=max_snapshots)
        # One RLock taken briefly around cache mutation / read-through lookups. Uncontended
        # in the as-wired daemon-only system; built API-thread-safe for the FastAPI layer (A4).
        self._lock = threading.RLock()
        # The dedicated account-state carrier (A2), registered on the shared MetaData by
        # build_portfolio_tables (constructing the store registered + created it).
        self._account_state = store.backend.metadata.tables["portfolio_account_state"]
        self.logger = get_itrader_logger().bind(
            component="CachedSqlPortfolioStateStorage"
        )

    # -- Positions (open = working state, closed = append-only history) ------

    def set_position(self, ticker: str, position: "Position") -> None:
        # Store-first, then mirror the open position into the working set.
        self._store.set_position(ticker, position)
        with self._lock:
            self._cache.set_position(ticker, position)

    def get_position(self, ticker: str) -> Optional["Position"]:
        # Cache-only — the open set is always resident.
        with self._lock:
            return self._cache.get_position(ticker)

    def get_positions(self) -> Dict[str, "Position"]:
        # Cache-only — the open set is always resident.
        with self._lock:
            return self._cache.get_positions()

    def remove_position(self, ticker: str) -> None:
        self._store.remove_position(ticker)
        with self._lock:
            self._cache.remove_position(ticker)

    def add_closed_position(self, position: "Position") -> None:
        # Store-only history (D-02) — closed positions are NOT resident in the working set.
        self._store.add_closed_position(position)

    def get_closed_positions(self) -> List["Position"]:
        # Read-through to the store (history is not cached).
        return self._store.get_closed_positions()

    # -- Transactions (append-only history) ----------------------------------

    def add_transaction(self, transaction: "Transaction") -> None:
        # Store-only history (D-02).
        self._store.add_transaction(transaction)

    def get_transaction_history(self) -> List["Transaction"]:
        # Read-through to the store.
        return self._store.get_transaction_history()

    # -- Cash reservations (reference_id -> amount, full precision) -----------

    def get_reserved_cash(self) -> Decimal:
        with self._lock:
            return self._cache.get_reserved_cash()

    def add_reservation(self, reference_id: str, amount: Decimal) -> None:
        self._store.add_reservation(reference_id, amount)
        with self._lock:
            self._cache.add_reservation(reference_id, amount)

    def pop_reservation(self, reference_id: str) -> Optional[Decimal]:
        # Store-first pop (source of truth), then mirror the removal into the cache.
        popped = self._store.pop_reservation(reference_id)
        with self._lock:
            self._cache.pop_reservation(reference_id)
        return popped

    # -- Locked margin (position_id str -> amount, full precision) ------------

    def get_locked_margin(self) -> Decimal:
        with self._lock:
            return self._cache.get_locked_margin()

    def get_locked_margin_for(self, position_id: str) -> Decimal:
        with self._lock:
            return self._cache.get_locked_margin_for(position_id)

    def add_locked_margin(self, position_id: str, amount: Decimal) -> None:
        self._store.add_locked_margin(position_id, amount)
        with self._lock:
            self._cache.add_locked_margin(position_id, amount)

    def pop_locked_margin(self, position_id: str) -> Optional[Decimal]:
        popped = self._store.pop_locked_margin(position_id)
        with self._lock:
            self._cache.pop_locked_margin(position_id)
        return popped

    # -- Cash operations (append-only audit) ---------------------------------

    def add_cash_operation(self, operation: Any) -> None:
        # Store-only audit trail (D-02).
        self._store.add_cash_operation(operation)

    def get_cash_operations(self) -> List[Any]:
        # Read-through to the store.
        return self._store.get_cash_operations()

    # -- Metrics snapshots (append-only history; latest/count served cache-only) --

    def add_snapshot(self, snapshot: Any) -> None:
        # Store-first (read-through history) then mirror into the bounded working-set deque
        # (so snapshot_count / get_latest_snapshot stay cache-only).
        self._store.add_snapshot(snapshot)
        with self._lock:
            self._cache.add_snapshot(snapshot)

    def get_snapshots(self) -> List[Any]:
        # Read-through to the store — the full history lives there.
        return self._store.get_snapshots()

    def set_snapshots(self, snapshots: List[Any]) -> None:
        # Store-first, then rebuild the bounded working-set deque (Pitfall 2 — the cache's
        # set_snapshots rebuilds deque(maxlen), never a plain list).
        self._store.set_snapshots(snapshots)
        with self._lock:
            self._cache.set_snapshots(snapshots)

    def snapshot_count(self) -> int:
        with self._lock:
            return self._cache.snapshot_count()

    def get_latest_snapshot(self) -> Optional[Any]:
        with self._lock:
            return self._cache.get_latest_snapshot()

    # -- Account-state carrier (A2 — purge-derived accumulators) -------------

    def save_account_state(
        self,
        *,
        cash_balance: Decimal,
        realized_pnl: Decimal,
        total_equity: Decimal,
        peak_equity: Decimal,
        open_positions_count: int,
        updated_time: datetime,
    ) -> None:
        """Synchronously upsert the single account-state row for the bound portfolio (A2/D-03).

        Cross-dialect upsert = delete-then-insert in one txn (the Phase-3 ``add_reservation``
        idiom). Parameterized Core on the ``portfolio_account_state`` ``Table`` — never
        f-string SQL (T-04-01). Scoped to ``self._portfolio_id`` so it can never write another
        portfolio's row.
        """
        table = self._account_state
        with self._store.engine.begin() as connection:
            connection.execute(
                delete(table).where(table.c.portfolio_id == self._portfolio_id)
            )
            connection.execute(
                insert(table),
                [
                    {
                        "portfolio_id": self._portfolio_id,
                        "cash_balance": cash_balance,
                        "realized_pnl": realized_pnl,
                        "total_equity": total_equity,
                        "peak_equity": peak_equity,
                        "open_positions_count": open_positions_count,
                        "updated_time": updated_time,
                    }
                ],
            )

    def load_account_state(self) -> Optional[dict[str, Any]]:
        """Return the single account-state row for the bound portfolio, or ``None`` if absent.

        Parameterized SELECT scoped to ``self._portfolio_id`` (V4 isolation). Money round-trips
        as exact ``Decimal`` (Postgres-native ``Numeric``); ``updated_time`` as the original
        business ``datetime`` (``UtcIsoText``).
        """
        table = self._account_state
        statement = select(table).where(table.c.portfolio_id == self._portfolio_id)
        with self._store.engine.connect() as connection:
            row = connection.execute(statement).mappings().first()
        if row is None:
            return None
        return {
            "cash_balance": row["cash_balance"],
            "realized_pnl": row["realized_pnl"],
            "total_equity": row["total_equity"],
            "peak_equity": row["peak_equity"],
            "open_positions_count": row["open_positions_count"],
            "updated_time": row["updated_time"],
        }

    # -- Rehydration (open-only restart boot sequence — D-03) -----------------

    def rehydrate(self, account: "Optional[Account]" = None) -> None:
        """Reload the open working set from the store on restart — open-only (D-03/D-07).

        Loads open positions (the indexed ``WHERE is_open = true`` query, D-08), repopulates
        the reservations / locked-margin dicts from their per-reference rows, and — when a live
        ``account`` is supplied — restores the persisted cash scalar INTO it (D-07 / V17-05:
        the engine remembers its balance after a restart). NEVER loads closed positions /
        transaction history / cash-ops into the working set (read-through serves those).

        The rehydrated OPEN positions surface through the live ``PositionManager`` read path
        automatically: the manager reads ``state_storage.get_positions()`` → this wrapper's
        cache, which is populated below. The cash scalar is the one piece NOT served by the
        cache (it lives on the ``Account._balance``), so it is threaded into
        ``account.restore_cash`` here — closing the D-07 restore gap (was: read back and
        discarded, "N+4").

        Args:
            account: The live ``Account`` leaf to restore the persisted cash balance into.
                ``None`` keeps the read-back-only boot behaviour (the caller restores cash
                elsewhere) — the SMA_MACD backtest never reaches this path (oracle-dark).
        """
        positions = self._store.get_positions()
        reservations = self._load_scoped_amounts(
            self._store.cash_reservations, "reference_id"
        )
        locked_margin = self._load_scoped_amounts(
            self._store.locked_margin, "position_id"
        )
        with self._lock:
            for ticker, position in positions.items():
                self._cache.set_position(ticker, position)
            for reference_id, amount in reservations.items():
                self._cache.add_reservation(reference_id, amount)
            for position_id, amount in locked_margin.items():
                self._cache.add_locked_margin(position_id, amount)
        # D-07: restore the persisted cash scalar INTO the live account (no longer
        # discarded). Positions/reservations/locked-margin are already restored above via
        # the cache the managers read; the cash balance is the one scalar the cache does
        # not carry, so it is threaded into the account here.
        state = self.load_account_state()
        if account is not None and state is not None:
            account.restore_cash(state["cash_balance"])

    def _load_scoped_amounts(self, table: Any, key_column: str) -> dict[str, Decimal]:
        """Read a ``{key -> amount}`` map for the bound portfolio from a per-reference table.

        Parameterized Core scoped to ``self._portfolio_id`` (V4 isolation) — used to repopulate
        the reservations / locked-margin working-set dicts on rehydration.
        """
        statement = select(
            table.c[key_column], table.c.amount
        ).where(table.c.portfolio_id == self._portfolio_id)
        with self._store.engine.connect() as connection:
            rows = connection.execute(statement).mappings().all()
        return {row[key_column]: row["amount"] for row in rows}

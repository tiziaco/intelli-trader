"""Concrete ``SqlPortfolioStateStorage`` — the portfolio-state operational backend (OPS-02).

The portfolio-state ``Sql<Concern>Storage`` on the shared SQL spine: it *composes* a
``SqlBackend`` by reference (has-a, D-06 — never a cross-concern god base), registers the
six portfolio tables on ``backend.metadata`` via ``build_portfolio_tables``, and calls
``metadata.create_all(checkfirst=True)`` so schema creation is idempotent (live path uses
Alembic; ``create_all`` is the test/idempotent path). Mirrors ``results/sql_storage.py``.

THE defining nuance (Pitfall 1): the ``PortfolioStateStorage`` ABC has NO ``portfolio_id``
parameter on any of its ~21 methods — the in-memory backend is one-instance-per-``Portfolio``.
So this backend BINDS a ``portfolio_id`` at construction and scopes EVERY query to it:

* every SELECT/DELETE carries ``.where(table.c.portfolio_id == self._portfolio_id)``;
* every INSERT injects ``self._portfolio_id`` — INCLUDING ``cash_operations`` /
  ``equity_snapshots`` rows whose source objects carry NO ``portfolio_id`` field.

This is the cross-portfolio-isolation boundary Phase-4 rehydration depends on (T-03-08).
All SQL is parameterized Core against the constant ``Table`` objects — never f-string SQL
(T-03-09 / SEC-01). Money moves ``Decimal`` ↔ Postgres-native ``Numeric`` with NO quantize
on reservation/locked-margin amounts (full precision, OPS-04). Append-only histories
(snapshots / transactions / cash_operations) return in a stable order via an explicit
per-portfolio ``seq`` (snapshots) or ``ORDER BY (time, id)`` tiebreak — Postgres has no
implicit insertion order (Pitfall 7); the snapshot ``seq`` is backend-written, NOT Integer
autoincrement (single-UUID rule).

The store stays quarantined: it is NOT re-exported from the package ``__init__`` (importing
it pulls SQLAlchemy), so the backtest import path stays SQL-free (GATE-01 inertness). 4-space
indentation (mirrors the ``itrader/results`` SQL layer — D-05).
"""

import uuid
from decimal import Decimal
from typing import Any, Dict, List, Optional

from sqlalchemy import delete, func, insert, select

from itrader.core.enums import CashOperationType, PositionSide, TransactionType
from itrader.core.ids import PositionId, TransactionId
from itrader.logger import get_itrader_logger
from itrader.storage import SqlBackend

from ..base import PortfolioStateStorage
from itrader.portfolio_handler.account import CashOperation
from ..metrics.metrics_manager import PortfolioSnapshot
from ..position import Position
from ..transaction import Transaction
from .models import build_portfolio_tables


class SqlPortfolioStateStorage(PortfolioStateStorage):
    """Portfolio-state backend on the SQL spine, scoped to one bound ``portfolio_id``.

    Parameters
    ----------
    backend:
        The shared spine (Engine + MetaData). The driver/URL is selected by config at
        wiring; this backend registers its six tables on ``backend.metadata`` and creates
        them idempotently (``checkfirst=True``).
    portfolio_id:
        The UUIDv7 portfolio this instance is bound to (Pitfall 1). EVERY query is scoped
        to it; the source objects that carry no ``portfolio_id`` field
        (``CashOperation`` / ``PortfolioSnapshot``) have it injected on insert.
    """

    def __init__(self, backend: SqlBackend, portfolio_id: uuid.UUID) -> None:
        self.backend = backend
        self.engine = backend.engine
        self._portfolio_id = portfolio_id

        tables = build_portfolio_tables(backend.metadata)
        self.positions = tables["positions"]
        self.transactions = tables["transactions"]
        self.cash_reservations = tables["cash_reservations"]
        self.locked_margin = tables["locked_margin"]
        self.cash_operations = tables["cash_operations"]
        self.equity_snapshots = tables["equity_snapshots"]

        # Idempotent, ephemeral-friendly schema creation (the live path migrates via
        # Alembic; create_all is the test/no-op-if-present path).
        backend.metadata.create_all(self.engine, checkfirst=True)

        self.logger = get_itrader_logger().bind(component="SqlPortfolioStateStorage")

    def dispose(self) -> None:
        """Dispose the shared backend engine (WR-03 — delegate, never engine.dispose())."""
        self.backend.dispose()

    # -- Positions (open = working state, closed = append-only history) ------

    def _position_to_row(self, position: "Position") -> dict[str, Any]:
        """Map a ``Position`` to a ``positions`` row (portfolio_id injected — Pitfall 1)."""
        return {
            "id": position.id,
            "portfolio_id": self._portfolio_id,
            "ticker": position.ticker,
            "side": position.side.value,
            "leverage": position.leverage,
            "current_price": position.current_price,
            "current_time": position.current_time,
            "buy_quantity": position.buy_quantity,
            "sell_quantity": position.sell_quantity,
            "avg_bought": position.avg_bought,
            "avg_sold": position.avg_sold,
            "buy_commission": position.buy_commission,
            "sell_commission": position.sell_commission,
            "entry_date": position.entry_date,
            "exit_date": position.exit_date,
            "_last_accrual_time": position._last_accrual_time,
            "is_open": position.is_open,
        }

    def _row_to_position(self, row: Any) -> "Position":
        """Rebuild a ``Position`` from a ``positions`` row.

        The derived caches (``_net_quantity_cache`` / ``_avg_price_cache``) are NOT
        persisted — they default ``None`` and recompute on first access. ``id`` /
        ``current_time`` / ``exit_date`` / ``_last_accrual_time`` are restored after
        construction (the constructor generates a fresh id and seeds ``current_time`` from
        ``entry_date``).
        """
        position = Position(
            entry_date=row["entry_date"],
            ticker=row["ticker"],
            side=PositionSide(row["side"]),
            price=row["current_price"],
            buy_quantity=row["buy_quantity"],
            sell_quantity=row["sell_quantity"],
            avg_bought=row["avg_bought"],
            avg_sold=row["avg_sold"],
            buy_commission=row["buy_commission"],
            sell_commission=row["sell_commission"],
            is_open=row["is_open"],
            portfolio_id=row["portfolio_id"],
            leverage=row["leverage"],
        )
        position.id = PositionId(row["id"])
        position.current_time = row["current_time"]
        position.exit_date = row["exit_date"]
        position._last_accrual_time = row["_last_accrual_time"]
        return position

    def set_position(self, ticker: str, position: "Position") -> None:
        # Mirror dict assignment ``self._positions[ticker] = position``: replace the open
        # row for this ticker (delete-then-insert in one txn). The is_open=true filter
        # leaves closed-position history untouched.
        with self.engine.begin() as connection:
            connection.execute(
                delete(self.positions).where(
                    (self.positions.c.portfolio_id == self._portfolio_id)
                    & (self.positions.c.ticker == ticker)
                    & (self.positions.c.is_open.is_(True))
                )
            )
            connection.execute(
                insert(self.positions), [self._position_to_row(position)]
            )

    def get_position(self, ticker: str) -> Optional["Position"]:
        statement = select(self.positions).where(
            (self.positions.c.portfolio_id == self._portfolio_id)
            & (self.positions.c.ticker == ticker)
            & (self.positions.c.is_open.is_(True))
        )
        with self.engine.connect() as connection:
            row = connection.execute(statement).mappings().first()
        return None if row is None else self._row_to_position(row)

    def get_positions(self) -> Dict[str, "Position"]:
        statement = select(self.positions).where(
            (self.positions.c.portfolio_id == self._portfolio_id)
            & (self.positions.c.is_open.is_(True))
        )
        with self.engine.connect() as connection:
            rows = connection.execute(statement).mappings().all()
        return {row["ticker"]: self._row_to_position(row) for row in rows}

    def remove_position(self, ticker: str) -> None:
        statement = delete(self.positions).where(
            (self.positions.c.portfolio_id == self._portfolio_id)
            & (self.positions.c.ticker == ticker)
            & (self.positions.c.is_open.is_(True))
        )
        with self.engine.begin() as connection:
            connection.execute(statement)

    def add_closed_position(self, position: "Position") -> None:
        # Append-only closed-position history (is_open=False on the row).
        with self.engine.begin() as connection:
            connection.execute(
                insert(self.positions), [self._position_to_row(position)]
            )

    def get_closed_positions(self) -> List["Position"]:
        # Stable order by (exit_date, id) — Postgres has no implicit insertion order
        # and PortfolioSnapshot-style seq is not modelled for positions (Pitfall 7).
        statement = (
            select(self.positions)
            .where(
                (self.positions.c.portfolio_id == self._portfolio_id)
                & (self.positions.c.is_open.is_(False))
            )
            .order_by(self.positions.c.exit_date.asc(), self.positions.c.id.asc())
        )
        with self.engine.connect() as connection:
            rows = connection.execute(statement).mappings().all()
        return [self._row_to_position(row) for row in rows]

    # -- Transactions (append-only history) ----------------------------------

    def _transaction_to_row(self, transaction: "Transaction") -> dict[str, Any]:
        """Map a ``Transaction`` to a ``transactions`` row (portfolio_id injected)."""
        return {
            "id": transaction.id,
            "portfolio_id": self._portfolio_id,
            "fill_id": transaction.fill_id,
            "position_id": transaction.position_id,
            "venue_trade_id": transaction.venue_trade_id,
            "time": transaction.time,
            "type": transaction.type.value,
            "ticker": transaction.ticker,
            "price": transaction.price,
            "quantity": transaction.quantity,
            "commission": transaction.commission,
            "leverage": transaction.leverage,
        }

    def _row_to_transaction(self, row: Any) -> "Transaction":
        """Rebuild a ``Transaction`` (msgspec.Struct — field-wise ``==``) from a row."""
        position_id = (
            None if row["position_id"] is None else PositionId(row["position_id"])
        )
        return Transaction(
            row["time"],
            TransactionType(row["type"]),
            row["ticker"],
            row["price"],
            row["quantity"],
            row["commission"],
            row["portfolio_id"],
            TransactionId(row["id"]),
            fill_id=row["fill_id"],
            position_id=position_id,
            venue_trade_id=row["venue_trade_id"],
            leverage=row["leverage"],
        )

    def add_transaction(self, transaction: "Transaction") -> None:
        with self.engine.begin() as connection:
            connection.execute(
                insert(self.transactions), [self._transaction_to_row(transaction)]
            )

    def get_transaction_history(self) -> List["Transaction"]:
        # Stable append-only order by (time, id) — Pitfall 7.
        statement = (
            select(self.transactions)
            .where(self.transactions.c.portfolio_id == self._portfolio_id)
            .order_by(self.transactions.c.time.asc(), self.transactions.c.id.asc())
        )
        with self.engine.connect() as connection:
            rows = connection.execute(statement).mappings().all()
        return [self._row_to_transaction(row) for row in rows]

    # -- Cash reservations (reference_id → amount, full precision) -----------

    def get_reserved_cash(self) -> Decimal:
        statement = select(self.cash_reservations.c.amount).where(
            self.cash_reservations.c.portfolio_id == self._portfolio_id
        )
        with self.engine.connect() as connection:
            amounts = connection.execute(statement).scalars().all()
        # Sum in Python (Decimal start) to preserve full precision (in-memory parity).
        return sum(amounts, Decimal("0.00"))

    def add_reservation(self, reference_id: str, amount: Decimal) -> None:
        # Upsert by (portfolio_id, reference_id): portable insert-or-replace.
        with self.engine.begin() as connection:
            connection.execute(
                delete(self.cash_reservations).where(
                    (self.cash_reservations.c.portfolio_id == self._portfolio_id)
                    & (self.cash_reservations.c.reference_id == reference_id)
                )
            )
            connection.execute(
                insert(self.cash_reservations),
                [
                    {
                        "portfolio_id": self._portfolio_id,
                        "reference_id": reference_id,
                        "amount": amount,
                    }
                ],
            )

    def pop_reservation(self, reference_id: str) -> Optional[Decimal]:
        with self.engine.begin() as connection:
            row = connection.execute(
                select(self.cash_reservations.c.amount).where(
                    (self.cash_reservations.c.portfolio_id == self._portfolio_id)
                    & (self.cash_reservations.c.reference_id == reference_id)
                )
            ).first()
            if row is None:
                return None
            connection.execute(
                delete(self.cash_reservations).where(
                    (self.cash_reservations.c.portfolio_id == self._portfolio_id)
                    & (self.cash_reservations.c.reference_id == reference_id)
                )
            )
        amount: Decimal = row[0]
        return amount

    # -- Locked margin (position_id str → amount, full precision) ------------

    def get_locked_margin(self) -> Decimal:
        statement = select(self.locked_margin.c.amount).where(
            self.locked_margin.c.portfolio_id == self._portfolio_id
        )
        with self.engine.connect() as connection:
            amounts = connection.execute(statement).scalars().all()
        # Clean Decimal("0") start (Pitfall 6) so the spot subtraction stays byte-exact.
        return sum(amounts, Decimal("0"))

    def get_locked_margin_for(self, position_id: str) -> Decimal:
        statement = select(self.locked_margin.c.amount).where(
            (self.locked_margin.c.portfolio_id == self._portfolio_id)
            & (self.locked_margin.c.position_id == position_id)
        )
        with self.engine.connect() as connection:
            row = connection.execute(statement).first()
        if row is None:
            return Decimal("0")
        amount: Decimal = row[0]
        return amount

    def add_locked_margin(self, position_id: str, amount: Decimal) -> None:
        with self.engine.begin() as connection:
            connection.execute(
                delete(self.locked_margin).where(
                    (self.locked_margin.c.portfolio_id == self._portfolio_id)
                    & (self.locked_margin.c.position_id == position_id)
                )
            )
            connection.execute(
                insert(self.locked_margin),
                [
                    {
                        "portfolio_id": self._portfolio_id,
                        "position_id": position_id,
                        "amount": amount,
                    }
                ],
            )

    def pop_locked_margin(self, position_id: str) -> Optional[Decimal]:
        with self.engine.begin() as connection:
            row = connection.execute(
                select(self.locked_margin.c.amount).where(
                    (self.locked_margin.c.portfolio_id == self._portfolio_id)
                    & (self.locked_margin.c.position_id == position_id)
                )
            ).first()
            if row is None:
                return None
            connection.execute(
                delete(self.locked_margin).where(
                    (self.locked_margin.c.portfolio_id == self._portfolio_id)
                    & (self.locked_margin.c.position_id == position_id)
                )
            )
        amount: Decimal = row[0]
        return amount

    # -- Cash operations (append-only audit) ---------------------------------

    def _cash_operation_to_row(self, operation: Any) -> dict[str, Any]:
        """Map a ``CashOperation`` to a row (portfolio_id injected — not a field, Pitfall 1)."""
        return {
            "operation_id": operation.operation_id,
            "portfolio_id": self._portfolio_id,
            "operation_type": operation.operation_type.value,
            "amount": operation.amount,
            "timestamp": operation.timestamp,
            "description": operation.description,
            "fee": operation.fee,
            "reference_id": operation.reference_id,
            "balance_before": operation.balance_before,
            "balance_after": operation.balance_after,
        }

    def _row_to_cash_operation(self, row: Any) -> CashOperation:
        """Rebuild a ``CashOperation`` (@dataclass — field-wise ``==``); omit portfolio_id."""
        return CashOperation(
            operation_id=row["operation_id"],
            operation_type=CashOperationType(row["operation_type"]),
            amount=row["amount"],
            timestamp=row["timestamp"],
            description=row["description"],
            fee=row["fee"],
            reference_id=row["reference_id"],
            balance_before=row["balance_before"],
            balance_after=row["balance_after"],
        )

    def add_cash_operation(self, operation: Any) -> None:
        with self.engine.begin() as connection:
            connection.execute(
                insert(self.cash_operations), [self._cash_operation_to_row(operation)]
            )

    def get_cash_operations(self) -> List[Any]:
        # Stable order by (timestamp, operation_id) — Pitfall 7.
        statement = (
            select(self.cash_operations)
            .where(self.cash_operations.c.portfolio_id == self._portfolio_id)
            .order_by(
                self.cash_operations.c.timestamp.asc(),
                self.cash_operations.c.operation_id.asc(),
            )
        )
        with self.engine.connect() as connection:
            rows = connection.execute(statement).mappings().all()
        return [self._row_to_cash_operation(row) for row in rows]

    # -- Metrics snapshots (append-only history, explicit per-portfolio seq) --

    def _snapshot_to_row(self, snapshot: Any, seq: int) -> dict[str, Any]:
        """Map a ``PortfolioSnapshot`` to a row (portfolio_id + explicit seq injected)."""
        return {
            "portfolio_id": self._portfolio_id,
            "seq": seq,
            "timestamp": snapshot.timestamp,
            "total_equity": snapshot.total_equity,
            "cash_balance": snapshot.cash_balance,
            "positions_value": snapshot.positions_value,
            "unrealized_pnl": snapshot.unrealized_pnl,
            "realized_pnl": snapshot.realized_pnl,
            "total_pnl": snapshot.total_pnl,
            "open_positions_count": snapshot.open_positions_count,
            "portfolio_return": snapshot.portfolio_return,
            "benchmark_return": snapshot.benchmark_return,
        }

    def _row_to_snapshot(self, row: Any) -> PortfolioSnapshot:
        """Rebuild a ``PortfolioSnapshot`` (@dataclass — field-wise ``==``); omit portfolio_id/seq."""
        return PortfolioSnapshot(
            timestamp=row["timestamp"],
            total_equity=row["total_equity"],
            cash_balance=row["cash_balance"],
            positions_value=row["positions_value"],
            unrealized_pnl=row["unrealized_pnl"],
            realized_pnl=row["realized_pnl"],
            total_pnl=row["total_pnl"],
            open_positions_count=row["open_positions_count"],
            portfolio_return=row["portfolio_return"],
            benchmark_return=row["benchmark_return"],
        )

    def _next_snapshot_seq(self, connection: Any) -> int:
        """Next monotonic per-portfolio ``seq`` (MAX+1; backend-written, NOT autoincrement)."""
        max_seq = connection.execute(
            select(func.max(self.equity_snapshots.c.seq)).where(
                self.equity_snapshots.c.portfolio_id == self._portfolio_id
            )
        ).scalar()
        return 0 if max_seq is None else int(max_seq) + 1

    def add_snapshot(self, snapshot: Any) -> None:
        with self.engine.begin() as connection:
            seq = self._next_snapshot_seq(connection)
            connection.execute(
                insert(self.equity_snapshots),
                [self._snapshot_to_row(snapshot, seq)],
            )

    def get_snapshots(self) -> List[Any]:
        statement = (
            select(self.equity_snapshots)
            .where(self.equity_snapshots.c.portfolio_id == self._portfolio_id)
            .order_by(self.equity_snapshots.c.seq.asc())
        )
        with self.engine.connect() as connection:
            rows = connection.execute(statement).mappings().all()
        return [self._row_to_snapshot(row) for row in rows]

    def set_snapshots(self, snapshots: List[Any]) -> None:
        # Replace the whole history, re-numbering seq 0..n-1 (stable order preserved).
        with self.engine.begin() as connection:
            connection.execute(
                delete(self.equity_snapshots).where(
                    self.equity_snapshots.c.portfolio_id == self._portfolio_id
                )
            )
            rows = [
                self._snapshot_to_row(snapshot, seq)
                for seq, snapshot in enumerate(snapshots)
            ]
            if rows:
                connection.execute(insert(self.equity_snapshots), rows)

    def snapshot_count(self) -> int:
        statement = select(func.count()).select_from(self.equity_snapshots).where(
            self.equity_snapshots.c.portfolio_id == self._portfolio_id
        )
        with self.engine.connect() as connection:
            count = connection.execute(statement).scalar()
        return 0 if count is None else int(count)

    def get_latest_snapshot(self) -> Optional[Any]:
        statement = (
            select(self.equity_snapshots)
            .where(self.equity_snapshots.c.portfolio_id == self._portfolio_id)
            .order_by(self.equity_snapshots.c.seq.desc())
            .limit(1)
        )
        with self.engine.connect() as connection:
            row = connection.execute(statement).mappings().first()
        return None if row is None else self._row_to_snapshot(row)

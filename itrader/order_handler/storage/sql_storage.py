"""Concrete ``SqlOrderStorage`` — the order-mirror backend on the shared SQL spine (OPS-01).

The first of the three operational ``Sql<Concern>Storage`` classes (order / portfolio-state /
signal). It *composes* a ``SqlEngine`` by reference (has-a, D-04 — never a cross-concern god
base), registers the two order tables on ``backend.metadata`` via ``build_order_tables``, and
calls ``metadata.create_all(checkfirst=True)`` so schema creation is idempotent (tests/dev;
the deploy path uses Alembic). This mirrors the existing concrete analogs
``results/sql_storage.py`` and ``price_handler/store/sql_store.py``.

It fills the retired-and-deleted ``PostgreSQLOrderStorage`` ``NotImplementedError`` stub (D-05)
and implements the full ``OrderStorage`` ABC via *parameterized* SQLAlchemy Core (constant
``Table``/``Column`` objects + bound values, never f-string SQL — SEC-01 / T-03-03).

Round-trip contract (D-10): an ``Order`` is a field-wise ``@dataclass`` whose ``__eq__``
includes ``state_changes`` and ``child_order_ids``. So a faithful round-trip persists the
``state_changes`` to the ``order_state_changes`` child table (``seq``-ordered) and rebuilds
``child_order_ids`` by querying the self-referential ``parent_order_id`` index (Pitfall 6 —
``child_order_ids`` is NOT a column, D-02). Money columns are Postgres-native ``Numeric`` and
read back as exact ``Decimal`` (OPS-04).

The store stays quarantined: it is NOT re-exported from any package ``__init__`` (importing it
pulls SQLAlchemy), so the backtest import path stays SQL-free (GATE-01 inertness). 4-space
indentation (matches the existing ``order_handler/storage`` siblings).
"""

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

from sqlalchemy import (
    Connection,
    RowMapping,
    bindparam,
    delete,
    func,
    insert,
    select,
    update,
)

from itrader.config import TrailType
from itrader.core.enums import (
    OrderStatus,
    OrderTriggerSource,
    OrderType,
    Side,
)
from itrader.core.ids import OrderId, PortfolioId, StrategyId
from itrader.logger import get_itrader_logger
from itrader.storage import SqlEngine

from ..base import IdLike, OrderStorage
from ..order import Order, OrderStateChange
from .models import build_order_tables

# The active predicate as stored ``.value`` text (D-10) — kept in lockstep with
# ``Order.is_active`` (PENDING / PARTIALLY_FILLED). A single home for the SQL WHERE filter.
_ACTIVE_STATUS_VALUES: list[str] = [
    OrderStatus.PENDING.value,
    OrderStatus.PARTIALLY_FILLED.value,
]


class SqlOrderStorage(OrderStorage):
    """Concrete order-mirror store composing the shared SQL spine (OPS-01, D-04/D-05/D-06).

    Parameters
    ----------
    backend:
        The shared spine (Engine + MetaData). The driver/URL is selected by config at
        wiring; the store registers its two tables on ``backend.metadata`` and creates them
        idempotently (``checkfirst=True``).
    """

    def __init__(self, backend: SqlEngine) -> None:
        self.backend = backend
        self.engine = backend.engine

        tables = build_order_tables(backend.metadata)
        self.orders = tables["orders"]
        self.state_changes = tables["order_state_changes"]

        # Idempotent, ephemeral schema creation (tests/dev; deploy uses Alembic).
        backend.metadata.create_all(self.engine, checkfirst=True)

        # T-03-03 — search_orders resolves criteria keys through this allow-list of bound
        # Column objects, NEVER an interpolated column name. A key outside the map yields no
        # match (mirrors the in-memory ``hasattr`` guard).
        self._searchable: Dict[str, Any] = {
            "ticker": self.orders.c.ticker,
            "status": self.orders.c.status,
            "action": self.orders.c.action,
            "type": self.orders.c.type,
            "exchange": self.orders.c.exchange,
            "portfolio_id": self.orders.c.portfolio_id,
            "strategy_id": self.orders.c.strategy_id,
            "parent_order_id": self.orders.c.parent_order_id,
        }

        self.logger = get_itrader_logger().bind(component="SqlOrderStorage")

    def dispose(self) -> None:
        """Dispose the shared backend engine (WR-03 — delegate, never engine.dispose())."""
        self.backend.dispose()

    # ------------------------------------------------------------------ row codec (D-10)
    def _order_to_row(self, order: Order) -> Dict[str, Any]:
        """Map every ``Order`` field to its ``orders`` column (enums -> ``.value``, D-07).

        ``child_order_ids`` is intentionally absent (D-02 — derived on read); ``state_changes``
        is persisted separately into the child table.
        """
        return {
            "id": order.id,
            "time": order.time,
            "type": order.type.value,
            "status": order.status.value,
            "ticker": order.ticker,
            "action": order.action.value,
            "price": order.price,
            "quantity": order.quantity,
            "exchange": order.exchange,
            "strategy_id": order.strategy_id,
            "portfolio_id": order.portfolio_id,
            "filled_quantity": order.filled_quantity,
            "created_at": order.created_at,
            "updated_at": order.updated_at,
            "filled_at": order.filled_at,
            "cancelled_at": order.cancelled_at,
            "expired_at": order.expired_at,
            "expiry_time": order.expiry_time,
            "parent_order_id": order.parent_order_id,
            "rejection_reason": order.rejection_reason,
            "modification_count": order.modification_count,
            "last_modification_time": order.last_modification_time,
            "leverage": order.leverage,
            "trail_type": order.trail_type.value if order.trail_type is not None else None,
            "trail_value": order.trail_value,
            # 05-07 (RECON-05 / Open Question 3): the venue order id round-trips (None
            # on backtest/paper orders) so a rehydrated bracket leg re-links confidently.
            "venue_order_id": order.venue_order_id,
        }

    def _state_change_rows(self, order: Order) -> List[Dict[str, Any]]:
        """Flatten ``order.state_changes`` to ``order_state_changes`` rows (``seq``-ordered)."""
        rows: List[Dict[str, Any]] = []
        for seq, change in enumerate(order.state_changes):
            rows.append(
                {
                    "order_id": order.id,
                    "seq": seq,
                    "from_status": (
                        change.from_status.value
                        if change.from_status is not None
                        else None
                    ),
                    "to_status": change.to_status.value,
                    "timestamp": change.timestamp,
                    "reason": change.reason,
                    "triggered_by": change.triggered_by.value,
                    "additional_data": change.additional_data,
                }
            )
        return rows

    def _row_to_order(self, row: RowMapping, conn: Connection) -> Order:
        """Rebuild an ``Order`` from an ``orders`` row (D-10 field-wise round-trip).

        Enum columns are validated back through their enum constructor (D-07); ``state_changes``
        are loaded from the child table ``seq``-ordered; ``child_order_ids`` is rebuilt from the
        ``parent_order_id`` index (Pitfall 6).
        """
        order_id = uuid.UUID(str(row["id"])) if not isinstance(row["id"], uuid.UUID) else row["id"]
        parent_raw = row["parent_order_id"]
        trail_raw = row["trail_type"]
        return Order(
            time=row["time"],
            type=OrderType(row["type"]),
            status=OrderStatus(row["status"]),
            ticker=row["ticker"],
            action=Side(row["action"]),
            price=row["price"],
            quantity=row["quantity"],
            exchange=row["exchange"],
            strategy_id=StrategyId(row["strategy_id"]),
            portfolio_id=PortfolioId(row["portfolio_id"]),
            id=OrderId(order_id),
            filled_quantity=row["filled_quantity"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            filled_at=row["filled_at"],
            cancelled_at=row["cancelled_at"],
            expired_at=row["expired_at"],
            expiry_time=row["expiry_time"],
            state_changes=self._load_state_changes(conn, row["id"]),
            parent_order_id=OrderId(parent_raw) if parent_raw is not None else None,
            child_order_ids=self._load_child_ids(conn, row["id"]),
            rejection_reason=row["rejection_reason"],
            modification_count=row["modification_count"],
            last_modification_time=row["last_modification_time"],
            leverage=row["leverage"],
            trail_type=TrailType(trail_raw) if trail_raw is not None else None,
            trail_value=row["trail_value"],
            # 05-07 (RECON-05 / Open Question 3): round-trip the persisted venue order id.
            venue_order_id=row["venue_order_id"],
        )

    def _load_state_changes(
        self, conn: Connection, order_id: Any
    ) -> List[OrderStateChange]:
        """Load an order's ``OrderStateChange`` list from the child table, ``seq``-ordered."""
        statement = (
            select(self.state_changes)
            .where(self.state_changes.c.order_id == bindparam("oid"))
            .order_by(self.state_changes.c.seq)
        )
        rows = conn.execute(statement, {"oid": order_id}).mappings().all()
        return [
            OrderStateChange(
                from_status=(
                    OrderStatus(r["from_status"]) if r["from_status"] is not None else None
                ),
                to_status=OrderStatus(r["to_status"]),
                timestamp=r["timestamp"],
                reason=r["reason"],
                triggered_by=OrderTriggerSource(r["triggered_by"]),
                additional_data=r["additional_data"],
            )
            for r in rows
        ]

    def _load_child_ids(self, conn: Connection, order_id: Any) -> List[OrderId]:
        """Rebuild ``child_order_ids`` via the self-referential ``parent_order_id`` index.

        Pitfall 6 — ``child_order_ids`` is derived, not stored. Stable ``ORDER BY`` (Pitfall 7).
        """
        statement = (
            select(self.orders.c.id)
            .where(self.orders.c.parent_order_id == bindparam("pid"))
            .order_by(self.orders.c.created_at, self.orders.c.id)
        )
        return [OrderId(v) for v in conn.execute(statement, {"pid": order_id}).scalars().all()]

    # ------------------------------------------------------------------ query helper
    def _query_orders(self, *whereclauses: Any) -> List[Order]:
        """Run a parameterized ``orders`` SELECT (stable ``ORDER BY``) and rebuild Orders.

        Always orders by ``(created_at, id)`` — Postgres has no implicit insertion order
        (Pitfall 7). The child-table / bracket sub-queries reuse the same connection.
        """
        statement = select(self.orders).order_by(
            self.orders.c.created_at, self.orders.c.id
        )
        if whereclauses:
            statement = statement.where(*whereclauses)
        with self.engine.connect() as conn:
            rows = conn.execute(statement).mappings().all()
            return [self._row_to_order(r, conn) for r in rows]

    # ------------------------------------------------------------------ writes
    def add_order(self, order: Order) -> None:
        """Insert one order row + its state-change rows in ONE transaction (Pitfall 6).

        The parent ``orders`` row is inserted BEFORE the dependent ``order_state_changes``
        rows so the child-table FK is satisfied.
        """
        order_row = self._order_to_row(order)
        change_rows = self._state_change_rows(order)
        with self.engine.begin() as conn:
            conn.execute(insert(self.orders), [order_row])
            if change_rows:
                conn.execute(insert(self.state_changes), change_rows)

    def update_order(self, order: Order) -> bool:
        """Update an existing order and REPLACE its state-change rows (D-10 faithful).

        Returns ``False`` if the order id is unknown (mirrors the in-memory contract).
        """
        with self.engine.begin() as conn:
            exists = conn.execute(
                select(self.orders.c.id).where(self.orders.c.id == bindparam("oid")),
                {"oid": order.id},
            ).first()
            if exists is None:
                return False
            row = self._order_to_row(order)
            row.pop("id")
            conn.execute(
                update(self.orders).where(self.orders.c.id == bindparam("oid")).values(**row),
                {"oid": order.id},
            )
            conn.execute(
                delete(self.state_changes).where(
                    self.state_changes.c.order_id == bindparam("oid")
                ),
                {"oid": order.id},
            )
            change_rows = self._state_change_rows(order)
            if change_rows:
                conn.execute(insert(self.state_changes), change_rows)
        return True

    def remove_order(self, order_id: IdLike, portfolio_id: Optional[IdLike] = None) -> bool:
        """Remove an order (and its state-change rows) by id; optional portfolio guard."""
        if not isinstance(order_id, uuid.UUID):
            return False
        with self.engine.begin() as conn:
            match_clause = [self.orders.c.id == order_id]
            if portfolio_id is not None:
                match_clause.append(self.orders.c.portfolio_id == portfolio_id)
            match = conn.execute(select(self.orders.c.id).where(*match_clause)).first()
            if match is None:
                return False
            conn.execute(
                delete(self.state_changes).where(
                    self.state_changes.c.order_id == order_id
                )
            )
            conn.execute(delete(self.orders).where(self.orders.c.id == order_id))
        return True

    def remove_orders_by_ticker(self, ticker: str, portfolio_id: IdLike) -> int:
        """Remove all ACTIVE orders for a ticker in a portfolio (in-memory parity, D-07)."""
        return self._delete_active(
            self.orders.c.ticker == ticker,
            self.orders.c.portfolio_id == portfolio_id,
        )

    def clear_portfolio_orders(self, portfolio_id: IdLike) -> int:
        """Clear all ACTIVE orders for a portfolio (in-memory parity, D-07)."""
        return self._delete_active(self.orders.c.portfolio_id == portfolio_id)

    def _delete_active(self, *whereclauses: Any) -> int:
        """Delete ACTIVE orders matching ``whereclauses`` (+ their state-change rows)."""
        with self.engine.begin() as conn:
            ids = list(
                conn.execute(
                    select(self.orders.c.id).where(
                        self.orders.c.status.in_(_ACTIVE_STATUS_VALUES), *whereclauses
                    )
                ).scalars().all()
            )
            if not ids:
                return 0
            conn.execute(
                delete(self.state_changes).where(
                    self.state_changes.c.order_id.in_(ids)
                )
            )
            conn.execute(delete(self.orders).where(self.orders.c.id.in_(ids)))
        return len(ids)

    # ------------------------------------------------------------------ reads
    def get_order_by_id(
        self, order_id: IdLike, portfolio_id: Optional[IdLike] = None
    ) -> Optional[Order]:
        """Get a specific order by id (optional portfolio guard); rebuild fully."""
        if not isinstance(order_id, uuid.UUID):
            return None
        clauses = [self.orders.c.id == order_id]
        if portfolio_id is not None:
            clauses.append(self.orders.c.portfolio_id == portfolio_id)
        statement = select(self.orders).where(*clauses)
        with self.engine.connect() as conn:
            row = conn.execute(statement).mappings().first()
            if row is None:
                return None
            return self._row_to_order(row, conn)

    def get_pending_orders(
        self, portfolio_id: Optional[IdLike] = None
    ) -> Dict[Any, Dict[Any, Order]]:
        """Active orders grouped by portfolio (derived nested view; in-memory parity)."""
        if portfolio_id is not None:
            orders = self._query_orders(
                self.orders.c.status.in_(_ACTIVE_STATUS_VALUES),
                self.orders.c.portfolio_id == portfolio_id,
            )
            return {portfolio_id: {o.id: o for o in orders}}
        orders = self._query_orders(self.orders.c.status.in_(_ACTIVE_STATUS_VALUES))
        result: Dict[Any, Dict[Any, Order]] = {}
        for order in orders:
            result.setdefault(order.portfolio_id, {})[order.id] = order
        return result

    def get_orders_by_ticker(
        self, ticker: str, portfolio_id: Optional[IdLike] = None
    ) -> List[Order]:
        """Get all orders for a ticker (optional portfolio filter)."""
        clauses: List[Any] = [self.orders.c.ticker == ticker]
        if portfolio_id is not None:
            clauses.append(self.orders.c.portfolio_id == portfolio_id)
        return self._query_orders(*clauses)

    def get_orders_by_status(
        self, status: OrderStatus, portfolio_id: Optional[IdLike] = None
    ) -> List[Order]:
        """Get orders by status (optional portfolio filter)."""
        clauses: List[Any] = [self.orders.c.status == status.value]
        if portfolio_id is not None:
            clauses.append(self.orders.c.portfolio_id == portfolio_id)
        return self._query_orders(*clauses)

    def get_active_orders(self, portfolio_id: Optional[IdLike] = None) -> List[Order]:
        """Get all active orders (PENDING / PARTIALLY_FILLED), optional portfolio filter."""
        clauses: List[Any] = [self.orders.c.status.in_(_ACTIVE_STATUS_VALUES)]
        if portfolio_id is not None:
            clauses.append(self.orders.c.portfolio_id == portfolio_id)
        return self._query_orders(*clauses)

    def get_orders_by_time_range(
        self,
        start_time: datetime,
        end_time: datetime,
        portfolio_id: Optional[IdLike] = None,
    ) -> List[Order]:
        """Get orders whose ``created_at`` falls within ``[start_time, end_time]``.

        WR-03 — ``created_at`` binds through ``UtcIsoText``, which RAISES ``ValueError`` on a
        timezone-naive datetime. Normalize the bounds to tz-aware UTC at this method boundary
        (documented + deterministic) so a naive bound does not escape as a raw codec error
        mid-query; the lexicographic ISO-text compare is then a consistent UTC comparison.
        """
        start_time = self._ensure_utc(start_time)
        end_time = self._ensure_utc(end_time)
        clauses: List[Any] = [
            self.orders.c.created_at >= start_time,
            self.orders.c.created_at <= end_time,
        ]
        if portfolio_id is not None:
            clauses.append(self.orders.c.portfolio_id == portfolio_id)
        return self._query_orders(*clauses)

    def get_order_history(self, order_id: IdLike) -> List[Dict[str, Any]]:
        """Return the order's state-change history as a list of plain dicts (in-memory shape)."""
        if not isinstance(order_id, uuid.UUID):
            return []
        statement = (
            select(self.state_changes)
            .where(self.state_changes.c.order_id == bindparam("oid"))
            .order_by(self.state_changes.c.seq)
        )
        with self.engine.connect() as conn:
            rows = conn.execute(statement, {"oid": order_id}).mappings().all()
        history: List[Dict[str, Any]] = []
        for r in rows:
            from_value = r["from_status"]
            timestamp = r["timestamp"]
            history.append(
                {
                    "from_status": OrderStatus(from_value).name if from_value is not None else None,
                    "to_status": OrderStatus(r["to_status"]).name,
                    "timestamp": timestamp.isoformat() if timestamp is not None else None,
                    "reason": r["reason"],
                    "triggered_by": OrderTriggerSource(r["triggered_by"]).value,
                    "additional_data": r["additional_data"],
                }
            )
        return history

    def search_orders(
        self, criteria: Dict[str, Any], portfolio_id: Optional[IdLike] = None
    ) -> List[Order]:
        """Search orders by an allow-listed ``criteria`` dict (T-03-03 bound columns)."""
        clauses: List[Any] = []
        for key, value in criteria.items():
            column = self._searchable.get(key)
            if column is None:
                # An un-allow-listed key matches nothing (mirrors the in-memory hasattr guard).
                return []
            clauses.append(column == self._encode_criteria(value))
        if portfolio_id is not None:
            clauses.append(self.orders.c.portfolio_id == portfolio_id)
        return self._query_orders(*clauses)

    @staticmethod
    def _ensure_utc(bound: datetime) -> datetime:
        """Coerce a time-range bound to a tz-aware UTC datetime (WR-03).

        A naive bound is assumed UTC and stamped tz-aware; an aware bound is converted to
        UTC. This keeps ``get_orders_by_time_range`` from leaking the ``UtcIsoText``
        ``ValueError`` (naive-datetime rejection) out of the query method.
        """
        if bound.tzinfo is None:
            return bound.replace(tzinfo=timezone.utc)
        return bound.astimezone(timezone.utc)

    @staticmethod
    def _encode_criteria(value: Any) -> Any:
        """Convert an enum criterion to its stored ``.value`` (D-07); pass others through."""
        if isinstance(value, Enum):
            return value.value
        return value

    def count_orders_by_status(
        self, portfolio_id: Optional[IdLike] = None
    ) -> Dict[str, int]:
        """Count orders grouped by status (status NAME -> count; in-memory parity)."""
        statement = select(self.orders.c.status, func.count()).group_by(
            self.orders.c.status
        )
        if portfolio_id is not None:
            statement = statement.where(self.orders.c.portfolio_id == portfolio_id)
        with self.engine.connect() as conn:
            rows = conn.execute(statement).all()
        return {OrderStatus(value).name: count for value, count in rows}

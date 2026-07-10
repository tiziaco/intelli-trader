"""Concrete ``SqlSignalStorage`` — the signal store on the shared SQL spine (OPS-03).

The strategy/signal operational backend: it *composes* a ``SqlEngine`` by reference
(has-a, D-04 — never a cross-concern god base) and registers the single ``signals`` table on
``backend.metadata`` via ``build_signal_tables``. It is schema-pure (WR-03/D-14 — no runtime
``create_all``): the durable schema is Alembic-owned in production and provisioned by
``tests.support.schema.provision_schema`` in tests. This mirrors the existing concrete-store
analog, ``results/sql_storage.py`` (composition, ``dispose`` delegation, ``bindparam`` reads,
``engine.begin`` writes).

The 4-method ``SignalStore`` ABC is implemented over parameterized SQLAlchemy Core (constant
``Table``/``Column`` objects + ``bindparam`` — never f-string SQL, T-03-13 / SEC-01):

- ``add`` writes one row (enums → ``.value``; config dict → json_variant; money as Decimal).
- ``get_all`` SELECTs ordered by a stable insertion key (``time`` then ``signal_id`` tiebreak).
- ``by_strategy`` / ``by_ticker`` add an indexed WHERE filter — no cross-strategy/ticker bleed
  (T-03-15).

Money is Postgres-native ``Numeric`` and reads back as exact ``Decimal`` (OPS-04 / Pitfall 2 —
money never touches a SQLite-family backend). The ``config`` params dict round-trips as a
decoded dict (value equality, NOT JSON byte identity — Pitfall 8 / A6).

The class stays quarantined: it is NOT re-exported from
``itrader/strategy_handler/storage/__init__.py`` (importing it pulls SQLAlchemy), so the
backtest signal path stays SQL-free (GATE-01 inertness — mirrors ``itrader/storage/__init__``).
4-space indentation (matches the ``strategy_handler/storage/`` siblings).
"""

from decimal import Decimal
from typing import Any, List

from sqlalchemy import bindparam, insert, select

from itrader.core.enums import OrderType, Side, order_type_map
from itrader.core.ids import SignalId, StrategyId
from itrader.logger import get_itrader_logger
from itrader.storage import SqlEngine
from itrader.strategy_handler.signal_record import SignalRecord
from itrader.strategy_handler.storage.base import SignalStore
from itrader.strategy_handler.storage.models import build_signal_tables


class SqlSignalStorage(SignalStore):
    """Concrete signal store composing the shared SQL spine (OPS-03, D-04).

    Parameters
    ----------
    sql_engine:
        The shared spine (Engine + MetaData). The driver/URL is selected by config at
        wiring; the signal store registers its ``signals`` table on ``sql_engine.metadata`` but
        does NOT create it — the durable schema is Alembic-owned in production (WR-03/D-14) and
        provisioned by the shared ``provision_schema`` test fixture in tests.
    """

    def __init__(self, sql_engine: SqlEngine) -> None:
        self.backend = sql_engine
        self.engine = sql_engine.engine

        tables = build_signal_tables(sql_engine.metadata)
        self.signals = tables["signals"]

        # WR-03/D-14 — schema-pure: register the table, never create it. On the live Postgres
        # path the Alembic chain owns the migration; tests provision via
        # tests.support.schema.provision_schema.

        self.logger = get_itrader_logger().bind(component="SqlSignalStorage")

    def dispose(self) -> None:
        """Dispose the shared backend engine (delegate, never engine.dispose())."""
        self.backend.dispose()

    # ------------------------------------------------------------------ codec
    def _to_row(self, record: SignalRecord) -> dict[str, Any]:
        """Project a ``SignalRecord`` to a ``signals`` row dict (enums → ``.value``)."""
        return {
            "signal_id": record.signal_id,
            "strategy_id": record.strategy_id,
            "ticker": record.ticker,
            "time": record.time,
            "action": record.action.value,
            "order_type": record.order_type.value,
            "stop_loss": record.stop_loss,
            "take_profit": record.take_profit,
            "exit_fraction": record.exit_fraction,
            "quantity": record.quantity,
            "entry_price": record.entry_price,
            "config": record.config,
        }

    def _from_row(self, row: Any) -> SignalRecord:
        """Rebuild a ``SignalRecord`` from a ``signals`` result-row mapping.

        Enums are parsed back via ``Side(value)`` / ``order_type_map`` (the house
        string→enum maps); money reads back as exact ``Decimal`` (Postgres-native Numeric,
        OPS-04); ``config`` round-trips as a decoded dict (Pitfall 8 — value equality).
        """
        return SignalRecord(
            signal_id=SignalId(row["signal_id"]),
            strategy_id=StrategyId(row["strategy_id"]),
            ticker=row["ticker"],
            time=row["time"],
            action=Side(row["action"]),
            order_type=order_type_map[row["order_type"]],
            stop_loss=self._as_decimal(row["stop_loss"]),
            take_profit=self._as_decimal(row["take_profit"]),
            exit_fraction=Decimal(row["exit_fraction"]),
            quantity=self._as_decimal(row["quantity"]),
            entry_price=self._as_decimal(row["entry_price"]),
            config=row["config"] or {},
        )

    @staticmethod
    def _as_decimal(value: Any) -> Decimal | None:
        """Coerce a nullable Numeric column back to ``Decimal | None`` (OPS-04)."""
        if value is None:
            return None
        return Decimal(value)

    # ------------------------------------------------------------------ writes
    def add(self, record: SignalRecord) -> None:
        """Persist one ``SignalRecord`` as a ``signals`` row (parameterized Core insert)."""
        with self.engine.begin() as connection:
            connection.execute(insert(self.signals), [self._to_row(record)])

    # ------------------------------------------------------------------ reads
    def get_all(self) -> List[SignalRecord]:
        """Return every stored record ordered by a stable insertion key.

        ORDER BY ``time`` then ``signal_id`` (UUIDv7 — monotonic in generation) gives a
        deterministic, insertion-stable order across both dialects.
        """
        statement = select(self.signals).order_by(
            self.signals.c.time.asc(), self.signals.c.signal_id.asc()
        )
        with self.engine.connect() as connection:
            rows = connection.execute(statement).mappings().all()
        return [self._from_row(row) for row in rows]

    def by_strategy(self, strategy_id: StrategyId) -> List[SignalRecord]:
        """Return only the records produced by ``strategy_id`` (indexed WHERE filter)."""
        statement = (
            select(self.signals)
            .where(self.signals.c.strategy_id == bindparam("strategy_id"))
            .order_by(self.signals.c.time.asc(), self.signals.c.signal_id.asc())
        )
        with self.engine.connect() as connection:
            rows = connection.execute(
                statement, {"strategy_id": strategy_id}
            ).mappings().all()
        return [self._from_row(row) for row in rows]

    def by_ticker(self, ticker: str) -> List[SignalRecord]:
        """Return only the records targeting ``ticker`` (indexed WHERE filter)."""
        statement = (
            select(self.signals)
            .where(self.signals.c.ticker == bindparam("ticker"))
            .order_by(self.signals.c.time.asc(), self.signals.c.signal_id.asc())
        )
        with self.engine.connect() as connection:
            rows = connection.execute(
                statement, {"ticker": ticker}
            ).mappings().all()
        return [self._from_row(row) for row in rows]

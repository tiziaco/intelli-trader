"""Core ``Table`` definitions for the portfolio-state operational store (OPS-02, D-03).

SQLAlchemy **Core** (not declarative ORM) — mirroring ``itrader/results/models.py``'s
idempotent registrar. ``build_portfolio_tables`` registers seven normalized tables on the
injected ``backend.metadata`` and is idempotent on a shared backend (reuse an
already-registered table, the same guard as the results store).

The seven tables map the four portfolio-manager collections the
``PortfolioStateStorage`` ABC owns (plus the Phase-4 account-state carrier):

  * ``positions`` — open + closed positions (D-03 ``is_open`` flag), one row per Position.
  * ``transactions`` — append-only transaction history.
  * ``cash_reservations`` — ``reference_id → amount`` working state (full precision).
  * ``locked_margin`` — ``position_id → amount`` working state (full precision, A2: the
    ABC types ``position_id: str`` so the key column is ``String``, not ``Uuid``).
  * ``cash_operations`` — append-only cash audit trail.
  * ``equity_snapshots`` — append-only metrics-snapshot history (explicit per-portfolio
    ``seq`` PK-part, Pitfall 7 / A3 — NOT Integer autoincrement, single-UUID rule).
  * ``portfolio_account_state`` — single-row-per-portfolio account-state carrier (Phase-4
    A2): the latest persisted ``cash_balance`` / ``realized_pnl`` accumulators + the
    ``total_equity`` / ``peak_equity`` / ``open_positions_count`` snapshot, upserted
    synchronously so the latest persisted account state is never behind the working set
    after a crash (D-03). The ``portfolio_id`` IS the primary key (single UUIDv7 key, no
    surrogate/autoincrement) — the ``CachedSqlPortfolioStateStorage`` wrapper writes it via
    ``save_account_state`` and reads it via ``load_account_state``; the untouched
    ``SqlPortfolioStateStorage`` (D-04) simply ignores the extra table.

Every table carries a ``portfolio_id`` column: the SQL backend binds a ``portfolio_id`` at
construction (the ABC has NO ``portfolio_id`` parameter) and scopes every query to it
(Pitfall 1). ``cash_operations`` / ``equity_snapshots`` rows additionally carry a
``portfolio_id`` the source objects do NOT have — it is injected by the bound backend.

Column-type vocabulary comes from ``itrader.storage`` (``Uuid`` round-trips to a native
``uuid.UUID`` on both dialects, D-03; ``UtcIsoText`` is deterministic UTC-isoformat
business-time). Money is ``sqlalchemy.Numeric`` direct (Postgres-native exact precision,
OPS-04 — no TypeDecorator; money never touches a SQLite-family backend). 4-space
indentation (matches the ``itrader/results`` SQL layer this file mirrors — D-05).
"""

from sqlalchemy import (
    Boolean,
    Column,
    Index,
    Integer,
    MetaData,
    Numeric,
    String,
    Table,
)

from itrader.storage import Uuid, UtcIsoText


def build_portfolio_tables(metadata: MetaData) -> dict[str, Table]:
    """Register (idempotently) the seven portfolio-state tables on ``metadata`` and return them.

    Parameters
    ----------
    metadata : MetaData
        The shared spine ``MetaData`` (``backend.metadata``). If a table name is already
        registered, the existing ``Table`` is reused — the same shared-backend guard as
        the results store (idempotent append).

    Returns
    -------
    dict[str, Table]
        ``{"positions", "transactions", "cash_reservations", "locked_margin",
        "cash_operations", "equity_snapshots", "portfolio_account_state"}``.
    """
    tables: dict[str, Table] = {}

    # positions — open + closed positions (D-03 is_open flag). PK id (PositionId);
    # composite index (portfolio_id, is_open) for the open-position lookup (D-08).
    # The derived caches (_net_quantity_cache / _avg_price_cache) are NOT persisted.
    if "positions" in metadata.tables:
        tables["positions"] = metadata.tables["positions"]
    else:
        tables["positions"] = Table(
            "positions",
            metadata,
            Column("id", Uuid(as_uuid=True), primary_key=True),
            Column("portfolio_id", Uuid(as_uuid=True), nullable=False),
            Column("ticker", String, nullable=False),
            Column("side", String, nullable=False),
            Column("leverage", Numeric, nullable=False),
            Column("current_price", Numeric, nullable=False),
            Column("current_time", UtcIsoText, nullable=False),
            Column("buy_quantity", Numeric, nullable=False),
            Column("sell_quantity", Numeric, nullable=False),
            Column("avg_bought", Numeric, nullable=False),
            Column("avg_sold", Numeric, nullable=False),
            Column("buy_commission", Numeric, nullable=False),
            Column("sell_commission", Numeric, nullable=False),
            Column("entry_date", UtcIsoText, nullable=False),
            Column("exit_date", UtcIsoText, nullable=True),
            Column("_last_accrual_time", UtcIsoText, nullable=True),
            Column("is_open", Boolean, nullable=False),
            Index("ix_positions_portfolio_open", "portfolio_id", "is_open"),
        )

    # transactions — append-only history. PK id (TransactionId); portfolio_id indexed
    # (bound scope). type is TransactionType.value ("buy"/"sell").
    if "transactions" in metadata.tables:
        tables["transactions"] = metadata.tables["transactions"]
    else:
        tables["transactions"] = Table(
            "transactions",
            metadata,
            Column("id", Uuid(as_uuid=True), primary_key=True),
            Column("portfolio_id", Uuid(as_uuid=True), index=True, nullable=False),
            Column("fill_id", Uuid(as_uuid=True), nullable=False),
            Column("position_id", Uuid(as_uuid=True), nullable=True),
            # CR-01: the venue's own trade id (FIX ExecID / Nautilus TradeId)
            # carried from the FillEvent so the durable settlement record keeps
            # the venue idempotency key. None for backtest/simulated rows.
            Column("venue_trade_id", String, nullable=True),
            Column("time", UtcIsoText, nullable=False),
            Column("type", String, nullable=False),
            Column("ticker", String, nullable=False),
            Column("price", Numeric, nullable=False),
            Column("quantity", Numeric, nullable=False),
            Column("commission", Numeric, nullable=False),
            Column("leverage", Numeric, nullable=False),
        )

    # cash_reservations — reference_id → amount map (D-03). Composite PK
    # (portfolio_id, reference_id String); amount FULL precision (no quantize, OQ4).
    if "cash_reservations" in metadata.tables:
        tables["cash_reservations"] = metadata.tables["cash_reservations"]
    else:
        tables["cash_reservations"] = Table(
            "cash_reservations",
            metadata,
            Column("portfolio_id", Uuid(as_uuid=True), primary_key=True),
            Column("reference_id", String, primary_key=True),
            Column("amount", Numeric, nullable=False),
        )

    # locked_margin — position_id → amount map (D-03). Composite PK
    # (portfolio_id, position_id **String** per A2 — the ABC types position_id: str);
    # amount FULL precision (no quantize).
    if "locked_margin" in metadata.tables:
        tables["locked_margin"] = metadata.tables["locked_margin"]
    else:
        tables["locked_margin"] = Table(
            "locked_margin",
            metadata,
            Column("portfolio_id", Uuid(as_uuid=True), primary_key=True),
            Column("position_id", String, primary_key=True),
            Column("amount", Numeric, nullable=False),
        )

    # cash_operations — append-only audit trail. PK operation_id; portfolio_id is
    # INJECTED by the bound backend (NOT a CashOperation field — Pitfall 1) and indexed.
    # operation_type is CashOperationType.value.
    if "cash_operations" in metadata.tables:
        tables["cash_operations"] = metadata.tables["cash_operations"]
    else:
        tables["cash_operations"] = Table(
            "cash_operations",
            metadata,
            Column("operation_id", Uuid(as_uuid=True), primary_key=True),
            Column("portfolio_id", Uuid(as_uuid=True), index=True, nullable=False),
            Column("operation_type", String, nullable=False),
            Column("amount", Numeric, nullable=False),
            Column("timestamp", UtcIsoText, nullable=False),
            Column("description", String, nullable=False),
            Column("fee", Numeric, nullable=False),
            Column("reference_id", String, nullable=True),
            Column("balance_before", Numeric, nullable=True),
            Column("balance_after", Numeric, nullable=True),
        )

    # equity_snapshots — append-only metrics history. Composite PK (portfolio_id, seq):
    # PortfolioSnapshot has NO id and timestamps can tie, so an explicit per-portfolio
    # monotonic seq is the stable-ordering key (Pitfall 7 / A3) — autoincrement=False
    # keeps the single-UUID / no-second-ID-scheme rule (the backend writes seq, not the DB).
    # portfolio_id is INJECTED by the bound backend (NOT a PortfolioSnapshot field).
    if "equity_snapshots" in metadata.tables:
        tables["equity_snapshots"] = metadata.tables["equity_snapshots"]
    else:
        tables["equity_snapshots"] = Table(
            "equity_snapshots",
            metadata,
            Column("portfolio_id", Uuid(as_uuid=True), primary_key=True),
            Column("seq", Integer, primary_key=True, autoincrement=False),
            Column("timestamp", UtcIsoText, nullable=False),
            Column("total_equity", Numeric, nullable=False),
            Column("cash_balance", Numeric, nullable=False),
            Column("positions_value", Numeric, nullable=False),
            Column("unrealized_pnl", Numeric, nullable=False),
            Column("realized_pnl", Numeric, nullable=False),
            Column("total_pnl", Numeric, nullable=False),
            Column("open_positions_count", Integer, nullable=False),
            Column("portfolio_return", Numeric, nullable=False),
            Column("benchmark_return", Numeric, nullable=True),
        )

    # portfolio_account_state — single row per portfolio (A2 / Phase-4). portfolio_id IS
    # the PK (single UUIDv7 key, no surrogate/autoincrement). Carries the two purge-derived
    # accumulators (cash_balance, realized_pnl) + the latest account snapshot
    # (total_equity, peak_equity, open_positions_count) so the latest persisted account
    # state is never behind the working set after a crash (D-03). updated_time is business
    # `time` (UtcIsoText), never wall-clock. The CachedSqlPortfolioStateStorage wrapper
    # upserts it via save_account_state and reads it via load_account_state; the untouched
    # SqlPortfolioStateStorage (D-04) ignores it.
    if "portfolio_account_state" in metadata.tables:
        tables["portfolio_account_state"] = metadata.tables["portfolio_account_state"]
    else:
        tables["portfolio_account_state"] = Table(
            "portfolio_account_state",
            metadata,
            Column("portfolio_id", Uuid(as_uuid=True), primary_key=True),
            Column("cash_balance", Numeric, nullable=False),
            Column("realized_pnl", Numeric, nullable=False),
            Column("total_equity", Numeric, nullable=False),
            Column("peak_equity", Numeric, nullable=False),
            Column("open_positions_count", Integer, nullable=False),
            Column("updated_time", UtcIsoText, nullable=False),
        )

    return tables

"""Hardened SQL price store — ``SqlHandler`` reworked onto the spine (FL-06 / SEC-01, D-06/07/08).

This file is the FL-06 security target. The previous revision carried three confirmed
injection / disclosure defects, all removed here:

1. **Hardcoded credential (closed).** The old ``init_engine`` built the engine from a
   credential literal embedded in the connection URL (a secret living in VCS history).
   The credential is now sourced exclusively from the spine's secret seam:
   ``Settings.database_url.get_secret_value()`` resolved lazily inside
   ``SqlSettings.engine_url()`` (``SecretStr`` masks ``repr``/``str``/logs). ``SqlHandler``
   composes an injected ``SqlBackend`` and NEVER constructs an engine from a literal URL.

2. **Dynamic-identifier DDL (closed).** The old purge interpolated each symbol into a
   ``DROP TABLE`` statement built by formatting an identifier into a SQL string — a DDL
   injection vector. There is no string-built identifier anywhere in this module now;
   purges are parameterized Core ``DELETE`` against the constant ``prices`` table name.

3. **Symbol-as-table-name (closed).** The old store wrote/read one table *per symbol*,
   using the symbol as a dynamic table identifier (the schema-sprawl + injection surface).
   That is collapsed into a SINGLE ``prices`` table with ``symbol`` as a VALUE column
   (D-07); every read/write/delete filters by a BOUND parameter (``bindparam``), never an
   interpolated identifier. The table name is the literal constant ``"prices"``.

OHLCV is analytical market data (pandas float64) → ``Float`` columns, NOT money-policy
``Decimal`` (D-13: money never touches a SQLite-family backend this milestone). Business
time is encoded uniformly via ``UtcIsoText`` (deterministic UTC-isoformat).

**Single canonical credential source (T-01-15).** The ONE credential seam is
``Settings.database_url`` (env ``ITRADER_DATABASE_URL``, a ``SecretStr``), resolved lazily
on the Postgres arm of ``SqlSettings.engine_url()``. This module adds NO new credential
source. The legacy ``live_trading_system.py`` ``SYSTEM_DB_URL`` env var is a *separate*
D-live seam reading a *different* variable; reconciling it onto ``Settings.database_url``
is document-and-deferred to the live-wiring phase (Open Q4, D-09) — it is intentionally
not re-wired here, so exactly one canonical source exists for this store.

This file is ``mypy --strict`` clean and out of the D-sql override (GATE-02, D-09); no
broad/module-level ignore was added.

The store stays quarantined: it is deliberately NOT re-exported from
``price_handler/store/__init__.py`` (importing it pulls SQLAlchemy), so the backtest
import path stays SQL-free (GATE-01 inertness).
"""

from typing import Any

import pandas as pd
from sqlalchemy import Column, Float, String, Table, bindparam, insert, select

from itrader.config import TIMEZONE
from itrader.logger import get_itrader_logger
from itrader.storage import SqlBackend, UtcIsoText


class SqlHandler:
    """Read/write OHLCV prices through the shared SQL spine (5th ``SqlBackend`` consumer).

    Composition, not inheritance (D-06): the handler holds an injected ``SqlBackend`` by
    reference and registers a single ``prices`` ``Table`` on ``backend.metadata``. All
    access is parameterized Core SQL against the literal ``prices`` table — there are no
    dynamic SQL identifiers and no hardcoded credentials.

    Parameters
    ----------
    backend:
        The shared spine (Engine + MetaData). The engine's driver/URL — and, on the
        Postgres arm, its credential — come from ``SqlSettings``/``Settings`` at wiring;
        the resolved secret URL is NEVER logged.
    """

    def __init__(self, backend: SqlBackend) -> None:
        self.backend = backend
        self.engine = backend.engine

        metadata = backend.metadata
        if "prices" in metadata.tables:
            # Idempotent on a shared backend: reuse the already-registered table.
            self.prices = metadata.tables["prices"]
        else:
            self.prices = Table(
                "prices",
                metadata,
                Column("symbol", String, primary_key=True),
                Column("date", UtcIsoText, primary_key=True),
                Column("open", Float),
                Column("high", Float),
                Column("low", Float),
                Column("close", Float),
                Column("volume", Float),
            )

        # Create only the prices table (checkfirst → idempotent); never CREATE DATABASE.
        self.prices.create(self.engine, checkfirst=True)

        self.logger = get_itrader_logger().bind(component="SQLHandler")
        # NEVER log the resolved secret URL (SecretStr masks repr; do not get_secret_value into a log).
        self.logger.info("Price Database connected")

    def stop_engine(self) -> None:
        """Dispose the shared backend engine (closes pooled connections)."""
        self.engine.dispose()

    def to_database(self, symbol: str, prices: pd.DataFrame, replace: bool = True) -> None:
        """Store OHLCV prices for ``symbol`` in the single ``prices`` table.

        Writes the literal ``prices`` table with ``symbol`` as a VALUE column — the table
        name is a constant and every value is a BOUND parameter, so an attacker-controlled
        ``symbol`` cannot influence SQL structure (D-07/D-08).

        Parameters
        ----------
        symbol:
            Ticker stored in the ``symbol`` value column (never used as an identifier).
        prices:
            Date-indexed OHLCV frame (columns open/high/low/close/volume, any case).
        replace:
            When ``True`` (default) the symbol's existing rows are deleted first (a
            parameterized ``DELETE ... WHERE symbol = :symbol``), then re-inserted;
            otherwise the rows are appended.
        """
        records = self._rows_from_frame(symbol, prices)
        with self.engine.begin() as connection:
            if replace:
                connection.execute(
                    self.prices.delete().where(self.prices.c.symbol == bindparam("symbol")),
                    {"symbol": symbol},
                )
            if records:
                connection.execute(insert(self.prices), records)

    def read_prices(self, symbol: str) -> pd.DataFrame:
        """Read the OHLCV frame for ``symbol`` from the single ``prices`` table.

        Filters by a BOUND parameter (``bindparam("symbol")``) against the constant
        ``prices`` table and orders by ``date`` for a deterministic frame. The ``symbol``
        column is dropped from the returned frame; the index is the business-time ``date``.
        """
        statement = (
            select(self.prices)
            .where(self.prices.c.symbol == bindparam("symbol"))
            .order_by(self.prices.c.date)
        )
        with self.engine.connect() as connection:
            df = pd.read_sql(  # pandas is untyped (Any) — no narrow ignore needed
                statement,
                connection,
                params={"symbol": symbol},
                index_col="date",
            )
        if "symbol" in df.columns:
            df = df.drop(columns=["symbol"])
        # Use the authoritative project timezone (Settings.timezone) so this store's index
        # tz matches its CsvPriceStore sibling and the rest of the system (WR-01). The two
        # stores were accidentally equal only because the default resolves to Europe/Paris.
        df.index = pd.to_datetime(df.index, utc=True).tz_convert(TIMEZONE)
        try:
            df.index.freq = df.index.inferred_freq
        except ValueError:
            # Irregular / too-short spacing — leave freq unset rather than raise.
            pass
        return df

    def get_symbols(self) -> list[str]:
        """Return the distinct symbols stored in the single ``prices`` table (sorted)."""
        statement = select(self.prices.c.symbol).distinct().order_by(self.prices.c.symbol)
        with self.engine.connect() as connection:
            symbols = connection.execute(statement).scalars().all()
        return list(symbols)

    def delete_prices(self, symbol: str | None = None) -> None:
        """Delete stored prices — one symbol (parameterized) or all rows.

        With ``symbol`` set, deletes that symbol's rows via a BOUND parameter; with
        ``symbol=None``, clears the whole ``prices`` table. The constant table name and the
        bound parameter mean no dynamic SQL identifier is ever constructed (D-07/D-08).
        """
        with self.engine.begin() as connection:
            if symbol is None:
                connection.execute(self.prices.delete())
            else:
                connection.execute(
                    self.prices.delete().where(self.prices.c.symbol == bindparam("symbol")),
                    {"symbol": symbol},
                )

    def _rows_from_frame(self, symbol: str, prices: pd.DataFrame) -> list[dict[str, Any]]:
        """Convert a date-indexed OHLCV frame into parameterized insert rows.

        Lowercases column names defensively (CSV providers ship ``Open``/``High``/...),
        normalizes the index to tz-aware UTC datetimes (uniform business-time encoding),
        and emits one ``{symbol, date, open, high, low, close, volume}`` dict per bar.
        """
        frame = prices.copy()
        frame.columns = [str(column).lower() for column in frame.columns]
        frame.index = pd.to_datetime(frame.index, utc=True)
        records: list[dict[str, Any]] = []
        for timestamp, row in frame.iterrows():
            records.append(
                {
                    "symbol": symbol,
                    "date": timestamp.to_pydatetime(),
                    "open": float(row["open"]),
                    "high": float(row["high"]),
                    "low": float(row["low"]),
                    "close": float(row["close"]),
                    "volume": float(row["volume"]),
                }
            )
        return records

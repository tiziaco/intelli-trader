"""Core ``Table`` definitions for the results store (D-05/D-06/D-07/D-08/D-09).

SQLAlchemy **Core** (not declarative ORM) — matching the only existing concrete that
composes the spine (``price_handler/store/sql_store.py``'s ``Table("prices", metadata, ...)``
block). ``build_results_tables`` registers the three tables on the injected
``backend.metadata`` and is idempotent on a shared backend (reuse an already-registered
table, the same guard as ``sql_store.py``).

Column-type vocabulary comes from ``itrader.storage`` (``Uuid`` round-trips to a native
``uuid.UUID`` on both dialects, D-03; ``json_variant()`` is ``JSON`` on SQLite / ``JSONB`` on
Postgres). The 11 metric columns are sourced from ``records.METRIC_NAMES`` — never hand-retyped
(D-08 single source of truth). 4-space indentation (matches the ``itrader/results`` layer).
"""

from sqlalchemy import (
    Column,
    Float,
    ForeignKey,
    LargeBinary,
    MetaData,
    String,
    Table,
)

from itrader.results.records import METRIC_NAMES
from itrader.storage import Uuid, json_variant


def _metric_columns() -> list[Column[float]]:
    """Fresh indexed ``Float`` columns for the 11 rankable metrics (D-08/D-18).

    A new list each call — a ``Column`` object cannot be shared across two ``Table``s.
    """
    return [Column(name, Float, index=True) for name in METRIC_NAMES]


def build_results_tables(metadata: MetaData) -> dict[str, Table]:
    """Register (idempotently) the three results tables on ``metadata`` and return them.

    Parameters
    ----------
    metadata : MetaData
        The shared spine ``MetaData`` (``backend.metadata``). If a table name is already
        registered, the existing ``Table`` is reused — the same shared-backend guard as
        ``sql_store.py`` (D-12 idempotent append).

    Returns
    -------
    dict[str, Table]
        ``{"runs": ..., "run_portfolios": ..., "run_artifacts": ...}``.
    """
    tables: dict[str, Table] = {}

    # runs — one summary row per run (D-05). PK run_id; 11 indexed Float metrics;
    # curated settings JSON; Optuna-FK-ready nullable study_id/trial_id (D-09).
    if "runs" in metadata.tables:
        tables["runs"] = metadata.tables["runs"]
    else:
        tables["runs"] = Table(
            "runs",
            metadata,
            Column("run_id", Uuid(as_uuid=True), primary_key=True),
            *_metric_columns(),
            Column("settings", json_variant()),
            Column("study_id", Uuid(as_uuid=True), nullable=True),
            Column("trial_id", Uuid(as_uuid=True), nullable=True),
        )

    # run_portfolios — one row per portfolio in a run (D-06). Composite PK
    # (run_id, portfolio_id); run_id FKs runs.run_id; same 11 indexed Float metrics.
    if "run_portfolios" in metadata.tables:
        tables["run_portfolios"] = metadata.tables["run_portfolios"]
    else:
        tables["run_portfolios"] = Table(
            "run_portfolios",
            metadata,
            Column(
                "run_id",
                Uuid(as_uuid=True),
                ForeignKey("runs.run_id"),
                primary_key=True,
            ),
            Column("portfolio_id", Uuid(as_uuid=True), primary_key=True),
            Column("name", String),
            *_metric_columns(),
            Column("params", json_variant()),
        )

    # run_artifacts — one gzip-blob row per frame (D-09, NOT exploded per-bar). Composite
    # PK (run_id, portfolio_id, artifact_type); aggregate-level frames (D-07) carry the
    # ALL-ZEROS sentinel portfolio_id (storage maps None <-> sentinel), so portfolio_id is
    # NOT NULL — a nullable PK column is implicitly NOT NULL on Postgres and rejects a NULL
    # insert there (WR-01). artifact_type ∈ {"equity_curve", "trade_log"}; blob is gzip
    # bytes (D-10).
    if "run_artifacts" in metadata.tables:
        tables["run_artifacts"] = metadata.tables["run_artifacts"]
    else:
        tables["run_artifacts"] = Table(
            "run_artifacts",
            metadata,
            Column(
                "run_id",
                Uuid(as_uuid=True),
                ForeignKey("runs.run_id"),
                primary_key=True,
            ),
            Column("portfolio_id", Uuid(as_uuid=True), primary_key=True),
            Column("artifact_type", String, primary_key=True),
            Column("blob", LargeBinary),
        )

    return tables

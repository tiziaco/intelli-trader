"""Concrete ``SqlResultsStore`` — the results store on the shared SQL spine (SPINE-02).

The fourth ``Sql<Concern>Storage`` (after order / portfolio-state / signal): it *composes*
a ``SqlBackend`` by reference (has-a, D-06 — never a cross-concern god base), registers the
three results tables on ``backend.metadata`` via ``build_results_tables``, and calls
``metadata.create_all(checkfirst=True)`` so schema creation is idempotent and ephemeral (no
Alembic — the research store is SQLite, D-12). This mirrors the only existing concrete-store
analog, ``price_handler/store/sql_store.py``.

Writes (D-13):

- ``save_run`` persists the ``runs`` summary row AND its N ``run_portfolios`` rows in ONE
  ``engine.begin()`` transaction (atomic — either the whole run lands or none of it).
- ``save_artifact`` writes one ``run_artifacts`` gzip-blob row in a *separate* transaction.

Frame codec (D-10 / RESULT-04, research PITFALLS 10/11) — byte-deterministic gzip: both
``mtime=0`` AND a fixed ``compresslevel`` are pinned so the same DataFrame encodes to
byte-identical blobs across runs; the ``orient="table"`` JSON (Table Schema) round-trips to
a DTYPE-stable, value-equal DataFrame (CR-01 — ``orient="split"`` was lossy: datetime and
integral-float columns decoded back as ``int64``).

The store stays quarantined: it is NOT re-exported from ``itrader/results/__init__.py``
(importing it pulls SQLAlchemy), so the backtest import path stays SQL-free (GATE-01
inertness — mirrors ``itrader/storage/__init__.py``). 4-space indentation (the
``itrader/results`` layer).
"""

import gzip
import io
import uuid
from typing import Any

import pandas as pd
from sqlalchemy import Column, bindparam, insert, select

from itrader.core.exceptions import ResultsNotFound
from itrader.logger import get_itrader_logger
from itrader.results.base import MetricName, ResultsStore
from itrader.results.models import build_results_tables
from itrader.results.records import (
    METRIC_NAMES,
    PortfolioRecord,
    RunMetrics,
    RunRecord,
)
from itrader.storage import SqlBackend

# Fixed gzip compression level — pinned alongside ``mtime=0`` so the encoded blob is
# byte-deterministic across runs (RESULT-04 / D-10). Changing this value changes the bytes.
_COMPRESSLEVEL = 6

# WR-01 — the all-zeros UUID sentinel for the aggregate-level artifact's ``portfolio_id``.
# ``run_artifacts.portfolio_id`` is part of the composite PK, so it MUST be NOT NULL to work
# on Postgres (a nullable PK column is implicitly NOT NULL there and rejects a NULL insert).
# A UUIDv7 portfolio id can never be all-zeros (version/timestamp bits are always set), so
# this sentinel never collides with a real portfolio. The store maps None <-> sentinel at
# the write/read boundary, so callers still key the aggregate frame on ``(None, type)``.
_AGGREGATE_PORTFOLIO_ID = uuid.UUID(int=0)

# D-18 — best-first ranking is DESC for EVERY metric in this set, INCLUDING ``max_drawdown``:
# drawdown is stored NEGATIVE (``reporting/metrics.py`` L47-56), so the value closest to zero
# is the LEAST-bad drawdown and the LARGEST signed value → DESC. An ASC on negative drawdown
# would surface the WORST runs. Tiebreak is ``run_id`` ASC (applied in the queries below). The
# map is documentation + a single home for the direction invariant; every entry is "desc".
_METRIC_DIRECTION: dict[str, str] = {name: "desc" for name in METRIC_NAMES}


class SqlResultsStore(ResultsStore):
    """Concrete results store composing the shared SQL spine (SPINE-02, D-06/D-12/D-13).

    Parameters
    ----------
    backend:
        The shared spine (Engine + MetaData). The driver/URL is selected by config at
        wiring; the results store registers its three tables on ``backend.metadata`` and
        creates them idempotently (``checkfirst=True``).
    strict_persist:
        Dump-failure policy (D-17). ``False`` (default) → a caller may log-and-swallow a
        persist failure; ``True`` → surface it. The store itself only RAISES on missing
        reads; the dump-failure decision lives at the run-hook caller (02-04), not here.
    """

    def __init__(self, backend: SqlBackend, *, strict_persist: bool = False) -> None:
        self.backend = backend
        self.engine = backend.engine
        self._strict_persist = strict_persist

        tables = build_results_tables(backend.metadata)
        self.runs = tables["runs"]
        self.run_portfolios = tables["run_portfolios"]
        self.run_artifacts = tables["run_artifacts"]

        # D-12 — idempotent, ephemeral schema creation (no Alembic on the research store).
        backend.metadata.create_all(self.engine, checkfirst=True)

        # T-02-01 — the ORDER BY column is ALWAYS resolved through a MetricName -> Column
        # allow-list map (bound Column objects), NEVER an f-string. ``MetricName`` (a
        # ``Literal``) + mypy --strict block any free string from reaching ``order_by``.
        self._run_metric_columns: dict[str, Column[Any]] = {
            name: self.runs.c[name] for name in METRIC_NAMES
        }
        self._portfolio_metric_columns: dict[str, Column[Any]] = {
            name: self.run_portfolios.c[name] for name in METRIC_NAMES
        }

        self.logger = get_itrader_logger().bind(component="SqlResultsStore")

    def dispose(self) -> None:
        """Dispose the shared backend engine (WR-03 — delegate, never engine.dispose())."""
        self.backend.dispose()

    # ------------------------------------------------------------------ codec (D-10)
    def _encode_frame(self, frame: pd.DataFrame) -> bytes:
        """Encode a DataFrame to a byte-deterministic gzip blob (RESULT-04 / D-10).

        Pinning BOTH ``mtime=0`` AND a fixed ``compresslevel`` is the byte-determinism
        requirement: the gzip header carries an mtime that would otherwise default to the
        wall clock, making two encodes of the same frame differ.

        ``orient="table"`` (NOT ``"split"``) is the DTYPE-STABLE orientation (CR-01): it
        embeds the Table Schema so ``read_json`` restores every column's dtype EXACTLY.
        ``orient="split"`` carried no schema, so ``read_json`` fell back to a name-based
        date heuristic — ``entry_date``/``exit_date`` decoded back as ``int64`` epoch-millis
        and integral-valued ``float`` columns collapsed to ``int64``, breaking the D-15
        value-equal round-trip. ``orient="table"`` is still byte-deterministic (the schema
        is a pure function of the frame's columns/dtypes; no wall-clock content).
        """
        payload = frame.to_json(orient="table", index=True).encode("utf-8")
        buf = io.BytesIO()
        with gzip.GzipFile(
            fileobj=buf, mode="wb", compresslevel=_COMPRESSLEVEL, mtime=0
        ) as gz:
            gz.write(payload)
        return buf.getvalue()

    def _decode_frame(self, blob: bytes) -> pd.DataFrame:
        """Decode a gzip blob back to a value-equal DataFrame (D-10 / D-15 round-trip)."""
        text = gzip.decompress(blob).decode("utf-8")
        return pd.read_json(io.StringIO(text), orient="table")

    def _metric_values(self, metrics: RunMetrics) -> dict[str, Any]:
        """Read the 11 metric floats off a ``RunMetrics`` by ``METRIC_NAMES`` (D-08)."""
        return {name: getattr(metrics, name) for name in METRIC_NAMES}

    # ------------------------------------------------------------------ writes (D-13)
    def save_run(self, run: RunRecord) -> uuid.UUID:
        """Persist the ``runs`` row + all ``run_portfolios`` rows in ONE transaction (D-13).

        Atomic: both inserts execute inside a single ``engine.begin()`` block, so a run is
        persisted whole or not at all. Uses parameterized Core inserts against the constant
        table objects — never string-built SQL. Returns the run's UUIDv7 ``run_id``.
        """
        runs_row: dict[str, Any] = {
            "run_id": run.run_id,
            **self._metric_values(run.metrics),
            "settings": run.settings,
            "study_id": run.study_id,
            "trial_id": run.trial_id,
        }
        portfolio_rows: list[dict[str, Any]] = [
            {
                "run_id": run.run_id,
                "portfolio_id": portfolio.portfolio_id,
                "name": portfolio.name,
                **self._metric_values(portfolio.metrics),
                "params": portfolio.params,
            }
            for portfolio in run.per_portfolio
        ]

        with self.engine.begin() as connection:
            connection.execute(insert(self.runs), [runs_row])
            if portfolio_rows:
                connection.execute(insert(self.run_portfolios), portfolio_rows)

        return run.run_id

    def save_artifact(
        self,
        run_id: uuid.UUID,
        portfolio_id: uuid.UUID | None,
        artifact_type: str,
        frame: pd.DataFrame,
    ) -> None:
        """Persist one frame as a gzip-blob ``run_artifacts`` row (separate txn, D-13).

        WR-01 — an aggregate-level frame (``portfolio_id=None``) is stored under the
        all-zeros sentinel so the composite-PK ``portfolio_id`` column stays NOT NULL on
        Postgres; ``get_artifact`` maps it back to ``None``.
        """
        stored_portfolio_id = (
            _AGGREGATE_PORTFOLIO_ID if portfolio_id is None else portfolio_id
        )
        row: dict[str, Any] = {
            "run_id": run_id,
            "portfolio_id": stored_portfolio_id,
            "artifact_type": artifact_type,
            "blob": self._encode_frame(frame),
        }
        with self.engine.begin() as connection:
            connection.execute(insert(self.run_artifacts), [row])

    # ------------------------------------------------------------------ reads
    def get_artifact(
        self, run_id: uuid.UUID
    ) -> dict[tuple[uuid.UUID | None, str], pd.DataFrame]:
        """Read a run's artifact frames as ``{(portfolio_id, artifact_type): frame}`` (D-15).

        Parameterized read (``bindparam`` against the constant ``run_artifacts`` table). An
        unknown ``run_id`` (no rows) raises ``ResultsNotFound`` (D-16); otherwise each row's
        gzip blob is decoded back to a value-equal DataFrame and keyed by its identity.
        """
        statement = select(self.run_artifacts).where(
            self.run_artifacts.c.run_id == bindparam("run_id")
        )
        with self.engine.connect() as connection:
            rows = connection.execute(statement, {"run_id": run_id}).mappings().all()
        if not rows:
            raise ResultsNotFound(run_id)
        return {
            (self._key_portfolio_id(row["portfolio_id"]), row["artifact_type"]):
                self._decode_frame(row["blob"])
            for row in rows
        }

    @staticmethod
    def _key_portfolio_id(stored: uuid.UUID | None) -> uuid.UUID | None:
        """Map the stored ``portfolio_id`` back to the caller key (WR-01).

        The all-zeros sentinel (written for an aggregate-level frame) maps back to ``None``
        so callers continue to key the aggregate frame on ``(None, artifact_type)``.
        """
        return None if stored == _AGGREGATE_PORTFOLIO_ID else stored

    def top_runs(self, metric: MetricName, n: int) -> list[RunRecord]:
        """Return the top-``n`` runs ranked best-first by ``metric`` (D-18).

        The ORDER BY column is resolved through the ``MetricName`` → ``Column`` allow-list
        map (NEVER an f-string, T-02-01); ``column.desc()`` is best-first for every metric
        (drawdown is stored negative — see ``_METRIC_DIRECTION``). Tiebreak: ``run_id`` ASC.
        An empty / short table returns ``[]`` (D-16). The ranking projection sets
        ``per_portfolio=[]`` (the per-portfolio rows are not joined for the cross-run query).
        """
        column = self._run_metric_columns[metric]
        statement = (
            select(self.runs)
            .order_by(column.desc(), self.runs.c.run_id.asc())
            .limit(n)
        )
        with self.engine.connect() as connection:
            rows = connection.execute(statement).mappings().all()
        return [self._row_to_run_record(row) for row in rows]

    def top_portfolios(self, metric: MetricName, n: int) -> list[PortfolioRecord]:
        """Return the top-``n`` per-strategy portfolios ranked best-first by ``metric`` (D-06/D-18).

        Same allow-list-resolved DESC ranking as ``top_runs`` but against ``run_portfolios``;
        tiebreak ``run_id`` ASC then ``portfolio_id`` ASC. Empty table returns ``[]``.
        """
        column = self._portfolio_metric_columns[metric]
        statement = (
            select(self.run_portfolios)
            .order_by(
                column.desc(),
                self.run_portfolios.c.run_id.asc(),
                self.run_portfolios.c.portfolio_id.asc(),
            )
            .limit(n)
        )
        with self.engine.connect() as connection:
            rows = connection.execute(statement).mappings().all()
        return [self._row_to_portfolio_record(row) for row in rows]

    def _row_to_run_record(self, row: Any) -> RunRecord:
        """Rebuild a ``RunRecord`` from a ``runs`` result row (ranking projection)."""
        metrics = RunMetrics(**{name: row[name] for name in METRIC_NAMES})
        return RunRecord(
            run_id=row["run_id"],
            metrics=metrics,
            settings=row["settings"] or {},
            per_portfolio=[],
            study_id=row["study_id"],
            trial_id=row["trial_id"],
        )

    def _row_to_portfolio_record(self, row: Any) -> PortfolioRecord:
        """Rebuild a ``PortfolioRecord`` from a ``run_portfolios`` result row."""
        metrics = RunMetrics(**{name: row[name] for name in METRIC_NAMES})
        return PortfolioRecord(
            portfolio_id=row["portfolio_id"],
            name=row["name"],
            metrics=metrics,
            params=row["params"] or {},
        )

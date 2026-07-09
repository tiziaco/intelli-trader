"""``ResultsStore`` abstract base class — the spine's fourth composable concern (SPINE-02).

The SQL spine (``itrader.storage.SqlEngine``) is *composed*, never inherited: each storage
concern is one narrow ABC implemented by exactly one ``Sql<Concern>Storage`` that holds a
``SqlEngine`` by reference. Three such ABCs already exist (``OrderStorage``,
``PortfolioStateStorage``, strategy ``SignalStore``); ``ResultsStore`` is the fourth, added
now so the "all four concerns compose the spine" shape (SPINE-02) is concrete. There is
deliberately NO shared cross-concern god base.

This module is ONLY the composition seam. The concrete column types and encoding contract —
the ``runs`` table's ``Float`` summary columns + JSON settings column (RESULT-01), and the
``run_artifacts`` JSON/gzip'd-text frame column (RESULT-02, a text blob — not a columnar
binary format) — are finalized in Phase 2 when the concrete ``Sql``-backed results store
lands. The four abstract methods below map 1:1 to the already-written RESULT-01/02/03
requirements; the surface is intentionally NOT widened beyond them.

Mirrors the narrow-ABC shape of ``strategy_handler/storage/base.py::SignalStore``
(``ABC`` + ``@abstractmethod`` + NumPy docstrings). 4-space indentation (matches the
``itrader/storage`` / ``itrader/config`` layer it sits beside).
"""

import uuid
from abc import ABC, abstractmethod
from typing import Literal

import pandas as pd

from itrader.results.records import PortfolioRecord, RunRecord

# Allow-list of rankable summary metrics (WR-04/D-08/D-18). ``top_runs``/``top_portfolios``
# select an ``ORDER BY`` column, and column names CANNOT be bound parameters — constraining
# the type at this ABC forces every concrete implementation onto a fixed allow-list, so the
# SQL-injection pattern (interpolating a free ``metric`` string into ``ORDER BY``) can never
# be written. Mirrors ``records.METRIC_NAMES`` (the single metric-name source).
MetricName = Literal[
    "sharpe",
    "sortino",
    "cagr",
    "calmar",
    "max_drawdown",
    "profit_factor",
    "win_rate",
    "total_return",
    "final_equity",
    "total_realised_pnl",
    "trade_count",
]


class ResultsStore(ABC):
    """Abstract base class for the research/optimization results store (SPINE-02).

    A sink + cross-run read-model for backtest/optimization runs: the composition root
    writes a run summary and its artifact frame post-run, then queries across runs. The
    store *composes* the shared ``SqlEngine`` (has-a) — it does NOT inherit it, and there
    is no cross-concern god base. Concrete column/encoding choices are deferred to Phase 2;
    this ABC fixes only the method surface, sourced 1:1 from RESULT-01/02/03.
    """

    @abstractmethod
    def save_run(self, run: RunRecord) -> uuid.UUID:
        """Persist one run's summary row + its per-portfolio rows, return ``run_id`` (D-13).

        Parameters
        ----------
        run : RunRecord
            The run summary: aggregate ``RunMetrics`` destined for ``Float`` columns, a
            curated JSON settings envelope, and the ``per_portfolio`` rows. The single
            UUIDv7 ``run.run_id`` is the primary key — no DB autoincrement / second ID scheme.

        Returns
        -------
        uuid.UUID
            The persisted run's ``run_id`` (a native ``uuid.UUID``).
        """
        ...

    @abstractmethod
    def save_artifact(
        self,
        run_id: uuid.UUID,
        portfolio_id: uuid.UUID | None,
        artifact_type: str,
        frame: pd.DataFrame,
    ) -> None:
        """Persist one equity-curve / trade-log frame as a gzip blob row (D-13).

        Parameters
        ----------
        run_id : uuid.UUID
            The owning run's UUIDv7 id.
        portfolio_id : uuid.UUID | None
            The owning portfolio, or ``None`` for an aggregate-level frame (D-07).
        artifact_type : str
            The frame kind — ``"equity_curve"`` or ``"trade_log"``.
        frame : pd.DataFrame
            The pandas DataFrame to persist as one gzip-blob ``run_artifacts`` row (D-09 —
            one row per frame, not exploded per-bar).
        """
        ...

    @abstractmethod
    def get_artifact(
        self, run_id: uuid.UUID
    ) -> dict[tuple[uuid.UUID | None, str], pd.DataFrame]:
        """Read a run's artifact frames back as a keyed collection (D-15 round-trip).

        Parameters
        ----------
        run_id : uuid.UUID
            The run whose artifact frames to load.

        Returns
        -------
        dict[tuple[uuid.UUID | None, str], pd.DataFrame]
            ``{(portfolio_id, artifact_type): frame}`` — each frame value-equal to what
            ``save_artifact`` stored. A missing ``run_id`` raises ``ResultsNotFound`` (D-16).
        """
        ...

    @abstractmethod
    def top_runs(self, metric: MetricName, n: int) -> list[RunRecord]:
        """Return the top-``n`` runs ranked by a summary ``metric`` (RESULT-03 cross-run query).

        Parameters
        ----------
        metric : MetricName
            The summary-metric column to rank by — constrained to the ``MetricName``
            allow-list (WR-04) because column names cannot be bound parameters; a
            scalar-promoted indexed ``Float`` column, no JSON-path filtering in the
            cross-run query surface.
        n : int
            How many top runs to return.

        Returns
        -------
        list[RunRecord]
            The top-``n`` run summaries, best first (stable ``ORDER BY`` for determinism).
        """
        ...

    @abstractmethod
    def top_portfolios(self, metric: MetricName, n: int) -> list[PortfolioRecord]:
        """Return the top-``n`` per-strategy portfolios ranked by ``metric`` (D-08/D-18).

        A dedicated method for per-strategy ranking on ``run_portfolios`` — kept separate
        from ``top_runs`` so each return type stays clean (a ``PortfolioRecord`` list rather
        than overloading ``top_runs`` with a target argument).

        Parameters
        ----------
        metric : MetricName
            The summary-metric column to rank by — same ``MetricName`` allow-list as
            ``top_runs`` (column names cannot be bound parameters, WR-04).
        n : int
            How many top portfolios to return.

        Returns
        -------
        list[PortfolioRecord]
            The top-``n`` portfolios, best first (stable ``ORDER BY`` for determinism).
        """
        ...

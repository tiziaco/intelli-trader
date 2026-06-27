"""``ResultsStore`` abstract base class — the spine's fourth composable concern (SPINE-02).

The SQL spine (``itrader.storage.SqlBackend``) is *composed*, never inherited: each storage
concern is one narrow ABC implemented by exactly one ``Sql<Concern>Storage`` that holds a
``SqlBackend`` by reference. Three such ABCs already exist (``OrderStorage``,
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

from abc import ABC, abstractmethod
from typing import Any, Literal

# Allow-list of rankable summary metrics (WR-04). ``top_runs`` selects an ``ORDER BY``
# column, and column names CANNOT be bound parameters — constraining the type at this ABC
# forces every concrete implementation onto a fixed allow-list, so the SQL-injection
# pattern (interpolating a free ``metric`` string into ``ORDER BY``) can never be written.
MetricName = Literal["sharpe", "total_return", "max_drawdown", "calmar"]


class ResultsStore(ABC):
    """Abstract base class for the research/optimization results store (SPINE-02).

    A sink + cross-run read-model for backtest/optimization runs: the composition root
    writes a run summary and its artifact frame post-run, then queries across runs. The
    store *composes* the shared ``SqlBackend`` (has-a) — it does NOT inherit it, and there
    is no cross-concern god base. Concrete column/encoding choices are deferred to Phase 2;
    this ABC fixes only the method surface, sourced 1:1 from RESULT-01/02/03.
    """

    @abstractmethod
    def save_run(self, run: Any) -> Any:
        """Persist one run's summary row and return its ``run_id`` (RESULT-01).

        Parameters
        ----------
        run : Any
            The run summary (Phase-2 type): summary metrics destined for ``Float`` columns
            plus a JSON settings blob. A single UUIDv7 ``run_id`` is the primary key — no DB
            autoincrement / second ID scheme.

        Returns
        -------
        Any
            The persisted run's ``run_id`` (a native ``uuid.UUID``).
        """
        ...

    @abstractmethod
    def save_artifact(self, run_id: Any, frame: Any) -> None:
        """Persist a run's equity-curve / trade-log frame as a text blob (RESULT-02).

        Parameters
        ----------
        run_id : Any
            The owning run's UUIDv7 id.
        frame : Any
            The pandas DataFrame (equity curve / trade log) to persist as a JSON/gzip'd-text
            ``run_artifacts`` column — a text blob, not a columnar binary format.
        """
        ...

    @abstractmethod
    def get_artifact(self, run_id: Any) -> Any:
        """Read a run's artifact frame back to a pandas DataFrame (RESULT-02 round-trip).

        Parameters
        ----------
        run_id : Any
            The run whose artifact frame to load.

        Returns
        -------
        Any
            The reconstructed pandas DataFrame, value-equal to what ``save_artifact`` stored.
        """
        ...

    @abstractmethod
    def top_runs(self, metric: MetricName, n: int) -> list[Any]:
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
        list[Any]
            The top-``n`` run summaries, best first (stable ``ORDER BY`` for determinism).
        """
        ...

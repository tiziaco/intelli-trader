"""The results-store package — the ``ResultsStore`` ABC + its value records (SPINE-02).

Re-exports the SQL-free surface: the narrow ``ResultsStore`` abstract base class (the spine's
fourth composable concern) and the frozen result DTOs (``RunRecord`` / ``PortfolioRecord`` /
``RunMetrics`` + the ``METRIC_NAMES`` allow-list). The concrete ``SqlResultsStore`` is
deliberately NOT re-exported here: importing it pulls SQLAlchemy, so a store-free
(``persist=False``) run keeps the backtest import path SQL-free (GATE-01 inertness — mirrors
``itrader/storage/__init__.py``). Import it explicitly via
``from itrader.results.sql_storage import SqlResultsStore`` only on the persistence path.
"""

from itrader.results.base import ResultsStore
from itrader.results.records import (
    METRIC_NAMES,
    PortfolioRecord,
    RunMetrics,
    RunRecord,
)

__all__ = [
    "ResultsStore",
    "RunRecord",
    "PortfolioRecord",
    "RunMetrics",
    "METRIC_NAMES",
]

"""Frozen result DTOs for the results store (D-08/D-13).

Pure value objects — no serialization logic. ``RunMetrics`` carries the 11 summary metrics
as ``float`` (the results store is all-``Float``, CONTEXT Precedence + D-08 — this is the
analytical store, NOT the money ledger, so ``float`` is correct here, not a Decimal defect).

``METRIC_NAMES`` is the SINGLE SOURCE OF TRUTH for the metric column set (D-08): ``models.py``
builds its ``Float`` columns from it and ``base.py``'s ``MetricName`` Literal mirrors it.

Mirrors the codebase frozen-DTO convention (``matching_engine.py::FillDecision``,
``system_spec.py::SystemSpec`` holding ``list[PortfolioSpec]``) — 4-space indentation
(matches the ``itrader/results`` layer it sits in).
"""

import uuid
from dataclasses import dataclass
from typing import Any

# The 11 summary-metric column names in canonical order (D-08). Reused by ``models.py``
# (one indexed ``Float`` column per name) and ``base.py``'s ``MetricName`` allow-list.
METRIC_NAMES: tuple[str, ...] = (
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
)


@dataclass(frozen=True, slots=True, kw_only=True)
class RunMetrics:
    """The 11 summary metrics for a run or portfolio (D-08, all ``float``)."""

    sharpe: float
    sortino: float
    cagr: float
    calmar: float
    max_drawdown: float
    profit_factor: float
    win_rate: float
    total_return: float
    final_equity: float
    total_realised_pnl: float
    trade_count: float


@dataclass(frozen=True, slots=True, kw_only=True)
class PortfolioRecord:
    """One portfolio's contribution to a run — its metrics + declared params (D-06)."""

    portfolio_id: uuid.UUID
    name: str
    metrics: RunMetrics
    params: dict[str, Any]


@dataclass(frozen=True, slots=True, kw_only=True)
class RunRecord:
    """One run's summary: aggregate metrics + curated settings + per-portfolio rows (D-13).

    ``study_id`` / ``trial_id`` are Optuna-FK-ready nullable substrate (D-09): the sweep
    integration is deferred, but the fields exist now so the schema does not churn later.
    """

    run_id: uuid.UUID
    metrics: RunMetrics
    settings: dict[str, Any]
    per_portfolio: list[PortfolioRecord]
    study_id: uuid.UUID | None = None
    trial_id: uuid.UUID | None = None

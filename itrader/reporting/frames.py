"""Pure frame builders for the deterministic run artifacts (M5-07, D-14 amendment).

``build_trade_log`` and ``build_equity_curve`` (plus the ``TRADE_COLUMNS`` /
``EQUITY_COLUMNS`` pins) are relocated VERBATIM from ``scripts/run_backtest.py``
so the engine's end-of-run metrics printout (D-14 amendment, user decision
2026-06-07) and the oracle generator share ONE frame-building source. The
goldens serialize from these frames — the function bodies are
character-identical to the run_backtest.py originals (any drift breaks the
byte-exact oracle gate, T-07-23).

Purity contract (same anti-pattern guard as ``itrader.reporting.metrics``):
imports are pandas + stdlib only; the ``portfolio`` parameter stays DUCK-TYPED
(``closed_positions`` / ``metrics_manager.get_snapshots()``) — zero handler
imports.
"""

from dataclasses import asdict
from typing import Any

import pandas as pd

# Deterministic trade-log columns only (D-12). EXCLUDES position_id / current_price /
# unrealised_pnl, which are volatile / non-deterministic until M2.
TRADE_COLUMNS = [
    "entry_date",
    "exit_date",
    "side",
    "net_quantity",
    "avg_price",
    "avg_bought",
    "avg_sold",
    "total_bought",
    "total_sold",
    "realised_pnl",
    "pair",
]

# Deterministic equity-curve columns sourced from PortfolioSnapshot (metrics_manager.py:29).
EQUITY_COLUMNS = [
    "timestamp",
    "total_equity",
    "cash_balance",
    "positions_value",
    "unrealized_pnl",
    "realized_pnl",
    "total_pnl",
    "open_positions_count",
    "portfolio_return",
]


def build_trade_log(portfolio: Any) -> pd.DataFrame:
    """Build the deterministic trade-log frame from closed positions (D-12).

    Source: ``portfolio.closed_positions`` -> ``Position.to_dict()`` (position.py:244),
    keeping only the deterministic columns and sorting by (entry_date, exit_date, side)
    so row ordering is reproducible.
    """
    rows = [position.to_dict() for position in portfolio.closed_positions]
    frame = pd.DataFrame(rows, columns=TRADE_COLUMNS) if rows else pd.DataFrame(columns=TRADE_COLUMNS)
    if not frame.empty:
        frame = frame.sort_values(["entry_date", "exit_date", "side"]).reset_index(drop=True)
    return frame


def build_equity_curve(portfolio: Any) -> pd.DataFrame:
    """Build the deterministic equity-curve frame from metrics snapshots (Pitfall 5).

    Sources the ``PortfolioSnapshot`` list directly from the metrics manager — NOT through
    ``StatisticsReporting._prepare_data`` (which reads a non-existent ``portfolio.metrics``).
    """
    snapshots = portfolio.metrics_manager.get_snapshots()
    rows = []
    for snapshot in snapshots:
        record = asdict(snapshot)
        # Decimal fields serialize as floats for a stable CSV repr; timestamp stays as-is.
        rows.append({column: record.get(column) for column in EQUITY_COLUMNS})
    frame = pd.DataFrame(rows, columns=EQUITY_COLUMNS) if rows else pd.DataFrame(columns=EQUITY_COLUMNS)
    if not frame.empty:
        for column in EQUITY_COLUMNS:
            if column in ("timestamp", "open_positions_count"):
                continue
            frame[column] = frame[column].astype(float)
        frame = frame.sort_values("timestamp").reset_index(drop=True)
    return frame

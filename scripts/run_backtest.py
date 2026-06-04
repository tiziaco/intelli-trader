#!/usr/bin/env python
"""Reproducible oracle generator for the SMA_MACD backtest (M1-07).

This committed driver pins every oracle-defining decision so a run is bit-reproducible:

  * D-01  dataset  : data/BTCUSD_1d_ohlcv_2018_2026.csv (the golden CSV feed)
  * D-02  window   : 2018-01-01 -> 2026-06-03 (pinned explicitly below)
  * D-03  params   : SMA_MACD code defaults (short=50/long=100/FAST=6/SLOW=12/WIN=3)
  * D-04  capital  : starting cash $10,000, fees 0, slippage 0
  * D-06  ticker   : BTCUSD on the 1d timeframe
  * D-10  output   : output/trades.csv + output/equity.csv + output/summary.json
  * D-12  fields   : only deterministic fields are serialized (no wall-clock timestamps,
                     no position-id / current-price / unrealised-pnl volatile values)

Queue-only rule: this script constructs the system and reads result state AFTER the run
(``portfolio.closed_positions`` and the metrics snapshots). It never calls handler methods
across domains during the run.

The summary's derived metrics are intentionally minimal: sharpe/sortino/cagr math is M5-owned
and currently buggy, so it is NOT frozen here.

Run via ``make backtest`` or ``poetry run python scripts/run_backtest.py``.
"""

import json
import pathlib
from dataclasses import asdict

import pandas as pd

from itrader.trading_system.backtest_trading_system import TradingSystem
from itrader.strategy_handler.SMA_MACD_strategy import SMA_MACD_strategy
from itrader.logger import get_itrader_logger


# --- Pinned oracle configuration -------------------------------------------

DATASET = "data/BTCUSD_1d_ohlcv_2018_2026.csv"  # D-01
START_DATE = "2018-01-01"                        # D-02
END_DATE = "2026-06-03"                          # D-02
CASH = 10_000                                     # D-04 (fees 0, slippage 0 — exchange defaults)
TICKER = "BTCUSD"                                 # D-06
TIMEFRAME = "1d"                                  # D-06

OUTPUT_DIR = pathlib.Path("output")              # D-10 / D-11 (gitignored)
FLOAT_FORMAT = "%.10f"                            # pinned repr for cross-platform stability (T-04-01)

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


def build_trade_log(portfolio):
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


def build_equity_curve(portfolio):
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


def build_summary(portfolio, trades):
    """Build a minimal deterministic summary dict (D-12).

    Final cash + a minimal deterministic metric set (trade count, total realised PnL,
    final equity). Derived ratios (sharpe/sortino/cagr) are intentionally omitted — that
    math is M5-owned and currently buggy, so freezing it here would corrupt the oracle.
    """
    total_realised_pnl = float(trades["realised_pnl"].sum()) if not trades.empty else 0.0
    return {
        "ticker": TICKER,
        "timeframe": TIMEFRAME,
        "start_date": START_DATE,
        "end_date": END_DATE,
        "starting_cash": float(CASH),
        "final_cash": float(portfolio.cash),
        "final_equity": float(portfolio.total_equity),
        "trade_count": int(len(trades)),
        "total_realised_pnl": total_realised_pnl,
    }


def main():
    logger = get_itrader_logger().bind(component="OracleRunner")

    # Construct the CSV-fed engine (D-01/D-02). Fees/slippage are exchange defaults (D-04).
    system = TradingSystem(
        exchange="csv",
        start_date=START_DATE,
        end_date=END_DATE,
    )

    # Reference strategy on the daily timeframe, subscribed to BTCUSD (D-03/D-06).
    strategy = SMA_MACD_strategy(timeframe=TIMEFRAME, tickers=[TICKER])
    system.strategies_handler.add_strategy(strategy)

    # Single long-only portfolio with $10k starting cash (D-04).
    portfolio_id = system.portfolio_handler.add_portfolio(
        user_id=1,
        name="oracle_pf",
        exchange="csv",
        cash=CASH,
    )
    strategy.subscribe_portfolio(portfolio_id)

    # Run the full PING->BAR->SIGNAL->ORDER->FILL loop. print_summary=False avoids the
    # broken StatisticsReporting._prepare_data path (Pitfall 5).
    system.run(print_summary=False)

    # --- Read result state AFTER the run (queue-only rule) ------------------
    portfolio = system.portfolio_handler.get_portfolio(portfolio_id)
    trades = build_trade_log(portfolio)
    equity = build_equity_curve(portfolio)
    summary = build_summary(portfolio, trades)

    # --- Serialize the deterministic oracle (D-10/D-12) --------------------
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    trades.to_csv(OUTPUT_DIR / "trades.csv", index=False, float_format=FLOAT_FORMAT)
    equity.to_csv(OUTPUT_DIR / "equity.csv", index=False, float_format=FLOAT_FORMAT)
    with open(OUTPUT_DIR / "summary.json", "w") as handle:
        json.dump(summary, handle, indent=2, sort_keys=True)

    logger.info(
        "Oracle written",
        trades=len(trades),
        equity_points=len(equity),
        final_equity=summary["final_equity"],
        output_dir=str(OUTPUT_DIR),
    )


if __name__ == "__main__":
    main()

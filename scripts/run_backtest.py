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

The summary carries the D-15 derived-metrics block (sharpe/sortino/cagr/max_drawdown/
profit_factor/win_rate) computed by ``itrader.reporting.metrics`` — the same formula
source the engine's end-of-run printout uses (D-14 amendment). The trades frame carries
the D-17 slippage-attribution columns. Both are produced every run and freeze into
``tests/golden/`` only at the named D-11 re-freezes (plan 07-07).

Run via ``make backtest`` or ``poetry run python scripts/run_backtest.py``.
"""

import json
import pathlib

import pandas as pd

from itrader.reporting.frames import (
    EQUITY_COLUMNS,
    TRADE_COLUMNS,
    build_equity_curve,
    build_trade_log,
)
from itrader.reporting.metrics import (
    cagr,
    compute_returns,
    max_drawdown,
    profit_factor,
    sharpe,
    sortino,
    win_rate,
)
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

# D-17 slippage-attribution columns appended to the serialized trade log (after
# the relocated TRADE_COLUMNS) — float columns, so the FLOAT_FORMAT pin applies.
SLIPPAGE_COLUMNS = ["slippage_entry", "slippage_exit"]


def attach_slippage(trades, closes):
    """Attach the D-17 per-trade slippage columns — post-hoc, engine-inert (Pattern 3).

    Under the Phase 6 next-bar-open fill convention, a fill at bar ``T`` was decided
    at the bar immediately BEFORE ``T`` in the store index; the attribution is
    ``fill price - decision-bar close`` for the entry and exit fills separately.
    In the zero-slippage golden run these columns measure the overnight next-open
    gap introduced by Phase 6 fill realism. Computed purely from the store's
    per-ticker close series + the trades frame — no engine/event/entity change.
    """
    if trades.empty:
        trades["slippage_entry"] = pd.Series(dtype=float)
        trades["slippage_exit"] = pd.Series(dtype=float)
        return trades

    index = closes.index

    def decision_close(fill_time):
        position = index.searchsorted(fill_time, side="left")
        return float(closes.iloc[position - 1]) if position > 0 else float("nan")

    def entry_fill_price(row):
        # LONG enters by buying; SHORT enters by selling.
        return float(row["avg_bought"] if row["side"] == "LONG" else row["avg_sold"])

    def exit_fill_price(row):
        # LONG exits by selling; SHORT exits by buying back.
        return float(row["avg_sold"] if row["side"] == "LONG" else row["avg_bought"])

    trades["slippage_entry"] = trades.apply(
        lambda row: entry_fill_price(row) - decision_close(row["entry_date"]), axis=1)
    trades["slippage_exit"] = trades.apply(
        lambda row: exit_fill_price(row) - decision_close(row["exit_date"]), axis=1)
    return trades


def build_metrics_block(equity, trades):
    """Build the nested D-15 derived-metrics dict for ``summary.json``.

    Computed by the pure ``itrader.reporting.metrics`` functions on the equity
    curve + trades frame — the SAME formula source the engine's end-of-run
    printout uses (one formula source, two consumers). All values are plain
    floats, deterministic; the block freezes at the plan 07-07 re-freeze.
    """
    equity_series = equity["total_equity"].astype(float)
    returns = compute_returns(equity_series)
    return {
        "sharpe": float(sharpe(returns)),
        "sortino": float(sortino(returns)),
        "cagr": float(cagr(equity_series)),
        "max_drawdown": float(max_drawdown(equity_series)),
        "profit_factor": float(profit_factor(trades)),
        "win_rate": float(win_rate(trades)),
    }


def build_summary(portfolio, trades):
    """Build a minimal deterministic summary dict (D-12).

    Final cash + a minimal deterministic metric set (trade count, total realised PnL,
    final equity). The derived ratios live in the nested ``metrics`` block added by
    ``build_metrics_block`` (D-15 — the M5-owned carve-out is closed this phase).
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

    # Run the full PING->BAR->SIGNAL->ORDER->FILL loop. The default
    # print_summary=True prints the engine-level D-15 metrics block at end of
    # run (D-14 amendment) — stdout only, no output/ artifact bytes change.
    system.run()

    # --- Read result state AFTER the run (queue-only rule) ------------------
    portfolio = system.portfolio_handler.get_portfolio(portfolio_id)
    trades = build_trade_log(portfolio)
    equity = build_equity_curve(portfolio)

    # D-17: post-hoc slippage attribution from the store's close series.
    closes = system.store.read_bars(TICKER)["close"]
    trades = attach_slippage(trades, closes)

    summary = build_summary(portfolio, trades)
    # D-15: nested derived-metrics block — produced every run, frozen at 07-07.
    summary["metrics"] = build_metrics_block(equity, trades)

    # --- Serialize the deterministic oracle (D-10/D-12) --------------------
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    trades[TRADE_COLUMNS + SLIPPAGE_COLUMNS].to_csv(
        OUTPUT_DIR / "trades.csv", index=False, float_format=FLOAT_FORMAT)
    equity[EQUITY_COLUMNS].to_csv(
        OUTPUT_DIR / "equity.csv", index=False, float_format=FLOAT_FORMAT)
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

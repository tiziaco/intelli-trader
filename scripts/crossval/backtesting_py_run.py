"""backtesting.py FractionalBacktest force-match module (08-05 Task 2).

Runs SMA_MACD on the golden BTCUSD window through `backtesting.py`, force-matched
to iTrader's D-01 rules (cash $10k, zero fees/slippage, 95%-of-equity fractional
sizing, long-only single position, next-bar-open fills) and consuming the
INJECTED `ta` indicator arrays from `scripts.crossval.indicators` so no indicator
divergence exists by construction (D-03).

THE QUIRK (verbatim from SMA_MACD_strategy lines 88-94): the SMA filter
`sma_short >= sma_long` gates BOTH entry AND exit; the exit branch is an `elif`
NESTED INSIDE the filter `if`. When the filter is False, a held long is NOT
exited on a MACD down-cross — it stays open until a later bar where the filter is
True AND a down-cross occurs.

SCRIPT-ONLY (D-10): imports backtesting.py (bokeh). NEVER import under tests/.

Uniform contract: `run(prices=None, indicators=None) -> (trade_log_df,
equity_curve_series)`. None args → load/compute internally; injected args → use
those identical arrays (the 08-07 orchestrator path). `trade_log_df` is
NORMALIZED to columns `entry_date, exit_date, side, realised_pnl`.

4-space indentation (new script code, per CLAUDE.md).
"""

from __future__ import annotations

import pandas as pd

from backtesting import Strategy
from backtesting.lib import FractionalBacktest

from scripts.crossval.indicators import (
    MIN_BARS,
    load_golden_with_indicators,
)

CASH = 10_000
# μBTC granularity — small enough that 0.95 * equity / price never floors to 0
# BTC (the fractional-units landmine). Plain Backtest would floor to whole units.
FRACTIONAL_UNIT = 1e-6


class SMAMACDBacktesting(Strategy):
    """SMA_MACD replicated verbatim, reading the INJECTED `ta` arrays.

    The injected `sma_short`, `sma_long`, `macd_hist` are supplied as extra
    columns on the data feed and registered via `self.I(...)` so the framework
    tracks them as indicator series. The strategy computes NO indicators itself
    (D-03).
    """

    def init(self):
        # Register the injected arrays as tracked indicator series. The lambdas
        # read the extra feed columns threaded in by `run()`.
        self.sma_short = self.I(
            lambda: self.data.sma_short, name="sma_short", overlay=False
        )
        self.sma_long = self.I(
            lambda: self.data.sma_long, name="sma_long", overlay=False
        )
        self.macd_hist = self.I(
            lambda: self.data.macd_hist, name="macd_hist", overlay=False
        )

    def next(self):
        # Warm-up gate: skip until MIN_BARS (100) bars elapsed, mirroring
        # SMA_MACD_strategy `if len(bars) < self.max_window: return None`.
        if len(self.data) < MIN_BARS:
            return

        # THE QUIRK — the SMA filter gates BOTH entry and exit; exit is the
        # nested elif inside the filter block. Note: FractionalBacktest rescales
        # prices internally, but every comparison here is scale-invariant
        # (sma_short vs sma_long; macd_hist vs 0), so injected-array semantics
        # are preserved.
        if self.sma_short[-1] >= self.sma_long[-1]:  # Filter
            # Entry: filter True AND macd up-cross AND flat (no pyramiding).
            if (self.macd_hist[-1] >= 0) and (self.macd_hist[-2] < 0):
                if not self.position:
                    self.buy(size=0.95)
            # Exit: filter True AND macd down-cross (nested elif).
            elif (self.macd_hist[-1] <= 0) and (self.macd_hist[-2] > 0):
                if self.position:
                    self.position.close()
        # When the filter is False: do NOT close an open long (THE QUIRK).


def _normalize_trades(trades_raw: pd.DataFrame) -> pd.DataFrame:
    """Map backtesting.py `stats['_trades']` to the 08-07 reconcile shape.

    Columns: entry_date (EntryTime), exit_date (ExitTime), side (Size sign →
    "LONG"; this is a long-only force-match), realised_pnl (PnL).
    """
    if trades_raw.empty:
        return pd.DataFrame(
            columns=["entry_date", "exit_date", "side", "realised_pnl"]
        )
    return pd.DataFrame(
        {
            "entry_date": trades_raw["EntryTime"].to_numpy(),
            "exit_date": trades_raw["ExitTime"].to_numpy(),
            "side": ["LONG" if s > 0 else "SHORT" for s in trades_raw["Size"]],
            "realised_pnl": trades_raw["PnL"].to_numpy(),
        }
    )


def run(prices=None, indicators=None):
    """Uniform entry: run the force-match and return (trade_log_df, equity_series).

    `prices`/`indicators` None → load the bar+indicator frame internally
    (standalone / verify path). When the 08-07 orchestrator passes them, use
    those identical injected arrays (D-03). `prices` may be either a combined
    bar+indicator frame or just bars; `indicators` (when given) is joined on.
    """
    if prices is None:
        frame = load_golden_with_indicators()
    else:
        frame = prices.copy()
        if indicators is not None:
            frame = frame.join(indicators)

    # backtesting.py expects TitleCase OHLCV; thread the injected indicator
    # arrays as extra lowercase columns the strategy reads via self.data.
    data = pd.DataFrame(
        {
            "Open": frame["open"].to_numpy(),
            "High": frame["high"].to_numpy(),
            "Low": frame["low"].to_numpy(),
            "Close": frame["close"].to_numpy(),
            "Volume": frame["volume"].to_numpy(),
            "sma_short": frame["sma_short"].to_numpy(),
            "sma_long": frame["sma_long"].to_numpy(),
            "macd_hist": frame["macd_hist"].to_numpy(),
        },
        index=frame.index,
    )

    bt = FractionalBacktest(
        data,
        SMAMACDBacktesting,
        cash=CASH,
        commission=0.0,
        spread=0.0,
        margin=1.0,
        trade_on_close=False,  # fill at next bar open (D-01)
        exclusive_orders=True,
        # finalize_trades=False: iTrader's 134 are CLOSED positions and the
        # golden run ends flat (last trade exits on the final bar). Do NOT
        # finalize an open final trade. 08-07 confirms final-open-trade handling
        # against the frozen oracle.
        finalize_trades=False,
        fractional_unit=FRACTIONAL_UNIT,
    )
    stats = bt.run()

    trade_log_df = _normalize_trades(stats["_trades"])
    equity_curve_series = stats["_equity_curve"]["Equity"]
    equity_curve_series.name = "equity"
    return trade_log_df, equity_curve_series


if __name__ == "__main__":
    trades, equity = run()
    print(
        "backtesting.py:",
        len(trades),
        "trades | final_equity",
        float(equity.iloc[-1]),
    )

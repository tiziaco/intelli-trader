"""backtrader custom-float-sizer force-match module (08-05 Task 3).

Runs SMA_MACD on the golden BTCUSD window through `backtrader`, force-matched to
iTrader's D-01 rules (cash $10k, zero fees/slippage, 95%-of-equity FRACTIONAL
sizing via a custom float sizer, long-only single position, next-bar-open fills)
and consuming the INJECTED `ta` indicator arrays from `scripts.crossval.indicators`
as extra PandasData lines so no indicator divergence exists by construction (D-03).

THE QUIRK (verbatim from SMA_MACD_strategy lines 88-94): the SMA filter
`sma_short >= sma_long` gates BOTH entry AND exit; the exit branch is an `elif`
NESTED INSIDE the filter `if`. When the filter is False, a held long is NOT
exited on a MACD down-cross.

FRACTIONAL-UNITS LANDMINE: the built-in `bt.sizers.PercentSizer` casts size to
int → 0 BTC → 0 trades. A CUSTOM `bt.Sizer` returning a FLOAT
`0.95 * cash / price` is mandatory.

SCRIPT-ONLY (D-10): imports backtrader (emits SyntaxWarning docstring escapes at
import that would trip filterwarnings=["error"]). NEVER import under tests/.

Uniform contract: `run(prices=None, indicators=None) -> (trade_log_df,
equity_curve_series)`. None args → load/compute internally; injected args → use
those identical arrays (08-07 orchestrator path). `trade_log_df` is NORMALIZED to
columns `entry_date, exit_date, side, realised_pnl`.

4-space indentation (new script code, per CLAUDE.md).
"""

from __future__ import annotations

import pandas as pd

import backtrader as bt

from scripts.crossval.indicators import (
    MIN_BARS,
    load_golden_with_indicators,
)

CASH = 10_000.0
FRACTION = 0.95


class FractionalSizer(bt.Sizer):
    """Return a FLOAT 0.95 * cash / price — NOT PercentSizer (which int-floors).

    This is the fractional-units landmine fix: a float size lets backtrader hold
    fractional BTC, matching iTrader's 95%-of-equity sizing.
    """

    def _getsizing(self, comminfo, cash, data, isbuy):
        if not isbuy:
            # Sell to close: return the full held position (float).
            position = self.broker.getposition(data)
            return position.size
        price = data.close[0]
        if price <= 0:
            return 0.0
        return FRACTION * cash / price


class GoldenPandasData(bt.feeds.PandasData):
    """PandasData with the three injected `ta` arrays as extra lines.

    The strategy reads iTrader's exact SMA/MACD arrays rather than computing its
    own (D-03). Each extra line maps to a same-named lowercase column on the fed
    frame (param value = column name string).
    """

    lines = ("sma_short", "sma_long", "macd_hist")
    params = (
        ("sma_short", "sma_short"),
        ("sma_long", "sma_long"),
        ("macd_hist", "macd_hist"),
    )


class SMAMACDBacktrader(bt.Strategy):
    """SMA_MACD replicated verbatim, reading the injected `ta` extra lines."""

    def __init__(self):
        self.trades_log: list[dict] = []
        self.equity_dates: list[pd.Timestamp] = []
        self.equity_values: list[float] = []

    def next(self):
        # Record equity each bar (per-bar equity curve), keyed by bar datetime.
        self.equity_dates.append(self.data.datetime.datetime(0))
        self.equity_values.append(self.broker.getvalue())

        # Warm-up gate: skip until MIN_BARS bars elapsed (mirrors the strategy's
        # `len(bars) < max_window` guard). len(self) is the processed bar count.
        if len(self) < MIN_BARS:
            return

        sma_short = self.data.sma_short
        sma_long = self.data.sma_long
        macd_hist = self.data.macd_hist

        # THE QUIRK — SMA filter gates BOTH entry and exit; exit is the nested
        # elif inside the filter block.
        if sma_short[0] >= sma_long[0]:  # Filter
            # Entry: filter True AND macd up-cross AND flat (no pyramiding).
            if (macd_hist[0] >= 0) and (macd_hist[-1] < 0):
                if not self.position:
                    self.buy()
            # Exit: filter True AND macd down-cross (nested elif).
            elif (macd_hist[0] <= 0) and (macd_hist[-1] > 0):
                if self.position:
                    self.close()
        # When the filter is False: do NOT close an open long (THE QUIRK).

    def notify_trade(self, trade):
        # Capture per-trade entry/exit datetimes + realised pnl on close.
        if not trade.isclosed:
            return
        self.trades_log.append(
            {
                "entry_date": bt.num2date(trade.dtopen),
                "exit_date": bt.num2date(trade.dtclose),
                "side": "LONG",  # long-only force-match
                "realised_pnl": trade.pnl,
            }
        )


def _normalize_trades(records: list[dict]) -> pd.DataFrame:
    """Assemble notify_trade records into the 08-07 reconcile shape."""
    if not records:
        return pd.DataFrame(
            columns=["entry_date", "exit_date", "side", "realised_pnl"]
        )
    return pd.DataFrame(records)[
        ["entry_date", "exit_date", "side", "realised_pnl"]
    ]


def run(prices=None, indicators=None):
    """Uniform entry: run the force-match and return (trade_log_df, equity_series).

    `prices`/`indicators` None → load the bar+indicator frame internally;
    injected → use those identical arrays (D-03). `prices` may be a combined
    bar+indicator frame or just bars; `indicators` (when given) is joined on.
    """
    if prices is None:
        frame = load_golden_with_indicators()
    else:
        frame = prices.copy()
        if indicators is not None:
            frame = frame.join(indicators)

    # backtrader PandasData expects an `openinterest`-free frame is fine; map the
    # OHLCV + the three injected indicator columns. Drop warm-up NaN indicator
    # rows to 0.0 is WRONG (would corrupt the filter) — instead keep NaN; the
    # MIN_BARS gate skips those bars before any indicator is read.
    feed_frame = pd.DataFrame(
        {
            "open": frame["open"].to_numpy(),
            "high": frame["high"].to_numpy(),
            "low": frame["low"].to_numpy(),
            "close": frame["close"].to_numpy(),
            "volume": frame["volume"].to_numpy(),
            "sma_short": frame["sma_short"].to_numpy(),
            "sma_long": frame["sma_long"].to_numpy(),
            "macd_hist": frame["macd_hist"].to_numpy(),
        },
        index=pd.DatetimeIndex(frame.index).tz_localize(None),
    )

    cerebro = bt.Cerebro()
    cerebro.broker.setcash(CASH)
    cerebro.broker.setcommission(commission=0.0)
    # Default next-bar-open fills — do NOT enable cheat-on-open/close (D-01).
    cerebro.broker.set_coc(False)
    cerebro.broker.set_coo(False)
    cerebro.addsizer(FractionalSizer)
    cerebro.adddata(GoldenPandasData(dataname=feed_frame))
    cerebro.addstrategy(SMAMACDBacktrader)

    strat = cerebro.run()[0]

    trade_log_df = _normalize_trades(strat.trades_log)
    equity_curve_series = pd.Series(
        strat.equity_values,
        index=pd.DatetimeIndex(strat.equity_dates),
        name="equity",
    )
    return trade_log_df, equity_curve_series


if __name__ == "__main__":
    trades, equity = run()
    print(
        "backtrader:",
        len(trades),
        "trades | final_equity",
        float(equity.iloc[-1]),
    )

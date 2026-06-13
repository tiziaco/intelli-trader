"""backtrader LIMIT-entry bracket force-match module (Plan 05-04, D-07).

Runs the crafted ``LimitEntryStrategy`` (date-keyed ``buy_limit`` + percent SL/TP)
on the pinned BTCUSD golden window through ``backtrader``, force-matched to
iTrader's rules (cash $10k, zero fees/slippage, 0.95-of-cash FRACTIONAL sizing on
the LIMIT TRIGGER price, long-only single position, next-bar fills). This is the
LIMIT-entry analog of the MARKET-only ``backtrader_run.py`` SMA_MACD runner — it
preserves the uniform ``run()`` contract and normalized trade columns.

THE BRACKET (RESEARCH Code Examples): ``self.buy_bracket(price=limit_entry,
exectype=bt.Order.Limit, stopprice=sl, limitprice=tp)`` places an OCO-linked
entry Limit + low-side Stop (SL) + high-side Limit (TP). The children are inactive
until the entry executes, and executing/cancelling one child cancels the other —
the same entry-fill -> SL/TP-bracket sequence iTrader's MatchingEngine runs.

THE FILL ALGEBRA: a backtrader Limit entry fills at the limit price (or the better
open on a favorable gap) with default next-bar fills — the ``min(open, limit)``
rule iTrader and backtesting.py share (A1: backtrader's exact gap-through price is
not documented; the marketable case is dispositioned via the reconcile machinery
if it diverges).

FRACTIONAL-UNITS LANDMINE (inherited from backtrader_run.py): the built-in sizers
cast size to int -> 0 BTC. A FLOAT size (0.95 * cash / trigger) is mandatory; here
it is computed per-decision and passed to ``buy_bracket(size=...)`` directly.

SCRIPT-ONLY (D-10): imports backtrader (SyntaxWarning at import would trip
``filterwarnings=["error"]``). NEVER import under tests/.

Uniform contract: ``run(prices=None, indicators=None) -> (trade_log_df,
equity_curve_series)``. None args -> load the pinned window internally; injected
``prices`` -> use that frame. ``indicators`` is accepted-and-ignored. ``trade_log_df``
is NORMALIZED to columns ``entry_date, exit_date, side, realised_pnl``.

4-space indentation (new script code, per CLAUDE.md).
"""

from __future__ import annotations

from decimal import Decimal

import pandas as pd

import backtrader as bt

from scripts.crossval.indicators import load_golden_csv
from scripts.crossval.limit_entry_strategy import (
    CASH,
    DATASET,
    FRACTION,
    LIMIT_OFFSET,
    MARKETABLE_MULT,
    SCRIPT,
    SL_PCT,
    TP_PCT,
    WINDOW_END,
    WINDOW_START,
)


def _trigger_for(close: float, kind: str) -> float:
    """The crafted buy-limit trigger for a decision-bar close (shared algebra)."""
    mult = LIMIT_OFFSET if kind == "resting" else MARKETABLE_MULT
    return float(Decimal(str(close)) * mult)


class LimitEntryBacktrader(bt.Strategy):
    """The crafted date-keyed ``buy_limit`` bracket strategy, replicated in backtrader."""

    def __init__(self):
        self.trades_log: list[dict] = []
        self.equity_dates: list[pd.Timestamp] = []
        self.equity_values: list[float] = []
        self._script_by_date = dict(SCRIPT)
        self._in_market = False

    def next(self):
        self.equity_dates.append(self.data.datetime.datetime(0))
        self.equity_values.append(self.broker.getvalue())

        date_key = self.data.datetime.datetime(0).strftime("%Y-%m-%d")
        kind = self._script_by_date.get(date_key)
        if kind is None:
            return
        if self._in_market or self.position:
            return  # single-position, long-only
        close = float(self.data.close[0])
        trigger = _trigger_for(close, kind)
        sl = float(Decimal(str(trigger)) * SL_PCT)
        tp = float(Decimal(str(trigger)) * TP_PCT)
        # FLOAT size on the limit TRIGGER (iTrader sizes/reserves on the signal
        # price = the trigger, D-05). 0.95 of cash / trigger — fractional BTC.
        cash = self.broker.getcash()
        size = float(FRACTION) * cash / trigger
        if size <= 0:
            return
        # buy_bracket: entry Limit + low-side Stop (SL) + high-side Limit (TP),
        # OCO-linked. Default next-bar fills (no cheat-on-open/close).
        self.buy_bracket(
            size=size,
            price=trigger,
            exectype=bt.Order.Limit,
            stopprice=sl,
            limitprice=tp,
        )
        self._in_market = True

    def notify_trade(self, trade):
        if not trade.isclosed:
            return
        self._in_market = False
        self.trades_log.append(
            {
                "entry_date": bt.num2date(trade.dtopen),
                "exit_date": bt.num2date(trade.dtclose),
                "side": "LONG",  # long-only force-match
                "realised_pnl": trade.pnl,
            }
        )


def _normalize_trades(records: list[dict]) -> pd.DataFrame:
    """Assemble notify_trade records into the reconcile shape."""
    if not records:
        return pd.DataFrame(
            columns=["entry_date", "exit_date", "side", "realised_pnl"]
        )
    return pd.DataFrame(records)[
        ["entry_date", "exit_date", "side", "realised_pnl"]
    ]


def run(prices=None, indicators=None):
    """Uniform entry: run the force-match and return (trade_log_df, equity_series).

    ``prices`` None -> load the pinned BTCUSD window internally. ``indicators`` is
    accepted-and-ignored (the crafted strategy declares none).
    """
    if prices is None:
        frame = load_golden_csv(DATASET, WINDOW_START, WINDOW_END)
    else:
        frame = prices.copy()

    feed_frame = pd.DataFrame(
        {
            "open": frame["open"].to_numpy(),
            "high": frame["high"].to_numpy(),
            "low": frame["low"].to_numpy(),
            "close": frame["close"].to_numpy(),
            "volume": frame["volume"].to_numpy(),
        },
        index=pd.DatetimeIndex(frame.index).tz_localize(None),
    )

    cerebro = bt.Cerebro()
    cerebro.broker.setcash(float(CASH))
    cerebro.broker.setcommission(commission=0.0)
    # Default next-bar fills — do NOT enable cheat-on-open/close (D-01).
    cerebro.broker.set_coc(False)
    cerebro.broker.set_coo(False)
    cerebro.adddata(bt.feeds.PandasData(dataname=feed_frame))
    cerebro.addstrategy(LimitEntryBacktrader)

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
        "backtrader LIMIT:",
        len(trades),
        "trades | final_equity",
        float(equity.iloc[-1]),
    )

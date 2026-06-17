"""backtrader trailing-stop force-match module (Plan 05-04, TRAIL-03, A1).

Runs the crafted LONG trailing-stop scenario (shared with
``scripts/crossval/trailing_run.py``) through ``backtrader`` 1.9.78.123, force-matched
to iTrader's rules (cash $100k, zero fees/slippage, FixedQuantity(10), long-only single
position, next-bar fills). This is the trailing analog of the MARKET-only
``backtrader_run.py`` SMA_MACD runner — same uniform ``run()`` contract + normalized
trade columns (entry_date, exit_date, side, realised_pnl).

================================ A1 VERIFICATION ================================
[ASSUMED A1] said backtrader exposes ``StopTrail`` / ``StopTrailLimit`` and "trails off
the CLOSE, activates next bar". VERIFIED against the installed 1.9.78.123 this session:

  * ``bt.Order.StopTrail`` (enum 5) and ``bt.Order.StopTrailLimit`` (enum 6) EXIST;
    ``self.sell(exectype=bt.Order.StopTrail, trailpercent=...)`` is a supported signature
    (``trailamount`` / ``trailpercent`` parameters present on ``Strategy.sell``).
  * backtrader's native ``StopTrail`` ratchets the stop off the LATEST price each bar
    (close-basis, favorably-only) — CONFIRMING the A1 close-basis assumption.
  * To force-match an EXACT percent-of-close trail (iTrader's PERCENT trail_value) and
    keep the three engines byte-aligned with the backtesting.py runner, we manage the
    stop MANUALLY: each bar set ``stop = max(stop, Close*(1-pct))`` and resubmit a
    Stop order at that level (the same close-basis, same-mechanics ratchet backtrader's
    native StopTrail performs, with an exact percent distance). (iTrader trails off the
    closed-bar HIGH; on this crafted frame HIGH == CLOSE on every ratcheting bar so the
    watermarks coincide — see the report's high-vs-close LEGITIMATE-DIFFERENCE.)
================================ END A1 ================================

FRACTIONAL-UNITS / FILL note: FixedQuantity(10) is passed as a plain size to buy/sell;
default next-bar fills (no cheat-on-open/close, D-01). A resting Stop fills at the stop
trigger on the bar whose range pierces it.

SCRIPT-ONLY (D-10): imports backtrader (SyntaxWarning at import would trip
``filterwarnings=["error"]``). NEVER import under tests/. Uniform contract:
``run(prices=None, indicators=None) -> (trade_log_df, equity_series)``. 4-space
indentation (new script code, per CLAUDE.md).
"""

from __future__ import annotations

import pandas as pd

import backtrader as bt

from scripts.crossval.trailing_run import (
    BUY_DATE,
    CASH,
    QTY,
    TRAIL_PCT,
    scenario_frame,
)


def run(prices=None, indicators=None):
    """backtrader trailing long. Returns (trade_log_df, equity_series)."""
    frame = scenario_frame() if prices is None else prices.copy()
    buy_date, pct = BUY_DATE, TRAIL_PCT

    class TrailingLong(bt.Strategy):
        def __init__(self):
            self.trades_log: list[dict] = []
            self.equity_dates: list[pd.Timestamp] = []
            self.equity_values: list[float] = []
            self._in_market = False
            self._stop_order = None
            self._stop_level: float | None = None

        def next(self):
            self.equity_dates.append(self.data.datetime.datetime(0))
            self.equity_values.append(self.broker.getvalue())
            date_key = self.data.datetime.datetime(0).strftime("%Y-%m-%d")

            if date_key == buy_date and not self._in_market:
                self.buy(size=QTY)  # next-bar MARKET fill @ open
                self._in_market = True
                self._stop_level = None
                return

            if not self._in_market:
                return

            # Close-basis trailing ratchet (the verified StopTrail convention, with an
            # exact percent distance): advance the stop UP off the just-closed close,
            # favorably-only, and resubmit a Stop SELL at the new level. The broker
            # evaluates the resting Stop against the next bar's range.
            close = float(self.data.close[0])
            cand = close * (1.0 - pct)
            if self._stop_level is None or cand > self._stop_level:
                self._stop_level = cand
                if self._stop_order is not None:
                    self.cancel(self._stop_order)
                self._stop_order = self.sell(
                    size=QTY, exectype=bt.Order.Stop, price=self._stop_level
                )

        def notify_trade(self, trade):
            if not trade.isclosed:
                return
            self._in_market = False
            self._stop_order = None
            self._stop_level = None
            self.trades_log.append(
                {
                    "entry_date": bt.num2date(trade.dtopen),
                    "exit_date": bt.num2date(trade.dtclose),
                    "side": "LONG",
                    "realised_pnl": trade.pnl,
                }
            )

    feed = pd.DataFrame(
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
    cerebro.broker.setcash(CASH)
    cerebro.broker.setcommission(commission=0.0)
    cerebro.broker.set_coc(False)
    cerebro.broker.set_coo(False)
    cerebro.adddata(bt.feeds.PandasData(dataname=feed))
    cerebro.addstrategy(TrailingLong)
    strat = cerebro.run()[0]
    trades = _normalize_records(strat.trades_log)
    equity = pd.Series(
        strat.equity_values,
        index=pd.DatetimeIndex(strat.equity_dates),
        name="equity",
    )
    return trades, equity


def _normalize_records(records: list[dict]) -> pd.DataFrame:
    if not records:
        return pd.DataFrame(
            columns=["entry_date", "exit_date", "side", "realised_pnl"]
        )
    return pd.DataFrame(records)[
        ["entry_date", "exit_date", "side", "realised_pnl"]
    ]


if __name__ == "__main__":
    trades, equity = run()
    print(
        "backtrader TRAILING:",
        len(trades),
        "trades | final_equity",
        float(equity.iloc[-1]),
        "| realised_pnl",
        None if trades.empty else float(trades["realised_pnl"].iloc[0]),
    )

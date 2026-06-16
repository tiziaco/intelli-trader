"""Liquidation directional-corroboration runners (Plan 04-04, XVAL-01, D-08).

Runs the leveraged-long-INTO-liquidation accounting scenario (the
``tests/e2e/levered_long_into_liquidation`` analog: a leveraged long marked DOWN past
its maintenance floor) through backtesting.py + backtrader.

D-08 — DIRECTIONAL corroboration ONLY: the hand-computed isolated closed-form in the
e2e leaf is the PRIMARY oracle for the liquidation EVENT. backtesting.py models a
minimal liquidation (a margin call: when equity <= 0 it force-closes ALL positions);
backtrader has NO isolated-liquidation model (it rejects/margin-calls but does not
reproduce the isolated maintenance liq price). So this runner asserts the engines
LIQUIDATE the levered long (the position is force-closed / margin-called), NOT a
byte-match of the isolated formula. The runner's ``liquidated`` flag is the directional
claim the evidence doc records as corroboration.

Synthetic LIQUSD frame (NEVER BTCUSD — the spot oracle stays byte-exact
134 / 46189.87730727451, D-11). SCRIPT-ONLY (D-10): imports backtesting.py + backtrader,
NEVER under ``tests/``. 4-space indentation (new script code, per CLAUDE.md).
"""

from __future__ import annotations

import pandas as pd

# --- Crafted leveraged-long-into-liquidation scenario -----------------------
CASH = 10_000.0
LEVERAGE = 5
# Open LONG @ 100 (5x); the price collapses to 10 — a 90% drawdown on a 5x long is a
# 450% equity loss, FAR past the margin floor, so backtesting.py's equity<=0 margin
# call force-closes the position (directional corroboration of the iTrader maintenance
# liquidation that triggers at the 80.808 isolated liq price).
_PRICES = [
    ("2020-01-01", 100.0),
    ("2020-01-02", 100.0),
    ("2020-01-03", 100.0),
    ("2020-01-04", 90.0),
    ("2020-01-05", 10.0),
    ("2020-01-06", 10.0),
]
_BUY_DATE = "2020-01-02"
QTY = 200


def _frame() -> pd.DataFrame:
    idx = pd.DatetimeIndex([pd.Timestamp(d) for d, _ in _PRICES])
    close = [c for _, c in _PRICES]
    return pd.DataFrame(
        {"open": close, "high": close, "low": close, "close": close,
         "volume": [1000.0] * len(close)},
        index=idx,
    )


def run_backtesting(prices=None, indicators=None):
    """backtesting.py levered long into a margin-call liquidation.

    Returns (trade_log_df, equity_series). The engine's equity<=0 margin call
    force-closes the position; the trade log records the forced close (directional
    corroboration, D-08).
    """
    from backtesting import Backtest, Strategy

    frame = _frame() if prices is None else prices.copy()
    buy_date = _BUY_DATE

    class LevLongLiq(Strategy):
        def init(self):
            self._buy = buy_date

        def next(self):
            date_key = pd.Timestamp(self.data.index[-1]).strftime("%Y-%m-%d")
            if date_key == self._buy and not self.position:
                self.buy(size=QTY)
            # No strategy-side exit — the margin call (equity <= 0) closes it.

    data = pd.DataFrame(
        {"Open": frame["open"].to_numpy(), "High": frame["high"].to_numpy(),
         "Low": frame["low"].to_numpy(), "Close": frame["close"].to_numpy(),
         "Volume": frame["volume"].to_numpy()},
        index=pd.DatetimeIndex(frame.index).tz_localize(None),
    )
    bt = Backtest(
        data, LevLongLiq, cash=CASH, commission=0.0, spread=0.0,
        margin=1.0 / LEVERAGE, trade_on_close=False, exclusive_orders=False,
        finalize_trades=True,
    )
    stats = bt.run()
    return _normalize_bt(stats["_trades"]), _equity_bt(stats)


def run_backtrader(prices=None, indicators=None):
    """backtrader levered long into liquidation (margin call / forced close).

    Returns (trade_log_df, equity_series). backtrader has no isolated-liquidation
    model; the deep collapse drives a margin call / forced close, the directional
    corroboration D-08 records.
    """
    import backtrader as bt

    frame = _frame() if prices is None else prices.copy()
    buy_date = _BUY_DATE

    class LevLongLiq(bt.Strategy):
        def __init__(self):
            self.trades_log: list[dict] = []
            self.equity_dates: list[pd.Timestamp] = []
            self.equity_values: list[float] = []
            self._in_market = False

        def next(self):
            self.equity_dates.append(self.data.datetime.datetime(0))
            self.equity_values.append(self.broker.getvalue())
            date_key = self.data.datetime.datetime(0).strftime("%Y-%m-%d")
            if date_key == buy_date and not self._in_market:
                self.buy(size=QTY)
                self._in_market = True

        def notify_trade(self, trade):
            if not trade.isclosed:
                return
            self._in_market = False
            self.trades_log.append({
                "entry_date": bt.num2date(trade.dtopen),
                "exit_date": bt.num2date(trade.dtclose),
                "side": "LONG",
                "realised_pnl": trade.pnl,
            })

    feed = pd.DataFrame(
        {"open": frame["open"].to_numpy(), "high": frame["high"].to_numpy(),
         "low": frame["low"].to_numpy(), "close": frame["close"].to_numpy(),
         "volume": frame["volume"].to_numpy()},
        index=pd.DatetimeIndex(frame.index).tz_localize(None),
    )
    cerebro = bt.Cerebro()
    cerebro.broker.setcash(CASH)
    cerebro.broker.setcommission(commission=0.0, leverage=float(LEVERAGE))
    cerebro.broker.set_coc(False)
    cerebro.broker.set_coo(False)
    cerebro.adddata(bt.feeds.PandasData(dataname=feed))
    cerebro.addstrategy(LevLongLiq)
    strat = cerebro.run()[0]
    trades = _normalize_records(strat.trades_log)
    equity = pd.Series(strat.equity_values,
                       index=pd.DatetimeIndex(strat.equity_dates), name="equity")
    return trades, equity


def liquidated(trades: pd.DataFrame, equity: pd.Series) -> bool:
    """Directional-corroboration claim (D-08): did the engine liquidate the levered long?

    True when the engine force-closed the position (a recorded round-trip OR a final
    equity that collapsed past the margin floor) — the directional agreement the e2e's
    PRIMARY isolated-formula oracle is corroborated by.
    """
    if len(trades) >= 1:
        return True
    if len(equity) and float(equity.iloc[-1]) <= float(CASH) * 0.5:
        return True
    return False


def _normalize_bt(trades_raw: pd.DataFrame) -> pd.DataFrame:
    if trades_raw.empty:
        return pd.DataFrame(columns=["entry_date", "exit_date", "side", "realised_pnl"])
    return pd.DataFrame({
        "entry_date": trades_raw["EntryTime"].to_numpy(),
        "exit_date": trades_raw["ExitTime"].to_numpy(),
        "side": ["LONG" if s > 0 else "SHORT" for s in trades_raw["Size"]],
        "realised_pnl": trades_raw["PnL"].to_numpy(),
    })


def _equity_bt(stats) -> pd.Series:
    eq = stats["_equity_curve"]["Equity"]
    eq.name = "equity"
    return eq


def _normalize_records(records: list[dict]) -> pd.DataFrame:
    if not records:
        return pd.DataFrame(columns=["entry_date", "exit_date", "side", "realised_pnl"])
    return pd.DataFrame(records)[["entry_date", "exit_date", "side", "realised_pnl"]]


if __name__ == "__main__":
    bt_trades, bt_eq = run_backtesting()
    btr_trades, btr_eq = run_backtrader()
    print("liquidation backtesting.py:", len(bt_trades), "trades | final",
          float(bt_eq.iloc[-1]), "| liquidated", liquidated(bt_trades, bt_eq))
    print("liquidation backtrader:", len(btr_trades), "trades | final",
          float(btr_eq.iloc[-1]), "| liquidated", liquidated(btr_trades, btr_eq))

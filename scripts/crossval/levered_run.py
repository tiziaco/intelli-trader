"""Leveraged-long cross-validation runners (Plan 04-04, XVAL-01, D-08).

Runs the crafted leveraged-long accounting scenario (the ``tests/e2e/levered_long``
analog: a leveraged long that takes an adverse-but-surviving mark then closes at a
profit) through backtesting.py + backtrader, force-matched to iTrader's rules. Both
reference engines model leverage as ``margin = 1 / leverage`` (the same admission
reservation = notional / L iTrader books), so this scenario FULLY cross-validates
trade-level + metric-level (not just directionally).

Accounting-core analog of ``scripts/crossval/backtesting_py_run.py`` — uniform
``run_*()`` contract, normalized trade columns. Synthetic LEVUSD frame (NEVER BTCUSD —
the spot oracle stays byte-exact 134 / 46189.87730727451, D-11), hand-derivable.

SCRIPT-ONLY (D-10): imports backtesting.py + backtrader. NEVER import under ``tests/``.
4-space indentation (new script code, per CLAUDE.md).
"""

from __future__ import annotations

import pandas as pd

# --- Crafted leveraged-long scenario (mirrors tests/e2e/levered_long) -------
CASH = 10_000.0
LEVERAGE = 5            # effective leverage (iTrader clamps 20 -> 5); margin = 1/5
# Open LONG @ 100 (5x), adverse mark to 90 (survives), close @ 120 for a profit.
#   2020-01-02 decision BUY -> fills 2020-01-03 @ 100
#   2020-01-05 decision SELL -> fills 2020-01-06 @ 120
_PRICES = [
    ("2020-01-01", 100.0),
    ("2020-01-02", 100.0),
    ("2020-01-03", 100.0),
    ("2020-01-04", 90.0),
    ("2020-01-05", 120.0),
    ("2020-01-06", 120.0),
]
_BUY_DATE = "2020-01-02"
_SELL_DATE = "2020-01-05"
# iTrader sizes notional = f x equity = 2 x 10_000 = 20_000.
NOTIONAL = 2 * CASH


def _entry_price(buy_date: str) -> float:
    """Fill price for a decision on ``buy_date`` (next-bar fill -> that bar's close)."""
    dates = [d for d, _ in _PRICES]
    fill_close = _PRICES[dates.index(buy_date) + 1][1]
    return fill_close


# IN-03: derive QTY from notional / entry_price so it TRACKS the frame instead of
# being correct only by coincidence of a flat-100 entry. If the synthetic frame's
# entry close changes, the reference QTY follows the iTrader-sized qty.
QTY = int(NOTIONAL / _entry_price(_BUY_DATE))


def _frame() -> pd.DataFrame:
    idx = pd.DatetimeIndex([pd.Timestamp(d) for d, _ in _PRICES])
    close = [c for _, c in _PRICES]
    return pd.DataFrame(
        {"open": close, "high": close, "low": close, "close": close,
         "volume": [1000.0] * len(close)},
        index=idx,
    )


def run_backtesting(prices=None, indicators=None):
    """backtesting.py leveraged long. Returns (trade_log_df, equity_series)."""
    from backtesting import Backtest, Strategy

    frame = _frame() if prices is None else prices.copy()
    buy_date, sell_date = _BUY_DATE, _SELL_DATE

    class LeveredLong(Strategy):
        def init(self):
            self._buy = buy_date
            self._sell = sell_date

        def next(self):
            date_key = pd.Timestamp(self.data.index[-1]).strftime("%Y-%m-%d")
            if date_key == self._buy and not self.position:
                # Whole-unit absolute size = 200 (iTrader LeveredFraction f=2 sizes
                # notional 20_000 -> 200 units). Leverage enters via the Backtest
                # margin = 1/LEVERAGE below.
                self.buy(size=QTY)
            elif date_key == self._sell and self.position:
                self.position.close()

    data = pd.DataFrame(
        {"Open": frame["open"].to_numpy(), "High": frame["high"].to_numpy(),
         "Low": frame["low"].to_numpy(), "Close": frame["close"].to_numpy(),
         "Volume": frame["volume"].to_numpy()},
        index=pd.DatetimeIndex(frame.index).tz_localize(None),
    )
    bt = Backtest(
        data, LeveredLong, cash=CASH, commission=0.0, spread=0.0,
        margin=1.0 / LEVERAGE,  # the leverage model: reserve notional / L
        trade_on_close=False, exclusive_orders=False, finalize_trades=True,
    )
    stats = bt.run()
    return _normalize_bt(stats["_trades"]), _equity_bt(stats)


def run_backtrader(prices=None, indicators=None):
    """backtrader leveraged long (comminfo leverage). Returns (trade_log_df, equity_series)."""
    import backtrader as bt

    frame = _frame() if prices is None else prices.copy()
    buy_date, sell_date = _BUY_DATE, _SELL_DATE

    class LeveredLong(bt.Strategy):
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
            elif date_key == sell_date and self._in_market:
                self.close()

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
    cerebro.addstrategy(LeveredLong)
    strat = cerebro.run()[0]
    trades = _normalize_records(strat.trades_log)
    equity = pd.Series(strat.equity_values,
                       index=pd.DatetimeIndex(strat.equity_dates), name="equity")
    return trades, equity


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
    print("levered backtesting.py:", len(bt_trades), "trades | final", float(bt_eq.iloc[-1]))
    print("levered backtrader:", len(btr_trades), "trades | final", float(btr_eq.iloc[-1]))

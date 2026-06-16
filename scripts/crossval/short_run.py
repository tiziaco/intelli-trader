"""Short round-trip cross-validation runners (Plan 04-04, XVAL-01, D-08).

Runs the crafted SHORT round-trip accounting scenario (SELL-to-open -> BUY-to-cover,
the ``tests/e2e/short_roundtrip`` analog) through backtesting.py + backtrader,
force-matched to iTrader's rules (zero fees/slippage, fixed quantity, next-bar fills).
backtesting.py and backtrader BOTH model shorts as a first-class direction, so this
scenario FULLY cross-validates (trade-level + metric-level), not just directionally.

This is the accounting-core analog of ``scripts/crossval/backtesting_py_run.py`` (the
MARKET SMA_MACD runner) — it preserves the uniform ``run_*()`` contract and the
normalized trade columns (``entry_date, exit_date, side, realised_pnl``). The price
series is a small synthetic SHORTUSD frame (NEVER BTCUSD — the spot oracle stays
byte-exact 134 / 46189.87730727451, D-11), hand-derivable so every fill is checkable.

SCRIPT-ONLY (D-10): imports backtesting.py (bokeh) + backtrader (SyntaxWarning at
import). NEVER import under ``tests/`` — the engines' import-time warnings would trip
``filterwarnings=["error"]``. 4-space indentation (new script code, per CLAUDE.md).
"""

from __future__ import annotations

import pandas as pd

# --- Crafted SHORT scenario (mirrors tests/e2e/short_roundtrip) -------------
CASH = 100_000.0
QTY = 10.0
# Flat-OHLC daily series: open SHORT @ 100, price falls to 80 (favorable), cover @ 80.
#   2020-01-02 decision SELL -> fills 2020-01-03 @ 100
#   2020-01-04 decision BUY-cover -> fills 2020-01-05 @ 80
_PRICES = [
    ("2020-01-01", 100.0),
    ("2020-01-02", 100.0),
    ("2020-01-03", 100.0),
    ("2020-01-04", 80.0),
    ("2020-01-05", 80.0),
    ("2020-01-06", 80.0),
]
_SELL_DATE = "2020-01-02"
_COVER_DATE = "2020-01-04"


def _frame() -> pd.DataFrame:
    """The synthetic flat-OHLC SHORTUSD frame (tz-naive index for the engines)."""
    idx = pd.DatetimeIndex([pd.Timestamp(d) for d, _ in _PRICES])
    close = [c for _, c in _PRICES]
    return pd.DataFrame(
        {"open": close, "high": close, "low": close, "close": close,
         "volume": [1000.0] * len(close)},
        index=idx,
    )


def run_backtesting(prices=None, indicators=None):
    """backtesting.py short round-trip. Returns (trade_log_df, equity_series)."""
    from backtesting import Backtest, Strategy

    frame = _frame() if prices is None else prices.copy()
    sell_date, cover_date = _SELL_DATE, _COVER_DATE

    class ShortRoundtrip(Strategy):
        def init(self):
            self._sell = sell_date
            self._cover = cover_date

        def next(self):
            date_key = pd.Timestamp(self.data.index[-1]).strftime("%Y-%m-%d")
            if date_key == self._sell and not self.position:
                # FIXED quantity short (mirror iTrader FixedQuantity(10)). A plain
                # Backtest treats an integer size as an absolute whole-unit count, so
                # this shorts exactly QTY units (10) — the FixedQuantity analog, no
                # fractional-units rescaling.
                self.sell(size=int(QTY))
            elif date_key == self._cover and self.position:
                self.position.close()

    data = pd.DataFrame(
        {"Open": frame["open"].to_numpy(), "High": frame["high"].to_numpy(),
         "Low": frame["low"].to_numpy(), "Close": frame["close"].to_numpy(),
         "Volume": frame["volume"].to_numpy()},
        index=pd.DatetimeIndex(frame.index).tz_localize(None),
    )
    bt = Backtest(
        data, ShortRoundtrip, cash=CASH, commission=0.0, spread=0.0, margin=1.0,
        trade_on_close=False, exclusive_orders=False, finalize_trades=True,
    )
    stats = bt.run()
    return _normalize_bt(stats["_trades"]), _equity_bt(stats)


def run_backtrader(prices=None, indicators=None):
    """backtrader short round-trip. Returns (trade_log_df, equity_series)."""
    import backtrader as bt

    frame = _frame() if prices is None else prices.copy()
    sell_date, cover_date = _SELL_DATE, _COVER_DATE

    class ShortRoundtrip(bt.Strategy):
        def __init__(self):
            self.trades_log: list[dict] = []
            self.equity_dates: list[pd.Timestamp] = []
            self.equity_values: list[float] = []
            self._in_market = False

        def next(self):
            self.equity_dates.append(self.data.datetime.datetime(0))
            self.equity_values.append(self.broker.getvalue())
            date_key = self.data.datetime.datetime(0).strftime("%Y-%m-%d")
            if date_key == sell_date and not self._in_market:
                self.sell(size=QTY)
                self._in_market = True
            elif date_key == cover_date and self._in_market:
                self.close()

        def notify_trade(self, trade):
            if not trade.isclosed:
                return
            self._in_market = False
            self.trades_log.append({
                "entry_date": bt.num2date(trade.dtopen),
                "exit_date": bt.num2date(trade.dtclose),
                "side": "SHORT",
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
    cerebro.broker.setcommission(commission=0.0)
    cerebro.broker.set_coc(False)
    cerebro.broker.set_coo(False)
    cerebro.adddata(bt.feeds.PandasData(dataname=feed))
    cerebro.addstrategy(ShortRoundtrip)
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
    print("short backtesting.py:", len(bt_trades), "trades | final", float(bt_eq.iloc[-1]))
    print("short backtrader:", len(btr_trades), "trades | final", float(btr_eq.iloc[-1]))

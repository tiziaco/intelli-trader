"""backtesting.py trailing-stop force-match module (Plan 05-04, TRAIL-03, A1).

Runs the crafted LONG trailing-stop scenario (shared with
``scripts/crossval/trailing_run.py``) through ``backtesting.py`` 0.6.5, force-matched
to iTrader's rules (cash $100k, zero fees/slippage, FixedQuantity(10), long-only
single position, next-bar fills). This is the trailing analog of the MARKET-only
``backtesting_py_run.py`` SMA_MACD runner — same uniform ``run()`` contract +
normalized trade columns (entry_date, exit_date, side, realised_pnl).

================================ A1 VERIFICATION ================================
[ASSUMED A1] said backtesting.py exposes ``TrailingStrategy`` / ``set_trailing_sl``
and "trails off the CLOSE, activates next bar". VERIFIED against the installed
0.6.5 this session:

  * ``backtesting.lib.TrailingStrategy`` EXISTS; ``set_trailing_sl(n_atr=6)`` and
    ``set_trailing_pct(pct)`` EXIST.
  * ITS TRAIL BASIS IS THE **CLOSE**, NOT the high: ``TrailingStrategy.next()`` sets
    ``trade.sl = max(trade.sl, Close[i] - atr[i]*n_atr)`` every bar (read from the
    installed source). This CONFIRMS the A1 close-basis assumption.
  * BUT the trail DISTANCE is an ATR multiple, and ``set_trailing_pct`` is documented
    INEXACT ("converted to units of ATR with mean(Close*pct/atr)"). To force-match a
    clean PERCENT-of-close trail (iTrader's PERCENT trail_value), we do NOT use the
    ATR machinery; we set ``trade.sl = max(trade.sl, Close*(1-pct))`` DIRECTLY each
    bar — the same close-based, same-bar-active ratchet TrailingStrategy uses, with an
    EXACT percent distance. This is a faithful force-match of the documented convention
    (close-basis ratchet), not a re-implementation of the indicator.
  * ACTIVATION: backtesting.py updates ``trade.sl`` in ``next()`` and the broker
    evaluates resting SLs against the NEXT bar's range — i.e. close-basis ratchet from
    the just-closed bar, live the next bar. (iTrader trails off the closed-bar HIGH; on
    this crafted frame HIGH == CLOSE on every ratcheting bar so the two watermarks
    coincide — see the report's high-vs-close LEGITIMATE-DIFFERENCE.)
================================ END A1 ================================

SCRIPT-ONLY (D-10): imports backtesting.py (bokeh). NEVER import under tests/ — the
engine's import-time warnings would trip ``filterwarnings=["error"]``. Uniform
contract: ``run(prices=None, indicators=None) -> (trade_log_df, equity_series)``.
4-space indentation (new script code, per CLAUDE.md).
"""

from __future__ import annotations

import pandas as pd

from backtesting import Backtest, Strategy

from scripts.crossval.trailing_run import (
    BUY_DATE,
    CASH,
    QTY,
    TRAIL_PCT,
    scenario_frame,
)


def run(prices=None, indicators=None):
    """backtesting.py trailing long. Returns (trade_log_df, equity_series)."""
    frame = scenario_frame() if prices is None else prices.copy()
    buy_date, pct = BUY_DATE, TRAIL_PCT

    class TrailingLong(Strategy):
        def init(self):
            self._buy_date = buy_date
            self._pct = pct

        def next(self):
            date_key = pd.Timestamp(self.data.index[-1]).strftime("%Y-%m-%d")
            if date_key == self._buy_date and not self.position:
                # FixedQuantity(10) — an integer size is an absolute whole-unit count
                # on a plain Backtest (the FixedQuantity analog, no fractional rescale).
                self.buy(size=int(QTY))
            # Close-basis trailing ratchet (the verified TrailingStrategy convention,
            # with an EXACT percent distance instead of the inexact ATR conversion):
            # ratchet each open LONG trade's stop UP off the just-closed bar's close,
            # favorably-only. The broker evaluates the resting SL on the next bar.
            close = float(self.data.Close[-1])
            cand = close * (1.0 - self._pct)
            for trade in self.trades:
                if trade.is_long:
                    trade.sl = cand if trade.sl is None else max(trade.sl, cand)

    data = pd.DataFrame(
        {
            "Open": frame["open"].to_numpy(),
            "High": frame["high"].to_numpy(),
            "Low": frame["low"].to_numpy(),
            "Close": frame["close"].to_numpy(),
            "Volume": frame["volume"].to_numpy(),
        },
        index=pd.DatetimeIndex(frame.index).tz_localize(None),
    )
    bt = Backtest(
        data,
        TrailingLong,
        cash=CASH,
        commission=0.0,
        spread=0.0,
        margin=1.0,
        trade_on_close=False,  # next-bar fills
        exclusive_orders=False,  # the strategy enforces single-position itself
        finalize_trades=True,
    )
    stats = bt.run()
    return _normalize_trades(stats["_trades"]), _equity(stats)


def _normalize_trades(trades_raw: pd.DataFrame) -> pd.DataFrame:
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


def _equity(stats) -> pd.Series:
    eq = stats["_equity_curve"]["Equity"]
    eq.name = "equity"
    return eq


if __name__ == "__main__":
    trades, equity = run()
    print(
        "backtesting.py TRAILING:",
        len(trades),
        "trades | final_equity",
        float(equity.iloc[-1]),
        "| realised_pnl",
        None if trades.empty else float(trades["realised_pnl"].iloc[0]),
    )

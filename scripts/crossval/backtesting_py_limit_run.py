"""backtesting.py LIMIT-entry force-match module (Plan 05-04, D-07).

Runs the crafted ``LimitEntryStrategy`` (date-keyed ``buy_limit`` + percent SL/TP)
on the pinned BTCUSD golden window through ``backtesting.py``, force-matched to
iTrader's rules (cash $10k, zero fees/slippage, 0.95-of-equity FRACTIONAL sizing
on the LIMIT TRIGGER price, long-only single position, next-bar fills). This is the
LIMIT-entry analog of the MARKET-only ``backtesting_py_run.py`` SMA_MACD runner —
it preserves the same uniform ``run()`` contract and normalized trade columns.

THE FILL ALGEBRA (the three-engine-agreement anchor, RESEARCH Pitfall 3): a BUY
limit fills at ``min(open, limit)`` (limit-or-better) — identical to iTrader's
``MatchingEngine._evaluate``. backtesting.py's ``_process_orders`` computes the
same ``min(stop_price or open, limit)`` for a long limit, so the resting-limit
entry (fills AT the limit on an in-bar touch) and the marketable-limit entry
(fills at the better OPEN on a favorable gap) both reproduce by construction.

The bracket: backtesting.py supports ``sl=``/``tp=`` on ``self.buy(...)`` (a
native OCO bracket). The SL/TP levels are the strategy's ABSOLUTE percent levels
(trigger * 0.95 / trigger * 1.15), so they match iTrader's bracket children.

SCRIPT-ONLY (D-10): imports backtesting.py (bokeh). NEVER import under tests/ —
the engine's import-time warnings would trip ``filterwarnings=["error"]``.

Uniform contract: ``run(prices=None, indicators=None) -> (trade_log_df,
equity_curve_series)``. None args -> load the pinned window internally; injected
``prices`` -> use that frame. ``indicators`` is accepted-and-ignored (this crafted
strategy declares no indicators) so the orchestrator can call every runner with
the same signature. ``trade_log_df`` is NORMALIZED to columns ``entry_date,
exit_date, side, realised_pnl``.

4-space indentation (new script code, per CLAUDE.md).
"""

from __future__ import annotations

from decimal import Decimal

import pandas as pd

from backtesting import Strategy
from backtesting.lib import FractionalBacktest

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

# μBTC granularity — small enough that the fractional sizing never floors to 0.
FRACTIONAL_UNIT = 1e-6


def _trigger_for(close: float, kind: str) -> float:
    """The crafted buy-limit trigger for a decision-bar close (shared algebra)."""
    mult = LIMIT_OFFSET if kind == "resting" else MARKETABLE_MULT
    return float(Decimal(str(close)) * mult)


class LimitEntryBacktesting(Strategy):
    """The crafted date-keyed ``buy_limit`` strategy, replicated in backtesting.py.

    On a scripted decision-bar date it places a LIMIT BUY (resting below market or
    marketable above market) sized at ``FRACTION`` of current equity on the limit
    TRIGGER price, with a native SL/TP bracket at the strategy's absolute percent
    levels. backtesting.py rests the limit and fills it at ``min(open, limit)``.
    """

    def init(self):
        # Map each bar index to its decision kind ("resting"/"marketable") so next()
        # can place the crafted limit on the scripted dates. The data index is the
        # tz-naive bar datetime; key by the "YYYY-MM-DD" string like the strategy.
        self._script_by_date = dict(SCRIPT)

    def next(self):
        date_key = pd.Timestamp(self.data.index[-1]).strftime("%Y-%m-%d")
        kind = self._script_by_date.get(date_key)
        if kind is None:
            return
        if self.position:
            return  # single-position, long-only (mirrors max_positions=1)
        close = float(self.data.Close[-1])
        trigger = _trigger_for(close, kind)
        sl = float(Decimal(str(trigger)) * SL_PCT)
        tp = float(Decimal(str(trigger)) * TP_PCT)
        # Size as a FRACTION of equity (backtesting.py requires 0 < size < 1 for a
        # fractional-of-equity order). 0.95 mirrors iTrader's FractionOfCash(0.95).
        # NOTE (A1 cross-engine caveat): backtesting.py converts this fraction into
        # a unit count at the FILL price, whereas iTrader sizes on the limit TRIGGER
        # (D-05). On the marketable case (fill at open != trigger) this is a small,
        # documented sizing-basis divergence the reconcile machinery dispositions.
        self.buy(size=float(FRACTION), limit=trigger, sl=sl, tp=tp)


def _normalize_trades(trades_raw: pd.DataFrame) -> pd.DataFrame:
    """Map backtesting.py ``stats['_trades']`` to the reconcile shape.

    Columns: entry_date (EntryTime), exit_date (ExitTime), side (long-only ->
    "LONG"), realised_pnl (PnL).
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

    ``prices`` None -> load the pinned BTCUSD window internally. ``indicators`` is
    accepted-and-ignored (the crafted strategy declares none) so the orchestrator
    can call every runner with the same signature.
    """
    if prices is None:
        frame = load_golden_csv(DATASET, WINDOW_START, WINDOW_END)
    else:
        frame = prices.copy()

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

    bt = FractionalBacktest(
        data,
        LimitEntryBacktesting,
        cash=float(CASH),
        commission=0.0,
        spread=0.0,
        margin=1.0,
        trade_on_close=False,  # next-bar fills (D-01)
        exclusive_orders=False,  # the strategy enforces single-position itself
        finalize_trades=True,  # close any still-open trade at the last bar
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
        "backtesting.py LIMIT:",
        len(trades),
        "trades | final_equity",
        float(equity.iloc[-1]),
    )

"""iTrader white-box trailing-stop runner (Plan 05-04, TRAIL-03, D-TRAIL-1/2).

Drives the crafted LONG trailing-stop scenario through the REAL iTrader engine (the
e2e white-box build path) and returns the normalized trade log + per-bar equity so
the orchestrator (``scripts/cross_validate_trailing.py``) can reconcile it against
the two gating reference engines. iTrader is the AUTHORITATIVE baseline.

THE SCENARIO (hand-computable, synthetic ``TRAILUSD`` — NEVER BTCUSD so the spot
oracle stays byte-exact 134 / 46189.87730727451): a strategy declares a trailing-SL
bracket (``PercentFromFill`` carrying a 10% PERCENT trail). The SL child rests as an
engine-native ``TRAILING_STOP`` seeded from the ENTRY FILL (D-TRAIL-3), ratchets UP
across rising closed-bar highs (D-TRAIL-1/2, favorably-only, live the NEXT bar), then
a sharp single-bar drop triggers the RATCHETED level.

THE FORCE-MATCH (cross-engine alignment, see the report's high-vs-close disposition):
the rising leg uses ``high == close`` on every ratcheting bar, so iTrader's HIGH-based
watermark (D-TRAIL-1) and the oracles' CLOSE-based watermark COINCIDE — the only
remaining engine difference (iTrader arms NEXT bar, the oracles arm SAME bar) does not
change the exit bar because the trail distance (10%) is large relative to the gentle
intrabar range on the rising leg and the single drop bar opens above the stop while its
low pierces far below it. All three engines therefore gap-fill at the SAME ratcheted
stop on the SAME bar -> trade-level PRIMARY reconciliation is exact, the residual
high-vs-close gap is a documented LEGITIMATE-DIFFERENCE (it would only SHIFT a trade by
a bar on a borderline series where high != close on a ratcheting bar).

This mirrors ``tests/e2e/trailing_long`` (the regression lock) but uses its OWN crafted
frame so the alignment-with-oracles property above holds. The uniform contract returns
``(trades_df, equity_series, headline_dict)`` with trades normalized to the reconcile
shape (entry_date, exit_date, side, realised_pnl).

NOTE: this module imports ONLY ``itrader`` (never a reference engine), so it is safe to
sit alongside the oracle runners under ``scripts/crossval/``. 4-space indentation
(new script code, per CLAUDE.md).
"""

from __future__ import annotations

import pathlib
import tempfile
from decimal import Decimal

import pandas as pd

from itrader.config import TrailType
from itrader.core.enums import Side
from itrader.core.enums.order import OrderType
from itrader.core.enums.trading import TradingDirection
from itrader.core.sizing import FixedQuantity, PercentFromFill, SignalIntent
from itrader.strategy_handler.base import Strategy
from itrader.trading_system.backtest_trading_system import BacktestTradingSystem
from scripts.crossval import reconcile

_TICKER = "TRAILUSD"  # synthetic — NEVER BTCUSD.
_CASH = 100_000
_QTY = Decimal("10")
_TRAIL_PCT = Decimal("0.10")
_START = "2020-01-01"
_END = "2020-01-08"
_BUY_DATE = "2020-01-02"

# Crafted flat-on-the-rising-leg frame: HIGH == CLOSE on every ratcheting bar so the
# HIGH-based (iTrader) and CLOSE-based (oracle) watermarks coincide; the single drop
# bar (01-07) opens above the ratcheted stop (~100.8) and its low (90) pierces far
# below it, so every engine gap-fills at the SAME stop on the SAME bar.
#   (Open, High, Low, Close)
_BARS: list[tuple[str, float, float, float, float]] = [
    ("2020-01-01", 100.0, 100.0, 100.0, 100.0),
    ("2020-01-02", 100.0, 100.0, 100.0, 100.0),  # BUY decided (MARKET)
    ("2020-01-03", 100.0, 100.0, 100.0, 100.0),  # parent fills @ OPEN 100 == anchor
    ("2020-01-04", 100.0, 105.0, 100.0, 105.0),  # high == close 105
    ("2020-01-05", 105.0, 110.0, 105.0, 110.0),  # high == close 110
    ("2020-01-06", 110.0, 112.0, 110.0, 112.0),  # high == close 112 -> stop 100.8
    ("2020-01-07", 112.0, 112.0, 90.0, 95.0),    # drop: low 90 << stop -> TRIGGER @100.8
    ("2020-01-08", 95.0, 95.0, 95.0, 95.0),
]


def scenario_frame() -> pd.DataFrame:
    """The shared synthetic TRAILUSD OHLC frame (tz-naive index for the oracles)."""
    idx = pd.DatetimeIndex([pd.Timestamp(d) for d, *_ in _BARS])
    return pd.DataFrame(
        {
            "open": [o for _d, o, _h, _l, _c in _BARS],
            "high": [h for _d, _o, h, _l, _c in _BARS],
            "low": [l for _d, _o, _h, l, _c in _BARS],
            "close": [c for _d, _o, _h, _l, c in _BARS],
            "volume": [1000.0] * len(_BARS),
        },
        index=idx,
    )


# Cross-engine shared constants (the oracle runners import these for the force-match).
CASH = float(_CASH)
QTY = float(_QTY)
TRAIL_PCT = float(_TRAIL_PCT)
BUY_DATE = _BUY_DATE


_TRAIL = PercentFromFill(
    sl_pct=_TRAIL_PCT,
    tp_pct=Decimal("5"),  # TP-limit far above the path; the trailing SL is the exit.
    trail_type=TrailType.PERCENT,
    trail_value=_TRAIL_PCT,
)


class _TrailingLongStrategy(Strategy):
    """A LONG strategy declaring a trailing-SL bracket on a single MARKET BUY."""

    name = "trailing_xval_long"
    max_window = 100
    warmup = 0
    sizing_policy = FixedQuantity(qty=_QTY)
    sltp_policy = _TRAIL
    direction = TradingDirection.LONG_ONLY

    def __init__(self, timeframe: str, tickers: list[str]) -> None:
        super().__init__(timeframe=timeframe, tickers=list(tickers))

    def generate_signal(self, ticker: str) -> SignalIntent | None:
        date = self.now.tz_convert("UTC").strftime("%Y-%m-%d")
        if date == _BUY_DATE:
            return SignalIntent(
                ticker=ticker, action=Side.BUY, order_type=OrderType.MARKET
            )
        return None


def _write_bars_csv(path: pathlib.Path) -> None:
    """Materialize the crafted frame in the tz-aware CsvPriceStore schema."""
    rows = ["Open time,Open,High,Low,Close,Volume"]
    for d, o, h, l, c in _BARS:
        rows.append(f"{d} 00:00:00+00:00,{o},{h},{l},{c},1000.0")
    path.write_text("\n".join(rows) + "\n")


def _build_system(tmpdir: pathlib.Path):
    """Build the real backtest engine on the crafted TRAILUSD frame."""
    bars_csv = tmpdir / "trailusd_bars.csv"
    _write_bars_csv(bars_csv)
    system = BacktestTradingSystem(
        exchange="csv",
        csv_paths={_TICKER: bars_csv},
        start_date=_START,
        end_date=_END,
    )
    strategy = _TrailingLongStrategy(timeframe="1d", tickers=[_TICKER])
    system.strategies_handler.add_strategy(strategy)
    portfolio_id = system.portfolio_handler.add_portfolio(
        user_id=1, name="trailing_xval_pf", exchange="csv", cash=_CASH
    )
    strategy.subscribe_portfolio(portfolio_id)
    system.runner._initialise_backtest_session()
    return system, portfolio_id


def run_itrader():
    """Drive the trailing scenario through the REAL iTrader engine.

    Returns ``(trades_df, equity_series, headline_dict)``; trades normalized to the
    reconcile shape (entry_date, exit_date, side, realised_pnl).
    """
    with tempfile.TemporaryDirectory() as td:
        system, portfolio_id = _build_system(pathlib.Path(td))
        engine = system.engine
        handler = system.portfolio_handler
        portfolio = handler.get_portfolio(portfolio_id)

        equity_rows: list[tuple] = []
        for time_event in engine.time_generator:
            engine.clock.set_time(time_event.time)
            engine.global_queue.put(time_event)
            engine.event_handler.process_events()
            for active in handler.get_active_portfolios():
                active.record_metrics(time_event.time)
            equity_rows.append((time_event.time, handler.total_equity(portfolio_id)))
        engine.order_handler.expire_all_resting()
        engine.event_handler.process_events()

        closed = portfolio.closed_positions
        trades = pd.DataFrame(
            {
                "entry_date": [p.entry_date for p in closed],
                "exit_date": [getattr(p, "exit_date", None) for p in closed],
                "side": [p.side.name for p in closed],
                "realised_pnl": [float(p.realised_pnl) for p in closed],
            }
        )
        equity = pd.Series(
            [float(e) for _t, e in equity_rows],
            index=pd.DatetimeIndex(
                [
                    pd.Timestamp(t).tz_convert("UTC").tz_localize(None)
                    for t, _e in equity_rows
                ]
            ),
            name="equity",
        )
    headline = reconcile.recompute_headline(equity, trades)
    return trades, equity, headline


if __name__ == "__main__":
    trades, equity, headline = run_itrader()
    print(
        "iTrader TRAILING:",
        len(trades),
        "trades | final_equity",
        float(equity.iloc[-1]),
        "| realised_pnl",
        None if trades.empty else float(trades["realised_pnl"].iloc[0]),
    )

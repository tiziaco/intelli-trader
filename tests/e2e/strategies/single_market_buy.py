"""Contrived single-round-trip strategy for the E2E canary (Phase 4, D-04/D-12).

``SingleMarketBuy`` is a purpose-built, deterministic strategy that lives in the
SHARED ``tests/e2e/strategies/`` library (D-04 — referenced, never inlined, by a
leaf's ``scenario.py``). It is NOT alpha: it fires by COUNT of completed bars so
its fills and PnL are hand-derivable on a tiny contrived ``bars.csv``.

Behavior (the contract the canary's VERIFY note depends on)
-----------------------------------------------------------
The handler pushes the look-ahead-safe completed-bar window each tick; with
``max_window`` set wide enough to cover the whole contrived CSV, ``len(bars)`` is
exactly the number of completed bars visible at the decision tick. The strategy:

* emits ONE MARKET ``buy`` on the tick where ``len(bars) == fire_on_bar`` — that
  entry fills at the NEXT bar's open (the Phase 6 next-bar-open convention); and
* emits ONE MARKET ``sell`` (a full exit, ``exit_fraction`` defaults to 1) on the
  tick where ``len(bars) == exit_on_bar`` — that exit fills at the following bar's
  open, fully closing the long so exactly ONE round-trip trade lands in
  ``portfolio.closed_positions``.

``max_window`` is deliberately NOT 0: the handler slices ``feed.window(..., max_window,
...)`` and a 0-width window is always empty (``len(bars) == 0`` forever), so a
count-based fire needs ``max_window >= exit_on_bar``. There is no indicator warmup
to gate — the wide window simply lets the strategy SEE the bar count. It still does
no resampling and no alpha; it is a pinned-bar canary, not SMA_MACD.
"""

from decimal import Decimal

import pandas as pd

from itrader.core.sizing import FractionOfCash, SignalIntent, TradingDirection
from itrader.strategy_handler.base import Strategy


class SingleMarketBuy(Strategy):
    """Fire one MARKET buy then one full MARKET exit, both by completed-bar count.

    Parameters
    ----------
    timeframe : str
        Bar timeframe alias, e.g. ``"1d"``.
    tickers : list[str]
        The tickers the strategy trades (the canary subscribes exactly one).
    fire_on_bar : int
        Completed-bar count at which the single MARKET BUY is emitted.
    exit_on_bar : int
        Completed-bar count at which the single full MARKET SELL (exit) is
        emitted. Must be > ``fire_on_bar`` so the entry fills before the exit.
    """

    def __init__(self, timeframe: str, tickers: list[str], *,
                 fire_on_bar: int = 2, exit_on_bar: int = 4) -> None:
        # FractionOfCash(Decimal("0.95")) is the string-path literal (Pitfall 1)
        # — the SAME golden sizing policy SMA_MACD declares — so the canary's
        # entry quantity is hand-derivable: 0.95 * available_cash / fill_price.
        super().__init__(
            "single_market_buy", timeframe, list(tickers),
            sizing_policy=FractionOfCash(Decimal("0.95")),
            direction=TradingDirection.LONG_ONLY,
            allow_increase=False,
        )
        self.fire_on_bar = fire_on_bar
        self.exit_on_bar = exit_on_bar
        # Wide enough to cover the contrived CSV so len(bars) == completed-bar
        # count (a 0-width window would always be empty — see module docstring).
        self.max_window = 100

    def generate_signal(self, ticker: str, bars: pd.DataFrame) -> SignalIntent | None:
        if len(bars) == self.fire_on_bar:
            return self.buy(ticker)
        if len(bars) == self.exit_on_bar:
            return self.sell(ticker)
        return None

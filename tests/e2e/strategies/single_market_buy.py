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

    name = "single_market_buy"
    # Wide enough to cover the contrived CSV so len(bars) == completed-bar
    # count (a 0-width window would always be empty — see module docstring).
    # warmup stays 0 (no warmup gating) so the framework short-circuit
    # never skips the count-based firing tick (D-15) — preserving the
    # frozen e2e golden.
    max_window: int = 100

    def __init__(self, timeframe: str, tickers: list[str], *,
                 fire_on_bar: int = 2, exit_on_bar: int = 4) -> None:
        # D-05 (Plan 02-03): pass the golden params straight through the base
        # **kwargs surface (no pydantic config layer, no shim).
        # FractionOfCash(Decimal("0.95")) is the string-path literal (Pitfall 4)
        # — the SAME golden sizing policy SMA_MACD declares — so the canary's
        # entry quantity is hand-derivable: 0.95 * available_cash / fill_price.
        super().__init__(
            timeframe=timeframe,
            tickers=list(tickers),
            sizing_policy=FractionOfCash(Decimal("0.95")),
            direction=TradingDirection.LONG_ONLY,
            allow_increase=False,
        )
        self.fire_on_bar = fire_on_bar
        self.exit_on_bar = exit_on_bar

    def generate_signal(self, ticker: str) -> SignalIntent | None:
        # P5-D13a: the per-tick self.bars master-frame slice is GONE — the handler
        # now drives update(ticker,bar) and the strategy reads the per-ticker
        # completed-bar COUNT via self.bar_count(ticker). This count increments once
        # per consumed bar (REAL bars only — a gap bar is skipped, P5-D10c), so it
        # is byte-identical to the old len(self.bars) against the wide max_window:
        # the fire/exit ticks (count == fire_on_bar / exit_on_bar) are UNCHANGED.
        count = self.bar_count(ticker)
        if count == self.fire_on_bar:
            return self.buy(ticker)
        if count == self.exit_on_bar:
            return self.sell(ticker)
        return None

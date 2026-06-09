"""Canary scenario spec + VERIFY hand-derivation (Phase 4, D-12/D-13).

This is the ONE contrived, hand-verifiable E2E canary (D-12): a deterministic
single MARKET buy → one known round-trip trade through the REAL
``CsvPriceStore`` → feed → signal → order → fill path on a tiny hand-written
``bars.csv``. It dogfoods the Plan 02 ``run_scenario`` harness and is the literal
copy-template for Phase 6-9 scenario authors.

The module docstring below IS the VERIFY hand-derivation note (D-13, mirrors
``tests/golden/REFREEZE-*.md``): it states the contrived bars, which bar fires the
BUY/SELL, the next-bar-open fill prices, the ``FractionOfCash(0.95)`` sizing math,
and the resulting single expected trade + final equity — WHY each frozen number is
what it is. A human verifies this derivation matches ``golden/`` BEFORE the freeze
is locked (E2E-04): a regression-lock proves stability, not correctness.

================================ VERIFY ================================

Contrived bars (``bars.csv`` — daily, tz-aware Open time, all prices round):

    bar  date         open   high   low    close
    0    2020-01-01   100    105    99     104
    1    2020-01-02   110    115    109    114
    2    2020-01-03   120    125    119    124
    3    2020-01-04   130    135    129    134
    4    2020-01-05   140    145    139    144
    5    2020-01-06   150    155    149    154

Engine knobs: starting_cash = 10_000, timeframe = 1d, exchange = None (zero-fee /
no-slippage simulated-exchange defaults — Open Q1 ExchangeConfig threading is
Phase 7), strategy = ``SingleMarketBuy(fire_on_bar=2, exit_on_bar=4)``.

Bar-count firing (the handler pushes the completed-bar window each tick; with
``max_window = 100 >> 6`` bars, ``len(bars)`` == count of completed bars ≤ asof,
and at base timeframe a bar stamped B is completed at its own tick):

    tick bar0 (01-01): len(bars) = 1 → no signal
    tick bar1 (01-02): len(bars) = 2 → BUY  (fire_on_bar == 2)
    tick bar2 (01-03): len(bars) = 3 → no signal
    tick bar3 (01-04): len(bars) = 4 → SELL (exit_on_bar == 4, full exit)
    tick bar4 (01-05): len(bars) = 5 → no signal
    tick bar5 (01-06): len(bars) = 6 → no signal

Entry (the BUY decided on bar1 / 01-02):
  * Sizing uses the DECISION-bar close (bar1 close = 114) and full available cash
    (10_000, no prior position): the resolver computes
        qty = (0.95 * 10_000) / 114 = 9_500 / 114 = 83.3333… (250/3)  units.
  * The MARKET order fills at the NEXT bar's open (next-bar-open convention) =
    bar2 open = 120, stamped entry_date 2020-01-03.
  * total_bought = qty * fill = (250/3) * 120 = 10_000.00  (full cash deployed).

Exit (the SELL decided on bar3 / 01-04, ``exit_fraction`` defaults to 1 → full):
  * The MARKET exit fills at the NEXT bar's open = bar4 open = 140, stamped
    exit_date 2020-01-05; it sells the entire 250/3 units.
  * total_sold = (250/3) * 140 = 11_666.666…  → avg_sold = 140.

Resulting SINGLE round-trip trade (fees 0, slippage 0):
  * side = LONG, pair = BTCUSD
  * entry_date = 2020-01-03, avg_bought = 120
  * exit_date  = 2020-01-05, avg_sold  = 140
  * net_quantity = 0 (fully closed)
  * realised_pnl = total_sold - total_bought = 11_666.666… - 10_000 = 1_666.666…
                 = (140 - 120) * 250/3.

Final portfolio (single trade, no open position at run end):
  * final_cash = 10_000 + 1_666.666… = 11_666.666…
  * final_equity = final_cash (no open positions) = 11_666.666…
  * trade_count = 1, total_realised_pnl = 1_666.666…

The metrics block (sharpe/sortino/cagr/max_drawdown/profit_factor/win_rate) is
machine-computed by the shared ``itrader.reporting.metrics`` on this single-trade
equity curve; profit_factor is +inf-guarded and win_rate = 1.0 (the one trade
won). Those derived ratios are frozen as-written; the LOAD-BEARING hand-checked
facts are the fill prices, the quantity, and the realised PnL above.

============================== END VERIFY =============================
"""

import pathlib
from dataclasses import dataclass
from typing import Any

from tests.e2e.strategies.single_market_buy import SingleMarketBuy

HERE = pathlib.Path(__file__).resolve().parent


@dataclass(frozen=True)
class PortfolioSpec:
    """Minimal portfolio spec the harness reads (``user_id`` / ``name`` / ``cash``).

    The harness consumes these three attributes via ``add_portfolio`` (Plan 02
    ``_build_and_run``). A real ``PortfolioConfig`` is the Phase 7+ richer form;
    the canary needs only the wiring trio (D-03 — reuse the real shape, no
    parallel sizing/fee schema here).
    """

    user_id: int
    name: str
    cash: int


@dataclass(frozen=True)
class ScenarioSpec:
    """The per-leaf scenario contract the Plan 02 ``run_scenario`` harness reads.

    Field names match EXACTLY what the harness consumes: ``start``, ``end``,
    ``timeframe``, ``data`` (ticker → CSV path), ``strategies``, ``portfolios``
    (each with ``user_id`` / ``name`` / ``cash``), ``exchange`` (None = zero-fee /
    no-slippage defaults, Open Q1 deferred to Phase 7), ``ticker``,
    ``starting_cash``.
    """

    start: str
    end: str
    timeframe: str
    ticker: str
    starting_cash: int
    data: dict[str, Any]
    strategies: list[Any]
    portfolios: list[PortfolioSpec]
    exchange: Any = None


_TICKER = "BTCUSD"
_TIMEFRAME = "1d"
_CASH = 10_000

# The harness imports this module-level SCENARIO (Plan 02 ``_load_spec``).
SCENARIO = ScenarioSpec(
    start="2020-01-01",
    end="2020-01-06",
    timeframe=_TIMEFRAME,
    ticker=_TICKER,
    starting_cash=_CASH,
    data={_TICKER: HERE / "bars.csv"},
    strategies=[SingleMarketBuy(_TIMEFRAME, [_TICKER], fire_on_bar=2, exit_on_bar=4)],
    portfolios=[PortfolioSpec(user_id=1, name="canary_pf", cash=_CASH)],
    exchange=None,
)

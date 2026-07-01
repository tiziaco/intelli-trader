"""COST-01: percent-fee canary — scenario spec + VERIFY hand-derivation.

The foundational COST-01 canary (Plan 07-01). It proves THREE Plan-1 seams wire
end-to-end on ONE leaf: (a) the always-on ``commission`` golden column sourced from
the real ``Position.commission`` (D-07/D-08), (b) the D-14 exchange-config seam
actually applying a configured fee model to the run (``spec.exchange`` is a non-None
``ExchangeConfig`` here, unlike every Phase 6 leaf), and (c) the percent fee model
itself (``PercentFeeModel.calculate_fee = abs(qty*price) * rate``).

A single MARKET BUY -> MARKET SELL round-trip on contrived BTCUSD bars with a 1%
percent fee. Round prices make the per-cent fee math cleanly hand-derivable; the
frozen ``commission`` column carries the NON-ZERO total fee and ``summary.json``
``final_cash`` is derivable to the cent.

================================ VERIFY ================================

HAND-VERIFIED & LOCKED (D-07/D-09a): the frozen ``golden/trades.csv`` +
``golden/summary.json`` MATCH the derivation below. Re-freeze ONLY via ``--freeze``
after re-verifying this derivation.

Contrived bars (``bars.csv`` — daily, tz-aware Open time, all prices round):

    bar  date         open   high   low    close
    0    2020-01-01   100    105    99     100
    1    2020-01-02   100    105    99     100
    2    2020-01-03   100    155    99     150
    3    2020-01-04   180    205    175    200
    4    2020-01-05   200    210    199    205
    5    2020-01-06   205    210    204    208

Engine knobs: starting_cash = 10_000, timeframe = 1d, sizing = FractionOfCash(0.95)
(the default), strategy = ``ScriptedEmitter`` with a DATE-keyed script (D-04):
a MARKET BUY on the 2020-01-02 decision bar and a MARKET SELL on the 2020-01-04
decision bar. ``exchange`` = an ``ExchangeConfig`` with a PERCENT fee model at
``fee_rate = Decimal("0.01")`` (1%) and NO slippage (model_type=NONE) — the D-14
seam re-inits the fee model from this config so the percent fee actually applies.

Sizing (FractionOfCash(0.95), priced off the BUY DECISION-bar close = bar1 close
= 100, full available cash, no prior position):
    qty = (0.95 * 10_000) / 100 = 9_500 / 100 = 95 units (round).

Lifecycle (decision bar -> fill bar; the next-bar-open rule):

    decision bar1 (2020-01-02): script hits BUY -> MARKET parent rests.
    bar2 (2020-01-03): the MARKET parent fills at bar2 OPEN = 100, stamped
        2020-01-03. Position opens LONG 95 @ 100.
    decision bar3 (2020-01-04): script hits SELL -> MARKET exit parent rests
        (position is open, so this is a flatten).
    bar4 (2020-01-05): the MARKET exit fills at bar4 OPEN = 200, stamped
        2020-01-05. Position closes.
    bar5 (2020-01-06): trailing bar — nothing rests, nothing fills.

Percent fee (PercentFeeModel: fee = abs(qty * price) * rate, rate = 0.01):
  * BUY leg : notional = 95 * 100 = 9_500.00 -> buy_commission  = 9_500  * 0.01 = 95.00
  * SELL leg: notional = 95 * 200 = 19_000.00 -> sell_commission = 19_000 * 0.01 = 190.00
  * total commission = buy_commission + sell_commission = 95.00 + 190.00 = 285.00
    (this is the NON-ZERO value frozen in the ``commission`` column).

Entry (BUY parent, filled bar2 @100):
  * total_bought = 95 * 100 = 9_500.00; avg_bought = 100.
Exit (MARKET SELL, filled bar4 @200):
  * total_sold = 95 * 200 = 19_000.00; avg_sold = 200.

Resulting SINGLE round-trip trade:
  * side = LONG, pair = BTCUSD
  * entry_date = 2020-01-03, avg_bought = 100
  * exit_date  = 2020-01-05, avg_sold  = 200
  * net_quantity = 0 (fully closed)
  * realised_pnl (Position.realised_pnl, LONG):
        (avg_sold - avg_bought) * sell_qty
        - (sell_qty / buy_qty) * buy_commission
        - sell_commission
      = (200 - 100) * 95 - (95/95) * 95 - 190
      = 9_500 - 95 - 190 = 9_215.00
  * commission = 285.00 (NON-ZERO — the COST-01 assertion).

Final cash (ledger): start - buy_notional - buy_commission + sell_notional
                      - sell_commission
    = 10_000 - 9_500 - 95 + 19_000 - 190 = 19_215.00
    cross-check: starting_cash + realised_pnl = 10_000 + 9_215 = 19_215.00. OK.

Slippage columns (slippage model = NONE, so fill = open; slippage = fill price
- the STORE bar immediately before the fill bar — attach_slippage indexes the
store close series, NOT the run/decision grid):
  * slippage_entry = bar2 open (100) - bar1 close (100) = 0.0
  * slippage_exit  = bar4 open (200) - bar3 close (200) = 0.0

Final portfolio: final_cash = final_equity = 19_215.00, trade_count = 1.

============================== END VERIFY =============================
"""

import pathlib
from decimal import Decimal

from itrader.config.exchange import (
    ExchangeConfig,
    FeeModelConfig,
    FeeModelType,
    SlippageModelConfig,
    SlippageModelType,
)
from tests.e2e.scenario_spec import PortfolioSpec, ScenarioSpec
from tests.e2e.strategies.scripted_emitter import ScriptedEmitter

HERE = pathlib.Path(__file__).resolve().parent

_TICKER = "BTCUSD"  # Pitfall 1: any other ticker silently REFUSES every order.
_TIMEFRAME = "1d"
_CASH = 10_000

# Date-keyed script (D-04): a MARKET BUY decided 2020-01-02 (fills bar2 @100) and a
# MARKET SELL decided 2020-01-04 (fills bar4 @200) — a clean round-trip.
_SCRIPT = {
    "2020-01-02": {"side": "BUY"},
    "2020-01-04": {"side": "SELL"},
}

# D-14: a PERCENT fee model at 1% (Decimal string-path, Pitfall 6) with NO slippage.
# The conftest seam re-inits simulated.fee_model from this config so the fee applies.
_EXCHANGE = ExchangeConfig(
    exchange_name="cost01_pf",
    fee_model=FeeModelConfig(model_type=FeeModelType.PERCENT, fee_rate=Decimal("0.01")),
    slippage_model=SlippageModelConfig(model_type=SlippageModelType.NONE),
)

# The harness imports this module-level SCENARIO (conftest ``_load_spec``).
SCENARIO = ScenarioSpec(
    start="2020-01-01",
    end="2020-01-06",
    timeframe=_TIMEFRAME,
    ticker=_TICKER,
    starting_cash=_CASH,
    data={_TICKER: HERE / "bars.csv"},
    strategies=[ScriptedEmitter(_TIMEFRAME, [_TICKER], script=_SCRIPT)],
    portfolios=[PortfolioSpec(name="cost01_pf", cash=_CASH)],
    exchange=_EXCHANGE,  # D-14: the percent fee model is applied to the run.
)

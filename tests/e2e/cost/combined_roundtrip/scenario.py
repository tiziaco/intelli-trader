"""COST-06: combined fee + slippage round-trip, cash to the cent — scenario + VERIFY.

A single MARKET BUY -> MARKET SELL round-trip with BOTH a PERCENT fee model (1%)
AND a deterministic FIXED slippage model (2%, ``random_variation=False`` — Pitfall
1). The full Decimal cash flow (FillEvent -> Transaction -> Position -> cash)
reconciles EXACTLY: the frozen ``commission`` column + ``summary.json`` ``final_cash``
satisfy ``final_cash = starting_cash + realised_pnl`` (and the ledger identity
``final_cash = starting - buy_notional - buy_comm + sell_notional - sell_comm``),
to the cent (D-07 / COST-06).

IMPORTANT engine truth (simulated.py:196-213): the fee model is called with the
BASE fill price (``price = to_money(fill_price)`` — the bar open) BEFORE the slipped
``executed_price = price * slippage_factor`` is computed. So the percent fee is
charged on the BASE (un-slipped) notional, while the POSITION settles at the slipped
``executed_price``. The two costs do NOT compound (fee is NOT levied on the slipped
notional) — they are independent deductions from the same round-trip.

Pure-fill (D-09): golden = ``trades.csv`` + ``summary.json``.

================================ VERIFY ================================

HAND-VERIFIED & LOCKED (COST-06 / D-09a): the frozen ``golden/trades.csv`` +
``golden/summary.json`` MATCH the derivation below. Re-freeze ONLY via ``--freeze``
after re-verifying this derivation.

Contrived bars (``bars.csv`` — daily, tz-aware Open time, all prices round):

    bar  date         open   high   low    close
    0    2020-01-01   100    105    99     100
    1    2020-01-02   100    105    99     100     BUY decision (close 100)
    2    2020-01-03   100    155    99     150     entry FILL bar (MARKET @ open 100)
    3    2020-01-04   200    205    199    200     SELL decision (close 200)
    4    2020-01-05   200    210    199    205     exit FILL bar (MARKET @ open 200)
    5    2020-01-06   205    210    204    208     trailing

Engine knobs: starting_cash = 10_000, timeframe = 1d, sizing = FractionOfCash(0.95),
strategy = ``ScriptedEmitter`` (default MARKET) with a DATE-keyed script (D-04): a
MARKET BUY on 2020-01-02, a full MARKET SELL on 2020-01-04. ``exchange`` carries a
PERCENT fee model (fee_rate=1%) AND a FIXED slippage model (slippage_pct=2%,
random_variation=False).

Sizing (decision-bar close bar1 = 100, full cash 10_000):
    qty = (0.95 * 10_000) / 100 = 9_500 / 100 = 95 units (round).

Slippage (FIXED, random_variation=False, slippage_pct=2): BUY factor 1.02, SELL 0.98.
  Entry: MARKET BUY fills bar2 @ base open 100 -> executed 100 * 1.02 = 102.00
  Exit : MARKET SELL fills bar4 @ base open 200 -> executed 200 * 0.98 = 196.00

Position notionals (settle at the EXECUTED/slipped price):
  total_bought = 95 * 102 = 9_690.00; avg_bought = 102.
  total_sold   = 95 * 196 = 18_620.00; avg_sold   = 196.

Percent fee (1% on the BASE/un-slipped notional — see engine truth above):
  buy_commission  = 95 * 100 * 0.01 = 9_500  * 0.01 = 95.00
  sell_commission = 95 * 200 * 0.01 = 19_000 * 0.01 = 190.00
  total commission = 95.00 + 190.00 = 285.00  (the frozen ``commission`` value)

realised_pnl (Position.realised_pnl, LONG):
    (avg_sold - avg_bought) * sell_qty - (sell_qty/buy_qty) * buy_commission - sell_commission
    = (196 - 102) * 95 - 1 * 95.00 - 190.00
    = 8_930.00 - 285.00 = 8_645.00

Cash-to-the-cent reconciliation (COST-06):
  ledger : final_cash = starting - buy_notional - buy_comm + sell_notional - sell_comm
                      = 10_000 - 9_690.00 - 95.00 + 18_620.00 - 190.00 = 18_645.00
  identity: final_cash = starting_cash + realised_pnl = 10_000 + 8_645.00 = 18_645.00
  Both agree -> the frozen ``summary.json final_cash`` (18_645.00) and the frozen
  ``commission`` (285.00) reconcile exactly.

Slippage columns (attach_slippage indexes the STORE close series — fill price minus
the store bar immediately before the fill bar, D-17):
  * slippage_entry = bar2 fill (102) - bar1 close (100) = 2.0
  * slippage_exit  = bar4 fill (196) - bar3 close (200) = -4.0

Final portfolio: final_cash = final_equity = 18_645.00, trade_count = 1.

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

# Date-keyed script (D-04): MARKET BUY decided 2020-01-02 (fills bar2 @100), full
# MARKET SELL decided 2020-01-04 (fills bar4 @200) — MARKET so slippage applies.
_SCRIPT = {
    "2020-01-02": {"side": "BUY"},
    "2020-01-04": {"side": "SELL"},
}

# COST-06: BOTH a PERCENT fee (1%) AND a deterministic FIXED slippage (2%,
# random_variation=False — Pitfall 1). Decimal string-path (Pitfall 6). The fee is
# charged on the BASE (un-slipped) notional (simulated.py:196-205 computes commission
# before executed_price = price * factor), while the position settles at the slipped
# price — the two costs do NOT compound. The cash math is verified to the cent.
_EXCHANGE = ExchangeConfig(
    exchange_name="cost06_cr",
    fee_model=FeeModelConfig(model_type=FeeModelType.PERCENT, fee_rate=Decimal("0.01")),
    slippage_model=SlippageModelConfig(
        model_type=SlippageModelType.FIXED,
        slippage_pct=Decimal("2"),
        random_variation=False,
    ),
)

SCENARIO = ScenarioSpec(
    start="2020-01-01",
    end="2020-01-06",
    timeframe=_TIMEFRAME,
    ticker=_TICKER,
    starting_cash=_CASH,
    data={_TICKER: HERE / "bars.csv"},
    strategies=[ScriptedEmitter(_TIMEFRAME, [_TICKER], script=_SCRIPT)],
    portfolios=[PortfolioSpec(name="cost06_pf", cash=_CASH)],
    exchange=_EXCHANGE,  # D-14: percent fee + fixed slippage both applied.
)

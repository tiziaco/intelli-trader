"""COST-05: limit-no-slip proof — scenario spec + VERIFY hand-derivation.

A standalone limit-no-slip leaf (D-10). A FIXED slippage model is CONFIGURED on
the exchange (``slippage_pct = Decimal("2")`` = 2%, ``random_variation=False`` so
the rate is deterministic) AND every entry/exit is a LIMIT order
(``ScriptedEmitter(order_type=OrderType.LIMIT)``). The execution layer forces
``slippage_factor = Decimal("1")`` for any LIMIT fill (simulated.py:206-208, D-03
"limit-or-better"), so the configured 2% slippage has ZERO price impact on these
fills: the fill price equals the limit/trigger price EXACTLY.

The contrast (proving the model is live, not silently off): the SAME 2% buy-side
fixed-slippage rate WOULD push a MARKET BUY fill to ``open * 1.02`` (e.g. an entry
at open 124 -> 126.48). Because the entry is a LIMIT it instead fills AT the trigger
120 with no impact. Pure-fill (D-09): the assertion is the closed round-trip, so the
golden set is ``trades.csv`` + ``summary.json`` only — NO ``orders.csv``.

================================ VERIFY ================================

HAND-VERIFIED & LOCKED (COST-05 / D-03/D-09a): the frozen ``golden/trades.csv`` +
``golden/summary.json`` MATCH the derivation below. Re-freeze ONLY via ``--freeze``
after re-verifying this derivation.

Contrived bars (``bars.csv`` — daily, tz-aware Open time, all prices round) — the
limit_touch geometry (in-bar TOUCH entry, gap-through exit):

    bar  date         open   high   low    close   role
    0    2020-01-01   100    105    99     104     warmup
    1    2020-01-02   118    122    116    120     BUY decision  (close 120 = entry trigger T)
    2    2020-01-03   124    128    118    126     entry FILL bar (open 124 > T, low 118 <= T)
    3    2020-01-04   135    142    134    140     SELL decision (close 140 = exit trigger Te)
    4    2020-01-05   150    155    149    154     exit FILL bar  (open 150 >= Te)
    5    2020-01-06   158    162    157    160     trailing

Engine knobs: starting_cash = 10_000, timeframe = 1d, sizing = FractionOfCash(0.95),
strategy = ``ScriptedEmitter(order_type=OrderType.LIMIT)`` with a DATE-keyed script
(D-04): a BUY on 2020-01-02, a full SELL on 2020-01-04. ``exchange`` carries a FIXED
slippage model (slippage_pct=2%, random_variation=False) and NO fee model (ZERO), so
commission stays 0.00 and the ONLY thing under test is the limit-no-slip guarantee.

Decision bar -> fill bar (LIMIT rests at the DECISION-bar close, D-02):

    decision bar1 (2020-01-02, close 120 = T): BUY LIMIT rests at T=120.
        bar2 (2020-01-03): open 124 > 120 AND low 118 <= 120 -> in-bar TOUCH arm:
        a MARKET buy would slip to 124 * 1.02 = 126.48, but this is a LIMIT, so
        slippage_factor=1 -> fill AT trigger 120 exactly, stamped 2020-01-03.
    decision bar3 (2020-01-04, close 140 = Te): SELL LIMIT (long TP) rests at Te=140.
        bar4 (2020-01-05): open 150 >= 140 -> gap-through arm: a MARKET sell would
        slip to 150 * (1 - 0.02) = 147.0, but this is a LIMIT, so slippage_factor=1
        -> fill at the OPEN 150 exactly, stamped 2020-01-05.

Sizing (FractionOfCash(0.95), priced off the BUY DECISION-bar close = bar1 close
= 120, full available cash, no prior position):
    qty = (0.95 * 10_000) / 120 = 9_500 / 120 = 475/6 = 79.1666... units.

Entry (BUY LIMIT, filled bar2 @120 — NO slippage):
  * total_bought = (475/6) * 120 = 9_500.00; avg_bought = 120.
Exit (SELL LIMIT, filled bar4 @150 — NO slippage):
  * total_sold = (475/6) * 150 = 11_875.00; avg_sold = 150.

Resulting SINGLE round-trip trade (fees 0; slippage NOT applied — both legs LIMIT):
  * side = LONG, pair = BTCUSD
  * entry_date = 2020-01-03, avg_bought = 120 (== trigger, no impact)
  * exit_date  = 2020-01-05, avg_sold  = 150 (== gap-through open, no impact)
  * net_quantity = 0 (fully closed)
  * realised_pnl = total_sold - total_bought = 11_875 - 9_500 = 2_375.00
  * commission = 0.00 (ZERO fee model).

Final cash (ledger): 10_000 + 11_875 - 9_500 = 12_375.00
    cross-check: starting_cash + realised_pnl = 10_000 + 2_375 = 12_375.00. OK.

Slippage columns (attach_slippage indexes the STORE close series — fill price minus
the store bar immediately before the fill bar; INDEPENDENT of the execution-layer
slippage model, D-17):
  * slippage_entry = bar2 fill (120) - bar1 close (120) = 0.0
  * slippage_exit  = bar4 fill (150) - bar3 close (140) = 10.0

Final portfolio: final_cash = final_equity = 12_375.00, trade_count = 1.

============================== END VERIFY =============================
"""

import pathlib
from decimal import Decimal

from itrader.core.enums.order import OrderType
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

# Date-keyed script (D-04): BUY decided 2020-01-02, full SELL decided 2020-01-04.
_SCRIPT = {
    "2020-01-02": {"side": "BUY", "sl": None, "tp": None},
    "2020-01-04": {"side": "SELL", "sl": None, "tp": None,
                   "exit_fraction": Decimal("1")},
}

# COST-05: a live FIXED slippage model (2%, deterministic) + NO fee. The LIMIT
# entry/exit force slippage_factor=1 (simulated.py:206-208), so the 2% has zero
# impact — the fills land AT the limit/trigger price. random_variation=False keeps
# the (unused-here) rate deterministic and is the Pitfall-1 guard if a future edit
# made a leg MARKET.
_EXCHANGE = ExchangeConfig(
    exchange_name="cost05_lns",
    fee_model=FeeModelConfig(model_type=FeeModelType.ZERO),
    slippage_model=SlippageModelConfig(
        model_type=SlippageModelType.FIXED,
        slippage_pct=Decimal("2"),
        random_variation=False,
    ),
)

# Pitfall 3: order_type=LIMIT is the per-INSTANCE config field selecting a LIMIT
# entry AND a LIMIT exit — this is HOW the limit-no-slip guarantee is exercised.
SCENARIO = ScenarioSpec(
    start="2020-01-01",
    end="2020-01-06",
    timeframe=_TIMEFRAME,
    ticker=_TICKER,
    starting_cash=_CASH,
    data={_TICKER: HERE / "bars.csv"},
    strategies=[ScriptedEmitter(_TIMEFRAME, [_TICKER], script=_SCRIPT,
                                order_type=OrderType.LIMIT)],
    portfolios=[PortfolioSpec(user_id=1, name="cost05_pf", cash=_CASH)],
    exchange=_EXCHANGE,  # D-14: FIXED slippage configured but forced to 1 for LIMIT.
)

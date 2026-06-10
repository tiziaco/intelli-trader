"""COST-04: linear slippage (size-impact only) on a MARKET fill — scenario + VERIFY.

A single MARKET BUY -> MARKET SELL round-trip with a LINEAR slippage model whose
RNG base-noise is ZEROED via ``base_slippage_pct = Decimal("0")`` (MANDATORY,
Pitfall 1), leaving ONLY the deterministic, size-proportional term:

    size_impact = min(max_slippage, order_value * size_impact_factor / 100)
    BUY  factor = 1 + size_impact   (worse for buys)
    SELL factor = 1 - size_impact   (worse for sells)

(LinearSlippageModel L85-107.) With ``base_slippage_pct=0`` the noise term is
``uniform(-0, 0) = 0`` (NO RNG draw influences the result), so the fill is
hand-derivable to the cent. Were ``base_slippage_pct`` non-zero the model would draw
seed-dependent noise and the fill would not be hand-derivable (T-07-06).

NOTE (07-02 engine fix): ``_init_slippage_model`` formerly read
``config.base_slippage_pct or 0.01``, which silently overrode a legitimate
``Decimal("0")`` (falsy) with the 0.01 default — making this leaf non-derivable. The
fix (``is not None`` instead of ``or``) lets the configured 0 stand. NO fee (ZERO).

Pure-fill (D-09): golden = ``trades.csv`` + ``summary.json``.

================================ VERIFY ================================

HAND-VERIFIED & LOCKED (COST-04 / D-09a): the frozen ``golden/trades.csv`` +
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
LINEAR slippage model (base_slippage_pct=0, size_impact_factor=0.0001,
max_slippage_pct=50) and NO fee (ZERO).

Sizing (decision-bar close bar1 = 100, full cash 10_000):
    qty = (0.95 * 10_000) / 100 = 9_500 / 100 = 95 units (round).

Linear slippage (base noise = 0; size term only; the model receives the BASE fill
price (the bar OPEN) and the FULL order quantity — simulated.py:210-212):

  Entry (MARKET BUY, fills bar2 @ base open 100):
    order_value = 95 * 100 = 9_500
    size_impact = 9_500 * 0.0001 / 100 = 0.0095   (< max 0.50, no cap)
    BUY factor  = 1 + 0.0095 = 1.0095
    fill price  = 100 * 1.0095 = 100.95
    total_bought = 95 * 100.95 = 9_590.25; avg_bought = 100.95.

  Exit (MARKET SELL, fills bar4 @ base open 200):
    order_value = 95 * 200 = 19_000
    size_impact = 19_000 * 0.0001 / 100 = 0.0190   (< max 0.50, no cap)
    SELL factor = 1 - 0.0190 = 0.9810
    fill price  = 200 * 0.9810 = 196.20
    total_sold = 95 * 196.20 = 18_639.00; avg_sold = 196.20.

Resulting SINGLE round-trip trade (fees 0; size-impact slippage on BOTH MARKET legs):
  * side = LONG, pair = BTCUSD
  * entry_date = 2020-01-03, avg_bought = 100.95
  * exit_date  = 2020-01-05, avg_sold  = 196.20
  * net_quantity = 0 (fully closed)
  * realised_pnl = total_sold - total_bought = 18_639.00 - 9_590.25 = 9_048.75
  * commission = 0.00 (ZERO fee model).

Final cash (ledger): 10_000 + 18_639.00 - 9_590.25 = 19_048.75
    cross-check: starting_cash + realised_pnl = 10_000 + 9_048.75 = 19_048.75. OK.

Slippage columns (attach_slippage indexes the STORE close series — fill price minus
the store bar immediately before the fill bar, INDEPENDENT of the execution-layer
slippage model, D-17):
  * slippage_entry = bar2 fill (100.95) - bar1 close (100) = 0.95
  * slippage_exit  = bar4 fill (196.20) - bar3 close (200) = -3.80

Final portfolio: final_cash = final_equity = 19_048.75, trade_count = 1.

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
# MARKET SELL decided 2020-01-04 (fills bar4 @200) — order_type defaults to MARKET so
# slippage applies (slippage only applies to non-LIMIT fills, simulated.py:206-212).
_SCRIPT = {
    "2020-01-02": {"side": "BUY"},
    "2020-01-04": {"side": "SELL"},
}

# COST-04: a LINEAR slippage model. base_slippage_pct=Decimal("0") is MANDATORY
# (Pitfall 1) — it zeros the RNG base-noise (uniform(-0,0)=0), leaving ONLY the
# deterministic size-impact term. size_impact_factor / max_slippage_pct are
# Decimal string-path (Pitfall 6). max_slippage_pct=50 is far above the actual
# impacts (0.0095 / 0.0190) so neither leg is capped. NO fee (ZERO).
_EXCHANGE = ExchangeConfig(
    exchange_name="cost04_ls",
    fee_model=FeeModelConfig(model_type=FeeModelType.ZERO),
    slippage_model=SlippageModelConfig(
        model_type=SlippageModelType.LINEAR,
        base_slippage_pct=Decimal("0"),
        size_impact_factor=Decimal("0.0001"),
        max_slippage_pct=Decimal("50"),
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
    portfolios=[PortfolioSpec(user_id=1, name="cost04_pf", cash=_CASH)],
    exchange=_EXCHANGE,  # D-14: LINEAR slippage (size-impact only) applied to the run.
)

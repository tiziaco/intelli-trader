"""COST-03: fixed slippage on a MARKET fill — scenario spec + VERIFY note.

A single MARKET BUY -> MARKET SELL round-trip with a FIXED slippage model at
``slippage_pct = Decimal("2")`` (2%) and ``random_variation=False`` (MANDATORY,
Pitfall 1). With ``random_variation=False`` the model applies a DETERMINISTIC,
DIRECTIONAL rate (FixedSlippageModel L84-88): a BUY fills WORSE (price * (1 + 2%)),
a SELL fills WORSE (price * (1 - 2%)). No RNG is drawn, so the fill is
hand-derivable to the cent. Were ``random_variation=True`` the model would draw
``self._rng.uniform(-2, 2)`` (L81) and the fill would be seed-dependent, not
hand-derivable (T-07-06). NO fee model (ZERO) — the only cost under test is the
fixed slippage on the MARKET fills.

Pure-fill (D-09): golden = ``trades.csv`` + ``summary.json``.

================================ VERIFY ================================

HAND-VERIFIED & LOCKED (COST-03 / D-09a): the frozen ``golden/trades.csv`` +
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
FIXED slippage model (slippage_pct=2%, random_variation=False) and NO fee (ZERO).

Sizing (decision-bar close bar1 = 100, full cash 10_000):
    qty = (0.95 * 10_000) / 100 = 9_500 / 100 = 95 units (round).

Fixed slippage factor (FixedSlippageModel, random_variation=False, slippage_pct=2):
    slippage = to_money(2) / 100 = 0.02
    BUY  factor = 1 + 0.02 = 1.02 (worse for buys)
    SELL factor = 1 - 0.02 = 0.98 (worse for sells)

Entry (MARKET BUY decided bar1, fills bar2 @ base open 100):
    fill price = 100 * 1.02 = 102.00 (deterministic, no RNG).
    total_bought = 95 * 102 = 9_690.00; avg_bought = 102.
Exit (MARKET SELL decided bar3, fills bar4 @ base open 200):
    fill price = 200 * 0.98 = 196.00 (deterministic, no RNG).
    total_sold = 95 * 196 = 18_620.00; avg_sold = 196.

Resulting SINGLE round-trip trade (fees 0; slippage applied to BOTH MARKET legs):
  * side = LONG, pair = BTCUSD
  * entry_date = 2020-01-03, avg_bought = 102 (base 100 slipped +2%)
  * exit_date  = 2020-01-05, avg_sold  = 196 (base 200 slipped -2%)
  * net_quantity = 0 (fully closed)
  * realised_pnl = total_sold - total_bought = 18_620 - 9_690 = 8_930.00
  * commission = 0.00 (ZERO fee model).

Final cash (ledger): 10_000 + 18_620 - 9_690 = 18_930.00
    cross-check: starting_cash + realised_pnl = 10_000 + 8_930 = 18_930.00. OK.

Slippage columns (attach_slippage indexes the STORE close series — fill price minus
the store bar immediately before the fill bar, INDEPENDENT of the execution-layer
slippage model, D-17):
  * slippage_entry = bar2 fill (102) - bar1 close (100) = 2.0
  * slippage_exit  = bar4 fill (196) - bar3 close (200) = -4.0

Final portfolio: final_cash = final_equity = 18_930.00, trade_count = 1.

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
# the slippage applies (slippage only applies to non-LIMIT fills, simulated.py:206-212).
_SCRIPT = {
    "2020-01-02": {"side": "BUY"},
    "2020-01-04": {"side": "SELL"},
}

# COST-03: a FIXED slippage model at 2% with random_variation=False (MANDATORY,
# Pitfall 1 — without it the model draws RNG jitter and the fill is non-derivable).
# Decimal string-path (Pitfall 6). NO fee (ZERO) so slippage is the only cost.
_EXCHANGE = ExchangeConfig(
    exchange_name="cost03_fs",
    fee_model=FeeModelConfig(model_type=FeeModelType.ZERO),
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
    portfolios=[PortfolioSpec(name="cost03_pf", cash=_CASH)],
    exchange=_EXCHANGE,  # D-14: FIXED slippage (deterministic) applied to the run.
)

"""MULTI-02: TWO strategies on ONE portfolio -> BOTH fill (no cap, no contention).

The multi-strategy breadth proof and the clean CONTRAST to MULTI-04. Two SEPARATE
``ScriptedEmitter`` instances — one trading BTCUSD, one trading ETHUSDT — are both
subscribed to the SAME portfolio (the harness subscribes EVERY ``spec.strategies``
to EVERY ``spec.portfolios``, conftest.py:316-317, so no wiring change). With AMPLE
cash and DIFFERENT tickers there is NO position cap and NO cash contention: BOTH
strategies open and close their own round-trip, and the combined ``trades.csv``
carries both (one BTCUSD ``pair`` row, one ETHUSDT ``pair`` row).

Where MULTI-01 proves ONE strategy can span two tickers, MULTI-02 proves TWO
strategies can coexist on one portfolio. MULTI-04 is the adversarial version of this
shape (insufficient cash -> the second loses); here cash is ample so both win.

This leaf rides the DEFAULT ``trades.csv`` + ``summary.json`` only — NO opt-in
(both fill cleanly, no state-edge to assert). ``spec.ticker = "BTCUSD"`` is only the
summary label / orders-snapshot query key; the ``trades.csv`` is portfolio-wide.

================================ VERIFY ================================

HAND-VERIFIED & LOCKED (E2E-04 / D-13): a human confirmed the frozen
``golden/trades.csv`` (one BTCUSD row + one ETHUSDT row) + ``golden/summary.json``
MATCH the hand-derivation below. Re-freeze ONLY via ``--freeze`` after re-verifying.

Contrived bars — daily, tz-aware Open time. Two CSVs, SAME dates, DISTINCT price
levels per ticker:

    BTCUSD (``bars.csv``)               ETHUSDT (``bars_eth.csv``)
    bar date         open  close        open  close   event
    0   2020-01-01   100   100          200   200     warmup
    1   2020-01-02   100   100          200   200     each strategy's BUY decided
    2   2020-01-03   120   120          210   210     BUY fills @ open (120 / 210)
    3   2020-01-04   120   120          210   210     each strategy's SELL decided
    4   2020-01-05   140   140          230   230     SELL fills @ open (140 / 230)
    5   2020-01-06   140   140          230   230     (no signal)

Engine knobs: starting_cash = 10_000, timeframe = 1d, exchange = None (zero-fee /
zero-slippage). TWO ``ScriptedEmitter`` instances on the ONE portfolio:
  * BTC strategy: ``ScriptedEmitter("1d", ["BTCUSD"], script=_BTC_SCRIPT, ...)``.
  * ETH strategy: ``ScriptedEmitter("1d", ["ETHUSDT"], script=_ETH_SCRIPT, ...)``.
``sizing_policy = FixedQuantity(qty=Decimal("10"))`` on EACH so each buys 10 units
and the cash math is exact.

Date-keyed scripts (each strategy fires only on its own ticker):
  * 2020-01-02: BUY  -> fills at the next-bar open (BTC 120 / ETH 210).
  * 2020-01-04: SELL -> fills at the next-bar open (2020-01-05: BTC 140 / ETH 230),
    full exit (exit_fraction default 1).

Admission cash trail (reserve at the DECISION-bar close, bar1: BTC 100 / ETH 200):
  * BTC BUY decided 01-02: reserve 10 * 100 = 1_000.
  * ETH BUY decided 01-02: reserve 10 * 200 = 2_000.
  * combined reservation 3_000 < 10_000 available -> BOTH admitted (no cap, no
    contention — the MULTI-02 point). Each fills at the next open, releasing its
    reservation and debiting its principal.

Per-strategy round-trips (fees 0):
  BTCUSD strategy:
    * entry_date 2020-01-03, avg_bought 120 ; exit_date 2020-01-05, avg_sold 140
    * total_bought = 1_200 ; total_sold = 1_400 ; realised_pnl = 200.
  ETHUSDT strategy:
    * entry_date 2020-01-03, avg_bought 210 ; exit_date 2020-01-05, avg_sold 230
    * total_bought = 2_100 ; total_sold = 2_300 ; realised_pnl = 200.

Slippage attribution (post-hoc ``attach_slippage``, single BTCUSD close series for
ALL rows — same harness behavior documented in the two_tickers leaf):
  * BTCUSD: slippage_entry 120 − 100 = 20 ; slippage_exit 140 − 120 = 20.
  * ETHUSDT: slippage_entry 210 − 100 = 110 ; slippage_exit 230 − 120 = 110.

Final portfolio (BOTH round-trips closed, no open position at run end):
  * realised PnL = 200 (BTC) + 200 (ETH) = 400.
  * final_cash = 10_400.00 ; final_equity = 10_400.00 (flat).
  * trade_count = 2, total_realised_pnl = 400.00.

The two ``pair`` rows ARE the MULTI-02 assertion: two independent strategies both
filled on the one portfolio. (Numerically identical to MULTI-01 by construction —
the DISTINGUISHING fact is the SHAPE: ``spec.strategies`` holds TWO emitter
instances here, ONE in MULTI-01.) The metrics block is machine-computed and frozen
as-written; the load-bearing facts are the two fills and the per-strategy PnL.

``profit_factor: Infinity`` is INTENDED here (WR-02 carve-out). Both round-trips are
winners (no losing trade), so gross losses = 0 and ``metrics.py`` returns the all-WIN
``inf`` branch — a legitimate, hand-derivable value for a clean all-win multi-entity
leaf, NOT a degenerate-metrics smell. The ROBUST-03 finite guard
(``_assert_finite.py`` / ``test_metrics_finite.py``) is opt-in and deliberately NOT
applied here; a future ``--freeze`` re-verifier should keep ``Infinity`` frozen
rather than treat it as drift. (``json.dump`` emits the non-standard token
``Infinity``; that is the expected serialization at this edge.)

============================== END VERIFY =============================
"""

import pathlib
from decimal import Decimal

from itrader.core.sizing import FixedQuantity
from tests.e2e.scenario_spec import PortfolioSpec, ScenarioSpec
from tests.e2e.strategies.scripted_emitter import ScriptedEmitter

HERE = pathlib.Path(__file__).resolve().parent

_BTC = "BTCUSD"   # added on the simulated instance; spec.ticker (summary label).
_ETH = "ETHUSDT"  # present in the default ExchangeConfig.limits.supported_symbols.
_TIMEFRAME = "1d"
_CASH = 10_000

# Per-strategy date-keyed scripts (D-04): each emitter trades only its own ticker.
_BTC_SCRIPT = {
    "2020-01-02": {"side": "BUY"},
    "2020-01-04": {"side": "SELL"},
}
_ETH_SCRIPT = {
    "2020-01-02": {"side": "BUY"},
    "2020-01-04": {"side": "SELL"},
}

# FixedQuantity so each strategy buys exactly 10 units and the cash math is exact.
_SIZING = FixedQuantity(qty=Decimal("10"))

# The harness imports this module-level SCENARIO (conftest ``_load_spec``). TWO
# emitter instances on the ONE portfolio -> two strategies, both fill (MULTI-02).
SCENARIO = ScenarioSpec(
    start="2020-01-01",
    end="2020-01-06",
    timeframe=_TIMEFRAME,
    ticker=_BTC,
    starting_cash=_CASH,
    data={_BTC: HERE / "bars.csv", _ETH: HERE / "bars_eth.csv"},
    strategies=[
        ScriptedEmitter(_TIMEFRAME, [_BTC], script=_BTC_SCRIPT,
                        sizing_policy=_SIZING),
        ScriptedEmitter(_TIMEFRAME, [_ETH], script=_ETH_SCRIPT,
                        sizing_policy=_SIZING),
    ],
    portfolios=[PortfolioSpec(name="two_strategies_pf", cash=_CASH)],
    exchange=None,  # zero-fee / zero-slippage — both fills are the only moving part.
)

"""MULTI-03 fanout_portfolios canary — per-portfolio cash isolation (D-01).

The FOUNDATIONAL canary that proves the D-01 ``portfolios.csv`` per-portfolio
summary snapshot end-to-end: ONE ``ScriptedEmitter`` over BTCUSD, subscribed to
TWO portfolios with ASYMMETRIC starting cash. Both portfolios see the SAME signal
on the SAME bars, but because they start with different cash the
``FractionOfCash(0.95)`` sizing deploys different quantities, so their
``final_cash``/``final_equity``/``realised_pnl`` PROVABLY differ. The two-row
``portfolios.csv`` (pf_a, pf_b) with differing values IS the cash-isolation
assertion (VALIDATION Undersampled-Edges: isolation must be OBSERVABLE, not merely
symmetric-and-plausible). The distinct ``name``s (``pf_a`` / ``pf_b``) are the
STABLE snapshot key (NEVER the UUIDv7 PortfolioId — Pitfall 2).

This clones the ``smoke/single_market_buy`` copy-template (same contrived bars,
same single round-trip) so the per-portfolio numbers cross-check trivially against
that already-hand-verified single-portfolio derivation.

================================ VERIFY ================================

HAND-VERIFIED & LOCKED (E2E-04 / D-13): a human confirmed the frozen
``golden/portfolios.csv`` MATCHES the hand-derivation below — two rows whose
``final_cash``/``final_equity`` DIFFER, proving per-portfolio cash isolation is
observable (not symmetric). Re-freeze ONLY via the deliberate ``--freeze`` flag
after re-verifying this derivation.

Contrived bars (``bars.csv`` — daily, tz-aware Open time, all prices round; the
SAME bars as the smoke canary):

    bar  date         open   high   low    close
    0    2020-01-01   100    105    99     104
    1    2020-01-02   110    115    109    114
    2    2020-01-03   120    125    119    124
    3    2020-01-04   130    135    129    134
    4    2020-01-05   140    145    139    144
    5    2020-01-06   150    155    149    154

Engine knobs: timeframe = 1d, exchange = None (zero-fee / no-slippage simulated-
exchange defaults), strategy = ONE ``ScriptedEmitter`` over BTCUSD with a BUY on
the 2020-01-02 decision bar and a full SELL on the 2020-01-04 decision bar
(``FractionOfCash(0.95)`` sizing). The emitter is subscribed to BOTH portfolios
(``_build_and_run`` subscribes every strategy to every portfolio), so each
portfolio independently sizes/fills the SAME signal.

Firing (date-keyed — ``ScriptedEmitter`` reads the decision-bar date):
    decision bar 2020-01-02 (close 114): BUY  → MARKET fills next-bar open
                                               = bar2 open 120 (entry 2020-01-03)
    decision bar 2020-01-04 (close 134): SELL → MARKET fills next-bar open
                                               = bar4 open 140 (exit 2020-01-05)

PORTFOLIO pf_a (starting cash 10_000) — identical to the smoke canary:
  * qty_a = (0.95 * 10_000) / 114 = 9_500 / 114 = 250/3 = 83.3333… units
  * total_bought = (250/3) * 120 = 10_000.00            (full 0.95-fraction deployed)
  * total_sold   = (250/3) * 140 = 11_666.666…          → avg_sold = 140
  * realised_pnl = 11_666.666… - 10_000 = 1_666.666…    = (140-120) * 250/3
  * final_cash   = 10_000 + 1_666.666… = 11_666.666…
  * final_equity = final_cash (no open position at run end) = 11_666.666…
  * trade_count  = 1

PORTFOLIO pf_b (starting cash 5_000) — HALF the cash → provably DIFFERENT numbers:
  * qty_b = (0.95 * 5_000) / 114 = 4_750 / 114 = 125/3 = 41.6666… units
  * total_bought = (125/3) * 120 = 5_000.00             (full 0.95-fraction deployed)
  * total_sold   = (125/3) * 140 = 5_833.333…           → avg_sold = 140
  * realised_pnl = 5_833.333… - 5_000 = 833.333…        = (140-120) * 125/3
  * final_cash   = 5_000 + 833.333… = 5_833.333…
  * final_equity = final_cash (no open position at run end) = 5_833.333…
  * trade_count  = 1

The two rows DIFFER on final_cash (11_666.666… vs 5_833.333…), final_equity (same),
and realised_pnl (1_666.666… vs 833.333…) — exactly the 2:1 cash-asymmetry ratio,
because each portfolio's CashManager reserves/settles its OWN cash. That asymmetry
is the cash-isolation proof.

``profit_factor: Infinity`` is INTENDED here (WR-02 carve-out). Both portfolios'
round-trips are winners (no losing trade), so gross losses = 0 and ``metrics.py``
returns the all-WIN ``inf`` branch — a legitimate, hand-derivable value for a clean
all-win multi-entity leaf, NOT a degenerate-metrics smell. The ROBUST-03 finite guard
(``_assert_finite.py`` / ``test_metrics_finite.py``) is opt-in and deliberately NOT
applied here; a future ``--freeze`` re-verifier should keep ``Infinity`` frozen rather
than treat it as drift. (``json.dump`` emits the non-standard token ``Infinity``; that
is the expected serialization at this edge.)

============================== END VERIFY =============================

Indentation: 4 spaces (matches ``tests/conftest.py`` / the e2e package house style).
"""

import pathlib
from decimal import Decimal

from tests.e2e.scenario_spec import PortfolioSpec, ScenarioSpec
from tests.e2e.strategies.scripted_emitter import ScriptedEmitter

HERE = pathlib.Path(__file__).resolve().parent

_TICKER = "BTCUSD"
_TIMEFRAME = "1d"

# ONE emitter: BUY on the 2020-01-02 decision bar, full SELL on 2020-01-04.
_SCRIPT = {
    "2020-01-02": {"side": "BUY"},
    "2020-01-04": {"side": "SELL", "exit_fraction": Decimal("1")},
}

# The harness imports this module-level SCENARIO (conftest._load_spec).
SCENARIO = ScenarioSpec(
    start="2020-01-01",
    end="2020-01-06",
    timeframe=_TIMEFRAME,
    ticker=_TICKER,
    starting_cash=10_000,
    data={_TICKER: HERE / "bars.csv"},
    strategies=[ScriptedEmitter(_TIMEFRAME, [_TICKER], script=_SCRIPT)],
    portfolios=[
        PortfolioSpec(name="pf_a", cash=10_000),
        PortfolioSpec(name="pf_b", cash=5_000),
    ],
    exchange=None,
)

"""ROBUST-03a no_trade: zero closed trades -> all-finite degenerate metrics (D-05).

The degenerate-input case for the derived metrics: a run that opens ZERO positions
and closes ZERO trades. The reporting metric guards (``reporting/metrics.py``) must
coerce every ratio to a finite 0.0 over an empty equity curve + empty trades frame
-- no NaN, no div-by-zero, no inf. This leaf proves that contract end-to-end on the
real run path and freezes the resulting metrics block.

Analog: ``tests/e2e/sizing/over_cash_reject`` (zero closed trades, EMPTY trades.csv,
``trade_count = 0``). Where over_cash_reject produces zero trades via a REJECTED
over-cash order, this leaf produces zero trades the SIMPLEST way -- the strategy is
subscribed but its date-keyed script NEVER hits a decision-bar date, so
``generate_signal`` always returns ``None`` (no order is ever emitted, nothing to
reject, nothing to fill). The flat constant-price ``bars.csv`` makes every derived
metric trivially hand-checkable.

================================ VERIFY ================================

HAND-VERIFIED & LOCKED (D-05): a human confirmed the frozen ``golden/trades.csv``
is EMPTY (header-only, ``trade_count = 0``) and the ``golden/summary.json``
``metrics`` block is all-finite (all 0.0). Re-freeze ONLY via ``--freeze`` after
re-verifying this derivation.

Contrived bars (``bars.csv`` -- daily, tz-aware Open time, constant flat price):

    bar  date         open   high   low    close
    0    2020-01-01   100    105    99     100
    1    2020-01-02   100    105    99     100
    2    2020-01-03   100    105    99     100
    3    2020-01-04   100    105    99     100

Engine knobs: starting_cash = 10_000, timeframe = 1d, exchange = None (zero-fee /
no-slippage, D-14), ONE portfolio, strategy = ``ScriptedEmitter`` with an EMPTY
script ``{}`` -- so ``generate_signal`` returns ``None`` on every tick. NO BUY, NO
SELL, NO order, NO fill.

Lifecycle: the run completes cleanly over all four bars. The order mirror is empty
(no order ever emitted); ZERO positions open; ZERO trades close. The portfolio cash
and equity stay at the starting 10_000 on every bar -- a perfectly flat equity
curve at the constant 10_000.

Derived metrics (the ROBUST-03a contract -- each guard fires, each is FINITE):
  * ``sharpe``        = 0.0  -- the equity curve is flat: per-bar returns are all
                               0.0, so ``sd == 0`` -> the zero-std guard fires
                               (metrics.py:65-66). Finite.
  * ``sortino``       = 0.0  -- downside deviation = 0 (no negative returns) ->
                               the zero-downside guard fires (metrics.py:80-81).
                               Finite.
  * ``cagr``          = 0.0  -- start == final == 10_000, so ``(final/start) **
                               (1/years) - 1 = 1 - 1 = 0.0`` (metrics.py:118).
                               Finite.
  * ``max_drawdown``  = 0.0  -- the equity never drops below its running max
                               (flat), so ``dd.min() == 0.0`` (metrics.py:53-54).
                               Finite.
  * ``profit_factor`` = 0.0  -- the trades frame is EMPTY -> the empty-frame guard
                               returns 0.0 (metrics.py:91-92), NOT inf. Finite.
  * ``win_rate``      = 0.0  -- empty trades frame -> 0.0 (metrics.py:124-125).
                               Finite.

Final portfolio: final_cash = final_equity = 10_000.00 (untouched), trade_count = 0,
total_realised_pnl = 0.0, trades.csv EMPTY. Every metric is finite -- no NaN, no inf
-- which is the ROBUST-03a assertion (also enforced explicitly by
``test_metrics_finite.py`` via ``assert_metrics_finite``).

============================== END VERIFY =============================
"""

import pathlib

from tests.e2e.scenario_spec import PortfolioSpec, ScenarioSpec
from tests.e2e.strategies.scripted_emitter import ScriptedEmitter

HERE = pathlib.Path(__file__).resolve().parent

_TICKER = "BTCUSD"  # Pitfall 1: any non-registered ticker silently REFUSES orders.
_TIMEFRAME = "1d"
_CASH = 10_000

# ROBUST-03a: an EMPTY script -> generate_signal returns None every tick -> NO order
# is ever emitted -> zero positions, zero trades. The simplest zero-trade shape
# (no REJECTED order to reason about, unlike over_cash_reject).
_SCRIPT: dict[str, dict] = {}

# The harness imports this module-level SCENARIO (conftest ``_load_spec``).
SCENARIO = ScenarioSpec(
    start="2020-01-01",
    end="2020-01-04",
    timeframe=_TIMEFRAME,
    ticker=_TICKER,
    starting_cash=_CASH,
    data={_TICKER: HERE / "bars.csv"},
    strategies=[ScriptedEmitter(_TIMEFRAME, [_TICKER], script=_SCRIPT)],
    portfolios=[PortfolioSpec(user_id=1, name="no_trade_pf", cash=_CASH)],
    exchange=None,  # D-14: zero-fee / zero-slippage -- degenerate metrics only.
)

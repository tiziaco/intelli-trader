"""ROBUST-02: AAVE mid-run listing over the UNION window, on REAL sliced data (D-03).

Phase 3 proved the union-window + mid-run-listing primitive on SYNTHETIC fixtures
(``tests/integration/test_universe_spans.py``) and DEFERRED the real ETH/SOL/AAVE
E2E run to Phase 9 (this leaf). It re-proves the SAME mechanic on the REAL
ingestion path: a tiny window of the committed ``data/AAVEUSD_1d_ohlcv.csv`` (which
LISTS mid-run at **2021-07-15**) SLICED via the D-03 ``csv_paths`` passthrough,
co-loaded with a sliced ``data/BTCUSD_1d_ohlcv_2018_2026.csv`` that trades
THROUGHOUT. The run window STARTS before AAVE's first bar so the union grid has
days where AAVE is ABSENT (pre-listing) then PRESENT — and NO AAVE fill occurs
before the listing (no look-ahead). No production change — the slices are small
committed CSVs beside this file; ``csv_paths`` default None keeps the BTCUSD oracle
byte-identical.

One-shape-per-leaf (RESEARCH §Undersampled): this leaf authors the mid-run-LISTING
edge cleanly. The differing-END-date edge (BTC ends 2026-06-03 vs the *USD majors
2026-01-08) is a SEPARATE shape and is NOT crammed in here — it stays trivially
hand-verifiable by being out of scope for this slice.

The engine mechanic (ships already — DO NOT rebuild)
----------------------------------------------------
The union ping grid (``backtest_trading_system`` WR-07) ticks across the UNION of
all loaded tickers' dates — here BTC's dense 07-10..07-20. On the 07-10..07-14
ticks AAVE has NO bar (pre-listing), so ``current_bars`` (a sparse dict) drops
AAVEUSD; the strategy handler's ``event.bars.get(ticker) is None -> continue``
guard means ``generate_signal`` is NEVER called for AAVE before 2021-07-15, so an
AAVE BUY scripted on a pre-listing date is STRUCTURALLY impossible to fill (the
span-aware feed / ``is_active`` / ``active_membership`` primitive,
``itrader/universe/membership.py``). The first AAVE bar the engine can deliver is
its listing day; the AAVE position can only open on/after it.

================================ VERIFY ================================

HAND-VERIFIED & LOCKED (E2E-04 / D-13): a human confirmed the frozen
``golden/trades.csv`` + ``golden/summary.json`` MATCH the hand-derivation below.
Re-freeze ONLY via ``--freeze`` after re-verifying this derivation.

Sliced bars (POST-slice, hand-verified against the raw committed CSVs — the store
loads ``<day> 00:00 UTC`` and tz-converts to Europe/Paris, but the emitter
``tz_convert("UTC")``s the decision-bar date back, so all date keys below are UTC,
matching the CSV stamps — Assumption A2):

    BTCUSD (btc_sliced.csv, the always-present co-asset)
    date         open       close       AAVE present?
    2021-07-10   33815.81   33502.87    no  (pre-listing — AAVE absent)
    2021-07-11   33502.87   34258.99    no
    2021-07-12   34259.00   33086.63    no  <- AAVE BUY scripted here NEVER fires
    2021-07-13   33086.94   32729.77    no     (no AAVE bar -> generate_signal not called)
    2021-07-14   32729.12   32820.02    no
    2021-07-15   32820.03   31880.00    YES (AAVE LISTS — first AAVE bar)
    2021-07-16   31874.49   31383.87    yes
    2021-07-17   31383.86   31520.07    yes
    2021-07-18   31520.07   31778.56    yes
    2021-07-19   31778.57   30839.65    yes
    2021-07-20   30839.65   29790.35    yes

    AAVEUSD (aave_sliced.csv) — FIRST row is 2021-07-15 (the mid-run listing).
    date         open       close
    2021-07-15   269.83     270.75
    2021-07-16   271.03     253.99
    2021-07-17   252.57     253.64
    2021-07-18   253.30     256.32
    2021-07-19   254.06     237.77
    2021-07-20   239.09     222.86

Engine knobs: starting_cash = 1_000_000 (ample — both fit, no contention),
timeframe = 1d, exchange = None (zero-fee / zero-slippage). TWO ScriptedEmitters
on ONE portfolio, FixedQuantity sizing so BTC and AAVE never contend for cash:
  * BTC emitter (FixedQuantity 1): the always-present co-asset proving the union
    window RUNS. BUY 2021-07-10 -> fills @ NEXT BTC open = 2021-07-11 open
    33502.87; SELL 2021-07-13 -> fills @ NEXT BTC open = 2021-07-14 open 32729.12.
  * AAVE emitter (FixedQuantity 10): the mid-run lister. A BUY is scripted on
    2021-07-12 (PRE-listing — NEVER fires, AAVE has no bar / generate_signal not
    called) AND on 2021-07-15 (the listing day) -> fills @ NEXT AAVE open =
    2021-07-16 open 271.03; SELL 2021-07-18 -> fills @ NEXT AAVE open = 2021-07-19
    open 254.06.

BTC round-trip (FixedQuantity 1, fees 0):
  * entry_date 2021-07-11, avg_bought 33502.87 ; exit_date 2021-07-14,
    avg_sold 32729.12 ; realised_pnl = (32729.12 - 33502.87) * 1 = -773.75 (BTC
    fell over the held window — a small real LOSS; the load-bearing fact is the
    union-window RUN, not the sign).

AAVE round-trip (FixedQuantity 10, fees 0):
  * The 2021-07-12 pre-listing BUY produced NO position (no AAVE bar delivered).
  * entry_date 2021-07-16 (>= the 2021-07-15 listing — NO look-ahead),
    avg_bought 271.03 ; exit_date 2021-07-19, avg_sold 254.06 ;
    realised_pnl = (254.06 - 271.03) * 10 = -169.70.

LOAD-BEARING ROBUST-02 facts (hand-checked; exact PnL digits machine-frozen on the
real prices above):
  * The run completes with NO crash over the union window (07-10..07-20) that
    spans AAVE's mid-run listing.
  * NO AAVE fill on ANY bar before 2021-07-15: the AAVE entry_date is 2021-07-16
    (fill of the listing-day BUY) — there is NO AAVE trade with an entry on or
    before the 2021-07-12 pre-listing BUY date.
  * BTC (the always-present co-asset) traded throughout — proving the engine ran
    the full union window, not just AAVE's span.
  * trade_count = 2 (one BTC, one AAVE round-trip).

Slippage attribution (the post-hoc ``attach_slippage`` lens, conftest.py): WR-03 —
the harness reads ONE close series, ``spec.ticker`` = AAVEUSD, and attributes it to
EVERY trade row regardless of the row's own ticker. ``slippage = fill_price −
decision_close``, where ``decision_close`` is read off the AAVE close index:
  * BTCUSD row: the BTC fills (entry 2021-07-11, exit 2021-07-14) land BEFORE AAVE's
    FIRST bar (2021-07-15), so they precede the AAVE close index. ``decision_close``
    returns 0.0 via the ``position <= 0`` early-return guard (summary.py), so
    ``slippage = fill_price − 0`` and the slippage columns EQUAL the raw BTC fill
    prices: slippage_entry = 33502.87 − 0 = 33502.87 ; slippage_exit = 32729.12 − 0
    = 32729.12. This is the documented single-close-series harness behavior, NOT a
    per-ticker BTC slippage — it is hand-checkable here so a re-freezer is not
    trusting a machine number.
  * AAVEUSD row: measured against the AAVE close series proper. Entry fill 271.03
    (07-16 open) vs the BUY decision-bar (07-15) close 270.75 -> slippage_entry =
    271.03 − 270.75 = 0.28. Exit fill 254.06 (07-19 open) vs the SELL decision-bar
    (07-18) close 256.32 -> slippage_exit = 254.06 − 256.32 = −2.26.

The metrics block is machine-computed by ``itrader.reporting.metrics`` and frozen
as-written; both trades are net LOSSES so profit_factor is 0.0 (the all-loss
branch — finite, not the all-win +inf branch).

============================== END VERIFY =============================
"""

import pathlib
from decimal import Decimal

from itrader.core.sizing import FixedQuantity
from tests.e2e.scenario_spec import PortfolioSpec, ScenarioSpec
from tests.e2e.strategies.scripted_emitter import ScriptedEmitter

HERE = pathlib.Path(__file__).resolve().parent

_BTC = "BTCUSD"    # the always-present co-asset (added on the simulated instance
# by execution_handler + the conftest spec.data seam).
_AAVE = "AAVEUSD"  # spec.ticker — the mid-run lister (registered by the conftest
# spec.data seam; not a default *USDT symbol).
_TIMEFRAME = "1d"
_CASH = 1_000_000  # ample — BTC (~33.5k) + AAVE (~2.7k) both fit; no cash contention.

# BTC round-trip across the full window (proves the union window RUNS).
_BTC_SCRIPT = {
    "2021-07-10": {"side": "BUY"},   # fills 07-11 open
    "2021-07-13": {"side": "SELL"},  # fills 07-14 open
}
# AAVE: a PRE-listing BUY (07-12, NEVER fires — no AAVE bar) + a listing-day BUY
# (07-15, fills 07-16) + a SELL (07-18, fills 07-19).
_AAVE_SCRIPT = {
    "2021-07-12": {"side": "BUY"},   # PRE-listing — structurally cannot fill
    "2021-07-15": {"side": "BUY"},   # listing day -> fills 07-16 open (no look-ahead)
    "2021-07-18": {"side": "SELL"},  # fills 07-19 open
}

# The harness imports this module-level SCENARIO (conftest ``_load_spec``).
SCENARIO = ScenarioSpec(
    start="2021-07-10",  # STARTS before AAVE's 2021-07-15 listing -> union has
    end="2021-07-20",    # pre-listing bars where AAVE is absent.
    timeframe=_TIMEFRAME,
    ticker=_AAVE,  # the asserted listing ticker (summary label / orders scope).
    starting_cash=_CASH,
    data={_BTC: HERE / "btc_sliced.csv", _AAVE: HERE / "aave_sliced.csv"},
    strategies=[
        ScriptedEmitter(_TIMEFRAME, [_BTC], script=_BTC_SCRIPT, name="emitter_btc",
                        sizing_policy=FixedQuantity(qty=Decimal("1"))),
        ScriptedEmitter(_TIMEFRAME, [_AAVE], script=_AAVE_SCRIPT, name="emitter_aave",
                        sizing_policy=FixedQuantity(qty=Decimal("10"))),
    ],
    portfolios=[PortfolioSpec(name="union_window_pf", cash=_CASH)],
    exchange=None,  # zero-fee / zero-slippage — the listing edge is the moving part.
)

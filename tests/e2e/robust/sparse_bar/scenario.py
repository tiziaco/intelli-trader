"""ROBUST-01: sparse / absent-bar guard re-proven on REAL sliced SOL data (D-03).

Phase 3 proved the sparse-dict no-fill guard on SYNTHETIC fixtures
(``tests/integration/test_universe_spans.py``). This leaf re-proves the SAME
mechanic on the REAL ingestion path: a tiny window of the committed
``data/SOLUSD_1d_ohlcv.csv`` SLICED (via the D-03 ``csv_paths`` passthrough that
``data={ticker: HERE/"x.csv"}`` drives) so a SOL position is LIVE across SOL's
genuine 2-day data gap (2023-06-24 / 2023-06-25). No production change — the
slices are small committed CSVs beside this file; ``csv_paths`` default None keeps
the BTCUSD oracle byte-identical.

Why THIS gap (Pitfall 1, RESEARCH — load-bearing)
--------------------------------------------------
SOL's 418 missing bars are ONE 416-day block (2023-07-07 -> 2024-08-25) PLUS
exactly one clean 2-day gap: **2023-06-24 and 2023-06-25**, both present in ETH
(and AAVE). A "random" SOL window is therefore either fully dense or inside the
416-day hole — only this 2-day gap lets a position be open BEFORE the gap and
still open AFTER it, exercising the matching path across the absent bars (not just
a warm-up gap). The sliced ``sol_sliced.csv`` is MISSING the 06-24/06-25 rows
(verified against the raw CSV); the dense ``eth_sliced.csv`` DOES carry both —
ETH is the always-present co-asset whose dates keep the union ping grid ticking
ACROSS the gap so the absent-SOL-bar ticks actually occur.

The engine mechanic (ships already — DO NOT rebuild)
----------------------------------------------------
The union ping grid (``backtest_trading_system`` WR-07) ticks across the UNION of
all loaded tickers' dates — here ETH's dense 06-22..06-28. On the 06-24 and 06-25
ticks SOL has NO bar, so ``current_bars`` (a sparse dict) drops SOLUSD; the
strategy handler's ``event.bars.get(ticker) is None -> continue`` guard (WR-12)
emits NO SOL signal, so the resting/market path produces NO SOL fill on those two
dates. The SOL position opened 06-23 simply RIDES the gap and is closed 06-27.

================================ VERIFY ================================

HAND-VERIFIED & LOCKED (E2E-04 / D-13): a human confirmed the frozen
``golden/trades.csv`` + ``golden/summary.json`` MATCH the hand-derivation below.
Re-freeze ONLY via ``--freeze`` after re-verifying this derivation.

Sliced bars (POST-slice, hand-verified against the raw committed CSVs — the store
loads ``<day> 00:00 UTC`` rows and tz-converts to Europe/Paris, but the emitter
``tz_convert("UTC")``s the decision-bar date back, so all date keys below are UTC,
matching the CSV stamps — Assumption A2):

    SOLUSD (sol_sliced.csv)              ETHUSDT (eth_sliced.csv, the dense control)
    date         open       close       date         present?
    2023-06-22   17.234     16.6310     2023-06-22   yes
    2023-06-23   16.6290    17.3552     2023-06-23   yes
    --- 2023-06-24 ABSENT (gap) ---     2023-06-24   yes   <- ping grid ticks here
    --- 2023-06-25 ABSENT (gap) ---     2023-06-25   yes   <- ping grid ticks here
    2023-06-26   16.4768    16.2697     2023-06-26   yes
    2023-06-27   16.2695    16.6162     2023-06-27   yes
    2023-06-28   16.6197    15.9709     2023-06-28   yes

Engine knobs: starting_cash = 10_000, timeframe = 1d, exchange = None (zero-fee /
zero-slippage simulated-exchange defaults). ONE ScriptedEmitter trades SOLUSD only
(FractionOfCash(0.95), the golden sizing policy). ETHUSDT is loaded ONLY as the
dense co-asset that fills the union ping grid across the gap — no ETH strategy, so
ETH never trades.

Script (date-keyed on the DECISION bar; MARKET fills at the NEXT SOL bar's open):
  * BUY decided 2023-06-22 (SOL close 16.6310) -> fills @ NEXT SOL bar open =
    2023-06-23 open 16.6289935 (entry_date 2023-06-23). The position is now OPEN.
  * 2023-06-24 / 2023-06-25: the ping grid ticks (ETH is present) but SOL is
    ABSENT -> ``current_bars`` has no SOLUSD -> NO signal, NO fill. The SOL
    position is LIVE across BOTH absent bars (the ROBUST-01 matching-path proof).
  * SELL decided 2023-06-26 (SOL close 16.2697, the first SOL bar after the gap)
    -> fills @ NEXT SOL bar open = 2023-06-27 open 16.2695400 (exit_date
    2023-06-27, full exit).

Entry sizing (FractionOfCash(0.95) on the DECISION-bar close 16.6310, full cash):
    qty = (0.95 * 10_000) / 16.6309936500 = 9_500 / 16.6309936500
        = 571.2226340727392436951594892 units (full-precision Decimal).
    total_bought = qty * entry_fill (16.6289935) = the frozen avg_bought basis.
Exit: total_sold = qty * exit_fill (16.2695400); realised_pnl = total_sold -
total_bought < 0 (SOL drifted DOWN 16.6290 -> 16.2695 over the held window — a
small real-data LOSS; the load-bearing fact is the NO-FILL/NO-CRASH across the
gap, not the sign of the PnL).

LOAD-BEARING ROBUST-01 facts (hand-checked; the exact PnL digits are machine-frozen
on the real prices above):
  * The run completes with NO crash over the union window that ticks across the gap.
  * NO SOL fill is recorded on 2023-06-24 or 2023-06-25 (entry_date 2023-06-23,
    exit_date 2023-06-27 — both straddle, neither equals an absent-bar date).
  * Exactly ONE SOLUSD round-trip; trade_count = 1.

The metrics block (sharpe/sortino/cagr/max_drawdown/profit_factor/win_rate) is
machine-computed by the shared ``itrader.reporting.metrics`` and frozen as-written;
profit_factor is finite here (the single trade is a net LOSS, so all-loss ->
profit_factor 0.0, not the all-win +inf branch).

============================== END VERIFY =============================
"""

import pathlib

from tests.e2e.scenario_spec import PortfolioSpec, ScenarioSpec
from tests.e2e.strategies.scripted_emitter import ScriptedEmitter

HERE = pathlib.Path(__file__).resolve().parent

_SOL = "SOLUSD"   # spec.ticker — the asset with the genuine 2-day gap. Registered
# on the simulated instance by the conftest spec.data seam (not a default *USDT).
_ETH = "ETHUSDT"  # the dense co-asset; in the default supported set. Loaded ONLY
# to fill the union ping grid across the SOL gap — no ETH strategy.
_TIMEFRAME = "1d"
_CASH = 10_000

# SOL round-trip straddling the 2023-06-24/25 gap: BUY before, SELL after.
_SOL_SCRIPT = {
    "2023-06-22": {"side": "BUY"},   # fills 06-23 open; position open BEFORE the gap
    "2023-06-26": {"side": "SELL"},  # fills 06-27 open; closes AFTER the gap
}

# The harness imports this module-level SCENARIO (conftest ``_load_spec``).
SCENARIO = ScenarioSpec(
    start="2023-06-22",
    end="2023-06-28",
    timeframe=_TIMEFRAME,
    ticker=_SOL,
    starting_cash=_CASH,
    data={_SOL: HERE / "sol_sliced.csv", _ETH: HERE / "eth_sliced.csv"},
    strategies=[
        # ONE emitter, SOLUSD only. ETH is data-only (the dense grid co-asset).
        ScriptedEmitter(_TIMEFRAME, [_SOL], script=_SOL_SCRIPT),
    ],
    portfolios=[PortfolioSpec(user_id=1, name="sparse_bar_pf", cash=_CASH)],
    exchange=None,  # zero-fee / zero-slippage — the gap is the only moving part.
)

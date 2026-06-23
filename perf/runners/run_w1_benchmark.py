"""W1 realistic benchmark runner (PERF-BASELINE §5/§11).

iTrader-only. Runs the 4-strategy / 6-portfolio topology over the real 5m CSVs,
drives Strategy B's cancel/modify lifecycle from the ``on_tick`` hook, captures
wall-clock + peak memory, and ASSERTS a non-trivial trade log (>0 total fills
across the six portfolios) — a benchmark that does not trade measures nothing.
Prints a per-portfolio breakdown so the §6 paths that fired are visible.

Profiling (Scalene) is Step 2, NOT here.
"""

import argparse
import datetime as dt
import json
import os
import sys
import time
import tracemalloc
from decimal import Decimal
from typing import Any

from itrader.core.enums import OrderStatus, OrderType
from itrader.trading_system.backtest_trading_system import BacktestTradingSystem

from perf.workloads.w1_topology import CSV_PATHS, TIMEFRAME, wire_w1, W1Topology

# Date window for the gated W1 run. D-07: the default is PINNED to the frozen
# 2-month baseline slice (2026-04-23 → 2026-06-23) so `make perf-w1` reproduces
# the ~240.8s gated number with no env vars to remember. The os.environ.get
# override mechanism stays intact: `make perf-w1 W1_START_DATE=… W1_END_DATE=…`
# still slices an ad-hoc window via the Makefile's .EXPORT_ALL_VARIABLES.
_START_DATE = os.environ.get("W1_START_DATE", "2026-04-23")
_END_DATE = os.environ.get("W1_END_DATE", "2026-06-23")


def _make_on_tick(system: Any, topo: W1Topology) -> Any:
    """Build the on_tick hook owning Strategy B's cancel/modify lifecycle (§6).

    Each bar, for B's portfolio (P2), inspect resting LIMIT orders (status
    PENDING) and play the operator the strategy cannot (a strategy cannot
    reach its own resting order from generate_signal; RECON §3):

    - re-price (``modify_order``) each unfilled limit UP toward the current price
      by a small step so a chasing maker fills within a few bars (this both
      exercises the modify + mirror-reconcile path AND lets B's resting-limit book
      actually fill), and
    - cancel (``cancel_order``) any limit that has been chased too many bars
      without filling (a stale order) — the cancel + mirror-reconcile path.

    The modify/cancel OrderEvents drain on the next bar's process_events.
    """
    pid_b = topo.portfolio_ids[1]  # P2 = B
    oh = system.order_handler
    # order_id -> number of bars it has been chased (re-priced) without filling.
    chase_age: dict[Any, int] = {}
    _STALE_AFTER = 6        # cancel a limit chased this many bars unfilled
    _CHASE_STEP = Decimal("1.002")  # re-price 0.2% UP toward price each bar

    def on_tick(_runner: Any, _time_event: Any) -> None:
        resting = [
            o for o in oh.get_orders_by_status(OrderStatus.PENDING, pid_b)
            if o.type == OrderType.LIMIT
        ]
        live_ids = {o.id for o in resting}
        # Drop age entries for orders that filled / cancelled (no longer resting).
        for oid in list(chase_age):
            if oid not in live_ids:
                chase_age.pop(oid, None)

        for o in resting:
            age = chase_age.get(o.id, 0)
            if age >= _STALE_AFTER:
                # Stale: cancel + mirror reconcile.
                oh.cancel_order(o.id, portfolio_id=pid_b,
                                reason="W1 on_tick cancel stale limit")
                chase_age.pop(o.id, None)
            else:
                # Chase UP toward price so the maker eventually crosses + fills.
                new_price = o.price * _CHASE_STEP
                oh.modify_order(o.id, new_price=new_price, portfolio_id=pid_b,
                                reason="W1 on_tick chase re-price")
                chase_age[o.id] = age + 1

    return on_tick


def _portfolio_trade_count(portfolio: Any) -> tuple[int, int]:
    """Return (fills, closed_positions) for one portfolio."""
    fills = len(portfolio.transactions)
    closed = len(portfolio.closed_positions)
    return fills, closed


def run_w1() -> dict[str, Any]:
    """Run the W1 benchmark; return a result dict (timing, memory, breakdown)."""
    system = BacktestTradingSystem(
        exchange="csv",
        csv_paths=CSV_PATHS,
        start_date=_START_DATE,
        end_date=_END_DATE,
        timeframe=TIMEFRAME,
    )
    topo = wire_w1(system)
    on_tick = _make_on_tick(system, topo)

    tracemalloc.start()
    t0 = time.perf_counter()
    system.run(print_summary=False, on_tick=on_tick)
    wall_clock_s = time.perf_counter() - t0
    _current, peak_bytes = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    peak_mem_mb = peak_bytes / (1024 * 1024)

    labels = ["P1_A", "P2_B", "P3_C", "P4_D", "P5_D", "P6_D"]
    breakdown: dict[str, dict[str, int]] = {}
    total_fills = 0
    total_closed = 0
    for label, pid in zip(labels, topo.portfolio_ids):
        portfolio = system.portfolio_handler.get_portfolio(pid)
        fills, closed = _portfolio_trade_count(portfolio)
        breakdown[label] = {"fills": fills, "closed_positions": closed}
        total_fills += fills
        total_closed += closed

    print("\n===== W1 BENCHMARK RESULT =====")
    print(f"wall_clock_s : {wall_clock_s:.3f}")
    print(f"peak_mem_mb  : {peak_mem_mb:.2f}")
    print("per-portfolio trade breakdown (fills / closed_positions):")
    for label in labels:
        b = breakdown[label]
        print(f"  {label}: {b['fills']:>5} fills  {b['closed_positions']:>4} closed")
    print(f"TOTAL fills: {total_fills}  TOTAL closed_positions: {total_closed}")
    print("================================\n")

    # Non-trivial trade-density assertion (§11): a benchmark that does not trade
    # measures nothing. Fail loudly so thresholds get tightened, never ship dead.
    assert total_fills > 0, (
        "W1 benchmark produced ZERO fills across all six portfolios — tighten "
        "strategy thresholds (spec §9 risk 3); do NOT ship a dead benchmark.")

    return {
        "wall_clock_s": wall_clock_s,
        "peak_mem_mb": peak_mem_mb,
        "breakdown": breakdown,
        "total_fills": total_fills,
        "total_closed_positions": total_closed,
    }


def _to_baseline_schema(result: dict[str, Any]) -> dict[str, Any]:
    """Build the D-01 committed-baseline payload from a run_w1() result dict.

    final_equity is the byte-exact SMA_MACD oracle CONSTANT serialized as a
    STRING (money discipline; never a JSON float) — it is a provenance stamp
    that the engine was on-contract when frozen (OQ-1/A1), NOT a W1-derived
    value (the W1 coverage workload is not the oracle).
    """
    return {
        "schema_version": 1,
        "frozen_at": dt.date.today().isoformat(),
        "metric": {
            "wall_clock_s": round(result["wall_clock_s"], 1),
            "peak_mem_mb": round(result["peak_mem_mb"], 1),
        },
        "window": {"start_date": _START_DATE, "end_date": _END_DATE},
        "workload": {
            "name": "W1",
            "timeframe": TIMEFRAME,
            "seed": 42,
            "total_fills": result["total_fills"],
            "total_closed_positions": result["total_closed_positions"],
        },
        "oracle_provenance": {
            "test": "tests/integration/test_backtest_oracle.py",
            "trade_count": 134,
            "final_equity": "46189.87730727451",
            "green_at_freeze": True,
        },
    }


def _write_baseline(result: dict[str, Any], out_path: str) -> None:
    """Freeze a run as the committed W1-BASELINE.json (D-01 schema)."""
    with open(out_path, "w") as fh:
        json.dump(_to_baseline_schema(result), fh, indent=2)
        fh.write("\n")


def _check_regression(
    result: dict[str, Any], baseline_path: str, band_pct: float = 5.0
) -> int:
    """Soft regression guard (D-02/D-04). ALWAYS print both deltas; FAIL (return
    1) ONLY on a >+band_pct wall-clock SLOWDOWN. A faster-or-within-±band run
    returns 0 — an improvement must NEVER trip the guard (Pitfall 3; no abs()).
    Peak memory is reported and watched but never fails.
    """
    with open(baseline_path) as fh:
        base = json.load(fh)
    base_wall = base["metric"]["wall_clock_s"]
    base_mem = base["metric"]["peak_mem_mb"]
    wall = result["wall_clock_s"]
    mem = result["peak_mem_mb"]
    wall_d = (wall - base_wall) / base_wall * 100.0
    mem_d = (mem - base_mem) / base_mem * 100.0
    print(f"W1 wall_clock {wall:.1f}s  Δ {wall_d:+.1f}%  (baseline {base_wall:.1f}s)")
    print(f"W1 peak_mem  {mem:.1f}MB  Δ {mem_d:+.1f}%  (baseline {base_mem:.1f}MB, watched)")
    if wall_d > band_pct:                       # only a real SLOWDOWN fails (D-04)
        print(f"PERF REGRESSION: +{wall_d:.1f}% > band {band_pct:.1f}% — gate (b) guard FAILED")
        return 1
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="W1 realistic benchmark")
    parser.add_argument("--json", action="store_true",
                        help="emit the result dict as JSON (machine-readable)")
    parser.add_argument("--check", action="store_true",
                        help="compare vs W1-BASELINE.json; soft regression guard (gate b)")
    parser.add_argument("--baseline-out", metavar="PATH",
                        help="freeze: write the run as the committed baseline JSON")
    args = parser.parse_args()
    result = run_w1()                       # human stdout prints by default (D-06)
    if args.json:
        print(json.dumps(_to_baseline_schema(result), indent=2))
    if args.baseline_out:
        _write_baseline(result, args.baseline_out)
    if args.check:
        sys.exit(_check_regression(result, "perf/results/W1-BASELINE.json"))


if __name__ == "__main__":
    main()

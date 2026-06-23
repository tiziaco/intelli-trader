"""W1 realistic benchmark runner (PERF-BASELINE §5/§11).

iTrader-only. Runs the 4-strategy / 6-portfolio topology over the real 5m CSVs,
drives Strategy B's cancel/modify lifecycle from the ``on_tick`` hook, captures
wall-clock + peak memory, and ASSERTS a non-trivial trade log (>0 total fills
across the six portfolios) — a benchmark that does not trade measures nothing.
Prints a per-portfolio breakdown so the §6 paths that fired are visible.

Profiling (Scalene) is Step 2, NOT here.
"""

import os
import time
import tracemalloc
from decimal import Decimal
from typing import Any

from itrader.core.enums import OrderStatus, OrderType
from itrader.trading_system.backtest_trading_system import BacktestTradingSystem

from perf.workloads.w1_topology import CSV_PATHS, TIMEFRAME, wire_w1, W1Topology

# Date window covering the fetched 5m data (180d ending 2026-06-22). The frozen
# default spans the full fetched range; override via env (W1_START_DATE /
# W1_END_DATE) to profile a shorter, faster slice (e.g. a 2-month window) without
# editing — keeps the slice reproducible and the committed default untouched.
_START_DATE = os.environ.get("W1_START_DATE", "2025-12-24")
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


def main() -> None:
    run_w1()


if __name__ == "__main__":
    main()

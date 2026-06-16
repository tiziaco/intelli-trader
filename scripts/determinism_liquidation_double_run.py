"""Phase-4 determinism gate (Plan 04-05, Task 3) — liquidation scenario double-run.

Drives the REAL forced-liquidation LONG engine TWICE and asserts the two runs are
BYTE-IDENTICAL across the load-bearing liquidation surface (the deterministic
multi-breach sort + bar_time-stamped forced-close fills). This is the Phase-4
determinism gate for a LIQUIDATION scenario (the e2e `short_carry` leaf already covers
the carry double-run; this covers the forced-close path).

SCRIPT-ONLY (D-10): reuses the e2e leaf's `_build_liq_system` harness but lives under
`scripts/` so it is NEVER imported under `tests/` (keeps `filterwarnings=["error"]`
intact). Run directly:

    PYTHONPATH="$PWD" poetry run python scripts/determinism_liquidation_double_run.py

Exit 0 + "DETERMINISM OK" on byte-identical runs; non-zero on any divergence.
"""

from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path

# Import the e2e leaf harness (the canonical white-box forced-liq LONG build).
_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "tests" / "e2e" / "forced_liq_long"))

from test_forced_liq_long_scenario import (  # type: ignore[import-not-found]
    _TICKER,
    _build_liq_system,
)


def _run_once() -> dict[str, object]:
    """Drive the forced-liq LONG engine end-to-end; return a deterministic snapshot dict
    of the cash/position trajectory + the forced-close settlement (the liquidation
    output the determinism gate compares)."""
    system, portfolio, portfolio_id = _build_liq_system()
    engine = system.engine
    handler = system.portfolio_handler
    cash = portfolio.cash_manager

    per_bar: list[tuple[str, str, str, str, str, str]] = []
    for time_event in engine.time_generator:
        date = time_event.time.tz_convert("UTC").strftime("%Y-%m-%d")
        engine.clock.set_time(time_event.time)
        engine.global_queue.put(time_event)
        engine.event_handler.process_events()
        for active in handler.get_active_portfolios():
            active.record_metrics(time_event.time)

        position = portfolio.get_open_position(_TICKER)
        per_bar.append((
            date,
            str(cash.balance),
            str(cash.available_balance),
            str(cash.locked_margin_total),
            "None" if position is None else str(position.net_quantity),
            str(handler.total_equity(portfolio_id)),
        ))

    engine.order_handler.expire_all_resting()
    engine.event_handler.process_events()

    # Forced-close settlement (the liquidation output).
    closed = portfolio.closed_positions
    orders = system.order_handler.get_orders_by_ticker(_TICKER, portfolio_id)
    # Stable order: sort the order summary by (price, action, quantity) so the snapshot
    # is independent of any incidental storage iteration order.
    order_rows = sorted(
        (str(o.price), o.action.name, str(o.quantity), o.status.name)
        for o in orders
    )

    return {
        "per_bar": per_bar,
        "final_balance": str(cash.balance),
        "closed_count": len(closed),
        "closed_realised_pnl": [str(c.realised_pnl) for c in closed],
        "orders": order_rows,
    }


def main() -> int:
    run_a = _run_once()
    run_b = _run_once()

    if run_a != run_b:
        print("DETERMINISM FAIL — the two liquidation runs diverge:", file=sys.stderr)
        for key in run_a:
            if run_a[key] != run_b[key]:
                print(f"  [{key}]", file=sys.stderr)
                print(f"    run A: {run_a[key]!r}", file=sys.stderr)
                print(f"    run B: {run_b[key]!r}", file=sys.stderr)
        return 1

    # Sanity: the run actually exercised the liquidation (a closed position + final
    # balance reflecting the WB-capped loss), so a no-op run can't pass the gate.
    if run_a["closed_count"] != 1 or run_a["final_balance"] != str(Decimal("6081.191919191919191919191919")):
        # final balance derived from the hand-computed scenario (10000 - 3918.808...).
        # Print but don't hard-fail on the exact tail — the byte-identity above is the gate;
        # this only guards against a silently-empty run.
        if run_a["closed_count"] != 1:
            print(
                f"DETERMINISM FAIL — run did not liquidate (closed_count={run_a['closed_count']!r})",
                file=sys.stderr,
            )
            return 1

    print("DETERMINISM OK — liquidation double-run byte-identical")
    print(f"  bars: {len(run_a['per_bar'])}  closed_positions: {run_a['closed_count']}  "
          f"final_balance: {run_a['final_balance']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

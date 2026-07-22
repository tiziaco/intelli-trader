#!/usr/bin/env python
"""Runnable paper-path worker for the live-paper engine (RUN-01, D-08).

A standalone bootstrap that constructs ``LiveTradingSystem``, wires the golden
SMA_MACD strategy + a single ``'simulated'``-exchange portfolio, and runs the
live-paper engine. The composition root is cleanly separable at a process
boundary (D-07 — option (b) architected as (c) with N=1); importing this module
has no side effects beyond the ``itrader`` package singletons.

  * D-02  replay entry : the golden CSV is replayed as confirm-gated ``ClosedBar``
                         dicts through the SAME Phase-3 feed seam an OKX provider
                         would drive (``set_bar_sink`` -> ``LiveBarFeed.update``).
  * D-03  drive        : the offline replay is SYNCHRONOUS, single-thread, single
                         process (``run_paper_replay``) — deterministic + CI-safe.
  * D-08  scope        : this worker builds ONLY the runnable entrypoint + the
                         start/stop/status lifecycle. It deliberately does NOT
                         build the Postgres command/status channel or any
                         web-framework wrapper — those move to Phase 5.
  * D-11  smoke        : the opt-in ``--mode okx`` branch exercises the daemon-
                         thread lifecycle against the REAL data arm. It performs
                         OKX network I/O, is a MANUAL smoke test, and is NEVER run
                         on the CI path (the default ``replay`` mode is offline).

Two ways to run:

    poetry run python scripts/run_live_paper.py --mode replay   # offline, CI-safe (default)
    poetry run python scripts/run_live_paper.py --mode okx       # manual live smoke (network)

Queue-only rule: this script constructs the system and reads result state AFTER
the run (``portfolio_handler.get_portfolio(...)`` + the pure ``reporting.frames``
builders). It never calls handler methods across domains during the run.
"""

import argparse
import time
from decimal import Decimal

from itrader.core.sizing import FractionOfCash, TradingDirection
from itrader.logger import get_itrader_logger
from itrader.reporting.frames import build_equity_curve, build_trade_log
from itrader.strategy_handler.strategies.SMA_MACD_strategy import SMAMACDStrategy
from itrader.trading_system.live_trading_system import LiveTradingSystem


# --- Pinned paper-worker configuration (parity anchor — verbatim golden literals) ---

CASH = 10_000                                    # D-04 (fees 0, slippage 0 — exchange defaults)
TICKER = "BTCUSD"                                # universe-member form (NOT the venue form)
TIMEFRAME = "1d"


def _build_paper_strategy() -> SMAMACDStrategy:
    """Construct the golden SMA_MACD strategy — literals copied verbatim (parity anchor).

    The sizing literal MUST be ``FractionOfCash(Decimal("0.95"))`` (string-path
    Decimal) and the direction ``LONG_ONLY`` so the paper run reproduces the
    backtest behavior by construction (D-01/D-09).
    """
    return SMAMACDStrategy(
        timeframe=TIMEFRAME,
        tickers=[TICKER],
        sizing_policy=FractionOfCash(Decimal("0.95")),
        direction=TradingDirection.LONG_ONLY,
        allow_increase=False,
    )


def _compose(system: LiveTradingSystem) -> int:
    """Wire the golden strategy + a single 'paper' portfolio onto the system.

    Shared by both modes so the composition is identical (the only divergence is
    the venue arm + the driver). Returns the portfolio id for post-run reads.
    """
    strategy = _build_paper_strategy()
    system.strategies_handler.add_strategy(strategy)
    # D-05/D-19: 'paper' is the ONE name for the simulated fill engine — the same
    # name the backtest portfolios carry — and it routes to the reused
    # SimulatedExchange (D-04). venue_name is passed explicitly.
    portfolio_id = system.portfolio_handler.add_portfolio(
        name="paper_pf",
        exchange="paper",
        venue_name="paper",
        cash=CASH,
    )
    strategy.subscribe_portfolio(portfolio_id)
    return portfolio_id


def _run_replay(logger) -> None:
    """Offline, synchronous paper run (D-03) — the CI-safe default worker path.

    Constructs the paper venue with the RELOCATED replay harness (TEST-01/D-18 — the
    replay apparatus lives in ``tests/`` now; production paper re-points to the OKX live
    feed, D-21), drives the golden dataset through the real replay -> feed -> queue seam
    via ``TestRunner`` (fail-fast BY DEFAULT, D-19), then reads result state and prints a
    short summary (trade count + final equity).
    """
    # The offline replay harness is TEST infrastructure now (tests/support). Put the repo
    # root on sys.path so this demo worker can import it standalone (sys.path[0] is the
    # scripts/ dir when run as `python scripts/run_live_paper.py`).
    import pathlib
    import sys

    repo_root = str(pathlib.Path(__file__).resolve().parent.parent)
    if repo_root not in sys.path:
        sys.path.insert(0, repo_root)
    from tests.support.replay_harness import TestRunner, build_paper_replay_system

    system, provider = build_paper_replay_system()
    portfolio_id = _compose(system)

    # Synchronous offline drive (D-02/D-03): replay -> feed.update -> BarEvent -> queue.
    TestRunner(system, provider).run()

    # --- Read result state AFTER the run (queue-only rule) ------------------
    portfolio = system.portfolio_handler.get_portfolio(portfolio_id)
    trades = build_trade_log(portfolio)
    equity = build_equity_curve(portfolio)

    trade_count = len(trades)
    final_equity = (
        equity["total_equity"].iloc[-1] if not equity.empty else None
    )

    logger.info(
        "Paper replay complete",
        trades=trade_count,
        equity_points=len(equity),
        final_equity=final_equity,
    )
    print(f"Paper replay complete — trades: {trade_count}, final equity: {final_equity}")


def _run_okx_smoke(logger) -> None:
    """Manual live smoke against the REAL data arm (D-11) — network-gated, NOT CI.

    Exercises the daemon-thread command surface: ``start()`` (returns bool, does
    not raise) -> brief poll -> ``stop(timeout=...)`` -> ``get_status()``. This
    branch performs OKX network I/O and is invoked ONLY when explicitly requested
    with ``--mode okx``; the default replay path and CI never reach it.
    """
    system = LiveTradingSystem.for_exchange("okx")
    _compose(system)

    started = system.start()
    logger.info("Live smoke start()", started=started)
    print(f"Live smoke start(): {started}")
    if not started:
        # WR-05: report the failed-start status but DO NOT early-return — fall
        # through to the try/finally so stop()'s unconditional connector teardown
        # (CR-01) always runs. The old bare return skipped stop(), leaking a
        # partially-connected OKX socket (authenticated session / ResourceWarning).
        print(f"Status: {system.get_status()}")

    try:
        # Let the daemon-thread stream drive briefly, then stop gracefully — only
        # meaningful when start() succeeded; skip the sleep on a failed start.
        if started:
            time.sleep(5.0)
    finally:
        stopped = system.stop(timeout=10.0)
        logger.info("Live smoke stop()", stopped=stopped)
        print(f"Live smoke stop(): {stopped}")
        print(f"Status: {system.get_status()}")


def main(mode: str = "replay") -> None:
    """Entrypoint: run the paper worker offline (``replay``) or the live smoke (``okx``).

    ``mode`` defaults to the offline replay path (D-03) — the runnable-worker
    demonstration of the paper path. ``okx`` is the opt-in manual live smoke (D-11).
    """
    logger = get_itrader_logger().bind(component="PaperWorker")

    if mode == "okx":
        _run_okx_smoke(logger)
    else:
        _run_replay(logger)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run the live-paper worker.")
    parser.add_argument(
        "--mode",
        choices=("replay", "okx"),
        default="replay",
        help="replay = offline CI-safe paper run (default); okx = manual live smoke (network, D-11)",
    )
    args = parser.parse_args()
    main(mode=args.mode)

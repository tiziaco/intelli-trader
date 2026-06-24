"""W2 synthetic scaling-sweep runner (PERF-BASELINE §7).

Sweeps ``n_symbols in {1, 10, 50}`` at a fixed ``n_bars`` with ONE trivial
LONG_ONLY strategy subscribed across all symbols. For each point: generate
seeded-GBM frames, write them to temp kline-schema CSVs (the safe route — they
flow through the same CsvPriceStore/feed path as the real data), run the
backtest, and capture wall-clock + peak memory. Prints a
(n_symbols, wall_clock_s, peak_mem_mb) table.

This is a SCALING test, not a realism test (realism lives in W1), so GBM + a
trivial strategy is sufficient. Determinism: seed 42 throughout. Profiling
(Scalene) is Step 2, NOT here.
"""

import argparse
import datetime as dt
import json
import sys
import tempfile
import time
import tracemalloc
from decimal import Decimal
from pathlib import Path
from typing import Any

import pandas as pd

from itrader.core.enums import TradingDirection
from itrader.core.sizing import FractionOfCash, SignalIntent
from itrader.strategy_handler.base import Strategy
from itrader.trading_system.backtest_trading_system import BacktestTradingSystem

from perf.workloads.synthetic import make_synthetic_ohlcv

_N_BARS = 3000
_N_SYMBOLS_SWEEP = [1, 10, 50]
_SEED = 42
_TIMEFRAME = "5m"

# The exact 12-column Binance-kline header CsvPriceStore parses.
_KLINE_HEADER = [
    "Open time", "Open", "High", "Low", "Close", "Volume",
    "Close time", "Quote asset volume", "Number of trades",
    "Taker buy base asset volume", "Taker buy quote asset volume", "Ignore",
]
_DT_FORMAT = "%Y-%m-%d %H:%M:%S.%f UTC"


class _TrivialBuyStrategy(Strategy):
    """Trivial LONG_ONLY scaling-test strategy: buy when the close rises.

    NOT a real strategy — a single cheap buy-on-condition so the sweep measures
    framework scaling in symbol count, not strategy compute.
    """

    name = "W2_trivial_buy"
    sizing_policy = FractionOfCash(Decimal("0.10"))
    direction = TradingDirection.LONG_ONLY
    max_positions = 1
    max_window: int = 3  # no indicators; pin a small fetch width

    def init(self) -> None:
        ...

    def generate_signal(self, ticker: str) -> SignalIntent | None:
        if self.bars.empty or len(self.bars) < 2:
            return None
        close = float(self.bars["close"].iloc[-1])
        prev = float(self.bars["close"].iloc[-2])
        if close > prev:
            return self.buy(ticker)
        return None


def _write_kline_csv(frame: pd.DataFrame, path: Path) -> None:
    """Serialize a canonical synthetic frame to a kline-schema CSV."""
    idx = frame.index
    out = pd.DataFrame()
    out["Open time"] = idx.strftime(_DT_FORMAT)
    out["Open"] = frame["open"].to_numpy()
    out["High"] = frame["high"].to_numpy()
    out["Low"] = frame["low"].to_numpy()
    out["Close"] = frame["close"].to_numpy()
    out["Volume"] = frame["volume"].to_numpy()
    close_time = (idx + pd.Timedelta(minutes=5) - pd.Timedelta(milliseconds=1))
    out["Close time"] = close_time.strftime(_DT_FORMAT)
    out["Quote asset volume"] = (frame["close"] * frame["volume"]).to_numpy()
    out["Number of trades"] = 0
    out["Taker buy base asset volume"] = 0.0
    out["Taker buy quote asset volume"] = 0.0
    out["Ignore"] = 0
    out[_KLINE_HEADER].to_csv(path, index=False)


def _wire_system(
    csv_paths: dict[str, str], start: str, end: str, tickers: list[str]
) -> BacktestTradingSystem:
    """Build a fresh, identically-wired BacktestTradingSystem for one pass.

    Both the timed pass (PASS 1) and the peak-mem pass (PASS 2) re-wire through
    this helper from the SAME csv_paths/start/end so the two passes measure the
    same engine work on the same seeded input — only the instrumentation differs.
    The wiring parameters (exchange="csv", cash, strategy/tickers, seed=_SEED via
    _TIMEFRAME-pinned synthetic frames) are identical across passes.
    """
    system = BacktestTradingSystem(
        exchange="csv", csv_paths=csv_paths,
        start_date=start, end_date=end, timeframe=_TIMEFRAME,
    )
    strategy = _TrivialBuyStrategy(timeframe=_TIMEFRAME, tickers=tickers)
    system.strategies_handler.add_strategy(strategy)
    pid = system.portfolio_handler.add_portfolio(
        user_id=1, name="W2_pf", exchange="csv", cash=Decimal("1000000"))
    strategy.subscribe_portfolio(pid)
    return system


def _run_point(n_symbols: int, tmpdir: Path) -> dict[str, Any]:
    """Generate, wire, run one sweep point; return timing + memory.

    D-13 part 2 — DE-TIMED two-pass structure. The synthetic frames/CSVs are
    generated ONCE (outside both passes) and reused. PASS 1 times ONLY
    ``system.run()`` with ``perf_counter`` and NO tracemalloc in the timed
    region, so ``wall_clock_s`` measures engine work clean (not ~19% harness
    allocation-tracking overhead). PASS 2 re-wires a fresh system from the same
    csv_paths/start/end (same seed=42) and captures peak memory under
    tracemalloc in a SEPARATE, un-timed pass.
    """
    # Synthetic generation — ONCE, outside any measured region; reused by both passes.
    frames = make_synthetic_ohlcv(_N_BARS, n_symbols, seed=_SEED)
    csv_paths: dict[str, str] = {}
    start = None
    end = None
    for ticker, frame in frames.items():
        path = tmpdir / f"{ticker}_5m.csv"
        _write_kline_csv(frame, path)
        csv_paths[ticker] = str(path)
        if start is None:
            start = frame.index[0].strftime("%Y-%m-%d")
            end = (frame.index[-1] + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    tickers = list(frames.keys())

    # WR-02 guard: start/end are only assigned inside the per-frame loop, so an
    # empty frames dict would leave them None and pass None into _wire_system's
    # typed `start: str, end: str` signature (latent TypeError/silent misbehavior).
    # Currently unreachable (_N_SYMBOLS_SWEEP is always non-empty) — fail loudly
    # rather than carry the None forward.
    if start is None or end is None:
        raise RuntimeError("W2 sweep produced no frames — cannot wire the system")

    # PASS 1 — clean wall-clock: NO tracemalloc anywhere in the timed region.
    system = _wire_system(csv_paths, start, end, tickers)
    t0 = time.perf_counter()
    system.run(print_summary=False)
    wall_clock_s = time.perf_counter() - t0

    # PASS 2 — peak memory: fresh re-wired system (same seed/input), instrumented.
    mem_system = _wire_system(csv_paths, start, end, tickers)
    tracemalloc.start()
    mem_system.run(print_summary=False)
    _current, peak_bytes = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    peak_mem_mb = peak_bytes / (1024 * 1024)

    return {
        "n_symbols": n_symbols,
        "wall_clock_s": wall_clock_s,
        "peak_mem_mb": peak_mem_mb,
    }


def run_w2() -> list[dict[str, Any]]:
    """Run the {1,10,50}-symbol sweep; print the scaling table."""
    points: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="w2_sweep_") as td:
        tmpdir = Path(td)
        for n in _N_SYMBOLS_SWEEP:
            print(f"W2 sweep: n_symbols={n}, n_bars={_N_BARS} ...")
            points.append(_run_point(n, tmpdir))

    print("\n===== W2 SCALING SWEEP =====")
    print(f"(n_bars={_N_BARS}, seed={_SEED})")
    print(f"{'n_symbols':>10} {'wall_clock_s':>14} {'peak_mem_mb':>13}")
    for p in points:
        print(f"{p['n_symbols']:>10} {p['wall_clock_s']:>14.3f} "
              f"{p['peak_mem_mb']:>13.2f}")
    print("============================\n")
    return points


def _to_w2_baseline_schema(points: list[dict[str, Any]]) -> dict[str, Any]:
    """Build the W2 committed-baseline payload from a run_w2() points list.

    Mirrors the W1 envelope (`run_w1_benchmark._to_baseline_schema`) but keys the
    metric on the 50-symbol sweep point — that is the most W2-visible scaling
    number gate (b) for this phase is judged on (D-05). The full {1,10,50} points
    list is carried verbatim so the standing reference also seeds Phase 5.
    """
    p50 = next(p for p in points if p["n_symbols"] == 50)
    return {
        "schema_version": 1,
        "frozen_at": dt.date.today().isoformat(),
        "metric": {
            "wall_clock_s_at_50": round(p50["wall_clock_s"], 2),
            "peak_mem_mb_at_50": round(p50["peak_mem_mb"], 2),
        },
        "sweep": {"n_symbols": _N_SYMBOLS_SWEEP, "n_bars": _N_BARS, "seed": _SEED},
        "points": points,
    }


def _write_w2_baseline(points: list[dict[str, Any]], out_path: str) -> None:
    """Freeze a sweep as the committed W2-BASELINE.json (mirrors _write_baseline)."""
    with open(out_path, "w") as fh:
        json.dump(_to_w2_baseline_schema(points), fh, indent=2)
        fh.write("\n")


def _check_w2(
    points: list[dict[str, Any]],
    baseline_path: str,
    min_improvement_pct: float = 10.0,
) -> int:
    """Gate (b) for this W2-dominant phase. The sense is INVERTED vs W1's soft
    guard: W1 FAILS only on a slowdown beyond a band, whereas this gate REQUIRES
    the win — PASS (return 0) iff the 50-symbol wall-clock improved by at least
    ``min_improvement_pct`` against the frozen baseline. ALWAYS print the line.

    WR-02 soft guard (carried from run_w1_benchmark._check_regression:208-211): a
    zeroed/malformed/hand-edited baseline (non-positive base50) must degrade
    gracefully — print a message and return 1, never raise a ZeroDivisionError.
    """
    with open(baseline_path) as fh:
        base = json.load(fh)
    base50 = base["metric"]["wall_clock_s_at_50"]
    now50 = next(p for p in points if p["n_symbols"] == 50)["wall_clock_s"]
    if base50 <= 0:
        print(f"PERF GUARD: baseline wall_clock_s_at_50 is {base50} — refusing to "
              "compute a delta against a zero/invalid baseline")
        return 1
    impr = (base50 - now50) / base50 * 100.0
    print(f"W2@50 {now50:.2f}s  improvement {impr:+.1f}%  (baseline {base50:.2f}s)")
    if impr < min_improvement_pct:
        print(f"PERF GATE (b): improvement {impr:+.1f}% < required "
              f"{min_improvement_pct:.1f}% at 50 symbols — gate (b) FAILED")
        return 1
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="W2 synthetic scaling sweep")
    parser.add_argument("--json", action="store_true",
                        help="emit the scaling points as JSON (machine-readable)")
    parser.add_argument("--check", action="store_true",
                        help="compare vs W2-BASELINE.json; gate (b) REQUIRES a "
                             ">=10%% wall-clock win at 50 symbols (inverted guard)")
    parser.add_argument("--baseline-out", metavar="PATH",
                        help="freeze: write the sweep as the committed W2 baseline JSON")
    args = parser.parse_args()
    # IN-01 (mirrors run_w1_benchmark): --baseline-out + --check together would
    # re-check a run against the baseline it JUST wrote (impr ~0%, a meaningless
    # self-comparison that can never reach the >=10% bar). The Makefile never
    # combines them; warn loudly so an ad-hoc invocation does not trust it.
    if args.baseline_out and args.check:
        print("PERF WARNING: --baseline-out and --check together compare a run "
              "against the baseline it just wrote (improvement ~0%) — the gate "
              "cannot pass. Run --check against a PREVIOUSLY frozen baseline.")
    points = run_w2()                       # human table prints by default (D-06)
    if args.json:
        print(json.dumps(points, indent=2))
    if args.baseline_out:
        _write_w2_baseline(points, args.baseline_out)
    if args.check:
        sys.exit(_check_w2(points, "perf/results/W2-BASELINE.json"))


if __name__ == "__main__":
    main()

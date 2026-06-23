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
import json
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


def _run_point(n_symbols: int, tmpdir: Path) -> dict[str, Any]:
    """Generate, wire, run one sweep point; return timing + memory."""
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

    system = BacktestTradingSystem(
        exchange="csv", csv_paths=csv_paths,
        start_date=start, end_date=end, timeframe=_TIMEFRAME,
    )
    strategy = _TrivialBuyStrategy(timeframe=_TIMEFRAME, tickers=list(frames.keys()))
    system.strategies_handler.add_strategy(strategy)
    pid = system.portfolio_handler.add_portfolio(
        user_id=1, name="W2_pf", exchange="csv", cash=Decimal("1000000"))
    strategy.subscribe_portfolio(pid)

    tracemalloc.start()
    t0 = time.perf_counter()
    system.run(print_summary=False)
    wall_clock_s = time.perf_counter() - t0
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


def main() -> None:
    parser = argparse.ArgumentParser(description="W2 synthetic scaling sweep")
    parser.add_argument("--json", action="store_true",
                        help="emit the scaling points as JSON (machine-readable)")
    args = parser.parse_args()
    points = run_w2()                       # human table prints by default (D-06)
    if args.json:
        print(json.dumps(points, indent=2))


if __name__ == "__main__":
    main()

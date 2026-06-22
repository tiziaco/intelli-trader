"""Pair flagship STABILITY snapshot + determinism double-run (PAIR-01, Wave 3).

This is a STABILITY lock, NOT a correctness oracle (D-11). The ETH/BTC pair-trading
run output is regression-locked as a GENERATED snapshot (not hand-verified) — a
two-leg market-neutral strategy partially cancels its own sign errors, so it is a
weak correctness oracle. The correctness oracle for this milestone is the crafted
short/leveraged/liquidation scenarios cross-validated under XVAL-01 (Phase 4), NOT
pair trading. This phase does NOT re-baseline the SMA_MACD golden master
(tests/golden/{trades,equity}.csv is untouched); the pair snapshot lives in its
own NEW artifact directory tests/golden/pair/.

Behavior (D-03 / PAIR-01): the ETH/BTC pair flagship runs end-to-end through the
full backtest run path — both a long leg and a short leg settle through the
Phase 2-4 accounting core (margin reservation, short PnL, borrow carry, liquidation
if triggered) with NO new correctness branches. The run is wired via
``csv_paths={ETHUSD, BTCUSD}`` with ``allow_short_selling=True`` and
``enable_margin=True`` over 2021-01-01..2026-01-08 (D-10). Legs left open at run
end (z not reverted) stay open and are marked-to-market in final equity — the
existing engine behavior, NO run-end force-close, NO new code (D-15).

Diff mechanic (Don't Hand-Roll, mirrors test_backtest_oracle.py): on the first run
the snapshot is absent, so it is GENERATED to tests/golden/pair/{trades,equity}.csv
from the run output and the test passes; subsequent runs load BOTH the fresh output
and the committed snapshot to pandas and ``pdt.assert_frame_equal(...,
check_exact=True, check_like=True)`` on the deterministic columns (trades keyed by
entry/exit/side, equity by timestamp/total_equity).

This test carries the ``integration`` marker AUTOMATICALLY via the
``tests/integration/`` path (folder-derived TYPE auto-marking) — markers are NOT
hand-added here.
"""

import io
import pathlib

import pandas as pd
import pandas.testing as pdt

from itrader.reporting.frames import (
    EQUITY_COLUMNS,
    TRADE_COLUMNS,
    build_equity_curve,
    build_trade_log,
)
from itrader.strategy_handler.strategies.eth_btc_pair_strategy import (
    EthBtcPairStrategy,
)
from itrader.trading_system.backtest_trading_system import BacktestTradingSystem

# --- Pinned flagship run configuration (D-10) -------------------------------
_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
_ETH_CSV = _REPO_ROOT / "data" / "ETHUSD_1d_ohlcv.csv"
_BTC_CSV = _REPO_ROOT / "data" / "BTCUSD_1d_ohlcv_2018_2026.csv"
_START_DATE = "2021-01-01"
_END_DATE = "2026-01-08"
# Starting capital sized so a single UNLEVERED fixed-1-ETH / β-BTC pair always fits
# the margin lock with drawdown headroom across the window: the BTC short leg notional
# peaks near 0.53 × $125k ≈ $66k + the ~$4.8k ETH leg ≈ $71k per pair; $500k gives
# comfortable headroom so the run never trips the solvency assertion mid-run (it is a
# fail-fast backtest, so an under-capitalised run aborts rather than completing). No
# engine change — β-weighting and the Phase 2-4 accounting core are untouched.
_CASH = 500_000
_TIMEFRAME = "1d"

# NEW snapshot directory — explicitly NOT the SMA_MACD oracle (tests/golden/) (A5, D-11).
_SNAPSHOT_DIR = _REPO_ROOT / "tests" / "golden" / "pair"

# Deterministic columns to diff (mirrors the oracle test). Trades keyed by
# (entry_date, exit_date, side); equity by (timestamp, total_equity).
_TRADE_KEY_COLUMNS = ["entry_date", "exit_date", "side"]
_EQUITY_KEY_COLUMNS = ["timestamp", "total_equity"]

# Non-trivial round-trip lower bound (D-06 success criterion). A3 measured 48-72
# entry crossings over the window; assert >= 20 round trips to avoid brittleness.
_MIN_ROUND_TRIPS = 20


def _build_flagship_system() -> tuple[BacktestTradingSystem, int]:
    """Wire the ETH/BTC pair flagship: csv_paths ETH+BTC, short + margin enabled.

    Mirrors the partial_cover short+margin wiring (tests/e2e/partial_cover):
    the strategy-handler flags MUST be set BEFORE ``add_strategy`` (the LONG_SHORT
    registration gate, T-06-10), and the portfolio / admission / validator margin
    flags are set before the run. The Universe (ETHUSD + BTCUSD instruments) is
    derived from the data by the runner during ``run()`` — no manual set_universe.
    """
    system = BacktestTradingSystem(
        exchange="csv",
        csv_paths={"ETHUSD": _ETH_CSV, "BTCUSD": _BTC_CSV},
        start_date=_START_DATE,
        end_date=_END_DATE,
        timeframe=_TIMEFRAME,
    )

    # Registration gate: a LONG_SHORT pair strategy is admitted ONLY when BOTH
    # short selling AND margin are enabled on the handler (strategies_handler:361).
    sh = system.strategies_handler
    sh._allow_short_selling = True
    sh._enable_margin = True

    strategy = EthBtcPairStrategy(timeframe=_TIMEFRAME)
    sh.add_strategy(strategy)

    portfolio_id = system.portfolio_handler.add_portfolio(
        user_id=1, name="pair_flagship_pf", exchange="csv", cash=_CASH,
    )
    strategy.subscribe_portfolio(portfolio_id)

    # Portfolio trading-rules: enable margin + short selling so the short leg
    # settles through the lock-and-settle accounting core (Phase 2-4).
    portfolio = system.portfolio_handler.get_portfolio(portfolio_id)
    portfolio.config = portfolio.config.model_copy(update={
        "trading_rules": portfolio.config.trading_rules.model_copy(update={
            "enable_margin": True,
            "allow_short_selling": True,
        })})

    # Admission + validator margin flags (the short leg must clear admission).
    order_manager = system.order_handler.order_manager
    order_manager.admission_manager._enable_margin = True
    order_manager.order_validator.enable_margin = True

    return system, portfolio_id


def _run_flagship() -> tuple[pd.DataFrame, pd.DataFrame]:
    """Run the flagship end-to-end and return (trades, equity) frames.

    Reads result state AFTER the run (queue-only rule): the closed-position trade
    log and the metrics-snapshot equity curve from the single portfolio.
    """
    system, portfolio_id = _build_flagship_system()
    system.run(print_summary=False)
    portfolio = system.portfolio_handler.get_portfolio(portfolio_id)
    trades = build_trade_log(portfolio)[TRADE_COLUMNS]
    equity = build_equity_curve(portfolio)[EQUITY_COLUMNS]
    return trades, equity


def _csv_roundtrip(frame: pd.DataFrame) -> pd.DataFrame:
    """Serialize a fresh frame to CSV bytes and read it back (oracle pattern).

    The committed snapshot is loaded via ``pd.read_csv`` (everything parsed as the
    CSV-stored repr), so the FRESH frame must go through the SAME serialization to
    get identical dtypes — otherwise a tz-aware datetime column (fresh) vs an object
    column (read back) or a Decimal ``0E-16`` repr vs ``0.0`` trips the exact
    comparison on a value that IS identical on disk. Mirrors test_backtest_oracle.py,
    which reads BOTH sides from CSV. This is the snapshot-diff seam, not a byte-compare.
    """
    return pd.read_csv(io.StringIO(frame.to_csv(index=False)))


def _sorted(frame: pd.DataFrame, keys: list[str]) -> pd.DataFrame:
    return frame.sort_values(keys).reset_index(drop=True)


def test_pair_flagship_snapshot_matches() -> None:
    """Full ETH/BTC run output matches the committed STABILITY snapshot (NOT an oracle, D-11).

    First run (snapshot absent): GENERATE tests/golden/pair/{trades,equity}.csv from
    the run output and pass. Subsequent runs: load both the fresh output and the
    committed snapshot and assert frame-equal on the deterministic columns (exact,
    sorted by a stable key). Asserts a non-trivial round-trip count and that BOTH a
    long (BUY) leg and a short (SELL) leg were exercised (PAIR-01).
    """
    fresh_trades, fresh_equity = _run_flagship()

    # Non-trivial round trips (D-06): the run must produce real activity.
    assert len(fresh_trades) >= _MIN_ROUND_TRIPS, (
        f"round-trip count {len(fresh_trades)} below the non-trivial lower bound "
        f"{_MIN_ROUND_TRIPS} (D-06)"
    )

    # PAIR-01: BOTH legs exercised — the closed-position trade log shows a SHORT
    # and a LONG side (the `side` column is the position side; the flagship
    # demonstration is that shorts settle end-to-end through the accounting core).
    sides = set(fresh_trades["side"].astype(str))
    assert "SHORT" in sides, f"no short leg in the trade log; sides={sides}"
    assert "LONG" in sides, f"no long leg in the trade log; sides={sides}"

    trades_path = _SNAPSHOT_DIR / "trades.csv"
    equity_path = _SNAPSHOT_DIR / "equity.csv"

    if not trades_path.exists() or not equity_path.exists():
        # First run: GENERATE the STABILITY snapshot (NOT a hand-verified oracle).
        _SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
        fresh_trades.to_csv(trades_path, index=False)
        fresh_equity.to_csv(equity_path, index=False)
        return

    # Subsequent runs: diff the fresh output against the committed snapshot on the
    # deterministic columns (exact, sorted by a stable key) — NOT a byte-compare.
    snapshot_trades = pd.read_csv(trades_path)
    snapshot_equity = pd.read_csv(equity_path)

    fresh_trades_sorted = _sorted(_csv_roundtrip(fresh_trades), _TRADE_KEY_COLUMNS)
    snapshot_trades_sorted = _sorted(snapshot_trades, _TRADE_KEY_COLUMNS)
    assert len(fresh_trades_sorted) == len(snapshot_trades_sorted), (
        f"trade count drift: fresh={len(fresh_trades_sorted)} "
        f"snapshot={len(snapshot_trades_sorted)}"
    )
    pdt.assert_frame_equal(
        fresh_trades_sorted[_TRADE_KEY_COLUMNS],
        snapshot_trades_sorted[_TRADE_KEY_COLUMNS],
        check_exact=True,
        check_like=True,
    )

    fresh_equity_sorted = _sorted(_csv_roundtrip(fresh_equity), _EQUITY_KEY_COLUMNS)
    snapshot_equity_sorted = _sorted(snapshot_equity, _EQUITY_KEY_COLUMNS)
    assert len(fresh_equity_sorted) == len(snapshot_equity_sorted), (
        f"equity point count drift: fresh={len(fresh_equity_sorted)} "
        f"snapshot={len(snapshot_equity_sorted)}"
    )
    pdt.assert_frame_equal(
        fresh_equity_sorted[_EQUITY_KEY_COLUMNS],
        snapshot_equity_sorted[_EQUITY_KEY_COLUMNS],
        check_exact=True,
        check_like=True,
    )


def test_pair_flagship_determinism_double_run() -> None:
    """Two runs of the ETH/BTC flagship are byte-identical (determinism, D-11).

    Run the flagship twice in-process (fresh system each run, same seed/clock) and
    assert the two outputs (trades + equity) are identical on every column. β enters
    the Decimal domain only via to_money so the run is reproducible (Pitfall 4); no
    new nondeterminism is introduced.
    """
    trades_a, equity_a = _run_flagship()
    trades_b, equity_b = _run_flagship()

    # Byte-identical on the serialized snapshot form, ALL columns (the stronger
    # determinism claim — not just the deterministic key columns). Both runs build
    # fresh frames with identical dtypes; the CSV roundtrip locks the on-disk repr.
    pdt.assert_frame_equal(
        _sorted(_csv_roundtrip(trades_a), _TRADE_KEY_COLUMNS),
        _sorted(_csv_roundtrip(trades_b), _TRADE_KEY_COLUMNS),
        check_exact=True,
    )
    pdt.assert_frame_equal(
        _sorted(_csv_roundtrip(equity_a), _EQUITY_KEY_COLUMNS),
        _sorted(_csv_roundtrip(equity_b), _EQUITY_KEY_COLUMNS),
        check_exact=True,
    )

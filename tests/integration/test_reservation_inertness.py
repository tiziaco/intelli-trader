"""D-14 mandated golden-run reservation inertness trace (Plan 05-06, M4-01).

Value-preservation PROOF for the admission reservation gate: the golden run is
long-only, fees 0, sizing 0.95 x cash — so the gate must be provably INERT:

  (a) reserve NEVER rejects: at every reserve call the requested amount is
      <= the available balance at that instant,
  (b) reservations are fully released — ``reserved_balance == 0`` after the
      run completes (T-05-17: no stuck reservations),
  (c) the produced trade log is IDENTICAL to the committed
      ``tests/golden/trades.csv`` (read, never regenerated).

Reservations touch ONLY ``available_balance`` — never balance/equity/metrics
(D-08) — so they are invisible to the byte-exact oracle, which stays asserted
separately in ``test_backtest_oracle.py``.

Harness: the same pinned construction as ``scripts/run_backtest.py::main``
(dataset/window/cash/params constants imported from the committed generator),
with ``PortfolioHandler.reserve`` wrapped on the instance to record
``(amount, available_balance)`` pairs per call.

Markers: ``integration`` + ``slow`` arrive AUTOMATICALLY via the
``tests/integration/`` path (root-conftest folder-derived TYPE auto-marking) —
they are NOT hand-added here (strict-markers).
"""

import importlib.util
import pathlib
from decimal import Decimal

import pandas as pd
import pandas.testing as pdt
import pytest

# Repo layout: this file lives at <repo>/tests/integration/, so the repo root is
# two parents up — same anchoring as test_backtest_oracle.py.
_REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
_RUN_BACKTEST = _REPO_ROOT / "scripts" / "run_backtest.py"
_GOLDEN_DIR = _REPO_ROOT / "tests" / "golden"

_TRADE_KEY_COLUMNS = ["entry_date", "exit_date", "side"]


def _load_run_backtest_module():
    """Import scripts/run_backtest.py as a module (it is not on the package path)."""
    if not _RUN_BACKTEST.exists():
        pytest.fail(f"oracle generator missing: {_RUN_BACKTEST}")
    spec = importlib.util.spec_from_file_location("run_backtest_inertness", _RUN_BACKTEST)
    assert spec is not None and spec.loader is not None, f"cannot load {_RUN_BACKTEST}"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def traced_run(tmp_path_factory):
    """Run the pinned golden backtest ONCE with reserve-call recording.

    Reuses the oracle generator's pins (dataset/window/cash/params) by importing
    its constants, constructs the identical system, and wraps
    ``PortfolioHandler.reserve`` on the INSTANCE so every admission reservation
    records ``(amount, available_balance_at_that_instant)`` before delegating.
    """
    if not _GOLDEN_DIR.exists():
        pytest.skip("tests/golden/ not frozen — inertness trace needs the committed oracle")

    module = _load_run_backtest_module()

    from itrader.strategy_handler.SMA_MACD_strategy import SMA_MACD_strategy
    from itrader.trading_system.backtest_trading_system import TradingSystem

    system = TradingSystem(
        exchange="csv",
        start_date=module.START_DATE,
        end_date=module.END_DATE,
    )
    strategy = SMA_MACD_strategy(timeframe=module.TIMEFRAME, tickers=[module.TICKER])
    system.strategies_handler.add_strategy(strategy)
    portfolio_id = system.portfolio_handler.add_portfolio(
        user_id=1,
        name="oracle_pf",
        exchange="csv",
        cash=module.CASH,
    )
    strategy.subscribe_portfolio(portfolio_id)

    # --- D-14 trace probe: wrap reserve on the handler INSTANCE -------------
    ptf_handler = system.portfolio_handler
    original_reserve = ptf_handler.reserve
    recorded: list[tuple[Decimal, Decimal]] = []

    def recording_reserve(pid, order_id, amount):
        available = ptf_handler.available_cash(pid)
        recorded.append((amount, available))
        original_reserve(pid, order_id, amount)

    # Instance-attribute shadowing: OrderManager calls
    # self.portfolio_handler.reserve(...) on this same object.
    ptf_handler.reserve = recording_reserve  # type: ignore[method-assign]

    system.run(print_summary=False)

    portfolio = ptf_handler.get_portfolio(portfolio_id)

    # Round-trip the fresh trade log through CSV with the SAME pinned float
    # format and column order as the committed golden, so the identity
    # comparison is repr-stable. As of M5b re-freeze 1 (plan 07-07) the golden
    # header carries the D-17 slippage columns — attach them post-hoc exactly
    # as the generator's main() does, from the store's close series.
    trades = module.build_trade_log(portfolio)
    closes = system.store.read_bars(module.TICKER)["close"]
    trades = module.attach_slippage(trades, closes)
    trades_path = tmp_path_factory.mktemp("inertness") / "trades.csv"
    trades[module.TRADE_COLUMNS + module.SLIPPAGE_COLUMNS].to_csv(
        trades_path, index=False, float_format=module.FLOAT_FORMAT
    )

    return {
        "recorded": recorded,
        "portfolio": portfolio,
        "fresh_trades": pd.read_csv(trades_path),
        "golden_trades": pd.read_csv(_GOLDEN_DIR / "trades.csv"),
    }


def test_reserve_never_rejects_in_golden_run(traced_run):
    """(a) The gate is provably inert: every reserve fits the available balance.

    Golden run sizing is 0.95 x available cash with fees 0, so each
    reservation (price x quantity = 0.95 x cash) must be <= available at the
    instant of the call — the gate can never reject on this path (D-14).
    """
    recorded = traced_run["recorded"]
    assert recorded, "golden run produced no reservations — gate not exercised"
    violations = [
        (amount, available) for amount, available in recorded if amount > available
    ]
    assert violations == [], (
        f"reserve would have rejected {len(violations)} time(s): {violations[:5]}"
    )


def test_reserved_balance_zero_after_run(traced_run):
    """(b) Every reservation was released: reserved == 0 post-run (T-05-17)."""
    portfolio = traced_run["portfolio"]
    assert portfolio.cash_manager.reserved_balance == Decimal("0")


def test_trade_log_identical_to_golden(traced_run):
    """(c) The trade log is byte-identical to the committed golden (D-08).

    Reservations only ever touch available_balance — the trade log (entry/exit
    timing, quantities, PnL) must be exactly the frozen oracle's.
    """
    fresh = traced_run["fresh_trades"].sort_values(_TRADE_KEY_COLUMNS).reset_index(drop=True)
    golden = traced_run["golden_trades"].sort_values(_TRADE_KEY_COLUMNS).reset_index(drop=True)
    assert len(fresh) == len(golden), (
        f"trade count drift: fresh={len(fresh)} golden={len(golden)}"
    )
    pdt.assert_frame_equal(fresh, golden, check_exact=True, check_like=True)

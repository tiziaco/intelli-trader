"""FROZEN short-with-carry e2e (SHORT-03 / CARRY-01) — Phase 3 (Plan 03-06).

============================ FROZEN — ACCOUNTING-CORE GOLDEN ==========================
FREEZE PROVENANCE (D-10/D-12): frozen as part of the single accounting-core golden at
the owner-gated 04-05 sign-off — Approved-by: tiziaco (tiziano.iaco@gmail.com),
2026-06-16. The freeze set is ALL parked P2/P3 scenarios (levered_long, short_roundtrip,
short_carry, partial_cover) + the new P4 liquidation scenarios (forced_liq_long,
forced_liq_short, levered_long_into_liquidation) frozen as ONE accounting-core golden
(cross-validated vs backtesting.py + backtrader; see tests/golden/CROSS-VALIDATION-ACCOUNTING.md).
Every number asserted below is a HAND-COMPUTED literal with the arithmetic shown
inline. This test does NOT use the golden-diff
harness — its load-bearing assertions are the per-bar BORROW_INTEREST carry debits and
the carry-eroded balance, which the trades/equity/summary golden CSVs do not capture.
It drives the engine's real SIGNAL -> ORDER -> FILL -> PORTFOLIO path and asserts on
live cash / ledger state. It also re-runs the WHOLE scenario and asserts the two runs
are BYTE-IDENTICAL (the determinism double-run gate — carry must derive from the bar's
BUSINESS time, never the wall clock).
=====================================================================================

What it exercises
-----------------
* CARRY-01 — every HELD-short bar accrues borrow interest
             ``days × close × |size| × borrow_rate / 365`` and debits realized cash
             via a first-class ``BORROW_INTEREST`` CashOperation (D-03/D-08 — carry is
             a SEPARATE ledger line, NEVER folded into Position.realised_pnl).
* Determinism — a second full run produces byte-identical carry amounts AND
                timestamps (carry rides the bar's BUSINESS time, not the wall clock).

Discretion values (oracle-dark — synthetic instrument, NEVER BTCUSD)
--------------------------------------------------------------------
``CARRYUSD`` declares ``borrow_rate = Decimal("0.10")`` (10% annualized — a realistic
crypto borrow cost; planner/owner discretion, oracle-dark), ``maintenance_margin_rate
= Decimal("0.01")``, ``max_leverage = Decimal("10")``. The short is UNLEVERED.

================================ HAND COMPUTATION ================================

Price series (``bars.csv`` — daily, flat 100 so each held bar carries the same):

    bar  date         close
    0    2020-01-01   100
    1    2020-01-02   100    <- SELL-to-open decided (SHORT_ONLY, FixedQuantity 10)
    2    2020-01-03   100    <- SELL fills NEXT bar at close 100; SHORT opened, entry=bar 2
    3    2020-01-04   100    <- HELD bar 1: carry debit #1
    4    2020-01-05   100    <- HELD bar 2: carry debit #2
    5    2020-01-06   100    <- HELD bar 3: carry debit #3

The accrual marker seeds from the position entry (the fill on 2020-01-03), so NO carry
accrues on the opening bar; each SUBSEQUENT held bar (4 / 5 / 6) accrues exactly one
day (the daily-grid gap is exactly 1 day).

Per-bar carry (days = 1, close = 100, |size| = 10, rate = 0.10):
    carry = days × close × |size| × rate / 365
          = 1 × 100 × 10 × 0.10 / 365
          = 100 / 365
          = 0.2739726027397260273972602740   (Decimal full precision)

Three held bars (4, 5, 6) → THREE carry debits:
    Σ carry = 3 × (100 / 365) = 0.8219178082191780821917808220   (the engine debits
        three INDEPENDENT full-precision 100/365 debits and sums the ledger; it never
        forms 300/365, which would round differently at the 28th Decimal digit)
    final balance = 100_000 − Σ carry = 99_999.1780821917808219178082...

================================ END HAND COMPUTATION ================================
"""

import pathlib
from decimal import Decimal

from itrader.config import PortfolioConfig, deep_merge, get_portfolio_preset
from itrader.core.enums import Side
from itrader.core.enums.order import OrderType
from itrader.core.enums.portfolio import CashOperationType
from itrader.core.enums.trading import TradingDirection
from itrader.core.instrument import Instrument
from itrader.core.sizing import FixedQuantity, SignalIntent
from itrader.strategy_handler.base import Strategy
from itrader.trading_system.backtest_trading_system import BacktestTradingSystem
from itrader.universe import Universe

HERE = pathlib.Path(__file__).resolve().parent

_TICKER = "CARRYUSD"
_CASH = 100_000
_QTY = Decimal("10")
_BORROW_RATE = Decimal("0.10")           # 10% annualized (oracle-dark discretion)
_PORTFOLIO_MAX_LEVERAGE = Decimal("5")

# Hand-computed per-bar carry: days × close × |size| × rate / 365 (full precision).
_CARRY_PER_BAR = (
    Decimal("1") * Decimal("100") * _QTY * _BORROW_RATE / Decimal("365")
)


class _ShortCarryStrategy(Strategy):
    """SHORT_ONLY: SELL-to-open on 2020-01-02 and HOLD (no cover) — every held bar
    accrues borrow interest. Drives the NORMAL fan-out (no injected events)."""

    name = "short_carry"
    max_window = 100
    warmup = 0
    sizing_policy = FixedQuantity(qty=_QTY)
    direction = TradingDirection.SHORT_ONLY

    def __init__(self, timeframe: str, tickers: list[str]) -> None:
        super().__init__(timeframe=timeframe, tickers=list(tickers))

    def generate_signal(self, ticker: str) -> SignalIntent | None:
        date = self.now.tz_convert("UTC").strftime("%Y-%m-%d")
        if date == "2020-01-02":
            return SignalIntent(ticker=ticker, action=Side.SELL, order_type=OrderType.MARKET)
        return None


def _carry_instrument() -> Instrument:
    return Instrument(
        symbol=_TICKER,
        price_precision=Decimal("0.01"),
        quantity_precision=Decimal("0.00000001"),
        min_order_size=None,
        maintenance_margin_rate=Decimal("0.01"),
        max_leverage=Decimal("10"),
        settles_funding=False,
        borrow_rate=_BORROW_RATE,
    )


def _build_carry_system():
    system = BacktestTradingSystem(
        exchange="csv",
        csv_paths={_TICKER: HERE / "bars.csv"},
        start_date="2020-01-01",
        end_date="2020-01-06",
    )
    sh = system.strategies_handler
    sh._allow_short_selling = True
    sh._enable_margin = True
    strategy = _ShortCarryStrategy(timeframe="1d", tickers=[_TICKER])
    sh.add_strategy(strategy)
    portfolio_id = system.portfolio_handler.add_portfolio(
        # 01-03 D-03 (sibling 01-03b finding): the account leaf is selected at
        # CONSTRUCTION from enable_margin; the post-construction config swap below
        # refines the rest but no longer rebuilds the leaf — so margin must be on
        # in the constructor config to get a SimulatedMarginAccount.
        name="short_carry_pf", exchange="csv", cash=_CASH,
        portfolio_config=PortfolioConfig.model_validate(deep_merge(
            get_portfolio_preset("default").model_dump(),
            {"trading_rules": {"enable_margin": True}})))
    strategy.subscribe_portfolio(portfolio_id)

    portfolio = system.portfolio_handler.get_portfolio(portfolio_id)
    portfolio.config = portfolio.config.model_copy(update={
        "trading_rules": portfolio.config.trading_rules.model_copy(update={
            "enable_margin": True,
            "allow_short_selling": True,
            "max_leverage": _PORTFOLIO_MAX_LEVERAGE,
        })})
    order_manager = system.order_handler.order_manager
    order_manager.admission_manager._enable_margin = True
    order_manager.admission_manager._portfolio_max_leverage = _PORTFOLIO_MAX_LEVERAGE
    order_manager.order_validator.enable_margin = True

    system.runner._initialise_backtest_session()
    universe = Universe(members=[_TICKER], instrument_map={_TICKER: _carry_instrument()})
    system.execution_handler.exchanges["simulated"].set_universe(universe)
    system.order_handler.set_universe(universe)
    system.portfolio_handler.set_universe(universe)

    return system, portfolio, portfolio_id


def _run_once():
    """Drive a full run and return the BORROW_INTEREST ledger (amount, timestamp,
    balance_after) + the final balance — the determinism double-run compares these."""
    system, portfolio, portfolio_id = _build_carry_system()
    engine = system.engine
    cash = portfolio.account
    for time_event in engine.time_generator:
        engine.clock.set_time(time_event.time)
        engine.global_queue.put(time_event)
        engine.event_handler.process_events()
        for active in system.portfolio_handler.get_active_portfolios():
            active.record_metrics(time_event.time)
    carry_ops = [
        (op.amount, op.timestamp, op.balance_after)
        for op in cash.get_cash_operations(
            operation_type=CashOperationType.BORROW_INTEREST)
    ]
    return carry_ops, cash.balance


def test_short_carry_scenario_parked():
    """PARKED multi-bar held-short carry: three per-bar BORROW_INTEREST debits of
    ``100 / 365`` each; the balance eroded by the cumulative carry; a determinism
    double-run is BYTE-IDENTICAL. PARKED — frozen as golden ONLY at P4/XVAL-01."""
    carry_ops, final_balance = _run_once()

    # THREE held bars (4 / 5 / 6) → three carry debits (none on the opening bar).
    assert len(carry_ops) == 3, "one BORROW_INTEREST debit per HELD short bar"

    # Each debit is the hand-computed per-bar carry = 1 × 100 × 10 × 0.10 / 365.
    for amount, _ts, _bal in carry_ops:
        assert amount == _CARRY_PER_BAR, "carry = days × close × |size| × rate / 365"
    # Sanity: the literal is 100/365 at full Decimal precision.
    assert _CARRY_PER_BAR == Decimal("100") / Decimal("365")

    # Cumulative carry = 3 × (100 / 365). NOTE: the engine debits three INDEPENDENT
    # full-precision ``100/365`` debits, so the ledger sum equals ``3 ×
    # _CARRY_PER_BAR`` exactly. (An independently-computed ``300/365`` rounds at the
    # 28th significant digit under the default Decimal context and is NOT the
    # invariant — the engine never forms ``300/365``.)
    total_carry = sum((a for a, _t, _b in carry_ops), Decimal("0"))
    assert total_carry == Decimal("3") * _CARRY_PER_BAR

    # final balance = 100_000 − Σ carry (carry is a REAL realized outflow, D-08).
    assert final_balance == Decimal("100000") - total_carry

    # The balance_after of each op steps down by exactly one carry (audit chain).
    expected_bal = Decimal("100000")
    for amount, _ts, bal_after in carry_ops:
        expected_bal -= amount
        assert bal_after == expected_bal

    # --- Determinism double-run (CARRY-01 rides bar BUSINESS time, not now()) ----
    carry_ops_2, final_balance_2 = _run_once()
    # Byte-identical carry amounts AND timestamps AND final balance — a wall-clock
    # stamp would make the timestamps differ run-to-run.
    assert carry_ops_2 == carry_ops, "determinism: carry amounts + timestamps identical"
    assert final_balance_2 == final_balance

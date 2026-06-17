"""FROZEN scale-in-then-partial-cover round-trip e2e (SCALE-02) — Phase 05.1 (Plan 05.1-02).

============================ FROZEN — SHORT SCALE-IN REGRESSION LOCK ================
FREEZE PROVENANCE (D-10/D-12): frozen as the parked regression lock for the short
scale-in re-baseline at the owner-gated 05.1-02 sign-off — Approved-by: tiziaco
(tiziano.iaco@gmail.com), 2026-06-17. The freeze set is the two parked short scale-in
scenarios (``short_scale_in`` aggregate-notional re-lock + ``short_scale_in_partial_cover``
scale-in-then-partial-cover) cross-validated vs backtesting.py 0.6.5 + backtrader
1.9.78.123 (see tests/golden/CROSS-VALIDATION-SCALE-IN.md, Owner Sign-Off = APPROVED).
This is a RESULT-CHANGING re-baseline that froze ONLY under explicit owner sign-off.
Every number asserted below is a HAND-COMPUTED literal with the arithmetic shown
inline (Decimal end-to-end; repr-exact ``str(x) == str(expected)`` assertions, never
float ``==``). This test does NOT use the golden-diff harness — its load-bearing
assertions are the scale-in + partial-cover margin/cash/position INTERNALS (the
SCALE-IN re-lock on the add, the partial release on the cover, and the first-class
short realised PnL on the covered fraction). It drives the engine's real
SIGNAL -> ORDER -> FILL -> PORTFOLIO path and asserts on the live read-model.
====================================================================================

What it exercises (D-02/D-08/SCALE-02)
--------------------------------------
* SCALE-02 (settlement path, ADD) — a SECOND same-side SELL-add settles through the
             EXISTING margin SCALE-IN branch (``portfolio.py:423-441``), re-locking the
             margin to the new ``aggregate_notional / leverage``.
* SHORT-02/SHORT-03 (settlement path, COVER) — a BUY partial-cover then REDUCES the
             scaled short: the lock is released pro-rata to the remaining notional and
             the first-class short realised PnL settles on the COVERED fraction
             (``|covered| × (entry − exit)``). NO new settlement branch — the same
             Phase-2/3 accounting core handles the round-trip (D-02/D-03).

Discretion values (oracle-dark — synthetic instrument, NEVER BTCUSD)
--------------------------------------------------------------------
``SCALPCUSD`` declares ``borrow_rate = Decimal("0")`` (a no-carry path),
``maintenance_margin_rate = Decimal("0.01")``, ``max_leverage = Decimal("10")``. The
short is UNLEVERED (effective leverage 1). Capital $100k; csv exchange (zero fee / zero
slippage); next-bar fills; flat-OHLC.

================================ HAND COMPUTATION ================================

Price series (``bars.csv`` — daily, flat-OHLC so close == the unambiguous mark):

    bar  date         close
    0    2020-01-01   100
    1    2020-01-02   100    <- SELL-to-open decided (SHORT_ONLY, FixedQuantity 10)
    2    2020-01-03   100    <- open SELL fills NEXT bar @ 100; SHORT 10
    3    2020-01-04   100    <- SECOND SELL-add decided (allow_increase=True)
    4    2020-01-05   100    <- SELL-add fills NEXT bar @ 100; SHORT 20 (scale-in re-lock)
    5    2020-01-06    80    <- partial BUY-cover decided (exit_fraction = 0.5)
    6    2020-01-07    80    <- BUY-cover fills NEXT bar @ 80; covers 10, leaves SHORT 10

Engine knobs: starting_cash = 100_000, csv exchange (commission 0 everywhere),
enable_margin = True, allow_short_selling = True. Unlevered short (effective L = 1).

--- SELL-to-open fill (2020-01-03), fill 100 ---
    SHORT 10 @ 100; aggregate_notional = 1_000; locked = 1_000 / 1 = 1_000; balance 100_000.

--- SECOND SELL-add fill (2020-01-05), fill 100 (SCALE-IN re-lock, SCALE-02) ---
    sell_quantity = 20; avg_price = 100; net_quantity = 20 → SHORT 20.
    aggregate_notional = 20 × 100 = 2_000; locked RE-LOCKED to 2_000 / 1 = 2_000.
    balance unchanged (commission 0) -> 100_000; available = 100_000 − 2_000 = 98_000.

--- partial BUY-cover fill (2020-01-07), fill 80, exit_fraction 0.5 ------------------
    covered quantity = exit_fraction × |open| = 0.5 × 20 = 10 → remaining SHORT 10.
    SHORT-03 realised increment (covered fraction) = |covered| × (entry − exit)
        = 10 × (100 − 80) = 200  → settled to cash.
    balance = 100_000 + 200 = 100_200.
    remaining position: SHORT 10; aggregate_notional = 10 × 100 = 1_000;
        locked recomputed (pro-rata release) = 1_000 / 1 = 1_000.
    available = balance − locked = 100_200 − 1_000 = 99_200.
    equity = market_value + cash = (−80 × 10) + 100_200 = −800 + 100_200 = 99_400.

The position is STILL OPEN after the partial cover (NOT closed, NOT flipped).

================================ END HAND COMPUTATION ================================
"""

import pathlib
from decimal import Decimal

from itrader.core.enums import Side
from itrader.core.enums.order import OrderStatus, OrderType
from itrader.core.enums.trading import TradingDirection
from itrader.core.instrument import Instrument
from itrader.core.sizing import FixedQuantity, SignalIntent
from itrader.strategy_handler.base import Strategy
from itrader.trading_system.backtest_trading_system import BacktestTradingSystem
from itrader.universe import Universe

HERE = pathlib.Path(__file__).resolve().parent

_TICKER = "SCALPCUSD"
_CASH = 100_000
_QTY = Decimal("10")
_EXIT_FRACTION = Decimal("0.5")
_PORTFOLIO_MAX_LEVERAGE = Decimal("5")


class _ShortScaleInPartialCoverStrategy(Strategy):
    """SHORT_ONLY with allow_increase=True: SELL-to-open on 2020-01-02, a SECOND
    same-side SELL-add on 2020-01-04, then a PARTIAL BUY-cover (exit_fraction 0.5)
    on 2020-01-06. Drives the NORMAL fan-out — no hand-built SignalEvent injected."""

    name = "short_scale_in_partial_cover"
    max_window = 100
    warmup = 0
    sizing_policy = FixedQuantity(qty=_QTY)
    direction = TradingDirection.SHORT_ONLY
    allow_increase = True

    def __init__(self, timeframe: str, tickers: list[str]) -> None:
        super().__init__(timeframe=timeframe, tickers=list(tickers))

    def generate_signal(self, ticker: str) -> SignalIntent | None:
        date = self.now.tz_convert("UTC").strftime("%Y-%m-%d")
        if date == "2020-01-02":
            return SignalIntent(ticker=ticker, action=Side.SELL, order_type=OrderType.MARKET)
        if date == "2020-01-04":
            return SignalIntent(ticker=ticker, action=Side.SELL, order_type=OrderType.MARKET)
        if date == "2020-01-06":
            return SignalIntent(
                ticker=ticker, action=Side.BUY, order_type=OrderType.MARKET,
                exit_fraction=_EXIT_FRACTION)
        return None


def _scalpc_instrument() -> Instrument:
    """Oracle-dark synthetic instrument — borrow_rate 0 (a no-carry path)."""
    return Instrument(
        symbol=_TICKER,
        price_precision=Decimal("0.01"),
        quantity_precision=Decimal("0.00000001"),
        min_order_size=None,
        maintenance_margin_rate=Decimal("0.01"),
        max_leverage=Decimal("10"),
        settles_funding=False,
        borrow_rate=Decimal("0"),
    )


def _build_scalpc_system():
    """Build the real backtest engine, enable margin + short-selling, wire the
    oracle-dark Universe (mirrors tests/e2e/short_roundtrip)."""
    system = BacktestTradingSystem(
        exchange="csv",
        csv_paths={_TICKER: HERE / "bars.csv"},
        start_date="2020-01-01",
        end_date="2020-01-07",
    )
    sh = system.strategies_handler
    sh._allow_short_selling = True
    sh._enable_margin = True
    strategy = _ShortScaleInPartialCoverStrategy(timeframe="1d", tickers=[_TICKER])
    sh.add_strategy(strategy)
    portfolio_id = system.portfolio_handler.add_portfolio(
        user_id=1, name="short_scale_in_partial_cover_pf", exchange="csv", cash=_CASH)
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
    universe = Universe(members=[_TICKER], instrument_map={_TICKER: _scalpc_instrument()})
    system.execution_handler.exchanges["simulated"].set_universe(universe)
    system.order_handler.set_universe(universe)
    system.portfolio_handler.set_universe(universe)

    return system, portfolio, portfolio_id


def test_short_scale_in_partial_cover_scenario_parked():
    """PARKED scale-in-then-partial-cover round-trip: the SELL-add scales the short
    (SCALE-IN re-lock to aggregate_notional / L, SCALE-02), then a partial BUY-cover
    REDUCES it — releasing the lock pro-rata and settling the first-class short PnL on
    the covered fraction. The cover does NOT close or flip the book. See the module
    docstring for the full arithmetic. PARKED — frozen ONLY at the 05.1-02 owner
    sign-off."""
    system, portfolio, portfolio_id = _build_scalpc_system()
    engine = system.engine
    handler = system.portfolio_handler
    cash = portfolio.cash_manager

    snaps: dict[str, dict] = {}
    for time_event in engine.time_generator:
        date = time_event.time.tz_convert("UTC").strftime("%Y-%m-%d")
        engine.clock.set_time(time_event.time)
        engine.global_queue.put(time_event)
        engine.event_handler.process_events()
        for active in handler.get_active_portfolios():
            active.record_metrics(time_event.time)

        position = portfolio.get_open_position(_TICKER)
        snaps[date] = {
            "balance": cash.balance,
            "available": cash.available_balance,
            "locked": cash.locked_margin_total,
            "qty": None if position is None else position.net_quantity,
            "side": None if position is None else position.side.name,
            "realised": None if position is None else position.realised_pnl,
            "aggregate_notional": None if position is None else position.aggregate_notional,
            "equity": handler.total_equity(portfolio_id),
        }

    engine.order_handler.expire_all_resting()
    engine.event_handler.process_events()

    # --- SELL-to-open fill (2020-01-03): SHORT 10 @ 100, lock = 1000 -------------
    opened = snaps["2020-01-03"]
    assert opened["side"] == "SHORT"
    assert str(opened["qty"]) == str(Decimal("10"))
    # aggregate_notional reprs 1000.0 (avg_price 100.0 from CSV close 100.0; value 1000).
    assert str(opened["aggregate_notional"]) == str(Decimal("1000.0"))
    # locked carries the un-quantized notional repr (.0); cash fields quantize to .00.
    assert str(opened["locked"]) == str(Decimal("1000.0"))
    assert str(opened["balance"]) == str(Decimal("100000.00"))

    # --- SECOND SELL-add fill (2020-01-05): SHORT 20; SCALE-IN re-lock to 2000 ---
    # SCALE-02: the add settles through portfolio.py:423-441 — aggregate_notional
    # recomputes to 20 × 100 = 2000 and the lock RE-LOCKS to 2000 / 1 = 2000.
    scaled = snaps["2020-01-05"]
    assert scaled["side"] == "SHORT", "the scale-in stays SHORT (no flip)"
    assert str(scaled["qty"]) == str(Decimal("20")), "10 + 10 = SHORT 20 (scaled in)"
    assert str(scaled["aggregate_notional"]) == str(Decimal("2000.0")), "20 × 100.0 = 2000.0"
    assert str(scaled["locked"]) == str(Decimal("2000.0")), "re-locked to aggregate_notional / L"
    assert str(scaled["balance"]) == str(Decimal("100000.00"))
    assert str(scaled["available"]) == str(Decimal("98000.00")), "100000 − 2000 = 98000"

    # --- partial BUY-cover fill (2020-01-07): covers 10, leaves SHORT 10 ---------
    # SHORT-02: the cover REDUCES the scaled short (not closes, not flips) — remaining
    # SHORT 10; the lock is released pro-rata to the remaining notional (SHORT-03 PnL
    # on the covered fraction settles to cash).
    covered = snaps["2020-01-07"]
    assert covered["side"] == "SHORT", "partial cover keeps the book SHORT (no flip)"
    # After the close-path settlement the position internals re-quantize: qty reprs
    # 10.0 and aggregate_notional / locked repr at the cash scale (.00).
    assert str(covered["qty"]) == str(Decimal("10.0")), "exit_fraction 0.5 × 20 covered → 10 remain"
    # SHORT-03 realised increment for the covered 10 = 10 × (100 − 80) = 200.
    assert str(covered["realised"]) == str(Decimal("200.00")), "10 × (100 − 80) = 200"
    assert str(covered["balance"]) == str(Decimal("100200.00")), "settled covered PnL 200 -> 100200"
    # remaining aggregate_notional = 10 × 100 = 1000; lock recomputed (pro-rata) = 1000.
    assert str(covered["aggregate_notional"]) == str(Decimal("1000.00")), "remaining 10 × 100 = 1000"
    assert str(covered["locked"]) == str(Decimal("1000.00")), "lock released pro-rata to remaining 1000"
    # available = balance − locked = 100200 − 1000 = 99200.
    assert str(covered["available"]) == str(Decimal("99200.00")), "100200 − 1000 = 99200"
    # equity = market_value + cash = (−80 × 10) + 100200 = −800 + 100200 = 99400.
    assert str(covered["equity"]) == str(Decimal("99400.00")), "(−80 × 10) + 100200 = 99400"

    # The position is NOT closed (a partial cover keeps it open).
    assert len(portfolio.closed_positions) == 0, "partial cover does NOT close the position"

    # All three orders (open SELL + SELL-add + partial-cover BUY) filled in full —
    # the SELL-add was ADMITTED (SCALE-01) and the round-trip reached settlement.
    orders = system.order_handler.get_orders_by_ticker(_TICKER, portfolio_id)
    assert len(orders) == 3
    assert {o.status for o in orders} == {OrderStatus.FILLED}

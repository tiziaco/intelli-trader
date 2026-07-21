"""FROZEN short scale-in e2e (SCALE-02) — Phase 05.1 (Plan 05.1-02).

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
assertions are the short scale-in margin/cash/position INTERNALS (the SCALE-IN re-lock
to the new ``aggregate_notional / leverage``). It drives the engine's real
SIGNAL -> ORDER -> FILL -> PORTFOLIO path and asserts on the live read-model.
====================================================================================

What it exercises (D-02/D-08/SCALE-02)
--------------------------------------
* SCALE-01 (Plan 05.1-01) — a SHORT_ONLY strategy with ``allow_increase=True`` ADMITS a
             same-side SELL-add against an open short (it does not reject at the
             admission INCREASE gate); the add falls through to the direction-agnostic
             ``resolve_entry`` sizing + check-and-reserve gate.
* SCALE-02 (settlement path) — the SECOND SELL-add settles through the EXISTING
             side-agnostic margin SCALE-IN branch at ``portfolio.py:423-441`` (the
             ``is_increase`` derivation at :385-388 is True for SHORT+SELL), recomputing
             the margin lock to the NEW ``position.aggregate_notional / leverage``. NO
             new settlement branch — the Phase-2/3 accounting core is reused unchanged
             (D-02/D-03).

Discretion values (oracle-dark — synthetic instrument, NEVER BTCUSD)
--------------------------------------------------------------------
``SCALEUSD`` declares ``borrow_rate = Decimal("0")`` (a no-carry scale-in path),
``maintenance_margin_rate = Decimal("0.01")``, ``max_leverage = Decimal("10")``. The
short is UNLEVERED (the SignalIntent carries no leverage -> effective leverage 1), so the
lock is the FULL aggregate notional. Capital $100k; csv exchange (zero fee / zero
slippage); next-bar fills; flat-OHLC so close == the unambiguous mark.

================================ HAND COMPUTATION ================================

Price series (``bars.csv`` — daily, flat-OHLC so close == the unambiguous mark):

    bar  date         close
    0    2020-01-01   100
    1    2020-01-02   100    <- SELL-to-open decided (SHORT_ONLY, FixedQuantity 10)
    2    2020-01-03   100    <- open SELL fills NEXT bar @ 100; SHORT 10 opened
    3    2020-01-04   100    <- SECOND SELL-add decided (allow_increase=True)
    4    2020-01-05   100    <- SELL-add fills NEXT bar @ 100; SHORT 20 (scale-in re-lock)
    5    2020-01-06    90    <- favourable mark (price dropped); short carries on

Engine knobs: starting_cash = 100_000, csv exchange (commission 0 everywhere),
enable_margin = True, allow_short_selling = True, portfolio max_leverage = 5.
Effective leverage of the unlevered short = 1.

--- SELL-to-open fill (2020-01-03), fill price 100 ---
    FixedQuantity 10; SHORT position opened.
    aggregate_notional = |size| × avg_price = 10 × 100 = 1_000
    locked_margin = aggregate_notional / L = 1_000 / 1 = 1_000   (unlevered)
    balance unchanged (margin opens debit ONLY commission = 0) -> 100_000
    available = balance − locked = 100_000 − 1_000 = 99_000

--- SECOND SELL-add fill (2020-01-05), fill price 100 (SCALE-IN re-lock, SCALE-02) ---
    sell_quantity = 20; avg_sold = 100; avg_price = (100 × 20 − 0) / 20 = 100.
    net_quantity = |0 − 20| = 20; the short scales to SHORT 20 (NOT a flip, NOT a new
    position — the same open short is increased).
    aggregate_notional = |size| × avg_price = 20 × 100 = 2_000
    locked_margin RE-LOCKED to aggregate_notional / L = 2_000 / 1 = 2_000
        (portfolio.py:423-441 — release the prior 1_000 lock, re-lock to 2_000)
    balance unchanged (add debits ONLY commission = 0) -> 100_000
    available = balance − locked = 100_000 − 2_000 = 98_000

--- favourable mark (2020-01-06, mark 90): short carries on -------------------------
    total_equity = total_market_value + cash. A SHORT carries a NEGATIVE market_value
    liability = −mark × |size| = −90 × 20 = −1_800, so equity = −1_800 + 100_000 = 98_200.
    The unrealised GAIN is the liability shrinking from −2_000 (at the 100 entry mark)
    to −1_800 = +200 = (entry − mark) × |size| = (100 − 90) × 20.
    locked stays 2_000 (locked off the aggregate ENTRY notional, not the mark).

================================ END HAND COMPUTATION ================================
"""

import pathlib
from decimal import Decimal

from itrader.config import PortfolioConfig, get_portfolio_preset
from itrader.outils.dict_merge import recursive_merge
from itrader.core.enums import Side
from itrader.core.enums.order import OrderStatus, OrderType
from itrader.core.enums.trading import TradingDirection
from itrader.core.instrument import Instrument
from itrader.core.sizing import FixedQuantity, SignalIntent
from itrader.strategy_handler.base import Strategy
from itrader.trading_system.backtest_trading_system import BacktestTradingSystem
from itrader.universe import Universe
from itrader.execution_handler.execution_handler import DEFAULT_ACCOUNT_ID

HERE = pathlib.Path(__file__).resolve().parent

# Synthetic ticker — NEVER BTCUSD, so the spot oracle (134 / 46189.87730727451)
# cannot be touched by anything in this file.
_TICKER = "SCALEUSD"
_CASH = 100_000
_QTY = Decimal("10")
_PORTFOLIO_MAX_LEVERAGE = Decimal("5")


class _ShortScaleInStrategy(Strategy):
    """SHORT_ONLY with allow_increase=True driving a scale-in through the NORMAL
    fan-out: SELL-to-open on 2020-01-02, a SECOND same-side SELL-add on 2020-01-04.
    No hand-built SignalEvent is injected onto the queue — the strategy declares
    ``allow_increase`` so the SELL-add is ADMITTED (SCALE-01) and settles through
    the EXISTING margin SCALE-IN branch (SCALE-02)."""

    name = "short_scale_in"
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
        return None


def _scale_instrument() -> Instrument:
    """Oracle-dark synthetic instrument — borrow_rate 0 (a no-carry scale-in path)."""
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


def _build_scale_in_system():
    """Build the real backtest engine, enable margin + short-selling, wire the
    oracle-dark Universe, and return the engine + portfolio handle ready to drive
    tick-by-tick (mirrors tests/e2e/short_roundtrip)."""
    system = BacktestTradingSystem(
        exchange="csv",
        csv_paths={_TICKER: HERE / "bars.csv"},
        start_date="2020-01-01",
        end_date="2020-01-06",
    )
    sh = system.strategies_handler
    sh._allow_short_selling = True
    sh._enable_margin = True
    strategy = _ShortScaleInStrategy(timeframe="1d", tickers=[_TICKER])
    sh.add_strategy(strategy)
    portfolio_id = system.portfolio_handler.add_portfolio(
        # 01-03 D-03 (sibling 01-03b finding): the account leaf is selected at
        # CONSTRUCTION from enable_margin; the post-construction config swap below
        # refines the rest but no longer rebuilds the leaf — so margin must be on
        # in the constructor config to get a SimulatedMarginAccount.
        name="short_scale_in_pf", exchange="csv", cash=_CASH,
        portfolio_config=PortfolioConfig.model_validate(recursive_merge(
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
    universe = Universe(members=[_TICKER], instrument_map={_TICKER: _scale_instrument()})
    system.execution_handler.exchanges[("simulated", DEFAULT_ACCOUNT_ID)].set_universe(universe)
    system.order_handler.set_universe(universe)
    system.portfolio_handler.set_universe(universe)

    return system, portfolio, portfolio_id


def test_short_scale_in_scenario_parked():
    """PARKED short scale-in (SELL-to-open -> SECOND SELL-add): the add is ADMITTED
    (allow_increase=True, SCALE-01) and settles through the EXISTING margin SCALE-IN
    branch (portfolio.py:423-441), re-locking the margin to the new
    aggregate_notional / leverage (SCALE-02). See the module docstring for the full
    arithmetic. PARKED — frozen as the regression lock ONLY at the 05.1-02 owner
    sign-off."""
    system, portfolio, portfolio_id = _build_scale_in_system()
    engine = system.engine
    handler = system.portfolio_handler
    cash = portfolio.account

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
            "aggregate_notional": None if position is None else position.aggregate_notional,
            "avg_price": None if position is None else position.avg_price,
            "equity": handler.total_equity(portfolio_id),
        }

    engine.order_handler.expire_all_resting()
    engine.event_handler.process_events()

    # --- SELL-to-open fill (2020-01-03): SHORT 10 @ 100; lock = notional = 1000 ---
    opened = snaps["2020-01-03"]
    assert opened["side"] == "SHORT", "SELL-to-open opened a SHORT (not a long)"
    assert str(opened["qty"]) == str(Decimal("10")), "FixedQuantity sized the short to 10"
    # aggregate_notional = |size| × avg_price; avg_price reprs 100.0 (CSV close 100.0),
    # so the magnitude reprs 1000.0 (value 1000) — repr-exact against the live reading.
    assert str(opened["aggregate_notional"]) == str(Decimal("1000.0")), "10 × 100.0 = 1000.0"
    # Unlevered short: locked = aggregate_notional / L = 1000.0 / 1 = 1000.0
    # (the lock carries the un-quantized notional repr; value 1000).
    assert str(opened["locked"]) == str(Decimal("1000.0")), "lock = full notional (unlevered)"
    # Cash fields are quantized to the cash scale (2dp) -> .00 repr.
    assert str(opened["balance"]) == str(Decimal("100000.00"))
    assert str(opened["available"]) == str(Decimal("99000.00")), "100000 − 1000 = 99000"

    # --- SECOND SELL-add fill (2020-01-05): SHORT 20; SCALE-IN re-lock to 2000 ---
    # SCALE-02: the add settles through portfolio.py:423-441 — the same open short
    # is INCREASED (is_increase True for SHORT+SELL, :385-388), aggregate_notional
    # recomputes to 20 × 100 = 2000 and the lock RE-LOCKS to 2000 / 1 = 2000.
    scaled = snaps["2020-01-05"]
    assert scaled["side"] == "SHORT", "the scale-in stays SHORT (no flip, no new position)"
    assert str(scaled["qty"]) == str(Decimal("20")), "10 + 10 = SHORT 20 (scaled in)"
    assert str(scaled["avg_price"]) == str(Decimal("100.0")), "(100.0 × 20 − 0) / 20 = 100.0"
    assert str(scaled["aggregate_notional"]) == str(Decimal("2000.0")), "20 × 100.0 = 2000.0"
    # The SCALE-IN re-lock: lock == aggregate_notional / leverage = 2000.0 / 1 = 2000.0.
    assert str(scaled["locked"]) == str(Decimal("2000.0")), "re-locked to aggregate_notional / L"
    # The add debits ONLY commission (0) — balance unchanged.
    assert str(scaled["balance"]) == str(Decimal("100000.00"))
    # available = balance − locked = 100000 − 2000 = 98000.
    assert str(scaled["available"]) == str(Decimal("98000.00")), "100000 − 2000 = 98000"

    # --- favourable mark (2020-01-06, mark 90): the scaled short carries on -------
    marked = snaps["2020-01-06"]
    assert marked["side"] == "SHORT"
    assert str(marked["qty"]) == str(Decimal("20"))
    # equity = total_market_value + cash = (−90 × 20) + 100000 = −1800 + 100000 = 98200.
    assert str(marked["equity"]) == str(Decimal("98200.00")), "(−90 × 20) + 100000 = 98200"
    # The lock stays at the aggregate ENTRY notional (not the mark).
    assert str(marked["locked"]) == str(Decimal("2000.0"))

    # Both orders (open SELL + SELL-add) filled in full — the SELL-add was ADMITTED
    # (SCALE-01), proving the scale-in reached settlement (NOT rejected at the gate).
    orders = system.order_handler.get_orders_by_ticker(_TICKER, portfolio_id)
    assert len(orders) == 2
    assert {o.status for o in orders} == {OrderStatus.FILLED}

    # The scale-in is ONE open short position (not two), proving the add INCREASED
    # the existing position rather than opening a fresh lot.
    assert len(portfolio.closed_positions) == 0, "a scale-in closes nothing"

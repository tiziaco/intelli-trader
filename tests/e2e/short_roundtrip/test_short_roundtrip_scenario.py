"""FROZEN pure-short round-trip e2e (SHORT-02 / SHORT-03) — Phase 3 (Plan 03-06).

============================ FROZEN — ACCOUNTING-CORE GOLDEN ==========================
FREEZE PROVENANCE (D-10/D-12): frozen as part of the single accounting-core golden at
the owner-gated 04-05 sign-off — Approved-by: tiziaco (tiziano.iaco@gmail.com),
2026-06-16. The freeze set is ALL parked P2/P3 scenarios (levered_long, short_roundtrip,
short_carry, partial_cover) + the new P4 liquidation scenarios (forced_liq_long,
forced_liq_short, levered_long_into_liquidation) frozen as ONE accounting-core golden
(cross-validated vs backtesting.py + backtrader; see tests/golden/CROSS-VALIDATION-ACCOUNTING.md).
Every number asserted below is a HAND-COMPUTED literal with the arithmetic shown
inline. This test does NOT use the golden-diff
harness (``run_scenario`` / ``golden/``) — its load-bearing assertions are short
margin/cash/position INTERNALS (the margin lock, the released lock on cover, the
first-class short realised PnL) that the trades/equity/summary golden CSVs do not
capture. It drives the engine's real SIGNAL -> ORDER -> FILL -> PORTFOLIO path and
asserts on the live read-model + cash/position state.
=====================================================================================

What it exercises
-----------------
* SHORT-01 — a SHORT_ONLY strategy is admitted (two-flag registration: the handler's
             ``allow_short_selling`` AND ``enable_margin`` are on).
* SHORT-02 — a BUY-to-cover on the open short routes through the side-agnostic exit
             arm (the cover dispatches on ``side``, NOT a sign of the unsigned
             read-model magnitude) and nets the short to FLAT — it does NOT flip long.
* SHORT-03 — first-class short realised PnL = ``|size| × (entry − exit)`` (zero
             commission), settled to cash; the position-life margin lock is released.

Discretion values (oracle-dark — synthetic instrument, NEVER BTCUSD)
--------------------------------------------------------------------
The synthetic ticker ``SHORTUSD`` declares ``borrow_rate = Decimal("0")`` (this is a
pure round-trip with NO held-carry bars — carry is exercised in ``short_carry``),
``maintenance_margin_rate = Decimal("0.01")``, ``max_leverage = Decimal("10")``. The
short is UNLEVERED (the SignalIntent carries no leverage → effective leverage 1), so
the lock is the FULL notional.

================================ HAND COMPUTATION ================================

Price series (``bars.csv`` — daily, flat-OHLC so close == the unambiguous mark):

    bar  date         close
    0    2020-01-01   100
    1    2020-01-02   100    <- SELL-to-open decided here (SHORT_ONLY, FixedQuantity 10)
    2    2020-01-03   100    <- SELL fills NEXT bar at close 100 (look-ahead-safe)
    3    2020-01-04    80    <- BUY-to-cover decided here (price dropped 20%)
    4    2020-01-05    80    <- BUY fills NEXT bar at close 80
    5    2020-01-06    80

Engine knobs: starting_cash = 100_000, csv exchange (zero fee / zero slippage —
commission 0 everywhere), enable_margin = True, allow_short_selling = True, portfolio
max_leverage = 5. Effective leverage of the unlevered short = 1.

--- SELL-to-open fill (2020-01-03), fill price = 100 ---
    quantity = 10 (FixedQuantity); SHORT position opened.
    notional = |size| × entry = 10 × 100 = 1_000
    locked_margin = notional / L = 1_000 / 1 = 1_000   (unlevered → full notional)
    cash unchanged (margin debits ONLY commission = 0) -> 100_000
    available = balance − locked = 100_000 − 1_000 = 99_000

--- favourable mark (2020-01-04, mark 80) ---
    total_equity = total_market_value + cash; a SHORT market_value is the NEGATIVE
    liability = −mark × |size| = −80 × 10 = −800, so equity = −800 + 100_000 = 99_200.
    The unrealised GAIN is the liability shrinking from −1_000 (at the 100 entry
    mark) to −800 = +200 = (entry − mark) × |size| = (100 − 80) × 10.
    locked stays 1_000 (locked off ENTRY notional, not the mark)

--- BUY-to-cover fill (2020-01-05), fill price = 80 ---
    SHORT-02: the cover nets the short to FLAT (does NOT flip long).
    SHORT-03 realised PnL = |size| × (entry − exit) = 10 × (100 − 80) = 200
    locked margin fully RELEASED -> 0
    final balance = 100_000 + 200 = 100_200
    final available = 100_200 (lock gone); final equity = 100_200 (flat)

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
_TICKER = "SHORTUSD"
_CASH = 100_000
_QTY = Decimal("10")
_PORTFOLIO_MAX_LEVERAGE = Decimal("5")


class _ShortRoundtripStrategy(Strategy):
    """A SHORT_ONLY strategy driving a pure short round-trip through the NORMAL
    fan-out: SELL-to-open on 2020-01-02, BUY-to-cover on 2020-01-04. NO hand-built
    SignalEvent is injected onto the queue."""

    name = "short_roundtrip"
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
        if date == "2020-01-04":
            return SignalIntent(ticker=ticker, action=Side.BUY, order_type=OrderType.MARKET)
        return None


def _short_instrument() -> Instrument:
    """Oracle-dark synthetic instrument — borrow_rate 0 (no carry in this pure
    round-trip; carry is exercised by the short_carry scenario)."""
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


def _build_short_system():
    """Build the real backtest engine, enable margin + short-selling (white-box —
    the factory exposes no per-portfolio short knob), wire the oracle-dark Universe,
    and return the engine + portfolio handle ready to drive tick-by-tick."""
    system = BacktestTradingSystem(
        exchange="paper",
        csv_paths={_TICKER: HERE / "bars.csv"},
        start_date="2020-01-01",
        end_date="2020-01-06",
    )
    # Two-flag short registration (SHORT-01) on the StrategiesHandler.
    sh = system.strategies_handler
    sh._allow_short_selling = True
    sh._enable_margin = True
    strategy = _ShortRoundtripStrategy(timeframe="1d", tickers=[_TICKER])
    sh.add_strategy(strategy)
    portfolio_id = system.portfolio_handler.add_portfolio(
        # 01-03 D-03 (sibling 01-03b finding): the account leaf is selected at
        # CONSTRUCTION from enable_margin; the post-construction config swap below
        # refines the rest but no longer rebuilds the leaf — so margin must be on
        # in the constructor config to get a SimulatedMarginAccount.
        name="short_roundtrip_pf", exchange="paper", cash=_CASH,
        portfolio_config=PortfolioConfig.model_validate(recursive_merge(
            get_portfolio_preset("default").model_dump(),
            {"trading_rules": {"enable_margin": True}})))
    strategy.subscribe_portfolio(portfolio_id)

    portfolio = system.portfolio_handler.get_portfolio(portfolio_id)
    # Enable margin + shorts on the settlement branch (D-09). Pydantic models are
    # immutable, so swap via model_copy.
    portfolio.config = portfolio.config.model_copy(update={
        "trading_rules": portfolio.config.trading_rules.model_copy(update={
            "enable_margin": True,
            "allow_short_selling": True,
            "max_leverage": _PORTFOLIO_MAX_LEVERAGE,
        })})
    # Enable the order-domain margin arm (admission reservation + validator).
    order_manager = system.order_handler.order_manager
    order_manager.admission_manager._enable_margin = True
    order_manager.admission_manager._portfolio_max_leverage = _PORTFOLIO_MAX_LEVERAGE
    order_manager.order_validator.enable_margin = True

    # Initialise the session (Trap-4 ordering), THEN override the auto-derived
    # Universe with the oracle-dark synthetic instrument on the three set_universe
    # seams the runner wires.
    runner = system.runner
    runner._initialise_backtest_session()
    universe = Universe(members=[_TICKER], instrument_map={_TICKER: _short_instrument()})
    system.execution_handler.exchanges[("paper", DEFAULT_ACCOUNT_ID)].set_universe(universe)
    system.order_handler.set_universe(universe)
    system.portfolio_handler.set_universe(universe)

    return system, portfolio, portfolio_id


def test_short_roundtrip_scenario_parked():
    """PARKED pure-short round-trip (SELL-to-open -> BUY-to-cover -> flat): the
    cover nets the short to FLAT (SHORT-02 — no flip), settles first-class short
    PnL (SHORT-03), and releases the lock. See the module docstring for the full
    arithmetic. PARKED — frozen as golden ONLY at Phase 4 / XVAL-01."""
    system, portfolio, portfolio_id = _build_short_system()
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
            "equity": handler.total_equity(portfolio_id),
        }

    engine.order_handler.expire_all_resting()
    engine.event_handler.process_events()

    # --- SELL-to-open fill (2020-01-03): SHORT 10 @ 100; lock = notional = 1000 ---
    opened = snaps["2020-01-03"]
    assert opened["side"] == "SHORT", "SELL-to-open opened a SHORT (not a long)"
    assert opened["qty"] == Decimal("10"), "FixedQuantity sized the short to 10"
    # Unlevered short: locked = |size| × entry / L = 10 × 100 / 1 = 1000.
    assert opened["locked"] == Decimal("1000"), "locked = full notional (unlevered)"
    # Margin opens debit ONLY commission (0) — balance unchanged.
    assert opened["balance"] == Decimal("100000")
    # available = balance − locked = 100000 − 1000 = 99000.
    assert opened["available"] == Decimal("99000")

    # --- favourable mark (2020-01-04, mark 80): unrealised short PnL = +200 ------
    marked = snaps["2020-01-04"]
    # total_equity = total_market_value + cash. A SHORT carries a NEGATIVE
    # market_value liability = −mark × |size| = −80 × 10 = −800, so
    #     equity = −800 + 100000 = 99200.
    # The short's unrealised GAIN is the liability shrinking from −1000 (at the
    # 100 entry mark) to −800 (at the 80 mark) = +200, exactly (100 − 80) × 10.
    assert marked["equity"] == Decimal("99200")
    # The lock stays at the ENTRY notional (not the mark).
    assert marked["locked"] == Decimal("1000")
    assert marked["side"] == "SHORT"

    # --- BUY-to-cover fill (2020-01-05): nets to FLAT (SHORT-02), settles 200 ----
    covered = snaps["2020-01-05"]
    assert covered["qty"] is None, "SHORT-02: cover nets the short to FLAT (no flip)"
    assert covered["side"] is None
    assert covered["locked"] == Decimal("0"), "margin lock released on cover"
    # SHORT-03: realised PnL = |size| × (entry − exit) = 10 × (100 − 80) = 200.
    assert covered["balance"] == Decimal("100200"), "settled short PnL 200 -> 100200"
    assert covered["available"] == Decimal("100200")
    assert covered["equity"] == Decimal("100200")

    # Realised PnL on the closed SHORT is the hand-computed 200.
    closed = portfolio.closed_positions
    assert len(closed) == 1
    assert closed[0].side.name == "SHORT"
    assert closed[0].realised_pnl == Decimal("200"), "10 × (100 − 80) = 200"

    # Both orders filled in full — the SHORT_ONLY BUY-cover was ADMITTED (not
    # rejected at the direction gate), proving SHORT-02's side-agnostic cover arm.
    orders = system.order_handler.get_orders_by_ticker(_TICKER, portfolio_id)
    assert len(orders) == 2
    assert {o.status for o in orders} == {OrderStatus.FILLED}

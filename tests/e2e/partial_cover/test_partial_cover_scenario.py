"""FROZEN partial-cover e2e (SHORT-02 / SHORT-03) — Phase 3 (Plan 03-06).

============================ FROZEN — ACCOUNTING-CORE GOLDEN ==========================
FREEZE PROVENANCE (D-10/D-12): frozen as part of the single accounting-core golden at
the owner-gated 04-05 sign-off — Approved-by: tiziaco (tiziano.iaco@gmail.com),
2026-06-16. The freeze set is ALL parked P2/P3 scenarios (levered_long, short_roundtrip,
short_carry, partial_cover) + the new P4 liquidation scenarios (forced_liq_long,
forced_liq_short, levered_long_into_liquidation) frozen as ONE accounting-core golden
(cross-validated vs backtesting.py + backtrader; see tests/golden/CROSS-VALIDATION-ACCOUNTING.md).
Every number asserted below is a HAND-COMPUTED literal with the arithmetic shown
inline. This test does NOT use the golden-diff
harness — its load-bearing assertions are the partial-cover margin/position INTERNALS
(the short REDUCES, not closes; the lock recomputes to the remaining notional; the
realized increment settles for the closed fraction). It drives the engine's real
SIGNAL -> ORDER -> FILL -> PORTFOLIO path and asserts on the live read-model + cash /
position state.
=====================================================================================

What it exercises
-----------------
* SHORT-02 — a BUY-cover with ``exit_fraction = 0.5`` REDUCES the open short to half
             (does NOT close, does NOT flip long) — the side-agnostic exit arm sizes
             the cover from the open magnitude and clamps to at most |net|.
* SHORT-03 — the realized PnL increment for the COVERED fraction settles to cash =
             ``|covered| × (entry − exit)``; the remaining short carries on with a
             recomputed margin lock.

Discretion values (oracle-dark — synthetic instrument, NEVER BTCUSD)
--------------------------------------------------------------------
``PCOVUSD`` declares ``borrow_rate = Decimal("0")`` (carry is exercised by short_carry),
``maintenance_margin_rate = Decimal("0.01")``, ``max_leverage = Decimal("10")``. The
short is UNLEVERED.

================================ HAND COMPUTATION ================================

Price series (``bars.csv`` — daily, flat-OHLC):

    bar  date         close
    0    2020-01-01   100
    1    2020-01-02   100    <- SELL-to-open decided (SHORT_ONLY, FixedQuantity 10)
    2    2020-01-03   100    <- SELL fills NEXT bar at 100; SHORT 10 opened
    3    2020-01-04    80    <- partial BUY-cover decided (exit_fraction = 0.5)
    4    2020-01-05    80    <- BUY-cover fills NEXT bar at 80; covers 5, leaves SHORT 5
    5    2020-01-06    80

Engine knobs: starting_cash = 100_000, csv exchange (zero fee / slippage),
enable_margin = True, allow_short_selling = True. Unlevered short (effective L = 1).

--- SELL-to-open fill (2020-01-03), fill 100 ---
    SHORT 10 @ 100; notional = 1_000; locked = 1_000 / 1 = 1_000; balance 100_000.

--- partial BUY-cover fill (2020-01-05), fill 80, exit_fraction 0.5 ---
    covered quantity = exit_fraction × |open| = 0.5 × 10 = 5 → remaining SHORT 5.
    SHORT-03 realized increment (covered fraction) = |covered| × (entry − exit)
        = 5 × (100 − 80) = 100  → settled to cash.
    balance = 100_000 + 100 = 100_100
    remaining position: SHORT 5; notional = 5 × 100 = 500; locked recomputed = 500.
    available = balance − locked = 100_100 − 500 = 99_600.
    equity = market_value + cash = (−80 × 5) + 100_100 = −400 + 100_100 = 99_700.

The position is STILL OPEN after the partial cover (NOT closed, NOT flipped).

================================ END HAND COMPUTATION ================================
"""

import pathlib
from decimal import Decimal

from itrader.config import PortfolioConfig, deep_merge, get_portfolio_preset
from itrader.core.enums import Side
from itrader.core.enums.order import OrderStatus, OrderType
from itrader.core.enums.trading import TradingDirection
from itrader.core.instrument import Instrument
from itrader.core.sizing import FixedQuantity, SignalIntent
from itrader.strategy_handler.base import Strategy
from itrader.trading_system.backtest_trading_system import BacktestTradingSystem
from itrader.universe import Universe

HERE = pathlib.Path(__file__).resolve().parent

_TICKER = "PCOVUSD"
_CASH = 100_000
_QTY = Decimal("10")
_EXIT_FRACTION = Decimal("0.5")
_PORTFOLIO_MAX_LEVERAGE = Decimal("5")


class _PartialCoverStrategy(Strategy):
    """SHORT_ONLY: SELL-to-open on 2020-01-02, then a PARTIAL BUY-cover
    (exit_fraction 0.5) on 2020-01-04. Drives the NORMAL fan-out."""

    name = "partial_cover"
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
            return SignalIntent(
                ticker=ticker, action=Side.BUY, order_type=OrderType.MARKET,
                exit_fraction=_EXIT_FRACTION)
        return None


def _pcov_instrument() -> Instrument:
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


def _build_pcov_system():
    system = BacktestTradingSystem(
        exchange="csv",
        csv_paths={_TICKER: HERE / "bars.csv"},
        start_date="2020-01-01",
        end_date="2020-01-06",
    )
    sh = system.strategies_handler
    sh._allow_short_selling = True
    sh._enable_margin = True
    strategy = _PartialCoverStrategy(timeframe="1d", tickers=[_TICKER])
    sh.add_strategy(strategy)
    portfolio_id = system.portfolio_handler.add_portfolio(
        # 01-03 D-03 (sibling 01-03b finding): the account leaf is selected at
        # CONSTRUCTION from enable_margin; the post-construction config swap below
        # refines the rest but no longer rebuilds the leaf — so margin must be on
        # in the constructor config to get a SimulatedMarginAccount.
        name="partial_cover_pf", exchange="csv", cash=_CASH,
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
    universe = Universe(members=[_TICKER], instrument_map={_TICKER: _pcov_instrument()})
    system.execution_handler.exchanges["simulated"].set_universe(universe)
    system.order_handler.set_universe(universe)
    system.portfolio_handler.set_universe(universe)

    return system, portfolio, portfolio_id


def test_partial_cover_scenario_parked():
    """PARKED partial cover (exit_fraction 0.5): the BUY-cover REDUCES the short to
    half and the remaining short carries on; the covered fraction's PnL settles. The
    cover does NOT close or flip the book (SHORT-02). See the module docstring for the
    full arithmetic. PARKED — frozen as golden ONLY at P4/XVAL-01."""
    system, portfolio, portfolio_id = _build_pcov_system()
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
            "realised": None if position is None else position.realised_pnl,
            "equity": handler.total_equity(portfolio_id),
        }

    engine.order_handler.expire_all_resting()
    engine.event_handler.process_events()

    # --- SELL-to-open fill (2020-01-03): SHORT 10 @ 100, lock = 1000 -------------
    opened = snaps["2020-01-03"]
    assert opened["side"] == "SHORT"
    assert opened["qty"] == Decimal("10")
    assert opened["locked"] == Decimal("1000")
    assert opened["balance"] == Decimal("100000")

    # --- partial BUY-cover fill (2020-01-05): covers 5, leaves SHORT 5 -----------
    covered = snaps["2020-01-05"]
    # SHORT-02: REDUCES (not closes, not flips) — remaining SHORT 5.
    assert covered["side"] == "SHORT", "partial cover keeps the book SHORT (no flip)"
    assert covered["qty"] == Decimal("5"), "exit_fraction 0.5 × 10 covered → 5 remain"
    # SHORT-03 realized increment for the covered 5 = 5 × (100 − 80) = 100.
    assert covered["realised"] == Decimal("100"), "5 × (100 − 80) = 100"
    assert covered["balance"] == Decimal("100100"), "settled covered PnL 100 -> 100100"
    # Lock recomputed to the remaining notional / L = 5 × 100 / 1 = 500.
    assert covered["locked"] == Decimal("500"), "lock recomputed to remaining 500"
    # available = balance − locked = 100100 − 500 = 99600.
    assert covered["available"] == Decimal("99600")
    # equity = market_value + cash = (−80 × 5) + 100100 = −400 + 100100 = 99700.
    assert covered["equity"] == Decimal("99700")

    # --- the remaining short CARRIES ON to the last bar (still open) -------------
    last = snaps["2020-01-06"]
    assert last["side"] == "SHORT", "remaining short carries on past the partial cover"
    assert last["qty"] == Decimal("5")
    assert last["locked"] == Decimal("500")

    # The position is NOT closed (a partial cover keeps it open).
    assert len(portfolio.closed_positions) == 0, "partial cover does NOT close the position"

    # Both orders (open SELL + partial-cover BUY) filled in full.
    orders = system.order_handler.get_orders_by_ticker(_TICKER, portfolio_id)
    assert len(orders) == 2
    assert {o.status for o in orders} == {OrderStatus.FILLED}

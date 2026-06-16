"""FROZEN forced-liquidation SHORT white-box e2e — the P4 liquidation core (D-08).

============================ FROZEN — ACCOUNTING-CORE GOLDEN ==========================
FREEZE PROVENANCE (D-10/D-12): frozen as part of the single accounting-core golden at
the owner-gated 04-05 sign-off — Approved-by: tiziaco (tiziano.iaco@gmail.com),
2026-06-16. The freeze set is ALL parked P2/P3 scenarios (levered_long, short_roundtrip,
short_carry, partial_cover) + the new P4 liquidation scenarios (forced_liq_long,
forced_liq_short, levered_long_into_liquidation) frozen as ONE accounting-core golden
(liquidation directionally corroborated vs backtesting.py + backtrader, D-08; the
hand-computed closed-form is PRIMARY; see tests/golden/CROSS-VALIDATION-ACCOUNTING.md).
Every number asserted below is a HAND-COMPUTED literal with the arithmetic shown
inline. This
test does NOT use the golden-diff harness (``run_scenario`` / ``golden/``) precisely
because the load-bearing assertions are liquidation INTERNALS (the corrected isolated
SHORT liq price, the breach-bar forced-cover FillEvent, the penalty on commission, the
WB-capped loss, the LIQUIDATION-tagged forced-cover Order reaching FILLED in the
mirror) that the trades/equity/summary golden CSVs do not capture. It drives the
engine's real BAR -> (liquidation pass) -> FILL -> PORTFOLIO path.

The hand-computed closed-form is the PRIMARY oracle for the liquidation event (D-08);
this is the SHORT mirror of forced_liq_long.
=====================================================================================

What it exercises (LIQ-01 / LIQ-02 / LIQ-03 — the SHORT side, closes DEF-01-C)
-----------------------------------------------------------------------------
* LIQ-01 — a per-bar maintenance-margin breach check on the BAR route force-COVERS the
           breaching SHORT position at the corrected isolated liquidation price the
           moment the bar CLOSE crosses it UPWARD (a short breaches as price rises).
* LIQ-02 — the configurable liquidation penalty rides ``FillEvent.commission``, total
           realized loss EXPLICITLY clamped at WB (D-03-CORR / D-07).
* LIQ-03 — the forced cover reuses ``FillStatus.EXECUTED`` (NO new status), minting an
           admission-bypassing BUY-to-cover Order tagged ``OrderTriggerSource.LIQUIDATION``.

Discretion values (oracle-dark — synthetic instrument, NEVER BTCUSD)
--------------------------------------------------------------------
``LIQUSD`` declares ``max_leverage = 10``, ``maintenance_margin_rate = 0.01``,
``liquidation_fee_rate = 0.005``. The portfolio cap is 5; the signal requests leverage
20 (clamps to 5) sized by ``LeveredFraction(f=2)``. (Synthetic ticker — the spot oracle
stays byte-exact 134 / 46189.87730727451, D-11.)

================================ HAND COMPUTATION ================================

Price series (``bars.csv`` — daily, flat-OHLC so close == the unambiguous mark):

    bar  date         close
    0    2020-01-01   100
    1    2020-01-02   100     <- SELL-to-open decided (SHORT_ONLY, leverage 20 -> 5, f=2)
    2    2020-01-03   100     <- SELL fills next bar at close 100; SHORT opened
    3    2020-01-04   110     <- adverse mark UP, STILL HEALTHY (110 < 118.811 liq): no breach
    4    2020-01-05   125     <- BREACH: close 125 >= 118.811 liq price -> FORCED COVER

--- SELL fill (2020-01-03), fill price = 100 ---
    effective leverage = min(20, 10, 5) = 5; notional = f x equity = 2 x 10_000 = 20_000;
    quantity = 20_000 / 100 = 200; SHORT WB locked = 20_000 / 5 = 4_000.

--- corrected isolated SHORT liquidation price (D-01-CORR) ---
    margin_per_unit = WB / |size| = 4_000 / 200 = 20
    liq_price = (entry + margin_per_unit) / (1 + MMR)
              = (100 + 20) / (1 + 0.01) = 120 / 1.01 = 118.811881...

--- adverse mark (2020-01-04), mark 110 ---
    110 < 118.811881... -> NO breach; the short survives this bar (healthy).

--- BREACH (2020-01-05), close 125 >= 118.811881... -> FORCED COVER ---
    The forced cover settles AT the liq price, QUANTIZED to the LIQUSD price scale (0.01)
    at the FillEvent money boundary: fill_price = quantize(118.811881...) = 118.81.
    penalty (D-05) = fee_rate x |size| x liq_price = 0.005 x 200 x 118.811881... (full
        precision) = 118.811881..., carried on FillEvent.commission.
    Position.realised_pnl = short close PnL at the quantized fill price NET of penalty:
        (entry - fill_price) x |size| - penalty = (100 - 118.81) x 200 - 118.811881...
        = -3762.00 - 118.811881... = -3880.811881...
    The EXPLICIT D-07 clamp min(loss + penalty, WB) keeps the total loss <= WB = 4_000;
    here 3880.811881... <= 4_000 -> within the envelope (clamp not binding), and
    GUARANTEES equity never drops below -WB (DEF-01-C closed).
    final balance = 10_000 - 3880.811881... = 6119.188118... (> 0).
    The short covers to FLAT; the locked 4_000 is released; the forced-cover Order
    reaches FILLED in the mirror tagged OrderTriggerSource.LIQUIDATION.

================================ END HAND COMPUTATION ================================
"""

import pathlib
from decimal import Decimal

from itrader.core.enums import Side
from itrader.core.enums.order import OrderStatus, OrderType, OrderTriggerSource
from itrader.core.instrument import Instrument
from itrader.core.sizing import LeveredFraction, SignalIntent, TradingDirection
from itrader.strategy_handler.base import Strategy
from itrader.trading_system.backtest_trading_system import BacktestTradingSystem
from itrader.universe import Universe

HERE = pathlib.Path(__file__).resolve().parent

# Synthetic ticker — NEVER BTCUSD, so the spot oracle (134 / 46189.87730727451)
# cannot be touched by anything in this file.
_TICKER = "LIQUSD"
_CASH = 10_000

_INSTRUMENT_MAX_LEVERAGE = Decimal("10")
_MAINTENANCE_MARGIN_RATE = Decimal("0.01")
_LIQUIDATION_FEE_RATE = Decimal("0.005")
_PORTFOLIO_MAX_LEVERAGE = Decimal("5")

_REQUESTED_LEVERAGE = Decimal("20")             # above both caps -> clamps to 5
_KELLY_FRACTION = Decimal("2")

# --- Hand-computed liquidation literals (the PRIMARY oracle, D-08) ----------
_WB = Decimal("4000")
_SIZE = Decimal("200")
_ENTRY = Decimal("100")
# SHORT liq price = (entry + WB/|size|)/(1 + MMR) = (100 + 20)/1.01 (full precision).
_LIQ_PRICE = (_ENTRY + _WB / _SIZE) / (Decimal("1") + _MAINTENANCE_MARGIN_RATE)
_FILL_PRICE = Decimal("118.81")                 # quantized to the 0.01 price scale
_PENALTY = _LIQUIDATION_FEE_RATE * _SIZE * _LIQ_PRICE
# Position.realised_pnl = short close PnL at the quantized fill NET of penalty.
_FILL_PNL = (_ENTRY - _FILL_PRICE) * _SIZE      # -3762.00 at the fill price
_REALIZED_PNL = _FILL_PNL - _PENALTY            # -3880.811881... net of penalty


class _ForcedLiqShortStrategy(Strategy):
    """SELL-to-open a leveraged short on 2020-01-02 then HOLD — the position is force-
    covered by the engine on the breach bar (no strategy-side cover). Drives the NORMAL
    fan-out (no injected SignalEvent)."""

    name = "forced_liq_short"
    max_window = 100
    warmup = 0
    sizing_policy = LeveredFraction(fraction=_KELLY_FRACTION)
    direction = TradingDirection.SHORT_ONLY

    def __init__(self, timeframe: str, tickers: list[str]) -> None:
        super().__init__(timeframe=timeframe, tickers=list(tickers))

    def generate_signal(self, ticker: str) -> SignalIntent | None:
        date = self.now.tz_convert("UTC").strftime("%Y-%m-%d")
        if date == "2020-01-02":
            return SignalIntent(
                ticker=ticker,
                action=Side.SELL,
                order_type=OrderType.MARKET,
                leverage=_REQUESTED_LEVERAGE,
            )
        return None


def _liq_instrument() -> Instrument:
    """Oracle-dark synthetic instrument declaring the margin + liquidation params (D-06)."""
    return Instrument(
        symbol=_TICKER,
        price_precision=Decimal("0.01"),
        quantity_precision=Decimal("0.00000001"),
        min_order_size=None,
        maintenance_margin_rate=_MAINTENANCE_MARGIN_RATE,
        max_leverage=_INSTRUMENT_MAX_LEVERAGE,
        settles_funding=False,
        liquidation_fee_rate=_LIQUIDATION_FEE_RATE,
    )


def _build_liq_system():
    """Build the real backtest engine, enable margin + short-selling (white-box), wire
    the oracle-dark margin Instrument on the three set_universe seams. The
    set_order_storage write-seam (04-03, LIQ-03) is wired at construction by compose.py."""
    system = BacktestTradingSystem(
        exchange="csv",
        csv_paths={_TICKER: HERE / "bars.csv"},
        start_date="2020-01-01",
        end_date="2020-01-05",
    )
    sh = system.strategies_handler
    sh._allow_short_selling = True
    sh._enable_margin = True
    strategy = _ForcedLiqShortStrategy(timeframe="1d", tickers=[_TICKER])
    sh.add_strategy(strategy)
    portfolio_id = system.portfolio_handler.add_portfolio(
        user_id=1, name="forced_liq_short_pf", exchange="csv", cash=_CASH)
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

    runner = system.runner
    runner._initialise_backtest_session()
    universe = Universe(members=[_TICKER], instrument_map={_TICKER: _liq_instrument()})
    system.execution_handler.exchanges["simulated"].set_universe(universe)
    system.order_handler.set_universe(universe)
    system.portfolio_handler.set_universe(universe)

    return system, portfolio, portfolio_id


def test_forced_liq_short_scenario():
    """Forced-liquidation SHORT full run-path e2e (white-box, PRIMARY oracle D-08). The
    short survives the adverse mark (110 < 118.811 liq floor) and is FORCE-COVERED on
    the breach bar (close 125) at the corrected isolated liq price, with the penalty on
    commission, the WB-capped loss, and the LIQUIDATION-tagged forced-cover Order FILLED
    in the mirror. See the module docstring for the full arithmetic."""
    system, portfolio, portfolio_id = _build_liq_system()
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
            "equity": handler.total_equity(portfolio_id),
        }

    engine.order_handler.expire_all_resting()
    engine.event_handler.process_events()

    # --- SELL fill (2020-01-03): SHORT 200 @ 100; WB locked = 20000/5 = 4000 ----------
    opened = snaps["2020-01-03"]
    assert opened["side"] == "SHORT", "SELL-to-open opened a SHORT"
    assert opened["qty"] == Decimal("200"), "LeveredFraction sized notional = f x equity"
    assert opened["locked"] == Decimal("4000"), "WB = aggregate_notional / leverage = 4000"

    # --- adverse mark UP (2020-01-04, 110): STILL HEALTHY (110 < 118.811 liq floor) ----
    healthy = snaps["2020-01-04"]
    assert healthy["qty"] == Decimal("200"), "survives the adverse mark (no breach)"
    assert healthy["side"] == "SHORT"
    assert healthy["locked"] == Decimal("4000")

    # --- BREACH (2020-01-05, 125 >= 118.811): FORCED COVER ----------------------------
    liq = snaps["2020-01-05"]
    assert liq["qty"] is None, "LIQ-01: short force-covered on the breach bar"
    assert liq["side"] is None
    assert liq["locked"] == Decimal("0"), "locked margin released on liquidation"
    # DEF-01-C: equity floored, never impossibly negative; here it stays POSITIVE.
    assert liq["equity"] > Decimal("0"), "DEF-01-C: equity floored"
    assert liq["equity"] >= -_WB, "DEF-01-C: equity never below -WB"

    # --- the closed position carries the hand-computed forced-cover PnL ---------------
    closed = portfolio.closed_positions
    assert len(closed) == 1
    assert closed[0].side.name == "SHORT"
    # Realized PnL = short close PnL at the quantized liq fill 118.81 NET of penalty:
    # (100 - 118.81) x 200 - penalty = -3762.00 - 118.811... = -3880.811881...
    assert closed[0].realised_pnl == _REALIZED_PNL, "(100 - 118.81) x 200 - penalty"
    total_loss = -_REALIZED_PNL
    assert total_loss <= _WB, "D-07: loss + penalty <= WB (DEF-01-C closed)"
    assert cash.balance == _CASH - total_loss, "final balance = 10000 - total loss"

    # --- LIQ-03: the forced-cover Order is FILLED + tagged LIQUIDATION -----------------
    orders = system.order_handler.get_orders_by_ticker(_TICKER, portfolio_id)
    assert len(orders) == 2
    assert {o.status for o in orders} == {OrderStatus.FILLED}, "both orders FILLED"
    liq_orders = [
        o for o in orders
        if any(sc.triggered_by == OrderTriggerSource.LIQUIDATION for sc in o.state_changes)
    ]
    assert len(liq_orders) == 1, "exactly one LIQUIDATION-tagged forced-cover Order"
    liq_order = liq_orders[0]
    assert liq_order.action == Side.BUY, "a short is closed by a BUY-to-cover"
    assert liq_order.quantity == Decimal("200"), "forced-cover qty = |net_quantity|"
    assert liq_order.status == OrderStatus.FILLED, "LIQ-03: EXECUTED -> FILLED in the mirror"
    assert liq_order.price == _FILL_PRICE, "settled at the quantized isolated liq price 118.81"

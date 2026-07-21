"""FROZEN forced-liquidation LONG white-box e2e — the P4 liquidation core (D-08).

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
liq price, the breach-bar forced-close FillEvent, the penalty on commission, the
WB-bounded loss (fill-at-liq-price), the LIQUIDATION-tagged forced-close Order reaching FILLED in the
mirror) that the trades/equity/summary golden CSVs do not capture. It drives the
engine's real BAR -> (liquidation pass) -> FILL -> PORTFOLIO path and asserts on the
live read-model + cash/position state.

The hand-computed closed-form is the PRIMARY oracle for the liquidation event (D-08);
backtesting.py / backtrader give directional corroboration only (the leveraged-long-
into-liquidation runner under scripts/crossval/). This crafted scenario is THAT oracle.
=====================================================================================

What it exercises (LIQ-01 / LIQ-02 / LIQ-03, end-to-end — closes DEF-01-C)
-------------------------------------------------------------------------
* LIQ-01 — a per-bar maintenance-margin breach check on the BAR route force-closes the
           breaching LONG position at the corrected isolated liquidation price
           (D-01-CORR) the moment the bar CLOSE crosses it.
* LIQ-02 — a configurable liquidation penalty rides ``FillEvent.commission``
           (``fee_rate x |size| x liq_price``, D-05), and the total realized loss is
           bounded at the allocated isolated margin WB by SETTLING THE FORCED CLOSE AT
           THE LIQ PRICE (fill-at-liq-price, D-03 automatic-floor reading / D-07) so
           equity can never drift impossibly negative (DEF-01-C closed). There is NO
           explicit min(loss + penalty, WB) clamp — the floor is the fill (CR-01).
* LIQ-03 — the forced close reuses ``FillStatus.EXECUTED`` (NO new status), minting an
           admission-bypassing close Order tagged ``OrderTriggerSource.LIQUIDATION`` that
           reconciles EXECUTED -> FILLED through the existing mirror path.

Discretion values (oracle-dark — synthetic instrument, NEVER BTCUSD)
--------------------------------------------------------------------
The synthetic ticker ``LIQUSD`` (NEVER BTCUSD — the spot oracle must stay byte-exact,
134 / 46189.87730727451, D-11) declares ``max_leverage = Decimal("10")``,
``maintenance_margin_rate = Decimal("0.01")`` (1% flat MMR), and a realistic crypto
``liquidation_fee_rate = Decimal("0.005")`` (0.5%). The portfolio cap is 5; the signal
requests leverage 20 (clamps to 5) sized by ``LeveredFraction(f=2)``.

================================ HAND COMPUTATION ================================

Price series (``bars.csv`` — daily, flat-OHLC so close == the unambiguous mark):

    bar  date         close
    0    2020-01-01   100
    1    2020-01-02   100     <- BUY decided (leverage 20 -> clamps to 5, LeveredFraction f=2)
    2    2020-01-03   100     <- BUY fills next bar at close 100 (look-ahead-safe); LONG opened
    3    2020-01-04    90     <- adverse mark, STILL HEALTHY (90 > 80.808 liq floor): no breach
    4    2020-01-05    75     <- BREACH: close 75 <= 80.808 liq price -> FORCED LIQUIDATION

--- BUY fill (2020-01-03), fill price = 100 ---
    effective leverage = min(20, 10, 5) = 5; notional = f x equity = 2 x 10_000 = 20_000;
    quantity = 20_000 / 100 = 200; position-life locked isolated margin WB =
        aggregate_notional / leverage = 20_000 / 5 = 4_000.

--- corrected isolated LONG liquidation price (D-01-CORR) ---
    margin_per_unit = WB / |size| = 4_000 / 200 = 20
    liq_price = (entry - margin_per_unit) / (1 - MMR)
              = (100 - 20) / (1 - 0.01) = 80 / 0.99 = 80.808080...
    (NOT the bankruptcy price entry x (1 - 1/L) = 80; the maintenance liq price retains
     the /(1 - MMR) buffer — D-03-CORR.)

--- adverse mark (2020-01-04), mark 90 ---
    90 > 80.808... -> NO breach; the position survives this bar (healthy).

--- BREACH (2020-01-05), close 75 <= 80.808... -> FORCED LIQUIDATION ---
    The forced close settles AT the liq price, QUANTIZED to the LIQUSD price scale
    (0.01) at the FillEvent money boundary: fill_price = quantize(80.808080...) = 80.81.
    penalty (D-05) = fee_rate x |size| x liq_price = 0.005 x 200 x 80.808080... (full
        precision, BEFORE quantization) = 80.808080..., carried on FillEvent.commission.
    Position.realised_pnl = close PnL at the quantized fill price NET of the penalty:
        (fill_price - entry) x |size| - penalty = (80.81 - 100) x 200 - 80.808080...
        = -3838.00 - 80.808080... = -3918.808080...
    Fill-at-liq-price (D-03 automatic-floor reading / D-07) keeps the total loss <= WB = 4_000:
    the close settles AT the liq price (~80.81), never below it (even though the breach bar
    gapped to close=75, below the 80.808... floor — the engine fills at the floor, not the gap).
    Here total loss 3918.808080... <= 4_000 -> within the envelope. There is NO explicit
    min(loss + penalty, WB) clamp; settling at the floor GUARANTEES equity never drops below
    -WB (DEF-01-C). (CR-01)
    final balance = 10_000 - 3918.808080... = 6081.191919... (> 0; DEF-01-C closed).
    The position closes; the locked 4_000 is released; the forced-close Order reaches
    FILLED in the mirror tagged OrderTriggerSource.LIQUIDATION.

================================ END HAND COMPUTATION ================================
"""

import pathlib
from decimal import Decimal

from itrader.config import PortfolioConfig, get_portfolio_preset
from itrader.outils.dict_merge import recursive_merge
from itrader.core.enums import Side
from itrader.core.enums.order import OrderStatus, OrderType, OrderTriggerSource
from itrader.core.instrument import Instrument
from itrader.core.sizing import LeveredFraction, SignalIntent, TradingDirection
from itrader.strategy_handler.base import Strategy
from itrader.trading_system.backtest_trading_system import BacktestTradingSystem
from itrader.universe import Universe
from itrader.execution_handler.execution_handler import DEFAULT_ACCOUNT_ID

HERE = pathlib.Path(__file__).resolve().parent

# Synthetic ticker — NEVER BTCUSD, so the spot oracle (134 / 46189.87730727451)
# cannot be touched by anything in this file.
_TICKER = "LIQUSD"
_CASH = 10_000

_INSTRUMENT_MAX_LEVERAGE = Decimal("10")        # per-symbol venue ceiling
_MAINTENANCE_MARGIN_RATE = Decimal("0.01")      # 1% flat MMR
_LIQUIDATION_FEE_RATE = Decimal("0.005")        # 0.5% forced-close penalty (D-05)
_PORTFOLIO_MAX_LEVERAGE = Decimal("5")          # account-wide cap

_REQUESTED_LEVERAGE = Decimal("20")             # above both caps -> clamps to 5
_KELLY_FRACTION = Decimal("2")                  # f = 2 (> 1, valid only with margin)

# --- Hand-computed liquidation literals (the PRIMARY oracle, D-08) ----------
_WB = Decimal("4000")                           # locked isolated margin = 20000 / 5
_SIZE = Decimal("200")
_ENTRY = Decimal("100")
# liq price = (entry - WB/|size|)/(1 - MMR) = (100 - 20)/0.99 (full precision).
_LIQ_PRICE = (_ENTRY - _WB / _SIZE) / (Decimal("1") - _MAINTENANCE_MARGIN_RATE)
# Quantized to the LIQUSD price scale (0.01) at the FillEvent boundary.
_FILL_PRICE = Decimal("80.81")
# Penalty rides FillEvent.commission: fee_rate x |size| x liq_price (UNquantized).
_PENALTY = _LIQUIDATION_FEE_RATE * _SIZE * _LIQ_PRICE
# Position.realised_pnl is the close PnL at the quantized fill price NET of the penalty
# commission: (fill - entry) x size - penalty (D-08 — penalty folds into the close PnL,
# NOT a separate carry line). (80.81 - 100) x 200 - 80.808... = -3918.808080...
_FILL_PNL = (_FILL_PRICE - _ENTRY) * _SIZE                      # -3838.00 at the fill price
_REALIZED_PNL = _FILL_PNL - _PENALTY                            # -3918.808080... net of penalty


class _ForcedLiqLongStrategy(Strategy):
    """BUY-to-open a leveraged long on 2020-01-02 then HOLD — the position is force-
    liquidated by the engine on the breach bar (no strategy-side close). Drives the
    NORMAL fan-out (no injected SignalEvent)."""

    name = "forced_liq_long"
    max_window = 100
    warmup = 0
    sizing_policy = LeveredFraction(fraction=_KELLY_FRACTION)
    direction = TradingDirection.LONG_ONLY

    def __init__(self, timeframe: str, tickers: list[str]) -> None:
        super().__init__(timeframe=timeframe, tickers=list(tickers))

    def generate_signal(self, ticker: str) -> SignalIntent | None:
        date = self.now.tz_convert("UTC").strftime("%Y-%m-%d")
        if date == "2020-01-02":
            return SignalIntent(
                ticker=ticker,
                action=Side.BUY,
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
    """Build the real backtest engine, enable margin (white-box), wire the oracle-dark
    margin Instrument on the three set_universe seams, and return the engine + portfolio
    handle ready to drive tick-by-tick. The set_order_storage write-seam (04-03, LIQ-03)
    is wired at construction by compose.py."""
    system = BacktestTradingSystem(
        exchange="csv",
        csv_paths={_TICKER: HERE / "bars.csv"},
        start_date="2020-01-01",
        end_date="2020-01-05",
    )
    strategy = _ForcedLiqLongStrategy(timeframe="1d", tickers=[_TICKER])
    system.strategies_handler.add_strategy(strategy)
    portfolio_id = system.portfolio_handler.add_portfolio(
        # 01-03 D-03 (sibling 01-03b finding): the account leaf is selected at
        # CONSTRUCTION from enable_margin; the post-construction config swap below
        # refines the rest but no longer rebuilds the leaf — so margin must be on
        # in the constructor config to get a SimulatedMarginAccount.
        name="forced_liq_long_pf", exchange="csv", cash=_CASH,
        portfolio_config=PortfolioConfig.model_validate(recursive_merge(
            get_portfolio_preset("default").model_dump(),
            {"trading_rules": {"enable_margin": True}})))
    strategy.subscribe_portfolio(portfolio_id)

    portfolio = system.portfolio_handler.get_portfolio(portfolio_id)
    portfolio.config = portfolio.config.model_copy(update={
        "trading_rules": portfolio.config.trading_rules.model_copy(update={
            "enable_margin": True,
            "max_leverage": _PORTFOLIO_MAX_LEVERAGE,
        })})
    order_manager = system.order_handler.order_manager
    order_manager.admission_manager._enable_margin = True
    order_manager.admission_manager._portfolio_max_leverage = _PORTFOLIO_MAX_LEVERAGE
    order_manager.order_validator.enable_margin = True

    runner = system.runner
    runner._initialise_backtest_session()
    universe = Universe(members=[_TICKER], instrument_map={_TICKER: _liq_instrument()})
    system.execution_handler.exchanges[("simulated", DEFAULT_ACCOUNT_ID)].set_universe(universe)
    system.order_handler.set_universe(universe)
    system.portfolio_handler.set_universe(universe)

    return system, portfolio, portfolio_id


def test_forced_liq_long_scenario():
    """Forced-liquidation LONG full run-path e2e (white-box, PRIMARY oracle D-08).
    The position survives the adverse mark (90 > 80.808 liq floor) and is FORCE-
    LIQUIDATED on the breach bar (close 75) at the corrected isolated liq price, with
    the penalty on commission, the WB-bounded loss (fill-at-liq-price), and the LIQUIDATION-tagged forced-
    close Order FILLED in the mirror. See the module docstring for the full arithmetic."""
    system, portfolio, portfolio_id = _build_liq_system()
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
            "equity": handler.total_equity(portfolio_id),
        }

    engine.order_handler.expire_all_resting()
    engine.event_handler.process_events()

    # --- BUY fill (2020-01-03): LONG 200 @ 100; WB locked = 20000/5 = 4000 -----------
    opened = snaps["2020-01-03"]
    assert opened["qty"] == Decimal("200"), "LeveredFraction sized notional = f x equity"
    assert opened["locked"] == Decimal("4000"), "WB = aggregate_notional / leverage = 4000"
    assert opened["available"] == Decimal("6000"), "available = 10000 - 4000 locked"

    # --- adverse mark (2020-01-04, 90): STILL HEALTHY (90 > 80.808 liq floor) ---------
    healthy = snaps["2020-01-04"]
    assert healthy["qty"] == Decimal("200"), "survives the adverse mark (no breach)"
    assert healthy["locked"] == Decimal("4000")

    # --- BREACH (2020-01-05, 75 <= 80.808): FORCED LIQUIDATION ------------------------
    liq = snaps["2020-01-05"]
    # The position is force-closed on the breach bar.
    assert liq["qty"] is None, "LIQ-01: position force-liquidated on the breach bar"
    # The locked isolated margin is fully released on the forced close.
    assert liq["locked"] == Decimal("0"), "locked margin released on liquidation"
    # DEF-01-C: equity never drifts below -WB. Here it stays POSITIVE (the loss is well
    # within the 10000 wallet + 4000 lock envelope).
    assert liq["equity"] > Decimal("0"), "DEF-01-C: equity floored, never impossibly negative"
    assert liq["equity"] >= -_WB, "DEF-01-C: equity never below -WB"

    # --- the closed position carries the hand-computed forced-close PnL ---------------
    closed = portfolio.closed_positions
    assert len(closed) == 1
    assert closed[0].side.name == "LONG"
    # Realized PnL = close PnL at the quantized liq fill price 80.81 NET of the penalty
    # commission: (80.81 - 100) x 200 - penalty = -3838.00 - 80.808... = -3918.808080...
    assert closed[0].realised_pnl == _REALIZED_PNL, "(80.81 - 100) x 200 - penalty"
    # The total loss magnitude (close loss + penalty) stays within WB (D-07 envelope).
    # The bound comes from SETTLING THE CLOSE AT THE LIQ PRICE (fill-at-liq-price, D-03
    # automatic-floor reading): the breach bar gapped to close=75, BELOW the 80.808 floor,
    # yet the position closed AT the liq price (~80.81), never below it. There is NO
    # explicit min(loss + penalty, WB) clamp — settling at the floor IS the guarantee
    # (CR-01). final balance = 10000 - 3918.808... = 6081.191... > 0 (DEF-01-C closed).
    total_loss = -_REALIZED_PNL
    assert total_loss <= _WB, "D-07: loss + penalty <= WB (DEF-01-C closed)"
    assert cash.balance == _CASH - total_loss, "final balance = 10000 - total loss"

    # --- LIQ-03: the forced-close Order is FILLED + tagged LIQUIDATION -----------------
    orders = system.order_handler.get_orders_by_ticker(_TICKER, portfolio_id)
    # Two orders: the strategy BUY entry + the forced-close SELL liquidation.
    assert len(orders) == 2
    assert {o.status for o in orders} == {OrderStatus.FILLED}, "both orders FILLED"
    # A liquidation order is identified by its LIQUIDATION-tagged state change (D-04 —
    # the forced-close trigger source rides the OrderStateChange audit trail).
    liq_orders = [
        o for o in orders
        if any(sc.triggered_by == OrderTriggerSource.LIQUIDATION for sc in o.state_changes)
    ]
    assert len(liq_orders) == 1, "exactly one LIQUIDATION-tagged forced-close Order"
    liq_order = liq_orders[0]
    assert liq_order.action == Side.SELL, "a long is closed by a SELL"
    assert liq_order.quantity == Decimal("200"), "forced-close qty = |net_quantity|"
    assert liq_order.status == OrderStatus.FILLED, "LIQ-03: EXECUTED -> FILLED in the mirror"
    # The forced close settled AT the quantized liq price (NOT next-bar-open, D-04).
    assert liq_order.price == _FILL_PRICE, "settled at the quantized isolated liq price 80.81"

"""FROZEN leveraged-long e2e — the Phase-2 cross-cutting margin-core proof (D-17).

============================ FROZEN — ACCOUNTING-CORE GOLDEN ==========================
FREEZE PROVENANCE (D-10/D-12): frozen as part of the single accounting-core golden at
the owner-gated 04-05 sign-off — Approved-by: tiziaco (tiziano.iaco@gmail.com),
2026-06-16. The freeze set is ALL parked P2/P3 scenarios (levered_long, short_roundtrip,
short_carry, partial_cover) + the new P4 liquidation scenarios (forced_liq_long,
forced_liq_short, levered_long_into_liquidation) frozen as ONE accounting-core golden
(cross-validated vs backtesting.py + backtrader; see tests/golden/CROSS-VALIDATION-ACCOUNTING.md).
Every number asserted below is a HAND-COMPUTED literal with the arithmetic shown
inline. This test does NOT use the golden-diff harness (``run_scenario`` / ``golden/``)
precisely because the load-bearing
assertions are margin INTERNALS (initial-margin reservation, position-life locked
margin, maintenance_margin / margin_ratio) that the trades/equity/summary golden CSVs do
not capture. It drives the engine's real SIGNAL -> ORDER -> FILL -> PORTFOLIO path and
asserts on the live read-model + cash/position state.
=====================================================================================

What it exercises (the five Phase-2 requirements, end-to-end)
------------------------------------------------------------
* MARGIN-01  — opening reserves ``initial_margin = notional / L`` (admission gate), and
               the lock-and-settle lifecycle locks margin for the position's life and
               releases it + settles realized PnL on close.
* LEV-01     — the leverage cap ``effective = min(signal, instr.max_lev, pf.max_lev)``.
* LEV-02     — ``LeveredFraction(f)`` resolves ``notional = f x total_equity`` (f > 1
               permitted only under ``enable_margin``).
* LEV-03     — strategy-declared leverage flows end-to-end through the NORMAL run path:
               SignalIntent.leverage -> SignalEvent -> Order -> OrderEvent -> FillEvent
               -> Transaction -> Position. The position-life locked margin
               (aggregate_notional / position.leverage) EQUALS the admission reservation
               (notional / effective_leverage).
* MARGIN-03  — ``maintenance_margin`` / ``margin_ratio`` computed on demand via the
               read-model, reading honestly (no clamp) even on an adverse mark (D-16).

Discretion values (A5 — oracle-dark, realistic crypto defaults; documented per CONTEXT)
---------------------------------------------------------------------------------------
The synthetic instrument ``LEVUSD`` (NEVER BTCUSD — the spot oracle must stay
byte-exact, 134 / 46189.87730727451) declares:
    max_leverage             = Decimal("10")      # per-symbol venue ceiling
    maintenance_margin_rate  = Decimal("0.01")    # 1% flat MMR
The portfolio's account-wide cap is ``max_leverage = Decimal("5")``.

TWO HONEST INTEGRATION FINDINGS surfaced by the 02-06 run are now CLOSED by 02-07
(LEV-03):

  FINDING A (CLOSED, 02-07 Task 1) — the strategy -> SignalEvent fan-out
  (``StrategiesHandler.calculate_signals``) now carries ``SignalIntent.leverage`` onto
  the ``SignalEvent``. This e2e drives leverage through the NORMAL production fan-out: a
  strategy returns a leverage-carrying ``SignalIntent`` at the decision bars and the BAR
  route fans it out as a ``SignalEvent`` — no hand-built ``SignalEvent`` is injected onto
  the queue.

  FINDING B (CLOSED, 02-07 Task 2) — the effective leverage now flows Order ->
  OrderEvent -> FillEvent -> Transaction -> Position, so ``Position.leverage`` is the
  admission-clamped effective leverage (5), NOT the default 1. The POSITION-LIFE locked
  margin (``aggregate_notional / position.leverage`` = 20000 / 5 = 4000) now EQUALS the
  ADMISSION reservation (``notional / effective_leverage`` = 20000 / 5 = 4000). The
  accounting is self-consistent under leverage > 1.

================================ HAND COMPUTATION ================================

Price series (``bars.csv`` — daily, tz-aware Open time, flat-OHLC so the close == the
mark unambiguously):

    bar  date         close
    0    2020-01-01   100
    1    2020-01-02   100     <- BUY decided here (leverage 20 requested, LeveredFraction f=2)
    2    2020-01-03   100     <- BUY fills next bar at close 100 (look-ahead-safe)
    3    2020-01-04    90     <- ADVERSE mark (price drops 10% — stays ABOVE the 80.808 liq
                              floor, so the P4 liquidation engine does NOT trigger; the
                              breach case is owned by levered_long_into_liquidation)
    4    2020-01-05   120     <- SELL (close) decided here
    5    2020-01-06   120     <- SELL fills next bar at close 120

Engine knobs: starting_cash = 10_000, exchange = None (zero fee / zero slippage —
commission is 0 everywhere so the margin math is the only moving part), enable_margin =
True, portfolio max_leverage = 5.

--- BUY decision (2020-01-02), decision price = 100 ---
LEV-01 leverage cap (D-04):
    requested = 20 ; instrument cap = 10 ; portfolio cap = 5
    effective = min(20, 10, 5) = 5
LEV-02 LeveredFraction sizing (D-07): notional = f x total_equity = 2 x 10_000 = 20_000
    quantity = notional / price = 20_000 / 100 = 200
MARGIN-01 admission reservation (D-08): initial_margin = notional / effective_leverage
    initial_margin = 20_000 / 5 = 4_000   (commission 0)
    available_balance: 10_000 - 4_000 = 6_000  <- asserted at bar 2020-01-02

--- BUY fill (2020-01-03), fill price = 100 ---
Order reservation (4_000, order-keyed) is RELEASED on the terminal fill; the position-life
locked margin (position-keyed) is locked. LEV-03 (Finding B CLOSED): position.leverage = 5,
so
    locked_margin = aggregate_notional / position.leverage = 20_000 / 5 = 4_000
        (EQUAL to the admission reservation — self-consistent under leverage > 1)
    available_balance = balance - reserved - locked = 10_000 - 0 - 4_000 = 6_000
    position: net_quantity = 200, aggregate_notional = 20_000, current_price = 100
MARGIN-03 read-model at price 100:
    maintenance_margin = mmr x |size| x price = 0.01 x 200 x 100 = 200
    total_equity = balance + market_value = 10_000 + 200 x 100 = 30_000
    margin_ratio = total_equity / maintenance = 30_000 / 200 = 150

--- ADVERSE mark (2020-01-04), mark price = 90 (D-16 honest-when-breached) ---
    maintenance_margin = 0.01 x 200 x 90 = 180
    total_equity = 10_000 + 200 x 90 = 28_000
    margin_ratio = 28_000 / 180 = 155.5555...  (read HONESTLY off the adverse mark, no clamp)
    locked_margin stays 4_000 (locked off the ENTRY notional at open, not the mark)
    available_balance = balance - locked = 10_000 - 4_000 = 6_000 (free margin POSITIVE —
        the 4000 lock is well within the 10000 cash floor; the position is healthy)
    The mark 90 stays ABOVE the corrected isolated long liq price 80.808080... (P4,
        D-01-CORR: (entry - WB/|size|)/(1 - MMR) = (100 - 4000/200)/0.99 = 80/0.99),
        so the P4 liquidation engine finds NO breach here — the position survives. (The
        original Phase-2 mark of 80 sat exactly AT the bankruptcy price entry x (1 - 1/L)
        = 100 x 0.8 = 80, which is BELOW 80.808 and now liquidates under the closed
        DEF-01-C engine; the deep-mark breach case is owned by the dedicated
        levered_long_into_liquidation leaf.)

--- SELL fill (2020-01-06), fill price = 120 ---
MARGIN-01 lock-and-settle close:
    realized_pnl = (exit - entry) x quantity = (120 - 100) x 200 = 4_000
    locked margin fully RELEASED -> 0
    final balance = 10_000 + 4_000 = 14_000
    final available_balance = 14_000 (reservation + lock both gone)
    final total_equity = 14_000 (flat — no open position)

================================ END HAND COMPUTATION ================================
"""

import pathlib
from decimal import Decimal

import pytest

from itrader.config import PortfolioConfig, deep_merge, get_portfolio_preset
from itrader.core.enums import Side
from itrader.core.enums.order import OrderStatus, OrderType
from itrader.core.instrument import Instrument
from itrader.core.sizing import LeveredFraction, SignalIntent, TradingDirection
from itrader.strategy_handler.base import Strategy
from itrader.trading_system.backtest_trading_system import BacktestTradingSystem
from itrader.universe import Universe

HERE = pathlib.Path(__file__).resolve().parent

# A5 (discretion, oracle-dark): a SYNTHETIC ticker — NEVER BTCUSD, so the spot oracle
# (134 / 46189.87730727451) cannot be touched by anything in this file.
_TICKER = "LEVUSD"
_CASH = 10_000

# Discretion crypto-default instrument margin params (A5 — realistic, oracle-dark).
_INSTRUMENT_MAX_LEVERAGE = Decimal("10")        # per-symbol venue ceiling
_MAINTENANCE_MARGIN_RATE = Decimal("0.01")      # 1% flat MMR
_PORTFOLIO_MAX_LEVERAGE = Decimal("5")          # account-wide cap

# Signal knobs (D-03 leverage scalar + D-07 LeveredFraction f).
_REQUESTED_LEVERAGE = Decimal("20")             # above both caps -> clamps to 5
_KELLY_FRACTION = Decimal("2")                  # f = 2 (> 1, valid only with enable_margin)


class _LevLongStrategy(Strategy):
    """A minimal strategy driving the leveraged long through the NORMAL fan-out
    (LEV-03 / Finding A CLOSED).

    It returns a leverage-carrying ``SignalIntent`` at the decision bars — BUY on
    2020-01-02 (leverage 20 requested, LeveredFraction f=2) and SELL on 2020-01-05 —
    so ``StrategiesHandler.calculate_signals`` fans it out as a ``SignalEvent``
    carrying ``leverage`` through the production path. NO hand-built SignalEvent is
    injected onto the queue."""

    name = "lev_long"
    # warmup 0 so the handler reaches generate_signal from the first tick; a wide
    # max_window keeps the whole 6-bar series visible.
    max_window = 100
    warmup = 0
    sizing_policy = LeveredFraction(fraction=_KELLY_FRACTION)
    direction = TradingDirection.LONG_ONLY

    def __init__(self, timeframe: str, tickers: list[str]) -> None:
        super().__init__(timeframe=timeframe, tickers=list(tickers))

    def generate_signal(self, ticker: str) -> SignalIntent | None:
        # self.now is the decision-bar timestamp (window.index[-1], D-06).
        date = self.now.tz_convert("UTC").strftime("%Y-%m-%d")
        if date == "2020-01-02":
            # BUY carrying the strategy-declared leverage (D-03) — the fan-out
            # threads it onto the SignalEvent (LEV-03 Task 1).
            return SignalIntent(
                ticker=ticker,
                action=Side.BUY,
                order_type=OrderType.MARKET,
                leverage=_REQUESTED_LEVERAGE,
            )
        if date == "2020-01-05":
            # SELL (full exit) — leverage is irrelevant on the close, but it rides
            # the same normal fan-out.
            return SignalIntent(
                ticker=ticker,
                action=Side.SELL,
                order_type=OrderType.MARKET,
            )
        return None


def _levered_instrument() -> Instrument:
    """The oracle-dark synthetic instrument carrying the discretion margin params (A5)."""
    return Instrument(
        symbol=_TICKER,
        price_precision=Decimal("0.01"),
        quantity_precision=Decimal("0.00000001"),
        min_order_size=None,
        maintenance_margin_rate=_MAINTENANCE_MARGIN_RATE,
        max_leverage=_INSTRUMENT_MAX_LEVERAGE,
        settles_funding=False,
    )


def _build_margin_system():
    """Build the real backtest engine, enable margin (white-box — the factory exposes no
    per-portfolio margin knob), wire the oracle-dark margin Universe, and return the
    engine + portfolio handle ready to drive tick-by-tick."""
    system = BacktestTradingSystem(
        exchange="csv",
        csv_paths={_TICKER: HERE / "bars.csv"},
        start_date="2020-01-01",
        end_date="2020-01-06",
    )
    strategy = _LevLongStrategy(timeframe="1d", tickers=[_TICKER])
    system.strategies_handler.add_strategy(strategy)
    portfolio_id = system.portfolio_handler.add_portfolio(
        # 01-03 D-03 (sibling 01-03b finding): the account leaf is selected at
        # CONSTRUCTION from enable_margin; the post-construction config swap below
        # refines the rest but no longer rebuilds the leaf — so margin must be on
        # in the constructor config to get a SimulatedMarginAccount.
        name="levered_long_pf", exchange="csv", cash=_CASH,
        portfolio_config=PortfolioConfig.model_validate(deep_merge(
            get_portfolio_preset("default").model_dump(),
            {"trading_rules": {"enable_margin": True}})))
    strategy.subscribe_portfolio(portfolio_id)

    portfolio = system.portfolio_handler.get_portfolio(portfolio_id)
    # Enable margin on the settlement branch (D-09) — the portfolio reads its own config
    # in process_transaction. Pydantic models are immutable, so swap via model_copy.
    portfolio.config = portfolio.config.model_copy(update={
        "trading_rules": portfolio.config.trading_rules.model_copy(update={
            "enable_margin": True,
            "max_leverage": _PORTFOLIO_MAX_LEVERAGE,
        })})
    # Enable the order-domain margin arm (D-04/D-08): the admission leverage cap +
    # notional/L reservation, and let the validator defer the full-notional cash check to
    # the admission gate (it is the cash authority under margin).
    order_manager = system.order_handler.order_manager
    order_manager.admission_manager._enable_margin = True
    order_manager.admission_manager._portfolio_max_leverage = _PORTFOLIO_MAX_LEVERAGE
    order_manager.order_validator.enable_margin = True

    # Initialise the session (Trap-4 ordering), THEN override the auto-derived Universe
    # (which would give LEVUSD the default max_leverage=1) with our oracle-dark margin
    # Instrument, mirroring the three set_universe seams the runner wires.
    runner = system.runner
    runner._initialise_backtest_session()
    universe = Universe(members=[_TICKER], instrument_map={_TICKER: _levered_instrument()})
    system.execution_handler.exchanges["simulated"].set_universe(universe)
    system.order_handler.set_universe(universe)
    system.portfolio_handler.set_universe(universe)

    return system, portfolio, portfolio_id


def test_levered_long_scenario_parked():
    """PARKED leveraged-long e2e (D-17): hand-computed margin-core assertions, NOT a
    frozen golden. Leverage travels the NORMAL production fan-out (LEV-03). See the
    module docstring for the full arithmetic derivation."""
    system, portfolio, portfolio_id = _build_margin_system()
    engine = system.engine
    handler = system.portfolio_handler
    cash = portfolio.account

    # Per-bar snapshots keyed by date so the assertions read against the hand-computation.
    snaps: dict[str, dict] = {}

    for time_event in engine.time_generator:
        date = time_event.time.tz_convert("UTC").strftime("%Y-%m-%d")
        engine.clock.set_time(time_event.time)
        engine.global_queue.put(time_event)
        # LEV-03 (Finding A CLOSED): NO signal injection — the BAR route runs the
        # strategy, which fans out a leverage-carrying SignalEvent through the
        # production path. The same tick processes SIGNAL -> ORDER -> FILL.
        engine.event_handler.process_events()
        for active in handler.get_active_portfolios():
            active.record_metrics(time_event.time)

        position = portfolio.get_open_position(_TICKER)
        snaps[date] = {
            "available": cash.available_balance,
            "locked": cash.locked_margin_total,
            "qty": None if position is None else position.net_quantity,
            "agg_notional": None if position is None else position.aggregate_notional,
            "leverage": None if position is None else position.leverage,
            "equity": handler.total_equity(portfolio_id),
            "maintenance": handler.maintenance_margin(portfolio_id),
            "margin_ratio": handler.margin_ratio(portfolio_id),
        }

    engine.order_handler.expire_all_resting()
    engine.event_handler.process_events()

    # --- LEV-01 cap + MARGIN-01 reservation (decision bar 2020-01-02) -----------------
    # effective leverage = min(20, 10, 5) = 5; notional = f x equity = 2 x 10_000 = 20_000;
    # initial_margin = notional / 5 = 4_000; available = 10_000 - 4_000 = 6_000.
    assert snaps["2020-01-02"]["available"] == Decimal("6000"), (
        "admission reserved initial_margin = notional/L = 20000/5 = 4000 "
        "(LEV-01 cap to 5, MARGIN-01 reservation)")
    # No position yet on the decision bar (market order fills NEXT bar — look-ahead safe).
    assert snaps["2020-01-02"]["qty"] is None

    # --- LEV-02 sizing + LEV-03 leverage + MARGIN-01 lock + MARGIN-03 (fill 2020-01-03) -
    fill = snaps["2020-01-03"]
    # LEV-02: quantity = (f x equity) / price = (2 x 10_000) / 100 = 200.
    assert fill["qty"] == Decimal("200"), "LeveredFraction sized notional = f x equity"
    # aggregate notional = 200 x 100 = 20_000.
    assert fill["agg_notional"] == Decimal("20000")
    # LEV-03 (Finding B CLOSED): the effective leverage 5 flows to the Position.
    assert fill["leverage"] == Decimal("5"), (
        "effective leverage min(20,10,5)=5 flows signal->...->position (LEV-03)")
    # Position-life locked margin = aggregate_notional / position.leverage = 20_000 / 5 =
    # 4_000 — EQUAL to the admission reservation (self-consistent under leverage > 1).
    assert fill["locked"] == Decimal("4000"), (
        "lock-and-settle locked margin = aggregate_notional / position.leverage = "
        "20000 / 5 = 4000 (== admission reservation; LEV-03 self-consistency)")
    # Free margin = balance - reserved - locked = 10_000 - 0 - 4_000 = 6_000 (POSITIVE —
    # the lock is well within the cash floor; the position is healthy).
    assert fill["available"] == Decimal("6000"), (
        "free margin = balance - locked = 10000 - 4000 = 6000")
    # MARGIN-03 at price 100: maintenance = 0.01 x 200 x 100 = 200; equity = 10_000 +
    # 200 x 100 = 30_000; ratio = 30_000 / 200 = 150.
    assert fill["maintenance"] == Decimal("200")
    assert fill["equity"] == Decimal("30000")
    assert fill["margin_ratio"] == Decimal("150")

    # --- MARGIN-03 honest-when-breached on an adverse mark (2020-01-04, price 90, D-16) -
    adverse = snaps["2020-01-04"]
    # maintenance = 0.01 x 200 x 90 = 180; equity = 10_000 + 200 x 90 = 28_000;
    # ratio = 28_000 / 180 = 155.5555... — read straight off the adverse mark, NO clamp.
    assert adverse["maintenance"] == Decimal("180")
    assert adverse["equity"] == Decimal("28000")
    assert adverse["margin_ratio"] == Decimal("28000") / Decimal("180")
    # Locked margin stays 4_000 (locked off the ENTRY notional at open, not the mark);
    # free margin stays POSITIVE 6_000 — the position is healthy on the adverse mark.
    # The mark 90 stays ABOVE the 80.808080... long liq floor (P4, D-01-CORR), so the
    # closed-DEF-01-C liquidation engine finds NO breach here and the position survives;
    # the deep-mark breach case is owned by the levered_long_into_liquidation leaf.
    assert adverse["locked"] == Decimal("4000")
    assert adverse["available"] == Decimal("6000")
    # The position is STILL OPEN after the adverse mark (NOT liquidated).
    assert adverse["qty"] == Decimal("200"), "survives the adverse mark (no P4 breach)"

    # --- MARGIN-01 lock-and-settle close (SELL fills 2020-01-06) ----------------------
    close = snaps["2020-01-06"]
    # No open position after the close; locked margin fully released; realized PnL
    # (120 - 100) x 200 = 4_000 settled to cash; final equity = 10_000 + 4_000 = 14_000.
    assert close["qty"] is None, "position fully closed"
    assert close["locked"] == Decimal("0"), "locked margin released on close (MARGIN-01)"
    assert close["available"] == Decimal("14000"), (
        "settled realized PnL 4000 + released reservation/lock -> 14_000")
    assert close["equity"] == Decimal("14000")
    # maintenance/margin_ratio collapse to the zero-maintenance sentinel when flat (D-13).
    assert close["maintenance"] == Decimal("0")
    assert close["margin_ratio"] == Decimal("0")

    # Realized PnL on the closed position is the hand-computed 4_000.
    closed = portfolio.closed_positions
    assert len(closed) == 1
    assert closed[0].side.name == "LONG"
    assert closed[0].realised_pnl == Decimal("4000"), "(120 - 100) x 200 = 4000"

    # Both orders filled in full (the leverage-carrying BUY was admitted under margin —
    # NOT rejected — proving the notional/L reservation was affordable, MARGIN-01/02).
    orders = system.order_handler.get_orders_by_ticker(_TICKER, portfolio_id)
    assert len(orders) == 2
    assert {o.status for o in orders} == {OrderStatus.FILLED}

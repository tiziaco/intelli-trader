"""PARKED leveraged-long e2e — the Phase-2 cross-cutting margin-core proof (D-17).

================================ PARKED — NOT A GOLDEN ================================
Every number asserted below is a HAND-COMPUTED literal with the arithmetic shown
inline. This scenario is **PARKED**, NOT frozen as a golden: Phase 2 freezes NO new
leveraged golden (D-16/D-17). The single owner-gated accounting-core re-baseline is at
Phase 4 / XVAL-01 (cross-validation + owner sign-off). This test does NOT use the
golden-diff harness (``run_scenario`` / ``golden/``) precisely because the load-bearing
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
* MARGIN-03  — ``maintenance_margin`` / ``margin_ratio`` computed on demand via the
               read-model, reading honestly (no clamp) even on an adverse mark (D-16).

Discretion values (A5 — oracle-dark, realistic crypto defaults; documented per CONTEXT)
---------------------------------------------------------------------------------------
The synthetic instrument ``LEVUSD`` (NEVER BTCUSD — the spot oracle must stay
byte-exact, 134 / 46189.87730727451) declares:
    max_leverage             = Decimal("10")      # per-symbol venue ceiling
    maintenance_margin_rate  = Decimal("0.01")    # 1% flat MMR
The portfolio's account-wide cap is ``max_leverage = Decimal("5")``.

TWO HONEST INTEGRATION FINDINGS surfaced by this end-to-end run (documented, NOT a
golden-freeze, NOT fixed here — this is a TEST-ONLY plan; both are logged as Phase-2
deviations for the owner):

  FINDING A — the strategy -> SignalEvent fan-out (``StrategiesHandler``) does NOT carry
  ``SignalIntent.leverage`` onto the ``SignalEvent`` (the field is dropped). A strategy
  therefore cannot today express leverage > 1 through the normal fan-out. This test works
  AROUND it by enqueuing a leverage-carrying ``SignalEvent`` directly onto the real
  ``global_queue`` at the decision bar, so the SIGNAL route dispatches it through the real
  admission/execution/portfolio handlers (the margin core under test).

  FINDING B — ``Transaction.new_transaction`` does NOT carry leverage from the
  ``FillEvent``, so ``Position.leverage`` defaults to ``Decimal("1")`` in the run path.
  Consequence: the ADMISSION reservation correctly divides by the effective leverage
  (notional / 5 = 4000), but the POSITION-LIFE locked margin uses ``position.leverage = 1``
  (= full notional 20000). Both are asserted HONESTLY below; the divergence is the
  documented finding (the lock-and-settle leverage divisor is a production gap, parked).

================================ HAND COMPUTATION ================================

Price series (``bars.csv`` — daily, tz-aware Open time, flat-OHLC so the close == the
mark unambiguously):

    bar  date         close
    0    2020-01-01   100
    1    2020-01-02   100     <- BUY decided here (leverage 20 requested, LeveredFraction f=2)
    2    2020-01-03   100     <- BUY fills next bar at close 100 (look-ahead-safe)
    3    2020-01-04    80     <- ADVERSE mark (price drops 20%)
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
locked margin (position-keyed) is locked. FINDING B: position.leverage = 1, so
    locked_margin = aggregate_notional / position.leverage = 20_000 / 1 = 20_000
    available_balance = balance - reserved - locked = 10_000 - 0 - 20_000 = -10_000
        (HONEST NEGATIVE free margin — D-16: no clamp, no force-close in Phase 2)
    position: net_quantity = 200, aggregate_notional = 20_000, current_price = 100
MARGIN-03 read-model at price 100:
    maintenance_margin = mmr x |size| x price = 0.01 x 200 x 100 = 200
    total_equity = balance + market_value = 10_000 + 200 x 100 = 30_000
    margin_ratio = total_equity / maintenance = 30_000 / 200 = 150

--- ADVERSE mark (2020-01-04), mark price = 80 (D-16 honest-when-breached) ---
    maintenance_margin = 0.01 x 200 x 80 = 160
    total_equity = 10_000 + 200 x 80 = 26_000
    margin_ratio = 26_000 / 160 = 162.5     (read HONESTLY off the adverse mark, no clamp)
    available_balance = -10_000 (still honestly negative — the position is underwater on
        free margin; equity stays positive only because the cash floor holds — D-16: Phase
        2 has NO force-close, the honest breach is the free-margin negative read)

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

from itrader.core.enums import Side
from itrader.core.enums.order import OrderStatus, OrderType
from itrader.core.instrument import Instrument
from itrader.core.sizing import LeveredFraction, TradingDirection
from itrader.events_handler.events import SignalEvent
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


class _LevUniverseStrategy(Strategy):
    """A minimal strategy that registers the ticker (for membership / feed precompute)
    and emits NOTHING — the leverage-carrying SignalEvents are injected directly onto
    the queue by the test (FINDING A work-around). It declares LeveredFraction sizing so
    the registered policy is margin-shaped, matching the injected signals."""

    name = "lev_universe"
    max_window = 100
    sizing_policy = LeveredFraction(fraction=_KELLY_FRACTION)
    direction = TradingDirection.LONG_ONLY

    def __init__(self, timeframe: str, tickers: list[str]) -> None:
        super().__init__(timeframe=timeframe, tickers=list(tickers))

    def generate_signal(self, ticker: str):  # noqa: D401 - emits nothing (injection path)
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


def _signal(time, action: Side, price: Decimal, strategy_id, portfolio_id) -> SignalEvent:
    """A leverage-carrying SignalEvent (FINDING A work-around — the strategy fan-out
    drops intent.leverage, so the margin core is driven by injecting the event the
    fan-out WOULD build if it threaded leverage, plus the D-03 leverage scalar)."""
    return SignalEvent(
        time=time,
        order_type=OrderType.MARKET,
        ticker=_TICKER,
        action=action,
        price=price,
        stop_loss=Decimal("0"),
        take_profit=Decimal("0"),
        strategy_id=strategy_id,
        portfolio_id=portfolio_id,
        sizing_policy=LeveredFraction(fraction=_KELLY_FRACTION),
        direction=TradingDirection.LONG_ONLY,
        leverage=_REQUESTED_LEVERAGE,
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
    strategy = _LevUniverseStrategy(timeframe="1d", tickers=[_TICKER])
    system.strategies_handler.add_strategy(strategy)
    portfolio_id = system.portfolio_handler.add_portfolio(
        user_id=1, name="levered_long_pf", exchange="csv", cash=_CASH)
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
    frozen golden. See the module docstring for the full arithmetic derivation."""
    system, portfolio, portfolio_id = _build_margin_system()
    engine = system.engine
    handler = system.portfolio_handler
    cash = portfolio.cash_manager

    # Per-bar snapshots keyed by date so the assertions read against the hand-computation.
    snaps: dict[str, dict] = {}

    for time_event in engine.time_generator:
        date = time_event.time.tz_convert("UTC").strftime("%Y-%m-%d")
        engine.clock.set_time(time_event.time)
        engine.global_queue.put(time_event)
        # Inject the leverage-carrying SignalEvents at the decision bars BEFORE the drain
        # so the same tick processes SIGNAL -> ORDER -> FILL through the real handlers.
        if date == "2020-01-02":
            engine.global_queue.put(_signal(
                time_event.time, Side.BUY, Decimal("100"),
                next(iter(engine.strategies_handler.strategies)).strategy_id,
                portfolio_id))
        elif date == "2020-01-05":
            engine.global_queue.put(_signal(
                time_event.time, Side.SELL, Decimal("120"),
                next(iter(engine.strategies_handler.strategies)).strategy_id,
                portfolio_id))
        engine.event_handler.process_events()
        for active in handler.get_active_portfolios():
            active.record_metrics(time_event.time)

        position = portfolio.get_open_position(_TICKER)
        snaps[date] = {
            "available": cash.available_balance,
            "locked": cash.locked_margin_total,
            "qty": None if position is None else position.net_quantity,
            "agg_notional": None if position is None else position.aggregate_notional,
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

    # --- LEV-02 sizing + MARGIN-01 lock + MARGIN-03 read-model (fill bar 2020-01-03) ---
    fill = snaps["2020-01-03"]
    # LEV-02: quantity = (f x equity) / price = (2 x 10_000) / 100 = 200.
    assert fill["qty"] == Decimal("200"), "LeveredFraction sized notional = f x equity"
    # aggregate notional = 200 x 100 = 20_000.
    assert fill["agg_notional"] == Decimal("20000")
    # FINDING B (documented): position.leverage defaults to 1 in the run path, so the
    # position-life locked margin = aggregate_notional / 1 = 20_000 (NOT 4_000).
    assert fill["locked"] == Decimal("20000"), (
        "lock-and-settle locked margin = aggregate_notional / position.leverage; "
        "position.leverage defaults to 1 in the run path (FINDING B), so = 20000")
    # D-16: free margin reads HONESTLY negative (no clamp, no force-close in Phase 2):
    # available = balance - reserved - locked = 10_000 - 0 - 20_000 = -10_000.
    assert fill["available"] == Decimal("-10000"), (
        "free margin reads honestly negative (D-16, no clamp)")
    # MARGIN-03 at price 100: maintenance = 0.01 x 200 x 100 = 200; equity = 10_000 +
    # 200 x 100 = 30_000; ratio = 30_000 / 200 = 150.
    assert fill["maintenance"] == Decimal("200")
    assert fill["equity"] == Decimal("30000")
    assert fill["margin_ratio"] == Decimal("150")

    # --- MARGIN-03 honest-when-breached on an adverse mark (2020-01-04, price 80, D-16) -
    adverse = snaps["2020-01-04"]
    # maintenance = 0.01 x 200 x 80 = 160; equity = 10_000 + 200 x 80 = 26_000;
    # ratio = 26_000 / 160 = 162.5 — read straight off the adverse mark, NO clamp (D-16).
    assert adverse["maintenance"] == Decimal("160")
    assert adverse["equity"] == Decimal("26000")
    assert adverse["margin_ratio"] == Decimal("162.5")
    # Free margin is STILL honestly negative on the adverse mark (the honest breach the
    # Phase-4 liquidation trigger will consume — D-16, DEF-01-C stays open until P4).
    assert adverse["available"] == Decimal("-10000")

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

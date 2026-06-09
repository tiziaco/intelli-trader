"""Run-path smoke test for the SMA_MACD backtest (D-16).

Behavior: import -> construct a CSV-fed ``TradingSystem`` -> add the SMA_MACD
strategy + a $10k portfolio -> run a short window of bars -> assert the run
completes AND produces at least one closed position with a non-zero quantity.

This is the Wave-0 gate for the ignition fixes (M1-01/02/04/05/06). It is EXPECTED
to be RED until the CSV feed (Plan 02) and the loop/sizing fixes (Plan 03) land —
do NOT force it green here. Because the project runs under
``filterwarnings=["error"]``, this test is also what catches the SMA_MACD
FutureWarning hard-error (Pitfall 3) and the tz-mismatch zero-trade case (Pitfall 6)
once the run actually executes.

Carries the ``unit`` marker automatically via the ``test_smoke`` path (auto-marking
in the root conftest) — do NOT hand-add markers.
"""

from itrader.strategy_handler.strategies.SMA_MACD_strategy import SMA_MACD_strategy


# Golden-run configuration (D-03/D-04/D-06).
TICKER = "BTCUSD"
TIMEFRAME = "1d"
CASH = 10_000


def test_backtest_smoke_produces_nonzero_trade(backtest_engine):
    """Import -> construct -> run -> assert completion + >=1 non-zero-qty trade.

    Uses the shared ``backtest_engine`` factory (conftest) for construction so the
    same wiring is reused once the CSV feed exists.
    """
    # Construct the CSV-fed engine (fees=0, slippage=0 per D-04).
    system = backtest_engine(
        ticker=TICKER,
        timeframe=TIMEFRAME,
        cash=CASH,
    )

    # Add the reference strategy on the daily timeframe, subscribed to BTCUSD.
    strategy = SMA_MACD_strategy(timeframe=TIMEFRAME, tickers=[TICKER])
    system.strategies_handler.add_strategy(strategy)

    # Add a single long-only portfolio with $10k starting cash.
    portfolio_id = system.portfolio_handler.add_portfolio(
        user_id=1,
        name="smoke_pf",
        exchange="csv",
        cash=CASH,
    )
    strategy.subscribe_portfolio(portfolio_id)

    # (a) The run completes without raising (FutureWarning -> hard error caught here).
    system.run(print_summary=False)

    # (b) At least one closed position exists, and at least one round-tripped a
    # non-zero traded quantity (proves the M1-06 sizing seam emitted real orders).
    # NOTE: a CLOSED position has net_quantity ~= 0 by construction (it closes when
    # buy_quantity and sell_quantity net to within tolerance), so the non-zero-quantity
    # assertion must check the *traded* size (buy/sell quantity), not the residual net.
    portfolio = system.portfolio_handler.get_portfolio(portfolio_id)
    closed_positions = portfolio.closed_positions
    assert closed_positions, "expected >=1 closed position from the smoke run"
    assert any(
        position.buy_quantity > 0 or position.sell_quantity > 0
        for position in closed_positions
    ), "expected >=1 closed position with a non-zero traded quantity (M1-06 sizing seam)"

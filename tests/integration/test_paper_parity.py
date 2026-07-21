"""The milestone Definition of Done: the paper-parity gate (PAPER-04 / COV-01).

In ONE test, drive BOTH the live-paper path and a fresh backtest run over the SAME
golden dataset, then assert their trade logs and equity curves are EXACTLY equal —
frame-equal, no tolerance (D-01/D-03). This is the anchor E2E coverage of the full
paper path: live feed -> strategy -> order -> fill -> Portfolio.

Parity anchor (D-01): the gate is re-anchored to "paper == a FRESH backtest on
identical data", NOT pinned to the committed frozen equity artifact. Rationale:
pinning to the frozen number breaks the moment the backtest loop is reworked (the
deferred bar-direct-unify todo); "paper == backtest, same data" is invariant under
changing the loop — rework both, the test still holds, no re-freeze needed. The
transitive lock to the frozen equity number stays held by the separate, unchanged
oracle test (``test_backtest_oracle.py``), so paper == backtest == the frozen number
holds transitively today while this gate needs no edit when the oracle re-freezes.

Replay mechanism (D-02/D-03): the paper side pushes the golden CSV rows as confirm-
gated ``ClosedBar`` dicts through the real Phase-3 live seam (``set_bar_sink`` ->
``LiveBarFeed.update()`` -> direct-BAR emission), driven SYNCHRONOUSLY in-thread via
``run_paper_replay()`` — offline, single process, deterministic, CI-safe.

TZ NORMALIZATION (load-bearing): ``config.TIMEZONE`` defaults to 'Europe/Paris'. The
backtest stamps bar-open / fill / equity timestamps in Europe/Paris; the live feed
stamps ``bar.time`` in UTC (the correct contract for a real venue). Same INSTANT,
different tz label — a naive exact diff on ``entry_date``/``exit_date``/``timestamp``
would FALSELY fail. Both sides' tz-aware datetime columns are normalized to UTC
(``pd.to_datetime(col, utc=True)``) before the exact diff, so identical instants
compare equal.

Carries the ``integration`` marker AUTOMATICALLY via the ``tests/integration/`` path
(folder-derived TYPE auto-marking) — markers are NOT hand-added here.
"""

from decimal import Decimal

import pandas as pd
import pandas.testing as pdt

from itrader.core.sizing import FractionOfCash, TradingDirection
from itrader.reporting.frames import (
    EQUITY_COLUMNS,
    TRADE_COLUMNS,
    build_equity_curve,
    build_trade_log,
)
from itrader.execution_handler.execution_handler import DEFAULT_ACCOUNT_ID
from itrader.strategy_handler.strategies.SMA_MACD_strategy import SMAMACDStrategy
from itrader.trading_system.backtest_trading_system import BacktestTradingSystem
from tests.support.replay_harness import (
    PAPER_PARITY_END_DATE,
    PAPER_PARITY_START_DATE,
    PAPER_PARITY_SYMBOL,
    TestRunner,
    build_paper_replay_system,
)

# D-18 (TEST-01): the WHOLE replay harness left the itrader package for tests/. The
# backtest comparand window/symbol are imported from the relocated PAPER_PARITY_*
# constants — the SAME literals the replay store is constructed from — so paper and
# backtest can never silently desync (WR-02). Production paper re-points to the OKX live
# feed (D-21); the paper↔replay pairing survives ONLY in this test harness.
_START_DATE = PAPER_PARITY_START_DATE
_END_DATE = PAPER_PARITY_END_DATE
_CASH = 10_000
_TICKER = PAPER_PARITY_SYMBOL
_TIMEFRAME = "1d"

# Sort keys mirroring the oracle's frame-diff mechanic (test_backtest_oracle.py:39-40).
_TRADE_SORT_KEYS = ["entry_date", "exit_date", "side"]
_EQUITY_SORT_KEY = "timestamp"

# The tz-sensitive datetime columns normalized to UTC before the exact diff (the tz trap).
_TRADE_TZ_COLUMNS = ["entry_date", "exit_date"]
_EQUITY_TZ_COLUMNS = ["timestamp"]


def _build_golden_strategy() -> SMAMACDStrategy:
    """Construct the golden SMA_MACD strategy — literals copied verbatim (parity anchor).

    The sizing literal MUST be ``FractionOfCash(Decimal("0.95"))`` (string-path Decimal)
    and the direction ``LONG_ONLY`` so both paths reproduce the same behavior by
    construction (D-01/D-09).
    """
    return SMAMACDStrategy(
        timeframe=_TIMEFRAME,
        tickers=[_TICKER],
        sizing_policy=FractionOfCash(Decimal("0.95")),
        direction=TradingDirection.LONG_ONLY,
        allow_increase=False,
    )


def _run_backtest_frames() -> tuple[pd.DataFrame, pd.DataFrame]:
    """Run a FRESH backtest over the golden window; return (trades, equity) frames.

    D-01 option (b): the comparand is a fresh in-test backtest run — NO output/ file
    round-trip, NO diff against the committed frozen golden artifact directory.
    """
    system = BacktestTradingSystem(
        exchange="csv",
        start_date=_START_DATE,
        end_date=_END_DATE,
    )
    strategy = _build_golden_strategy()
    system.strategies_handler.add_strategy(strategy)
    portfolio_id = system.portfolio_handler.add_portfolio(
        name="parity_bt", exchange="csv", cash=_CASH,
    )
    strategy.subscribe_portfolio(portfolio_id)
    # print_summary=False suppresses the display-only metrics printout (oracle-inert).
    system.run(print_summary=False)

    portfolio = system.portfolio_handler.get_portfolio(portfolio_id)
    return build_trade_log(portfolio), build_equity_curve(portfolio)


def _run_paper_frames() -> tuple[pd.DataFrame, pd.DataFrame]:
    """Drive the live-paper path over the golden dataset; return (trades, equity) frames.

    The paper side (TEST-01/D-18): ``build_paper_replay_system()`` builds the paper live
    system with the relocated ``TestDataPlugin`` injected on the data registry (paper↔replay
    lives ONLY in the fixture now) and reuses the account-free 'simulated'
    ``SimulatedExchange`` as-is (D-04); ``TestRunner(system, provider).run()`` replays the
    golden bars through the real feed -> queue seam with backtest-faithful per-tick +
    run-end discipline, fail-fast BY DEFAULT (D-19).
    """
    system, provider = build_paper_replay_system()
    strategy = _build_golden_strategy()
    system.strategies_handler.add_strategy(strategy)
    # 'simulated' routes to the reused SimulatedExchange (D-04) — the paper exchange.
    # D-27: the paper side is a LIVE system, so its portfolio must NAME the venue
    # account its orders route through — on_order resolves the account through the
    # injected read-model and REFUSES a portfolio that names none. The reused
    # simulated exchange is registered under the default account, so naming it here
    # is parity-preserving: the same object receives the same orders as before.
    portfolio_id = system.portfolio_handler.add_portfolio(
        name="parity_paper", exchange="simulated", cash=_CASH,
        account_id=DEFAULT_ACCOUNT_ID,
    )
    strategy.subscribe_portfolio(portfolio_id)
    # Synchronous offline drive (D-02/D-03): replay -> feed.update -> BarEvent -> queue.
    # TestRunner holds the TestLiveDataProvider handle (Landmine 2), not system._replay_provider.
    TestRunner(system, provider).run()

    portfolio = system.portfolio_handler.get_portfolio(portfolio_id)
    return build_trade_log(portfolio), build_equity_curve(portfolio)


def _normalize_and_sort(
    frame: pd.DataFrame, tz_columns: list[str], sort_keys: "list[str] | str"
) -> pd.DataFrame:
    """Normalize the tz-sensitive datetime columns to UTC, then sort + reindex.

    The tz trap: paper stamps bar.time in UTC (live-feed contract) while the backtest
    stamps Europe/Paris (config.TIMEZONE) for the SAME instant. Converting both sides'
    datetime columns to tz-aware UTC (``pd.to_datetime(col, utc=True)``) compares the
    identical INSTANTS, not the Europe/Paris-vs-UTC label. Sorting after normalization
    keeps row order reproducible across both sides.
    """
    frame = frame.copy()
    for column in tz_columns:
        # utc=True handles both already-tz-aware datetimes and offset strings; the same
        # instant on either side collapses to the same UTC value (the tz trap).
        frame[column] = pd.to_datetime(frame[column], utc=True)
    return frame.sort_values(sort_keys).reset_index(drop=True)


def test_paper_path_equals_fresh_backtest_exactly():
    """The DoD gate: the live-paper path reproduces a fresh backtest EXACTLY (D-01/D-03).

    Trades (count + all TRADE_COLUMNS) and equity (count + all EQUITY_COLUMNS) are
    asserted frame-equal with NO tolerance (``check_exact=True``) after tz-normalizing
    the datetime columns to UTC. The paper trade count is asserted > 0 so a zero-trade
    parity cannot pass vacuously (T-04-08). The gate is anchored to the fresh backtest,
    NOT the frozen equity number (D-01) — it survives a future backtest-loop rework.
    """
    bt_trades, bt_equity = _run_backtest_frames()
    paper_trades, paper_equity = _run_paper_frames()

    # tz-normalize (UTC) + sort BOTH sides before the exact diff (the tz trap).
    bt_trades = _normalize_and_sort(bt_trades, _TRADE_TZ_COLUMNS, _TRADE_SORT_KEYS)
    paper_trades = _normalize_and_sort(paper_trades, _TRADE_TZ_COLUMNS, _TRADE_SORT_KEYS)
    bt_equity = _normalize_and_sort(bt_equity, _EQUITY_TZ_COLUMNS, _EQUITY_SORT_KEY)
    paper_equity = _normalize_and_sort(paper_equity, _EQUITY_TZ_COLUMNS, _EQUITY_SORT_KEY)

    # --- Guard against a vacuous (zero-trade) parity pass (T-04-08) ------------
    assert len(paper_trades) > 0, (
        "paper run produced zero trades — a zero-trade parity would be a vacuous pass"
    )

    # --- Trades: count + full TRADE_COLUMNS EXACT (no tolerance) --------------
    assert len(paper_trades) == len(bt_trades), (
        f"trade count drift: paper={len(paper_trades)} backtest={len(bt_trades)}"
    )
    pdt.assert_frame_equal(
        paper_trades[TRADE_COLUMNS],
        bt_trades[TRADE_COLUMNS],
        check_exact=True,
        check_like=True,
    )

    # --- Equity: point count + full EQUITY_COLUMNS EXACT (no tolerance) -------
    assert len(paper_equity) == len(bt_equity), (
        f"equity point count drift: paper={len(paper_equity)} backtest={len(bt_equity)}"
    )
    pdt.assert_frame_equal(
        paper_equity[EQUITY_COLUMNS],
        bt_equity[EQUITY_COLUMNS],
        check_exact=True,
        check_like=True,
    )

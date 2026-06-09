"""Shared serialization assembly for the run artifacts (D-16, plan 04-01).

``attach_slippage``, ``build_metrics_block`` and ``build_summary`` are relocated
VERBATIM from ``scripts/run_backtest.py`` so the oracle generator AND the future
e2e harness import ONE serialization path and cannot drift. The function bodies
are character-identical to the run_backtest.py originals — only the five module
constants ``build_summary`` closed over (``TICKER`` / ``TIMEFRAME`` /
``START_DATE`` / ``END_DATE`` / ``CASH``) become keyword parameters. Any drift
breaks the byte-exact oracle gate (``test_backtest_oracle.py``, T-04-01).

Purity contract (same anti-pattern guard as ``itrader.reporting.frames`` /
``itrader.reporting.metrics``): imports are pandas + stdlib + the pure metrics
formulas only; the ``portfolio`` / ``trades`` parameters stay DUCK-TYPED — zero
handler imports. The Decimal->float money boundary is preserved verbatim:
``float(portfolio.cash)`` / ``float(portfolio.total_equity)`` with no arithmetic
on the Decimal beforehand — this is the single money Decimal->float boundary for
``summary.json``.
"""

from typing import Any

import pandas as pd

from itrader.reporting.metrics import (
    cagr,
    compute_returns,
    max_drawdown,
    profit_factor,
    sharpe,
    sortino,
    win_rate,
)

#: pinned repr for cross-platform stability (T-04-01)
FLOAT_FORMAT = "%.10f"

# D-17 slippage-attribution columns appended to the serialized trade log (after
# the relocated TRADE_COLUMNS) — float columns, so the FLOAT_FORMAT pin applies.
SLIPPAGE_COLUMNS = ["slippage_entry", "slippage_exit"]


def attach_slippage(trades: Any, closes: Any) -> Any:
    """Attach the D-17 per-trade slippage columns — post-hoc, engine-inert (Pattern 3).

    Under the Phase 6 next-bar-open fill convention, a fill at bar ``T`` was decided
    at the bar immediately BEFORE ``T`` in the store index; the attribution is
    ``fill price - decision-bar close`` for the entry and exit fills separately.
    In the zero-slippage golden run these columns measure the overnight next-open
    gap introduced by Phase 6 fill realism. Computed purely from the store's
    per-ticker close series + the trades frame — no engine/event/entity change.
    """
    if trades.empty:
        trades["slippage_entry"] = pd.Series(dtype=float)
        trades["slippage_exit"] = pd.Series(dtype=float)
        return trades

    index = closes.index

    def decision_close(fill_time: Any) -> float:
        # The decision bar is the store bar immediately BEFORE the fill bar.
        # ``searchsorted(side="left") - 1`` only identifies the correct
        # decision bar when ``fill_time`` lands EXACTLY on a store-index bar. If
        # the fill timestamp is drawn from a different grid (e.g. a resampled run
        # timeframe vs the raw base store series), ``position - 1`` would silently
        # attribute slippage to the WRONG bar and freeze a wrong number into a
        # golden. Enforce membership so a grid mismatch fails LOUDLY here rather
        # than mis-attributing. Contract: ``attach_slippage`` requires fill
        # timestamps drawn from the SAME grid as ``closes`` (the store index).
        # The first store bar has no prior bar; return a diff-stable 0.0 ("no
        # overnight gap measurable") rather than NaN, which would break the
        # exact, no-tolerance diff.
        position = index.searchsorted(fill_time, side="left")
        if position <= 0:
            return 0.0
        if fill_time not in index:
            raise ValueError(
                f"fill timestamp {fill_time!r} is not a store-index bar — "
                f"attach_slippage requires fill timestamps drawn from the same grid "
                f"as the close series"
            )
        return float(closes.iloc[position - 1])

    def entry_fill_price(row: Any) -> float:
        # LONG enters by buying; SHORT enters by selling.
        return float(row["avg_bought"] if row["side"] == "LONG" else row["avg_sold"])

    def exit_fill_price(row: Any) -> float:
        # LONG exits by selling; SHORT exits by buying back.
        return float(row["avg_sold"] if row["side"] == "LONG" else row["avg_bought"])

    trades["slippage_entry"] = trades.apply(
        lambda row: entry_fill_price(row) - decision_close(row["entry_date"]), axis=1)
    trades["slippage_exit"] = trades.apply(
        lambda row: exit_fill_price(row) - decision_close(row["exit_date"]), axis=1)
    return trades


def build_metrics_block(equity: Any, trades: Any) -> dict[str, float]:
    """Build the nested D-15 derived-metrics dict for ``summary.json``.

    Computed by the pure ``itrader.reporting.metrics`` functions on the equity
    curve + trades frame — the SAME formula source the engine's end-of-run
    printout uses (one formula source, two consumers). All values are plain
    floats, deterministic; the block freezes at the plan 07-07 re-freeze.
    """
    equity_series = equity["total_equity"].astype(float)
    returns = compute_returns(equity_series)
    return {
        "sharpe": float(sharpe(returns)),
        "sortino": float(sortino(returns)),
        "cagr": float(cagr(equity_series)),
        "max_drawdown": float(max_drawdown(equity_series)),
        "profit_factor": float(profit_factor(trades)),
        "win_rate": float(win_rate(trades)),
    }


def build_summary(
    portfolio: Any,
    trades: Any,
    *,
    ticker: str,
    timeframe: str,
    start_date: str,
    end_date: str,
    starting_cash: Any,
) -> dict[str, Any]:
    """Build a minimal deterministic summary dict (D-12).

    Final cash + a minimal deterministic metric set (trade count, total realised PnL,
    final equity). The derived ratios live in the nested ``metrics`` block added by
    ``build_metrics_block`` (D-15 — the M5-owned carve-out is closed this phase).
    """
    # total_realised_pnl reads the already-float trades-frame column (build_trade_log
    # casts money to float at the frame edge) — a frame read, not a Portfolio property.
    total_realised_pnl = float(trades["realised_pnl"].sum()) if not trades.empty else 0.0
    # Decimal->float at the serialization edge: portfolio.cash and
    # portfolio.total_equity are Decimal end-to-end (08-01 retype); float()
    # narrows them HERE, at the summary.json serialization boundary, with no
    # arithmetic on the Decimal beforehand (direct reads). This is the single
    # money Decimal->float boundary for summary.json.
    return {
        "ticker": ticker,
        "timeframe": timeframe,
        "start_date": start_date,
        "end_date": end_date,
        "starting_cash": float(starting_cash),
        "final_cash": float(portfolio.cash),
        "final_equity": float(portfolio.total_equity),
        "trade_count": int(len(trades)),
        "total_realised_pnl": total_realised_pnl,
    }

"""Pure backtest metric functions on run-artifact frames (M5-07; D-14/D-15/D-16/D-18).

This module is the single formula source for the derived backtest metrics. It is
PURE computation: stateless functions over the run artifacts that
``itrader.reporting.frames`` builds from portfolio state — the equity curve
(``total_equity`` column as a ``pd.Series``) and the closed-trades frame
(``realised_pnl`` column). Zero itrader imports, no SQL, no class state, no I/O
(the ``statistics.py`` anti-pattern — handler/SQL imports — must never reappear).

Pinned conventions (D-16, Pitfall 10) — verified against backtesting.py ``_stats.py``,
the Phase 8 cross-validation reference:

* **Drawdown sign: NEGATIVE.** ``max_drawdown`` returns the most-negative value of
  ``equity / equity.cummax() - 1`` — matching backtesting.py's ``dd.min()`` where
  dd <= 0. The legacy zero-seeded-HWM positive-magnitude drawdown died with
  ``performance.py``.
* **ddof = 1** (sample standard deviation). Pinned EXPLICITLY everywhere because
  ``np.std`` defaults to ddof=0 while ``pandas.Series.std`` defaults to ddof=1 —
  a silent factor on every Sharpe/Sortino if left implicit.
* **PERIODS = 365** — annualization for daily crypto bars (the old periods=355 died).
* **risk_free_rate = 0** for Sharpe/Sortino.
* **Profit factor = gross profit / gross loss** (true PF — the misspelled
  ``profict_factor`` count-ratio died).
* **Sortino downside deviation = sqrt(mean(clip(r, -inf, 0)^2))** — textbook
  full-period denominator with target 0, NOT the std of the negative subset.

Every denominator is guarded (zero std, zero gross loss, empty frames) — the old
code raised ``ZeroDivisionError`` and empty-slice ``RuntimeWarning``s, both fatal
under the suite's ``filterwarnings=["error"]`` regime. Pandas-2-safe idioms only:
``.iloc`` indexing, whole-column construction, explicit empty-subset guards.
"""

from typing import Any

import numpy as np
import pandas as pd

#: D-16 — annualization periods for daily crypto bars (periods=355 died by deletion).
PERIODS = 365


def compute_returns(equity: pd.Series) -> pd.Series:
    """Per-bar simple returns of the equity series, leading element filled with 0.0."""
    return equity.pct_change().fillna(0.0)


def max_drawdown(equity: pd.Series) -> float:
    """Maximum drawdown on ``equity.cummax()`` — NEGATIVE sign convention (D-16).

    Matches backtesting.py: ``dd = equity / np.maximum.accumulate(equity) - 1``,
    reported as ``dd.min()`` (a value <= 0). Empty equity returns 0.0.
    """
    if equity.empty:
        return 0.0
    dd = equity / equity.cummax() - 1.0
    return float(dd.min())


def sharpe(returns: pd.Series, periods: int = PERIODS) -> float:
    """Annualized Sharpe ratio with risk_free_rate=0 and ddof=1 (D-16).

    Guarded: fewer than 2 observations or zero sample std returns 0.0.
    """
    if len(returns) < 2:
        return 0.0
    sd = returns.std(ddof=1)  # ddof pinned: sample std (np.std defaults ddof=0)
    if sd == 0:
        return 0.0
    return float(np.sqrt(periods) * returns.mean() / sd)


def sortino(returns: pd.Series, periods: int = PERIODS) -> float:
    """Annualized Sortino ratio — textbook full-period downside deviation (D-16).

    ``downside = sqrt(mean(clip(r, -inf, 0)^2))`` over the FULL period with
    target 0 (matching backtesting.py), NOT the std of the negative subset.
    Guarded: empty returns or zero downside deviation returns 0.0.
    """
    if returns.empty:
        return 0.0  # guard: np.mean of an empty slice raises RuntimeWarning
    downside = float(np.sqrt(np.mean(np.clip(returns.to_numpy(), -np.inf, 0.0) ** 2)))
    if downside == 0.0:
        return 0.0
    return float(np.sqrt(periods) * returns.mean() / downside)


def profit_factor(trades: pd.DataFrame) -> float:
    """True profit factor: gross profit / gross loss (D-16).

    All-winning frames return ``inf``; all-losing and empty frames return 0.0
    (the old count-ratio ``profict_factor`` raised ``ZeroDivisionError``).
    """
    if trades.empty:
        return 0.0
    pnl = trades["realised_pnl"]
    gross_profit = float(pnl[pnl > 0].sum())  # empty-subset .sum() is 0.0, no warning
    gross_loss = float(abs(pnl[pnl < 0].sum()))
    if gross_loss == 0.0:
        return float("inf") if gross_profit > 0.0 else 0.0
    return gross_profit / gross_loss


def cagr(equity: pd.Series, periods: int = PERIODS) -> float:
    """Compound annual growth rate over the equity series (D-16).

    ``years = len(equity) / periods``; ``.iloc`` indexing only (pandas-2-safe —
    ``equity[-1]`` raises FutureWarning, suite-fatal). Empty, zero/negative-start,
    and non-positive-final equity return 0.0 (a negative ratio under a fractional
    exponent is complex-valued).
    """
    if equity.empty:
        return 0.0
    start = float(equity.iloc[0])
    final = float(equity.iloc[-1])
    if start <= 0.0 or final <= 0.0:
        return 0.0
    years = len(equity) / periods
    if years <= 0:
        return 0.0
    return float((final / start) ** (1.0 / years) - 1.0)


def win_rate(trades: pd.DataFrame) -> float:
    """Fraction of closed trades with positive realised pnl. Empty frame returns 0.0."""
    if trades.empty:
        return 0.0
    pnl = trades["realised_pnl"]
    return float((pnl > 0).sum() / len(pnl))


def rolling_sharpe(returns: pd.Series, window: int, periods: int = PERIODS) -> pd.Series:
    """Rolling annualized Sharpe over ``window`` bars — one pure expression (D-18).

    Returns a Series of the same length with a NaN head (the first ``window - 1``
    entries). Zero-variance windows yield NaN, never raise. This finishes the
    legacy rolling-stats stub (statistics.py:171-177) instead of deleting it.
    """
    roll = returns.rolling(window)
    result: pd.Series = np.sqrt(periods) * roll.mean() / roll.std(ddof=1)
    return result


def total_return(equity: pd.Series) -> float:
    """Total return over the equity series: ``final / start - 1``.

    Mirrors ``cagr``'s guards: empty equity or a non-positive start returns 0.0.
    ``.iloc`` indexing only (pandas-2-safe).
    """
    if equity.empty:
        return 0.0
    start = float(equity.iloc[0])
    if start <= 0.0:
        return 0.0
    final = float(equity.iloc[-1])
    return final / start - 1.0


def avg_trade_pnl(trades: pd.DataFrame) -> float:
    """Mean realised pnl across all closed trades. Empty frame returns 0.0."""
    if trades.empty:
        return 0.0
    return float(trades["realised_pnl"].mean())


def avg_win(trades: pd.DataFrame) -> float:
    """Mean realised pnl over winning trades (pnl > 0). No winners returns 0.0."""
    if trades.empty:
        return 0.0
    pnl = trades["realised_pnl"]
    winners = pnl[pnl > 0]
    if winners.empty:
        return 0.0  # guard: .mean() of an empty subset raises RuntimeWarning
    return float(winners.mean())


def avg_loss(trades: pd.DataFrame) -> float:
    """Mean realised pnl over losing trades (pnl < 0) — a NEGATIVE value.

    No losers returns 0.0 (guards the empty-subset ``.mean()`` RuntimeWarning).
    """
    if trades.empty:
        return 0.0
    pnl = trades["realised_pnl"]
    losers = pnl[pnl < 0]
    if losers.empty:
        return 0.0
    return float(losers.mean())


def best_trade(trades: pd.DataFrame) -> float:
    """Maximum realised pnl across closed trades. Empty frame returns 0.0."""
    if trades.empty:
        return 0.0
    return float(trades["realised_pnl"].max())


def worst_trade(trades: pd.DataFrame) -> float:
    """Minimum realised pnl across closed trades. Empty frame returns 0.0."""
    if trades.empty:
        return 0.0
    return float(trades["realised_pnl"].min())


def avg_trade_duration(trades: pd.DataFrame) -> float:
    """Mean trade duration ``(exit_date - entry_date)`` in SECONDS (float).

    Empty frame returns 0.0. The formatter renders the human ``Nd Nh`` form;
    this function returns the raw seconds.
    """
    if trades.empty:
        return 0.0
    deltas = trades["exit_date"] - trades["entry_date"]
    return float(deltas.dt.total_seconds().mean())


def exposure_time(equity_frame: pd.DataFrame) -> float:
    """Fraction of bars with an open position — ``(open_positions_count > 0).mean()``.

    Takes the equity FRAME (it needs the ``open_positions_count`` column), NOT the
    equity series. A value in ``[0, 1]``; an empty frame returns 0.0.
    """
    if equity_frame.empty:
        return 0.0
    return float((equity_frame["open_positions_count"] > 0).mean())


def calmar(equity: pd.Series, periods: int = PERIODS) -> float:
    """Calmar ratio: ``cagr(equity) / abs(max_drawdown(equity))``.

    Reuses the pinned ``cagr``/``max_drawdown`` formulas. A zero drawdown
    (monotonic or empty equity) is guarded to 0.0 (no ZeroDivisionError).
    """
    dd = max_drawdown(equity)
    if dd == 0.0:
        return 0.0
    return cagr(equity, periods) / abs(dd)


def format_metrics(metrics: dict[str, float], title: str = "Backtest metrics") -> str:
    """Render a metric dict as an aligned multi-line text block (D-14 amendment).

    Pure string building — no printing, no I/O; print/log decisions belong to the
    callers (the engine's end-of-run printout, ``run_backtest.py``). Values render
    with ``%.4f``; non-finite values (``inf``) pass through as-is.
    """
    name_width = max((len(name) for name in metrics), default=0)
    lines = [title, "-" * max(len(title), name_width + 12)]
    for name, value in metrics.items():
        lines.append(f"{name:<{name_width}}  {value:>10.4f}")
    return "\n".join(lines)


#: Cap on the rendered instrument list before truncating with "+N more".
_TICKER_CAP = 6

#: Box-drawing rules for the grouped backtest-summary block.
_DOUBLE_RULE = "=" * 46
_SINGLE_RULE = "-" * 46


def _format_duration(seconds: float) -> str:
    """Human duration: ``Nd Nh`` / ``Nh Nm`` / ``Nm Ns`` / ``N.NNs``.

    Pure string building. The two-largest non-zero units are shown; sub-minute
    durations render as fractional seconds (``3.42s``).
    """
    total = int(seconds)
    days, rem = divmod(total, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, secs = divmod(rem, 60)
    if days > 0:
        return f"{days}d {hours}h"
    if hours > 0:
        return f"{hours}h {minutes}m"
    if minutes > 0:
        return f"{minutes}m {secs}s"
    return f"{seconds:.2f}s"


def _format_tickers(tickers: list[str], cap: int = _TICKER_CAP) -> str:
    """Comma-joined instrument list; ``+N more`` past ``cap``. Empty -> ``""``."""
    if not tickers:
        return ""
    if len(tickers) <= cap:
        return ", ".join(tickers)
    shown = ", ".join(tickers[:cap])
    return f"{shown}, +{len(tickers) - cap} more"


def _pct(value: float, *, signed: bool = False) -> str:
    """Render a fraction as ``value * 100`` with a ``%`` suffix (optionally signed)."""
    fmt = "{:+.2f}%" if signed else "{:.2f}%"
    return fmt.format(value * 100.0)


def _ratio(value: float) -> str:
    """Render a raw ratio at 4dp; ``inf`` passes through (``str(float('inf'))``)."""
    if not np.isfinite(value):
        return str(value)
    return f"{value:.4f}"


def _money(value: float, *, signed: bool = False) -> str:
    """Render currency with thousands separators + 2dp (optionally signed)."""
    fmt = "{:+,.2f}" if signed else "{:,.2f}"
    return fmt.format(value)


def format_backtest_summary(
    portfolios: list[dict[str, Any]],
    *,
    period: tuple[Any, Any, int] | None = None,
    duration_seconds: float | None = None,
) -> str:
    """Render the grouped end-of-run backtest summary block (display-only).

    Sibling to the UNTOUCHED ``format_metrics``. Pure string building — no I/O,
    no itrader imports. Renders one shared run-level header (Period + Duration)
    followed by a per-portfolio Capital / Trades / Risk-Return group.

    Each entry in ``portfolios`` is a value bag with keys: ``name``, ``tickers``
    (``list[str]``), ``starting_cash``, ``final_cash``, ``final_equity``,
    ``realised_pnl``, ``trade_count``, plus the metric bag (``total_return``,
    ``win_rate``, ``profit_factor``, ``avg_trade_pnl``, ``avg_win``, ``avg_loss``,
    ``best_trade``, ``worst_trade``, ``avg_trade_duration`` [seconds],
    ``exposure_time``, ``cagr``, ``sharpe``, ``sortino``, ``max_drawdown``,
    ``calmar``).

    Rendering rules (spec §2):

    * Currency: thousands separators + 2dp; signed for return/PnL columns.
    * Percentages (total_return, cagr, max_drawdown, win_rate, exposure_time):
      ``value * 100`` with ``%``, signed where natural.
    * Ratios (sharpe, sortino, profit_factor, calmar): raw ``%.4f``; ``inf``
      passes through.
    * Duration: seconds -> human ``Nd Nh`` / ``Nh Nm`` / ``Nm Ns`` form.
    * Instrument list: comma-joined, ``+N more`` past a cap of 6; line OMITTED
      if empty.
    * Period: three lines (Start / End / Bars), date+time with the timezone
      stripped; all three omitted if ``period`` is None.
    """
    lines: list[str] = [_DOUBLE_RULE, " Backtest Run Summary", _DOUBLE_RULE]

    if period is not None:
        start, end, bar_count = period
        # Date+time only, timezone stripped (%Y-%m-%d %H:%M:%S, no %z).
        lines.append(f" {'Start':<13} {pd.Timestamp(start).strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append(f" {'End':<13} {pd.Timestamp(end).strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append(f" {'Bars':<13} {bar_count}")
    if duration_seconds is not None:
        lines.append(f" Duration      {_format_duration(duration_seconds)}")

    for bag in portfolios:
        lines.append(_SINGLE_RULE)
        header = f" Portfolio · {bag['name']}"
        ticker_line = _format_tickers(list(bag.get("tickers", [])))
        if ticker_line:
            header += f"   ({ticker_line})"
        lines.append(header)
        lines.append(_SINGLE_RULE)

        # Capital group.
        lines.append(" Capital")
        lines.append(f"   Starting cash      {_money(bag['starting_cash']):>14}")
        lines.append(f"   Final cash         {_money(bag['final_cash']):>14}")
        lines.append(f"   Final equity       {_money(bag['final_equity']):>14}")
        lines.append(f"   Total return       {_pct(bag['total_return'], signed=True):>14}")
        lines.append(f"   Realised PnL       {_money(bag['realised_pnl'], signed=True):>14}")

        # Trades group.
        lines.append(" Trades")
        lines.append(f"   Count              {bag['trade_count']:>14}")
        lines.append(f"   Win rate           {_pct(bag['win_rate']):>14}")
        lines.append(f"   Profit factor      {_ratio(bag['profit_factor']):>14}")
        lines.append(f"   Avg trade PnL      {_money(bag['avg_trade_pnl'], signed=True):>14}")
        lines.append(f"   Avg win            {_money(bag['avg_win'], signed=True):>14}")
        lines.append(f"   Avg loss           {_money(bag['avg_loss'], signed=True):>14}")
        lines.append(f"   Best trade         {_money(bag['best_trade'], signed=True):>14}")
        lines.append(f"   Worst trade        {_money(bag['worst_trade'], signed=True):>14}")
        lines.append(f"   Avg duration       {_format_duration(bag['avg_trade_duration']):>14}")
        lines.append(f"   Exposure time      {_pct(bag['exposure_time']):>14}")

        # Risk / Return group.
        lines.append(" Risk / Return")
        lines.append(f"   CAGR               {_pct(bag['cagr']):>14}")
        lines.append(f"   Sharpe             {_ratio(bag['sharpe']):>14}")
        lines.append(f"   Sortino            {_ratio(bag['sortino']):>14}")
        lines.append(f"   Max drawdown       {_pct(bag['max_drawdown']):>14}")
        lines.append(f"   Calmar             {_ratio(bag['calmar']):>14}")

    lines.append(_DOUBLE_RULE)
    return "\n".join(lines)

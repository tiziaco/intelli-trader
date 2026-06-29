"""Pure serializer layer for the results store (RESULT-01, D-06/D-08/D-11/D-14).

Turns post-run engine state into the typed inputs the store persists:

* ``curate_run_settings`` — the curated ``runs.settings`` envelope (D-11): a
  hand-picked, flat, JSON-safe dict of the result-relevant run knobs. It is NOT a
  ``model_dump`` of ``SystemConfig`` and it NEVER reads ``Settings.database_url`` or
  any ``SecretStr`` (credential-leak guard, T-02-03).
* ``curate_portfolio_params`` — the per-strategy ``run_portfolios.params`` envelope
  (D-06/D-11): reads ``strategy.to_dict()`` (the existing JSON-safe introspection
  seam) and keeps only the result-relevant knobs.
* ``build_run_metrics`` — the per-portfolio / aggregate ``RunMetrics`` (D-08): all
  11 metrics computed by REUSING ``itrader.reporting.metrics`` formulas (the single
  formula source — never reimplemented), incl. the two derived ones
  (``total_return = final/start - 1``, ``calmar = cagr/abs(max_drawdown)``).
* ``build_aggregate_equity_curve`` — the multi-portfolio aggregate equity curve
  (D-14): outer-join each portfolio's ``total_equity`` on the union timestamp index,
  forward-fill (leading region = that portfolio's starting cash), and sum —
  mixed-timeframe-safe.
* ``annual_periods`` — the explicit mixed-timeframe annualization basis (D-14):
  ``PERIODS=365`` for an all-daily run, the finest timeframe's periods-per-year for
  a mixed run.

Purity contract (mirrors ``itrader.reporting.frames`` / ``summary`` / ``metrics``):
imports are pandas + stdlib + ``itrader.reporting`` + ``itrader.results.records`` +
the pure ``itrader.outils.time_parser`` util only — ZERO handler imports, no SQL, no
engine run. The ``exchange`` / ``strategies`` parameters stay DUCK-TYPED. 4-space
indentation (matches the ``itrader/results`` layer).
"""

from decimal import Decimal
from enum import Enum
from typing import Any

import pandas as pd

from itrader.outils.time_parser import to_timedelta
from itrader.reporting.metrics import (
    PERIODS,
    cagr,
    calmar,
    compute_returns,
    max_drawdown,
    profit_factor,
    sharpe,
    sortino,
    total_return,
    win_rate,
)
from itrader.results.records import RunMetrics

# The result-relevant per-strategy knobs kept in ``run_portfolios.params`` (D-11).
# A subset of ``strategy.to_dict()`` — the alpha windows present plus the risk knobs.
# Keys absent from a given strategy's ``to_dict()`` are simply skipped.
_PARAM_KEYS: tuple[str, ...] = (
    "strategy_name",
    "fast_window",
    "slow_window",
    "signal_window",
    "short_window",
    "long_window",
    "sizing_policy",
    "sltp_policy",
    "direction",
    "allow_increase",
    "max_positions",
)

#: Seconds in a (365-day) year — the annualization numerator (D-14).
_SECONDS_PER_YEAR = 31_536_000


def _json_scalar(value: Any) -> Any:
    """Narrow a value to a JSON-safe scalar (D-11 serialization edge).

    ``Decimal`` -> ``float`` (the results store is all-``Float``); ``bool``/``int``/
    ``float``/``str``/``None`` pass through; anything else (datetime, Timestamp, custom
    object) is ``str``-coerced so the curated dict stays ``json.dumps``-safe and never
    leaks a non-native leaf (e.g. a ``SecretStr``).
    """
    if isinstance(value, bool):
        return value
    if value is None or isinstance(value, (int, float, str)):
        return value
    if isinstance(value, Decimal):
        return float(value)
    return str(value)


def _enum_value(value: Any) -> Any:
    """Serialize an ``Enum`` as its ``.value``; pass any other value through."""
    return value.value if isinstance(value, Enum) else value


def _model_envelope(model: Any) -> dict[str, Any]:
    """Build the ``{"type","params"}`` envelope for a fee/slippage model (D-11).

    ``type`` is the model class name; ``params`` is its public instance attributes
    (non-underscore keys, sorted for determinism), each narrowed to a JSON-safe scalar.
    Duck-typed: any object with a ``__dict__`` works (no model-specific accessor).
    """
    raw = vars(model) if hasattr(model, "__dict__") else {}
    params = {key: _json_scalar(raw[key]) for key in sorted(raw) if not key.startswith("_")}
    return {"type": type(model).__name__, "params": params}


def curate_run_settings(
    exchange: Any,
    order_config: Any,
    *,
    tickers: list[str],
    timeframe: str,
    start_date: Any,
    end_date: Any,
    starting_cash: Any,
    rng_seed: int,
) -> dict[str, Any]:
    """Build the curated ``runs.settings`` envelope (D-11).

    Hand-picks a flat, JSON-safe dict of the result-relevant run knobs — run window,
    ``rng_seed``, the fee/slippage model ``{"type","params"}`` envelopes,
    ``market_execution``, the exchange limits, and the failure-sim config. This is a
    CURATED serializer, NOT a ``model_dump``: it MUST NOT read ``Settings.database_url``
    or any ``SecretStr`` (credential-leak guard, T-02-03).
    """
    # Hand-picked, flat envelope — NOT a ``model_dump`` (D-11). Every value is narrowed
    # to a JSON-safe scalar at this serialization edge. The fee/slippage models are read
    # off the LIVE exchange at persist time (late values), then enveloped as
    # ``{"type","params"}``. No ``Settings``/``database_url``/``SecretStr`` is ever read.
    return {
        "tickers": list(tickers),
        "timeframe": timeframe,
        "start_date": _json_scalar(start_date),
        "end_date": _json_scalar(end_date),
        "starting_cash": float(starting_cash),
        "rng_seed": int(rng_seed),
        "fee_model": _model_envelope(exchange.fee_model),
        "slippage_model": _model_envelope(exchange.slippage_model),
        "market_execution": _enum_value(order_config.market_execution),
        # Decimal venue limits narrow to float; supported symbols sort for determinism.
        "min_order_size": float(exchange._min_order_size),
        "max_order_size": float(exchange._max_order_size),
        "supported_symbols": sorted(exchange._supported_symbols),
        "simulate_failures": bool(exchange.simulate_failures),
        "failure_rate": float(exchange.failure_rate),
    }


def curate_portfolio_params(strategies: list[Any]) -> dict[str, Any]:
    """Build the per-strategy ``run_portfolios.params`` envelope (D-06/D-11).

    For each strategy reads ``strategy.to_dict()`` (the JSON-safe introspection seam)
    and keeps only the result-relevant knobs. A single-strategy portfolio returns the
    lone curated dict directly; a multi-strategy portfolio returns
    ``{"strategies": [<curated dict>, ...]}``.
    """
    curated = [_curate_one_strategy(strategy) for strategy in strategies]
    if len(curated) == 1:
        # Single-strategy common case — return the lone curated dict directly.
        return curated[0]
    # Multi-strategy portfolio — wrap so each strategy's knobs stay distinct.
    return {"strategies": curated}


def _curate_one_strategy(strategy: Any) -> dict[str, Any]:
    """Keep only the result-relevant ``_PARAM_KEYS`` from ``strategy.to_dict()`` (D-06).

    ``to_dict()`` already produces JSON-safe leaves (windows, ``sizing_policy`` repr,
    ``direction.value``, ``strategy_name``), so no re-introspection is needed.
    """
    full = strategy.to_dict()
    return {key: full[key] for key in _PARAM_KEYS if key in full}


def build_run_metrics(
    equity_frame: pd.DataFrame,
    trades_frame: pd.DataFrame,
    *,
    periods: int = PERIODS,
) -> RunMetrics:
    """Build a ``RunMetrics`` from an equity-curve + trades frame (D-08).

    Reuses the ``itrader.reporting.metrics`` formulas (the single formula source —
    never reimplemented), incl. the two derived metrics ``total_return`` and
    ``calmar``. All 11 ``METRIC_NAMES`` are populated.
    """
    # astype(float) keeps the empty-run path warning-free (an empty frame's column is
    # object-dtype) and the populated path float-native (mirrors reporting/summary.py).
    equity = equity_frame["total_equity"].astype(float)
    returns = compute_returns(equity)
    final_equity = float(equity.iloc[-1]) if not equity.empty else 0.0
    total_realised_pnl = (
        float(trades_frame["realised_pnl"].sum()) if not trades_frame.empty else 0.0)
    # Every value comes from reporting/metrics.py — the single formula source (D-08).
    # total_return and calmar are the two derived metrics, obtained from the metrics
    # helpers so the formula stays single-sourced (never reimplemented here).
    return RunMetrics(
        sharpe=float(sharpe(returns, periods)),
        sortino=float(sortino(returns, periods)),
        cagr=float(cagr(equity, periods)),
        calmar=float(calmar(equity, periods)),
        max_drawdown=float(max_drawdown(equity)),
        profit_factor=float(profit_factor(trades_frame)),
        win_rate=float(win_rate(trades_frame)),
        total_return=float(total_return(equity)),
        final_equity=final_equity,
        total_realised_pnl=total_realised_pnl,
        trade_count=float(len(trades_frame)),
    )


def build_aggregate_equity_curve(equity_frames: list[pd.DataFrame]) -> pd.Series:
    """Build the multi-portfolio aggregate equity curve (D-14).

    Outer-joins each portfolio's ``total_equity`` on the union timestamp index,
    forward-fills (leading region = that portfolio's starting cash), and sums across
    portfolios — mixed-timeframe-safe.
    """
    # Outer-join is the only mixed-timeframe-correct join: an inner-join would discard
    # the fine-resolution bars that the coarse series lacks, and an identical-grid
    # assumption would raise on a mixed run. Each portfolio's total_equity is indexed by
    # timestamp; concat(axis=1, join="outer") aligns them on the UNION index.
    columns: list[pd.Series] = []
    for position, frame in enumerate(equity_frames):
        series = frame.set_index("timestamp")["total_equity"].astype(float)
        series.name = position  # unique column label so concat never collides
        columns.append(series)
    combined = pd.concat(columns, axis=1, join="outer").sort_index()
    # ffill carries each portfolio's last observed equity across the gaps where a
    # coarser series has no bar; bfill then fills each column's LEADING NaN region with
    # its first observed value (that portfolio's starting cash — pre-activity = start).
    combined = combined.ffill().bfill()
    aggregate = combined.sum(axis=1)
    aggregate.name = "total_equity"
    return aggregate


def annual_periods(timeframes: list[str]) -> int:
    """Resolve the explicit mixed-timeframe annualization basis (D-14).

    Returns ``PERIODS`` (365) for an empty or all-daily run, and the FINEST
    timeframe's periods-per-year (max across the run) for a mixed-timeframe run.
    """
    if not timeframes:
        return PERIODS
    best = 0
    for timeframe in timeframes:
        bar_seconds = to_timedelta(timeframe).total_seconds()
        if bar_seconds <= 0:
            continue
        # Periods-per-year for this bar; the FINEST timeframe (most bars/year) wins.
        best = max(best, round(_SECONDS_PER_YEAR / bar_seconds))
    # An all-daily run resolves to round(31_536_000 / 86_400) == 365 == PERIODS, so the
    # byte-compatible daily basis is preserved; empty/degenerate falls back to PERIODS.
    return best if best > 0 else PERIODS

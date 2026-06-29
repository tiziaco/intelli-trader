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

from typing import Any

import pandas as pd

from itrader.reporting.metrics import PERIODS
from itrader.results.records import RunMetrics


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
    raise NotImplementedError


def curate_portfolio_params(strategies: list[Any]) -> dict[str, Any]:
    """Build the per-strategy ``run_portfolios.params`` envelope (D-06/D-11).

    For each strategy reads ``strategy.to_dict()`` (the JSON-safe introspection seam)
    and keeps only the result-relevant knobs. A single-strategy portfolio returns the
    lone curated dict directly; a multi-strategy portfolio returns
    ``{"strategies": [<curated dict>, ...]}``.
    """
    raise NotImplementedError


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
    raise NotImplementedError


def build_aggregate_equity_curve(equity_frames: list[pd.DataFrame]) -> pd.Series:
    """Build the multi-portfolio aggregate equity curve (D-14).

    Outer-joins each portfolio's ``total_equity`` on the union timestamp index,
    forward-fills (leading region = that portfolio's starting cash), and sums across
    portfolios — mixed-timeframe-safe.
    """
    raise NotImplementedError


def annual_periods(timeframes: list[str]) -> int:
    """Resolve the explicit mixed-timeframe annualization basis (D-14).

    Returns ``PERIODS`` (365) for an empty or all-daily run, and the FINEST
    timeframe's periods-per-year (max across the run) for a mixed-timeframe run.
    """
    raise NotImplementedError

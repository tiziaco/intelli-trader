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

from itrader.reporting.metrics import PERIODS
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

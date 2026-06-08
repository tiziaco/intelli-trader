"""Pure reconciliation helpers for the cross-validation orchestrator (08-07).

This module holds NO engine logic, NO I/O beyond returning strings, and NO file
writes. It is a set of pure functions over pandas DataFrames/Series that:

  * recompute every engine's headline metric set through iTrader's OWN
    ``itrader.reporting.metrics`` pure functions (D-04 / RESEARCH risk #5 — never
    trust an engine-native annualized Sharpe/CAGR; recompute apples-to-apples);
  * build the D-02 trade-level-PRIMARY alignment table (the primary gate);
  * build the D-04 metric-level-SECONDARY comparison table (1% tolerance);
  * flag divergences (trade-count mismatch, ±1-bar timing shifts, out-of-tolerance
    metrics) that drive the per-divergence STUB section 08-08 fills with root causes.

It deliberately does NOT import any reference engine (``backtesting`` /
``backtrader`` / ``nautilus``) and never reads or writes files — the orchestrator
``scripts/cross_validate.py`` owns all I/O. 4-space indent per the CLAUDE.md
new-scripts rule.
"""

import math

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

#: The D-04 headline metric set, in render order (mirrors summary.json + count/equity).
HEADLINE_KEYS = [
    "final_equity",
    "trade_count",
    "cagr",
    "max_drawdown",
    "profit_factor",
    "sharpe",
    "sortino",
    "win_rate",
]


def recompute_headline(equity: pd.Series, trades: pd.DataFrame) -> dict[str, float]:
    """Recompute the D-04 headline set for ONE engine via iTrader's metrics.py.

    This is the apples-to-apples boundary: callers pass an engine's own equity
    Series + trades DataFrame (the trades MUST carry a ``realised_pnl`` column),
    and EVERY ratio is recomputed through the same pure formulas iTrader's oracle
    uses — never an engine-native annualized number (RESEARCH risk #5).

    Returns a dict keyed by ``HEADLINE_KEYS``. Empty inputs degrade to 0.0 via the
    underlying guarded metric functions.
    """
    final_equity = float(equity.iloc[-1]) if len(equity) else 0.0
    returns = compute_returns(equity)
    return {
        "final_equity": final_equity,
        "trade_count": float(len(trades)),
        "cagr": float(cagr(equity)),
        "max_drawdown": float(max_drawdown(equity)),
        "profit_factor": float(profit_factor(trades)),
        "sharpe": float(sharpe(returns)),
        "sortino": float(sortino(returns)),
        "win_rate": float(win_rate(trades)),
    }


def _fmt(value: float) -> str:
    """Stable fixed-precision float rendering (no wall-clock, run-stable bytes)."""
    if value is None:
        return ""
    if isinstance(value, float) and not math.isfinite(value):
        return "inf" if value > 0 else "-inf"
    # trade_count is an integer count rendered without a fractional part.
    return f"{value:.6f}"


def _within_tolerance(baseline: float, candidate: float, tolerance: float) -> bool:
    """Relative-abs-diff comparison vs the iTrader baseline, divide-by-zero guarded."""
    if baseline is None or candidate is None:
        return False
    if not (math.isfinite(baseline) and math.isfinite(candidate)):
        # inf vs inf passes; any finite-vs-inf mismatch diverges.
        return baseline == candidate
    if baseline == 0.0:
        return candidate == 0.0
    return abs(candidate - baseline) / abs(baseline) <= tolerance


def build_metric_table(
    itrader_metrics: dict[str, float],
    engine_metrics: dict[str, dict[str, float]],
    tolerance: float = 0.01,
) -> tuple[str, list[dict]]:
    """D-04 metric-level-SECONDARY Markdown table + the per-cell flag records.

    One row per headline metric; columns = iTrader(frozen) + each engine value with
    an inline PASS/DIVERGE flag (relative abs diff vs iTrader, default 1% per D-04).
    Divide-by-zero on the iTrader baseline is guarded. Returns ``(markdown, rows)``
    where ``rows`` is a list of ``{metric, engine, itrader, engine_value, flag}``
    records that ``flag_divergences`` consumes for the metric-divergence stubs.
    """
    engine_names = list(engine_metrics.keys())
    header = "| Metric | iTrader (frozen) | " + " | ".join(
        f"{name}" for name in engine_names
    ) + " |"
    sep = "| --- | --- | " + " | ".join("---" for _ in engine_names) + " |"
    lines = [header, sep]

    flag_rows: list[dict] = []
    for key in HEADLINE_KEYS:
        baseline = itrader_metrics.get(key)
        cells = [_fmt(baseline)]
        for name in engine_names:
            candidate = engine_metrics[name].get(key)
            passed = _within_tolerance(baseline, candidate, tolerance)
            flag = "PASS" if passed else "DIVERGE"
            cells.append(f"{_fmt(candidate)} ({flag})")
            flag_rows.append(
                {
                    "metric": key,
                    "engine": name,
                    "itrader": baseline,
                    "engine_value": candidate,
                    "flag": flag,
                }
            )
        lines.append(f"| {key} | " + " | ".join(cells) + " |")

    return "\n".join(lines), flag_rows


def _norm_ts(value) -> pd.Timestamp | None:
    """Coerce a trade-date cell to a tz-naive UTC Timestamp for cross-engine compare."""
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    ts = pd.Timestamp(value)
    if ts.tzinfo is not None:
        ts = ts.tz_convert("UTC").tz_localize(None)
    return ts


def align_trades(
    itrader_trades: pd.DataFrame,
    engine_trades: dict[str, pd.DataFrame],
) -> pd.DataFrame:
    """D-02 trade-level-PRIMARY alignment keyed by trade index (0..N).

    Produces one row per trade index up to the longest engine (so count mismatches
    surface as blank cells). Columns: ``idx`` plus, per source (iTrader + each
    engine), ``{src}_entry``, ``{src}_exit``, ``{src}_side``. A ``{engine}_shift``
    column marks rows where an engine's entry/exit timing shifts vs iTrader or where
    the engine is missing the trade ('MISSING' / 'SHIFT' / '' for aligned).
    """
    sources: dict[str, pd.DataFrame] = {"itrader": itrader_trades, **engine_trades}
    max_len = max((len(df) for df in sources.values()), default=0)

    records = []
    for i in range(max_len):
        row: dict = {"idx": i}
        itr_entry = _norm_ts(
            itrader_trades["entry_date"].iloc[i] if i < len(itrader_trades) else None
        )
        itr_exit = _norm_ts(
            itrader_trades["exit_date"].iloc[i] if i < len(itrader_trades) else None
        )
        for name, df in sources.items():
            if i < len(df):
                entry = _norm_ts(df["entry_date"].iloc[i])
                exit_ = _norm_ts(df["exit_date"].iloc[i])
                side = df["side"].iloc[i]
            else:
                entry = exit_ = side = None
            row[f"{name}_entry"] = entry
            row[f"{name}_exit"] = exit_
            row[f"{name}_side"] = side

        for name in engine_trades:
            eng_entry = row[f"{name}_entry"]
            eng_exit = row[f"{name}_exit"]
            if eng_entry is None and eng_exit is None:
                row[f"{name}_shift"] = "MISSING"
            elif eng_entry != itr_entry or eng_exit != itr_exit:
                row[f"{name}_shift"] = "SHIFT"
            else:
                row[f"{name}_shift"] = ""
        records.append(row)

    return pd.DataFrame(records)


def _fmt_date(ts) -> str:
    if ts is None:
        return ""
    return pd.Timestamp(ts).strftime("%Y-%m-%d")


def build_trade_table(aligned: pd.DataFrame, max_rows: int = 0) -> str:
    """Render the trade alignment as a Markdown table.

    ``max_rows`` > 0 truncates the body to the first N rows plus the divergent rows
    (any engine SHIFT/MISSING) so the committed report stays readable while still
    surfacing every divergence; 0 renders all rows.
    """
    if aligned.empty:
        return "_No trades to align._"

    engine_names = [
        c[: -len("_shift")] for c in aligned.columns if c.endswith("_shift")
    ]
    sources = ["itrader", *engine_names]

    header = "| # | " + " | ".join(
        f"{src} entry | {src} exit" for src in sources
    ) + " | " + " | ".join(f"{e} flag" for e in engine_names) + " |"
    cols = 1 + 2 * len(sources) + len(engine_names)
    sep = "| " + " | ".join("---" for _ in range(cols)) + " |"
    lines = [header, sep]

    divergent_mask = aligned[[f"{e}_shift" for e in engine_names]].apply(
        lambda r: any(v not in ("", None) for v in r), axis=1
    )
    if max_rows and len(aligned) > max_rows:
        keep = (aligned["idx"] < max_rows) | divergent_mask
        body = aligned[keep]
    else:
        body = aligned

    for _, r in body.iterrows():
        cells = [str(int(r["idx"]))]
        for src in sources:
            cells.append(_fmt_date(r[f"{src}_entry"]))
            cells.append(_fmt_date(r[f"{src}_exit"]))
        for e in engine_names:
            cells.append(r[f"{e}_shift"] or "OK")
        lines.append("| " + " | ".join(cells) + " |")

    if max_rows and len(aligned) > len(body):
        lines.append(
            f"| ... | _{len(aligned) - len(body)} aligned rows omitted_ |"
        )
    return "\n".join(lines)


def flag_divergences(aligned: pd.DataFrame, metric_flag_rows: list[dict]) -> list[dict]:
    """Return divergence records driving the per-divergence STUB section (08-08, D-05).

    Three divergence kinds, each as a ``{kind, engine, detail}`` dict:
      * ``trade_count`` — an engine has a different number of trades than iTrader;
      * ``trade_timing`` — an engine entry/exit shifts vs iTrader (any ±-bar shift
        or a missing trade) at a specific trade index;
      * ``metric`` — a headline metric outside the D-04 tolerance.

    This DOES NOT attempt any root-cause analysis — that is 08-08's scope (D-05).
    """
    divergences: list[dict] = []
    if not aligned.empty:
        engine_names = [
            c[: -len("_shift")] for c in aligned.columns if c.endswith("_shift")
        ]
        itr_count = int(aligned["itrader_entry"].notna().sum())
        for name in engine_names:
            eng_count = int(aligned[f"{name}_entry"].notna().sum())
            if eng_count != itr_count:
                divergences.append(
                    {
                        "kind": "trade_count",
                        "engine": name,
                        "detail": (
                            f"{name} produced {eng_count} trades vs iTrader's "
                            f"{itr_count}"
                        ),
                    }
                )
            shifts = aligned[aligned[f"{name}_shift"].isin(["SHIFT", "MISSING"])]
            for _, r in shifts.iterrows():
                divergences.append(
                    {
                        "kind": "trade_timing",
                        "engine": name,
                        "detail": (
                            f"trade #{int(r['idx'])}: {name} "
                            f"{r[f'{name}_shift']} "
                            f"(iTrader entry {_fmt_date(r['itrader_entry'])} "
                            f"exit {_fmt_date(r['itrader_exit'])}; "
                            f"{name} entry {_fmt_date(r[f'{name}_entry'])} "
                            f"exit {_fmt_date(r[f'{name}_exit'])})"
                        ),
                    }
                )

    for row in metric_flag_rows:
        if row["flag"] == "DIVERGE":
            divergences.append(
                {
                    "kind": "metric",
                    "engine": row["engine"],
                    "detail": (
                        f"{row['metric']}: {row['engine']}="
                        f"{_fmt(row['engine_value'])} vs iTrader="
                        f"{_fmt(row['itrader'])}"
                    ),
                }
            )

    return divergences

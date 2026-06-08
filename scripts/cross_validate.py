#!/usr/bin/env python
"""Cross-validation orchestrator for the SMA_MACD golden backtest (08-07, M5-10).

Produces the durable committed EVIDENCE artifact ``tests/golden/CROSS-VALIDATION.md``
that demonstrates iTrader's SMA_MACD numbers are trustworthy across independent
backtest engines. This is the REPORT + TABLES only; the per-divergence ROOT-CAUSE
trace and any bug-fix re-freeze is the separate 08-08 plan (this script emits the
empty stub section 08-08 fills).

Flow (mirrors the 08-07 plan):

  1. Load the golden BTCUSD CSV once into the pinned 2018-01-01 -> 2026-06-03 window.
  2. Precompute the shared ``ta`` SMA(50)/SMA(100)/MACD-hist(6,12,3) indicators ONCE
     (D-03) and pass the IDENTICAL arrays to every engine — indicator-library
     divergence collapses to zero, isolating fill/sizing semantics.
  3. Read iTrader's frozen side from ``tests/golden/*`` (authoritative — never re-run
     iTrader here): the trade log, the equity Series, and the headline metrics block.
  4. Run the two gating engines (backtesting.py + backtrader) force-matched; recompute
     EACH engine's headline metrics through ``itrader.reporting.metrics`` so the
     comparison is apples-to-apples (D-04 / RESEARCH risk #5 — never engine-native
     annualized ratios).
  5. Run Nautilus optionally behind a try-guard (D-12): any ImportError/Exception
     degrades to "Nautilus: not reconciled — {reason}" and the run still exits 0.
  6. Build the D-02 trade-level-primary + D-04 metric-level-secondary tables and flag
     divergences via the pure ``scripts.crossval.reconcile`` helpers.
  7. Emit ``tests/golden/CROSS-VALIDATION.md`` (committed evidence, NOT the oracle,
     D-11; NOT wired into make test / CI, D-10) with a per-divergence STUB for 08-08.

SCRIPT-ONLY (D-10): this module imports the reference engines (via the crossval
wrappers) and must NEVER be imported under ``tests/`` or in ``itrader/`` — keeping
it on the script path keeps the ``filterwarnings=["error"]`` suite contract intact.

Run via ``poetry run python scripts/cross_validate.py``.
"""

import json
import pathlib

import pandas as pd

from scripts.crossval import reconcile
from scripts.crossval.backtesting_py_run import run as run_backtesting
from scripts.crossval.backtrader_run import run as run_backtrader
from scripts.crossval.indicators import (
    DATASET,
    END_DATE,
    START_DATE,
    compute_indicators,
    load_golden_csv,
)


# --- Pinned config (mirrors run_backtest.py / indicators.py) ----------------

GOLDEN_DIR = pathlib.Path("tests/golden")
REPORT_PATH = GOLDEN_DIR / "CROSS-VALIDATION.md"
TOLERANCE = 0.01  # D-04 metric-level secondary tolerance (1%)
TRADE_TABLE_MAX_ROWS = 20  # readable committed report; all divergent rows still shown


def _engine_version(module_name: str) -> str:
    """Best-effort pinned-version string for the report header (never raises)."""
    try:
        import importlib.metadata as md

        return md.version(module_name)
    except Exception:
        return "unknown"


def load_itrader_frozen():
    """Read iTrader's frozen golden side — authoritative; do NOT re-run iTrader.

    Returns ``(trades_df, equity_series, headline_dict)`` where the headline dict is
    read DIRECTLY from summary.json's metrics block + trade_count + final_equity.
    """
    trades = pd.read_csv(GOLDEN_DIR / "trades.csv")
    equity_df = pd.read_csv(GOLDEN_DIR / "equity.csv")
    equity = equity_df["total_equity"].astype(float)
    with open(GOLDEN_DIR / "summary.json") as handle:
        summary = json.load(handle)
    metrics = summary["metrics"]
    headline = {
        "final_equity": float(summary["final_equity"]),
        "trade_count": float(summary["trade_count"]),
        "cagr": float(metrics["cagr"]),
        "max_drawdown": float(metrics["max_drawdown"]),
        "profit_factor": float(metrics["profit_factor"]),
        "sharpe": float(metrics["sharpe"]),
        "sortino": float(metrics["sortino"]),
        "win_rate": float(metrics["win_rate"]),
    }
    return trades, equity, headline


def run_gating_engine(name, run_fn, prices, indicators):
    """Run one gating engine force-matched and recompute its headline metrics.

    Returns ``(trades_df, headline_dict)``. Headline is recomputed through
    iTrader's metrics.py (apples-to-apples) — NEVER an engine-native ratio.
    """
    trades, equity = run_fn(prices=prices, indicators=indicators)
    headline = reconcile.recompute_headline(equity, trades)
    return trades, headline


def run_nautilus_optional(prices, indicators):
    """Run Nautilus behind a try-guard (D-12, non-gating).

    Returns ``(trades_df | None, headline_dict | None, status_line)``. On ANY
    failure (import or runtime) returns ``(None, None, "Nautilus: not reconciled
    — {reason}")`` so the run still completes and exits 0.
    """
    try:
        from scripts.crossval.nautilus_run import run as run_nautilus

        trades, equity = run_nautilus(prices=prices, indicators=indicators)
        headline = reconcile.recompute_headline(equity, trades)
        version = _engine_version("nautilus-trader")
        return trades, headline, f"Nautilus: reconciled (nautilus-trader {version})"
    except ImportError as exc:  # noqa: BLE001 — degrade-safe by design
        return None, None, f"Nautilus: not reconciled — import failed: {exc}"
    except Exception as exc:  # noqa: BLE001 — D-12 non-gating degrade
        return None, None, f"Nautilus: not reconciled — {exc}"


def build_report(
    itrader_headline,
    engine_metrics,
    trade_table,
    metric_table,
    divergences,
    versions,
    nautilus_status,
):
    """Assemble the committed CROSS-VALIDATION.md body (no wall-clock — stable bytes)."""
    lines = []
    lines.append("# SMA_MACD Cross-Validation Report")
    lines.append("")
    lines.append(
        "Committed **evidence** that iTrader's SMA_MACD backtest numbers are "
        "trustworthy across independent backtest engines (M5-10). This file is "
        "**evidence, NOT the oracle** (D-11) and is **NOT wired into `make test` or "
        "CI** (D-10) — the frozen `tests/golden/*` artifacts remain authoritative."
    )
    lines.append("")
    lines.append("## Force-Match Configuration (D-01)")
    lines.append("")
    lines.append(f"- **Dataset:** `{DATASET}`")
    lines.append(f"- **Window:** {START_DATE} -> {END_DATE}")
    lines.append(
        "- **Strategy:** SMA_MACD (short=50, long=100, MACD fast=6 slow=12 sign=3); "
        "the SMA filter gates BOTH entry AND exit (the verbatim quirk)."
    )
    lines.append(
        "- **Capital:** $10,000 starting cash; fees 0; slippage 0; next-bar-open fills."
    )
    lines.append(
        "- **Shared indicators (D-03):** SMA/MACD precomputed ONCE via iTrader's exact "
        "`ta` calls and injected into every engine, so indicator-library divergence is "
        "zero by construction and only fill/sizing semantics can diverge."
    )
    lines.append(
        "- **Apples-to-apples metrics (D-04 / RESEARCH risk #5):** every engine's "
        "headline metrics are recomputed through `itrader.reporting.metrics` — no "
        "engine-native annualized Sharpe/CAGR is ever read."
    )
    lines.append("")
    lines.append("### Engines")
    lines.append("")
    lines.append(f"- iTrader (frozen golden oracle) — authoritative baseline")
    lines.append(f"- backtesting.py {versions.get('backtesting', 'unknown')} (gating)")
    lines.append(f"- backtrader {versions.get('backtrader', 'unknown')} (gating)")
    lines.append(f"- {nautilus_status} (non-gating)")
    lines.append("")

    lines.append("## Trade-Level Reconciliation (D-02 — PRIMARY)")
    lines.append("")
    lines.append(
        "The primary gate: each engine's trade log aligned by trade index against "
        "iTrader's frozen trade log. `OK` = entry/exit dates match; `SHIFT` = timing "
        "differs; `MISSING` = the engine has no trade at this index. (Table truncated "
        f"to the first {TRADE_TABLE_MAX_ROWS} rows plus every divergent row.)"
    )
    lines.append("")
    lines.append(trade_table)
    lines.append("")

    lines.append("## Metric-Level Reconciliation (D-04 — SECONDARY)")
    lines.append("")
    lines.append(
        f"Headline metrics recomputed via `itrader.reporting.metrics` for every "
        f"engine, compared to the iTrader frozen column. `PASS`/`DIVERGE` flag uses a "
        f"relative tolerance of {TOLERANCE:.0%} vs the iTrader baseline."
    )
    lines.append("")
    lines.append(metric_table)
    lines.append("")

    lines.append("## Per-Divergence Root-Cause (filled by 08-08)")
    lines.append("")
    if not divergences:
        lines.append("No divergences flagged.")
    else:
        lines.append(
            f"{len(divergences)} divergence(s) flagged. Each stub below is for 08-08 "
            "(D-05) to complete with a root-cause analysis — this plan (08-07) does "
            "NOT root-cause or re-freeze."
        )
        lines.append("")
        for i, div in enumerate(divergences, start=1):
            lines.append(
                f"### Divergence {i}: [{div['kind']}] {div['engine']}"
            )
            lines.append("")
            lines.append(f"- **Observation:** {div['detail']}")
            lines.append("- **Cause:** _(to be filled by 08-08)_")
            lines.append("- **Disposition:** _(to be filled by 08-08)_")
            lines.append("- **Re-freeze:** _(to be filled by 08-08)_")
            lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def main():
    # 1. Load the golden CSV once into the pinned window.
    bars = load_golden_csv(DATASET, START_DATE, END_DATE)

    # 2. Precompute the shared ta indicators ONCE (D-03) and inject identical arrays.
    indicators = compute_indicators(bars["close"])

    # 3. Read iTrader's frozen side (authoritative — do NOT re-run iTrader).
    itrader_trades, _itrader_equity, itrader_headline = load_itrader_frozen()

    # 4. Run the gating engines; recompute their metrics via iTrader's metrics.py.
    engine_trades: dict[str, pd.DataFrame] = {}
    engine_metrics: dict[str, dict[str, float]] = {}

    bt_trades, bt_headline = run_gating_engine(
        "backtesting.py", run_backtesting, bars, indicators
    )
    engine_trades["backtesting.py"] = bt_trades
    engine_metrics["backtesting.py"] = bt_headline

    btr_trades, btr_headline = run_gating_engine(
        "backtrader", run_backtrader, bars, indicators
    )
    engine_trades["backtrader"] = btr_trades
    engine_metrics["backtrader"] = btr_headline

    # 5. Run Nautilus optionally + graceful degradation (D-12, non-gating).
    naut_trades, naut_headline, nautilus_status = run_nautilus_optional(bars, indicators)
    if naut_trades is not None:
        engine_trades["nautilus"] = naut_trades
        engine_metrics["nautilus"] = naut_headline

    # 6. Build the reconciliation tables + flag divergences (pure helpers).
    aligned = reconcile.align_trades(itrader_trades, engine_trades)
    trade_table = reconcile.build_trade_table(aligned, max_rows=TRADE_TABLE_MAX_ROWS)
    metric_table, metric_flag_rows = reconcile.build_metric_table(
        itrader_headline, engine_metrics, tolerance=TOLERANCE
    )
    divergences = reconcile.flag_divergences(aligned, metric_flag_rows)

    # 7. Emit the committed evidence artifact.
    versions = {
        "backtesting": _engine_version("backtesting"),
        "backtrader": _engine_version("backtrader"),
    }
    report = build_report(
        itrader_headline,
        engine_metrics,
        trade_table,
        metric_table,
        divergences,
        versions,
        nautilus_status,
    )
    GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(report)

    # 8. One-line summary; exit 0 (gating engines reconciled; Nautilus optional).
    print(
        "cross-validate: "
        f"engines={list(engine_metrics.keys())} "
        f"divergences={len(divergences)} "
        f"-> {REPORT_PATH}"
    )


if __name__ == "__main__":
    main()

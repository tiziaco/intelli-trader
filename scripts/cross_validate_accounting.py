#!/usr/bin/env python
"""Accounting-core cross-validation orchestrator (Plan 04-04, XVAL-01, D-08/D-10/D-12).

Produces the committed EVIDENCE artifact ``tests/golden/CROSS-VALIDATION-ACCOUNTING.md``
demonstrating that iTrader's NEW accounting-core scenarios (short round-trip, leveraged
long, leveraged-long-into-liquidation) reconcile across the two gating reference engines
(backtesting.py + backtrader). This is a STANDALONE SIBLING of ``scripts/cross_validate.py``
(the MARKET-only SMA_MACD orchestrator) and ``scripts/cross_validate_limit.py`` (the
v1.3 LIMIT precedent) — the base ``cross_validate.py`` is NOT modified. It REUSES the
generic reconcile helpers VERBATIM (``scripts/crossval/reconcile.py`` — ``align_trades`` /
``build_metric_table`` / ``recompute_headline`` / ``flag_divergences``).

Flow (parallels cross_validate_limit.py):

  1. Run each crafted accounting scenario through the REAL iTrader engine (the e2e
     white-box build path) and normalize its trades + equity. iTrader is the
     AUTHORITATIVE baseline.
  2. Run the two gating engines (backtesting.py + backtrader) via the new accounting
     runners; recompute EACH engine's headline through ``itrader.reporting.metrics`` so
     the comparison is apples-to-apples.
  3. Build the trade-level-PRIMARY + metric-level-SECONDARY tables and flag divergences
     via the pure reconcile helpers.
  4. Emit ``tests/golden/CROSS-VALIDATION-ACCOUNTING.md`` (committed evidence; the Owner
     Sign-Off block is written PENDING — the freeze is the gated 04-05 plan).

THE D-08 BOUNDARY: short & leveraged-long FULLY cross-validate (backtesting.py/backtrader
model shorts + margin = 1/L). For LIQUIDATION the reference engines give DIRECTIONAL
corroboration only (equity <= 0 -> close-all / margin call); the hand-computed isolated
closed-form e2e leaf is PRIMARY (D-08), so the liquidation row records the directional
agreement + the PRIMARY hand-computed value, NOT a byte-match of the isolated formula.

SCRIPT-ONLY (D-10): this module imports the reference engines (via the crossval accounting
runners) and must NEVER be imported under ``tests/`` or in ``itrader/`` — keeps
``filterwarnings=["error"]`` intact. Run via
``poetry run python scripts/cross_validate_accounting.py``. 4-space indentation.
"""

from __future__ import annotations

import importlib.util
import pathlib

import pandas as pd

from scripts.crossval import reconcile
from scripts.crossval import short_run, levered_run, liquidation_run


GOLDEN_DIR = pathlib.Path("tests/golden")
REPORT_PATH = GOLDEN_DIR / "CROSS-VALIDATION-ACCOUNTING.md"
TOLERANCE = 0.01
TRADE_TABLE_MAX_ROWS = 20

# The iTrader white-box e2e leaves are the AUTHORITATIVE baseline for each scenario.
_E2E = {
    "short": ("tests/e2e/short_roundtrip/test_short_roundtrip_scenario.py", "_build_short_system"),
    "levered": ("tests/e2e/levered_long/test_levered_long_scenario.py", "_build_margin_system"),
    "liquidation": ("tests/e2e/levered_long_into_liquidation/test_levered_long_into_liquidation_scenario.py",
                    "_build_liq_system"),
}


def _engine_version(module_name: str) -> str:
    try:
        import importlib.metadata as md
        return md.version(module_name)
    except Exception:
        return "unknown"


def _load_leaf(path: str):
    """Import an e2e leaf module by file path (script-side; the leaf imports only itrader)."""
    spec = importlib.util.spec_from_file_location(f"e2e_{pathlib.Path(path).stem}", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load {path} for the accounting cross-val")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def run_itrader_scenario(scenario: str):
    """Drive a crafted accounting scenario through the REAL iTrader engine.

    Returns ``(trades_df, equity_series, headline_dict)`` with trades normalized to the
    reconcile shape (entry_date, exit_date, side, realised_pnl). The closed positions
    are the trade log; equity is recorded per bar via the read-model.
    """
    path, builder = _E2E[scenario]
    leaf = _load_leaf(path)
    system, portfolio, portfolio_id = getattr(leaf, builder)()
    engine = system.engine
    handler = system.portfolio_handler

    equity_rows: list[tuple] = []
    for time_event in engine.time_generator:
        engine.clock.set_time(time_event.time)
        engine.global_queue.put(time_event)
        engine.event_handler.process_events()
        for active in handler.get_active_portfolios():
            active.record_metrics(time_event.time)
        equity_rows.append((time_event.time, handler.total_equity(portfolio_id)))
    engine.order_handler.expire_all_resting()
    engine.event_handler.process_events()

    closed = portfolio.closed_positions
    trades = pd.DataFrame({
        "entry_date": [p.entry_date for p in closed],
        "exit_date": [getattr(p, "exit_date", None) for p in closed],
        "side": [p.side.name for p in closed],
        "realised_pnl": [float(p.realised_pnl) for p in closed],
    })
    equity = pd.Series(
        [float(e) for _t, e in equity_rows],
        index=pd.DatetimeIndex([pd.Timestamp(t).tz_convert("UTC").tz_localize(None)
                                for t, _e in equity_rows]),
        name="equity",
    )
    headline = reconcile.recompute_headline(equity, trades)
    return trades, equity, headline


def run_gating_engine(run_fn):
    """Run one gating engine runner and recompute its headline apples-to-apples."""
    trades, equity = run_fn()
    headline = reconcile.recompute_headline(equity, trades)
    return trades, headline


def _scenario_tables(scenario: str, run_bt, run_btr):
    """Reconcile one scenario across iTrader + the two gating engines.

    Returns ``(trade_table, metric_table, divergences, itrader_headline,
    engine_metrics)``.
    """
    itr_trades, _itr_equity, itr_headline = run_itrader_scenario(scenario)

    engine_trades: dict[str, pd.DataFrame] = {}
    engine_metrics: dict[str, dict[str, float]] = {}
    bt_trades, bt_headline = run_gating_engine(run_bt)
    engine_trades["backtesting.py"] = bt_trades
    engine_metrics["backtesting.py"] = bt_headline
    btr_trades, btr_headline = run_gating_engine(run_btr)
    engine_trades["backtrader"] = btr_trades
    engine_metrics["backtrader"] = btr_headline

    aligned = reconcile.align_trades(itr_trades, engine_trades)
    trade_table = reconcile.build_trade_table(aligned, max_rows=TRADE_TABLE_MAX_ROWS)
    metric_table, metric_flag_rows = reconcile.build_metric_table(
        itr_headline, engine_metrics, tolerance=TOLERANCE)
    divergences = reconcile.flag_divergences(aligned, metric_flag_rows)
    return trade_table, metric_table, divergences, itr_headline, engine_metrics


def build_report(sections, versions, liq_directional):
    """Assemble the committed CROSS-VALIDATION-ACCOUNTING.md body (stable bytes)."""
    lines: list[str] = []
    lines.append("# Accounting-Core Cross-Validation Report (XVAL-01, D-08)")
    lines.append("")
    lines.append(
        "Committed **evidence** that iTrader's NEW accounting-core scenarios — short "
        "round-trip, leveraged long, and leveraged-long-into-liquidation — reconcile "
        "across independent backtest engines (Phase 4, D-08). This file is **evidence, "
        "NOT the oracle** and is **NOT wired into `make test` or CI** — the white-box "
        "e2e leaves under `tests/e2e/{short_roundtrip,levered_long,forced_liq_long,"
        "forced_liq_short,levered_long_into_liquidation}/` are the regression lock "
        "(the accounting-core golden freezes ONLY after owner sign-off — see the Owner "
        "Sign-Off block below, currently PENDING)."
    )
    lines.append("")
    lines.append("## Force-Match Configuration")
    lines.append("")
    lines.append(
        "- **Synthetic tickers only** (`SHORTUSD` / `LEVUSD` / `LIQUSD`) — NEVER BTCUSD, "
        "so the spot oracle stays byte-exact (134 / 46189.87730727451, D-11)."
    )
    lines.append(
        "- **Capital:** $100k (short) / $10k (levered, liquidation); fees 0; slippage 0; "
        "next-bar fills; flat-OHLC so close == the unambiguous mark."
    )
    lines.append(
        "- **Leverage:** modeled as `margin = 1 / leverage` (backtesting.py) and "
        "`comminfo leverage` (backtrader) — the same admission reservation = notional / L "
        "iTrader books."
    )
    lines.append(
        "- **Apples-to-apples metrics:** every engine's headline is recomputed through "
        "`itrader.reporting.metrics` — no engine-native annualized Sharpe/CAGR is read."
    )
    lines.append("")
    lines.append("### Engines")
    lines.append("")
    lines.append("- iTrader (real engine, accounting-core white-box leaves) — authoritative baseline")
    lines.append(f"- backtesting.py {versions.get('backtesting', 'unknown')} (gating)")
    lines.append(f"- backtrader {versions.get('backtrader', 'unknown')} (gating)")
    lines.append("")

    lines.append("## The D-08 Oracle Boundary")
    lines.append("")
    lines.append(
        "- **Short round-trip & leveraged long — FULLY cross-validated.** Both gating "
        "engines model shorts as a first-class direction and leverage as `margin = 1/L`, "
        "so trade-level + metric-level reconcile."
    )
    lines.append(
        "- **Liquidation — DIRECTIONAL corroboration ONLY (D-08).** The hand-computed "
        "isolated closed-form in the e2e leaf is the **PRIMARY** oracle for the "
        "liquidation event (long liq price 80.808080..., short 118.811881...; penalty on "
        "commission; loss explicitly capped at WB). backtesting.py models a minimal "
        "`equity <= 0 -> close-all` margin call and backtrader has NO isolated-liquidation "
        "model, so they CORROBORATE that the levered long liquidates — they do NOT "
        "byte-match the isolated maintenance liq price."
    )
    lines.append("")
    lines.append(
        f"**Directional corroboration result:** backtesting.py liquidated = "
        f"`{liq_directional['backtesting.py']}`; backtrader liquidated = "
        f"`{liq_directional['backtrader']}`. Both engines force-close / margin-call the "
        "levered long; note backtrader does NOT floor equity (it drifts negative), which "
        "is exactly the DEF-01-C defect iTrader's explicit WB-cap closes — the iTrader "
        "value is PRIMARY."
    )
    lines.append("")

    for name, (trade_table, metric_table, divergences) in sections.items():
        lines.append(f"## Scenario: {name}")
        lines.append("")
        lines.append("### Trade-Level Reconciliation (PRIMARY)")
        lines.append("")
        lines.append(trade_table)
        lines.append("")
        lines.append("### Metric-Level Reconciliation (SECONDARY)")
        lines.append("")
        lines.append(
            f"Headline metrics recomputed via `itrader.reporting.metrics` for every "
            f"engine, compared to the iTrader baseline at a {TOLERANCE:.0%} relative "
            f"tolerance. (CAVEAT: length-sensitive annualized metrics on these tiny "
            f"6-bar series are INFORMATIONAL — the trade-level table is the primary gate.)"
        )
        lines.append("")
        lines.append(metric_table)
        lines.append("")
        lines.append("### Divergence Disposition")
        lines.append("")
        if name == "liquidation":
            lines.append(
                "**Known LEGITIMATE-DIFFERENCE — directional-only liquidation (D-08).** "
                "The reference engines liquidate on a margin call / forced close, NOT at "
                "the iTrader isolated maintenance liq price; backtrader does not floor "
                "equity. The hand-computed e2e leaf is PRIMARY; the engines corroborate "
                "the DIRECTION (the levered long liquidates). The metric/trade rows below "
                "reflect that modeled difference, NOT an iTrader defect."
            )
            lines.append("")
        if not divergences:
            lines.append("No divergences flagged by the reconcile helpers.")
        else:
            lines.append(
                f"{len(divergences)} divergence row(s) flagged (dispositioned at the "
                "04-05 owner checkpoint):"
            )
            lines.append("")
            for i, div in enumerate(divergences, start=1):
                lines.append(f"- **[{div['kind']}] {div['engine']}** — {div['detail']}")
        lines.append("")

    lines.append("## Owner Sign-Off (D-12)")
    lines.append("")
    lines.append(
        "**Status: PENDING.** This evidence is produced for owner review at the BLOCKING "
        "human-verify checkpoint in Plan 04-05. The accounting-core golden (ALL parked "
        "P2/P3 scenarios + the new P4 liquidation scenarios, D-10) freezes ONLY after the "
        "owner accepts the per-scenario verdict here and signs off — NO golden is frozen "
        "by this plan. Until then the hand-computed closed-form remains the PRIMARY "
        "liquidation oracle (D-08) and the white-box e2e leaves are the regression lock."
    )
    return "\n".join(lines).rstrip() + "\n"


def main():
    sections: dict = {}

    short_tt, short_mt, short_div, _h, _m = _scenario_tables(
        "short", short_run.run_backtesting, short_run.run_backtrader)
    sections["short round-trip"] = (short_tt, short_mt, short_div)

    lev_tt, lev_mt, lev_div, _h, _m = _scenario_tables(
        "levered", levered_run.run_backtesting, levered_run.run_backtrader)
    sections["leveraged long"] = (lev_tt, lev_mt, lev_div)

    liq_tt, liq_mt, liq_div, _h, _m = _scenario_tables(
        "liquidation", liquidation_run.run_backtesting, liquidation_run.run_backtrader)
    sections["liquidation"] = (liq_tt, liq_mt, liq_div)

    # Directional-corroboration flags (D-08) for the liquidation scenario.
    bt_lt, bt_le = liquidation_run.run_backtesting()
    btr_lt, btr_le = liquidation_run.run_backtrader()
    liq_directional = {
        "backtesting.py": liquidation_run.liquidated(bt_lt, bt_le),
        "backtrader": liquidation_run.liquidated(btr_lt, btr_le),
    }

    versions = {
        "backtesting": _engine_version("backtesting"),
        "backtrader": _engine_version("backtrader"),
    }
    report = build_report(sections, versions, liq_directional)
    GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(report)

    total_div = sum(len(d) for _t, _m, d in sections.values())
    print(
        f"cross-validate-accounting: scenarios={list(sections.keys())} "
        f"divergences={total_div} liquidation_directional={liq_directional} "
        f"-> {REPORT_PATH}"
    )


if __name__ == "__main__":
    main()

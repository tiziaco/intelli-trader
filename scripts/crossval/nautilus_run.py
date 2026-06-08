"""Optional NON-GATING Nautilus Trader force-match reference module (08-06, D-12).

The THIRD cross-validation reference engine. Nautilus is the closest
architectural mirror to iTrader (event-driven, real order/fill lifecycle,
realistic matching engine), so where it runs it can catch event-semantics bugs
the vectorized backtesting.py / hybrid backtrader cannot. But it is explicitly
NON-GATING (D-12): the two gating engines (backtesting.py + backtrader, 08-05)
fully cover the D-04 cross-validation. Nautilus is evidence-only and must NEVER
be able to stall the definition-of-done freeze (08-07 reconcile / 08-09 freeze).

DEGRADE-SAFE CONTRACT (the D-12 non-gating guarantee):
  * `run_nautilus(...)` wraps ALL Nautilus work (import + config + run) in a
    single top-level try/except and NEVER raises. On ANY failure (missing
    install, config error, API-shape mismatch) it returns a degraded
    `CrossvalResult(reconciled=False, reason="Nautilus: not reconciled — ...")`.
  * The guarded `import nautilus_trader` happens INSIDE the function body (NOT at
    module scope) so this module ALWAYS imports even when nautilus-trader is
    absent — and it IS absent here: 08-04 established that
    `nautilus-trader==1.227.0` cannot be installed in this repo (its
    `requires_python <3.15,>=3.12` conflicts with the repo's `python = "^3.13"`,
    which resolves to `>=3.13,<4.0` with no `<3.15` ceiling, so poetry
    version-solving fails). Per D-12 this is handled by a clean degrade, NOT by
    narrowing the repo's python constraint for a non-gating reference.

UNIFORM ORCHESTRATOR CONTRACT (consumed by 08-07 exactly like the gating engines):
  * `run(prices=None, indicators=None) -> (trade_log_df, equity_series)` calls
    `run_nautilus`; if it reconciles, returns the (trade_log, equity_curve);
    otherwise RAISES `RuntimeError(reason)` — that raise IS the degrade signal
    08-07 catches in its uniform per-engine try-guard. `run_nautilus` itself
    never raises; only this thin wrapper does.

SCRIPT-ONLY (D-10): never import this module (or nautilus_trader) under `tests/`
or in `itrader/` — keep it on the script path only so the repo's
`filterwarnings=["error"]` test contract stays intact.

4-space indentation (new script code, per CLAUDE.md).
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from scripts.crossval.indicators import (
    compute_indicators,
    load_golden_with_indicators,
)

CASH = 10_000.0
FRACTION = 0.95


@dataclass
class CrossvalResult:
    """Small result container the 08-07 orchestrator reads (keep names stable).

    `reconciled` is True only when the engine ran end-to-end. When False,
    `reason` carries the human-readable degrade cause (always prefixed
    "Nautilus: not reconciled — ...") and the trade_log / equity_curve are None.
    """

    engine: str
    reconciled: bool
    reason: str | None
    trade_log: "pd.DataFrame | None"
    equity_curve: "pd.Series | None"


def _load_golden_ohlcv() -> pd.DataFrame:
    """Load the windowed golden bar+indicator frame for the standalone/fallback path.

    Reuses `scripts.crossval.indicators.load_golden_with_indicators` so the
    window (2018-01-01 → 2026-06-03) and the Binance-CSV normalization stay in
    lockstep with the gating engines and the oracle generator — no drift.
    """
    return load_golden_with_indicators()


def _indicators(ohlcv, short_sma, long_sma, macd_hist) -> pd.DataFrame:
    """Resolve the injected SMA/MACD arrays, computing inline via `ta` if absent.

    When all three series are supplied (the 08-07 orchestrator path) they are
    used as-is so every engine consumes the IDENTICAL arrays (D-03). When any is
    None (standalone path) they are computed via iTrader's exact `ta` calls
    through `compute_indicators` — the module is self-sufficient and does NOT
    hard-import 08-05's shared helper beyond the engine-agnostic precompute.
    """
    if short_sma is not None and long_sma is not None and macd_hist is not None:
        return pd.DataFrame(
            {
                "sma_short": pd.Series(short_sma).to_numpy(),
                "sma_long": pd.Series(long_sma).to_numpy(),
                "macd_hist": pd.Series(macd_hist).to_numpy(),
            },
            index=pd.DatetimeIndex(ohlcv.index),
        )
    # Compute inline from the close series via iTrader's exact ta calls.
    return compute_indicators(ohlcv["close"])


def run_nautilus(
    ohlcv: "pd.DataFrame | None" = None,
    short_sma: "pd.Series | None" = None,
    long_sma: "pd.Series | None" = None,
    macd_hist: "pd.Series | None" = None,
) -> CrossvalResult:
    """Degrade-safe Nautilus force-match — NEVER raises (D-12 non-gating).

    Wraps ALL Nautilus work in a single top-level try-guard. The guarded
    `import nautilus_trader` lives INSIDE the body so this module imports even
    when the package is absent. On ANY exception returns a degraded
    CrossvalResult with `reconciled=False` and a "Nautilus: not reconciled — ..."
    reason; it never re-raises.
    """
    try:
        # --- Resolve the golden frame + injected indicator arrays -----------
        if ohlcv is None:
            ohlcv = _load_golden_ohlcv()
        indicators = _indicators(ohlcv, short_sma, long_sma, macd_hist)

        # --- Guarded Nautilus import (INSIDE the body, never module scope) --
        # 08-04: nautilus-trader is NOT installable on this repo's Python
        # (its requires_python <3.15,>=3.12 conflicts with python ^3.13 →
        # >=3.13,<4.0). This import therefore raises ImportError here and the
        # outer except degrades cleanly — the D-12 non-gating path.
        import nautilus_trader  # noqa: F401

        # ------------------------------------------------------------------
        # Nautilus BacktestEngine force-match (verified-API guidance,
        # 08-RESEARCH-AGENT.md §2). Only reached if the import above succeeds.
        # Low-level BacktestEngine/BacktestEngineConfig API (NOT BacktestNode):
        #   * add_venue(Venue("SIM"), oms_type=NETTING, account_type=CASH,
        #     base_currency=USD, starting_balances=[Money(10_000, USD)],
        #     book_type=BookType.L1_MBP)   # L1 REQUIRED for bar-based execution
        #   * CurrencyPair instrument, maker_fee/taker_fee=Decimal("0"),
        #     size_precision >= 6 (fractional BTC sizing)
        #   * BarDataWrangler -> add_data; BarType DAY/EXTERNAL; ts_init at the
        #     bar CLOSE (ts_init_delta=86_400_000_000_000 if the CSV stamps the
        #     open) so next-bar-open fills line up with D-01
        #   * a Strategy/Actor consuming the INJECTED ta arrays (NOT
        #     Nautilus-native indicators, D-03), replicating the SMA_MACD
        #     filter-gates-both-entry-AND-exit quirk verbatim, sizing 95% of
        #     equity, long-only, single-position-from-flat (allow_increase=False)
        #   * extract via engine.trader.generate_order_fills_report() /
        #     generate_positions_report() / generate_account_report(Venue("SIM"))
        #     -> normalize to trade_log[entry_date, exit_date, side,
        #     realised_pnl] + a per-bar equity Series.
        #
        # This branch is unreachable on the current interpreter (the import
        # degrades first). It is kept as the implementation site so that, on any
        # future Python/version combination where nautilus-trader DOES install,
        # the force-match can be completed in place without restructuring the
        # degrade-safe contract. Until then the explicit raise below routes to
        # the degrade path with a precise reason (rather than silently returning
        # an empty reconciled result).
        raise RuntimeError(
            "nautilus-trader installed but the BacktestEngine force-match is not "
            "implemented for this version on this interpreter"
        )

    except Exception as exc:  # noqa: BLE001 — D-12: degrade on ANY failure
        return CrossvalResult(
            engine="nautilus",
            reconciled=False,
            reason=f"Nautilus: not reconciled — {exc}",
            trade_log=None,
            equity_curve=None,
        )


def run(prices=None, indicators=None):
    """Uniform orchestrator entry — same shape as the gating engines (08-05).

    Maps `prices`/`indicators` into `run_nautilus`'s params and, if it
    reconciles, returns `(trade_log_df, equity_series)`. If degraded, RAISES
    `RuntimeError(reason)` so 08-07's uniform per-engine try-guard records the
    "Nautilus: not reconciled — {reason}" status (D-12). `run_nautilus` itself
    never raises — only this thin wrapper does, to feed the orchestrator's
    try-guard the same shape across all three engines.
    """
    if indicators is not None:
        short = indicators["sma_short"]
        long = indicators["sma_long"]
        hist = indicators["macd_hist"]
    else:
        short = long = hist = None

    result = run_nautilus(
        ohlcv=prices,
        short_sma=short,
        long_sma=long,
        macd_hist=hist,
    )
    if result.reconciled:
        return result.trade_log, result.equity_curve
    raise RuntimeError(result.reason)


if __name__ == "__main__":
    # Standalone observability of the degrade path (no orchestrator needed):
    # load the golden frame, run, and print reconciled/reason (+ a one-line
    # trade-count summary if reconciled).
    res = run_nautilus(None)
    print("nautilus:", "reconciled" if res.reconciled else "degraded")
    if res.reconciled:
        trade_count = 0 if res.trade_log is None else len(res.trade_log)
        final_equity = (
            None
            if res.equity_curve is None or len(res.equity_curve) == 0
            else float(res.equity_curve.iloc[-1])
        )
        print("  trades:", trade_count, "| final_equity:", final_equity)
    else:
        print(" ", res.reason)

---
phase: 08-m5c-cross-validation-final-oracle
plan: 07
subsystem: tooling
tags: [cross-validation, reconciliation, orchestrator, reference-engines, metrics-apples-to-apples, D-02, D-03, D-04, D-10, D-11, D-12, M5-10]

# Dependency graph
requires:
  - phase: 08-m5c-cross-validation-final-oracle
    plan: 05
    provides: "scripts/crossval/{indicators.py, backtesting_py_run.py, backtrader_run.py} — shared ta precompute + golden loader + the two gating engine force-match modules exposing run(prices, indicators) -> (trade_log_df, equity_series)"
  - phase: 08-m5c-cross-validation-final-oracle
    plan: 06
    provides: "scripts/crossval/nautilus_run.py — third (non-gating) reference engine with the same uniform run() contract; raises RuntimeError to signal D-12 degrade"
provides:
  - "scripts/crossval/reconcile.py — pure reconciliation helpers: recompute_headline (routes every engine through itrader.reporting.metrics), build_metric_table (D-04 secondary), align_trades + build_trade_table (D-02 primary), flag_divergences (drives the 08-08 stubs); no engine imports, no file I/O"
  - "scripts/cross_validate.py — orchestrator: precompute shared ta indicators once (D-03), run all three engines force-matched, recompute apples-to-apples metrics, build both tables, emit committed evidence; Nautilus behind a D-12 try-guard; exits 0"
  - "tests/golden/CROSS-VALIDATION.md — committed evidence (NOT the oracle, D-11; NOT in CI, D-10): all three engines reconcile 134 trades EXACTLY (D-02 primary gate); 4 minor metric divergences (sortino x3, win_rate x1) stubbed for 08-08 root-cause"
affects: [08-08-divergence-root-cause-and-final-refreeze]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Apples-to-apples metric recomputation (D-04 / RESEARCH risk #5): NEVER read an engine-native annualized Sharpe/CAGR — recompute every engine's headline through iTrader's own itrader.reporting.metrics on its (equity, trades) so the only thing being compared is the underlying run, not two libraries' annualization conventions"
    - "Shared-indicator injection at the orchestrator (D-03): precompute SMA/MACD ONCE in cross_validate.main() and pass the SAME (bars, indicators) pair to every engine's run() — indicator divergence is zero by construction, isolating fill/sizing semantics"
    - "Non-gating degrade try-guard (D-12): the optional Nautilus engine import AND run() are wrapped in try/except (ImportError + Exception); any failure records 'Nautilus: not reconciled — {reason}' and the run still exits 0 with the two gating engines reconciled"
    - "Pure reconciliation module: reconcile.py is import-light (only pandas + itrader.reporting.metrics), holds zero engine logic and zero file I/O, returning Markdown strings + flag records — the orchestrator owns all I/O, keeping the reconciliation trivially testable"

key-files:
  created:
    - "scripts/crossval/reconcile.py (310 lines) — the five pure reconciliation functions + HEADLINE_KEYS + tz-normalization + stable float formatting"
    - "scripts/cross_validate.py (292 lines) — the orchestrator: load_itrader_frozen, run_gating_engine, run_nautilus_optional, build_report, main"
    - "tests/golden/CROSS-VALIDATION.md (94 lines) — committed reconciliation evidence"
  modified: []

key-decisions:
  - "iTrader's headline is read DIRECTLY from the frozen tests/golden/summary.json metrics block (NOT recomputed by re-running iTrader) — the frozen oracle is authoritative for iTrader (D-11), and re-running it would risk drift. The engines are the ones recomputed through metrics.py for the apples-to-apples comparison."
  - "Trade-level table is truncated to the first 20 rows PLUS every divergent row (build_trade_table max_rows=20) so the committed Markdown stays readable while still surfacing 100% of divergences. With zero trade-level divergences across all engines, the report shows the first 20 aligned rows + a '114 aligned rows omitted' line."
  - "Float rendering uses fixed %.6f precision (reconcile._fmt) for run-stable committed bytes; no datetime.now() anywhere in the report body, so re-running the orchestrator produces byte-identical output (modulo engine non-determinism, which there is none of here)."
  - "Metric tolerance pinned at 1% (D-04 secondary). At this tolerance all engines PASS final_equity/trade_count/cagr/max_drawdown/profit_factor/sharpe/win_rate (except nautilus win_rate); the three sortino values land ~1.0-1.3% under iTrader and flag DIVERGE — left as 08-08 root-cause stubs (this plan does not root-cause)."

patterns-established:
  - "Cross-engine timestamp alignment: reconcile._norm_ts coerces every trade-date cell (tz-aware UTC from iTrader/nautilus, tz-naive from backtrader/backtesting.py) to a tz-naive UTC Timestamp before equality comparison, so 'SHIFT' detection compares calendar instants, not tz representations."

requirements-completed: [M5-10]

# Metrics
duration: 6min
completed: 2026-06-08
---

# Phase 8 Plan 07: Cross-Validation Orchestrator + Evidence Report Summary

**Built the cross-validation orchestrator `scripts/cross_validate.py` + the pure reconciliation module `scripts/crossval/reconcile.py`, and emitted the committed evidence artifact `tests/golden/CROSS-VALIDATION.md` (M5-10). The orchestrator loads the golden BTCUSD CSV once, precomputes the shared `ta` SMA(50)/SMA(100)/MACD-hist(6,12,3) arrays ONCE and injects the IDENTICAL arrays into every engine (D-03 — indicator divergence is zero by construction), runs the two gating engines (backtesting.py 0.6.5, backtrader 1.9.78.123) force-matched plus the non-gating Nautilus 1.227.0 behind a D-12 try-guard, recomputes EVERY engine's headline metric set through iTrader's own `itrader.reporting.metrics` (D-04 / RESEARCH risk #5 — never an engine-native annualized ratio), reads iTrader's frozen golden side DIRECTLY from `tests/golden/*` (the oracle is authoritative; iTrader is never re-run), then builds the D-02 trade-level-PRIMARY alignment table + the D-04 metric-level-SECONDARY comparison table and flags divergences. Result: ALL THREE engines reconcile 134 trades EXACTLY with byte-identical entry/exit timing on every aligned trade (the primary D-02 gate passes perfectly — zero trade-level divergences), and the only flags are 4 minor metric divergences (sortino ~1.0-1.3% low across all three engines + nautilus win_rate) emitted as empty per-divergence STUBS for 08-08 to root-cause. The report is committed EVIDENCE, NOT the oracle (D-11), and is NOT wired into `make test`/CI (D-10); the orchestrator exits 0 and the 724-test suite still collects clean with no `cross_validate` import under `tests/`.**

## Performance

- **Duration:** ~6 min
- **Started:** 2026-06-08T15:02Z
- **Completed:** 2026-06-08T15:08Z
- **Tasks:** 2 (pure reconciliation module; orchestrator + emit report)
- **Files created:** 3 (`scripts/crossval/reconcile.py`, `scripts/cross_validate.py`, `tests/golden/CROSS-VALIDATION.md`)

## Accomplishments

- **Task 1 — pure reconciliation module (`scripts/crossval/reconcile.py`, 310 lines).** Five pure functions over DataFrames/Series, import-light (only `pandas` + `itrader.reporting.metrics`), zero engine imports, zero file I/O: `recompute_headline(equity, trades)` recomputes the D-04 headline set ({final_equity, trade_count, cagr, max_drawdown, profit_factor, sharpe, sortino, win_rate}) for ONE engine through iTrader's metrics.py (the apples-to-apples boundary); `build_metric_table` renders the D-04 secondary Markdown table with per-cell PASS/DIVERGE flags (relative-abs-diff vs iTrader, divide-by-zero guarded) and returns the flag rows; `align_trades` builds the D-02 primary alignment keyed by trade index (0..N up to the longest engine, so count mismatches surface as blanks) with `_norm_ts` tz-normalizing every date cell before comparison and a SHIFT/MISSING marker per engine; `build_trade_table` renders it (first-N + every divergent row); `flag_divergences` returns `{kind, engine, detail}` records (trade_count / trade_timing / metric) WITHOUT any root-cause analysis (08-08's scope, D-05). Verify: imports clean, all five functions present → `OK`.
- **Task 2 — orchestrator (`scripts/cross_validate.py`, 292 lines) + emit report.** `main()`: (1) `load_golden_csv` once; (2) `compute_indicators(bars['close'])` ONCE (D-03) and inject the same `(bars, indicators)` into every engine's `run()`; (3) `load_itrader_frozen` reads `trades.csv` + `equity.csv` `total_equity` + `summary.json` metrics block DIRECTLY (no re-run); (4) `run_gating_engine` runs backtesting.py + backtrader and recomputes each headline via `reconcile.recompute_headline`; (5) `run_nautilus_optional` wraps the import + run in try/except (ImportError + Exception) for the D-12 degrade — on this interpreter it reconciles, returning the version-stamped status line; (6) `align_trades`/`build_trade_table` + `build_metric_table` + `flag_divergences`; (7) `build_report` assembles the header (D-01 config + pinned engine versions + Nautilus status + the D-10/D-11 evidence-not-oracle disclaimer), the D-02 trade-level table FIRST, the D-04 metric table, and a "Per-Divergence Root-Cause (filled by 08-08)" section with one `###` stub per flagged divergence; (8) prints a one-line summary and exits 0. Verify: `poetry run python scripts/cross_validate.py` exits 0, writes the report, both required headings present → `VERIFY OK`.

## Reconciliation Result (handoff to 08-08)

| Metric | iTrader (frozen) | backtesting.py 0.6.5 | backtrader 1.9.78.123 | nautilus 1.227.0 | Flag |
|---|---|---|---|---|---|
| **trade_count** | 134 | 134 | 134 | 134 | all PASS (D-02 primary) |
| final_equity | 46189.88 | 46027.30 | 46189.88 | 46287.24 | all PASS (<1%) |
| cagr | 0.1991 | 0.1986 | 0.1991 | 0.1994 | all PASS |
| max_drawdown | -0.5383 | -0.5383 | -0.5383 | -0.5383 | all PASS |
| profit_factor | 1.2911 | 1.2897 | 1.2911 | 1.2805 | all PASS |
| sharpe | 0.6584 | 0.6568 | 0.6579 | 0.6580 | all PASS |
| sortino | 1.0385 | 1.0251 | 1.0269 | 1.0254 | **all 3 DIVERGE** (~1.0-1.3% low) |
| win_rate | 0.3657 | 0.3657 | 0.3657 | 0.3582 | nautilus DIVERGE |

**Trade-level (D-02 PRIMARY): every one of the 134 trades aligns EXACTLY (same entry + exit date) across all three engines — zero SHIFT, zero MISSING.** The only flags are 4 secondary metric divergences (3x sortino + 1x nautilus win_rate), stubbed for 08-08's root-cause + disposition.

## Task Commits

1. **Task 1 (reconcile module):** `c607acb` (feat) — `scripts/crossval/reconcile.py`.
2. **Task 2 (orchestrator + report):** `041b0c6` (feat) — `scripts/cross_validate.py` + `tests/golden/CROSS-VALIDATION.md`.
3. **Plan metadata:** final docs commit (this SUMMARY + STATE + ROADMAP + REQUIREMENTS).

## Files Created/Modified

- `scripts/crossval/reconcile.py` (created, 310 lines) — the five pure reconciliation functions; exceeds plan min_lines 60.
- `scripts/cross_validate.py` (created, 292 lines) — the orchestrator; exceeds plan min_lines 80.
- `tests/golden/CROSS-VALIDATION.md` (created, 94 lines) — committed evidence with both tables + the per-divergence stub section.

## Decisions Made

- **iTrader's headline read DIRECTLY from frozen `summary.json`, not recomputed.** The frozen oracle is authoritative for iTrader (D-11); re-running iTrader inside the cross-validation orchestrator would risk drift and violate the read-only contract. Only the ENGINES are recomputed through metrics.py for the apples-to-apples comparison.
- **Trade-table truncation (first 20 + every divergent row).** Keeps the committed Markdown readable; with zero trade-level divergences the table shows 20 aligned rows + a "114 aligned rows omitted" line. Every divergent row would always be force-included regardless of position.
- **Stable float bytes.** Fixed `%.6f` rendering + no wall-clock in the report body → re-running the orchestrator yields byte-identical output, so the committed evidence is a stable diff target for 08-08.
- **1% metric tolerance (D-04 secondary).** Only sortino (all 3 engines, ~1.0-1.3% low) and nautilus win_rate flag DIVERGE; everything else (including all three final_equity values and exact trade counts) passes. Left as 08-08 stubs — this plan does NOT root-cause.

## Deviations from Plan

None — both tasks executed exactly as written. The two gating engines and the (on this interpreter) reconciling Nautilus engine all returned the expected 134-trade logs on the first run, the shared-indicator injection and apples-to-apples recomputation wired cleanly against the 08-05/08-06 contracts, and both verify commands passed first time. The D-12 try-guard is exercised structurally (wraps import + run); on this interpreter the real reconciled path is taken (status line: "Nautilus: reconciled (nautilus-trader 1.227.0)").

## Known Stubs

The per-divergence section in `CROSS-VALIDATION.md` contains 4 INTENTIONAL stubs (Cause / Disposition / Re-freeze fields empty) — these are the plan's explicit deliverable for 08-08 (D-05) to fill with root-cause analysis. They are NOT code stubs: the orchestrator and reconciliation code are fully wired and run end-to-end on real golden + engine data. No placeholder data, no TODO/FIXME in the code.

## Threat Flags

None — no new security-relevant surface. Per the plan's threat register (T-08-01/T-08-02/T-08-SC, all accept/mitigate): this is offline orchestration over the local golden CSV + frozen committed `tests/golden/*` artifacts, read-only consumption with no write-back to the oracle (the report is separate evidence, D-11). No network, no untrusted input, no secrets. The reference engines are imported via the already-vetted 08-05/08-06 wrappers (no new installs here); D-10 script-only isolation holds (`grep cross_validate tests/` empty).

## Verification

- `poetry run python -c "... from scripts.crossval import reconcile; assert all five functions present"` → `OK` (Task 1).
- `poetry run python scripts/cross_validate.py` → exit 0, prints `engines=['backtesting.py', 'backtrader', 'nautilus'] divergences=4 -> tests/golden/CROSS-VALIDATION.md`.
- `test -f tests/golden/CROSS-VALIDATION.md && grep -q "Trade-Level" && grep -q "Per-Divergence Root-Cause"` → `VERIFY OK` (Task 2).
- `grep -rn "cross_validate" tests/` → empty (exit 1): D-10 keep-out-of-tests holds.
- `poetry run pytest tests/ -q --collect-only` → 724 collected, exit 0 (suite unaffected; `filterwarnings=["error"]` contract intact).
- Report content confirmed: D-02 trade-level table FIRST (all 134 trades align exactly, OK on every engine), D-04 metric table with the iTrader frozen column + per-cell PASS/DIVERGE flags, and 4 per-divergence `###` stubs with empty Cause/Disposition/Re-freeze fields.

## Handoff to 08-08

- `tests/golden/CROSS-VALIDATION.md` carries 4 per-divergence stubs to root-cause: **sortino** diverges ~1.0-1.3% low on ALL THREE engines (a consistent cross-engine offset → likely a sortino downside-deviation convention difference, NOT a per-engine bug — investigate iTrader's `sortino` full-period-downside formula vs the engines' equity-return series), and **nautilus win_rate** (0.3582 vs 0.3657 — one fewer winning trade despite identical 134-trade alignment → a borderline-pnl trade flipped sign under nautilus's fill arithmetic).
- The PRIMARY D-02 gate is fully GREEN: 134 trades, exact entry/exit timing across all engines. The secondary metric divergences are small and (for sortino) systematic across engines — 08-08 should decide disposition (accept-within-tolerance with a rationale, or trace + fix + re-freeze) and complete the stub fields, then any re-freeze per D-11.
- Re-running `poetry run python scripts/cross_validate.py` regenerates the report deterministically (stable float bytes, no wall-clock) — 08-08 can re-run after any fix to refresh the evidence.

## Self-Check: PASSED

- Files: `scripts/crossval/reconcile.py` (310 lines), `scripts/cross_validate.py` (292 lines), `tests/golden/CROSS-VALIDATION.md` (94 lines) — all FOUND on disk; line counts exceed plan min_lines (60/80/—).
- Commits: `c607acb` (Task 1), `041b0c6` (Task 2) — verified present in git history.
- Reconciliation: all three engines 134 trades exact (D-02 primary GREEN); 4 secondary metric divergences stubbed for 08-08; report has both tables + the per-divergence stub section; D-10 isolation holds; suite collects 724 clean.

---
*Phase: 08-m5c-cross-validation-final-oracle*
*Completed: 2026-06-08*

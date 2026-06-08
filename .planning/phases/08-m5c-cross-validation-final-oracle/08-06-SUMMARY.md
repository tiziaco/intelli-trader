---
phase: 08-m5c-cross-validation-final-oracle
plan: 06
subsystem: tooling
tags: [cross-validation, reference-engines, nautilus-trader, force-match, ta-indicators, owner-directed-deviation, D-01, D-03, D-10, D-12-superseded, M5-10]

# Dependency graph
requires:
  - phase: 08-m5c-cross-validation-final-oracle
    plan: 04
    provides: "Pinned gating engines + the python-constraint analysis whose D-12 nautilus drop this plan supersedes (owner-directed)"
  - phase: 08-m5c-cross-validation-final-oracle
    plan: 05
    provides: "scripts/crossval/{__init__.py, indicators.py} — shared ta precompute + golden loader + the uniform run(prices, indicators) contract this module mirrors"
provides:
  - "nautilus-trader==1.227.0 installed (dev group, EXACT pin) after narrowing python to >=3.13,<3.14 — supersedes 08-04 D-12 drop (owner-directed Rule-4 deviation)"
  - "scripts/crossval/nautilus_run.py — REAL low-level BacktestEngine force-match: reconciled=True, 134 trades (EXACT match to iTrader frozen golden), final_equity 46287.24 (~0.21% vs golden 46189.88), driven by the injected ta arrays (D-03) with the filter-gates-both quirk verbatim; degrade-safe (never raises) + uniform run() wrapper for 08-07"
affects: [08-07-cross-validate-orchestrator]

# Tech tracking
tech-stack:
  added:
    - "nautilus-trader==1.227.0 (dev) — THIRD cross-validation reference engine (non-gating); Rust-backed; pulled msgspec, pyarrow 24.0.0, portion, click, uvloop, fsspec, sortedcontainers transitively (dev-only, script-path-only)"
  patterns:
    - "Owner-directed Rule-4 deviation: narrow a CORE constraint (python ^3.13 → >=3.13,<3.14) to admit a previously-dropped non-gating dep when the owner explicitly approves and version-solve feasibility is pre-verified (subset relation [3.13,3.14) ⊂ nautilus [3.12,3.15))"
    - "Inject-identical-indicators (D-03) extended to a heavy event-driven engine: a Nautilus Strategy consumes the shared ta SMA/MACD arrays via a bar-open-ts-keyed dict lookup (NOT Nautilus-native indicators) so divergence collapses to order/fill/sizing semantics only"
    - "Multi-currency CASH account (no base_currency) to hold a crypto spot pair: a single-currency CASH account rejects BTC/USD; omitting base_currency lets the account carry both USD (quote) and BTC (bought base)"
    - "Next-bar-open fills in Nautilus: ts_init_delta=86_400_000_000_000 shifts the bar's executable timestamp to its CLOSE so bar_execution fills market orders at the NEXT bar's open (mirrors D-01)"

key-files:
  created:
    - ".planning/phases/08-m5c-cross-validation-final-oracle/08-06-SUMMARY.md — this summary"
  modified:
    - "pyproject.toml — python = \"^3.13\" → \">=3.13,<3.14\"; nautilus-trader = \"1.227.0\" added to dev group"
    - "poetry.lock — resolved + locked nautilus-trader 1.227.0 + additive transitives"
    - "scripts/crossval/nautilus_run.py — staged degrade-only scaffold replaced with the REAL BacktestEngine force-match (reconciled result); degrade safety net + uniform run() wrapper retained"

key-decisions:
  - "OWNER-DIRECTED DEVIATION (Rule 4, supersedes 08-04 D-12): instead of accepting the clean-degrade outcome for the non-gating Nautilus reference, the owner directed installing nautilus-trader==1.227.0 by narrowing the repo python constraint from ^3.13 (→ >=3.13,<4.0, no <3.15 ceiling) to >=3.13,<3.14. [3.13,3.14) is a subset of nautilus's requires_python [3.12,3.15), so the 08-04 version-solve rejection disappears; the cp313 macOS-arm64 wheel installs cleanly; transitive pins (numpy/pandas/tqdm) stay compatible."
  - "Multi-currency CASH account (omit base_currency). A single-currency CASH account with base_currency=USD rejects a BTC/USD spot CurrencyPair ('Cannot add ... for a venue with a single-currency CASH account'). Omitting base_currency yields a multi-currency account that holds USD free + BTC position — the correct config for spot crypto."
  - "Zero fees via a zero-fee instrument, not FixedFeeModel. FixedFeeModel(Money(0,USD)) is rejected (commission must be positive); the default fee model reads the instrument's maker_fee/taker_fee, so a CurrencyPair with maker_fee=taker_fee=Decimal('0') gives zero commission cleanly (D-01)."
  - "Per-bar equity computed as free USD + open_qty*close (mark-to-market) rather than reading the multi-currency account's USD-converted total, which is config-nuanced; the strategy already tracks open_qty from position events, so this is robust and matches the gating engines' equity convention."

patterns-established:
  - "When the owner approves narrowing a core constraint to admit a dropped dependency, verify the subset relation between the project's resolved python range and the dep's requires_python BEFORE editing, and record the supersession explicitly in the commit + SUMMARY so the prior drop decision (08-04 D-12) is traceable."

requirements-completed: [M5-10]

# Metrics
duration: 7min
completed: 2026-06-08
---

# Phase 8 Plan 06: Nautilus Reference Module (Real Force-Match, Owner-Directed) Summary

**Completed the THIRD cross-validation reference engine with a REAL reconciled result, per an explicit owner-directed Rule-4 deviation that SUPERSEDES 08-04's D-12 drop of nautilus-trader. Narrowed the repo python constraint from `^3.13` (which resolved to `>=3.13,<4.0`, missing the `<3.15` ceiling nautilus requires) to `>=3.13,<3.14` — now a subset of nautilus's `requires_python` `[3.12,3.15)` — and installed `nautilus-trader==1.227.0` (EXACT pin, dev group, script-path-only). Replaced the prior degrade-only scaffold (commit 7a92dd3) with a real low-level `BacktestEngine` force-match: a custom zero-fee BTCUSD `CurrencyPair`, a multi-currency CASH account, `BookType.L1_MBP` bar execution with `ts_init` shifted to the bar close for next-bar-open fills (D-01), and a Nautilus `Strategy` that consumes the SHARED `ta` SMA(50)/SMA(100)/MACD-hist(6,12,3) arrays (D-03, injected via a bar-open-ts-keyed lookup, NOT Nautilus-native indicators) replicating the SMA_MACD filter-gates-both-entry-AND-exit quirk verbatim with 95%-of-equity fractional sizing, long-only, single-position-from-flat. Result: `reconciled=True`, **134 trades — EXACT match to iTrader's frozen golden count** — final_equity **46287.24** vs golden **46189.88** (~0.21% divergence, well within ballpark for a non-gating reference and now CONFIRMING the two gating engines on a true event-driven architecture). The D-12 degrade safety net is fully retained (any import/config/runtime failure still degrades to "Nautilus: not reconciled — {reason}", never raises; the `run()` wrapper raises `RuntimeError` on degrade for 08-07's uniform try-guard). D-10 isolation holds: no nautilus import under `tests/` or `itrader/`; the 724-test suite still collects clean and the golden-oracle integration test stays GREEN after the re-lock.**

## Performance

- **Duration:** ~7 min
- **Started:** 2026-06-08T14:42Z
- **Completed:** 2026-06-08T14:49Z
- **Tasks:** STEP A (install) + STEP B (real force-match) + STEP C (docs)
- **Files modified:** 3 (pyproject.toml, poetry.lock, scripts/crossval/nautilus_run.py)

## Accomplishments

- **STEP A — narrowed python + installed nautilus-trader (owner-directed, supersedes D-12).** `pyproject.toml`: `python = "^3.13"` → `">=3.13,<3.14"` and `nautilus-trader = "1.227.0"` appended to `[tool.poetry.group.dev.dependencies]` (EXACT pin, D-10 style, dev-only). `poetry lock` resolved clean (exit 0) — `[3.13,3.14)` is a subset of nautilus's `requires_python [3.12,3.15)`, so the 08-04 version-solve failure is gone. `poetry install --with dev` installed nautilus-trader 1.227.0 + 7 additive transitives (sortedcontainers, fsspec, click, msgspec, portion, pyarrow 24.0.0, uvloop). Verify: `import nautilus_trader; print(nautilus_trader.__version__)` → `1.227.0`, exit 0.
- **STEP B — completed the REAL BacktestEngine force-match.** Replaced the staged degrade-only body with: `_build_zero_fee_btcusd()` (custom `CurrencyPair`, USD quote, `maker_fee=taker_fee=Decimal("0")`, `size_precision=6` for fractional BTC, `min_notional=None`); `_make_strategy_class()` (a `Strategy` subclass that, in `on_bar`, looks up the INJECTED ta arrays by bar-open ts, replicates the filter-gates-both quirk verbatim, sizes 95% of free USD / price, long-only, single-position; captures per-trade entry/exit/pnl from `on_position_closed` and per-bar equity = free USD + position MTM). The engine uses a multi-currency CASH account (no `base_currency`, so it accepts the BTC/USD spot pair), `BookType.L1_MBP` bar execution, and `BarDataWrangler.process(..., ts_init_delta=86_400_000_000_000)` so the bar is executable at its close and fills at the next bar's open (D-01). Result extracted into `CrossvalResult(reconciled=True, ...)`. Verify: `poetry run python scripts/crossval/nautilus_run.py` → `nautilus: reconciled | trades: 134 | final_equity: 46287.24`, exit 0.
- **Re-lock safety confirmed.** After the install AND after the force-match: `poetry run pytest tests/ -q --collect-only` → 724 collected clean (exit 0); `poetry run pytest tests/integration/test_backtest_oracle.py` → 2 passed (golden oracle GREEN). The re-lock did not shift any shared dep in a way that breaks the suite or the oracle.
- **D-10 isolation preserved.** `grep -rn "import nautilus\|from nautilus\|nautilus_run" tests/ itrader/` → empty (exit 1). The only `tests/` match for "nautilus" is a doc mention in `tests/golden/REFREEZE-M5C-DECIMAL.md` (markdown, not a code import). The engine is dev-group + script-path only; the `filterwarnings=["error"]` test contract stays intact.

## Force-Match Results (handoff to 08-07)

| Engine | Trades | Final equity | vs iTrader golden (46189.87730727451) | Gating? |
|---|---|---|---|---|
| iTrader (frozen golden) | 134 | 46189.87730727451 | — | oracle |
| backtrader 1.9.78.123 | 134 | 46189.877307274444 | match to ~10 decimals | gating |
| backtesting.py 0.6.5 | 134 | 46027.30313542994 | ~0.35% | gating |
| **nautilus-trader 1.227.0** | **134** | **46287.24** | **~0.21%** | **non-gating (confirming)** |

All three references hit the **primary D-02 gate** (134 trades, exact). Nautilus — the closest architectural mirror to iTrader (event-driven, real order/fill lifecycle) — independently confirms the trade count and lands within ~0.21% of the frozen final equity on a genuinely different matching engine, the strongest possible cross-validation evidence short of bit-equality.

## Task Commits

1. **STEP A (install):** `eb38367` (chore) — `pyproject.toml` (python narrowed + nautilus added) + `poetry.lock`.
2. **STEP B (real force-match):** `c43dd5f` (feat) — `scripts/crossval/nautilus_run.py`.
3. **STEP C (plan metadata):** final docs commit (this SUMMARY + STATE + ROADMAP + REQUIREMENTS).

## Files Created/Modified

- `pyproject.toml` (modified) — `python = ">=3.13,<3.14"`; `nautilus-trader = "1.227.0"` in dev group.
- `poetry.lock` (modified) — nautilus-trader 1.227.0 + transitives locked.
- `scripts/crossval/nautilus_run.py` (modified, 469 lines) — real BacktestEngine force-match (reconciled) + degrade safety net + uniform `run()` wrapper.
- `.planning/phases/08-m5c-cross-validation-final-oracle/08-06-SUMMARY.md` (created) — this summary.

## Deviations from Plan

### Owner-Directed Architectural Deviation (Rule 4)

**1. [Rule 4 - Architectural, OWNER-APPROVED] Install nautilus-trader by narrowing the python constraint — supersedes 08-04 D-12**
- **Context:** The 08-06 plan and 08-04 D-12 specified DROPPING nautilus-trader and accepting a clean degrade, because its `requires_python <3.15,>=3.12` conflicted with the repo's `python = "^3.13"` (resolving to `>=3.13,<4.0`). The Task 2 checkpoint (`gate="blocking-human"`) was reached with the degrade-safe scaffold (commit 7a92dd3).
- **Owner decision:** Instead of accepting the degrade, the project owner DIRECTED installing nautilus-trader and completing the REAL force-match, after the orchestrator pre-verified feasibility (subset relation, published cp313 macOS-arm64 wheel, compatible transitive pins).
- **Change:** Narrowed `python` to `>=3.13,<3.14` (so `[3.13,3.14) ⊂ [3.12,3.15)`), added `nautilus-trader = "1.227.0"` to the dev group, and replaced the staged degrade-only body with a real reconciled BacktestEngine force-match.
- **Impact:** A third confirming reference now reconciles a real result (134 trades, ~0.21% equity divergence). The repo's python floor/ceiling is now `>=3.13,<3.14` (was effectively `>=3.13,<4.0`); the project already pins 3.13 via `.python-version`, so no supported interpreter is lost. The D-12 non-gating safety net is retained verbatim.
- **Files modified:** pyproject.toml, poetry.lock, scripts/crossval/nautilus_run.py
- **Commits:** `eb38367` (STEP A), `c43dd5f` (STEP B)

### Auto-fixed Issues

**2. [Rule 1 - Bug] Single-currency CASH account rejected the BTC/USD spot pair**
- **Found during:** STEP B (first standalone run degraded with "Cannot add CurrencyPair ... for a venue with a single-currency CASH account").
- **Issue:** `add_venue(..., base_currency=USD)` creates a single-currency CASH account that cannot hold a BTC/USD spot instrument.
- **Fix:** Omit `base_currency` → multi-currency CASH account holding USD (quote) + BTC (bought base). Reconciled on re-run.
- **Files modified:** scripts/crossval/nautilus_run.py
- **Commit:** `c43dd5f` (fixed before STEP B was committed — never shipped broken)

## Known Stubs

None — the module runs end-to-end on the real golden data, returning a non-empty 134-trade log and a 3076-point equity curve. The degrade path is a genuine D-12 safety net, not a stub: on this interpreter the real reconciled path is taken.

## Threat Flags

None new beyond the plan's registered surface. T-08-SC (supply-chain, nautilus-trader Rust-backed dev dep): mitigated as planned — EXACT-pinned in the dev group only, never imported under `tests/` or `itrader/`, guarded import inside the function body (a compromised/absent package degrades rather than executing at module scope). T-08-DoS (run_nautilus stalling the freeze): the top-level try-guard is retained verbatim, so the owner-directed install does not weaken the non-gating guarantee — any future failure on a different interpreter still degrades cleanly. Nautilus output remains evidence-only and never reaches the frozen oracle (D-11).

## Verification

- `poetry run python -c "import nautilus_trader; print(nautilus_trader.__version__)"` → `1.227.0`, exit 0.
- `poetry run python scripts/crossval/nautilus_run.py` → `nautilus: reconciled | trades: 134 | final_equity: 46287.24`, exit 0 (no traceback, no hang).
- `run_nautilus(None)` → `reconciled=True`, 134 trades, 3076 equity points, normalized columns `[entry_date, exit_date, side, realised_pnl]`.
- `run()` uniform wrapper → `(trade_log_df, equity_series)`, 134 trades, final_equity 46287.24.
- `poetry run pytest tests/ -q --collect-only` → 724 collected, exit 0 (suite unaffected by the re-lock).
- `poetry run pytest tests/integration/test_backtest_oracle.py` → 2 passed (golden oracle GREEN after re-lock).
- `grep -rn "import nautilus\|from nautilus\|nautilus_run" tests/ itrader/` → empty (exit 1): D-10 script-only isolation holds (no code import; only a markdown doc mention).

## Handoff to 08-07

- Import `run` from `scripts.crossval.nautilus_run` exactly like the gating engines: `run(prices=..., indicators=...) -> (trade_log_df, equity_series)`. On this interpreter it returns the real reconciled result (134 trades, equity 46287.24); on any future interpreter where nautilus is absent/broken it raises `RuntimeError("Nautilus: not reconciled — {reason}")`, which 08-07's uniform per-engine try-guard records as the non-gating "not reconciled" status (D-12).
- Pass the SAME precomputed `ta` arrays (`scripts.crossval.indicators.compute_indicators` / `load_golden_with_indicators`) to all three engines so divergence is order/fill/sizing only (D-03). The returned `trade_log_df` is already in the `[entry_date, exit_date, side, realised_pnl]` reconcile shape; `entry_date`/`exit_date` are tz-aware UTC.
- All three engines hit 134 trades exactly. backtrader equity is essentially exact; backtesting.py within ~0.35%; nautilus within ~0.21%. Recompute headline metrics via `itrader.reporting.metrics` on identical formulas — do NOT trust engine-native ratios.

## Self-Check: PASSED

- Files: `scripts/crossval/nautilus_run.py` (469 lines > plan min_lines 80), `pyproject.toml`, `poetry.lock`, `.planning/phases/08-m5c-cross-validation-final-oracle/08-06-SUMMARY.md` — all FOUND on disk.
- Commits: `eb38367` (STEP A), `c43dd5f` (STEP B) — verified present in git history.
- Force-match: reconciled=True, 134 trades (exact golden match), final_equity 46287.24 (~0.21% vs golden); suite collects 724 clean; golden oracle 2 passed; D-10 isolation holds (no code import).

---
*Phase: 08-m5c-cross-validation-final-oracle*
*Completed: 2026-06-08*

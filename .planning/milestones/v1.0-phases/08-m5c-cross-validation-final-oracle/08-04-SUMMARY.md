---
phase: 08-m5c-cross-validation-final-oracle
plan: 04
subsystem: tooling
tags: [cross-validation, dev-dependencies, reference-engines, backtesting, backtrader, poetry, D-10, D-12, M5-10]

# Dependency graph
requires:
  - phase: 08-m5c-cross-validation-final-oracle
    plan: 03
    provides: "Settled, owner-blessed golden oracle (tests/golden/{trades.csv,equity.csv,summary.json} + REFREEZE-M5C-DECIMAL.md) — the locked cross-validation baseline (D-07 gate satisfied)"
provides:
  - "backtesting==0.6.5 + backtrader==1.9.78.123 pinned EXACTLY in [tool.poetry.group.dev.dependencies] and recorded in poetry.lock (D-10 reproducibility)"
  - "Smoke-verified: both engines import AND backtrader runs a trivial Cerebro backtest end-to-end on Python 3.13.1 / numpy 2.2.6 — the numpy-2.x alias landmine is empirically cleared, NO fork/shim needed"
  - "Engines confined to the dev group, absent from [tool.poetry.dependencies], and never imported under tests/ or itrader/ (filterwarnings=['error'] suite contract safe)"
  - "The known-working reference-engine versions 08-05 builds its force-match harness against: backtesting 0.6.5, backtrader 1.9.78.123 (plain, no fork)"
affects: [08-05-force-match-harness, 08-06-shared-ta-precompute, 08-07-cross-validate-script]

# Tech tracking
tech-stack:
  added:
    - "backtesting==0.6.5 (dev) — gating cross-validation reference engine; pulled bokeh 3.9.1 + contourpy + pillow + xyzservices transitively (dev-only, plotting lazy at import)"
    - "backtrader==1.9.78.123 (dev) — gating cross-validation reference engine; pure-Python (array.array line buffers, no numpy alias dependency)"
  patterns:
    - "Reference engines pinned EXACT (==) in the dev group only (D-10) — never main deps, never the runtime/result-bearing path; script-only isolation keeps the warnings-as-errors test contract intact"
    - "Install + validate (import + trivial run smoke gate) BEFORE any module depends on the engines — de-risks the entire 08-05→08-09 cross-validation wave; a broken import surfaces here, not mid-harness"

key-files:
  created: []
  modified:
    - "pyproject.toml — appended backtesting=0.6.5 + backtrader=1.9.78.123 to [tool.poetry.group.dev.dependencies] after mypy; existing entries untouched"
    - "poetry.lock — resolved + locked exact versions for backtesting, backtrader, and their transitive deps (bokeh, contourpy, pillow, xyzservices)"

key-decisions:
  - "backtrader compatibility CONFIRMED on this exact stack (Python 3.13.1 / numpy 2.2.6 / pandas 2.3.3): plain backtrader==1.9.78.123 imports AND runs a full Cerebro backtest cleanly. Research headline #1 held — backtrader uses array.array (not numpy) for line buffers, so numpy-2 alias removals never bite. NO fork/shim/alternate-pin fallback was needed or applied."
  - "nautilus-trader (optional, D-12 non-gating) NOT added: 1.227.0 requires Python <3.15,>=3.12, but this repo's python=^3.13 resolves to >=3.13,<4.0 (no <3.15 upper bound), so poetry version-solving fails. Per D-12 it is non-gating — left out cleanly rather than narrowing the repo's python constraint just to satisfy a non-gating reference. The two gating engines (backtesting + backtrader) fully cover the D-04 cross-validation."

patterns-established:
  - "When an optional non-gating dependency fails to resolve due to a constraint conflict, drop it with a recorded reason rather than mutating the project's core constraints (e.g. python upper bound) to force it in."

requirements-completed: [M5-10]

# Metrics
duration: 2min
completed: 2026-06-08
---

# Phase 8 Plan 04: Cross-Validation Reference-Engine Freeze Summary

**Pinned the two gating cross-validation reference engines — `backtesting==0.6.5` and `backtrader==1.9.78.123` — EXACTLY in the poetry dev group (D-10), locked `poetry.lock`, and smoke-gated them on this exact interpreter: both import and a trivial `backtrader.Cerebro` backtest runs end-to-end clean on Python 3.13.1 / numpy 2.2.6 (the numpy-2.x alias landmine is empirically cleared, NO fork/shim needed). Engines are dev-group-only, absent from main deps, and unimported by the test path — the 724-test suite still collects clean. `nautilus-trader` (D-12 non-gating) was dropped: its `<3.15` python cap conflicts with the repo's `^3.13` (`<4.0`) resolution. The known-working engine versions are now frozen for 08-05 to build the force-match harness against.**

## Performance

- **Duration:** ~2 min
- **Started:** 2026-06-08T14:23Z
- **Completed:** 2026-06-08T14:25Z
- **Tasks:** 2 (Task 1 pin + lock; Task 2 import/run smoke gate — validation only)
- **Files modified:** 2 (pyproject.toml, poetry.lock)

## Accomplishments

- **Task 1 — pinned + locked the reference engines.** `poetry add --group dev "backtesting==0.6.5"` and `poetry add --group dev "backtrader==1.9.78.123"` appended both EXACTLY (no `^`/`~`/`>=`) after the `mypy` line in `[tool.poetry.group.dev.dependencies]`; existing dev entries untouched; neither leaked into `[tool.poetry.dependencies]`. `poetry.lock` updated by `poetry add` with resolved entries for both engines + transitives (bokeh 3.9.1, contourpy 1.3.3, pillow 12.2.0, xyzservices 2026.3.0). Task 1 automated check (`tomllib` parse — dev-group membership, exact-pin regex, main-group absence) printed `OK: exact-pinned, dev-group-only`.
- **Task 2 — import + run smoke gate PASSED (no fallback).** Ran the combined gate: `import backtesting, backtrader` + a trivial `bt.Cerebro` run over a 5-bar synthetic OHLCV frame with `broker.setcash(10000)` + `cerebro.run()`. Output: `SMOKE OK 0.6.5 1.9.78.123`, exit 0. The Cerebro run exercises backtrader's numpy code paths (where `np.bool`/`np.float`/`np.int` removals would bite) — it completed without raising, **empirically confirming research headline #1**. backtrader's plain PyPI release works on numpy 2.2.6; no fork (`backtrader2`/`backtrader_next`), no compat shim, no alternate pin was needed.
- **Isolation verified (filterwarnings=['error'] contract safe).** `grep` for any engine import under `tests/` or `itrader/` returns nothing (exit 1) — the engines are script-only per D-10, so they never load at pytest collection time. `poetry run pytest tests/ -q --collect-only` succeeds: **724 tests collected, exit 0** (the plan's ~716 baseline plus tests added across 08-01→08-03). The new deps are installed but unimported, so the suite is unaffected.
- **nautilus-trader gracefully dropped (D-12 non-gating).** `poetry add --group dev "nautilus-trader==1.227.0"` failed version-solving: nautilus requires `Python <3.15,>=3.12` but the repo's `python = "^3.13"` resolves to `>=3.13,<4.0` (no `<3.15` ceiling). Per D-12 it is non-gating, so it was left out (pyproject.toml + poetry.lock confirmed nautilus-free) rather than narrowing the repo's python constraint to force it. The two gating engines fully cover the D-04 cross-validation.

## Final Engine Versions (for 08-05)

| Engine | Status | Version | Notes |
|---|---|---|---|
| backtesting (backtesting.py) | added, gating | `0.6.5` | imports clean; plotting (bokeh) lazy at import, not triggered |
| backtrader | added, gating | `1.9.78.123` | **plain PyPI release, NO fork/shim** — imports + runs Cerebro clean on numpy 2.2.6 |
| nautilus-trader | NOT added, non-gating | — | dropped: `<3.15` python cap conflicts with repo `^3.13` (`<4.0`) resolution (D-12) |

**Interpreter/stack validated against:** Python 3.13.1 (CPython), numpy 2.2.6, pandas 2.3.3.

## Task Commits

1. **Task 1 (pin + lock):** `d366692` (chore) — `pyproject.toml` (backtesting + backtrader appended to dev group, exact-pinned) + `poetry.lock` (resolved exact versions).
2. **Task 2 (smoke gate):** no commit — validation only; no file changes beyond Task 1 (the gate proves the already-committed pins import + run; results recorded in this SUMMARY).
3. **Plan metadata:** final docs commit (this SUMMARY + STATE + ROADMAP + REQUIREMENTS).

## Files Created/Modified

- `pyproject.toml` (modified) — appended `backtesting = "0.6.5"` + `backtrader = "1.9.78.123"` to `[tool.poetry.group.dev.dependencies]` after the `mypy` line; existing entries and ordering preserved; engines absent from `[tool.poetry.dependencies]`.
- `poetry.lock` (modified) — recorded resolved exact versions for `backtesting`, `backtrader`, and their transitive deps (bokeh 3.9.1, contourpy 1.3.3, pillow 12.2.0, xyzservices 2026.3.0) for reproducibility.

## Decisions Made

- **backtrader runs clean on numpy 2.2.6 — research headline #1 empirically confirmed.** The trivial Cerebro run (the place numpy-2 alias removals actually bite) completed without raising. backtrader's `array.array` line buffers sidestep `np.bool`/`np.float`/`np.int`. The fork/shim fallback was retained in the plan only as a contingency and was NOT exercised. 08-05 builds against plain `backtrader==1.9.78.123`.
- **nautilus-trader dropped, not forced in (D-12).** Forcing it would require narrowing the repo's `python` constraint to `>=3.13,<3.15` — an unjustified change to a core constraint for a non-gating reference. The gating engines suffice.

## Deviations from Plan

None — plan executed as written. The anticipated path (backtrader plain works, no fork) held; nautilus's documented "drop if it fails to resolve" branch was taken per D-12. The collect-only count is 724 vs the plan's ~716 estimate — this is the expected current baseline (tests added by 08-01→08-03), not a regression; collection succeeds clean with no warnings-as-errors failure.

## Known Stubs

None — this plan adds no code, only pinned dev dependencies. Per scope guard it builds NO force-match modules, NO shared `ta` precompute, NO `scripts/cross_validate.py` (those are 08-05/08-06/08-07).

## Verification

- `poetry run python -c "import backtesting, backtrader; ... c=bt.Cerebro(); c.run()"` → `SMOKE OK 0.6.5 1.9.78.123`, exit 0 (import + trivial run gate).
- Task 1 `tomllib` check → `OK: exact-pinned, dev-group-only` (dev-group membership, exact pin, main-group absence).
- `grep -rn "import backtesting|import backtrader|import nautilus_trader|from ..." tests/ itrader/` → empty (exit 1): script-only isolation holds.
- `poetry run pytest tests/ -q --collect-only` → 724 tests collected, exit 0 (suite unaffected by the new deps).
- `grep nautilus pyproject.toml` → not found (nautilus cleanly absent after failed resolution).

## Handoff to 08-05+

- Build the force-match harness against the frozen, smoke-verified engines: **backtesting 0.6.5** (`backtesting.lib.FractionalBacktest`) and **backtrader 1.9.78.123** (plain `import backtrader`, NO fork — `import backtrader` is the correct module name).
- Engines are **script-only**: the future `scripts/cross_validate.py` / `scripts/crossval/*` path lives OUTSIDE pytest. Do NOT import any engine under `tests/` or in `itrader/` — `filterwarnings=["error"]` would fail the suite (backtrader emits harmless `SyntaxWarning` docstring escapes at import that are fine in a script but would error under pytest).
- nautilus-trader is unavailable on this interpreter; cross-validation proceeds with the two gating engines (D-04 metric set reconciliation against the 08-03 golden: final_equity 46189.87730727451, trade_count 134, cagr 0.19910032815485068, max_drawdown -0.538256823181407, profit_factor 1.291149869385797, sharpe 0.6583614133806527, sortino 1.038504038796619, win_rate 0.3656716417910448).

## Self-Check: PASSED

- Files: `pyproject.toml` (backtesting + backtrader in dev group), `poetry.lock` (engines + transitives recorded), `.planning/phases/08-m5c-cross-validation-final-oracle/08-04-SUMMARY.md` — all FOUND on disk.
- Commit: `d366692` (Task 1 pin + lock) — verified present in git history.
- Smoke gate: `SMOKE OK 0.6.5 1.9.78.123` exit 0; suite collects 724 clean; no engine imports under tests/ or itrader/.
- Scope guard: no harness/script/precompute code created (deferred to 08-05/08-06/08-07); engines dev-group-only and absent from main deps.

---
*Phase: 08-m5c-cross-validation-final-oracle*
*Completed: 2026-06-08*

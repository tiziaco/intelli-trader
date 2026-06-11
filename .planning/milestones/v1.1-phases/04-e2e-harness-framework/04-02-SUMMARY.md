---
phase: 04-e2e-harness-framework
plan: 02
subsystem: testing
tags: [e2e, harness, fixture, marker, golden-master, freeze, D-02, D-05, D-08, D-13, D-15]
requires:
  - itrader.reporting.summary (attach_slippage, build_metrics_block, build_summary, FLOAT_FORMAT, SLIPPAGE_COLUMNS)
  - itrader.reporting.frames (build_trade_log, build_equity_curve, TRADE_COLUMNS, EQUITY_COLUMNS)
  - itrader.trading_system.backtest_trading_system.TradingSystem (csv_paths passthrough, run(print_summary=False))
provides:
  - "tests/e2e/conftest.py::run_scenario (the shared build->run->read-after->assemble->diff-what's-frozen harness fixture)"
  - "tests/e2e/conftest.py::pytest_addoption --freeze (deliberate golden-regen flag, OFF by default)"
  - "e2e pytest marker (registered in pyproject.toml, folder-derived auto-applied)"
  - "make test-e2e (-m e2e focused bucket)"
affects:
  - pyproject.toml (markers list — single registration home)
  - tests/conftest.py (folder-derived auto-marking hook)
  - Makefile (test-e2e target + .PHONY)
  - "future: Plan 03 canary + Phase 6-9 scenario leaves consume run_scenario by adding ONLY a leaf folder"
tech-stack:
  added: []
  patterns:
    - "Deferred-construction factory fixture (returns a callable; TradingSystem import inside the inner function so --collect-only stays clean)"
    - "In-process per-leaf scenario module load with a unique module name (avoids scenario.py shadowing — Pitfall 4)"
    - "Exact no-tolerance assert_frame_equal diff (identity + auto-derived-numeric split) reused VERBATIM from the oracle (D-08)"
    - "Diff-what's-frozen: presence of a golden file IS the assertion (D-05); one diff loop, no central registry"
key-files:
  created:
    - tests/e2e/conftest.py
    - tests/e2e/__init__.py
  modified:
    - pyproject.toml
    - tests/conftest.py
    - Makefile
decisions:
  - "D-15: e2e is its OWN marker (NOT slow) — tiny full-engine runs stay in the default make test; make test-e2e is the focused -m e2e bucket"
  - "D-13: --freeze is the deliberate OFF-by-default regen flag (chosen over an env var); default runs DIFF and fail on drift, goldens never auto-heal"
  - "D-05: run_scenario diffs ONLY the golden files PRESENT in the leaf's golden/ (presence = assertion); one diff loop, parallel-safe by construction"
  - "D-08: exact diff with NO float tolerance, reusing the oracle's assert_frame_equal(check_exact=True, check_like=True) identity-vs-numeric mechanic"
  - "D-06: default freeze = trades.csv + summary.json; equity.csv is opt-in (only refreshed if the leaf already committed one)"
  - "D-02/D-03: each leaf supplies a per-folder ScenarioSpec (published as module-level SCENARIO) that reuses the REAL engine config objects — no parallel/reinvented schema"
  - "OPEN Q1: the spec.exchange fee/slippage seam (execution_handler.exchanges['simulated'].update_config) is applied post-construction pre-run; canary's spec.exchange is None (no-op), real threading is Phase 7"
metrics:
  duration: ~12 min
  completed: 2026-06-09
  tasks: 2
  files: 5
---

# Phase 04 Plan 02: Shared E2E Harness Framework (e2e marker + run_scenario + --freeze) Summary

Stood up the SHARED end-to-end harness every scenario phase (6-9) and the Plan 03 canary consume: registered the `e2e` marker (folder-derived auto-marked, `make test-e2e` bucket, `make test` unchanged), and built the `run_scenario` fixture with the `--freeze` regen option in `tests/e2e/conftest.py` — it wires a real `TradingSystem` from a leaf's `ScenarioSpec`, runs it, reads portfolio state AFTER the run (queue-only), assembles artifacts via the shared `itrader.reporting.summary` (Plan 01), and diffs-what's-frozen with the oracle's exact no-tolerance mechanic.

## What Was Built

### Task 1 — e2e marker registration, auto-marking, make test-e2e (commit d5912ac)
- **`pyproject.toml`:** added one line to the `markers` list — `"e2e: End-to-end scenario — full engine on a (strategy, data) pair vs frozen goldens (tests/e2e/)"`. This is the SINGLE registration home under `--strict-markers`; `filterwarnings=["error", ...]` untouched.
- **`tests/conftest.py`:** added a folder-derived auto-marking branch in `pytest_collection_modifyitems` — `if "e2e" in parts: item.add_marker(pytest.mark.e2e)`, mirroring the existing unit/integration branches but deliberately NOT adding `slow` (D-15: ~10-bar runs stay in the default suite). Extended the module docstring's TYPE-axis section to document the `e2e` mapping.
- **`Makefile`:** added a `test-e2e` target (`poetry run pytest tests/ -v -m "e2e"`, tab-indented recipe) and added `test-e2e` to `.PHONY`. `make test` is unchanged (no `-m` filter, still runs everything including e2e).

### Task 2 — run_scenario harness + --freeze (commit 006b7a0)
- **`tests/e2e/__init__.py`:** empty package marker.
- **`tests/e2e/conftest.py`** (4-space indent, matching `tests/conftest.py`):
  - `pytest_addoption(parser)` registers `--freeze` (`action="store_true"`, default `False`) — the deliberate OFF-by-default golden-regen flag (D-13).
  - `_load_spec(scenario_path)` imports a leaf's `scenario.py` in-process with a UNIQUE module name (`e2e_scenario_<leaf-folder>`) so two leaves' `scenario.py` never shadow each other (Pitfall 4); returns the module-level `SCENARIO` ScenarioSpec.
  - `_build_and_run(spec)` DEFER-imports `TradingSystem` inside the function body (keeps `--collect-only` clean), wires `TradingSystem(exchange="csv", start_date=spec.start, end_date=spec.end, timeframe=spec.timeframe, csv_paths=spec.data)`, applies the OPEN Q1 `spec.exchange` seam if non-None (canary: no-op), loops `add_strategy`/`add_portfolio`+`subscribe_portfolio`, runs `print_summary=False`, and reads `get_portfolio(...)` AFTER the run (queue-only — D-07).
  - `_assemble(spec, system, portfolio)` uses the SHARED path: `build_trade_log` / `build_equity_curve`, `attach_slippage(trades, system.store.read_bars(spec.ticker)["close"])`, `build_summary(..., keyword pins)`, `summary["metrics"] = build_metrics_block(...)`.
  - `_diff_frame` / `_diff_summary` reuse the oracle's exact mechanic VERBATIM: sort, identity-column EXACT, auto-derived-numeric remainder EXACT, `assert_frame_equal(check_exact=True, check_like=True)` — NO float tolerance; summary compares the whole `metrics` dict EXACT plus key-by-key scalars.
  - `_freeze` WRITES goldens with the oracle's serialization (`to_csv(..., float_format=FLOAT_FORMAT)`, `json.dump(..., indent=2, sort_keys=True)`) — trades.csv + summary.json always, equity.csv opt-in (D-06).
  - `_diff` diffs ONLY the golden files PRESENT in `here/"golden"/` (D-05).
  - `run_scenario` fixture returns `_run(here)` gated on `request.config.getoption("--freeze")`.
  - Module docstring documents the `--freeze` deliberate-per-scenario discipline (Pitfall 5) and the OPEN Q1 ExchangeConfig seam.

## How It Was Verified

- **Marker resolves under --strict-markers:** `poetry run pytest tests/ -m e2e --collect-only -q` exits 0 (734 deselected, 0 selected — zero scenarios yet, no "unknown marker" error).
- **--freeze registered:** `poetry run pytest tests/e2e --help | grep -- --freeze` shows the option.
- **Collect-clean with zero scenarios:** `poetry run pytest tests/e2e --collect-only -q` exits 0 (deferred TradingSystem import).
- **Fixture surface:** in-process import of `tests/e2e/conftest.py` confirms `run_scenario` + `pytest_addoption` are exposed.
- **Acceptance greps:** shared-assembly import, `print_summary=False`, `get_portfolio`, `check_exact=True`, `getoption` all present; `grep -c 'rtol\|atol'` returns 0 (no float tolerance).
- **`make test` unaffected:** `make test` still has no `-m` filter; full suite **734 passed, 0 failures** with the e2e tree present (collect-clean, no failing collection).
- **Makefile recipe indentation:** the `test-e2e` recipe is tab-indented (verified with `grep -nP '^\t'`).

## Deviations from Plan

None — both tasks executed as written.

### Environment notes (not code deviations)
- Per Plan 01 SUMMARY's documented worktree/shared-venv artifact: symlinked the main repo's gitignored `.env` into the worktree and ran pytest with `PYTHONPATH=<worktree-root>` so worktree code precedes the shared `.venv` editable-install `.pth` entry. This is environment-only — no source change, the symlink is gitignored and not committed.

## Authentication Gates
None.

## Known Stubs
None. The harness is fully wired; there is intentionally no scenario yet — Plan 03 supplies the canary (`scenario.py` + `golden/`). This is the documented plan boundary (the framework lands and is committed BEFORE the canary, per the ROADMAP Phase 6 REMINDER), not a stub.

## Threat Flags
None — internal test infrastructure, no external inputs/auth/network/secrets. The planned tampering mitigations were applied exactly:
- **T-04-03** (--freeze auto-heal): `--freeze` is OFF by default; default runs are DIFF-ONLY and fail on drift; the conftest docstring mandates deliberate per-scenario freeze with a VERIFY note (Pitfall 5).
- **T-04-04** (silent no-tolerance diff): reused the oracle's exact `assert_frame_equal(check_exact=True)` with zero `rtol`/`atol` (acceptance asserts `grep -c 'rtol\|atol' == 0`). Plan 03's canary will prove the diff actually fails on a mutated golden.
- **T-04-05** (marker mis-registration): `--strict-markers` forces registration in pyproject.toml; `make test` has no `-m` filter so e2e is included; collect-only proves the marker resolves.

## Self-Check: PASSED
- FOUND: tests/e2e/conftest.py
- FOUND: tests/e2e/__init__.py
- FOUND: `from itrader.reporting.summary import` in tests/e2e/conftest.py
- FOUND: `e2e:` marker in pyproject.toml
- FOUND: `"e2e" in parts` in tests/conftest.py
- FOUND: `test-e2e` in Makefile (+ on .PHONY)
- FOUND commit d5912ac (Task 1)
- FOUND commit 006b7a0 (Task 2)

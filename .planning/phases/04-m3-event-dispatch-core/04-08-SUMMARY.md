---
phase: 04-m3-event-dispatch-core
plan: 08
subsystem: logging
tags: [logging, structlog, env-config, d-20, d-21, pitfall-8, m3-03]
requires:
  - "04-06 (routing-registry dispatcher — per-TIME log already demoted to DEBUG there)"
  - "04-07 (ITraderError hierarchy — no exception-surface overlap, simulated.py base merged)"
provides:
  - "env-driven logger config: ITRADER_LOG_LEVEL / ITRADER_JSON_LOGS read via os.environ — no Settings construction in logger.py (Pitfall 8: import itrader never raises ValidationError when ITRADER_DATABASE_URL is unset)"
  - "guarded, idempotent handler setup: sentinel-flagged handler swap removes only handlers this module installed; embedder/pytest handlers survive; repeated init never stacks duplicates"
  - "D-20 falsy-check fix: component presence in reorder_fields_for_console tested with 'is not None'"
  - "zero logging.getLogger('TradingSystem') in strategy_handler/ and live_streaming/ — SMA_MACD, sltp_models, BINANCE_Live bound through get_itrader_logger"
  - "D-21 level policy: per-signal (order_manager) and per-fill (simulated exchange) logs at DEBUG; lifecycle facts stay INFO — default backtest terminal quiet"
  - "tests/unit/core/test_logger_config.py: 6 env-wiring/guarding regression tests"
affects: [phase-05, M5b-engine-logger-deletion]
tech-stack:
  added: []
  patterns:
    - "env-var config reads via os.environ with names matching the pydantic-settings ITRADER_ prefix (Settings.log_level stays the documented knob; instance never constructed at import time)"
    - "sentinel-attribute handler ownership: setattr(handler, '_itrader_handler', True) + guarded removal for idempotent root-logger setup"
    - "log-level policy: per-flow facts (per-signal, per-fill, per-TIME) DEBUG; lifecycle facts (init, connect, run start/finish) INFO"
key-files:
  created:
    - tests/unit/core/test_logger_config.py
  modified:
    - itrader/logger.py
    - itrader/strategy_handler/SMA_MACD_strategy.py
    - itrader/strategy_handler/sltp_models/sltp_models.py
    - itrader/price_handler/live_streaming/BINANCE_Live.py
    - itrader/order_handler/order_manager.py
    - itrader/execution_handler/exchanges/simulated.py
key-decisions:
  - "init_logger keeps its config parameter (now Any = None, documented as ignored) so itrader/__init__.py's init_logger(config) call site stays untouched — plan's files_modified list respected"
  - "import-safety proven via subprocess probe (sys.executable -c 'import itrader' with all ITRADER_* env stripped and PYTHONPATH pinned to the repo root) — robust against the worktree shared-venv itrader.pth gotcha"
  - "order_manager demotion sites are the two per-signal INFO logs at actual lines 178/389 (plan's ~161/~220 had drifted after 04-02/04-07 edits); per-order modify/cancel INFO logs at 522/578 left at INFO — they are user-initiated lifecycle facts, not per-bar flow"
metrics:
  duration: "~7 min"
  completed: "2026-06-05"
  tasks: 2
  files: 7
---

# Phase 4 Plan 08: Logging Unification Summary

Logging unified and config-driven (M3-03, D-20/D-21): log level and JSON rendering now come from ITRADER_LOG_LEVEL/ITRADER_JSON_LOGS via direct os.environ reads (no Settings construction — import itrader stays safe without ITRADER_DATABASE_URL), root-handler setup is sentinel-guarded and idempotent, the two in-scope stdlib 'TradingSystem' loggers are bound through get_itrader_logger, and per-signal/per-fill logs are demoted to DEBUG so the default backtest terminal is quiet — locked by 6 regression tests (429 passed, mypy strict clean, oracle byte-exact with unmodified assertions).

## Tasks Completed

| Task | Name | Commit | Key Files |
| ---- | ---- | ------ | --------- |
| 1 | Env-driven logger config + guarded handler setup + falsy-check fixes | ab0b634 | itrader/logger.py, tests/unit/core/test_logger_config.py |
| 2 | Stdlib-logger swaps + per-flow DEBUG demotion (D-21 policy) | 9dd2ef2 | SMA_MACD_strategy.py, sltp_models.py, BINANCE_Live.py, order_manager.py, simulated.py |

## What Was Built

- **Env wiring (Pitfall 8 safe):** `_env_log_level()` returns `os.environ.get("ITRADER_LOG_LEVEL", "INFO")`; `_env_json_logs()` parses `ITRADER_JSON_LOGS` truthily (`1`/`true`/`yes`, case-insensitive, stripped). `init_logger` feeds both into `setup_logging(json_logs=..., log_level=...)` — the dead `getattr(config, "LOG_LEVEL", "INFO")` read and the hardcoded `json_logs=False` literal are gone. Zero `Settings()` constructions in logger.py (the plan's literal grep gate passes); SecretStr values are never touched or logged.
- **Guarded handler setup (T-04-24):** the handler this module installs is flagged with a `_itrader_handler` sentinel attribute; setup removes only sentinel-flagged handlers before adding the fresh one. Foreign handlers (pytest capture, embedding applications) survive; calling setup twice keeps exactly one itrader handler.
- **D-20 falsy fix:** `reorder_fields_for_console`'s `if component:` → `if component is not None:` so a legitimate falsy value is not silently dropped. (Audited the rest of the file: no other `if value:` checks that could drop legitimate 0/"" values.)
- **Stdlib swaps:** `SMA_MACD_strategy.py` (component="SMA_MACD_strategy"), `sltp_models/sltp_models.py` (component="SltpModels") — both TABS files, module-level two-line swap; `BINANCE_Live.py` got the identical swap only (D-live, no other changes; its three logger.info/warning/error call sites are signature-compatible with ITraderStructLogger). `engine_logger.py` untouched (zero diff); `my_strategies/` untouched.
- **D-21 demotions:** `order_manager.py:178` ('Processed signal for ...') and `:389` ('Created N/M orders from signal ...') INFO → DEBUG; `simulated.py:241` ('Order executed: ...') INFO → DEBUG. Lifecycle facts (exchange init, connect/disconnect, modify/cancel results) stay INFO.
- **Regression tests (6 new, 4-space, pytest, monkeypatch):** defaults without env (INFO/False), ITRADER_LOG_LEVEL=DEBUG honored, ITRADER_JSON_LOGS=true installs a JSONRenderer in the ProcessorFormatter chain, subprocess import-safety probe with ITRADER_* env stripped, double-init handler idempotency, foreign-handler survival.

## Verification Results

- `grep "ITRADER_LOG_LEVEL" itrader/logger.py` → present; `grep -c "Settings()" itrader/logger.py` → **0**
- `grep -rn "logging.getLogger('TradingSystem')" itrader/strategy_handler/ itrader/price_handler/live_streaming/` → **0 matches**
- `git diff` over `itrader/reporting/engine_logger.py` → empty (byte-identical, untouched)
- Pitfall 9 re-verified: zero `caplog` uses and zero assertions on the demoted log text anywhere in tests/
- `tests/integration/test_backtest_oracle.py` — **passes UNMODIFIED**: behavioral + numerical oracle byte-exact (logs are not oracle columns; `git diff` over `tests/integration/` empty across the plan)
- Full suite: **429 passed** (Wave 6b baseline 423 + 6 new; zero tests lost)
- `poetry run mypy itrader` (the `make typecheck` command): Success — 134 files
- (Worktree note: all pytest/mypy runs executed with `PYTHONPATH=$(worktree-root)` per the Wave 1 shared-venv gotcha; `make test`/`make typecheck` invoked via their underlying poetry commands because the gitignored `.env` is absent in worktrees)

## Deviations from Plan

### Minor in-scope clarifications

**1. [Rule 3 - Line drift] order_manager demotion sites at 178/389, not ~161/~220**
- **Found during:** Task 2 read_first review
- **Issue:** the plan's approximate line numbers predate the 04-02/04-07 edits to order_manager.py; the two per-signal INFO logs now sit at lines 178 and 389
- **Fix:** demoted the two logs the plan describes by content ('Processed signal for ...' and 'Created N/M orders from signal ...'); the per-order modify/cancel INFO logs at 522/578 were left at INFO (user-initiated lifecycle, not per-bar flow — not named by the plan)
- **Files modified:** itrader/order_handler/order_manager.py
- **Commit:** 9dd2ef2

**2. [Rule 3 - Verify-gate wording] docstring rephrased to keep the literal Settings() grep at zero**
- **Found during:** Task 1 verification
- **Issue:** the automated gate greps for the literal string `Settings()`; explanatory docstrings initially mentioned it
- **Fix:** docstrings reworded ("a ``Settings`` instance") so the zero-occurrence gate passes while the Pitfall-8 rationale stays documented
- **Files modified:** itrader/logger.py
- **Commit:** ab0b634

## Known Stubs

None — no placeholder values or unwired data.

## Threat Flags

None — no new network endpoints, auth paths, file access patterns, or trust-boundary schema changes. T-04-22 mitigated (no Settings construction; SecretStr never dereferenced; no .get_secret_value() anywhere in logging paths); T-04-23 mitigated (direct os.environ reads + subprocess import-safety regression test); T-04-24 mitigated (sentinel-guarded idempotent handler installation + foreign-handler survival test).

## TDD Gate Compliance

Not applicable — plan type is `execute`, not `tdd`.

## Self-Check: PASSED

- `itrader/logger.py` contains `ITRADER_LOG_LEVEL` and zero `Settings()` occurrences
- `tests/unit/core/test_logger_config.py` exists and contains `ITRADER_LOG_LEVEL`
- Commits exist: ab0b634, 9dd2ef2
- Deletion check: `git diff --diff-filter=D HEAD~2 HEAD` → zero files deleted
- Oracle assertions untouched: `git diff` over `tests/integration/` empty across the plan
- Phase-final gate (D-24): full suite 429 passed + mypy strict clean + oracle byte-exact — last plan of Phase 04

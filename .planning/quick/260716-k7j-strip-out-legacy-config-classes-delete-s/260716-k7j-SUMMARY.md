---
quick_id: 260716-k7j
subsystem: config
status: complete
tags: [config, refactor, dead-code-removal, oracle-gated, inertness]
requirements: [QT-260716-k7j]
provides:
  - "RuntimeSettings (config/runtime.py) slim ITRADER_* logging-knob env layer"
  - "frozen ITraderConfig.timezone base field (Europe/Paris)"
  - "ITraderConfig.logging: RuntimeSettings field (env-parsing preserved)"
requires:
  - "ITraderConfig frozen root (P9-01)"
affects:
  - "itrader/config, logger, results, trading_system, venues, universe, price_handler"
key-files:
  created:
    - itrader/config/runtime.py
  modified:
    - itrader/config/system.py
    - itrader/config/itrader_config.py
    - itrader/config/__init__.py
    - itrader/config/models.py
    - itrader/logger.py
    - itrader/config/stream.py
    - itrader/config/safety.py
    - itrader/config/sql.py
    - itrader/results/serializers.py
    - itrader/trading_system/engine_context.py
    - itrader/trading_system/live_trading_system.py
    - itrader/venues/okx_plugin.py
    - itrader/universe/universe_handler.py
    - itrader/price_handler/store/sql_store.py
    - tests/unit/config/test_itrader_config.py
    - tests/unit/config/test_safety_config.py
    - tests/unit/config/test_config_models.py
    - tests/unit/venues/test_okx_plugin.py
    - tests/unit/venues/test_assemble.py
    - tests/unit/core/test_logger_config.py
    - tests/integration/test_okx_inertness.py
    - tests/e2e/conftest.py
    - tests/e2e/strategies/scripted_emitter.py
  deleted:
    - itrader/config/settings.py
    - tests/unit/config/test_system_config.py
decisions:
  - "New field named `logging` (not `runtime`) per user decision — no `runtime` field remains on ITraderConfig"
  - "timezone re-homed as a FROZEN base param on ITraderConfig; TIMEZONE re-derives from its class default"
  - "log_level/disable_logs re-homed onto a slim RuntimeSettings(BaseSettings) sub-model, preserving ITRADER_* env-parsing"
  - "Settings.environment dropped as redundant (ITraderConfig already has an Environment enum base field)"
metrics:
  duration: 18min
  completed: 2026-07-16
  tasks: 3
  files: 25
---

# Quick Task 260716-k7j: Strip legacy config classes (Settings + SystemConfig) Summary

Deleted the two production-dead config classes — `Settings` (`config/settings.py`) and
`SystemConfig` (`config/system.py`) — and re-homed their surviving fields onto the live
frozen root `ITraderConfig`: `timezone` moved to the frozen base, `log_level`/`disable_logs`
re-homed via a new slim `RuntimeSettings(BaseSettings)` mounted as `config.logging`, with the
legacy `runtime` field dropped. Every consumer, barrel, test, and stale docstring repointed
with zero dangling references; byte-exact oracle + OKX import-inertness + `mypy --strict` all
green.

## What Changed

### Task 1 — Delete Settings + SystemConfig, re-home fields (commit `c7938cb8`)
- **NEW** `itrader/config/runtime.py`: `RuntimeSettings(BaseSettings, env_prefix="ITRADER_", extra="ignore")` with exactly two fields (`log_level: str = "INFO"`, `disable_logs: bool = False`). Imports only `pydantic_settings` — stays on the inert backtest import graph.
- **DELETED** `itrader/config/settings.py` (the `Settings` class).
- **`config/system.py`**: removed the `SystemConfig` class (body + `from_dict`/`default` + `sql` cached_property); kept `Environment`/`LogLevel`/`SystemSettings`/`UniverseConfig`; trimmed the now-orphaned imports (settings/safety/stream/functools/typing/TYPE_CHECKING SqlSettings).
- **`config/itrader_config.py`**: added frozen base param `timezone: str = "Europe/Paris"`; removed `runtime: Settings` + its import; added `from ...runtime import RuntimeSettings` and `logging: RuntimeSettings = Field(default_factory=RuntimeSettings)`; refreshed the class docstring.
- **`config/__init__.py`**: dropped `Settings`/`SystemConfig`, added `RuntimeSettings`; repointed `TIMEZONE = str(ITraderConfig.model_fields["timezone"].default)`; updated `__all__` + header comments.
- **`config/models.py`**: dropped `SystemConfig` from the system import + `__all__`.

### Task 2 — Repoint every consumer, test, docstring (commit `838138e7`)
- **Tests**: deleted `test_system_config.py`, migrating its import-safety pins (eager stream/feed_provider defaults, `sql` cached_property-not-a-field, unbuilt-at-import) into `test_itrader_config.py` retargeted to `ITraderConfig`; added new pins for `timezone` frozen-base read + setattr-raises, `TIMEZONE` derivation, `logging` field / no-`runtime`-field, and `ITRADER_LOG_LEVEL` env-parsing. Retargeted `test_safety_config.py` + the two venue `_fake_ctx()` helpers to `ITraderConfig()`. Reworded prose in `test_config_models.py`, `test_logger_config.py`, `test_okx_inertness.py`, `conftest.py`, `scripted_emitter.py`.
- **Source prose sweep** (comments/docstrings only, zero behavior change): `logger.py`, `config/stream.py`, `config/safety.py`, `config/sql.py`, `results/serializers.py`, `trading_system/engine_context.py`, `trading_system/live_trading_system.py`, `venues/okx_plugin.py`, `universe/universe_handler.py`, `price_handler/store/sql_store.py` — every mention of the deleted `Settings`/`SystemConfig` names now reads `ITraderConfig`/`RuntimeSettings`/`TIMEZONE`.

### Task 3 — Verification gate (no source changes)
All four gates pass (outputs below).

## Verification Gate Results

**1. Full suite — `poetry run pytest tests -q`: PASS**
```
======================= 2307 passed, 6 skipped in 38.49s =======================
```
(6 skips are all OKX-demo-credential-gated e2e/integration suites — unrelated to this change.)

**2. Byte-exact oracle — `poetry run pytest tests/integration/test_backtest_oracle.py -v`: PASS**
```
test_oracle_behavioral_identity PASSED
test_oracle_numeric_values PASSED
test_golden_run_signal_store_is_non_empty_and_queryable PASSED
============================== 3 passed in 1.01s ===============================
```
134 trades / `46189.87730727451` unchanged — confirms `TIMEZONE == "Europe/Paris"` and `rng_seed == 42` survived the move to the frozen base.

**3. Import inertness — `poetry run pytest tests/integration/test_okx_inertness.py -q`: PASS**
```
4 passed in 1.19s
```
`import itrader` pulls no sqlalchemy/ccxt; the lazy `sql` cached_property stays unbuilt at import.

**4. Types — `poetry run mypy itrader`: PASS**
```
Success: no issues found in 261 source files
```

Task-1 inline verification also passed:
```
T1 OK
```
(`TIMEZONE == c.timezone == "Europe/Paris"`, `rng_seed == 42`, no `runtime` field, `logging` field present with `INFO`/`False`, no sqlalchemy/ccxt on import.)

## Deviations from Plan

None — plan executed exactly as written. One process note: the Task-2 `git add` list included the already-`git rm`'d `test_system_config.py` path, which aborted the batch add; corrected by re-staging + `--amend` (final Task-2 commit `838138e7` contains all 23 file changes).

## Known Stubs

None.

## Self-Check: PASSED

- `itrader/config/runtime.py` — FOUND
- `itrader/config/settings.py` — CONFIRMED DELETED
- `tests/unit/config/test_system_config.py` — CONFIRMED DELETED
- Commit `c7938cb8` (Task 1) — FOUND in git log
- Commit `838138e7` (Task 2) — FOUND in git log (HEAD)
- Grep gates: zero `from itrader.config.settings`, zero bare `SystemConfig`, zero bare `Settings` across itrader/tests

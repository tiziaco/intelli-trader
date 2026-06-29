---
phase: quick-260629-l0q
plan: 01
subsystem: config
tags: [config, sql, settings, pydantic, refactor]
requires: []
provides:
  - "unified SqlSettings(BaseSettings): env_prefix ITRADER_DATABASE_, connection params, conditional Postgres validation, guard-clause engine_url()"
  - "Settings reverted to non-DB env only (no required secret)"
affects:
  - itrader/storage/backend.py
  - itrader/storage/migrations/env.py
  - itrader/price_handler/store/sql_store.py
tech-stack:
  added: []
  patterns:
    - "self-contained BaseSettings owning prefix + params + validation + URL builder"
    - "driver-conditional model_validator fail-loud (ValueError -> pydantic.ValidationError)"
    - "guard-clause / early-exit (no cascading/nested if)"
key-files:
  created: []
  modified:
    - itrader/config/sql.py
    - itrader/config/settings.py
    - itrader/storage/migrations/env.py
    - itrader/price_handler/store/sql_store.py
    - tests/unit/storage/test_sql_settings.py
    - tests/unit/config/test_config_models.py
    - .env.example
decisions:
  - "Unified self-contained SqlSettings(BaseSettings) supersedes 260629-jh2 (and transitively IN-02)"
metrics:
  duration: ~15m
  completed: 2026-06-29
---

# Quick Task 260629-l0q: Unify SQL Settings Summary

Collapsed the `SqlSettings` / proposed-`DatabaseSettings` / `Settings.database_*` split into ONE self-contained `SqlSettings(BaseSettings)` (env_prefix `ITRADER_DATABASE_`) that owns the connection params, the conditional Postgres validation, and the guard-clause `engine_url()` builder; removed all DB fields from `Settings`.

## What Was Built

**Task 1 — unify `SqlSettings`; revert `Settings`** (commit `17687a6`)
- `itrader/config/sql.py`: `SqlSettings` is now a `BaseSettings` with `SettingsConfigDict(env_prefix="ITRADER_DATABASE_", extra="forbid")`. Added `host`/`port`/`user`/`name`/`password`/`url` fields alongside `driver`/`database`/`strict_persist`.
- Added a `_require_pg_credentials` `@model_validator(mode="after")` in guard-clause / early-exit style — raises `ValueError` (so pydantic wraps it into `pydantic.ValidationError`) when `driver=POSTGRESQL` with neither `password` nor `url`.
- `engine_url()` dropped its `settings` param; reads `self.*` only; guard-clause/early-exit. The `# type: ignore[call-arg]` was removed (no required-no-default field anymore). `ConfigurationError` (confirmed import: `from itrader.core.exceptions import ConfigurationError`) is used ONLY for the defensive mypy-narrowing guard (unreachable in practice — the validator guarantees a password on the assembled-URL arm).
- `default()` / `results_default()` pin `driver`+`database` via init kwargs (init outranks env) → deterministic, env-tolerant SQLite/backtest path; no password ever needed.
- `itrader/config/settings.py`: reverted to non-DB env only (`timezone`/`log_level`/`environment`/`disable_logs`); removed the unused `SecretStr` import.
- Refreshed stale docstrings in `storage/migrations/env.py` and `price_handler/store/sql_store.py` (logic unchanged).

**Task 2 — rewrite tests; relocate Settings-secret coverage** (commit `9edbec7`)
- `tests/unit/storage/test_sql_settings.py`: rewritten to the unified API — sqlite default credential-free; driver enum members; (a) component assembly at port 5544; (b) special-char password escaping (`%40 %3A %2F %23 %3F`); (c) verbatim `url` escape hatch wins; (d) sqlite arm credential-free; (e) fail-loud `ValidationError` + `SecretStr` masking; import-does-not-instantiate (subprocess); extra-keys-forbidden. All env-isolated via explicit kwargs + `_env_file=None`.
- `tests/unit/config/test_config_models.py`: removed the two obsolete `Settings`-secret tests (Settings no longer carries a DB secret); kept the `PortfolioConfig` tests; updated docstring noting the relocation.

**Task 3 — refresh `.env.example`** (commit `aaf4d76`)
- Env var names unchanged (single underscore); refreshed comments to note these bind to the unified `SqlSettings`; `URL` documented as the optional verbatim override.

## Verification

- `poetry run mypy itrader/config itrader/storage itrader/price_handler/store/sql_store.py` → clean (14 files, no new ignores; the `call-arg` ignore is gone).
- Task 1 env-isolated python check → `OK` (assembly+escape, verbatim hatch, fail-loud, `Settings` has no `database_*`).
- `poetry run pytest tests/unit/storage/test_sql_settings.py tests/unit/config/test_config_models.py tests/unit/storage/test_sql_backend.py tests/integration/storage/test_migrations.py -v` → 21 passed.
- Broader sweep `poetry run pytest tests/unit/storage tests/unit/config tests/integration/storage -q` → 38 passed.
- `git check-ignore .env.example` → exit 1 (not gitignored).
- No live (non-docstring) code references to the removed `Settings.database_*` fields remain.

## Deviations from Plan

None — plan executed as written. The plan's guessed `ConfigurationError` import path (`from itrader.core.exceptions import ConfigurationError`) was confirmed correct against `itrader/core/exceptions/__init__.py`.

## Decisions

`SqlSettings` is now ONE self-contained `BaseSettings` (`env_prefix=ITRADER_DATABASE_`) owning the connection params + conditional Postgres validation + the URL builder. The proposed separate `DatabaseSettings` split was rejected as redundant; the DB fields were removed from `Settings`. Env var names are kept single-underscore (no `.env` migration). The backtest construction is env-tolerant (not env-required) and kept deterministic by pinning `driver`/`database` in `default()`/`results_default()`. This **supersedes 260629-jh2** (and transitively **IN-02**).

Accepted trade-offs:
1. Fail-loud moved from a required `Settings` field to a driver-conditional `SqlSettings` validator (only the Postgres arm without password/url raises).
2. The backtest now constructs a `BaseSettings` (runs the env-source pipeline) rather than a plain `BaseModel` — kept deterministic via pinned `default()`/`results_default()` init kwargs.

## Self-Check: PASSED

All modified files present; all three task commits (`17687a6`, `9edbec7`, `aaf4d76`) found in `git log`.

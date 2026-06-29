---
phase: quick-260629-jh2
plan: 01
subsystem: config
tags: [config, postgres, env, security, settings]
requires:
  - itrader/config/settings.py (Settings BaseSettings seam, env_prefix ITRADER_)
  - itrader/config/sql.py (SqlSettings.engine_url Postgres arm)
provides:
  - "Settings: database_host/port/user/name/password component env fields + optional verbatim database_url"
  - "SqlSettings.engine_url(): Postgres URL assembled via sqlalchemy.URL.create with verbatim escape hatch"
  - ".env.example documenting the full env surface (committed)"
affects:
  - itrader/price_handler/store/sql_store.py (consumes engine_url unchanged)
  - itrader/storage/backend.py (consumes engine_url unchanged)
  - itrader/storage/migrations/env.py (consumes engine_url unchanged)
tech-stack:
  added: []
  patterns: ["sqlalchemy.URL.create for password-safe URL assembly", "component env vars on the canonical Settings seam"]
key-files:
  created:
    - .env.example
  modified:
    - itrader/config/settings.py
    - itrader/config/sql.py
    - tests/unit/storage/test_sql_settings.py
    - tests/unit/config/test_config_models.py
decisions:
  - "260629-jh2 supersedes IN-02: env-driven component assembly (ITRADER_DATABASE_* host/port/user/name/password) is the PRIMARY Postgres URL source with default port 5544; ITRADER_DATABASE_URL becomes an OPTIONAL verbatim escape hatch."
metrics:
  duration: 4m
  completed: 2026-06-29
---

# Quick Task 260629-jh2: Parametrize Postgres Env Surface Summary

Parametrized the Postgres connection via component-level `ITRADER_DATABASE_*` env vars
(host/port/user/name/password, default port **5544** not 5432) on the canonical `Settings`
seam, assembling the engine URL with `sqlalchemy.URL.create` (password-safe escaping) while
keeping `ITRADER_DATABASE_URL` as an optional verbatim escape hatch; added a committed
`.env.example` documenting the full env surface.

## What Changed

- **`itrader/config/settings.py`** — Added `database_host` (`localhost`), `database_port`
  (`5544`), `database_user` (`postgres`), `database_name` (`itrader`) component fields and a
  required-no-default `database_password: SecretStr`. Changed `database_url` from a required
  `SecretStr` to an optional `SecretStr | None = None` (verbatim escape hatch). The fail-loud
  secret (M2-06 "no working secret defaults") is now `database_password`. Module docstring
  updated.
- **`itrader/config/sql.py`** — Rewrote only the Postgres arm of `engine_url()`. Added
  `from sqlalchemy import URL`. Resolution order: (1) if `Settings.database_url` is set, return
  it verbatim (escape hatch, original IN-02 path); (2) otherwise assemble via
  `URL.create(drivername="postgresql+psycopg2", username, password, host, port, database)
  .render_as_string(hide_password=False)`, which URL-escapes `@ : / # ?` in the password. Lazy
  `Settings()` resolution preserved (Pitfall 8 — never at import). SQLite-family arms left
  byte-identical and env-free. The existing `# type: ignore[call-arg]` stays valid (no new
  ignores). The IN-02 inline narrative was replaced with the superseding `260629-jh2` decision.
- **`.env.example`** (new, committed) — Grouped, placeholder-only documentation of the full env
  surface: logging (`ITRADER_LOG_LEVEL`, `ITRADER_JSON_LOGS`, `ITRADER_DISABLE_LOGS`),
  component Postgres store (port 5544), the optional verbatim `ITRADER_DATABASE_URL`, legacy
  D-live seams (`DATA_DB_URL`/`SYSTEM_DB_URL`, documented-only), and exchange credentials.
  `.env` stays gitignored; `.env.example` is not matched by the exact `.env` ignore rule.
- **Tests** — Added engine_url assembly tests in `tests/unit/storage/test_sql_settings.py`:
  component assembly with port 5544, special-char password escaping
  (`%40 %3A %2F %23 %3F`), verbatim-URL-wins escape hatch, and no-password
  `ValidationError`. Updated the previously-passing verbatim test (renamed to
  `test_postgres_arm_verbatim_url_wins_as_escape_hatch`) and the fail-loud / mask tests in
  `tests/unit/config/test_config_models.py` for the now-required `database_password`.

## Decisions

- **260629-jh2 — supersedes IN-02 (phase 01).** IN-02 held that on the Postgres arm "the driver
  is a branch selector only and the env URL (`ITRADER_DATABASE_URL`) is authoritative" — the
  only Postgres knob. As of this task, **env-driven component assembly** (`ITRADER_DATABASE_*`:
  host/port/user/name/password) is the **PRIMARY** Postgres URL source, with default port
  **5544** (5432 is taken by another DB on the target machine). `ITRADER_DATABASE_URL` is
  **demoted to an OPTIONAL verbatim escape hatch** — when set it wins over the assembled URL
  (its scheme/driver authoritative, honored as-is). The fail-loud secret moves from
  `database_url` to `database_password`, preserving the M2-06 "no working secret defaults"
  criterion. URL assembly uses `sqlalchemy.URL.create(...).render_as_string(hide_password=False)`
  rather than an f-string because f-strings do not URL-escape special chars in passwords.

## Deviations from Plan

None — plan executed exactly as written.

## Verification

- `poetry run mypy itrader/config` → Success: no issues found in 9 source files (no new ignores
  beyond the existing `call-arg`).
- `poetry run pytest tests/unit/storage/test_sql_settings.py tests/unit/config/test_config_models.py -v`
  → 13 passed.
- Broader sweep `poetry run pytest tests/unit/{storage,config,results,price_handler}
  tests/unit/core/test_logger_config.py -q` → 82 passed (no regressions in downstream
  `engine_url` consumers).
- Task 1 assembly check emits `postgresql+psycopg2://u:p%40ss%3Aw%2Frd%23%3F@h:5544/itrader`.
- `git check-ignore .env.example` → exit 1 (committed); `.env` stays ignored.

## Commits

- `eec6af4` feat(config): parametrize Postgres URL via ITRADER_DATABASE_* components
- `fa20149` docs(config): add .env.example documenting full env surface
- `075837b` test(config): cover Postgres component assembly, escaping, and fail-loud

## Self-Check: PASSED

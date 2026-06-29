---
phase: 01-sql-spine-security-hardening
reviewed: 2026-06-27T19:28:03Z
depth: standard
files_reviewed: 19
files_reviewed_list:
  - itrader/config/sql.py
  - itrader/price_handler/store/sql_store.py
  - itrader/results/__init__.py
  - itrader/results/base.py
  - itrader/storage/__init__.py
  - itrader/storage/backend.py
  - itrader/storage/migrations/env.py
  - itrader/storage/migrations/script.py.mako
  - itrader/storage/migrations/versions/.gitkeep
  - itrader/storage/types.py
  - tests/integration/storage/conftest.py
  - tests/integration/storage/test_engine_fixture.py
  - tests/integration/storage/test_migrations.py
  - tests/integration/storage/test_spine_roundtrip.py
  - tests/unit/price_handler/test_sql_handler.py
  - tests/unit/results/test_results_store_abc.py
  - tests/unit/storage/test_sql_backend.py
  - tests/unit/storage/test_sql_settings.py
  - tests/unit/storage/test_types.py
findings:
  critical: 0
  warning: 0
  info: 0
  total: 0
status: clean
---

# Phase 01: Code Review Report (Re-review, iteration 2)

**Reviewed:** 2026-06-27T19:28:03Z
**Depth:** standard
**Files Reviewed:** 19
**Status:** clean

## Summary

This is iteration 2 of the `--auto` fix loop. All nine findings from the first review (6
Warning + 3 Info) were addressed across nine atomic fix commits. Every fix was verified on
the current state of the code — directly in source and, where the property is empirically
checkable, by running it. No fix is incomplete, and no fix introduced a new defect.

All reviewed files now meet quality standards. No issues found.

**Verification of each prior fix:**

- **WR-01 (timezone literal):** `read_prices` now imports `from itrader.config import
  TIMEZONE` (`sql_store.py:49`) and calls `tz_convert(TIMEZONE)` (`sql_store.py:158`). The
  only remaining `Europe/Paris` occurrence is an explanatory comment, not a code literal.
  `TIMEZONE` resolves from `Settings.model_fields["timezone"].default` (`config/__init__.py:66`)
  — the same authoritative source `CsvPriceStore` uses, so the two stores no longer diverge.
  The import is env-free (reads a field default, never instantiates `Settings()`) and does
  not affect the GATE-01 quarantine (`sql_store` is already off the inert path).

- **WR-02 (naive-datetime coercion):** `UtcIsoText.process_bind_param` now raises
  `ValueError` on a `tzinfo is None` value (`types.py:52-58`) before the host-local
  `astimezone` coercion can silently shift the instant. The write path
  (`_rows_from_frame` normalizes to tz-aware UTC) always supplies aware datetimes, so the
  guard is correct and does not break current callers; the determinism/round-trip tests
  still pass.

- **WR-03 (shared-engine lifecycle):** `SqlBackend.dispose()` now owns engine teardown
  (`backend.py:32-40`); `SqlHandler.stop_engine()` delegates via `self.backend.dispose()`
  (`sql_store.py:104`) instead of disposing the shared engine directly. The backend
  unit test asserts `dispose` is the sole public method.

- **WR-04 (unconstrained ORDER BY seam):** `top_runs` is now typed
  `metric: MetricName` where `MetricName = Literal["sharpe", "total_return",
  "max_drawdown", "calmar"]` (`results/base.py:29,91`), moving allow-list enforcement to
  the single ABC declaration so the interpolation pattern cannot be written by an
  implementer.

- **WR-05 (import-time engine leak + inaccurate docstring):** `env.py` now uses a bare
  `target_metadata = MetaData()` (`env.py:49`) — no `SqlBackend`, no `create_engine`, no
  undisposed `SingletonThreadPool` at import. The remaining `SqlBackend` reference is a
  comment explaining what was avoided. The docstring ("URL resolved lazily inside the run
  functions, never at import") is now accurate: `_resolve_url()` is only called inside
  `run_migrations_offline/online`.

- **WR-06 (too-narrow security gates):** the FL-06 grep gates are now structural regexes —
  `://[^:\s/@]+:[^@\s/]+@` for embedded credentials and `(?<![A-Za-z0-9_])text\(\s*f["']`
  for f-strings in `text()`. Reproduced and exercised both: they catch real anti-patterns
  (`postgresql+psycopg2://itrader:itrader123@…`, `text( f"…"`, line-broken `text(\n  f"…")`),
  reject the safe shapes (`sqlite+pysqlite:///:memory:`, `postgresql://user@host`,
  `text("SELECT 1")`, `_operation_context(f"…")`), produce zero false positives across
  `itrader/`, and the test scans only `itrader/` so the gate cannot self-trip on the
  fragment-assembled patterns in the test file.

- **IN-01 (plaintext URL render):** `test_migrations.py:97-101` now carries an inline
  SECURITY note that the rendered password is a disposable testcontainers value and the
  pattern must not be copied to a real/shared credential.

- **IN-02 (driver ignored on Postgres arm):** `engine_url` now documents that on the
  Postgres arm `driver` is a branch-selector only and the env URL is authoritative
  (`config/sql.py:70-79`).

- **IN-03 (deprecated `typing.List`):** `results/base.py` now imports only
  `from typing import Any, Literal` and annotates `list[Any]` (`base.py:23,91,105`).

**Gates run on the current state:** the 33 no-Docker/Docker storage, results, and
`sql_handler` tests pass under `filterwarnings=["error"]`; `mypy --strict` reports
"no issues found" on the eight changed source modules. The primary SEC-01/FL-06 surface
(single `prices` table, bound-parameter-only access, single `SecretStr` credential seam,
env-free lazy import) remains intact and is unchanged by the fixes.

---

_Reviewed: 2026-06-27T19:28:03Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_

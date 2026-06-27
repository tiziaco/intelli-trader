---
phase: 01-sql-spine-security-hardening
reviewed: 2026-06-27T19:04:19Z
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
  warning: 6
  info: 3
  total: 9
status: issues_found
---

# Phase 01: Code Review Report

**Reviewed:** 2026-06-27T19:04:19Z
**Depth:** standard
**Files Reviewed:** 19
**Status:** issues_found

## Summary

The SQL spine correctly closes the three FL-06/SEC-01 vectors named in the brief: the
hardcoded-credential literal, the dynamic-identifier `DROP TABLE` DDL injection, and the
symbol-as-table-name identifier injection. Verified directly: `SqlHandler` issues only
parameterized Core SQL against the constant `"prices"` table (bound `symbol`, no string-built
identifiers, no `text()` interpolation); the credential seam is a single `SecretStr`
(`Settings.database_url`) resolved lazily inside `SqlSettings.engine_url()`; and a
fresh-interpreter import with `ITRADER_DATABASE_URL` unset succeeds (no import-time
`Settings()`). The 25 no-Docker unit tests pass under `filterwarnings=["error"]`. The
quarantine boundary (barrel does not pull `sql_store`) holds.

No Critical/Blocker findings — the primary SEC-01 surface is clean. The findings below are a
config-coupling defect, a silent-coercion edge in the encoding gate, a shared-engine
lifecycle hazard, a pre-injection seam in the new ABC, an import-time engine + inaccurate
docstring in the migration env, a too-narrow security grep gate, and three minor items.

## Warnings

### WR-01: `read_prices` hardcodes `"Europe/Paris"` instead of the authoritative `TIMEZONE` constant

**File:** `itrader/price_handler/store/sql_store.py:150`
**Issue:** `df.index = pd.to_datetime(df.index, utc=True).tz_convert("Europe/Paris")` uses a
bare literal. Its sibling `CsvPriceStore` does the identical conversion via the documented
authoritative source — `from itrader.config import TIMEZONE` (`csv_store.py:18`) and
`tz_convert(TIMEZONE)` (`csv_store.py:176`) — where `TIMEZONE` is derived from
`Settings.model_fields["timezone"].default` (`config/__init__.py:66`). The two price stores
now diverge: they are accidentally equal only because the default resolves to `"Europe/Paris"`.
If the timezone is ever reconfigured, the SQL store silently produces a different index
timezone than the CSV store and the rest of the system, surfacing as off-by-hours bugs. The
round-trip test only asserts column values (not the index tz), so the drift is uncaught.
**Fix:**
```python
from itrader.config import TIMEZONE  # alongside existing imports
...
df.index = pd.to_datetime(df.index, utc=True).tz_convert(TIMEZONE)  # line 150
```

### WR-02: `UtcIsoText.process_bind_param` silently coerces naive datetimes against system local time

**File:** `itrader/storage/types.py:49-52`
**Issue:** `value.astimezone(timezone.utc)` on a naive datetime does not raise — Python treats
it as system local time. Confirmed empirically: the same naive `datetime(2018,1,1)` encodes to
`2017-12-31T23:00:00+00:00` on this box (Europe/Paris) and `2018-01-01T05:00:00+00:00` under
`TZ=America/New_York`. This is the conversion gate between Python objects and the DB, and the
module explicitly promises "identical bytes across runs (determinism)" and "explicit UTC" — a
naive value breaks both, silently, and shifts the stored instant. Current callers always pass
aware datetimes, so it is latent, but the Phase-2 results store will reuse this decorator for
arbitrary business-time inputs.
**Fix:**
```python
def process_bind_param(self, value: datetime | None, dialect: Dialect) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        raise ValueError(f"UtcIsoText requires a timezone-aware datetime; got naive: {value!r}")
    return value.astimezone(timezone.utc).isoformat()
```

### WR-03: `SqlBackend` exposes no `dispose()` — shared-engine ownership hazard

**File:** `itrader/storage/backend.py:28-30` (and `sql_store.py:97-99`)
**Issue:** `SqlBackend` creates an `Engine` but offers no disposal surface; the only path to
close it is `SqlHandler.stop_engine()`, which does `self.engine.dispose()` on the *shared*
`backend.engine`. The stated architecture is that multiple storage concerns compose one
`SqlBackend` (has-a). The moment a second concern shares the backend, one store's
`stop_engine()` disposes the engine — and flushes the pooled connections — out from under
every other composing store. Lifecycle should live on the layer that owns the engine.
**Fix:**
```python
class SqlBackend:
    def dispose(self) -> None:
        """Dispose the engine and close all pooled connections."""
        self.engine.dispose()
```
Have `SqlHandler.stop_engine()` delegate (`self.backend.dispose()`), or move disposal
responsibility to the wiring that owns the backend.

### WR-04: `ResultsStore.top_runs(metric: str)` is an unconstrained column-name seam (pre-injection contract)

**File:** `itrader/results/base.py:84-101`
**Issue:** `top_runs(self, metric: str, n: int)` takes a free string intended to choose an
`ORDER BY` column. The ABC is the contract surface for Phase 2; a naive concrete
implementation that interpolates `metric` into an `ORDER BY` (column names cannot be bound
parameters) inherits a SQL-injection vector. Constraining the type at the ABC forces every
implementation to an allow-list and prevents the vulnerable pattern from ever being written.
**Fix:** Narrow the contract to an enumerated set:
```python
from typing import Literal
MetricName = Literal["sharpe", "total_return", "max_drawdown", "calmar"]
...
    def top_runs(self, metric: MetricName, n: int) -> list[Any]: ...
```
or a `str`-Enum following the config-domain enum convention. Either moves allow-list
enforcement to the single ABC declaration.

### WR-05: `env.py` creates an undisposed engine at import; "never at import" docstring is inaccurate

**File:** `itrader/storage/migrations/env.py:47`
**Issue:** `target_metadata = SqlBackend(SqlSettings.default()).metadata` runs at import and
calls `create_engine("sqlite+pysqlite:///:memory:")`, keeping only `.metadata` and discarding
the `SqlBackend` — the `Engine` (with its `SingletonThreadPool`) is never disposed. The module
docstring asserts "the DB URL is resolved LAZILY inside the run functions, never at import";
that holds for the Postgres credential arm but is false for the default SQLite engine, which is
built at import. The autogenerate target is just an (empty) `MetaData`, so the engine is
unnecessary. Under `ResourceWarning` promotion plus `filterwarnings=["error"]`, an
in-process import of `env.py` could fail on the GC-finalised pool.
**Fix:** Use a bare `MetaData()` (no operational tables are registered yet anyway), or retain
the backend and dispose it explicitly; and correct the docstring to scope "lazy" to the
operational Postgres URL only.
```python
from sqlalchemy import MetaData
target_metadata = MetaData()
```

### WR-06: FL-06 credential grep gate is too narrow to enforce its stated guarantee

**File:** `tests/unit/price_handler/test_sql_handler.py:137-145, 162-171`
**Issue:** `_hardcoded_credential_patterns()` checks only the literal substrings
`user:pass@` and `:1234@`, and `_fstring_in_text_patterns()` only `text(f'` / `text(f"` with
no intervening whitespace. The tests are named/documented as proving "no source file under
`itrader/` carries a hardcoded DB credential" and "no f-string inside `text()`", but a real
embedded credential (`postgres:password@`, `itrader:itrader123@`) or `text( f"..."` /
`text(\n  f"...")` passes untouched. A security gate that silently passes for the property it
claims to enforce manufactures false confidence.
**Fix:** Either rename/redocument them as regression guards for the specific legacy literal, or
strengthen the matchers to the structural shape — e.g. regex `://[^:\s/@]+:[^@\s/]+@` for an
embedded credential and `text\(\s*f["']` for the f-string-in-text case (excluding this test
file), assembled from fragments to avoid self-tripping.

## Info

### IN-01: `render_as_string(hide_password=False)` surfaces an unmasked credential URL in test code

**File:** `tests/integration/storage/test_migrations.py:97`
**Issue:** The Postgres migration test renders the engine URL with the password in plaintext
before handing it to Alembic. The credential is a throwaway testcontainers value, so the
direct risk is low — but the pattern is copy-prone into contexts where the URL is a real
secret (e.g. a shared CI database).
**Fix:** Document inline that this is a disposable container password and must not be adapted
for a real/shared credential; prefer passing the live `engine`/connection to Alembic where
feasible.

### IN-02: `SqlSettings.engine_url` Postgres arm ignores the `driver` member with no scheme validation

**File:** `itrader/config/sql.py:70-75`
**Issue:** On the `POSTGRESQL_PSYCOPG2` arm, `engine_url()` returns the raw
`Settings.database_url` value verbatim; the actual scheme/driver is whatever
`ITRADER_DATABASE_URL` carries. A mismatched env scheme (e.g. `postgresql://` without
`+psycopg2`, or an unrelated dialect) is silently honored, so `driver` is effectively a
branch-selector-only flag on this arm — surprising given the field name and a latent
config-mismatch footgun.
**Fix:** Optionally assert the resolved URL's scheme matches the selected driver token, or
document that on the Postgres arm `driver` only selects the branch and the env URL is
authoritative.

### IN-03: `from typing import List` deprecated alias in a Python-3.13 module

**File:** `itrader/results/base.py:23, 85, 98`
**Issue:** Imports and uses `typing.List` (`List[Any]`) where the project convention prefers
the builtin generic `list[...]` (CLAUDE.md "modern union syntax preferred"). `mypy --strict`
accepts both; purely stylistic/consistency.
**Fix:** `from typing import Any` and annotate `list[Any]`.

---

_Reviewed: 2026-06-27T19:04:19Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_

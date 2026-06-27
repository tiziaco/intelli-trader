---
phase: 01-sql-spine-security-hardening
reviewed: 2026-06-27T00:00:00Z
depth: standard
files_reviewed: 19
files_reviewed_list:
  - alembic.ini
  - itrader/config/sql.py
  - itrader/price_handler/store/sql_store.py
  - itrader/results/__init__.py
  - itrader/results/base.py
  - itrader/storage/__init__.py
  - itrader/storage/backend.py
  - itrader/storage/migrations/env.py
  - itrader/storage/migrations/script.py.mako
  - itrader/storage/types.py
  - pyproject.toml
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
  info: 2
  total: 8
status: issues_found
---

# Phase 01: Code Review Report

**Reviewed:** 2026-06-27
**Depth:** standard
**Files Reviewed:** 19
**Status:** issues_found

## Summary

The SQL spine implementation correctly eliminates the three FL-06/SEC-01 injection and credential-disclosure vectors called out in the phase brief (hardcoded credential literal, DDL injection via dynamic-identifier DROP TABLE, per-symbol table name as SQL identifier). Alembic integration, `UtcIsoText` round-trips, `SqlSettings` driver selection, and the GATE-01 quarantine boundary are all structurally sound. The credential seam (`SecretStr` / `get_secret_value()` / lazy `Settings()` instantiation) and the single-`prices`-table parameterized-query model are correct.

Six findings follow. None are injection or credential-disclosure bugs — the primary SEC-01 surface is clean. The issues are: a timezone coupling defect in `sql_store.py` that silently diverges from its sibling `csv_store.py`, a silent-corruption edge in `UtcIsoText`, a missing disposal surface on `SqlBackend`, a pre-injection ABC seam in `ResultsStore`, an inaccurate "lazy" claim in the migration env, and an insufficiently broad FL-06 grep gate.

---

## Warnings

### WR-01: `sql_store.read_prices` hardcodes `"Europe/Paris"` literal instead of the `TIMEZONE` constant

**File:** `itrader/price_handler/store/sql_store.py:150`
**Issue:** `read_prices` converts the returned index with `tz_convert("Europe/Paris")` as a bare string literal. Its sibling `CsvPriceStore` correctly imports and uses `from itrader.config import TIMEZONE` for the identical operation (see `csv_store.py:18,176`). The `TIMEZONE` constant in `itrader/config/__init__.py` reads `Settings.model_fields["timezone"].default` — the single authoritative source for this value.

The current behaviour is accidentally correct (both resolve to `"Europe/Paris"` under the default config), but the coupling defect creates two failure modes:
1. If `TIMEZONE` is ever made to reflect a runtime-configurable value, `sql_store.py` will silently diverge, producing inconsistent bar timestamps between the CSV and SQL price stores.
2. There is no comment anchoring the literal to the config convention, so the intent is invisible to future editors. The round-trip test (`test_ohlcv_round_trips_for_a_single_symbol`) only checks column values, not the index timezone, so this drift would not be caught automatically.

**Fix:**
```python
# at the top of sql_store.py, alongside the existing imports:
from itrader.config import TIMEZONE

# line 150 — replace the literal:
df.index = pd.to_datetime(df.index, utc=True).tz_convert(TIMEZONE)
```

---

### WR-02: `UtcIsoText.process_bind_param` silently coerces naive datetimes using local system time

**File:** `itrader/storage/types.py:49-52`
**Issue:** `value.astimezone(timezone.utc)` on a naive (timezone-unaware) `datetime` does not raise — Python silently treats the naive value as local time and converts it to UTC. On a machine running in UTC-5, `datetime(2018, 1, 1)` would be stored as `"2018-01-01T05:00:00+00:00"` rather than raising. This is a silent data-corruption vector at a trust boundary (the TypeDecorator is the conversion gate between Python objects and the database).

The system convention is that business time is always tz-aware (CLAUDE.md, bar-timing contract). The TypeDecorator should enforce this rather than absorb violations silently.

**Fix:**
```python
def process_bind_param(self, value: datetime | None, dialect: Dialect) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        raise ValueError(
            f"UtcIsoText requires a timezone-aware datetime; got naive: {value!r}"
        )
    return value.astimezone(timezone.utc).isoformat()
```

---

### WR-03: `SqlBackend` exposes no `dispose()` method — lifecycle management is implicit and error-prone

**File:** `itrader/storage/backend.py:28-30`
**Issue:** `SqlBackend` creates an `Engine` in `__init__` but provides no `dispose()` method. Callers must reach into `backend.engine.dispose()` directly, or rely on `SqlHandler.stop_engine()` — which, by design, disposes the shared backend engine. This creates an ownership hazard: if two storage concerns compose the same `SqlBackend` (the stated architectural goal is exactly that), one calling `stop_engine()` through the `SqlHandler` path disposes the shared engine for all other composing stores, causing unexpected pool flushes.

The public API should expose lifecycle management at the `SqlBackend` layer rather than forcing callers through a store's private method.

**Fix:**
```python
class SqlBackend:
    def __init__(self, settings: SqlSettings) -> None:
        self.engine: Engine = create_engine(settings.engine_url())
        self.metadata = MetaData()

    def dispose(self) -> None:
        """Dispose the engine and close all pooled connections."""
        self.engine.dispose()
```

`SqlHandler.stop_engine()` can then delegate: `self.backend.dispose()` (or be removed in favour of callers managing backend lifecycle directly).

---

### WR-04: `ResultsStore.top_runs(metric: str)` accepts an unconstrained column-name string — pre-injection seam for Phase 2

**File:** `itrader/results/base.py:85`
**Issue:** The ABC declares `top_runs(self, metric: str, n: int)` where `metric` is a free string intended to select a summary-metric column for ORDER BY. Any Phase 2 concrete implementation that naively uses `metric` in an ORDER BY clause without an explicit allow-list inherits an injection vector:

```python
# naive Phase 2 pattern — would be SQL-injectable
stmt = select(runs_table).order_by(text(f"ORDER BY {metric} DESC")).limit(n)
```

The ABC surface is the right place to constrain this. Using a `Literal` union or a dedicated Enum fixes it at the contract level, preventing Phase 2 from ever constructing the vulnerable pattern.

**Fix:**
```python
# Define in results/base.py (or a companion enums module):
from typing import Literal

MetricName = Literal["sharpe", "total_return", "max_drawdown", "calmar"]

class ResultsStore(ABC):
    @abstractmethod
    def top_runs(self, metric: MetricName, n: int) -> list[Any]:
        ...
```

Alternatively, a `str`-valued Enum (following the `config/` convention for config-domain enums). Either approach moves the allow-list enforcement from every Phase 2 implementation to the single ABC declaration.

---

### WR-05: Module-level `SqlBackend` instantiation in `env.py` creates an undisposed engine at import time; docstring claim is inaccurate

**File:** `itrader/storage/migrations/env.py:47`
**Issue:** Line 47 runs unconditionally at module import time:
```python
target_metadata = SqlBackend(SqlSettings.default()).metadata
```
This calls `create_engine("sqlite+pysqlite:///:memory:")` and immediately discards the `SqlBackend` object (only `.metadata` is retained). The created `Engine` — along with its `SingletonThreadPool` — is never disposed.

The module docstring states "the DB URL is resolved LAZILY inside the run functions, never at import." This is inaccurate: the SQLite default engine URL IS resolved at import. The claim is only true for the Postgres credential arm. The inaccuracy could mislead future editors into believing the module has no import-time side effects.

Under Python's debug mode (`PYTHONWARNINGFLAGS=d`) or explicit `ResourceWarning` promotion, the GC-finalised engine pool may emit a warning that, given `filterwarnings = ["error"]` in `pyproject.toml`, would fail tests that import `env.py` in-process.

**Fix:**
```python
# Capture the backend to allow disposal, or use a lazy property:
_backend = SqlBackend(SqlSettings.default())
target_metadata = _backend.metadata
# _backend.engine is disposed when the module is unloaded (GC), which is acceptable
# for a migration entry-point; or explicitly: atexit.register(_backend.engine.dispose)

# Also correct the docstring:
# "the OPERATIONAL (Postgres) DB URL is resolved lazily inside the run functions;
#  the research default SQLite engine IS created at import for autogenerate."
```

---

### WR-06: FL-06 grep gate patterns are too narrow — common credential forms are not caught

**File:** `tests/unit/price_handler/test_sql_handler.py:137-145`
**Issue:** `_hardcoded_credential_patterns()` returns only `["user:pass@", ":1234@"]`. These patterns catch only the literal strings used to construct them. Common real credential patterns are missed:

- `admin:secret@` — not caught (`admin` ≠ `user`)
- `postgres:password@localhost` — not caught
- `root:root@` — not caught
- A URL like `postgresql://dbuser:dbpass@localhost:5432/db` only matches if `dbuser` starts with `user` and the port starts with `1234`

A git-history credential like `postgresql://itrader:itrader123@localhost:5432/prices` (a realistic development URL) would pass the gate entirely.

**Fix:** Broaden the patterns to cover the structural credential embedding in a URL (any `:password@host` form) rather than specific strings:
```python
def _hardcoded_credential_patterns() -> list[str]:
    # Match the structural shape of embedded creds in a connection URL:
    # "<user>:<pass>@<host>" — the "@" preceded by a non-whitespace segment containing ":"
    # Assembled from fragments to avoid self-tripping the gate.
    colon_at = ":" + "@"  # catches any "<pass>@" immediately after a colon
    # Supplement with the port-free shape: "//word:word@"
    slash_cred = "//" + "user" + colon_at   # keep original
    return [slash_cred, colon_at + "localhost", colon_at + "127.0.0.1", ":" + "1234" + "@"]
```

Or replace the bespoke scan with a regex that matches the structural `://[^:]+:[^@]+@` credential embedding pattern.

---

## Info

### IN-01: `render_as_string(hide_password=False)` in migration test — unmasked credential URL in test code

**File:** `tests/integration/storage/test_migrations.py:97`
**Issue:** `engine.url.render_as_string(hide_password=False)` renders the testcontainers database URL with the password in plaintext before passing it to `_alembic_config(url)`. The password is a randomly generated container credential (throwaway, not a production secret), so the immediate risk is low. However, this establishes a pattern of handling unmasked credential strings in test code that could be copied to contexts where the URL is a real credential (e.g., if the test fixture is adapted for a shared CI database).

**Fix:** If the testcontainers `Engine` URL must be passed as a string to Alembic, prefer `render_as_string(hide_password=True)` and only unmask if Alembic cannot connect with a masked URL (which it cannot — it needs the real credentials). The actual fix is to prefer passing the URL via `engine` directly to Alembic where possible, or at least add a comment documenting that this is a throwaway container password and must never be adapted for a shared real credential.

---

### IN-02: `from typing import List` — deprecated alias used in Python 3.13 target module

**File:** `itrader/results/base.py:23`
**Issue:** `from typing import Any, List` imports the deprecated `typing.List` alias. Python 3.9+ (and especially the project's Python 3.13 target) prefers built-in `list[...]`. CLAUDE.md explicitly states "Modern union syntax preferred." `mypy --strict` accepts both, but `typing.List` is scheduled for removal in a future Python release.

**Fix:**
```python
# Replace:
from typing import Any, List

# With:
from typing import Any

# And update the signature:
def top_runs(self, metric: str, n: int) -> list[Any]:
```

---

_Reviewed: 2026-06-27_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_

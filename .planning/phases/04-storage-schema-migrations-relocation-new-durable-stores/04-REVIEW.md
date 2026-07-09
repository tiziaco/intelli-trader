---
phase: 04-storage-schema-migrations-relocation-new-durable-stores
reviewed: 2026-07-09T00:00:00Z
depth: standard
files_reviewed: 12
files_reviewed_list:
  - itrader/storage/engine.py
  - itrader/storage/strategy_registry_store.py
  - itrader/storage/system_store.py
  - itrader/storage/venue_store.py
  - migrations/env.py
  - migrations/versions/strategy_registry.py
  - migrations/versions/system_store.py
  - migrations/versions/venue_config.py
  - tests/integration/storage/test_migrations.py
  - tests/integration/test_okx_inertness.py
  - tests/unit/storage/test_strategy_registry_store.py
  - tests/unit/storage/test_system_store.py
  - tests/unit/storage/test_venue_store.py
findings:
  critical: 0
  warning: 3
  info: 3
  total: 6
status: issues_found
---

# Phase 4: Code Review Report

**Reviewed:** 2026-07-09T00:00:00Z
**Depth:** standard
**Files Reviewed:** 12
**Status:** issues_found

## Summary

Reviewed the storage-spine additions for Phase 4: three new durable stores
(`SystemStore`, `VenueStore`, `StrategyRegistryStore`), their Alembic revisions, the
`migrations/env.py` autogen wiring, and the unit/integration test suite. Supporting files
(`itrader/storage/__init__.py`, `itrader/storage/types.py`, `itrader/config/sql.py`, the
full migration chain, `alembic.ini`) were read as cross-references.

The phase's hard gates are met and verified against source:

- **SEC-01** — all SQL is parameterized SQLAlchemy Core against constant `Table` objects; no
  f-string/interpolated SQL. `alembic.ini` `sqlalchemy.url` is blank (no committed credential).
- **D-06 natural PKs** — `key`, `venue_name`, `strategy_name`, and the composite
  `(strategy_name, venue, symbol, timeframe)` are natural PKs; no surrogate UUID / autoincrement.
- **D-05 recursion** — `_assert_no_secret_keys` correctly recurses through nested dicts AND
  lists-of-dicts at any depth, fires before the delete-then-insert (verified by three tests).
- **Migrations** — all three revisions import `itrader.storage.types` + `sqlalchemy.dialects.postgresql`,
  wrap PK/FK names in `op.f(...)` with names byte-identical to `NAMING_CONVENTION`, and chain
  linearly to a single head (`strategy_registry`).
- **Inertness** — `migrations/env.py` and the registrars build only `Table` objects on a bare
  `MetaData` (no Engine/Settings/connection at import); the subprocess probe forbids the three
  store modules on the backtest path.
- **Indentation** — all 12 files are 4-space, no tabs. Stores `dispose()` delegates to
  `backend.dispose()` (clean `filterwarnings=["error"]` teardown).

No blockers found. Three warnings concern robustness/portability gaps that are latent today
because the real deploy target is Postgres and the primary D-05 protection is structural.

## Warnings

### WR-01: Secret denylist uses exact key membership — compound/camelCase secret keys slip through

**File:** `itrader/storage/venue_store.py:39-72`
**Issue:** `_assert_no_secret_keys` matches `key.lower() in _SECRET_KEY_DENYLIST` where the
denylist is a frozenset of exact tokens (`api_key`, `secret`, `secret_key`, `private_key`,
`token`, `access_token`, ...). Because it is exact equality, common credential key names that
are compounds or camelCase-without-underscore are **not** caught:

- `client_secret` → `"client_secret"` not in set
- `secretKey` → `"secretkey"` not in set (set has `secret_key`)
- `privateKey` → `"privatekey"` not in set (set has `private_key`)
- `api_secret` / `apiSecret` → not in set
- `auth_token` → not in set (`token` is an exact-match token, not a substring)

The ccxt-native OKX case (`apiKey`→`apikey`, `secret`, `password`) *is* covered, and D-05's
primary requirement (recursion depth) is correctly met, so this is a defense-in-depth
robustness gap rather than a live exposure — the structural arm (credentials are connector-owned
`SecretStr`, never passed here) is the real protection. Still, a security guard that silently
passes `client_secret` gives false confidence.

**Fix:** Match on substring/token-boundary rather than exact equality, e.g.:
```python
_SECRET_MARKERS = ("secret", "api_key", "apikey", "password", "passphrase",
                   "token", "private_key", "privatekey", "credential")

def _is_secret_key(key: str) -> bool:
    lowered = key.lower()
    return any(marker in lowered for marker in _SECRET_MARKERS)
```
This catches `client_secret`, `secretKey`, `aws_secret_access_key`, etc. (false-positives are
documented as safe — "a false-positive is a loud, safe failure").

### WR-02: SQLite FK on `strategy_subscriptions` is declared but never enforced (no `PRAGMA foreign_keys=ON`)

**File:** `itrader/storage/strategy_registry_store.py:78-88, 143-178`
**Issue:** SQLite ignores `FOREIGN KEY` constraints unless `PRAGMA foreign_keys=ON` is set
per-connection, and no such pragma / `event.listen` is configured anywhere in `itrader/storage/`
(grep confirms zero occurrences). Consequences:

1. `set_subscriptions(name, ...)` for a `strategy_name` with **no** registry row silently
   inserts orphan child rows on SQLite, while Postgres rejects the INSERT with an FK violation
   (the enclosing `engine.begin()` rolls back). The two backends diverge in behavior.
2. Every unit test runs on SQLite, so the FK integrity the schema declares is **never actually
   exercised** — `test_delete_removes_registry_and_subscriptions` and the restart-survival test
   pass on SQLite regardless of whether FK enforcement works.

The `delete()` child-first ordering (documented "FK child order") is only meaningful on the
Postgres deploy target; on the SQLite test double it is a no-op distinction.

**Fix:** Enable FK enforcement on SQLite connections so the tests validate the real constraint
and the two backends match:
```python
from sqlalchemy import event

@event.listens_for(self.engine, "connect")
def _fk_pragma(dbapi_conn, _):
    if self.engine.dialect.name == "sqlite":
        dbapi_conn.execute("PRAGMA foreign_keys=ON")
```
(Alternatively, add an explicit test that `set_subscriptions` on an unknown strategy raises,
to pin the intended cross-backend contract.)

### WR-03: `create_all(checkfirst=True)` in store `__init__` runs unconditionally — can create un-migrated tables on live Postgres

**File:** `itrader/storage/system_store.py:74`, `itrader/storage/venue_store.py:117`, `itrader/storage/strategy_registry_store.py:110`
**Issue:** Each store constructor calls `sql_engine.metadata.create_all(self.engine, checkfirst=True)`
with no environment guard. The docstrings assert "the live path migrates via Alembic; create_all
is the test / no-op-if-present path" — but the code does not distinguish paths. On a **live
Postgres** engine where the migration chain has *not* been applied, `create_all` will directly
create `system_store` / `venue_store` / `strategy_registry` / `strategy_subscriptions` **without**
stamping `alembic_version`. A subsequent `alembic upgrade head` then hits `op.create_table` on an
already-existing table (DuplicateTable), or the ops team silently runs on a schema Alembic
believes it never created — schema drift on the durable operational store the migrations are
supposed to own.

This is inherited from the accepted `HaltRecordStore` template and is harmless when migrations
run first (checkfirst no-ops), so it is a latent operational hazard, not a live bug — but on the
*durable* store the create_all path arguably shouldn't exist at all.

**Fix:** Gate schema creation on the SQLite/test arm, or drive it off an explicit flag, so the
Postgres operational store is Alembic-owned end-to-end:
```python
if self.engine.dialect.name == "sqlite":
    sql_engine.metadata.create_all(self.engine, checkfirst=True)
```

## Info

### IN-01: `read_all` (strategy registry) has no `ORDER BY` — group/row order is DB-dependent

**File:** `itrader/storage/strategy_registry_store.py:245-286`
**Issue:** The rehydrate JOIN `select(...).select_from(join)` has no `ORDER BY`, so both the
returned record order and the per-strategy `subscriptions` list order are whatever the backend
returns (unspecified). Tests tolerate this by re-keying into a dict and comparing sets, but any
future caller that assumes stable ordering (or a golden/byte-exact comparison) would be flaky.
`strategies_subscribed_to` and `list_active` in the same file do the right thing (`.order_by(...)`
/ deterministic filter). **Fix:** add `.order_by(self.strategy_registry.c.strategy_name.asc())`
(and a secondary sort on the subscription columns) for a deterministic rehydrate.

### IN-02: `SystemStore.value_json` / `StrategyRegistryStore.config_json` have no secret-scrub guard

**File:** `itrader/storage/system_store.py:81-96`, `itrader/storage/strategy_registry_store.py:117-141`
**Issue:** Only `VenueStore` carries the D-05 `_assert_no_secret_keys` guard. `SystemStore`
persists arbitrary `runtime_config` blobs and `StrategyRegistryStore` persists arbitrary strategy
`config` — either could carry a credential in a future caller with no defense-in-depth net. D-05
is scoped to VenueStore for this phase, so this is a note, not a violation. **Fix (optional):**
factor the recursive denylist walk into a shared `itrader/storage` helper and apply it to any
store that accepts caller-supplied JSON.

### IN-03: Three near-identical store clones — duplication is documented but real

**File:** `itrader/storage/system_store.py`, `itrader/storage/venue_store.py`, `itrader/storage/strategy_registry_store.py`
**Issue:** `__init__` (backend/engine/table/create_all/logger), `dispose`, the delete-then-insert
upsert, `get`, `delete`, and `read_all` are structurally duplicated across all three stores
(each labeled "a disciplined clone of the HaltRecordStore template"). This is a deliberate design
choice (per-concern ABC boundary over a shared base), so no change is required — but the
`_row_to_dict` helper pattern in `VenueStore` could be lifted to remove the repeated inline dict
projections in the other two, reducing drift risk if the row shape ever changes.

---

_Reviewed: 2026-07-09T00:00:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_

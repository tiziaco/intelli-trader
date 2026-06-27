---
phase: 01-sql-spine-security-hardening
plan: 02
type: execute
wave: 1
depends_on: []
files_modified:
  - itrader/storage/__init__.py
  - itrader/storage/types.py
  - itrader/storage/backend.py
  - itrader/config/sql.py
  - tests/unit/storage/__init__.py
  - tests/unit/storage/test_types.py
  - tests/unit/storage/test_sql_settings.py
  - tests/unit/storage/test_sql_backend.py
autonomous: true
requirements: [SPINE-01, SPINE-02, SPINE-03, GATE-02]

must_haves:
  truths:
    - "A developer selects SQLite vs Postgres by SqlSettings/SqlDriver alone — no storage code change; the surface is minimal (driver enum + engine_url builder), write-through/retention knobs deferred to Phase 4 (SPINE-01, D-12)"
    - "SqlSettings lives in config/sql.py (Pydantic, consuming Settings.database_url: SecretStr) at 4-space indentation matching config/ and core/ (D-02)"
    - "The driver enum carries a Turso-ready `sqlite+libsql` slot but the sqlalchemy-libsql driver is NOT added — the escape path is one URL change, zero code (D-15)"
    - "A single shared SqlBackend (Engine + MetaData, no business logic) is composed not inherited — there is NO SqlStorageBase god class (SPINE-02, D-01)"
    - "types.py carries Uuid(as_uuid=True) usage, the UtcIsoText TypeDecorator, and json_variant() — and NO DecimalAsText (money never touches SQLite this milestone) (D-13)"
    - "A business-time datetime encodes to identical UTC-isoformat TEXT bytes across two runs and round-trips instant-equal on in-process SQLite (SPINE-03 encoding/determinism, D-04, D-05)"
    - "Settings() is never instantiated at import time; database_url is resolved lazily on the Postgres arm only (Pitfall 8)"
    - "new spine code is mypy --strict clean (GATE-02, D-16)"
  artifacts:
    - path: "itrader/storage/types.py"
      provides: "UtcIsoText TypeDecorator + json_variant() + Uuid usage; NO DecimalAsText"
      contains: "class UtcIsoText"
    - path: "itrader/config/sql.py"
      provides: "SqlSettings (SqlDriver enum incl. libsql slot + engine_url builder, lazy Settings)"
      contains: "class SqlSettings"
    - path: "itrader/storage/backend.py"
      provides: "SqlBackend = Engine + MetaData, no business logic"
      contains: "class SqlBackend"
  key_links:
    - from: "itrader/config/sql.py::SqlSettings.engine_url"
      to: "itrader.config.settings.Settings.database_url.get_secret_value()"
      via: "lazy resolution on the POSTGRESQL_PSYCOPG2 arm only"
      pattern: "get_secret_value"
    - from: "itrader/storage/backend.py::SqlBackend.__init__"
      to: "sqlalchemy.create_engine"
      via: "create_engine(settings.engine_url())"
      pattern: "create_engine"
---

<objective>
Build the SQL spine — the hard dependency root nothing else in v1.6 compiles without. Ship
`itrader/storage/` (`types.py` cross-dialect helpers, `backend.py` SqlBackend, barrel `__init__`) and
`config/sql.py` (`SqlSettings`). Backend is selected by config, never code; a single SqlBackend is
*composed* by every storage concern (no god base); UUIDv7 ids and business-time encode losslessly and
deterministically.

Purpose: SPINE-01 (config-not-code backend selection), SPINE-02 (composition spine, no cross-concern god
base), SPINE-03 (lossless/deterministic encoding) all live here. Phase 1 adds ZERO per-tick code — the
spine is post-loop/live-only (GATE-01 inertness is structural).
Output: `itrader/storage/{__init__,types,backend}.py`, `itrader/config/sql.py`, and unit tests proving
encoding determinism, driver-by-config selection, and composition-not-inheritance.
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/execute-plan.md
@$HOME/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/PROJECT.md
@.planning/phases/01-sql-spine-security-hardening/01-CONTEXT.md
@.planning/phases/01-sql-spine-security-hardening/01-RESEARCH.md
@.planning/phases/01-sql-spine-security-hardening/01-PATTERNS.md
@itrader/config/settings.py
@itrader/config/order.py

<interfaces>
<!-- Cred source (config/settings.py:37-39) — required-no-default SecretStr; read ONLY via .get_secret_value() -->
```python
class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ITRADER_", extra="ignore")
    database_url: SecretStr   # NO default -> ValidationError if instantiated without ITRADER_DATABASE_URL
```

<!-- VERIFIED encodings (SQLAlchemy 2.0.50) the spine assembles — see RESEARCH.md Pattern 2 / Code Examples -->
<!--   Uuid(as_uuid=True)            -> CHAR(32) on SQLite, native UUID on PG; uuid.UUID == uuid.UUID across dialects -->
<!--   UtcIsoText(TypeDecorator)     -> normalize to UTC then datetime.isoformat(); fromisoformat() on read; cache_ok=True REQUIRED -->
<!--   JSON().with_variant(JSONB(),"postgresql") -> JSON on SQLite, JSONB on PG -->

<!-- Config-model analog (config/order.py:48-63): BaseModel + ConfigDict(extra="forbid") + default() classmethod; (str,Enum) members with explicit string values -->
</interfaces>
</context>

<tasks>

<task type="auto" tdd="true">
  <name>Task 1: storage/types.py — cross-dialect helpers (UtcIsoText, json_variant, Uuid); NO DecimalAsText</name>
  <files>itrader/storage/types.py, tests/unit/storage/__init__.py, tests/unit/storage/test_types.py</files>
  <read_first>
    - .planning/phases/01-sql-spine-security-hardening/01-RESEARCH.md → "Pattern 2: types.py cross-dialect helpers (D-13 shape)" + "Code Examples" (the VERIFIED transcripts)
    - .planning/phases/01-sql-spine-security-hardening/01-PATTERNS.md → "itrader/storage/types.py" (green-field; NO DecimalAsText; business-time is tz-aware datetime, microsecond max → ISO-8601-UTC-text is lossless)
    - INDENTATION: itrader/storage/ (NEW) and tests/unit/* = 4 SPACES (verified).
  </read_first>
  <behavior>
    - UtcIsoText.process_bind_param(aware datetime) returns the same UTC-normalized isoformat string on two separate calls (determinism — identical bytes).
    - A datetime written through UtcIsoText into an in-memory SQLite column reads back instant-equal (aware UTC), including a non-UTC input (e.g. +01:00) normalized to +00:00.
    - json_variant() compiles to JSON on the sqlite dialect and JSONB on the postgresql dialect.
    - Uuid(as_uuid=True) compiles to CHAR(32) on sqlite; a uuid_utils.compat.uuid7() round-trips through a SQLite column as an equal uuid.UUID.
    - There is NO DecimalAsText / money TypeDecorator anywhere in the module.
  </behavior>
  <action>
    Create `itrader/storage/types.py` (4-space). Define: a module-level `Uuid(as_uuid=True)` usage note/alias (use `sqlalchemy.Uuid(as_uuid=True)` directly at columns — do NOT hand-roll a per-dialect switch); a `UtcIsoText(TypeDecorator[datetime])` whose `impl = String`, `cache_ok = True`, `process_bind_param` returns `value.astimezone(timezone.utc).isoformat()` (None passthrough), and `process_result_value` returns `datetime.fromisoformat(value)` (None passthrough); and a `json_variant() -> JSON` returning `JSON().with_variant(JSONB(), "postgresql")`. Do NOT define `DecimalAsText` or any money type (D-13 — money never lands on SQLite this milestone). Write `tests/unit/storage/__init__.py` (empty) and `tests/unit/storage/test_types.py` asserting the five behaviors above against an in-process `sqlite+pysqlite:///:memory:` engine + `dialect.type_descriptor`/compile checks.
  </action>
  <verify>
    <automated>poetry run pytest tests/unit/storage/test_types.py -x && poetry run mypy itrader/storage/types.py</automated>
  </verify>
  <acceptance_criteria>
    - `tests/unit/storage/test_types.py` passes (all five behaviors green) including the determinism byte-equality assertion.
    - `! grep -n 'DecimalAsText\|Numeric' itrader/storage/types.py` (no money type — D-13).
    - `grep -n 'cache_ok = True' itrader/storage/types.py` present (mypy-strict + SQLAlchemy caching).
    - `poetry run mypy itrader/storage/types.py` clean (GATE-02).
  </acceptance_criteria>
  <done>types.py exports UtcIsoText + json_variant + the Uuid usage with no money type; tests + mypy green.</done>
</task>

<task type="auto" tdd="true">
  <name>Task 2: config/sql.py — SqlSettings (driver-by-config, libsql slot, lazy creds)</name>
  <files>itrader/config/sql.py, tests/unit/storage/test_sql_settings.py</files>
  <read_first>
    - itrader/config/order.py:22-63 (the BaseModel + ConfigDict(extra="forbid") + default() + (str,Enum) analog)
    - itrader/config/settings.py:1-39 (the SecretStr cred source + the import-side-effect docstring — database_url is required-no-default)
    - .planning/phases/01-sql-spine-security-hardening/01-RESEARCH.md → "Pattern 3: Minimal SqlSettings" + the `Settings()` import-side-effect trap note (Pitfall 8 — resolve lazily on the PG arm only)
    - INDENTATION: config/ = 4 SPACES.
  </read_first>
  <behavior>
    - SqlSettings() defaults to the SQLITE_PYSQLITE driver and a `:memory:` database; engine_url() returns a `sqlite+pysqlite:///:memory:` URL with NO env access (backtest path stays env-free).
    - SqlDriver carries exactly three members: SQLITE_PYSQLITE, POSTGRESQL_PSYCOPG2, and the unwired SQLITE_LIBSQL slot ("sqlite+libsql") — Turso-ready, driver not installed.
    - On the POSTGRESQL_PSYCOPG2 arm, engine_url() resolves credentials via Settings.database_url.get_secret_value() — and importing config/sql.py does NOT instantiate Settings() (no ValidationError when ITRADER_DATABASE_URL is unset).
    - extra keys are forbidden (mass-assignment defense).
  </behavior>
  <action>
    Create `itrader/config/sql.py` (4-space). Define `SqlDriver(str, Enum)` with `SQLITE_PYSQLITE = "sqlite+pysqlite"`, `POSTGRESQL_PSYCOPG2 = "postgresql+psycopg2"`, `SQLITE_LIBSQL = "sqlite+libsql"` (SLOT only — D-15, driver NOT added). Define `SqlSettings(BaseModel)` with `model_config = ConfigDict(extra="forbid")`, fields `driver: SqlDriver = SqlDriver.SQLITE_PYSQLITE` and `database: str = ":memory:"`, a `default()` classmethod, and `engine_url(self, settings: Settings | None = None) -> str` that returns `(settings or Settings()).database_url.get_secret_value()` ONLY on the POSTGRESQL_PSYCOPG2 arm and `f"{self.driver.value}:///{self.database}"` otherwise. Do NOT instantiate `Settings()` at module import. Do NOT add write-through/retention knobs (deferred to Phase 4 — D-12). Write `tests/unit/storage/test_sql_settings.py` asserting the four behaviors (use `monkeypatch.setenv("ITRADER_DATABASE_URL", ...)` to exercise the PG arm; assert the SQLite arm needs no env; assert the libsql slot exists).
  </action>
  <verify>
    <automated>poetry run pytest tests/unit/storage/test_sql_settings.py -x && poetry run mypy itrader/config/sql.py</automated>
  </verify>
  <acceptance_criteria>
    - `tests/unit/storage/test_sql_settings.py` passes, including a test that imports `itrader.config.sql` with `ITRADER_DATABASE_URL` unset and asserts no ValidationError (lazy resolution).
    - `grep -n 'SQLITE_LIBSQL' itrader/config/sql.py` present (Turso-ready slot, D-15).
    - `! grep -n 'sqlalchemy_libsql\|sqlalchemy-libsql' itrader/` (driver NOT added).
    - SQLite-arm engine_url() asserted env-free; PG-arm asserted to call get_secret_value().
    - `poetry run mypy itrader/config/sql.py` clean.
  </acceptance_criteria>
  <done>SqlSettings selects the driver by config, resolves PG creds lazily from SecretStr, carries the libsql slot; tests + mypy green.</done>
</task>

<task type="auto" tdd="true">
  <name>Task 3: storage/backend.py + barrel — SqlBackend (Engine + MetaData), no god base</name>
  <files>itrader/storage/backend.py, itrader/storage/__init__.py, tests/unit/storage/test_sql_backend.py</files>
  <read_first>
    - .planning/phases/01-sql-spine-security-hardening/01-RESEARCH.md → "Pattern 1: The spine via composition" + "backend.py" (SqlBackend = Engine + MetaData, NO business logic; NO SqlStorageBase god class)
    - .planning/phases/01-sql-spine-security-hardening/01-PATTERNS.md → "Barrel __init__.py with quarantine note" (price_handler/store/__init__.py:1-14 idiom)
    - INDENTATION: itrader/storage/ = 4 SPACES.
  </read_first>
  <behavior>
    - SqlBackend(SqlSettings()) over the default SQLite settings exposes `.engine` (a SQLAlchemy Engine bound to the resolved URL) and `.metadata` (a fresh MetaData) and holds NO business/query logic.
    - A throwaway concrete storage class can COMPOSE a SqlBackend (has-a) and create a Table on backend.metadata without inheriting any shared storage base — there is no SqlStorageBase symbol to import.
    - `itrader.storage` re-exports SqlBackend and the type helpers; importing the barrel does NOT import price_handler's quarantined sql_store and does NOT touch the env.
  </behavior>
  <action>
    Create `itrader/storage/backend.py` (4-space) with `class SqlBackend` whose `__init__(self, settings: SqlSettings) -> None` sets `self.engine: Engine = create_engine(settings.engine_url())` and `self.metadata = MetaData()` — NO query methods, NO god base. Create `itrader/storage/__init__.py` re-exporting `SqlBackend`, `UtcIsoText`, `json_variant` (and the Uuid usage note) via `__all__`. Write `tests/unit/storage/test_sql_backend.py` asserting the three behaviors, including an explicit assertion that NO `SqlStorageBase`/cross-concern god class exists (e.g. a sample `class _DemoStore` composes `SqlBackend` without subclassing it) — SPINE-02.
  </action>
  <verify>
    <automated>poetry run pytest tests/unit/storage/test_sql_backend.py -x && poetry run mypy itrader/storage</automated>
  </verify>
  <acceptance_criteria>
    - `tests/unit/storage/test_sql_backend.py` passes; the composition (has-a, not is-a) assertion is explicit.
    - `! grep -rn 'class SqlStorageBase\|SqlStorage(ABC)' itrader/storage/` (no cross-concern god base — D-01/SPINE-02).
    - `python -c "import itrader.storage"` succeeds with `ITRADER_DATABASE_URL` unset (barrel is env-free).
    - `poetry run mypy itrader/storage` clean (GATE-02).
  </acceptance_criteria>
  <done>SqlBackend exists as the composable Engine+MetaData spine; barrel re-exports the public surface; no god base; tests + mypy green.</done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| config/env (ITRADER_DATABASE_URL) → SqlSettings/SqlBackend | DB credentials (SecretStr) cross into engine construction |
| module import → process | Eager Settings() at import would couple every importer to a required secret |

## STRIDE Threat Register

| Threat ID | Category | Component | Disposition | Mitigation Plan |
|-----------|----------|-----------|-------------|-----------------|
| T-01-03 | Information Disclosure | SqlSettings.engine_url (PG arm) | mitigate | Creds resolved ONLY via Settings.database_url.get_secret_value(); SecretStr masks repr/str/model_dump; the resolved URL is never logged |
| T-01-04 | Denial of Service | config/sql.py / storage import | mitigate | No Settings() at import time (Pitfall 8) — resolve lazily on the PG arm; the SQLite/backtest path stays env-free so an unset ITRADER_DATABASE_URL can't break import |
| T-01-05 | Tampering | SqlBackend.create_engine | accept | The spine has no untrusted input on the backtest path; backend is selected at wiring from config, not from request data |
| T-01-06 | Tampering | second ID scheme / DB autoincrement | mitigate | No Integer primary_key / autoincrement introduced; UUIDv7 from idgen remains the single scheme (Uuid type only) |
</threat_model>

<verification>
- `poetry run pytest tests/unit/storage -x` green (types determinism, driver-by-config, composition-no-god-base).
- `poetry run mypy itrader/storage itrader/config/sql.py` clean (GATE-02; new code is auto-in-scope, no override).
- `! grep -rn 'DecimalAsText' itrader/` (D-13) and `! grep -rn 'sqlalchemy.libsql\|sqlalchemy_libsql' itrader/` (D-15).
- GATE-01 (recurring, inert): spine adds no per-tick code — `poetry run pytest tests/integration/test_backtest_oracle.py -x` byte-exact 134 / `46189.87730727451`.
</verification>

<success_criteria>
- A developer swaps SQLite⇄Postgres by changing SqlSettings/SqlDriver alone — no storage code change (SPINE-01).
- A single SqlBackend is composed by storage concerns with no cross-concern god base (SPINE-02).
- UUIDv7 + business-time encode losslessly and deterministically via types.py (SPINE-03 encoding half).
- New spine code is mypy --strict clean and the suite is green under filterwarnings=["error"] (GATE-02).
</success_criteria>

<output>
Create `.planning/phases/01-sql-spine-security-hardening/01-02-SUMMARY.md` when done.
</output>

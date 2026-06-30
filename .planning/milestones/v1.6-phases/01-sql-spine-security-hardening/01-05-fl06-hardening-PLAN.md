---
phase: 01-sql-spine-security-hardening
plan: 05
type: execute
wave: 2
depends_on: [01-01, 01-02]
files_modified:
  - itrader/price_handler/store/sql_store.py
  - pyproject.toml
  - tests/unit/price_handler/__init__.py
  - tests/unit/price_handler/test_sql_handler.py
autonomous: true
requirements: [SEC-01, GATE-02]

must_haves:
  truths:
    - "SqlHandler sources DB credentials from Settings.database_url.get_secret_value() — no hardcoded `user:pass@` / `:1234@` anywhere in itrader/ (SEC-01, D-08; FL-06 L17 closed)"
    - "Symbol-as-table-name is eliminated — one `prices` table with a `symbol` VALUE column; all reads/writes/deletes are parameterized (bound params / literal table name), no dynamic SQL identifiers (SEC-01, D-07; FL-06 L56/58/69 closed)"
    - "No f-string lives inside text() — the DROP TABLE injection vector is removed via constant/parameterized Core constructs (SEC-01, D-08; FL-06 L35 closed)"
    - "SqlHandler composes the shared SqlBackend as the 5th spine consumer (full migration onto the spine, not minimal in-place hardening) (D-06)"
    - "sql_store.py exits the D-sql mypy override and is mypy --strict clean; no new broad ignore is added; the resolved secret URL is never logged (GATE-02, D-09)"
  artifacts:
    - path: "itrader/price_handler/store/sql_store.py"
      provides: "reworked SqlHandler on the spine — single prices table, SecretStr creds, parameterized"
      contains: "get_secret_value"
    - path: "pyproject.toml"
      provides: "sql_store removed from the D-sql ignore_errors override"
    - path: "tests/unit/price_handler/test_sql_handler.py"
      provides: "SEC-01 behavior + FL-06 grep gates"
      contains: "prices"
  key_links:
    - from: "itrader/price_handler/store/sql_store.py::SqlHandler"
      to: "itrader.storage.SqlBackend (engine + metadata)"
      via: "composition (constructor injection of the shared backend)"
      pattern: "SqlBackend"
    - from: "itrader/price_handler/store/sql_store.py"
      to: "the single `prices` Table"
      via: "select/insert/delete with bindparam(symbol) — never f-string identifiers"
      pattern: "prices"
---

<objective>
Close FL-06 / SEC-01: rework `SqlHandler` (`price_handler/store/sql_store.py`) onto the new SQL spine.
Kill the three confirmed vulnerabilities — hardcoded creds (L17), f-string `DROP TABLE` injection (L35),
and symbol-as-table-name dynamic-identifier injection (L56/58/69) — by composing `SqlBackend`, sourcing
creds from `Settings.database_url` (SecretStr), and collapsing table-per-symbol into one parameterized
`prices` table with a `symbol` VALUE column. Lift the reworked file into `mypy --strict` (D-09).

Purpose: this is the security-bearing plan of the phase. The grep gates (no `user:pass@`, no `text(f'`)
must go from RED to GREEN, and the only file matching them today (`sql_store.py`) is hardened.
Output: reworked `sql_store.py` (full 4-space rewrite, D-06), the pyproject mypy-override removal, and a
unit test proving single-table parameterized behavior + the FL-06 grep gates.
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/execute-plan.md
@$HOME/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/phases/01-sql-spine-security-hardening/01-RESEARCH.md
@.planning/phases/01-sql-spine-security-hardening/01-PATTERNS.md
@.planning/phases/01-sql-spine-security-hardening/01-VALIDATION.md
@itrader/price_handler/store/sql_store.py
@itrader/price_handler/store/__init__.py
@itrader/config/settings.py

<interfaces>
<!-- The three vulns to remove (sql_store.py, current) — DESCRIBE them in any new comment, never reproduce the literal vulnerable strings (the grep gates scan all of itrader/): -->
<!--   L17  hardcoded creds: create_engine('postgresql+psycopg2://<user>:<pass>@localhost:5432/trading_system_prices') -->
<!--   L35  f-string DDL:     text(f'DROP TABLE IF EXISTS {sym};')  -> injection -->
<!--   L56/58 write:          prices.to_sql(symbol.lower(), engine, if_exists='replace'|'append')  -> dynamic identifier -->
<!--   L69  read:             pd.read_sql(symbol, connection, index_col='date')                     -> dynamic identifier -->

<!-- Replacement shape (RESEARCH Pattern 4 / PATTERNS): single `prices` Table on backend.metadata -->
```python
prices = Table(
    "prices", backend.metadata,
    Column("symbol", String, primary_key=True),
    Column("date",   UtcIsoText, primary_key=True),   # business-time, uniform encoding (storage/types.py)
    Column("open", Float), Column("high", Float), Column("low", Float),
    Column("close", Float), Column("volume", Float),
)
# read:   select(prices).where(prices.c.symbol == bindparam("symbol"))   # bound param, never f-string
# purge:  prices.delete().where(prices.c.symbol == bindparam("symbol"))  # or DROP TABLE prices (constant)
# write:  literal table name "prices" + a symbol value column (injection-safe)
```
<!-- OHLCV is analytical market data (pandas float64) -> Float columns, NOT money-policy Decimal (D-13: money never touches SQLite). -->
<!-- Preserve: self.logger = get_itrader_logger().bind(component="SQLHandler"); NEVER log the resolved secret URL. -->
<!-- Preserve the quarantine: do NOT add sql_store to price_handler/store/__init__.py (it pulls sqlalchemy). -->
</interfaces>
</context>

<tasks>

<task type="auto">
  <name>Task 1: Rework SqlHandler onto the spine — single prices table, SecretStr creds, parameterized</name>
  <files>itrader/price_handler/store/sql_store.py</files>
  <read_first>
    - itrader/price_handler/store/sql_store.py (the FULL current file — the rework target; TABS today)
    - .planning/phases/01-sql-spine-security-hardening/01-PATTERNS.md → "price_handler/store/sql_store.py — FL-06 rework" (Vuln 1/2/3 with exact lines + the replacement shape; the indentation decision D-06)
    - .planning/phases/01-sql-spine-security-hardening/01-RESEARCH.md → "Pattern 4" + "State of the Art" table
    - itrader/storage/types.py + itrader/storage/backend.py (from 01-02 — UtcIsoText, SqlBackend)
    - INDENTATION DECISION (D-06, pinned): the file is TABS today and is being FULLY REWRITTEN (every line replaced) — write it as a uniform 4-SPACE file to match the 4-space spine it now composes. This is a complete replacement, so no tab/space MIX is produced (Pitfall 5 avoided). No surviving tab-indented line is permitted.
  </read_first>
  <action>
    Rewrite `itrader/price_handler/store/sql_store.py` in full (uniform 4-space). `SqlHandler.__init__(self, backend: SqlBackend) -> None` composes the injected shared `SqlBackend` (5th consumer, D-06) — use `backend.engine` and `backend.metadata`; do NOT call `create_engine` with any hardcoded URL and do NOT use `sqlalchemy_utils.database_exists`/`create_database`. Define the single `prices` `Table` on `backend.metadata` (columns: `symbol` String PK, `date` UtcIsoText PK, `open`/`high`/`low`/`close`/`volume` Float — analytical Float, NOT Decimal). Implement: `to_database(symbol, prices_df, replace)` writing to the literal `"prices"` table with `symbol` as a value column (on replace, parameterized `prices.delete().where(prices.c.symbol == bindparam("symbol"))` then append); `read_prices(symbol)` via `select(prices).where(prices.c.symbol == bindparam("symbol"))`; `get_symbols()` via `select(prices.c.symbol).distinct()`; and a `delete_prices(symbol=None)` that is a parameterized delete or the constant `DROP TABLE prices` (never a built identifier). Remove `get_symbols_SQL`/`delete_all_tables`/the f-string DDL entirely. Preserve `self.logger = get_itrader_logger().bind(component="SQLHandler")` and NEVER log the resolved secret URL. In any new comment/docstring, DESCRIBE the removed vulns without reproducing the literal `user:pass@` / `:1234@` / `text(f'` strings (the grep gates scan all of itrader/). Do NOT add `sql_store` to `price_handler/store/__init__.py` (preserve the quarantine).
  </action>
  <verify>
    <automated>poetry run python -c "import ast,sys; ast.parse(open('itrader/price_handler/store/sql_store.py').read()); print('parse ok')" && ! grep -nP '^\t' itrader/price_handler/store/sql_store.py</automated>
  </verify>
  <acceptance_criteria>
    - `! grep -nP '^\t' itrader/price_handler/store/sql_store.py` (uniform 4-space, no surviving tab-indented line — clean full rewrite).
    - `! grep -n "user:pass@\|:1234@" itrader/price_handler/store/sql_store.py` (hardcoded cred gone — L17 closed).
    - `! grep -n "text(f'\|text(f\"" itrader/price_handler/store/sql_store.py` (no f-string in text() — L35 closed).
    - `! grep -nE "to_sql\(symbol|read_sql\(symbol" itrader/price_handler/store/sql_store.py` (no symbol-as-identifier — L56/58/69 closed).
    - `grep -n "bindparam\|SqlBackend\|get_secret_value" itrader/price_handler/store/sql_store.py` present (parameterized + composes spine + creds-from-secret).
    - `grep -n 'bind(component="SQLHandler")' itrader/price_handler/store/sql_store.py` present (logger preserved).
    - `price_handler/store/__init__.py` does NOT import `sql_store` (quarantine preserved).
  </acceptance_criteria>
  <done>SqlHandler composes SqlBackend, uses one parameterized prices table, sources creds from SecretStr; all three FL-06 vulns removed; quarantine + logger preserved.</done>
</task>

<task type="auto">
  <name>Task 2: Lift sql_store into mypy --strict (remove D-sql override) + reconcile SYSTEM_DB_URL note</name>
  <files>pyproject.toml, itrader/price_handler/store/sql_store.py</files>
  <read_first>
    - pyproject.toml:88-99 (the D-sql ignore_errors override block — remove the `itrader.price_handler.store.sql_store` line ONLY; leave `postgresql_storage` and the D-live/D-oanda/D-screener entries untouched — Phase 3 owns those)
    - .planning/phases/01-sql-spine-security-hardening/01-RESEARCH.md → "Pitfall 7" + Open Question 3 (D-09 resolution) + Open Question 4 (SYSTEM_DB_URL reconciliation)
    - INDENTATION: pyproject.toml is TOML (no Python-indent hazard); sql_store.py = 4-space (from Task 1).
  </read_first>
  <action>
    In `pyproject.toml`, remove the single line `"itrader.price_handler.store.sql_store",  # D-sql` from the first `[[tool.mypy.overrides]]` module list — and do NOT add any new broad ignore (GATE-02). This is the SOLE pyproject.toml mypy edit in this phase (the alembic env.py in 01-04 stays strict-clean via inline `# type: ignore` if needed; it does not touch pyproject). Make the reworked `sql_store.py` `mypy --strict` clean: where pandas `.to_sql`/`read_sql` (pandas is `ignore_missing_imports`, so its symbols are `Any`) trips `no-untyped-call`/`no-any-return`, apply the NARROWEST possible `# type: ignore[<code>]` at exactly that pandas boundary line with a one-line justification — never a module-level or broad ignore. Add a short module docstring note that the canonical credential source is `Settings.database_url` (`ITRADER_DATABASE_URL`) and that the legacy `live_trading_system.py` `SYSTEM_DB_URL` env var is a separate D-live seam, reconciled-or-deferred to the live-wiring phase (do NOT add a third cred source here).
  </action>
  <verify>
    <automated>poetry run mypy itrader/price_handler/store/sql_store.py && ! grep -n "store.sql_store" pyproject.toml</automated>
  </verify>
  <acceptance_criteria>
    - `! grep -n "itrader.price_handler.store.sql_store" pyproject.toml` (the D-sql override line for sql_store is removed).
    - `poetry run mypy itrader/price_handler/store/sql_store.py` is clean (file is now in strict scope — GATE-02/D-09).
    - `poetry run mypy itrader` reports no NEW errors introduced by the override removal.
    - Any `# type: ignore` in sql_store.py is narrow (carries a `[code]`) and justified — no module-level/broad ignore added.
    - The SYSTEM_DB_URL reconciliation is documented (one canonical source; no third source wired).
  </acceptance_criteria>
  <done>sql_store.py is mypy --strict clean and out of the D-sql override; SYSTEM_DB_URL drift documented; no new broad ignore.</done>
</task>

<task type="auto">
  <name>Task 3: test_sql_handler.py — SEC-01 single-table behavior + FL-06 grep gates</name>
  <files>tests/unit/price_handler/__init__.py, tests/unit/price_handler/test_sql_handler.py</files>
  <read_first>
    - tests/unit/order/test_order_storage.py:1-29 (the storage-test idiom — module imports + fixture + public-API asserts)
    - .planning/phases/01-sql-spine-security-hardening/01-VALIDATION.md → SEC-01 rows (the two grep gates + the single-prices-table behavior)
    - itrader/price_handler/store/sql_store.py (from Task 1 — the reworked public surface) + itrader/storage/backend.py
    - INDENTATION: tests/unit/* = 4 SPACES.
  </read_first>
  <action>
    Create `tests/unit/price_handler/__init__.py` (empty) and `tests/unit/price_handler/test_sql_handler.py` (4-space). Behavior tests (over an in-process `SqlBackend(SqlSettings())` SQLite engine — no Docker): build a small OHLCV DataFrame for `"BTCUSD"`, `to_database("BTCUSD", df, replace=True)`, `read_prices("BTCUSD")` → assert the OHLCV values round-trip; `get_symbols()` → `["BTCUSD"]`; inspect the engine and assert the ONLY data table is `"prices"` (no `"btcusd"` per-symbol table — D-07); write a second symbol and assert both coexist in the single `prices` table filtered by `symbol`. FL-06 grep-gate tests: assert (via `subprocess.run(["grep","-rIn", ...])` returning non-zero / no match, or a pathlib scan of `itrader/`) that NO source file under `itrader/` contains `user:pass@` or `:1234@`, and none contains an f-string inside `text(` (`text(f'` or `text(f"`). The test module itself must NOT embed those literal patterns (build them from fragments if asserting on them) so it does not self-trip the gate.
  </action>
  <verify>
    <automated>poetry run pytest tests/unit/price_handler/test_sql_handler.py -x</automated>
  </verify>
  <acceptance_criteria>
    - The behavior tests pass: OHLCV round-trips, `get_symbols()` returns the written symbols, and the only data table is `prices` (no per-symbol table — D-07).
    - The grep-gate tests pass: `grep -rIn 'user:pass@\|:1234@' itrader/` finds nothing; `grep -rIn "text(f'" itrader/` (and `text(f"`) finds nothing.
    - The test runs WITHOUT Docker (SQLite backend) and emits no non-ignored warning (filterwarnings=["error"]).
    - The test file does not itself contain the literal `user:pass@` / `:1234@` / `text(f'` strings.
  </acceptance_criteria>
  <done>SEC-01 single-table parameterized behavior is proven and the FL-06 grep gates are GREEN as automated tests.</done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| symbol/identifier input → SQL construction | the FL-06 injection boundary (was table-per-symbol) |
| Settings.database_url (SecretStr) → engine | DB credentials cross into connection setup |
| source/VCS → operator | a hardcoded credential leaks via the repo + history |
| persistence edge → logs | a resolved secret URL must never reach a log sink |

## STRIDE Threat Register

| Threat ID | Category | Component | Disposition | Mitigation Plan |
|-----------|----------|-----------|-------------|-----------------|
| T-01-12 | Tampering | symbol-as-table-name (sql_store L56/58/69) | mitigate | Single `prices` table + `symbol` VALUE column + bound params; literal table name only — no dynamic identifiers (D-07) |
| T-01-13 | Tampering | f-string DROP TABLE DDL (sql_store L35) | mitigate | Parameterized Core delete / constant `DROP TABLE prices`; never a string-built identifier inside text() (D-08) |
| T-01-14 | Information Disclosure | hardcoded credential (sql_store L17, in VCS) | mitigate | Creds from `Settings.database_url.get_secret_value()`; grep gate proves no `user:pass@`/`:1234@`; rotate the `:1234` credential if ever real + scrub from history (ops note) |
| T-01-04 | Information Disclosure | secret leak into logs | mitigate | SecretStr masks repr/str; never call get_secret_value() into a log; structlog component-bound logger preserved |
| T-01-15 | Spoofing / Repudiation | second cred source drift (SYSTEM_DB_URL vs ITRADER_DATABASE_URL) | mitigate | One canonical source (Settings.database_url); the legacy SYSTEM_DB_URL D-live seam is documented + deferred, not re-wired here |
| T-01-SC | Tampering | (cross-ref 01-01) package installs | mitigate | Covered by the 01-01 blocking-human legitimacy checkpoint |
</threat_model>

<verification>
- `poetry run pytest tests/unit/price_handler/test_sql_handler.py -x` green (single-table behavior + grep gates).
- `! grep -rIn 'user:pass@\|:1234@' itrader/` and `! grep -rIn "text(f'" itrader/` (+ review `text(f"`) — both clean (FL-06 closed).
- `poetry run mypy itrader/price_handler/store/sql_store.py` clean; `poetry run mypy itrader` no new errors (GATE-02, D-09).
- `poetry run pytest tests` green under filterwarnings=["error"] with no new broad ignore.
- GATE-01 (recurring, inert): sql_store is quarantined (not on the backtest import path) — oracle byte-exact 134 / `46189.87730727451`, no W1/W2 regression vs 15.7 s / 152.8 MB.
</verification>

<success_criteria>
- FL-06 closed: no hardcoded creds (L17), no f-string DDL (L35), no symbol-as-table-name (L56/58/69) — grep gates green (SEC-01).
- SqlHandler composes the spine on a single parameterized `prices` table with creds from SecretStr (D-06/D-07/D-08).
- sql_store.py is mypy --strict clean and out of the D-sql override; no new broad ignore (GATE-02/D-09).
</success_criteria>

<output>
Create `.planning/phases/01-sql-spine-security-hardening/01-05-SUMMARY.md` when done.
</output>

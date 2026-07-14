---
phase: 260713-ncq-centralize-live-stream-feed-db-settings
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - itrader/config/system.py
  - itrader/trading_system/live_trading_system.py
  - itrader/venues/okx_plugin.py
  - itrader/price_handler/providers/okx_provider.py
  - itrader/price_handler/feed/live_bar_feed.py
  - itrader/universe/universe_handler.py
  - itrader/execution_handler/exchanges/okx.py
  - itrader/portfolio_handler/account/venue.py
autonomous: true
requirements: [IN-01]

must_haves:
  truths:
    - "SystemConfig exposes eager `stream` (StreamSettings) and `feed_provider` (FeedProviderSettings) fields, both default-valued equal to the retired module constants (D-08 / IN-01)."
    - "Zero `StreamSettings()` / `FeedProviderSettings()` inline default-constructions remain in itrader/; every live read sources the process-wide SystemConfig (IN-01)."
    - "The `_STREAM_SETTINGS` module global is deleted; its three reads source `config.stream.*` (IN-01)."
    - "The live DB gate in build_live_system selects Postgres-vs-in-memory via a lazy default `SqlSettings()` probe (probe.password/probe.url presence), NOT `os.getenv`; the WR-10 loud in-memory fallback warning and all downstream storage wiring are preserved byte-for-byte."
    - "OKX import-inertness stays green: no ccxt/async/sql on the backtest import graph; the `sql` cached_property stays unresolved (`\"sql\" not in config.__dict__`)."
    - "The SMA_MACD backtest oracle stays byte-exact (134 / 46189.87730727451)."
  artifacts:
    - itrader/config/system.py
    - itrader/trading_system/live_trading_system.py
    - itrader/venues/okx_plugin.py
    - itrader/price_handler/providers/okx_provider.py
    - itrader/price_handler/feed/live_bar_feed.py
    - itrader/universe/universe_handler.py
    - itrader/execution_handler/exchanges/okx.py
    - itrader/portfolio_handler/account/venue.py
  key_links:
    - "SystemConfig.stream / .feed_provider <- imported eagerly from config/stream.py (pure pydantic/stdlib, inert)."
    - "ctx.config.stream <- EngineContext(config=_system_config) at live_trading_system.py:1602 -> okx_plugin.build_bundle / build_provider."
    - "from itrader import config (singleton) <- okx_provider / live_bar_feed / universe_handler / exchanges.okx / account.venue call-site reads."
    - "SqlSettings() probe <- config/sql.py lazy-imported inside build_live_system; gate on password/url presence (default SQLITE driver skips _require_pg_credentials)."
---

<!-- planner-discipline-allow: StreamSettings() -->
<!-- planner-discipline-allow: FeedProviderSettings() -->
<!-- planner-discipline-allow: _STREAM_SETTINGS -->
<!-- planner-discipline-allow: os.getenv("ITRADER_DATABASE_ -->

<objective>
Centralize every live stream / feed-provider / DB setting under the process-wide `SystemConfig` and inject it, replacing inline default-construction at every call site. This is an early, scoped down-payment on the EngineContext.config-is-read direction (Phase 9), limited to these settings. Origin: Phase 06 code review finding IN-01 plus the owner-flagged "default-construct-inline" anti-pattern. The design is LOCKED — implement exactly as scoped below.

Purpose: One source of truth for `StreamSettings` / `FeedProviderSettings` / DB-credential presence, so a value can never drift between the composition root and a lower-level reader.
Output: Two eager `SystemConfig` fields, all inline constructions repointed to the injected/singleton config, and the DB gate moved onto the existing `SqlSettings` layer.

DISCOVERY (planner reconciliation — surfaced, not a re-litigation): the locked design enumerates ~8 sites, but there are **10** `StreamSettings()` / `FeedProviderSettings()` default-constructions in `itrader/`. Three not explicitly enumerated are the `StreamSupervisor(StreamSettings(), ...)` sites at `okx_provider.py:186`, `portfolio_handler/account/venue.py:185`, and `execution_handler/exchanges/okx.py:173`. The GOAL ("sourced from ONE place, not default-constructed inline") and the locked verify guardrail ("grep proving zero remaining `StreamSettings()` default-constructions") BOTH require these three to be repointed too. `StreamSupervisor.__init__(self, config: "StreamSettings", *, ...)` takes a `StreamSettings` first-arg, so `config.stream` is a byte-identical drop-in. All three are folded into Task 2.
</objective>

<execution_context>
@$HOME/.claude/gsd-core/workflows/execute-plan.md
@$HOME/.claude/gsd-core/templates/summary.md
</execution_context>

<context>
@.planning/STATE.md
@./CLAUDE.md

# Config contract (defines the shapes being injected)
@itrader/config/stream.py
@itrader/config/sql.py

# The injection seam for the venue plugins
@itrader/trading_system/engine_context.py

INDENTATION HAZARD (per CLAUDE.md — measure bytes per file, NEVER normalize):
- 4 SPACES: config/system.py, trading_system/live_trading_system.py, price_handler/providers/okx_provider.py, price_handler/feed/live_bar_feed.py, portfolio_handler/account/venue.py, universe/universe_handler.py.
- TABS: itrader/venues/okx_plugin.py, itrader/execution_handler/exchanges/okx.py.
- The trading_system package is split — live_trading_system.py is 4-space; do not assume the package is tabs.
Confirm each file's leading whitespace before editing (e.g. `grep -nP "^\t" <file>` vs `grep -nP "^    [^ ]" <file>`).

WORKTREE GOTCHA (per project memory): if executing in a git worktree, prepend `PYTHONPATH="$PWD"` to pytest/mypy so the in-project `.venv` editable install does not shadow worktree edits, and use `poetry run pytest` (not `make test`, which aborts on missing `.env` and disables logs).
</context>

<tasks>

<task type="auto" tdd="true">
  <name>Task 1: Add eager stream + feed_provider fields to SystemConfig</name>
  <files>itrader/config/system.py</files>
  <behavior>
    - `SystemConfig.default().stream` is a `StreamSettings` with `okx_stream_symbol == "BTC/USDC"`, `okx_stream_timeframe == "1d"` (defaults unchanged from config/stream.py, D-08).
    - `SystemConfig.default().feed_provider` is a `FeedProviderSettings` with `warmup_margin == 5`, `backfill_page == 1000`.
    - Right after `import itrader`, `"sql" not in itrader.config.__dict__` still holds (the lazy `sql` cached_property is NOT resolved by adding these fields).
  </behavior>
  <action>
    Add the eager config home for the live stream + feed-provider settings (CHANGE 1, IN-01 / D-08). File is 4-SPACE indented.
    1. At the top import block (after `from itrader.config.settings import Settings`, line ~15), add: `from itrader.config.stream import FeedProviderSettings, StreamSettings`. This is import-safe — config/stream.py imports only pydantic/stdlib, so it pulls NO ccxt/async/sql and preserves inertness (owner-verified; it is already on the backtest import graph by D-08).
    2. In `class SystemConfig`, immediately after the `monitoring: MonitoringSettings = Field(default_factory=MonitoringSettings)` field (line ~104), add two eager fields matching the existing `Field(default_factory=...)` idiom:
       - `stream: StreamSettings = Field(default_factory=StreamSettings)`
       - `feed_provider: FeedProviderSettings = Field(default_factory=FeedProviderSettings)`
    3. Do NOT touch the lazy `sql` cached_property (lines ~116-130) — it MUST stay a `@cached_property` (not a field) because config/sql.py imports sqlalchemy; converting it to an eager field would break the inertness gate. Leave the `TYPE_CHECKING` `SqlSettings` import untouched.
    Under `model_config = ConfigDict(extra="forbid")` these two nested models already forbid extras (mass-assignment defense) — no further validation needed.
  </action>
  <verify>
    <automated>poetry run python -c "import itrader; from itrader import config; assert config.stream.okx_stream_symbol == 'BTC/USDC'; assert config.stream.okx_stream_timeframe == '1d'; assert config.feed_provider.warmup_margin == 5; assert config.feed_provider.backfill_page == 1000; assert 'sql' not in config.__dict__, 'sql cached_property must stay lazy'; print('OK')"</automated>
  </verify>
  <done>`SystemConfig` has eager `stream` and `feed_provider` fields with unchanged defaults; the `sql` cached_property stays unresolved on the singleton; `poetry run mypy itrader/config/system.py` is clean.</done>
</task>

<task type="auto">
  <name>Task 2: Repoint all StreamSettings() constructions to injected config</name>
  <files>itrader/trading_system/live_trading_system.py, itrader/venues/okx_plugin.py, itrader/price_handler/providers/okx_provider.py, itrader/execution_handler/exchanges/okx.py, itrader/portfolio_handler/account/venue.py</files>
  <action>
    Repoint every `StreamSettings()` default-construction to read the injected/singleton `SystemConfig` (CHANGE 2, stream portion — includes the three StreamSupervisor sites per the DISCOVERY note). Behavior is byte-identical: every source is a default-valued `StreamSettings`. Measure indentation per file (see context HAZARD note).

    A. `live_trading_system.py` (4-SPACE):
       - Delete line ~83 `_STREAM_SETTINGS = StreamSettings()` entirely.
       - Remove the now-unused module-top import at line ~19 `from itrader.config.stream import StreamSettings`.
       - Update the adjacent comment block (~73-82) that describes `_STREAM_SETTINGS`/"the P1 seam" so it no longer names a deleted symbol — describe it as reading `config.stream` (the injected single wiring source). Do NOT leave `_STREAM_SETTINGS` in any surviving comment.
       - Read site line ~367 (inside `_run_session_baseline_guard`, def@~342, which has NO config in scope): add `from itrader import config as _system_config` at the top of that method body, then change `_STREAM_SETTINGS.okx_stream_symbol` -> `_system_config.stream.okx_stream_symbol`.
       - Read site line ~948 (inside the method that already imports `from itrader import config as _system_config` at ~910): change `_STREAM_SETTINGS.okx_stream_timeframe` -> `_system_config.stream.okx_stream_timeframe`.
       - Read site line ~1069 (inside `start`, def@~979, which has NO config in scope): add `from itrader import config as _system_config` inside `start()` before the use, then change `_STREAM_SETTINGS.okx_stream_timeframe` -> `_system_config.stream.okx_stream_timeframe`.

    B. `okx_plugin.py` (TABS): both plugin methods already receive `ctx`, and `EngineContext.config` is `_system_config` (wired at live_trading_system.py:1602), so read `ctx.config.stream`.
       - `build_bundle` (~87): change `stream = StreamSettings()` -> `stream = ctx.config.stream`; remove the in-body lazy import at ~80 `from itrader.config.stream import StreamSettings`; update the adjacent comment (~85-86) so it references reading `ctx.config.stream` (remove the `_STREAM_SETTINGS` mention on ~86).
       - `build_provider` (~134): change `stream = StreamSettings()` -> `stream = ctx.config.stream`; remove the in-body lazy import at ~131.
       - Update the class docstrings (~73, ~125) that say "StreamSettings() read" to "ctx.config.stream read" so no stale current-mechanism claim remains.

    C. `okx_provider.py` (4-SPACE) — StreamSupervisor site only in this task: at line ~186 the constructor `self._supervisor = StreamSupervisor(StreamSettings(), ...)` sits in a body that already lazy-imports `import ccxt` (~182) and `from itrader.connectors.stream_supervisor import StreamSupervisor` (~184). Add `from itrader import config` in that same body and change the first positional arg from `StreamSettings()` to `config.stream`. Do NOT remove the module-top import at line ~59 yet (it still carries `FeedProviderSettings`, removed in Task 3).

    D. `execution_handler/exchanges/okx.py` (TABS): at line ~173 `self._supervisor = StreamSupervisor(StreamSettings(), ...)` sits in a body that lazy-imports `import ccxt` (~169) and `StreamSupervisor` (~171). Add `from itrader import config` in that body and change the first arg `StreamSettings()` -> `config.stream`; remove the now-unused module-top import at line ~37 `from itrader.config.stream import StreamSettings`.

    E. `portfolio_handler/account/venue.py` (4-SPACE): at line ~185 `self._supervisor = StreamSupervisor(StreamSettings(), ...)` sits in a body that lazy-imports `import ccxt` (~181) and `StreamSupervisor` (~183). Add `from itrader import config` in that body and change the first arg `StreamSettings()` -> `config.stream`; remove the now-unused module-top import at line ~40.

    All added `from itrader import config` reads are inside live-only method bodies (never module scope), matching the existing `from itrader import config as _system_config` local-import idiom in live_trading_system.py — inert on the backtest import path.
  </action>
  <verify>
    <automated>test -z "$(grep -rn 'StreamSettings()' itrader/ | grep -v '``')" && test -z "$(grep -rn '_STREAM_SETTINGS' itrader/ | grep -v '``')" && echo NO_STREAM_CONSTRUCTIONS</automated>
  </verify>
  <done>Zero non-doc `StreamSettings()` constructions and zero `_STREAM_SETTINGS` references remain in itrader/; the three `_STREAM_SETTINGS` reads and all six `StreamSettings()` sites source `config.stream` / `ctx.config.stream`; `poetry run mypy itrader` is clean over touched strict-scope files.</done>
</task>

<task type="auto">
  <name>Task 3: Repoint all FeedProviderSettings() constructions to injected config</name>
  <files>itrader/price_handler/providers/okx_provider.py, itrader/price_handler/feed/live_bar_feed.py, itrader/universe/universe_handler.py</files>
  <action>
    Repoint every `FeedProviderSettings()` default-construction to read the singleton config (CHANGE 2, feed_provider portion). Behavior is byte-identical (default-valued `FeedProviderSettings`). All three files are 4-SPACE.

    A. `okx_provider.py`:
       - Line ~541 (in `fetch_ohlcv_backfill`) and line ~582 (in `_fetch_ohlcv_backfill_async`): change `limit = FeedProviderSettings().backfill_page` -> `limit = config.feed_provider.backfill_page`. Add `from itrader import config` locally at the top of each of those two method bodies (or one shared local read per method) — do NOT add a module-top `from itrader import config`.
       - Now that both the StreamSettings (Task 2, ~186) and FeedProviderSettings (~541/~582) usages are gone, remove the fully-unused module-top import at line ~59 `from itrader.config.stream import FeedProviderSettings, StreamSettings`.
       - Update the adjacent docstrings (~538, ~579) that reference `FeedProviderSettings().backfill_page` to reference `config.feed_provider.backfill_page`.

    B. `live_bar_feed.py`:
       - Line ~283 (in `warmup`): change `depth = self.cache_capacity() + FeedProviderSettings().warmup_margin` -> `depth = self.cache_capacity() + config.feed_provider.warmup_margin`; add `from itrader import config` locally in `warmup()`.
       - Remove the now-unused module-top import at line ~42 `from itrader.config.stream import FeedProviderSettings`.
       - Update the adjacent docstring (~268) referencing `FeedProviderSettings().warmup_margin` to `config.feed_provider.warmup_margin`.

    C. `universe_handler.py`:
       - Line ~507 (in `_begin_warmup`): change `depth = self._feed.cache_capacity() + FeedProviderSettings().warmup_margin` -> `depth = self._feed.cache_capacity() + config.feed_provider.warmup_margin`; add `from itrader import config` locally in `_begin_warmup()`.
       - Remove the now-unused module-top import at line ~40 `from itrader.config.stream import FeedProviderSettings`.
       - Update the adjacent docstrings (~500, ~107) referencing `FeedProviderSettings().warmup_margin` to `config.feed_provider.warmup_margin`.
  </action>
  <verify>
    <automated>test -z "$(grep -rn 'FeedProviderSettings()' itrader/ | grep -v '``')" && echo NO_FEED_CONSTRUCTIONS</automated>
  </verify>
  <done>Zero non-doc `FeedProviderSettings()` constructions remain in itrader/; the three feed-provider read sites source `config.feed_provider.*`; the `from itrader.config.stream` module-top imports are removed from all three files; `poetry run mypy itrader` clean over touched strict-scope files.</done>
</task>

<task type="auto">
  <name>Task 4: Move the live DB gate onto the SqlSettings probe</name>
  <files>itrader/trading_system/live_trading_system.py</files>
  <action>
    Replace the raw env-presence check in `build_live_system` (~1473-1508) with the existing `SqlSettings` layer (CHANGE 3). File is 4-SPACE.
    1. Replace lines ~1473-1475:
         `pg_password = os.getenv("ITRADER_DATABASE_PASSWORD", "")`
         `pg_url = os.getenv("ITRADER_DATABASE_URL", "")`
         `if not (pg_password or pg_url):`
       with a lazy default-probe gate. Immediately before the gate, lazy-import inside the function body (NEVER module top): `from itrader.config.sql import SqlSettings`. Construct `probe = SqlSettings()`. Because the default driver is `SQLITE_PYSQLITE`, the `_require_pg_credentials` validator is SKIPPED, so this never raises when credentials are absent; the probe still reads `ITRADER_DATABASE_*` env via `env_prefix` into `password`/`url`. Gate the in-memory fallback branch on: `if probe.password is None and probe.url is None:` (Postgres arm = the `else`, i.e. `probe.password is not None or probe.url is not None`).
    2. Preserve the WR-10 in-memory fallback branch byte-for-byte: the loud `logger.warning(...)` about unset `ITRADER_DATABASE_PASSWORD` / `ITRADER_DATABASE_URL`, `OrderStorageFactory.create('backtest')`, `SignalStorageFactory.create_in_memory()`, `system_db_backend = None`.
    3. Preserve the Postgres `else` branch byte-for-byte: keep its lazy `from itrader.config.sql import SqlDriver, SqlSettings` import (~1488) and the `SqlSettings(driver=SqlDriver.POSTGRESQL_PSYCOPG2)` construction and everything downstream (SqlEngine / CachedSqlOrderStorage / SqlOrderStorage / signal_store / system_db_backend / portfolio_handler / halt_record_store wiring). A second `from itrader.config.sql import SqlSettings` for the probe is acceptable (redundant, harmless).
    4. Do NOT add DB fields to config/settings.py, and do NOT read `config.sql` anywhere (that would resolve the lazy cached_property and break inertness). The probe is a direct `SqlSettings()` construction inside build_live_system only.
    5. After removing both `os.getenv(...)` calls, `import os` (line 1) becomes unused (grep confirms no other `os.` usage in the file) — remove `import os`.
    6. Update the stale gate comment (~62-71) so it describes the `SqlSettings()` probe presence-check instead of the `os.getenv` mechanism, keeping the WR-10 "no hardcoded credential fallback" intent. Do not leave a comment claiming the gate "reads os.getenv inside __init__".
  </action>
  <verify>
    <automated>test -z "$(grep -rn 'os.getenv(\"ITRADER_DATABASE_' itrader/)" && test -z "$(grep -n '^import os$' itrader/trading_system/live_trading_system.py)" && echo DB_GATE_ON_SQLSETTINGS</automated>
  </verify>
  <done>The DB gate uses a lazy `SqlSettings()` probe (`probe.password` / `probe.url`) instead of `os.getenv`; zero `os.getenv("ITRADER_DATABASE_` calls remain; `import os` removed; the WR-10 warning and all Postgres/in-memory downstream wiring unchanged; `poetry run mypy itrader/trading_system/live_trading_system.py` (respecting existing overrides) clean.</done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| env -> config | `ITRADER_DATABASE_*` env vars cross into the `SqlSettings` probe (credential-presence detection). |
| composition root -> live components | `SystemConfig.stream` / `.feed_provider` injected/read by live-only readers. |

## STRIDE Threat Register

| Threat ID | Category | Component | Severity | Disposition | Mitigation Plan |
|-----------|----------|-----------|----------|-------------|-----------------|
| T-ncq-01 | Tampering | eager `SystemConfig.stream` / `.feed_provider` fields | low | mitigate | Both nested models set `ConfigDict(extra="forbid")` (config/stream.py) — an unknown key is rejected, not absorbed (mass-assignment defense, existing control preserved). |
| T-ncq-02 | Information disclosure | `SqlSettings()` DB probe reads credentials | medium | mitigate | `password`/`url` are `SecretStr`; the gate only tests `is None`/`is not None` (presence), never logs or serializes the secret; WR-10 warning names only the env-var keys, never values. |
| T-ncq-03 | Denial of service | probe resolving `config.sql` cached_property | low | mitigate | Probe is a direct `SqlSettings()` inside build_live_system; `config.sql` is never touched, so the lazy cached_property stays unresolved and the backtest import graph stays sqlalchemy-free (inertness gate). |
| T-ncq-SC | Tampering | package installs | low | accept | No npm/pip/cargo installs in this task — reuses existing pydantic config classes only. |
</threat_model>

<verification>
Run from the repo root (in a worktree, prepend `PYTHONPATH="$PWD"` and prefer `poetry run pytest` over `make test`).

1. Inertness gate stays green (no ccxt/async/sql on the backtest import graph; `sql` cached_property stays lazy):
   `poetry run pytest tests/integration/test_okx_inertness.py -q`
2. Backtest oracle stays byte-exact (134 / 46189.87730727451):
   `poetry run pytest tests/integration/test_backtest_oracle.py -q`
3. Type gate:
   `poetry run mypy itrader`
4. Grep gates — all must print nothing except the trailing OK marker:
   - `test -z "$(grep -rn 'StreamSettings()' itrader/ | grep -v '``')" && echo OK`
   - `test -z "$(grep -rn 'FeedProviderSettings()' itrader/ | grep -v '``')" && echo OK`
   - `test -z "$(grep -rn '_STREAM_SETTINGS' itrader/ | grep -v '``')" && echo OK`
   - `test -z "$(grep -rn 'os.getenv(\"ITRADER_DATABASE_' itrader/)" && echo OK`
   (The `grep -v '``'` filter excludes RST double-backtick doc mentions; after the doc-comment scrubs in Tasks 2-3 these should be empty regardless.)
5. Behavioral smoke: `SystemConfig.default().stream` / `.feed_provider` carry the unchanged defaults and `"sql" not in config.__dict__` (Task 1 automated check).
</verification>

<success_criteria>
- Two eager `stream` / `feed_provider` fields on `SystemConfig`, defaults unchanged (D-08).
- All 10 inline `StreamSettings()` / `FeedProviderSettings()` constructions repointed to the injected/singleton config; `_STREAM_SETTINGS` deleted.
- DB gate reads a lazy `SqlSettings()` probe, not `os.getenv`; WR-10 warning + downstream storage wiring preserved byte-for-byte.
- Inertness gate green; oracle byte-exact; `mypy` clean; all grep gates empty.
</success_criteria>

<output>
Create `.planning/quick/260713-ncq-centralize-live-stream-feed-db-settings-/260713-ncq-SUMMARY.md` when done.
</output>

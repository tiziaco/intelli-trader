---
phase: 260713-ncq-centralize-live-stream-feed-db-settings
plan: 01
subsystem: config
tags: [pydantic, SystemConfig, StreamSettings, FeedProviderSettings, SqlSettings, live-trading, okx, inertness]

requires:
  - phase: 01-config-centralization
    provides: "config/stream.py (StreamSettings/FeedProviderSettings, D-08); config/sql.py (SqlSettings probe)"
  - phase: 06-liverunner-factory-facade-shrink
    provides: "EngineContext.config wiring seam; build_live_system composition root; venue plugins reading ctx"
provides:
  - "Two eager SystemConfig fields (stream, feed_provider) as the single wiring source for live stream + feed-provider settings"
  - "All 10 inline StreamSettings()/FeedProviderSettings() default-constructions repointed to the injected/singleton config"
  - "_STREAM_SETTINGS module global deleted; three reads source config.stream"
  - "Live DB gate moved off os.getenv onto a lazy SqlSettings() presence probe"
affects: [phase-09-runtime-config-platform, engine-context-config-is-read, live-trading-wiring]

tech-stack:
  added: []
  patterns:
    - "Eager pydantic nested-config fields (Field(default_factory=...)) for import-inert live settings"
    - "Local (in-method-body) `from itrader import config` reads for live-only call sites — inert on the backtest import graph"
    - "Config-presence gating via a lazy default SqlSettings() probe (SQLite default driver skips _require_pg_credentials)"

key-files:
  created: []
  modified:
    - itrader/config/system.py
    - itrader/trading_system/live_trading_system.py
    - itrader/venues/okx_plugin.py
    - itrader/price_handler/providers/okx_provider.py
    - itrader/price_handler/feed/live_bar_feed.py
    - itrader/universe/universe_handler.py
    - itrader/execution_handler/exchanges/okx.py
    - itrader/portfolio_handler/account/venue.py
    - tests/unit/config/test_system_config.py
    - tests/unit/venues/test_okx_plugin.py
    - tests/unit/venues/test_assemble.py

key-decisions:
  - "stream/feed_provider are EAGER Field(default_factory=...) fields (config/stream.py is pydantic-only, inert); sql stays a lazy cached_property"
  - "Live-only reads use a local `from itrader import config` import inside the method body, never module top — preserves OKX import-inertness"
  - "okx_plugin.py is 4-SPACE indented (empirically verified), NOT tabs as the plan HAZARD note claimed"
  - "DB gate uses `probe.password is None and probe.url is None` presence test; never logs/serializes the SecretStr"

patterns-established:
  - "Single-source config injection: composition-root readers take ctx.config.stream; lower-level live readers take the config singleton"
  - "Presence-only credential probe: default SqlSettings() reads ITRADER_DATABASE_* env without raising on the SQLite default arm"

requirements-completed: [IN-01]

coverage:
  - id: D1
    description: "SystemConfig exposes eager stream (StreamSettings) + feed_provider (FeedProviderSettings) fields with unchanged D-08 defaults; sql cached_property stays lazy at import"
    requirement: "IN-01"
    verification:
      - kind: unit
        ref: "tests/unit/config/test_system_config.py#test_stream_is_eager_field_with_unchanged_defaults"
        status: pass
      - kind: unit
        ref: "tests/unit/config/test_system_config.py#test_feed_provider_is_eager_field_with_unchanged_defaults"
        status: pass
      - kind: unit
        ref: "tests/unit/config/test_system_config.py#test_adding_eager_fields_keeps_sql_lazy_at_import"
        status: pass
    human_judgment: false
  - id: D2
    description: "Zero inline StreamSettings()/FeedProviderSettings() default-constructions and zero _STREAM_SETTINGS references remain in itrader/; every live read sources the injected/singleton config"
    requirement: "IN-01"
    verification:
      - kind: automated_ui
        ref: "grep -rn 'StreamSettings()' itrader/ | grep -v '``'  (empty) && same for FeedProviderSettings() and _STREAM_SETTINGS"
        status: pass
    human_judgment: false
  - id: D3
    description: "Live DB gate selects Postgres-vs-in-memory via a lazy default SqlSettings() probe (not os.getenv); WR-10 loud warning + downstream storage wiring preserved"
    requirement: "IN-01"
    verification:
      - kind: integration
        ref: "tests/integration/test_live_portfolio_durable_wiring.py"
        status: pass
      - kind: integration
        ref: "tests/integration/test_store_live_drive.py"
        status: pass
      - kind: automated_ui
        ref: "grep -rn 'os.getenv(\"ITRADER_DATABASE_' itrader/ (empty) && no '^import os$' in live_trading_system.py"
        status: pass
  - id: D4
    description: "OKX import-inertness stays green (no ccxt/async/sql on the backtest import graph; sql cached_property unresolved) and SMA_MACD oracle stays byte-exact 134/46189.87730727451"
    requirement: "IN-01"
    verification:
      - kind: integration
        ref: "tests/integration/test_okx_inertness.py"
        status: pass
      - kind: integration
        ref: "tests/integration/test_backtest_oracle.py"
        status: pass
    human_judgment: false

duration: 70min
completed: 2026-07-13
status: complete
---

# Phase 260713-ncq Plan 01: Centralize live stream / feed-provider / DB settings under SystemConfig Summary

**Two eager `SystemConfig.stream`/`.feed_provider` fields become the single wiring source for every live stream + feed-provider setting, replacing 10 inline default-constructions and moving the live DB gate onto a lazy `SqlSettings()` probe — all with the OKX inertness gate green and the SMA_MACD oracle byte-exact.**

## Performance

- **Duration:** ~70 min
- **Started:** 2026-07-13T14:05Z
- **Completed:** 2026-07-13T15:15Z
- **Tasks:** 4
- **Files modified:** 11 (8 source + 3 test)

## Accomplishments
- Added eager `stream: StreamSettings` and `feed_provider: FeedProviderSettings` fields to `SystemConfig` (IN-01/D-08), the single source of truth — while keeping the `sql` cached_property lazy so the inertness lever holds.
- Deleted the `_STREAM_SETTINGS` module global and repointed all 6 `StreamSettings()` sites (3 composition-root reads + 3 `StreamSupervisor` constructor arms) to `config.stream` / `ctx.config.stream`.
- Repointed all 4 `FeedProviderSettings()` read sites to `config.feed_provider.*` and removed the now-unused `config.stream` module-top imports.
- Replaced the raw `os.getenv("ITRADER_DATABASE_*")` DB gate in `build_live_system` with a lazy default `SqlSettings()` presence probe, removed `import os`, and preserved the WR-10 loud in-memory-fallback warning + all Postgres/in-memory downstream wiring byte-for-byte.

## Task Commits

Each task was committed atomically:

1. **Task 1: Add eager stream + feed_provider fields to SystemConfig** - `1c2ff039` (feat, TDD: RED tests + GREEN impl in one commit)
2. **Task 2: Repoint all StreamSettings() constructions to injected config** - `1cb82f4b` (refactor)
3. **Task 3: Repoint all FeedProviderSettings() constructions to injected config** - `0611d6d8` (refactor)
4. **Task 4: Move the live DB gate onto the SqlSettings probe** - `8efe050d` (refactor)

Follow-up: **Venue-plugin ctx mock updates** - `33390772` (test) — consequence of Task 2's `ctx.config.stream` read.

## Files Created/Modified
- `itrader/config/system.py` - Added eager `stream`/`feed_provider` fields + the `config/stream` eager import
- `itrader/trading_system/live_trading_system.py` - Deleted `_STREAM_SETTINGS`, repointed 3 reads to `config.stream`, moved DB gate onto `SqlSettings()` probe, removed `import os`, refreshed two comment blocks
- `itrader/venues/okx_plugin.py` - `build_bundle`/`build_provider` read `ctx.config.stream`; scrubbed stale docstrings (file is 4-SPACE)
- `itrader/price_handler/providers/okx_provider.py` - `StreamSupervisor` arm + 2 backfill sites read `config.stream`/`config.feed_provider`; removed module-top import
- `itrader/price_handler/feed/live_bar_feed.py` - `warmup()` reads `config.feed_provider.warmup_margin`; removed module-top import
- `itrader/universe/universe_handler.py` - `_begin_warmup()` reads `config.feed_provider.warmup_margin`; removed module-top import
- `itrader/execution_handler/exchanges/okx.py` - `StreamSupervisor` arm reads `config.stream` (TABS); removed module-top import
- `itrader/portfolio_handler/account/venue.py` - `StreamSupervisor` arm reads `config.stream`; removed module-top import
- `tests/unit/config/test_system_config.py` - Added 3 TDD tests pinning the eager fields + lazy-sql invariant
- `tests/unit/venues/test_okx_plugin.py`, `tests/unit/venues/test_assemble.py` - `_fake_ctx` now exposes `config=SystemConfig.default()`

## Decisions Made
- None beyond the LOCKED plan design. The three `StreamSupervisor(StreamSettings(), ...)` arms flagged in the plan's DISCOVERY note were folded into Task 2 as scoped (byte-identical drop-in — `StreamSupervisor.__init__` takes a `StreamSettings` first arg).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Updated venue-plugin ctx mocks after the `ctx.config.stream` repoint**
- **Found during:** Task 2 (okx_plugin `build_bundle`/`build_provider` now read `ctx.config.stream`)
- **Issue:** `tests/unit/venues/test_okx_plugin.py` and `test_assemble.py` build a fake `EngineContext` via `SimpleNamespace(bus=object())` with no `config` attribute, so the repointed read raised `AttributeError` (6 test failures).
- **Fix:** `_fake_ctx()` in both files now returns `SimpleNamespace(bus=object(), config=SystemConfig.default())`, matching the real wiring (`EngineContext.config` is the process-wide singleton).
- **Files modified:** tests/unit/venues/test_okx_plugin.py, tests/unit/venues/test_assemble.py
- **Verification:** `poetry run pytest tests/unit/venues` → 32 passed
- **Committed in:** `33390772`

**2. [Rule 1 - Doc/plan discrepancy] okx_plugin.py is 4-SPACE, not TABS**
- **Found during:** Task 2 (indentation confirmation before editing okx_plugin.py)
- **Issue:** The plan's INDENTATION HAZARD note listed `itrader/venues/okx_plugin.py` under TABS; empirical measurement (`grep -cP "^\t"` → 0 tab lines, 31 four-space lines; the module docstring self-documents "Indentation: 4-SPACE") shows it is 4-SPACE.
- **Fix:** Edited okx_plugin.py with 4-SPACE indentation (matched the actual file). No behavior change; no mixed-indentation diff introduced. `itrader/execution_handler/exchanges/okx.py` WAS correctly TABS and was edited as such.
- **Files modified:** itrader/venues/okx_plugin.py
- **Verification:** `poetry run mypy itrader` clean; venue tests pass; no whitespace-mix introduced.
- **Committed in:** `1cb82f4b`

---

**Total deviations:** 2 (1 blocking test fix, 1 plan-vs-reality indentation correction)
**Impact on plan:** No scope creep. The test fix is a required consequence of the injected-config read; the indentation correction avoided corrupting a 4-SPACE file per the never-normalize rule.

## Issues Encountered
None beyond the deviations above.

## Verification Results
- Inertness gate: `tests/integration/test_okx_inertness.py` — 4 passed (sql cached_property stays lazy; no ccxt/async/sql on backtest import graph)
- Backtest oracle: `tests/integration/test_backtest_oracle.py` — 3 passed (byte-exact 134 / 46189.87730727451)
- Type gate: `poetry run mypy itrader` — Success, no issues in 249 source files
- Grep gates: all four empty (`StreamSettings()`, `FeedProviderSettings()`, `_STREAM_SETTINGS`, `os.getenv("ITRADER_DATABASE_`)
- Behavioral smoke: `config.stream`/`config.feed_provider` carry unchanged defaults; `"sql" not in config.__dict__`
- Full unit suite: `poetry run pytest tests/unit` — 1897 passed

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- IN-01 closed. This is the scoped down-payment on the EngineContext.config-is-read direction (Phase 9); the pattern (composition-root reads `ctx.config`, live-only leaf readers read the singleton) is established for the broader migration.

## Self-Check: PASSED
- All 8 source files + 3 test files modified and verified on disk.
- All 5 commits present: `1c2ff039`, `1cb82f4b`, `0611d6d8`, `8efe050d`, `33390772`.

---
*Phase: 260713-ncq-centralize-live-stream-feed-db-settings*
*Completed: 2026-07-13*

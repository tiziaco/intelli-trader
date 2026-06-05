---
phase: 03-m2b-config-types-storage-seam-oracle-re-freeze
plan: 05
subsystem: config
tags: [pydantic, pydantic-settings, config, secretstr, jsonb-round-trip, refactor]

# Dependency graph
requires:
  - phase: 03-01
    provides: "pydantic ^2.13 + pydantic-settings ^2.14 Poetry deps; M2-06 Wave-0 characterization stub"
  - phase: 03-04
    provides: "time_parser finalized; TIMEZONE consumer surface stable for the config-collapse rewire"
provides:
  - "config/ collapsed from a 3,380-line / 21-file hand-rolled package to ~1,130 lines of Pydantic v2 models + a pydantic-settings Settings layer"
  - "One model round-trips backtest-dict and JSON (JSONB-ready) via model_validate / model_dump(mode='json')"
  - "Settings(BaseSettings) with required-no-default SecretStr database_url (fail-loud; no working secret defaults)"
  - "FORBIDDEN_SYMBOLS/SUPPORTED_* in core/constants.py (implicit string-concat bug fixed); TIMEZONE sourced from Settings"
  - "Flat itrader/config.py shadow + its importlib loader shim DELETED; consumers construct Pydantic models directly (getters/registry/provider/validator/schema all removed)"
affects: [03-06, 03-07, 03-08, 03-09, portfolio-handler, execution-handler]

# Tech tracking
tech-stack:
  added: []  # pydantic/pydantic-settings added in 03-01; this plan consumes them
  patterns:
    - "Pydantic v2 config models: ConfigDict(extra=...), Field(gt/le) bounds, @classmethod .default()/preset factories"
    - "pydantic-settings fail-loud secrets: required-no-default SecretStr; value only via .get_secret_value()"
    - "model_validate / model_dump(mode='json') round-trip as the backtest-dict <-> JSONB seam"
    - "Reference-data literals live in core/constants.py; config holds tunable models only"

key-files:
  created:
    - itrader/config/models.py
    - itrader/config/settings.py
    - itrader/config/portfolio.py
    - itrader/config/trading.py
    - itrader/config/data.py
    - itrader/config/system.py
    - itrader/config/exchange.py
    - itrader/core/constants.py
  modified:
    - itrader/config/__init__.py
    - itrader/__init__.py
    - itrader/portfolio_handler/portfolio_handler.py
    - itrader/execution_handler/execution_handler.py
    - itrader/outils/time_parser.py
    - itrader/price_handler/data_provider.py
    - itrader/price_handler/exchange/CCXT.py
    - itrader/price_handler/sql_handler.py
    - itrader/trading_system/live_trading_system.py
    - pyproject.toml
    - test/test_config/test_config_models.py
    - test/test_execution_handler/test_exchanges/test_simulated_exchange.py

key-decisions:
  - "Pydantic models consolidated in config/models.py for Task 1 (file-vs-package import collision with old domain dirs), then split into per-domain files in Task 3 once old dirs were deleted"
  - "SecretStr database_url has NO default — a live Settings() instantiation fails loud (M2-06 no-working-secret-defaults); DB/exchange auth not wired (D-live)"
  - "TIMEZONE read from Settings.model_fields['timezone'].default (not Settings() — which requires the fail-loud secret)"
  - "get_exchange_preset replicated from the EXPORTED presets.py (4 presets incl. low_latency, 'HighFeeSimulatedExchange'), not config.py's create_simulated_preset — behavior preservation"
  - "PortfolioHandler holds a single validated PortfolioConfig; dormant per-portfolio config mutation methods deferred to D-live (were never wired on the backtest path)"

patterns-established:
  - "Pydantic v2 config model module per domain + a models.py aggregate import home + a clean __init__.py grouped re-export (mirrors core/enums)"
  - "Preset functions become @classmethod factories / module-level factory funcs that raise on unknown names"

requirements-completed: [M2-06]

# Metrics
duration: 90min
completed: 2026-06-05
---

# Phase 3 Plan 05: Config Collapse to Pydantic v2 Summary

**Collapsed the 3,380-line hand-rolled `config/` package + the flat `itrader/config.py` shadow into ~1,130 lines of Pydantic v2 models and a pydantic-settings `Settings` layer with fail-loud `SecretStr` secrets — JSONB round-trip for free, behavior-preserving on the backtest path (oracle byte-exact).**

## Performance

- **Duration:** ~90 min
- **Started:** 2026-06-05T11:08Z
- **Completed:** 2026-06-05T11:30Z (commit times reflect a tighter window; investigation/reading dominated)
- **Tasks:** 3
- **Files modified/created:** 42 files changed (1,276 insertions, 3,593 deletions)

## Accomplishments
- Pydantic v2 models for all 5 config domains (portfolio/trading/data/system/exchange) with bounded `Field` validators, nested models, and `.default()`/preset factories
- `Settings(BaseSettings)` with required-no-default `SecretStr database_url` — fails loud on a live instantiation, never ships a working secret default (M2-06 criterion)
- `core/constants.py` with `FORBIDDEN_SYMBOLS`/`SUPPORTED_*` and the implicit string-concat literal bug fixed (`'BTG/USDT' 'USDP/USDT'` → distinct entries)
- Flat `itrader/config.py` shadow + the `config/__init__.py` importlib loader shim DELETED; every `config.TIMEZONE`/`FORBIDDEN_SYMBOLS` reader rewired
- All getters + registry/provider/validator/schema machinery deleted; the ~4 in-scope consumers construct Pydantic models directly; `mypy --strict` caught every missed site

## Task Commits

1. **Task 1: Build Pydantic models + Settings + core/constants** - `dd9abf5` (feat, TDD — assertions in test_config_models.py turned live)
2. **Task 2: Absorb + delete flat config.py shadow + importlib shim** - `70af2b7` (refactor)
3. **Task 3: Clean-break rewire — delete getters/machinery, per-domain split** - `19cf1e7` (refactor)

## Files Created/Modified
- `itrader/config/models.py` - Aggregate import home re-exporting all per-domain Pydantic models
- `itrader/config/settings.py` - `Settings(BaseSettings)`, fail-loud `SecretStr database_url`
- `itrader/config/{portfolio,trading,data,system,exchange}.py` - per-domain Pydantic v2 models + preset factories
- `itrader/core/constants.py` - `FORBIDDEN_SYMBOLS`/`SUPPORTED_*` (concat bug fixed)
- `itrader/config/__init__.py` - clean grouped re-export (no getters/registry); module-level `TIMEZONE`
- `itrader/__init__.py` - `config = SystemConfig.default()` (registry getters deleted)
- `itrader/portfolio_handler/portfolio_handler.py` - holds a `PortfolioConfig`; config-mgmt methods re-validate via the model
- `itrader/execution_handler/execution_handler.py` - `_resolve_rng_seed` uses `SystemConfig.default()`
- `itrader/outils/time_parser.py`, `price_handler/data_provider.py`, `price_handler/exchange/CCXT.py` - `config.TIMEZONE` → module `TIMEZONE`
- `itrader/price_handler/sql_handler.py` - dead `from itrader import config` import removed
- `itrader/trading_system/live_trading_system.py` - `Config.SYSTEM_DB_URL` → `os.getenv` (D-live)
- `pyproject.toml` - pruned stale mypy overrides for deleted modules (legacy_config, config.exchange.schema)
- DELETED: flat `itrader/config.py`; `config/{portfolio,trading,data,system,exchange,core}/` packages (21 files)

## Decisions Made
- **Consolidate-then-split:** Task 1 placed all Pydantic models in `config/models.py` to dodge the `config/portfolio.py`-vs-`config/portfolio/` package import collision while the old config still shipped; Task 3 split into per-domain files after the old dirs were deleted (matches `files_modified`).
- **TIMEZONE without instantiating Settings:** read `Settings.model_fields["timezone"].default` — `Settings()` would require the fail-loud secret, which must NOT be needed on the backtest import path.
- **Dormant per-portfolio config methods** in `PortfolioHandler` (`update_portfolio_config`/`get_portfolio_config`) deferred to D-live rather than reconstructing a provider — they were never wired on the backtest path and no test exercises them.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] File-vs-package import collision forced a consolidate-then-split sequence**
- **Found during:** Task 1
- **Issue:** The plan's `files_modified` lists `config/portfolio.py` etc., but `config/portfolio/` (and the other 4 domain dirs) still existed and shadow same-named `.py` files — Python resolves the package, so `itrader.config.portfolio` imported the OLD dataclass, breaking the new test (`AttributeError: ... has no attribute 'model_validate'`).
- **Fix:** Consolidated all Pydantic models into `config/models.py` for Task 1 (no collision; old config untouched; suite green), then split into the per-domain files in Task 3 after `git rm`-ing the old dirs. End state matches `files_modified`.
- **Files modified:** itrader/config/models.py (Task 1), per-domain files (Task 3)
- **Verification:** `test_config_models.py` green at Task 1; per-domain imports resolve at Task 3; `PortfolioConfig is config.models.PortfolioConfig` True.
- **Committed in:** dd9abf5 (Task 1), 19cf1e7 (Task 3)

**2. [Rule 1 - Bug] get_exchange_preset must mirror the EXPORTED presets.py, not config.py's create_simulated_preset**
- **Found during:** Task 3 (full-suite run)
- **Issue:** `test_simulated_exchange.py` expected `high_fee` preset `exchange_name == "HighFeeSimulatedExchange"` with 4 presets. The old `config/exchange/__init__.py` exported `get_exchange_preset` from `presets.py` (4 presets, distinct values), NOT from `config.py::create_simulated_preset` (3 presets, `"HighFeeExchange"`). My first copy used the wrong source.
- **Fix:** Replicated all four `presets.py` definitions verbatim (default/realistic/high_fee/low_latency) as module-level factory funcs; dropped `create_simulated_preset`.
- **Files modified:** itrader/config/exchange.py
- **Verification:** `test_custom_config_initialization` green; full suite 321 pass.
- **Committed in:** 19cf1e7 (Task 3)

**3. [Rule 1 - Bug] Test import of deleted package path `itrader.config.exchange.config`**
- **Found during:** Task 3 (collection error)
- **Issue:** `test_simulated_exchange.py:20` imported `FeeModelType, SlippageModelType, ExchangeType` from the deleted `itrader.config.exchange.config`.
- **Fix:** Merged the import into the already-present `from itrader.config.exchange import ...` line (new module home).
- **Files modified:** test/test_execution_handler/test_exchanges/test_simulated_exchange.py
- **Verification:** Collection succeeds; suite green.
- **Committed in:** 19cf1e7 (Task 3)

**4. [Rule 3 - Blocking] Stale mypy overrides for deleted modules**
- **Found during:** Task 3
- **Issue:** `pyproject.toml` mypy overrides still listed `itrader.legacy_config` (deleted 03-02) and `itrader.config.exchange.schema` (deleted this plan).
- **Fix:** Removed both stale override entries (hygiene; mypy tolerated them but they were dead).
- **Files modified:** pyproject.toml
- **Verification:** `mypy --strict` clean (141 files).
- **Committed in:** 19cf1e7 (Task 3)

---

**Total deviations:** 4 auto-fixed (2 blocking, 2 bug). **Impact:** All necessary for correctness / behavior preservation. The consolidate-then-split (Dev 1) is a sequencing adjustment, not scope creep; end state matches the plan's intended per-domain file layout.

## Issues Encountered
- `from itrader import config` resolves to the **system config object** (formerly a dict, now `SystemConfig.default()`), NOT the config package — several `config.TIMEZONE` readers were latent-broken (dict had no `.TIMEZONE`); rewired them to the module-level `TIMEZONE` constant during the absorb step.

## Known Stubs
None. `Settings.database_url` is intentionally required-no-default (declared-but-unwired secret per D-02/D-live) — this is the M2-06 fail-loud criterion, not a stub.

## Threat Flags
None new. The single security-relevant change (fail-loud `SecretStr` secret) was in the plan's `<threat_model>` (T-03-05-SECRET, mitigate) and is implemented: required-no-default, masked repr, value via `.get_secret_value()`, tested.

## Config-collapse note (line count)
config/ tree is ~1,132 lines (down from 3,380 — 66% reduction). Slightly above the ~600-900 target because of (a) full 4-preset exchange fidelity for behavior preservation and (b) the dual public surface (`models.py` aggregate + `__init__.py` grouped re-export). Materially smaller and behavior-correct.

## Next Phase Readiness
- Config is now Pydantic v2; future plans construct models directly (no getters).
- Behavioral oracle byte-exact throughout (D-18 law held). The numeric oracle re-freeze (D-16) and the D-17 inertness gate remain plan 03-09's responsibility — this plan only asserts behavioral identity.
- No blockers.

## Self-Check: PASSED

- Created files verified present: config/models.py, config/settings.py, config/{portfolio,trading,data,system,exchange}.py, core/constants.py
- Task commits verified in git log: dd9abf5, 70af2b7, 19cf1e7
- Flat shadow itrader/config.py confirmed deleted
- mypy --strict clean (141 files); suite 321 pass / 4 skip / 1 xfail; behavioral oracle byte-exact

---
*Phase: 03-m2b-config-types-storage-seam-oracle-re-freeze*
*Completed: 2026-06-05*

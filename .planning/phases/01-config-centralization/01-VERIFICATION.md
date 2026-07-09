---
phase: 01-config-centralization
verified: 2026-07-09T11:12:07Z
status: passed
score: 6/6 must-haves verified
behavior_unverified: 0
overrides_applied: 0
re_verification: No — initial verification
---

# Phase 1: Config Centralization Verification Report

**Phase Goal:** Centralize all system-wide configuration into one import-safe `SystemConfig` (eager fields vs a lazy `sql` accessor), fold scattered module constants into their domain config, retire dead config, and introduce a typed `HaltReason` — the backtest path reading base defaults unchanged.
**Verified:** 2026-07-09T11:12:07Z
**Status:** passed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | `from itrader import config` exposes immutable base defaults; backtest reads unchanged and SMA_MACD oracle stays byte-exact `134/46189.87730727451` | ✓ VERIFIED | `poetry run pytest tests/integration/test_backtest_oracle.py -q` → 3 passed, byte-exact. `itrader/__init__.py:9` builds `config = SystemConfig.default()` at import; live end-to-end confirmed via `python -c "from itrader import config"`. |
| 2 | `SystemConfig` aggregates `performance`/`monitoring`/`runtime`(eager)/`sql`(lazy); Postgres arm resolved only on first access; import builds no `SqlSettings` | ✓ VERIFIED | `itrader/config/system.py`: `runtime: Settings = Field(default_factory=Settings)` (eager field, confirmed in `model_fields`); `sql` is a `@cached_property` returning `SqlSettings()`, NOT a pydantic field (confirmed `"sql" not in SystemConfig.model_fields`). `tests/integration/test_okx_inertness.py` asserts `"sql" not in _cfg.__dict__` post-import — green. `order` reclassified cardinality-N per CFG-01 owner amendment (explicitly documented in REQUIREMENTS.md, superseding the original spec §6b listing) and confirmed absent from `model_fields` at runtime. |
| 3 | Scattered module constants fold into domain config (`_STREAM_RECONNECT_*`→`StreamSettings`, `_WARMUP_MARGIN`/`_BACKFILL_PAGE`→`FeedProviderSettings`); `_OKX_*`/`_PAPER_*` gone (grep-clean); `extra` policy normalized | ✓ VERIFIED | `itrader/config/stream.py` (new): `StreamSettings` + `FeedProviderSettings`, both `extra="forbid"`. Grep-clean confirmed live: `_STREAM_RECONNECT`, `_WARMUP_MARGIN`, `_BACKFILL_PAGE`, `_OKX_STREAM\|_PAPER_STREAM\|_PAPER_EXPECTED` all return empty over `itrader/`. `_OKX_INTERVALS` (functional lookup, not a tunable) and `PAPER_PARITY_*` anchor confirmed still present. All 7 fold-site readers (`okx_provider.py`, `venue.py`, `okx.py`, `live_bar_feed.py`, `universe_handler.py`, `replay_provider.py`, `live_trading_system.py`) import and read the new config models (verified by grep of read sites, not just definitions). `SystemConfig` itself flipped `extra="ignore"`→`"forbid"`. |
| 4 | A typed `HaltReason` enum in `core/enums/system.py` replaces free-string halt reasons; off-vocabulary `'baseline-residual'` retired | ✓ VERIFIED | `itrader/core/enums/system.py`: `HaltReason(Enum)` with 5 members (`BASELINE_RESIDUAL`, `CONNECTOR_FATAL`, `RECONCILIATION_UNRESOLVED`, `DURABLE_HALT`, `DRIFT`). `grep -rn "'baseline-residual'" itrader/` returns exactly 1 line (the enum `.value` definition) — the call site at `live_trading_system.py:810` now passes `HaltReason.BASELINE_RESIDUAL.value`. Note: DRIFT was added post-plan via code-review fix `b2e88d29` (CR-01) because `portfolio_handler.py:839` fires a live, reachable `halt("drift")` call wired through `live_trading_system.py:678`; the plan's original "exactly 4 members" claim was a miscount corrected before phase close, and the test module + docstring were updated to match (`tests/unit/core/test_halt_reason.py::test_halt_reason_has_exactly_the_five_reachable_members` passes). |
| 5 | Dead-config audit removes unused settings + stale `__pycache__`; D-03a dual-validator paragraph applied to `CONVENTIONS.md` | ✓ VERIFIED | `grep -rn "settings/domains" itrader/` empty (zero YAML loaders); `settings/domains/system.default.yaml` + `trading.default.yaml` deleted (untracked/gitignored, confirmed absent from `settings/domains/`, only `portfolio.default.yaml` remains as intended). `git ls-files \| grep -c "__pycache__\|\.pyc$"` → 0. `.planning/codebase/CONVENTIONS.md` Pinned Decisions item 4 carries the CF-6 substance (`defense-in-depth`, `SimulatedExchange`-only-where-called nuance present; `aspirational` count 0 — stale pre-fix wording not reintroduced). |
| 6 | Both frozen milestone gates (oracle byte-exact, OKX import-inertness) stay green throughout the phase | ✓ VERIFIED | `poetry run pytest tests/integration/test_backtest_oracle.py -q` → 3 passed (134/46189.87730727451, check_exact). `poetry run pytest tests/integration/test_okx_inertness.py tests/unit/storage/test_import_quarantine.py -q` → 3 passed — including the GATE-01 quarantine regression introduced by 01-01 and fixed by orchestrator commit `f86fe5d2` (SqlSettings import moved under `TYPE_CHECKING` + lazy in-body import, confirmed present in `itrader/config/system.py`). |

**Score:** 6/6 truths verified (0 present, behavior-unverified)

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `itrader/config/system.py` | eager `runtime` field + lazy `sql` cached_property + `extra="forbid"` | ✓ VERIFIED | Present, substantive, wired; `SqlSettings` import lazy inside `TYPE_CHECKING` + property body (post-GATE-01-fix). |
| `itrader/config/stream.py` | `StreamSettings` + `FeedProviderSettings` (new) | ✓ VERIFIED | Present, pydantic+stdlib only, both models have `extra="forbid"` + `.default()` classmethod. |
| `itrader/core/enums/system.py` | `HaltReason` enum (typed vocabulary) | ✓ VERIFIED | Present, 5 members (incl. post-review `DRIFT`), stdlib-only imports preserved. |
| `tests/unit/config/test_system_config.py` | new unit test | ✓ VERIFIED | 5 tests, all pass. |
| `tests/unit/core/test_halt_reason.py` | new unit test | ✓ VERIFIED | 4 tests, all pass (updated for the 5-member set). |
| `tests/unit/config/test_stream_settings.py` | new unit test | ✓ VERIFIED | 6 tests, all pass. |
| `tests/integration/test_okx_inertness.py` | extended register-vs-build assertion | ✓ VERIFIED | `"sql" not in _cfg.__dict__` assertion present and green. |
| `.planning/codebase/CONVENTIONS.md` | updated Pinned Decisions item 4 (D-03a) | ✓ VERIFIED | CF-6 substance present; no regression to stale "aspirational" wording. |

### Key Link Verification

| From | To | Via | Status | Details |
|------|-----|-----|--------|---------|
| `itrader/__init__.py:9` | `SystemConfig.default()` | import-time construction | ✓ WIRED | Confirmed via live import: builds `config` with `sql` absent from `__dict__`. |
| `okx_provider.py`, `venue.py`, `okx.py` (exchange) | `itrader.config.stream.StreamSettings` | reconnect-family read at `__init__` | ✓ WIRED | grep confirms import + `StreamSettings()` construction + assignment at all 3 sites. |
| `live_bar_feed.py`, `universe_handler.py` | `FeedProviderSettings().warmup_margin` | warmup depth calc | ✓ WIRED | grep confirms read sites use the config field, module constant gone. |
| `okx_provider.py`, `replay_provider.py` | `FeedProviderSettings().backfill_page` | guard-clause default resolution | ✓ WIRED | Confirmed `limit = FeedProviderSettings().backfill_page` at both sites. |
| `live_trading_system.py:810` | `HaltReason.BASELINE_RESIDUAL.value` | baseline guard halt call | ✓ WIRED | grep confirms the free string survives only on the enum `.value` definition line. |
| `live_trading_system.py` paper-parity replay | `PAPER_PARITY_TIMEFRAME` anchor | WR-01 review fix | ✓ WIRED | Decoupled from `StreamSettings.okx_stream_timeframe`; the `run_paper_replay` guard now also checks timeframe drift (line ~1540). |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| SMA_MACD oracle byte-exact | `poetry run pytest tests/integration/test_backtest_oracle.py -q` | 3 passed | ✓ PASS |
| OKX import-inertness + GATE-01 quarantine | `poetry run pytest tests/integration/test_okx_inertness.py tests/unit/storage/test_import_quarantine.py -q` | 3 passed | ✓ PASS |
| Full unit suite | `poetry run pytest tests/unit -q` | 1769 passed | ✓ PASS |
| mypy --strict on changed source | `poetry run mypy itrader/config/system.py itrader/config/stream.py itrader/core/enums/system.py itrader/trading_system/live_trading_system.py` | Success: no issues found in 4 source files | ✓ PASS |
| Phase-01 new unit tests (15 assertions across 3 modules) | `poetry run pytest tests/unit/config/test_system_config.py tests/unit/core/test_halt_reason.py tests/unit/config/test_stream_settings.py -v` | 15 passed | ✓ PASS |
| grep-clean gates (`_STREAM_RECONNECT`, `_WARMUP_MARGIN`, `_BACKFILL_PAGE`, `_OKX_STREAM\|_PAPER_STREAM\|_PAPER_EXPECTED`, `settings/domains`) | `grep -rn ... itrader/` | all empty | ✓ PASS |
| `__pycache__`/`.pyc` tracked count | `git ls-files \| grep -c "__pycache__\|\.pyc$"` | 0 | ✓ PASS |
| No new dependency / poetry.lock unchanged | `git log` inspection of recent commits | no `poetry.lock`/`pyproject.toml` diffs in phase commits | ✓ PASS |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|-------------|-------------|--------|----------|
| CFG-01 | 01-01 | `SystemConfig` cardinality-1 aggregation, eager/lazy split, `order` excluded | ✓ SATISFIED | `model_fields` confirmed; `runtime` eager, `sql` lazy cached_property. |
| CFG-02 | 01-01 | `from itrader import config` base defaults, backtest unchanged | ✓ SATISFIED | Oracle byte-exact; live import confirmed. |
| CFG-03 | 01-04 | Module constants fold into domain config | ✓ SATISFIED | `StreamSettings`/`FeedProviderSettings` created + wired at all 7 readers; grep-clean. |
| CFG-04 | 01-01 | Dead-config audit + `__pycache__` hygiene | ✓ SATISFIED | Zero YAML loaders; orphaned overrides deleted; 0 tracked pycache. |
| CFG-05 | 01-02 | Typed `HaltReason` enum | ✓ SATISFIED | 5-member enum (corrected via CR-01 review fix); baseline-residual retired. |
| CFG-06 | 01-03 | D-03a dual-validator paragraph in CONVENTIONS.md | ✓ SATISFIED | Item 4 updated with CF-6 substance, no stale-wording regression. |

All 6 phase requirement IDs (CFG-01..06) declared in plan frontmatter are accounted for and cross-referenced against `.planning/REQUIREMENTS.md` (all listed `Status: Complete` under Phase 1). No orphaned requirements found — REQUIREMENTS.md maps exactly CFG-01..06 to P1, matching the plans' declared `requirements:` fields.

### Anti-Patterns Found

No `TBD`/`FIXME`/`XXX`/`TODO`/`HACK`/`PLACEHOLDER` markers found in any of the 13 phase-modified source files. No blocker or warning anti-patterns detected.

### Code-Review Findings (01-REVIEW.md) — Resolution Confirmed

- **CR-01 (critical, blocker):** `HaltReason` omitted the reachable `"drift"` halt reason and the test pinned a false "no-drift" invariant. **Fixed** in `b2e88d29` — `DRIFT` member added, docstring corrected, test updated to assert 5 members. Verified live in code and passing tests.
- **WR-01 (warning):** paper-parity replay timeframe coupled to the live-tunable `StreamSettings.okx_stream_timeframe`, with no timeframe check in the parity-drift guard. **Fixed** in `2c4aaac1` — `PAPER_PARITY_TIMEFRAME` anchor introduced, decoupled from the live knob, and the `run_paper_replay` guard extended to check timeframe. Verified live in code.
- **IN-01 (info):** config models default-constructed per read site rather than injected — documented as the intentional P1 seam (P5 composition-root injection is the follow-up). No action required in this phase.

### Deferred Items (documented, not gaps)

- **P8 halt-literal migration:** the remaining three halt call sites (`connector-fatal`, `reconciliation-unresolved`, `durable-halt`) and the `halt(reason: str)` signature migration are explicitly deferred to Phase 7/8 (SafetyController) per D-11 and tracked in `.planning/todos/pending/off-vocabulary-halt-reason-baseline-residual-wr04.md`. This is a documented scope boundary, not a phase-01 gap — CFG-05's phase-01 scope was only the enum definition + the one mandatory retirement.
- **P5 composition-root config injection:** `StreamSettings()`/`FeedProviderSettings()` are default-constructed per call site rather than injected via a shared composition root — documented (01-REVIEW.md IN-01) as the P1 seam that Phase 5 (`VenueBundle`/composition root work) replaces.

### Documented Deviations (not gaps — explicitly recorded in project docs)

- **`order` field exclusion vs ROADMAP.md wording:** ROADMAP.md Phase 1 Success Criterion #2 literal text still lists `SystemConfig` aggregating "`performance`/`monitoring`/`runtime`/`sql`/`order`" — but REQUIREMENTS.md's CFG-01 entry explicitly states the owner amendment (2026-07-09) reclassifying `order` as cardinality-N and excluding it from `SystemConfig`, "intentionally supersed[ing] the spec §6b listing of `order` as a `SystemConfig` singleton." The code correctly excludes `order` (confirmed: `'order' not in SystemConfig.model_fields`), matching the authoritative REQUIREMENTS.md text and the PLAN 01-01 must-haves, not the stale ROADMAP.md wording. Treated as VERIFIED against the requirements-doc contract, since ROADMAP.md was not updated to reflect the owner's later amendment.

### Human Verification Required

None. All must-haves and success criteria for this phase are config-plumbing/plumbing-wiring facts verifiable via unit tests, grep, and the two frozen milestone gates — no UI, real-time, or external-service behavior is in scope.

### Gaps Summary

No gaps found. All 6 CFG requirements are implemented, tested, and wired; both milestone-wide gates (oracle byte-exact, OKX import-inertness including the GATE-01 quarantine regression discovered and fixed mid-phase) are green; the full unit suite (1769 tests) passes; mypy --strict is clean on changed files; no debt markers; no dependency/lockfile changes. The two code-review findings (CR-01 blocker, WR-01 warning) were both fixed and verified during execution, not merely claimed.

---

_Verified: 2026-07-09T11:12:07Z_
_Verifier: Claude (gsd-verifier)_

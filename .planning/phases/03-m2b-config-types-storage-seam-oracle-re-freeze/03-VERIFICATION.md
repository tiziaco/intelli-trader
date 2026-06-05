---
phase: 03-m2b-config-types-storage-seam-oracle-re-freeze
verified: 2026-06-05T00:00:00Z
status: passed
score: 4/4 must-haves verified
overrides_applied: 0
resolution: "Owner dispositioned WR-01 (2026-06-05) as accept + note + follow-up. SC3's weekly sub-claim is accepted: the daily-UTC golden path — the only timeframe SMA_MACD exercises — is byte-exact and correct. The _aligned docstring was qualified to daily-UTC-only with an explicit weekly epoch-Thursday caveat, and a follow-up to correct/test weekly+DST anchoring was filed at .planning/todos/pending/weekly-anchor-time-parser.md. All 4 SCs met."
gaps:
human_verification:
  - test: "[RESOLVED 2026-06-05] SC3 weekly check_timeframe epoch-anchor disposition"
    expected: "Owner accepts epoch-anchored daily-UTC behavior (golden path byte-exact); weekly/DST anchoring correctness deferred via documented caveat + follow-up todo."
    why_human: "Resolved by owner decision (accept + note + follow-up). Docstring qualified, follow-up filed. Daily oracle unaffected."
---

# Phase 03: M2b Config-Types-Storage-Seam-Oracle-Re-Freeze Verification Report

**Phase Goal:** Collapse the over-engineered config package to Pydantic models, centralize scattered
types, route portfolio-handler state through an in-memory storage seam, finalize time_parser timing
correctness, delete dead modules, complete the bulk pytest conversion, and re-freeze the numerical oracle
after the Decimal shift while confirming the behavioral oracle is unchanged. Closes the #34 and #36 spans
started in M1.
**Verified:** 2026-06-05T00:00:00Z
**Status:** human_needed
**Re-verification:** No — initial verification

---

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | SC1: config/ collapses to Pydantic v2 models + pydantic-settings; one model round-trips backtest-dict and live-JSONB forms; no working secret defaults | VERIFIED | `itrader/config/settings.py` has `SecretStr database_url` with no default; `Settings()` with no env raises `ValidationError`; `PortfolioConfig.default().model_dump(mode="json")` round-trips; config/ is 1132 lines (down from 3380); getters/registry deleted; flat `itrader/config.py` shadow deleted; 03-05 commits dd9abf5, 70af2b7, 19cf1e7 present |
| 2 | SC2: Portfolio-handler manager state routes through an in-memory storage seam; order audit and transaction timestamps are event-derived/deterministic; modify_order routes through the validated path | VERIFIED | `PortfolioStateStorage` ABC in `portfolio_handler/base.py:93`; `InMemoryPortfolioStateStorage` in `storage/in_memory_storage.py`; `PortfolioStateStorageFactory.create("backtest")` returns in-memory backend; managers have no owned `self._*` containers (grep confirmed empty); `add_state_change` event-derived (no bare `datetime.now()` at that site); `modify_order` routes through `add_state_change` at :466; 03-07 commits aa371a7, bd1e3f4, cebbec7, 9d0fecc present |
| 3 | SC3: time_parser timing is correct (DST-immune; to_timedelta case-insensitive with week/month support; dead helpers removed); dead modules deleted; bulk unittest->pytest conversion lands | PARTIAL — WARNING | `_aligned` seam verified at `time_parser.py:127`; epoch anchor is DST-immune and correct for the golden daily UTC case; to_timedelta case-insensitive, week returns timedelta(weeks=1), month raises a clear error, None guarded, unknown raises; dead helpers removed; 4 dead modules deleted; all 29 unittest.TestCase files converted to pytest (346 collected, 0 unittest.TestCase hits); BUT: the `check_timeframe` epoch-anchor silently changes weekly firing behavior (fires on Thursdays only vs any midnight previously) — WR-01 flagged by code review; the docstring claims "behavioral oracle is unchanged" but this is only true for the golden daily UTC case; there is no test for weekly check_timeframe firing; SC3's claim "anchoring fixed for...week" is overstated |
| 4 | SC4: Golden-master gate: numerical oracle re-frozen after Decimal precision shift; behavioral oracle verified unchanged | VERIFIED | `tests/golden/summary.json` shows `final_equity: 53229.68512642488`; `xfail`/`_D15_RTOL`/`_D15_ATOL`/`_DEF_02_08_A` absent from oracle test; all numeric asserts use `check_exact=True`; D-17 inertness gate confirmed byte-exact vs `M2A-INERTNESS-REF/summary.json`; both oracle tests pass (2 passed in 5.52s); commit b146af4 present |

**Score:** 3/4 truths verified (SC3 partial — one sub-claim uncertain/partial)

---

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `.planning/phases/.../M2A-INERTNESS-REF/summary.json` | D-17 inertness baseline (M2a-end engine output) | VERIFIED | File exists, non-empty; numeric fields match tests/golden/summary.json exactly |
| `pyproject.toml` | pydantic + pydantic-settings dependency declarations | VERIFIED | `pydantic = "^2.13"`, `pydantic-settings = "^2.14"` present; `testpaths = ["tests"]` |
| `itrader/config/settings.py` | Settings(BaseSettings) with fail-loud required-no-default SecretStr secrets | VERIFIED | `database_url: SecretStr` at line 32 with no default; `Settings()` raises `ValidationError` programmatically confirmed |
| `itrader/core/constants.py` | FORBIDDEN_SYMBOLS + SUPPORTED_CURRENCIES/SUPPORTED_EXCHANGES (literal-concat bug fixed) | VERIFIED | File exists; docstring documents the BTG/USDT + USDP/USDT + BCHABC/USDT + 1INCH/USDT comma-fix |
| `itrader/config/portfolio.py` | PortfolioConfig Pydantic model + .default() factory classmethod | VERIFIED | `PortfolioConfig.default()` works; `model_dump(mode="json")` round-trips |
| `itrader/core/enums/execution.py` | Relocated class-based FillStatus with _missing_ parse | VERIFIED | `class FillStatus(Enum)` at line 59; `_missing_` at line 78; `FillStatus("executed") is FillStatus.EXECUTED` confirmed |
| `itrader/core/enums/portfolio.py` | CashOperationType/PositionEvent/MetricsPeriod/TransactionState + TransactionType._missing_ | VERIFIED | All 4 classes present; each has a `_missing_` classmethod |
| `itrader/outils/time_parser.py` | Epoch-aligned check_timeframe via single _aligned seam + corrected to_timedelta | VERIFIED (with warning) | `_aligned` at line 127; check_timeframe delegates at line 162; epoch anchor confirmed DST-immune for daily UTC; to_timedelta case-insensitive, week/month/unknown/None all handled; dead helpers absent — WR-01 caveat on weekly behavior documented below |
| `itrader/portfolio_handler/base.py` | PortfolioStateStorage ABC | VERIFIED | `class PortfolioStateStorage(ABC)` at line 93 |
| `itrader/portfolio_handler/storage/storage_factory.py` | PortfolioStateStorageFactory.create(environment) | VERIFIED | Factory present; backtest/test → in-memory; live → raises (ValueError); bogus → ValueError |
| `itrader/portfolio_handler/position/`, `transaction/`, `cash/`, `metrics/` | Subdomain packages | VERIFIED | All 4 dirs exist with `__init__.py` re-exports |
| `tests/conftest.py` | Root conftest with folder-derived TYPE-marker registration + shared fixtures | VERIFIED | Folder-derived `unit`/`integration` markers; `global_queue` fixture; auto-marking in `pytest_collection_modifyitems` |
| `tests/golden/summary.json` | Re-frozen numerical oracle | VERIFIED | `final_equity: 53229.68512642488`, `trade_count: 134`; matches inertness reference exactly |
| `tests/integration/test_backtest_oracle.py` | Oracle test with tolerance removed; numeric cols exact; behavioral identity active | VERIFIED | `check_exact=True` at 4 sites; no `xfail`/tolerance markers; both test functions present and passing |

---

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `itrader/__init__.py` / `portfolio_handler.py` / `execution_handler.py` | Pydantic model constructors | direct construction, getters deleted | WIRED | `grep get_config_registry itrader/` returns only docstring; consumers construct `PortfolioConfig`/`SystemConfig.default()` directly |
| `config.TIMEZONE` consumers (time_parser, data_provider, CCXT) | Settings.timezone / core constant | absorbed from deleted flat config.py shadow | WIRED | `config/__init__.py` re-exports from `core.constants` and `settings.Settings`; flat shadow absent |
| `Portfolio` | `PortfolioStateStorage` (injected via factory) | `PortfolioStateStorageFactory.create("backtest")` | WIRED | `portfolio.py:91` sets `self.state_storage` before constructing managers; confirmed at `portfolio.py:91` |
| `Order.add_state_change` / `modify_order` | event-derived time (not datetime.now()) | `add_state_change(time=event_time)` | WIRED | `datetime.now()` appears only in `created_at`/`updated_at` field defaults (construction-boundary, not the audit path); `add_state_change` and `modify_order` use event-derived time |
| `M2b-end scripts/run_backtest.py::main output` | `M2A-INERTNESS-REF` baseline | automated byte-exact inertness diff | WIRED | D-17 gate ran; golden summary matches inertness reference byte-exact; commit b146af4 |
| `tests/golden/` | tests/integration/test_backtest_oracle.py | golden path fixtures in `tests/integration/conftest.py` | WIRED | Makefile targets and `testpaths=["tests"]` updated; oracle test reads from `tests/golden/` |

---

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
|----------|--------------|--------|-------------------|--------|
| `tests/integration/test_backtest_oracle.py` | `oracle_run` fixture | `scripts/run_backtest.py::main()` invoked in-process | Yes — full SMA_MACD backtest over golden CSV | FLOWING |
| `tests/golden/summary.json` | `final_equity`, `trade_count` | Regenerated from M2b-end Decimal run | Yes — 134 trades, equity 53229.685 | FLOWING |
| `InMemoryPortfolioStateStorage` | positions/transactions/cash-ops/snapshots | Four manager `self._storage` writes (no owned containers) | Yes — routing confirmed by grep of manager files | FLOWING |

---

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| Settings() raises on missing secret | `python -c "from itrader.config.settings import Settings; Settings()"` | `ValidationError: 1 validation error for Settings... Field required` | PASS |
| FillStatus case-insensitive parse | `FillStatus('executed') is FillStatus.EXECUTED` | True | PASS |
| FillStatus unknown raises | `FillStatus('nope')` | `ValueError: Unknown FillStatus: 'nope'` | PASS |
| PortfolioStateStorageFactory.create("backtest") | returns InMemoryPortfolioStateStorage | `InMemoryPortfolioStateStorage` | PASS |
| PortfolioStateStorageFactory.create("live") raises | raises ValueError with db_url message | ValueError raised | PASS |
| Oracle tests both pass | `pytest tests/integration/test_backtest_oracle.py -v` | 2 passed in 5.52s | PASS |
| Full suite | `poetry run pytest --tb=no -q` | 346 passed | PASS |
| mypy --strict | `poetry run mypy --strict itrader/` | `Success: no issues found in 148 source files` | PASS |

---

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|-------------|-------------|--------|----------|
| M2-06 | 03-05 | config/ collapses to Pydantic v2 + pydantic-settings; round-trip; fail-loud secrets | SATISFIED | settings.py SecretStr; getters deleted; flat shadow deleted; 1132-line tree |
| M2-07 | 03-03 | Shared enums centralized in core/enums; string→enum maps replaced | SATISFIED | FillStatus + 4 manager enums in core/enums with _missing_; fill_status_map/transaction_type_map deleted |
| M2-08 | 03-06+03-07 | Portfolio manager state through in-memory storage seam | SATISFIED | PortfolioStateStorage ABC + factory + InMemory backend; managers route through seam |
| M2-09 | 03-07 | Order timestamps event-derived; modify_order validated path | SATISFIED (with IN-03 note) | add_state_change event-derived; modify_order routes through it; `created_at` wall-clock default remains (WR-03) but is outside the requirement scope per plan's stated acceptance criteria |
| M2-10 | 03-04 | time_parser timing correct: anchoring fixed, case-insensitive, week/month, dead helpers removed | PARTIAL — WARNING | DST/daily verified; to_timedelta week/case/month/unknown/None all correct; dead helpers removed; BUT weekly check_timeframe behavior changed (epoch-Thursday, not any-midnight) — WR-01 |
| M2-11 | 03-02 | Dead modules deleted (legacy_config, outils/profiling, outils/strategy, orphaned screener_event_handler) | SATISFIED | All 4 absent; no importers remain |
| M2-12 | 03-08 | Bulk unittest→pytest conversion; tests/ split by TYPE | SATISFIED | 0 unittest.TestCase files in tests/; 346 tests collected; testpaths=["tests"]; folder-derived markers; 29 conversions |
| M2-13 | 03-09 | Numerical oracle re-frozen; behavioral oracle unchanged | SATISFIED | D-17 inertness gate byte-exact; check_exact=True; xfail removed; 2 oracle tests pass |

---

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| `itrader/order_handler/order.py` | 294 | `TODO: check if i have to store the state changes permanently in sql when in live trading / production` | WARNING | Inline TODO without a formal ticket ID (e.g. DEF-* or issue #N). References D-sql deferred work conceptually but not by a traceable reference. Per debt-marker gate, `TODO` is WARNING severity (not a BLOCKER like TBD/FIXME/XXX). |
| `itrader/order_handler/order.py` | 59–60 | `created_at: datetime = field(default_factory=datetime.now)` / `updated_at: datetime = field(default_factory=datetime.now)` | WARNING | WR-03: construction-boundary timestamps remain wall-clock. `updated_at` is overwritten on first `add_state_change` (event-derived in practice), but `created_at` is never reset and remains wall-clock. Does not reach the oracle output today. Outside M2-09's stated acceptance criteria but contradicts the phase's D-12 event-derived invariant. |
| `itrader/outils/time_parser.py` | 127–145 | `_aligned` docstring claims "behavioral oracle is unchanged" without qualifying that this is only true for daily 00:00 UTC | WARNING | WR-01: The epoch-anchor changes `check_timeframe` firing for weekly (fires on Thursdays only vs any midnight previously). No test covers weekly `check_timeframe` firing. The docstring is misleading for non-daily timeframes. |
| `itrader/portfolio_handler/cash/cash_manager.py` (and 3 sibling managers) | ~68–71 | Standalone fallback creates a separate in-memory backend per manager when `portfolio.state_storage` is `None` | WARNING | WR-02: In production `Portfolio` usage the seam is always shared (set in `_init_managers` before manager construction). But if a manager is constructed standalone (e.g. in a minimal mock test) without `state_storage`, each gets an independent store — cross-manager invariants would silently break. Not a defect on the backtest path; a latent correctness trap in testing. |

---

### Human Verification Required

#### 1. SC3 Weekly check_timeframe Epoch-Anchor Disposition (WR-01)

**Test:** Review whether the `check_timeframe` weekly epoch-anchor behavior change is intentional and whether SC3/M2-10's claim "anchoring fixed for...week" should be interpreted as referring only to `to_timedelta` week-support (which is fully delivered) or also to `check_timeframe` firing for weekly timeframes (which now behaves differently than before).

**Expected:** Owner explicitly states one of:
  - (a) The epoch-anchor for weekly is an intentional improvement; "anchoring fixed for...week" in SC3 referred to `to_timedelta` week-support, not `check_timeframe` weekly firing; M2-10 is considered fully met. OR
  - (b) The weekly epoch-anchor behavior change is a gap; the docstring must be updated to document the behavior change explicitly; a follow-up task is logged to either restore midnight-relative weekly firing or document the Thursday-anchor as the new canonical behavior.

**Why human:** Code inspection and the code review (03-REVIEW.md WR-01) confirm the behavior change is real and no test covers it. The old behavior (fires on every midnight) vs new behavior (fires only on epoch-aligned midnights, which for weekly = Thursdays) is verifiably different. Whether the new behavior is "correct" vs the old behavior, and whether SC3 is therefore met or only partially met, requires an owner decision — not a programmatic determination.

---

### Gaps Summary

No hard BLOCKER gaps were found. All four phases of goal achievement have evidence:
1. Config collapse to Pydantic v2 with fail-loud secrets — fully delivered.
2. Portfolio storage seam and event-derived order timestamps — fully delivered.
3. time_parser DST-immune epoch seam, to_timedelta corrections, dead helpers removed, dead modules deleted, bulk pytest conversion — fully delivered EXCEPT the weekly `check_timeframe` anchor behavior is undocumented as a behavior change (WR-01 WARNING).
4. Numerical oracle re-frozen byte-exact; behavioral oracle unchanged — fully delivered.

The single human-verification item is WR-01 (weekly epoch-anchor disposition for SC3). If the owner accepts interpretation (a) above, SC3 is fully met and the phase passes. If interpretation (b), a gap exists requiring docstring correction and/or a follow-up task.

The IN-03 TODO at `order.py:294` is a WARNING per debt-marker gate rules (TODO is warning-tier, not BLOCKER-tier). The WR-02 standalone manager fallback and WR-03 `created_at` wall-clock are code-review findings that do not block the phase goal on the backtest path.

---

### Deferred Items

No items identified as deferred to later phases from this verification pass.

---

_Verified: 2026-06-05T00:00:00Z_
_Verifier: Claude (gsd-verifier)_

# Phase 3: M2b — Config, Types, Storage Seam & Oracle Re-Freeze - Research

**Researched:** 2026-06-05
**Domain:** Brownfield structural refactor (Pydantic config collapse, enum centralization, portfolio storage seam, time_parser, pytest restructure, golden-master numerical re-freeze)
**Confidence:** HIGH (all code anchors verified in-tree; Pydantic v2 idioms verified by direct execution)

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Config collapse (M2-06, #12/#13)**
- **D-01: Clean break on the public config API.** Delete `core/registry.py`, `core/provider.py`, `core/validator.py`, every `schema.py`, the `to_dict`/`from_dict` machinery, the mtime hot-reload, AND the `config/__init__.py` getters (`get_config_registry`, `get_*_config_provider`). Rewire the ~4 in-scope call sites (`itrader/__init__.py`, `portfolio_handler.py`, `execution_handler.py`) to construct Pydantic models directly. No vestigial compat shim — `mypy --strict` catches any missed site. End-state target ~600–900 lines.
- **D-02: Minimal `Settings(BaseSettings)` stub.** Build `Settings(BaseSettings)` with the fields the backtest path actually reads (timezone, log_level, environment). Declare secrets (DB URL, API keys) as **required-no-default** `SecretStr`/`Optional` so they **fail loud** if live ever runs — but do NOT wire DB/exchange auth (D-live). Satisfies M2-06's "no working secret defaults" without building live infrastructure.
- **D-03: Reference-data literals → `core/constants.py`; presets → factory classmethods.** `FORBIDDEN_SYMBOLS`, `SUPPORTED_CURRENCIES`/`SUPPORTED_EXCHANGES` → plain `core/constants.py`. Convert domain presets (`presets.py`/`defaults.py`) to Pydantic model factory classmethods (e.g. `PortfolioConfig.default()`). One source of truth per the #13 table. Fix the `'BTG/USDT' 'USDP/USDT'` implicit-concat literal bug while moving them.

**Type centralization (M2-07, #15)**
- **D-04: Relocate + de-map only — keep the three lifecycle vocabularies DISTINCT.** Centralize each shared enum in `core/enums`; replace scattered string→enum dicts (`transaction_type_map`, `event_type_map`, `fill_status_map`) and their buggy `ValueError('Value %s', x)` with a `_missing_`/`from_string` classmethod **on the enum** (case-insensitive parse, raise a real f-string error on unknown). **Do NOT merge** `OrderStatus`/`FillStatus`/`TransactionState` — the `FillStatus.EXECUTED → OrderStatus.FILLED` mapping in `order_manager` *is* the intended exchange-truth→mirror reconciliation and must be preserved.
- **D-05: Move `FillStatus` now, leave `EventType` for M3.** Relocate `FillStatus` (and the inline manager category enums — `CashOperationType`, `PositionEvent`, `MetricsPeriod`, `TransactionState`) to `core/enums`. Leave `EventType` inline in `event.py` — M3 (#11) reworks it.

**time_parser finalization (M2-10, #36)**
- **D-06: Epoch-anchoring now, isolated in one replaceable seam.** `check_timeframe` uses `int(ts.timestamp()) % tf == 0` (Unix-epoch anchor) as the single policy, isolated in ONE well-named function (e.g. `_aligned(ts, tf)`). Market-tz local anchoring is rejected.
- **D-07: UTC-everywhere + tz-for-display is the permanent foundation.** Store/compute instants in UTC (epoch); render in `config.TIMEZONE`.
- **D-08: `to_timedelta` case-insensitive, support `w`, raise on `M`/unknown.** Case-insensitive (`1H`/`1D`/`1W`), add `w` (week), **raise** on `M` (month) and any unknown unit (no silent `None`). Delete dead buggy helpers (`format_timeframe`, `elapsed_time`, `round_timestamp_to_frequency`); fix tab/space mix. Guard `timeframe is None`.

**Portfolio storage seam (M2-08, M2-09, #18/#19)**
- **D-09: One unified `PortfolioStateStorage` in a peer `portfolio_handler/storage/` package.** Single interface covering transactions/positions/cash-ops/metrics — one in-memory backend per `Portfolio`, one factory entry, mirroring `order_handler/storage/`. Storage stays a **peer** of the subdomain folders — do NOT put a storage class inside each manager folder.
- **D-10: Full mirror of the order pattern — route ALL manager state through the seam.** Working state (open positions, reserved cash) AND append-only records (transaction history, closed positions, cash operations, metrics snapshots) route through the seam. Single-threaded in-memory backend stays dict-fast; live persistence later is a pure backend swap.
- **D-11: Per-subdomain subpackage reorg, as isolated pure-move commits.** Restructure into `position/`, `transaction/`, `cash/`, `metrics/` + peer `storage/`. Rehomes inline #15 manager dataclasses. **Standalone behavior-preserving commits, separate from storage-seam logic and separate from the pytest move.** Folders named by subdomain (`position/`, not `position_manager/`).
- **D-12: Timestamp determinism (M2-09).** Thread real event/fill time through `add_state_change` (default to event time, never `datetime.now()`); route `add_fill`'s `fill_time` to the recorded transition timestamp; route `modify_order` through the single validated `add_state_change` path (remove duplicated direct append). Transaction record timestamps event-derived. Uses M2a's injected clock. Decide durable record shapes (Decimal money, UUID ids, event-time) — no DB code.

**pytest conversion + restructure (M2-12, #40)**
- **D-13: Full restructure to `tests/{unit,integration}` split-by-type.** Move `test/` → `tests/`, split by *type*, layered conftests, rework `DIR_MARKERS`/`testpaths` from path-segment-**domain** to folder-derived **type** markers. Mechanical, behavior-preserving: `git mv` to preserve history, **same test count + green suite at every commit**.
- **D-14: Convert ALL remaining `unittest.TestCase` files, file-by-file.** `TestCase`→functions/fixtures, `setUp`→fixtures, `self.assertX`→`assert`, `assertRaises`→`pytest.raises`; one file per commit asserting identical test count. **No big-bang.** Fix any surfaced `ResourceWarning` at the leak, never widen `filterwarnings`.
- **D-15: unit/integration boundary = "more than one collaborating component."** Unit = drives ONE component in isolation (may import several classes from its own domain + a real `global_queue`). Integration = asserts interaction *across* components. Document in conftests/README.

**Oracle re-freeze (M2-13) — the golden-master gate**
- **D-16: Byte-exact re-freeze, all tolerance removed.** After every other M2b change lands, regenerate `test/golden/{trades,equity}.csv` + `summary.json`; assert BOTH behavioral identity AND numeric columns (`final_cash`/`final_equity`/`total_realised_pnl`/`total_equity`) **byte-exact** henceforth; delete the D-15 transitional tolerance and DEF-02-08-A skip. **The re-freeze is the LAST step of the phase.**
- **D-17: Strict inertness gate before re-freeze.** Capture the M2a-end oracle output as a reference at M2b start; require the M2b-end run to equal that reference **byte-exact (behavioral AND numeric)** before re-freezing. Any non-zero diff **BLOCKS** the re-freeze pending owner explanation, logged as a COVERAGE-INDEX §E delta. (Expected numeric value is the already-characterized M2a Decimal-end number.)
- **D-18: Behavioral identity stays byte-exact and active throughout.** `test_oracle_behavioral_identity` remains a hard active assertion at every M2b commit. A `time_parser` firing-schedule shift is a **STOP / investigate** — never a re-baseline reason.

### Claude's Discretion
- Exact Pydantic model field definitions, validators (`Field(gt=0, le=1)`, `@field_validator`), and the `model_validate`/`model_dump(mode="json")` round-trip plumbing.
- The `_missing_` vs explicit `from_string` classmethod choice per enum, and exact error messages.
- The `PortfolioStateStorage` method signatures and the in-memory backend's internal structures.
- Layered-conftest fixture placement (root vs `unit/` vs `integration/`), fixture naming-by-intent, and the marker registration home (`pyproject.toml markers` list vs `pytest_configure` in conftest — pick exactly ONE, never both).
- Dead-module deletion (M2-11) is mechanical — verify zero in-scope importers before each delete.
- Sequencing of the structural moves (config / enums / time_parser / storage seam + reorg / pytest move / dead-code), provided the oracle re-freeze (D-16/D-17) is strictly LAST.

### Deferred Ideas (OUT OF SCOPE)
- **Stock support — session / exchange-calendar alignment** → future milestone. time_parser anchor (D-06) is a single replaceable function so this plugs in later.
- **`EventType` relocation to `core/enums`** → M3 (Phase 4, #11).
- **`TransactionState` rework + atomic transactions/rollback** → M4 (#16). M2b only relocates the enum and routes state through the seam.
- **Cash-through-`CashManager` (#22) + DEF-01-A commission reconciliation** → M4.
- **Postgres/JSONB backend for `PortfolioStateStorage`** → D-sql milestone. M2b ships only the in-memory backend (durable record shapes decided now).
- **Reporting split + `EngineLogger` delete (#14/#38), universe collapse (#33), `calculate_signal` contract (#24)** → M5b (Phase 7).
- **General per-cryptocurrency precision registry** → later (only BTCUSD traded).
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| M2-06 | `config/` collapses to Pydantic v2 + `pydantic-settings`; one model round-trips backtest-dict and live-JSONB; no working secret defaults | Pydantic v2.13.4 / pydantic-settings 2.14.1 verified on PyPI; `model_validate`/`model_dump(mode="json")` round-trip verified by execution (Decimal→str, UUID→str); `SecretStr` required-no-default pattern from official docs; current `config/` = 3,380 lines / 21 files + flat shadow `itrader/config.py` |
| M2-07 | Shared enums/entities centralized in `core/enums`; scattered string→enum maps + buggy `ValueError`s replaced | `core/enums/` structure verified (order/portfolio/execution); all enums use **functional `Enum(...)` syntax** (must convert to class syntax to carry `_missing_`/`from_string`); map sites located (`event.py:14,23`, `transaction.py:13`) |
| M2-08 | Portfolio-handler manager state routes through in-memory storage seam; durable record shapes decided | `order_handler/storage/` template read in full (ABC in `order_handler/base.py`, factory, in-memory backend); four managers' state containers located at exact lines |
| M2-09 | Order audit + transaction timestamps event-derived/deterministic; `modify_order` through validated path | `order.py` `datetime.now()` at :269,277,284,286,288,436,437,443; `add_fill(fill_time)` at :297; `modify_order` direct append at :440-448; injected `Clock` exists at `core/clock.py` |
| M2-10 | `time_parser` timing correct; `to_timedelta` case-insensitive w/ week/month; dead helpers removed | `time_parser.py` read in full; `check_timeframe` uses midnight-of-day anchor (NOT epoch), `to_timedelta` already raises-on-unknown but not case-insensitive; dead helpers present |
| M2-11 | Dead modules deleted (`legacy_config.py`, `outils/profiling.py`, `outils/strategy.py`, orphaned `screener_event_handler.py`) | All four files confirmed present with ZERO importers; `legacy_config` + `screener_event_handler` already in mypy overrides |
| M2-12 | Bulk `unittest`→pytest conversion; layered `tests/{unit,integration}` | 37 test files, 31 still `unittest.TestCase`, 6 pytest-native; `test/conftest.py` `DIR_MARKERS` read; markers in `pyproject.toml:56-65` |
| M2-13 | Numerical oracle re-frozen after Decimal shift; behavioral oracle verified unchanged | `test/test_integration/test_backtest_oracle.py` read (behavioral-identity test exact/active + numeric-values test xfail w/ D-15 tolerance); `scripts/run_backtest.py::main` writes `output/{trades,equity}.csv`+`summary.json`; golden assets present |
</phase_requirements>

## Summary

Phase 3 (M2b) is a **pure internal structural refactor** with one numerical re-baseline gate. Every change is behavior-preserving against the M1 behavioral oracle; the only change with any oracle-firing risk is the `time_parser` epoch-anchor. There is no new external surface — no network, auth, crypto, or user input beyond config files. The risk profile is almost entirely *regression risk* (breaking the green suite or shifting the oracle), not *implementation difficulty*.

All code anchors cited in CONTEXT.md were spot-checked against the live tree and are substantially accurate (line numbers drift by a few lines in a couple of cases — corrected below). Two CONTEXT/orchestrator claims are **wrong and must be flagged to the planner**: (1) Pydantic is **NOT** currently a dependency (not in `pyproject.toml`, not in `poetry.lock`) — it must be added via Poetry; (2) the `OrderStorage` ABC lives in `itrader/order_handler/base.py`, **not** `storage/base.py`. A third critical discovery: a **flat `itrader/config.py` module (3,542 bytes) shadows the `config/` package** and is the *real* source of `FORBIDDEN_SYMBOLS`/`TIMEZONE` consumed via `config.TIMEZONE`; the M1 fix wired `config/__init__.py` to load it via `importlib`. The D-01 clean break must delete/absorb this flat shadow too, or the consumers break.

**Primary recommendation:** Sequence the phase as independent behavior-preserving waves (dead-code purge → enums → time_parser → config collapse → storage seam + reorg → pytest move), each green at every commit, with the D-17 inertness gate captured at phase start and the D-16 byte-exact re-freeze as the strictly-last task. Add `pydantic ^2.13` + `pydantic-settings ^2.14` via Poetry as the very first task. Convert the functional-syntax enums to class-based `Enum` subclasses to host `_missing_`/`from_string`.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Config model definition + validation | Core/Config | — | Pydantic models are pure value objects in `config/`; consumed by handlers at construction |
| Secret declaration (fail-loud) | Core/Config (`Settings(BaseSettings)`) | — | `pydantic-settings` reads env; secrets never wired to live (D-live) |
| Enum vocabularies + string parsing | Core (`core/enums`) | — | Cross-cutting types used by all handlers; parsing belongs on the enum class |
| Portfolio state persistence seam | Portfolio domain (`portfolio_handler/storage/`) | Core (record shapes) | High cohesion: a fill mutates cash+position+transaction together; one aggregate |
| Timestamp determinism | Order domain + Portfolio domain | Core (`Clock`) | Order audit + transaction records derive time from events/injected clock |
| Time-alignment policy (`_aligned`) | Core util (`outils/time_parser`) | Strategy/Screener (callers) | Single seam decides firing; callers gate on it, never re-implement |
| Test organization | Test harness (`tests/`) | — | Type axis (unit/integration) orthogonal to domain; harness concern only |
| Oracle freeze/verify | Test harness (`tests/integration` + `scripts/run_backtest.py`) | — | Golden-master gate; re-runs the real engine, diffs CSV/JSON |

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `pydantic` | `^2.13` (latest 2.13.4) [VERIFIED: PyPI] | Config domain models, validation, serialization | The de-facto Python validation/settings library; v2 is Rust-core (pydantic-core 2.46.4), `model_validate`/`model_dump` round-trip is the exact backtest-dict↔JSONB mechanism |
| `pydantic-settings` | `^2.14` (latest 2.14.1) [VERIFIED: PyPI] | `Settings(BaseSettings)` env/secrets layer | The v2 home for `BaseSettings` (split out of pydantic v1); provides `SecretStr` fail-loud + `SettingsConfigDict`; pulls `python-dotenv` |
| `pytest` | `8.4.2` (in-tree) [VERIFIED: pyproject] | Test runner | Already the project runner; restructure is harness-level only |

### Supporting (already in-tree, no install)
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `pandas.testing` | (pandas 2.3.3) | `assert_frame_equal` for oracle CSV diffs | Already used in `test_backtest_oracle.py` — keep |
| `uuid_utils` | (in-tree, M2a) | UUIDv7 IDs in durable record shapes | Record shapes carry native UUID (D-12) |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Pydantic models | `@dataclass` + manual validation | Loses the model_dump(mode="json") JSONB round-trip (M2-06 requirement) and field validators; rejected by D-01/D-02 (locked Pydantic) |
| `_missing_` on enum | Standalone `parse_*()` functions | `_missing_` keeps parsing on the type (D-04 intent); but functional `Enum(...)` syntax can't host it → must convert to class syntax either way |

**Installation:**
```bash
poetry add pydantic@^2.13 pydantic-settings@^2.14
```
> ⚠️ The planner MUST add these via Poetry (updating `pyproject.toml` + `poetry.lock`). They are **NOT** currently dependencies. Do NOT rely on the ad-hoc `pip install` that this research session ran into `.venv` — that is not lockfile-tracked and will not survive `make init-env`.

**Version verification:**
```bash
pip index versions pydantic          # → 2.13.4 (latest) [VERIFIED 2026-06-05]
pip index versions pydantic-settings # → 2.14.1 (latest) [VERIFIED 2026-06-05]
```

## Package Legitimacy Audit

| Package | Registry | Age | Downloads | Source Repo | slopcheck | Disposition |
|---------|----------|-----|-----------|-------------|-----------|-------------|
| `pydantic` | PyPI | 8+ yrs (v2 since 2023) | ~300M+/mo | github.com/pydantic/pydantic | [OK] | Approved |
| `pydantic-settings` | PyPI | 2+ yrs (v2 split) | ~80M+/mo | github.com/pydantic/pydantic-settings | [OK] | Approved |

**Packages removed due to slopcheck [SLOP] verdict:** none
**Packages flagged as suspicious [SUS]:** none

slopcheck 0.6.1 ran clean (`2 OK`) on PyPI for both. `model_validate`/`model_dump(mode="json")` round-trip and Decimal→str / UUID→str serialization were verified by direct execution in this session (not just registry existence).

## Architecture Patterns

### System Architecture Diagram

```
                         Phase 3 (M2b) refactor surfaces — all behavior-preserving
                         ───────────────────────────────────────────────────────

 [env vars] ──> Settings(BaseSettings)  ──fail-loud on missing secret──> (live only, not wired)
                       │
 backtest dict ──> PortfolioConfig.model_validate(dict) ──> model_dump(mode="json") ──> (future JSONB)
                       │   (Decimal→str, UUID→str, round-trips exactly)
                       ▼
            itrader/__init__.py, portfolio_handler, execution_handler
                  construct Pydantic models DIRECTLY (no getters)

 BarEvent.time ──> check_timeframe(time, tf) ──> _aligned(ts, tf): int(ts.timestamp()) % tf == 0
                       │                              (single replaceable seam, D-06)
          ┌────────────┴────────────┐
   strategies_handler:47      screeners_handler:72   ── gate firing; same UTC bars as golden

 FillEvent ──> Order.add_state_change(time=event_time)  ──record──> state_changes (event-derived, D-12)
          └──> Order.add_fill(fill_time) ──> transition timestamp
          └──> modify_order ──routes through──> add_state_change (no direct append)

 Portfolio ──injects──> PortfolioStateStorage (in-memory backend, peer package)
     │  CashManager._reserved_cash, _cash_operations ─────┐
     │  PositionManager._positions, _closed_positions ────┤──> route through seam (D-09/D-10)
     │  TransactionManager._pending, _transaction_history ┤
     │  MetricsManager snapshots ─────────────────────────┘

 scripts/run_backtest.py::main() ──> output/{trades,equity}.csv + summary.json
        │                                          │
        └── M2b-START: capture as inertness ref ───┴── M2b-END: re-run, D-17 byte-exact gate
                                                        ──pass──> re-freeze test/golden/* (D-16, LAST)
```

### Recommended Project Structure (post-reorg, D-11)
```
itrader/
├── config/                    # ~600–900 lines of Pydantic models (was 3,380 / 21 files)
│   ├── __init__.py            # direct model exports, NO getters
│   ├── settings.py            # Settings(BaseSettings) — secrets fail-loud
│   ├── portfolio.py           # PortfolioConfig + .default() classmethod
│   ├── trading.py / data.py / system.py / exchange.py
├── core/
│   ├── constants.py           # NEW: FORBIDDEN_SYMBOLS, SUPPORTED_* (D-03)
│   └── enums/                 # + FillStatus, CashOperationType, PositionEvent,
│       └── ...                #   MetricsPeriod, TransactionState (D-05)
├── portfolio_handler/
│   ├── position/              # position.py + position_manager.py
│   ├── transaction/           # transaction.py + transaction_manager.py
│   ├── cash/                  # cash_manager.py + CashOperation entity
│   ├── metrics/               # metrics_manager.py + snapshot entities
│   ├── storage/               # PEER: PortfolioStateStorage ABC + in-memory + factory
│   └── portfolio.py / portfolio_handler.py
tests/                         # was test/
├── conftest.py                # root: shared fixtures + type marker registration (pick ONE home)
├── unit/                      # mirrors package; one collaborating component
│   └── conftest.py
└── integration/               # cross-component cascade, smoke, oracle
    └── conftest.py
```

### Pattern 1: Pydantic v2 `Settings(BaseSettings)` with fail-loud secrets (D-02)
**What:** Backtest-relevant fields have defaults; secrets are required-no-default `SecretStr` so any live run raises `ValidationError` immediately.
**When to use:** The single `Settings` stub.
```python
# Source: https://pydantic.dev/docs/validation/latest/concepts/pydantic_settings/ [CITED]
from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ITRADER_")

    # Backtest path reads these — safe defaults
    timezone: str = "Europe/Paris"
    log_level: str = "INFO"
    environment: str = "backtest"

    # Secrets: NO default → ValidationError if a live path ever instantiates Settings
    database_url: SecretStr        # required-no-default, fails loud (D-02)
    # access later via: settings.database_url.get_secret_value()
```

### Pattern 2: `model_validate` / `model_dump(mode="json")` round-trip (M2-06) [VERIFIED: executed]
**What:** One model round-trips a backtest dict and a JSON-compatible (JSONB-ready) dict. Decimal→str, UUID→str in json mode; `model_validate` parses them back exactly.
```python
# VERIFIED by direct execution in this research session (pydantic 2.13.4):
from pydantic import BaseModel
from decimal import Decimal
from uuid import UUID

class PortfolioConfig(BaseModel):
    cash: Decimal
    portfolio_id: UUID

cfg = PortfolioConfig(cash=Decimal("100000.00"),
                      portfolio_id=UUID("00000000-0000-0000-0000-000000000001"))

cfg.model_dump()              # {'cash': Decimal('100000.00'), 'portfolio_id': UUID(...)}
cfg.model_dump(mode="json")   # {'cash': '100000.00', 'portfolio_id': '0000...0001'}  ← JSONB-ready
PortfolioConfig.model_validate(cfg.model_dump(mode="json")) == cfg   # True ← round-trips exactly
```

### Pattern 3: Preset as factory classmethod (D-03)
```python
class PortfolioConfig(BaseModel):
    cash: Decimal
    # ... fields with Field(gt=0, le=1) validators at Claude's discretion ...

    @classmethod
    def default(cls) -> "PortfolioConfig":
        return cls(cash=Decimal("100000.00"), ...)
```

### Pattern 4: Enum with `_missing_` case-insensitive parse (D-04) — requires class syntax
**What:** The existing enums use **functional `Enum("Name", "A B C")` syntax which CANNOT host methods.** They must be rewritten as class-based enums to add `_missing_` or `from_string`.
```python
# Existing (functional — cannot host _missing_):
#   FillStatus = Enum("FillStatus", "EXECUTED REFUSED CANCELLED")   # event.py:12
# Rewrite as class-based:
from enum import Enum

class FillStatus(Enum):
    EXECUTED = "EXECUTED"
    REFUSED = "REFUSED"
    CANCELLED = "CANCELLED"

    @classmethod
    def _missing_(cls, value):
        if isinstance(value, str):
            for member in cls:
                if member.value.upper() == value.upper():
                    return member
        raise ValueError(f"Unknown FillStatus: {value!r}")   # real f-string, not ('Value %s', x)
```
> `_missing_` is invoked by `FillStatus(value)` on lookup failure. Replaces the `fill_status_map.get(status)` dict pattern (`event.py:411`). Same approach for `transaction_type_map` (`transaction.py:96`) and `event_type_map` — though `EventType` stays inline (D-05) so its map can stay or convert at discretion.

### Pattern 5: `PortfolioStateStorage` generalized from `OrderStorage` (D-09)
**What:** Mirror `order_handler/base.py::OrderStorage` (ABC) + `storage/in_memory_storage.py` (dict-backed) + `storage/storage_factory.py` (env→backend). One unified interface; the four managers' containers route through it.
- ABC pattern: `from abc import ABC, abstractmethod`; methods raise via `@abstractmethod`.
- In-memory backend: plain dicts/lists per `Portfolio`, e.g. `self._positions: Dict[str, Position]`, `self._transaction_history: List[Transaction]` — moved out of the managers into the backend.
- Factory: `PortfolioStateStorageFactory.create(environment)` → `InMemoryPortfolioStateStorage()` for `backtest`/`test`; `live` raises `NotImplementedError` (D-sql) or requires `db_url`.

### Anti-Patterns to Avoid
- **Storage class inside each manager folder** — drifts back toward four interfaces; D-09 mandates a single peer `storage/` package.
- **Merging `OrderStatus`/`FillStatus`/`TransactionState`** — domain-modeling regression (D-04). Keep distinct.
- **Market-tz local anchoring in `check_timeframe`** — would shift 00:00-UTC golden bars to 01:00 Paris and break the behavioral oracle (D-06).
- **Big-bang pytest conversion** — D-14 mandates one file per commit, identical test count each commit.
- **Widening `filterwarnings` to silence a `ResourceWarning`** — D-14: fix at the leak.
- **Registering markers in both `pyproject.toml` AND `pytest_configure`** — pick exactly one (discretion clause).

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Config validation + JSONB round-trip | Manual dict→object coercion + custom `to_dict`/`from_dict` | Pydantic `model_validate`/`model_dump(mode="json")` | The entire D-01 deletion target is hand-rolled config machinery; Pydantic replaces it and gives the M2-06 round-trip for free |
| Secret fail-loud | `if not os.environ.get(...): raise` | `SecretStr` required-no-default in `BaseSettings` | One declaration; `pydantic-settings` raises `ValidationError` automatically |
| Case-insensitive enum parse | scattered `{str: Enum}` map dicts | `_missing_` classmethod on the enum | D-04 explicitly replaces the maps; map dicts duplicate the enum and drift |
| Oracle CSV diff | byte-compare or manual row loop | `pandas.testing.assert_frame_equal` (already used) | Column-level failure messages; handles ordering via sort+reset_index |
| Storage abstraction | new bespoke interface | Generalize the proven `OrderStorage` ABC+factory | D-09 mandates mirroring; the order pattern is the template |
| Time alignment | inline `% timeframe` at each call site | single `_aligned(ts, tf)` seam | D-06: one replaceable policy; callers gate, never re-implement |

**Key insight:** This phase is largely *deletion of hand-rolled code* (3,380-line config package, scattered map dicts, dead helpers) in favor of standard library/Pydantic idioms — the danger is not building too little but breaking behavior while deleting.

## Runtime State Inventory

> This is a refactor phase. State inventory below. The critical insight: this refactor touches **no external runtime state** — it is all in-process Python + committed files.

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | **None external.** Portfolio/order state is in-memory only (backtest); the only persisted artifacts are `test/golden/{trades,equity}.csv` + `summary.json` (committed git files) | Re-freeze golden files (D-16) — a code+data-regen task, not a DB migration |
| Live service config | **None.** No live services run in backtest scope; `Settings` secrets are declared-but-not-wired (D-02). No n8n/Datadog/external dashboards | None |
| OS-registered state | **None.** No OS-level registrations (no Task Scheduler, launchd, systemd, pm2). Single `make backtest`/`pytest` invocation | None |
| Secrets/env vars | `Settings(BaseSettings)` introduces env-var names (`ITRADER_*` prefix at discretion) for secrets, but NONE are wired to a running path. The `.env` at repo root (loaded by Makefile) is unchanged | Declare secret field names; do NOT depend on them in backtest path |
| Build artifacts / installed packages | Adding `pydantic`+`pydantic-settings` to Poetry regenerates `poetry.lock`; the `.venv` must `poetry install`. The `test/`→`tests/` `git mv` invalidates `test/**/__pycache__` (auto-regenerated). No egg-info/compiled artifacts affected | `poetry lock` + `poetry install` after dependency add; pycache regenerates automatically |

**Behavior:** After every file in the repo is updated, the only "cached" runtime state is `test/golden/*` (committed) and `output/*` (gitignored, regenerated each run). The D-17 inertness gate exists precisely to confirm the structural changes produced byte-identical engine output before the golden files are re-frozen.

## Common Pitfalls

### Pitfall 1: The flat `itrader/config.py` shadow module
**What goes wrong:** A flat `itrader/config.py` (3,542 bytes) exists ALONGSIDE the `config/` package and is the *actual* source of `FORBIDDEN_SYMBOLS` and `TIMEZONE`. `config/__init__.py:60-70` loads it via `importlib.util.spec_from_file_location("itrader._flat_config", ...)`. Deleting the package getters (D-01) without absorbing this flat module breaks every `config.TIMEZONE` and `from itrader.config import FORBIDDEN_SYMBOLS` consumer.
**Why it happens:** It's the M1 KB16/#34 shadowing workaround — the flat module and package collided on `itrader.config`; M1 resolved imports by loading the flat module under an alias.
**How to avoid:** The D-01/D-03 collapse must migrate `FORBIDDEN_SYMBOLS`→`core/constants.py` and `TIMEZONE` into the `Settings`/system model, then DELETE the flat `itrader/config.py` and the importlib shim. Grep all `config.TIMEZONE` / `config.FORBIDDEN_SYMBOLS` readers (`time_parser.py`, `data_provider.py`, `CCXT.py`, plus `itrader/__init__.py` `config = ...`).
**Warning signs:** `AttributeError: module 'itrader.config' has no attribute 'TIMEZONE'` at import time.

### Pitfall 2: Functional-syntax enums can't host `_missing_`/`from_string`
**What goes wrong:** Every enum in the codebase uses `Name = Enum("Name", "A B C")` functional syntax. You cannot attach a `_missing_` or `from_string` classmethod to a functional Enum — adding D-04's parsing requires rewriting each to class-based `class Name(Enum): ...`.
**Why it happens:** The codebase standardized on functional syntax; D-04's requirement is incompatible with it.
**How to avoid:** Plan an explicit "convert functional enum → class enum" step per relocated enum. Preserve member values exactly (`OrderStatus` members are auto-numbered `1,2,3...` in functional syntax — switching to explicit `= "PENDING"` string values changes `.value` from int to str; verify nothing compares `.value` as int). **This is an oracle-risk if any serialization or comparison relies on the int auto-value.**
**Warning signs:** `AttributeError: type object 'X' has no attribute '_missing_'` or `.value` type mismatch in tests.

### Pitfall 3: `check_timeframe` anchor change shifts firing schedule
**What goes wrong:** Current `check_timeframe` (`time_parser.py`) anchors on **seconds-since-midnight-UTC** (`time.replace(hour=0,...)` after `.astimezone(pytz.utc)`). D-06 switches to **epoch anchor** `int(ts.timestamp()) % tf == 0`. For daily bars at 00:00 UTC the two AGREE, so the oracle should stay identical — but any divergence is a STOP/investigate per D-18, not a re-baseline.
**Why it happens:** Epoch-anchor and midnight-anchor differ for non-midnight-aligned timeframes; the golden run is 1d at 00:00 UTC so they coincide.
**How to avoid:** Make the change, run `test_oracle_behavioral_identity` IMMEDIATELY — it must stay green. If it moves, the inertness gate (D-17) blocks the re-freeze.
**Warning signs:** Trade timing/count drift in the behavioral-identity assertion.

### Pitfall 4: `filterwarnings=["error"]` surfaces ResourceWarning during pytest conversion
**What goes wrong:** Converting `unittest.TestCase` (which often leaks file handles/queues via `setUp` without teardown) to fixtures can surface `ResourceWarning`s that the strict filter promotes to errors, failing previously-green tests.
**Why it happens:** `pyproject.toml:71-75` `filterwarnings=["error", ...]`. unittest's implicit cleanup masked leaks pytest fixtures expose.
**How to avoid:** Use fixture `yield` teardown to close resources; never add to the ignore list (D-14).
**Warning signs:** `ResourceWarning: unclosed file` / `unclosed ... queue` promoted to test error.

### Pitfall 5: `git mv` history preservation + same-test-count gate
**What goes wrong:** Moving `test/`→`tests/` with plain `mv` (not `git mv`) loses blame/history; converting + moving in one commit makes a break un-bisectable.
**Why it happens:** D-13/D-14 require `git mv` AND identical test count AND green suite at EVERY commit.
**How to avoid:** Per file: `git mv` first (history-preserving rename commit), THEN convert in a separate commit, asserting `pytest --collect-only -q | wc -l` is unchanged. Keep the reorg (D-11), storage-seam logic, and pytest move as separate commit streams (D-11 explicit).
**Warning signs:** `pytest --collect-only` count changes; `git log --follow` shows no history across the move.

### Pitfall 6: `testpaths = ["test"]` not updated after the move
**What goes wrong:** `pyproject.toml:41` hardcodes `testpaths = ["test"]`; after `test/`→`tests/` it must become `["tests"]` or discovery silently finds nothing. Same for the Makefile targets (`make test-unit` etc. reference `test/...` paths) and `DIR_MARKERS` segment names.
**How to avoid:** Update `testpaths`, the 8 Makefile `test-*` targets, and rework `DIR_MARKERS` from domain-segment to type-segment (`unit`/`integration`) in the same move-completion commit.
**Warning signs:** `collected 0 items` after the move.

## Code Examples

### Reading the order-storage factory to generalize (D-09)
```python
# Source: itrader/order_handler/storage/storage_factory.py [VERIFIED: in-tree]
class OrderStorageFactory:
    @staticmethod
    def create(environment: str, db_url: Optional[str] = None) -> OrderStorage:
        environment = environment.lower()
        if environment in ('backtest', 'test'):
            return InMemoryOrderStorage()
        elif environment == 'live':
            if not db_url:
                raise ValueError("Database URL is required for live environment")
            from .postgresql_storage import PostgreSQLOrderStorage
            return PostgreSQLOrderStorage(db_url)
        else:
            raise ValueError(f"Unknown environment: {environment}. ...")
# → Mirror this exactly for PortfolioStateStorageFactory (live branch raises/defers to D-sql).
```

### Injected Clock (M2a) for timestamp determinism (D-12)
```python
# Source: itrader/core/clock.py [VERIFIED: in-tree]
class Clock(Protocol):
    def now(self) -> datetime: ...
# → add_state_change should accept an event-time arg (default to event time);
#   where a wall-clock fallback is needed, use the injected Clock, never datetime.now().
```

### Oracle test surfaces D-16/D-17/D-18 modify
```python
# Source: test/test_integration/test_backtest_oracle.py [VERIFIED: in-tree]
# test_oracle_behavioral_identity(oracle_run): EXACT, active — stays the law (D-18)
#   asserts trade (entry/exit/side/pair) + equity timestamp grid + trade_count, check_exact=True
# test_oracle_numeric_values(oracle_run): @pytest.mark.xfail(DEF-02-08-A), D-15 tolerance
#   → D-16 REMOVES the xfail + the _D15_RTOL/_D15_ATOL tolerance, asserts numeric cols EXACT
#   → re-freeze regenerates test/golden/* from scripts/run_backtest.py::main()
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Pydantic v1 `BaseSettings` inside `pydantic` | `pydantic-settings` separate package | Pydantic v2 (2023) | Must import `BaseSettings`/`SettingsConfigDict` from `pydantic_settings`, NOT `pydantic` |
| v1 `class Config:` inner class | v2 `model_config = ConfigDict(...)` / `SettingsConfigDict(...)` | Pydantic v2 | Use the dict form; v1 inner-class is deprecated |
| v1 `@validator` | v2 `@field_validator` / `@model_validator` | Pydantic v2 | Use `@field_validator` (discretion clause references it) |
| v1 `.dict()` / `.json()` | v2 `.model_dump()` / `.model_dump_json()` / `.model_validate()` | Pydantic v2 | The round-trip methods M2-06 needs |

**Deprecated/outdated:**
- Pydantic v1 idioms (`@validator`, `.dict()`, inner `Config`) — do NOT use; this is a fresh v2 build.
- Functional `Enum(...)` syntax for the relocated enums — must convert to class syntax to host `_missing_`.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `OrderStatus` functional-enum members carry int auto-values; nothing in the oracle path compares `.value` as int | Pitfall 2 | If a serialized field or comparison relies on int `.value`, converting to class-enum string values could shift behavior — verify by grep before converting |
| A2 | Daily-bar epoch-anchor and midnight-UTC-anchor coincide for the golden run, so D-06 is oracle-inert | Pitfall 3 | If they diverge, behavioral oracle shifts → D-18 STOP. Mitigated by running the identity test immediately after the change |
| A3 | `pydantic-settings` `secrets_dir`/env wiring is NOT needed for backtest (secrets declared-but-unwired) | Pattern 1 | Low — D-02 explicitly defers live wiring |
| A4 | The ~4 config consumer sites in D-01 are the complete in-scope set; `mypy --strict` catches misses | Standard Stack | Mitigated by the strict gate (D-01 relies on this); grep `from itrader.config` to confirm before deleting getters |

## Open Questions

1. **Does any code compare relocated-enum `.value` as an integer?**
   - What we know: all enums are functional syntax (auto int values); converting to class syntax with explicit string values changes `.value` type.
   - What's unclear: whether any serialization (e.g. order/transaction record `.value`) or test asserts the int.
   - Recommendation: planner adds a grep task (`\.value` near `OrderStatus`/`FillStatus`/`TransactionState`) in Wave 0 before the enum conversion; if found, keep string values consistent with any persisted form.

2. **Exact `Settings` field set the backtest path reads.**
   - What we know: `config.TIMEZONE` is read in `time_parser.py`/`data_provider.py`/`CCXT.py`; `execution_handler` reads `performance.rng_seed`; `portfolio_handler` reads portfolio config.
   - What's unclear: the full minimal field set (D-02 says "timezone, log_level, environment" + secrets).
   - Recommendation: planner enumerates actual `config.<attr>` reads via grep when defining the model fields.

3. **Metrics snapshot container shape (for the storage seam).**
   - What we know: `metrics_manager.py` is the fourth manager; CONTEXT cites "metrics snapshots" without an exact attribute.
   - What's unclear: the exact snapshot container name/structure.
   - Recommendation: planner reads `metrics_manager.py.__init__` to find the snapshot list before defining the seam method.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python | Everything | ✓ | 3.13.1 | — |
| Poetry | Dependency add (pydantic) | ✓ (in-tree workflow) | — | — |
| pytest | Test suite | ✓ | 8.4.2 | — |
| mypy | `make typecheck` strict gate | ✓ | 2.1.0 (verified) | — |
| pandas | Oracle CSV diff | ✓ | 2.3.3 | — |
| `pydantic` | Config collapse (M2-06) | ✗ (NOT a dep) | — | **None — must `poetry add`** |
| `pydantic-settings` | `Settings` (M2-06) | ✗ (NOT a dep) | — | **None — must `poetry add`** |
| PostgreSQL | (D-sql, NOT this phase) | n/a | — | In-memory backend only (D-10) |

**Missing dependencies with no fallback:**
- `pydantic` ^2.13 and `pydantic-settings` ^2.14 — the planner's FIRST task must `poetry add` them (and commit the lockfile delta). They are absent from both `pyproject.toml` and `poetry.lock`. This contradicts the orchestrator's "Pydantic v2 is in the dependency set" claim.

**Missing dependencies with fallback:**
- None blocking.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 8.4.2 (+ pytest-cov 5.0, pytest-html 4.2) |
| Config file | `pyproject.toml` `[tool.pytest.ini_options]` (testpaths/markers/filterwarnings); `test/conftest.py` (fixtures + auto-marking) |
| Quick run command | `poetry run pytest -m "unit" -q` (post-reorg: `tests/unit`) |
| Full suite command | `make test` (`poetry run pytest`) |
| Strict gates | `--strict-markers`, `--strict-config`, `filterwarnings=["error"]`; `make typecheck` = `mypy --strict` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| M2-06 | `PortfolioConfig.model_validate(d).model_dump(mode="json")` round-trips; `Settings` raises on missing secret | unit | `pytest tests/unit/config/test_config_models.py -x` | ❌ Wave 0 |
| M2-07 | `FillStatus("executed")` parses case-insensitively; unknown raises clear error | unit | `pytest tests/unit/core/test_enums.py -x` | ❌ Wave 0 |
| M2-08 | `PortfolioStateStorage` round-trips positions/transactions/cash/metrics; factory returns in-memory for backtest | unit | `pytest tests/unit/portfolio/test_state_storage.py -x` | ❌ Wave 0 |
| M2-09 | `add_state_change` uses event time (not `datetime.now()`); `modify_order` routes through it | unit | `pytest tests/unit/order/test_order_timestamps.py -x` | ❌ Wave 0 (extend existing order tests) |
| M2-10 | `to_timedelta("1W")` works, `to_timedelta("1M")` raises, `check_timeframe` fires on golden grid | unit | `pytest tests/unit/outils/test_time_parser.py -x` | partial (existing `test_outils`) |
| M2-11 | Dead modules deleted; suite still green (no import of deleted names) | integration | `make test` (collection succeeds) | ✅ (negative: collection) |
| M2-12 | All `unittest.TestCase` converted; identical count each commit | meta | `pytest --collect-only -q \| wc -l` unchanged | ✅ (existing suite) |
| M2-13 | Behavioral identity EXACT; numeric columns EXACT after re-freeze; inertness gate passes | integration | `pytest tests/integration/test_backtest_oracle.py -x` | ✅ (modify D-16/D-17/D-18) |

### Sampling Rate
- **Per task commit:** `poetry run pytest -m unit -q` + the specific touched test; `make typecheck` after any config/enum/type change.
- **Per wave merge:** `make test` (full suite) + `pytest tests/integration/test_backtest_oracle.py::test_oracle_behavioral_identity` (the D-18 law, must stay green every commit).
- **Phase gate:** Full suite green + `mypy --strict` clean + D-17 inertness gate byte-exact + D-16 re-freeze landed, before `/gsd:verify-work`.

### Wave 0 Gaps
- [ ] `tests/unit/config/test_config_models.py` — covers M2-06 (round-trip + fail-loud secret)
- [ ] `tests/unit/core/test_enums.py` — covers M2-07 (case-insensitive `_missing_` + unknown raises)
- [ ] `tests/unit/portfolio/test_state_storage.py` — covers M2-08 (seam round-trip + factory)
- [ ] `tests/unit/order/test_order_timestamps.py` — covers M2-09 (event-time, modify_order path)
- [ ] Extend `tests/unit/outils/test_time_parser.py` — covers M2-10 (`1W` ok, `1M` raises, epoch anchor)
- [ ] Modify `tests/integration/test_backtest_oracle.py` — D-16 (remove xfail+tolerance), D-17 (inertness ref), D-18 (keep behavioral law)
- [ ] Root + `unit/` + `integration/` conftests with type-marker registration (pick ONE home) — D-13
- [ ] Dependency: `poetry add pydantic@^2.13 pydantic-settings@^2.14` — the only framework install

## Security Domain

> security_enforcement is absent from config (default enabled). This phase is an internal structural refactor with **no external attack surface** — no network endpoints, no auth, no crypto, no untrusted input (config files are developer-authored). The applicable controls are minimal.

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | No auth surface in backtest scope (live/secrets deferred D-live) |
| V3 Session Management | no | No sessions |
| V4 Access Control | no | No access boundaries |
| V5 Input Validation | yes | Pydantic v2 models validate all config input (`@field_validator`, `Field(gt=0, le=1)`); enum `_missing_` validates string→enum |
| V6 Cryptography | no | No crypto; `SecretStr` is for fail-loud declaration, not encryption |
| V7 Error Handling/Logging | yes (light) | Enum parse + `to_timedelta` raise clear f-string errors (no silent `None`); structlog convention preserved |

### Known Threat Patterns for {Pydantic config refactor}

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Secret leaked via default value | Information Disclosure | `SecretStr` required-no-default (D-02) — fails loud, no working secret default (M2-06 requirement) |
| Secret printed in logs/repr | Information Disclosure | `SecretStr` masks `repr`/`str` by default; access only via `.get_secret_value()` |
| Malformed config silently accepted | Tampering | Pydantic validation raises `ValidationError`; no `to_dict`/`from_dict` silent coercion (D-01 deletes the lax machinery) |

## Sources

### Primary (HIGH confidence)
- In-tree code (verified by Read/grep 2026-06-05): `itrader/config/` (3,380 lines/21 files), flat `itrader/config.py` (3,542 B), `order_handler/{base.py,storage/}`, `portfolio_handler/{transaction,position,cash,metrics}_manager.py`, `order_handler/order.py`, `outils/time_parser.py`, `core/enums/`, `core/clock.py`, `events_handler/event.py`, `test/conftest.py`, `test/test_integration/test_backtest_oracle.py`, `scripts/run_backtest.py`, `pyproject.toml`
- Direct execution (pydantic 2.13.4): `model_validate`/`model_dump(mode="json")` Decimal→str, UUID→str round-trip verified
- PyPI registry: `pydantic 2.13.4`, `pydantic-settings 2.14.1` (latest) [VERIFIED 2026-06-05]
- slopcheck 0.6.1: both packages `[OK]` on PyPI

### Secondary (MEDIUM confidence)
- https://pydantic.dev/docs/validation/latest/concepts/pydantic_settings/ — `BaseSettings`, required-no-default, `SecretStr`, `SettingsConfigDict` [CITED]
- https://pydantic.dev/docs/validation/latest/concepts/serialization/ — `model_dump`/`model_dump(mode="json")` round-trip [CITED]

### Tertiary (LOW confidence)
- Pydantic v1→v2 deprecation idioms (State of the Art table) — training knowledge, consistent with the v2 docs fetched; verify exact `@field_validator` signature against docs at plan time if a complex validator is needed.

## Drift Flags (CONTEXT.md / orchestrator vs current code)

| Claim source | Claim | Reality | Action |
|--------------|-------|---------|--------|
| Orchestrator additional_context | "Pydantic v2 is in the dependency set" | **NOT in `pyproject.toml` or `poetry.lock`** | Planner's first task: `poetry add pydantic@^2.13 pydantic-settings@^2.14` |
| CONTEXT.md `code_context` | `order_handler/storage/{base.py,...}` | `OrderStorage` ABC is in `order_handler/base.py`, NOT `storage/base.py` (`storage/` has in_memory + factory + postgresql) | Read `order_handler/base.py` for the ABC |
| CONTEXT.md `code_context` | `event.py:10-13,22,407` (`fill_status_map`) | `EventType`/`FillStatus` at :11-12, `event_type_map` :14, `fill_status_map` :23, used at :411 (not 407) | Use corrected lines |
| CONTEXT.md `code_context` | `order.py:253,262,269` `datetime.now()` | Actual `datetime.now()` at :269,277,284,286,288 (add_state_change) + :436,437,443 (modify_order) | Use corrected lines |
| CONTEXT.md `code_context` | `position_manager.py:72` (`_closed_positions` + open index) | `_positions` (open) at :69, `_closed_positions` at :72 | Minor; both confirmed |
| (not in CONTEXT) | — | **Flat `itrader/config.py` shadow module** is the real source of `FORBIDDEN_SYMBOLS`/`TIMEZONE`, loaded via importlib in `config/__init__.py:60-70` | D-01 collapse MUST absorb + delete this flat module (see Pitfall 1) |
| (not in CONTEXT) | — | All enums use **functional `Enum(...)` syntax** — incompatible with `_missing_`; must convert to class syntax (Pitfall 2) | Add per-enum conversion step |
| CONTEXT.md `code_context` | `time_parser.py` epoch-anchor needed | `check_timeframe` currently uses midnight-of-day UTC anchor (coincides with golden for daily bars); `to_timedelta` already raises-on-unknown (M1) but is not case-insensitive / no `w` / no `M`-specific error | D-06/D-08 changes are incremental on the M1 fix |

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — Pydantic versions verified on PyPI + slopcheck + direct round-trip execution; packages NOT yet installed (flagged)
- Architecture: HIGH — all template/anchor files read in full in-tree; storage pattern, enum sites, timestamp sites, oracle test all verified
- Pitfalls: HIGH — flat-config shadow, functional-enum incompatibility, and testpaths/marker risks all observed directly in code
- time_parser: HIGH — current anchor + to_timedelta state read directly; oracle-inertness reasoning is MEDIUM (A2, requires immediate-test verification)

**Research date:** 2026-06-05
**Valid until:** 2026-07-05 (stable internal refactor; Pydantic versions may bump but v2 idioms are stable)

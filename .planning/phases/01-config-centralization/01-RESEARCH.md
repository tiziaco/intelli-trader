# Phase 1: Config Centralization - Research

**Researched:** 2026-07-09
**Domain:** Pydantic v2 configuration centralization (import-safety, lazy fields, constant folding, typed enum) in a brownfield, oracle-gated Python 3.13 event-driven framework
**Confidence:** HIGH (all core findings verified empirically against the installed pydantic 2.13.4 and against codebase file:line facts)

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions (D-01..D-13 — DO NOT re-derive or "fix" back)
- **D-01:** `SystemConfig` stays **mutable** (NOT frozen) in P1. Freezing deferred to P9.
- **D-02:** Aggregation boundary is **cardinality-1**. `SystemConfig` aggregates only `performance`, `monitoring`, `runtime`, `sql`(lazy).
- **D-03 (OWNER OVERRIDE of spec §6b + original CFG-01):** `order` is **kept OUT** of `SystemConfig` (reclassified cardinality-N). It lives with `OrderHandler` via `OrderConfig.default()`. Validation must check `order` lives with its owner, NOT on `SystemConfig`. **Downstream must not restore it.**
- **D-04:** **No per-instance default-template fields** on `SystemConfig`. `PortfolioConfig`/`ExchangeConfig`/`OrderConfig` own their seed via `.default()`. Supersedes §6a "default templates on SystemConfig".
- **D-05:** `sql` resolves `SqlSettings` on **first access only, never at import**; uncredentialed Postgres access **raises**. Import must construct no `SqlSettings`.
- **D-06:** Mechanism = **`@cached_property`**. Exact pydantic-v2 idiom to be verified (this research resolves it — see below).
- **D-07:** `runtime` (pydantic-settings `Settings`, `env_prefix="ITRADER_"`) stays **eager**. Constructing it reads env but does NOT construct `SqlSettings`. Do NOT give `runtime` a lazy seam.
- **D-08:** Define new config blocks AND rewire direct constant readers now; leave the shared `StreamSupervisor` to P5. `_STREAM_RECONNECT_*` → `StreamSettings`/`ConnectionSettings`; `_WARMUP_MARGIN`/`_BACKFILL_PAGE` → feed/provider config; `_OKX_*`/`_PAPER_*` deleted.
- **D-09:** `extra` policy resolved **empirically** during dead-config audit (this research resolves it — see below).
- **D-10:** `HaltReason` enum **minimal** — only reasons raised in code today. P8 extends it.
- **D-11:** Enum home = `core/enums/system.py` (alongside `SystemStatus`). P1 owns the definition; P8's `SafetyController` consumes it.
- **D-12:** Dead-config audit is **conservative** — remove only provably-unreferenced settings.
- **D-13:** Verify `.gitignore` covers `__pycache__`; `git-rm` tracked stragglers.

### Claude's Discretion
- Exact `StreamSettings`/`ConnectionSettings` field layout and location in `config/`.
- Exact feed/provider config field names for folded `_WARMUP_MARGIN`/`_BACKFILL_PAGE`.
- The precise pydantic-v2 `@cached_property` idiom (contract locked; this research provides it).

### Deferred Ideas (OUT OF SCOPE)
- Shared `StreamSupervisor` consolidation → **P5**.
- `RuntimeConfig` overlay + runtime mutation → **P9**.
- Per-portfolio/per-venue `order` config divergence → future (justifies D-03 cardinality-N).
- Freezing `SystemConfig` → deferred (D-01).
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| CFG-01 | Aggregate cardinality-1 singletons (`performance`, `monitoring`, `runtime`, lazy `sql`) into `SystemConfig` — `order` excluded per D-03 | Current `SystemConfig` shape mapped (§ Current SystemConfig Shape); `Settings`/`SqlSettings` confirmed separate models |
| CFG-02 | Eager-vs-lazy import-safety split (`sql` lazy via `@cached_property`) | Resolved D-06 idiom (§ Resolved D-06) + inertness recipe (§ Inertness Assertion) |
| CFG-03 | Fold scattered constants into domain config, grep-clean | Authoritative fold inventory with file:line (§ Constant-Fold Inventory) |
| CFG-04 | Dead-config audit + normalized `extra` policy | Empirical D-09 finding: domain YAML is orphaned/dead (§ extra Policy & Dead Config) |
| CFG-05 | Typed `HaltReason` enum retiring `'baseline-residual'` free string | Authoritative halt-reason inventory with file:line (§ HaltReason Inventory) |
| CFG-06 | Apply D-03a dual-validator paragraph to `CONVENTIONS.md` (paste, don't re-derive) | Source is `.planning/todos/pending/v17_audit_results.md §6d` (paste-ready per CONTEXT) |
</phase_requirements>

## Summary

The phase's two genuine unknowns are now resolved empirically. **(D-06)** In pydantic **2.13.4** (the pinned version), a stdlib `functools.cached_property` on a `BaseModel` works **natively** as the lazy `sql` accessor: it is **not** treated as a model field, needs **no** `ConfigDict(ignored_types=...)` tweak, and needs **no** `object.__setattr__` cache. First access constructs and caches into the instance `__dict__`; a raising accessor is **not** cached (so uncredentialed access re-raises on every access, satisfying D-05). The CONTEXT.md caveat ("may need a model_config tweak or an object.__setattr__ cache") is resolved: **neither is required** for the non-frozen model that D-01 mandates. **(D-09)** No code anywhere in `itrader/` loads YAML into `SystemConfig` — it is constructed solely via `SystemConfig.default()`. The `settings/domains/system.default.yaml` file is **orphaned dead config** whose keys don't even match the model, so moving `SystemConfig` to `extra="forbid"` is safe.

All eight constant-fold sites live on **live-only files** (none on the backtest hot path), so the oracle risk is low; the real gate to protect is **inertness** (config modules must import nothing live). The authoritative fold inventory and halt-reason inventory below give every definition and read site with file:line, plus the exact grep-clean commands that must return empty afterward.

**Primary recommendation:** Add `runtime: Settings` (eager, `default_factory`) and a `@cached_property def sql(self) -> SqlSettings` to `SystemConfig` exactly as the snippet below; fold the constants into new pure `config/` models wired to their live-only readers; enumerate `HaltReason` with the four members raised today; flip `SystemConfig` to `extra="forbid"` and delete the orphaned domain YAML.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Cardinality-1 singleton config aggregation | Config (`itrader/config/`) | Composition root (`itrader/__init__.py`) | `SystemConfig` is the single import-time singleton; `__init__.py` constructs it |
| Lazy SQL settings resolution | Config (`config/system.py` accessor → `config/sql.py`) | — | `@cached_property` gates `SqlSettings` construction to first access |
| Env-var process settings (`runtime`) | Config (`config/settings.py`) | — | `Settings(BaseSettings)` reads `ITRADER_*`; eager, no DB |
| Scattered runtime constants | Config (new blocks) ← read by live-only handlers/providers | — | D-08: config owns the value, live readers consume it |
| Halt-reason vocabulary | Core enums (`core/enums/system.py`) | Live system + reconciler (consumers) | Enum is core (stdlib-only); `halt()`/reconciler consume it |

## Resolved D-06 — the pydantic-v2 + `@cached_property` lazy-field idiom [VERIFIED: empirical, pydantic 2.13.4]

**Verdict: plain `functools.cached_property` on the non-frozen `BaseModel` — no config tweak, no `object.__setattr__`.**

Empirically confirmed against the installed pydantic **2.13.4** (`poetry run python -c "import pydantic; print(pydantic.VERSION)"` → `2.13.4`):

| Question | Answer (verified) |
|----------|-------------------|
| Does pydantic v2 treat `@cached_property` as a model field? | **No.** `"sql" in SystemConfig.model_fields` → `False`. Pydantic v2 recognizes `functools.cached_property` and excludes it from field collection natively. |
| Is `ConfigDict(ignored_types=(cached_property,))` needed? | **No.** Not required for the stdlib `functools.cached_property`. (Only needed for *custom* descriptor types pydantic doesn't recognize.) |
| Does the `__dict__` write conflict with validation/slots? | **No.** `BaseModel` stores fields in `__dict__` (not `__slots__`); the cached value coexists. After first access `"sql" in c.__dict__` → `True`. |
| Does `model_dump()` accidentally construct/serialize `sql`? | **No.** `model_dump()` keys exclude `sql` (cached_property is not a field). Verified `results/serializers.py` model_dump path stays inert. |
| Frozen interaction (D-01 says NOT frozen)? | cached_property even works under `frozen=True` in 2.13 (writes `__dict__` directly, bypassing `__setattr__`), but D-01 keeps it non-frozen — no concern either way. |
| Does a raising accessor cache the failure? | **No.** `cached_property` only writes `__dict__` on success. A raising body re-raises on every access (verified 2× raises, `"sql" not in c.__dict__`) — exactly the D-05 "uncredentialed access raises" contract. |

**Concrete snippet for the executor** (drop into `itrader/config/system.py`, 4-space indent):

```python
from functools import cached_property

from pydantic import BaseModel, ConfigDict, Field

from itrader.config.settings import Settings   # eager env layer (ITRADER_*)
from itrader.config.sql import SqlSettings      # lazy DB arm (ITRADER_DATABASE_*)


class SystemConfig(BaseModel):
    # D-09: flip ignore -> forbid (domain YAML is orphaned/dead; nothing feeds extras).
    model_config = ConfigDict(extra="forbid")

    # ... existing eager fields (name, version, performance, monitoring, ...) ...

    performance: PerformanceSettings = Field(default_factory=PerformanceSettings)
    monitoring: MonitoringSettings = Field(default_factory=MonitoringSettings)

    # D-07: eager — constructing Settings reads ITRADER_* env but builds NO SqlSettings.
    runtime: Settings = Field(default_factory=Settings)

    # D-05/D-06: lazy — NOT a pydantic field. First access constructs SqlSettings
    # (env-driven). No SqlSettings is built at import / SystemConfig construction.
    # A raising body (uncredentialed Postgres arm) is NOT cached -> re-raises each access.
    @cached_property
    def sql(self) -> SqlSettings:
        return SqlSettings()
```

**Note on what `SqlSettings()` builds (design nuance for the planner):** `SqlSettings` defaults to the **SQLite** arm (`driver=SQLITE_PYSQLITE`), which does **not** raise. The "uncredentialed access raises" of D-05 fires only when the *env* selects the Postgres arm (`ITRADER_DATABASE_DRIVER=postgresql+psycopg2`) with no password/url — then the `_require_pg_credentials` validator raises `pydantic.ValidationError` at first access. On the backtest/no-env path, `SystemConfig.sql` yields a SQLite `SqlSettings` and does not raise. The inertness contract (below) cares only that **nothing is built at import**, regardless of arm. [CITED: itrader/config/sql.py:91-107]

> Sources: empirical probe against installed pydantic 2.13.4; [CITED: pydantic v2 docs — "Serialization / cached_property" and "Model config: ignored_types"].

## Inertness Assertion Recipe (D-05/D-07 — register-vs-build) [VERIFIED: empirical]

The existing `tests/integration/test_okx_inertness.py` runs a **subprocess probe** in a fresh interpreter (importing `itrader.trading_system.backtest_trading_system`) and asserts a `_FORBIDDEN` module tuple is not in `sys.modules`. The lazy-`sql` property is a **construction**, not a **module import**, so it is invisible to a `sys.modules` check — a new assertion is required. Recommended, fitting the file's style:

**Register-vs-build (in-process test, simplest & airtight):**

```python
import inspect
from functools import cached_property

from itrader import config as _cfg          # the SystemConfig singleton (itrader/__init__.py:9)
from itrader.config.system import SystemConfig
from itrader.config.sql import SqlSettings   # noqa: F401 — class import is fine; construction is the risk

def test_sql_is_registered_but_unbuilt_at_import() -> None:
    # REGISTERED: the descriptor exists on the class ...
    assert isinstance(inspect.getattr_static(SystemConfig, "sql"), cached_property)
    # ... and is NOT a pydantic field (won't be built during model_validate / serialized).
    assert "sql" not in SystemConfig.model_fields
    # NOT BUILT: importing itrader ran SystemConfig.default() (itrader/__init__.py:9);
    # the cached_property is unresolved -> no SqlSettings was constructed at import.
    assert "sql" not in _cfg.__dict__
```

`"sql" not in _cfg.__dict__` **is** the register-vs-build assertion: `cached_property` provably populates `__dict__` only on first access, so its absence proves zero `SqlSettings` construction. (Optional hardening: a monkeypatched `SqlSettings.__init__` construction-counter asserted `== 0` after a fresh `SystemConfig.default()` — but reloading `itrader` in-process is awkward given import side effects, so the `__dict__` check is the cleaner primary.)

**Extend the subprocess probe** (belt-and-suspenders, add to `_PROBE` after `import itrader...`):

```python
from itrader import config as _cfg
assert "sql" not in _cfg.__dict__, "SqlSettings was BUILT at import (cached_property resolved)"
```

**D-07 verification (separate models):** `runtime` = `Settings` (`env_prefix="ITRADER_"`, `config/settings.py`) and `sql` = `SqlSettings` (`env_prefix="ITRADER_DATABASE_"`, `config/sql.py`) are **genuinely separate** `BaseSettings` classes — `Settings` carries no DB fields at all (the DB surface was moved wholly into `SqlSettings`, per `config/settings.py:8-11`). Constructing `runtime` therefore reads env but cannot construct `SqlSettings`. [VERIFIED: config/settings.py:17-31, config/sql.py:59-107]

## Constant-Fold Inventory (CFG-03 / D-08) [VERIFIED: grep, file:line]

**Every definition (DEF) and read (USE) site.** All fold-site files are **live-only** (none on the backtest hot path) — see Backtest-Path Classification below.

### `_STREAM_RECONNECT_*` (×4 family: DEBOUNCE_SECONDS, BACKOFF_BASE_SECONDS, BACKOFF_CAP_SECONDS, RETRY_CEILING) → `StreamSettings`/`ConnectionSettings`

| Site | File:line | Kind | Indent |
|------|-----------|------|--------|
| DEF ×4 (0.25 / 1.0 / 30.0 / 6) | `price_handler/providers/okx_provider.py:116-119` | def | SPACES(4) |
| USE ×4 | `price_handler/providers/okx_provider.py:182-185` | read | SPACES(4) |
| DEF ×4 (duplicate) | `portfolio_handler/account/venue.py:62-65` | def | SPACES(4) |
| USE ×4 | `portfolio_handler/account/venue.py:180-183` | read | SPACES(4) |
| DEF ×4 (duplicate) | `execution_handler/exchanges/okx.py:57-60` | def | **TABS** |
| USE ×4 | `execution_handler/exchanges/okx.py:157-160` | read | **TABS** |
| Comment ref only | `execution_handler/exchanges/venue_correlation.py:46` | comment | TABS |

> Note: the value set is triplicated across three files with identical numbers — a strong case for a single `StreamSettings` block that all three read.

### `_WARMUP_MARGIN` (= 5) → feed/provider config

| Site | File:line | Kind | Indent |
|------|-----------|------|--------|
| DEF | `price_handler/feed/live_bar_feed.py:66` | def | SPACES(4) |
| USE | `price_handler/feed/live_bar_feed.py:286` (docstring 272) | read | SPACES(4) |
| DEF (duplicate) | `universe/universe_handler.py:73` | def | SPACES(4) |
| USE | `universe/universe_handler.py:467` (docstrings 65-67, 90, 460) | read | SPACES(4) |

### `_BACKFILL_PAGE` (= 1000) → provider config

| Site | File:line | Kind | Indent |
|------|-----------|------|--------|
| DEF | `price_handler/providers/okx_provider.py:108` | def | SPACES(4) |
| USE (default arg ×2) | `price_handler/providers/okx_provider.py:636, 670` | read | SPACES(4) |
| DEF (duplicate) | `price_handler/providers/replay_provider.py:52` | def | SPACES(4) |
| USE (default arg) | `price_handler/providers/replay_provider.py:152` | read | SPACES(4) |

### `_OKX_*` / `_PAPER_*` → delete (D-08)

| Constant | File:line | Notes |
|----------|-----------|-------|
| `_OKX_STREAM_SYMBOL = "BTC/USDC"` | `trading_system/live_trading_system.py:76` | reads at 560,567,570,572,788,1362,1737,1744; symbol hardcode → fold/config |
| `_OKX_STREAM_TIMEFRAME = "1d"` | `trading_system/live_trading_system.py:77` | reads at 561,1416,1744,1747 |
| `_PAPER_STREAM_SYMBOL = PAPER_PARITY_SYMBOL` | `trading_system/live_trading_system.py:98` | alias to parity const; reads 652,1522,1531,1554 |
| `_PAPER_STREAM_TIMEFRAME = "1d"` | `trading_system/live_trading_system.py:99` | read 652 |
| `_PAPER_EXPECTED_START = PAPER_PARITY_START_DATE` | `trading_system/live_trading_system.py:105` | reads 1520,1530 — feeds the paper-parity gate assertion |
| `_PAPER_EXPECTED_END = PAPER_PARITY_END_DATE` | `trading_system/live_trading_system.py:106` | reads 1521,1530 |

> **Careful with `_PAPER_*`:** they alias `PAPER_PARITY_*` constants used by the paper-parity assertion (lines 1520-1533). Folding must preserve the exact parity window/symbol or the `run_paper_replay()` gate changes meaning. Treat as config-with-fixed-defaults, not a value change.

### `_OKX_INTERVALS` — **NOT a tunable; flag for the planner**

`_OKX_INTERVALS: dict[str, str]` at `price_handler/providers/okx_provider.py:95` (read at 207) is a **timeframe→token lookup table**, not a scalar knob. D-08's "`_OKX_*` deleted" targets the `_OKX_STREAM_*` hardcodes, not this mapping. Recommend leaving `_OKX_INTERVALS` as module-local provider data (or moving to provider config as a dict field) — do **not** blindly delete it (it's live functional data). Flag this distinction so a fold task doesn't break OKX interval resolution.

### Grep-clean commands (must return EMPTY after the fold)

```bash
grep -rn "_STREAM_RECONNECT" itrader/            # expect: empty
grep -rn "_WARMUP_MARGIN" itrader/               # expect: empty
grep -rn "_BACKFILL_PAGE" itrader/               # expect: empty
grep -rn "_OKX_STREAM\|_PAPER_STREAM\|_PAPER_EXPECTED" itrader/   # expect: empty
# _OKX_INTERVALS intentionally NOT in the grep-clean set (mapping data, not a folded tunable)
```

### Backtest-Path Classification (oracle-risk triage)

| File | Path | Oracle risk |
|------|------|-------------|
| `price_handler/providers/okx_provider.py` | live-only (OKX provider) | none — not on backtest path |
| `portfolio_handler/account/venue.py` | live-only (VenueAccount) | none — backtest uses SimulatedCashAccount |
| `execution_handler/exchanges/okx.py` | live-only (OkxExchange) | none |
| `execution_handler/exchanges/venue_correlation.py` | live-only | none (comment ref only) |
| `price_handler/providers/replay_provider.py` | paper-only (inertness-forbidden module) | none |
| `price_handler/feed/live_bar_feed.py` | live-only (inertness-forbidden module) | none — backtest uses BacktestBarFeed |
| `universe/universe_handler.py` | live-only (inertness-forbidden module) | none |
| `trading_system/live_trading_system.py` | live-only | none |

**Conclusion:** No fold site is on the backtest hot path → the oracle should remain byte-exact. The **inertness gate** is the real risk: any new `config/` block the fold introduces must import **nothing live** (no ccxt/async/live modules), since `config/` is already on the backtest import graph via `SystemConfig.default()`.

## HaltReason Inventory (CFG-05 / D-10/D-11) [VERIFIED: grep, file:line]

`halt()` signature: `def halt(self, reason: str) -> None:` at `trading_system/live_trading_system.py:813`. Reasons that actually reach `halt()` / `_update_status(halt_reason=...)` today:

| Reason string | Origin file:line | Kind | Enum member (proposed) |
|---------------|------------------|------|------------------------|
| `'baseline-residual'` | `live_trading_system.py:810` → `self.halt('baseline-residual')` | free string — **D-10 retirement target** | `BASELINE_RESIDUAL` |
| `'connector-fatal'` | `connectors/okx.py:231`, `price_handler/providers/okx_provider.py:541,766,880`, `portfolio_handler/account/venue.py:428`, `execution_handler/exchanges/okx.py:794`, default at `live_trading_system.py:1133` | fixed literal (via `_halt_signal`/pending flag → `halt()`) | `CONNECTOR_FATAL` |
| `'reconciliation-unresolved'` | `portfolio_handler/reconcile/venue_reconciler.py:56` (`_HALT_REASON`, used 94/341) | fixed literal (reconciler injected halt) | `RECONCILIATION_UNRESOLVED` |
| `'durable-halt'` | `live_trading_system.py:1698` (fallback when a durable record has no reason) | synthesized fallback → `_update_status(halt_reason=...)` at 1707 | `DURABLE_HALT` |

**Not halt reasons (do NOT add):**
- `'paused-on-disconnect'` (`live_trading_system.py:1007`) is a **`pause_submission()`** reason, not `halt()` — different mechanism. Excluded per D-10.
- `'drift'` appears **only in comments** (`portfolio_handler/portfolio_handler.py:1149` "spuriously tripping halt('drift')", and the `SystemStatus.HALTED` doc-comment at `core/enums/system.py:21`). No live `halt('drift')` call exists — do **not** add a `DRIFT` member (would be a dead member, violating D-10 "no dead members").

**Recommended minimal enum** (matches `SystemStatus` style at `core/enums/system.py:14` — bare `Enum` with string values; module imports **stdlib only** per the core/enums dependency rule):

```python
class HaltReason(Enum):
    BASELINE_RESIDUAL = "baseline-residual"
    CONNECTOR_FATAL = "connector-fatal"
    RECONCILIATION_UNRESOLVED = "reconciliation-unresolved"
    DURABLE_HALT = "durable-halt"
```

> Preserve the wire string values (`.value`) so durable-record persistence and existing `halt_reason` string logging/`ErrorEvent` binds stay byte-compatible. **Scope note:** P1 defines the enum; `halt()` still takes `reason: str` — P8's `SafetyController` owns migrating call sites to the enum (CF-8 split across P1+P8, D-11). P1's mandatory retirement is the `'baseline-residual'` free string at line 810. Whether P1 also converts the other three literals to enum members is a planner call, but the enum must at minimum **exist** and **`baseline-residual` must be retired**.

## `extra` Policy & Dead Config (CFG-04 / D-09/D-12/D-13) [VERIFIED: grep]

### D-09 empirical finding: domain YAML is orphaned — `SystemConfig` can move to `extra="forbid"`

**No code in `itrader/` loads any YAML into `SystemConfig`.** `grep -rn "yaml\|load\|settings/domains"` over `itrader/` returns **zero** YAML-loading sites. `SystemConfig` is constructed **only** via `SystemConfig.default()` (`itrader/__init__.py:9`) — the sole non-test usage.

`settings/domains/system.default.yaml` exists but is **orphaned dead config**: its keys (`logging`, `database`, `cache`, `security`, `environment`, and a `performance` block with `gc_threshold`/`max_memory_usage_mb`/`enable_memory_monitoring`) **do not match** the actual `SystemConfig`/`PerformanceSettings` fields at all, and nothing loads it. Same for `settings/domains/trading.default.yaml`.

**Recommendation (D-09 resolved):** Flip `SystemConfig` from `extra="ignore"` → `extra="forbid"` (true normalization, matches its `exchange`/`portfolio`/`order`/`sql` siblings and catches typos loudly). Keep env models `Settings`/`OkxSettings` on `extra="ignore"` (they legitimately see unrelated `ITRADER_*` env vars). The orphaned `settings/domains/system.default.yaml` + `trading.default.yaml` are **dead-config removal candidates** (D-12) — deleting them removes the only theoretical source of extras. Also update the stale `from_dict` docstring ("Tolerate unknown keys from a YAML override" at `system.py:78`) which no longer holds under `forbid`.

> Caution: `from_dict()` (`system.py:100`) is `model_validate(data or {})`. Under `extra="forbid"`, any caller passing unknown keys will now raise — grep confirms only tests + `.default()` construct `SystemConfig`, so runtime is safe, but verify test fixtures don't pass extras.

### D-13: `__pycache__` [VERIFIED]

`.gitignore` covers it (`__pycache__/` line 2, `*.pyc` line 5) and `git ls-files | grep -c "__pycache__\|.pyc$"` → **0** tracked stragglers. D-13 is effectively already satisfied — the task is a verification + confirm-clean, no `git rm` needed unless new stragglers appear.

## Current SystemConfig Shape (D-02/D-03/D-04) [VERIFIED: config/system.py]

`itrader/config/system.py::SystemConfig` (BaseModel, `extra="ignore"`, **4-space indent**) today holds:
- Scalars: `name`, `version`, `environment` (Environment enum), `debug_mode`, `data_dir`, `log_dir`, `config_dir`, `cache_dir`, `enable_auto_restart`, `auto_restart_delay_seconds`, `enable_graceful_shutdown`, `shutdown_timeout_seconds`.
- Nested: `performance: PerformanceSettings` (default_factory), `monitoring: MonitoringSettings` (default_factory).
- Classmethods: `from_dict(data)` (`model_validate(data or {})`), `default()` (`cls()`).

**P1 adds:** `runtime: Settings` (eager, `default_factory=Settings`) and `sql` (lazy `@cached_property → SqlSettings`). **`order` stays OUT** (D-03) — `OrderConfig.default()` already lives in `config/order.py` (BaseModel, `extra="forbid"`, seeded by its owner `OrderManager`). This confirms D-04: per-instance configs (`OrderConfig`/`PortfolioConfig`/`ExchangeConfig`) already own their seed via `.default()` — no template fields go on `SystemConfig`.

**Two barrels re-export `SystemConfig`** — update both if adding public models: `config/__init__.py` (line ~40 group) and `config/models.py` (line 38, `__all__` line 47). New `StreamSettings`/feed-provider config models should be re-exported consistently.

**Naming-collision warning for `StreamSettings`:** a `ConnectionSettings` **already exists** at `config/exchange.py:137` (fields: `auto_connect`, `connection_timeout`, `retry_attempts`, `retry_delay`) — a *different* concept from the `_STREAM_RECONNECT_*` debounce/backoff/cap/ceiling family. Do not overload it silently; either add a distinct `StreamSettings` model or extend `ConnectionSettings` deliberately with a documented rationale (Claude's discretion per CONTEXT).

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Lazy/memoized config field | Manual `_sql` attr + null-check getter + `object.__setattr__` | `functools.cached_property` | Verified native on pydantic 2.13.4; correct raise-not-cached semantics for free |
| "Is it built?" inertness probe | Custom construction counter + `itrader` reload | `"sql" not in cfg.__dict__` | cached_property provably writes `__dict__` only on first access |
| Halt-reason typo safety | Free strings + string compares | `HaltReason(Enum)` with pinned `.value` | Wire-compatible values + typed vocabulary; mirrors `SystemStatus` |

## Common Pitfalls

### Pitfall 1: hoisting a live import into a new `config/` block
**What goes wrong:** A folded `StreamSettings`/feed config that imports ccxt/async/live code pulls the live stack onto the backtest import graph via `SystemConfig`. **How to avoid:** keep new config modules pure (stdlib + pydantic only); run the inertness gate after every fold plan. **Warning sign:** `test_okx_inertness.py` fails with a new `_FORBIDDEN` leak.

### Pitfall 2: adding a dead `DRIFT`/`PAUSED_ON_DISCONNECT` enum member
**What goes wrong:** Violates D-10 (minimal). `'drift'` is comment-only; `'paused-on-disconnect'` is a pause, not a halt. **How to avoid:** enumerate exactly the four reasons that reach `halt()`/`halt_reason=` (table above).

### Pitfall 3: `extra="forbid"` breaking a test fixture that passes extras to `from_dict`
**What goes wrong:** A fixture passing unknown keys now raises `ValidationError`. **How to avoid:** grep test fixtures for `SystemConfig.from_dict`/`model_validate` with extra keys before flipping; update the stale docstring.

### Pitfall 4: folding `_PAPER_*` and changing the parity window
**What goes wrong:** `_PAPER_EXPECTED_START/END/SYMBOL` feed the `run_paper_replay()` assertion (lines 1520-1533); a value drift silently changes the parity gate. **How to avoid:** fold as config-with-fixed-defaults equal to the current `PAPER_PARITY_*` aliases; keep the assertion meaning identical.

## Runtime State Inventory

> Refactor/fold phase — inventory of non-source state.

| Category | Items Found | Action Required |
|----------|-------------|-----------------|
| Stored data | None on the config surface — `SqlSettings` is env/default-driven, no persisted config records touched by P1. Durable **halt records** persist reason *strings* (`storage/halt_record_store.py`); `HaltReason.value` must stay string-compatible (`"baseline-residual"` etc.) so historical records still resolve. | Preserve enum `.value` wire strings — no data migration |
| Live service config | None — no external service stores these constants; all fold values are in-source module constants. | None |
| OS-registered state | None. | None — verified (no scheduler/daemon embeds these constants) |
| Secrets/env vars | `ITRADER_DATABASE_*` (SqlSettings) and `ITRADER_*` (Settings) env var *names* are unchanged by P1 — the lazy `sql` accessor only changes *when* `SqlSettings()` is constructed, not the env contract. | None — env names unchanged |
| Build artifacts | `__pycache__`/`*.pyc` — gitignored, 0 tracked (D-13). | Verify-clean only; no `git rm` needed unless stragglers appear |

## Validation Architecture

> Nyquist validation enabled — observable, non-inferable checks.

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest ^8.4.2 (`testpaths=["tests"]`, `filterwarnings=["error"]`, `--strict-markers`, `--strict-config`) |
| Config file | `pyproject.toml` `[tool.pytest.ini_options]` |
| Quick run command | `poetry run pytest tests/unit/... -x` (per-domain, seconds) |
| Full suite command | `make test` (or `poetry run pytest tests` in a worktree — see MEMORY worktree `.env` note) |

### The two frozen gates (must stay green after EVERY plan)

| Gate | Command | Pass criterion |
|------|---------|----------------|
| **Oracle (byte-exact)** | `poetry run pytest tests/integration/test_backtest_oracle.py -v` | SMA_MACD result `134 / 46189.87730727451` unchanged |
| **Inertness** | `poetry run pytest tests/integration/test_okx_inertness.py -v` | Backtest import pulls no OKX/ccxt/live modules; sentinel `INERTNESS_OK` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| CFG-01 | `runtime` eager, `sql` lazy present on `SystemConfig`; `order` NOT present | unit | `poetry run pytest tests/unit/config/ -k "system_config" -x` | ❌ Wave 0 (add) |
| CFG-02 | Register-vs-build: `sql` registered as cached_property, unbuilt at import | unit + integration | `poetry run pytest tests/integration/test_okx_inertness.py -x` (+ new in-process assertion) | ⚠️ extend existing |
| CFG-03 | Constants folded, grep-clean | unit + shell | see grep-clean block (must return empty) + `poetry run pytest tests/unit -x` | ❌ Wave 0 (grep gate) |
| CFG-04 | `SystemConfig` `extra="forbid"`; orphaned YAML removed | unit | `poetry run pytest tests/unit/config -x` (assert forbid raises on extra) | ❌ Wave 0 (add) |
| CFG-05 | `HaltReason` enum exists (4 members); `baseline-residual` free string retired | unit + grep | `poetry run pytest tests/unit -k halt_reason -x`; `grep -rn "'baseline-residual'" itrader/` empty | ❌ Wave 0 (add) |
| CFG-06 | D-03a paragraph pasted into `CONVENTIONS.md` | manual/doc | grep the pasted paragraph present in `.planning/codebase/CONVENTIONS.md` | manual-only (doc) |

### Non-inferable observable checks (planner: encode these literally)
- **Lazy-sql inertness (CFG-02):** `from itrader import config as c; assert "sql" not in c.__dict__` after import; `assert isinstance(inspect.getattr_static(SystemConfig, "sql"), cached_property)`; `assert "sql" not in SystemConfig.model_fields`.
- **Grep-clean (CFG-03):** all four grep commands (above) return empty; `_OKX_INTERVALS` intentionally excluded.
- **HaltReason retirement (CFG-05):** `grep -rn "'baseline-residual'\|\"baseline-residual\"" itrader/` returns empty **except** the enum `.value` definition line in `core/enums/system.py`; enum members equal the four call-site reasons (no `DRIFT`, no `PAUSED_ON_DISCONNECT`).
- **extra policy (CFG-04):** `SystemConfig(model_validate={"bogus_key": 1})` raises `ValidationError`; `grep -rn "settings/domains" itrader/` stays empty (no new loader introduced).

### Wave 0 Gaps
- [ ] `tests/unit/config/test_system_config.py` — covers CFG-01/CFG-02/CFG-04 (runtime eager, sql lazy register-vs-build, extra=forbid)
- [ ] `tests/unit/config/test_stream_settings.py` (or extend existing) — folded values equal the retired constants
- [ ] `tests/unit/core/test_halt_reason.py` — covers CFG-05 (4 members, `.value` strings)
- [ ] Extend `tests/integration/test_okx_inertness.py` with the `"sql" not in _cfg.__dict__` assertion
- [ ] Grep-clean shell gate wired into a plan verification step (CFG-03)

## Project Constraints (from CLAUDE.md)
- Money is `Decimal` end-to-end — N/A to P1 config surface (no money fields folded), but do not introduce float knobs where Decimal is used (e.g. `ConnectionSettings.connection_timeout` is `Decimal`).
- **Indentation per-file (never normalize):** `config/`, `core/`, `price_handler/feed/` = **4 spaces**; handler modules = **tabs**. Fold-site indents are tabulated above — **`execution_handler/exchanges/okx.py` and `venue_correlation.py` are TABS**; all other fold sites are 4 spaces.
- Importing `itrader` triggers singleton init (`config`, `logger`, `idgen`) — the eager/lazy split protects this from constructing `SqlSettings`.
- Test strictness: `filterwarnings=["error"]`, `--strict-markers` — any new warning fails; declared markers only (`unit`/`integration`/`slow`/`e2e`/`smoke`/`live`).

## Sources

### Primary (HIGH confidence)
- Empirical probe against installed **pydantic 2.13.4** (cached_property field-exclusion, raise-not-cached, model_dump exclusion, frozen interaction) — the D-06 resolution.
- Codebase grep + Read, file:line: `config/system.py`, `config/sql.py`, `config/order.py`, `config/settings.py`, `config/__init__.py`, `config/models.py`, `config/exchange.py:137`, `core/enums/system.py`, `tests/integration/test_okx_inertness.py`, all eight fold-site files, `settings/domains/*.yaml`, `.gitignore`.

### Secondary (MEDIUM confidence)
- [CITED: pydantic v2 docs — cached_property serialization behavior + `model_config.ignored_types`] (corroborates the empirical result).

## Metadata
**Confidence breakdown:**
- D-06 idiom: HIGH — verified empirically on the exact pinned version (2.13.4).
- Fold + halt inventories: HIGH — exhaustive grep with file:line.
- `extra`/dead-config: HIGH — zero YAML loaders confirmed by grep.
- StreamSettings field layout: MEDIUM — Claude's discretion; naming-collision flagged.

**Research date:** 2026-07-09
**Valid until:** ~2026-08-09 (stable; re-verify only if pydantic is bumped past 2.13.x)

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `SystemConfig.sql` should construct `SqlSettings()` (env-driven), yielding SQLite on the no-env backtest path and raising only on the uncredentialed Postgres env arm | Resolved D-06 | If the intended contract is "always raise unless creds present regardless of arm", the accessor body differs — confirm with owner during planning |
| A2 | P1 converts only the mandatory `'baseline-residual'` free string; the other three literals may stay as strings until P8 migrates `halt()` to the enum | HaltReason Inventory | If P1 is expected to migrate all call sites, scope grows into live_trading_system + connectors (D-11 says P8 owns `halt()`) |

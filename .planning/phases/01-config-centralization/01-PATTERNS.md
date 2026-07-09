# Phase 1: Config Centralization - Pattern Map

**Mapped:** 2026-07-09
**Files analyzed:** 13 (2 config models modified/new, 1 enum new, 8 fold-site rewires, 3 test files)
**Analogs found:** 13 / 13 (brownfield — all analogs are in-repo)

> **Global constraint (per-file, NEVER normalize):** `config/`, `core/`, `price_handler/feed/` = **4 spaces**; handler modules = **tabs**. Fold-site indents are tagged per row. `execution_handler/exchanges/okx.py` + `venue_correlation.py` are **TABS**; every other fold site is 4 spaces.

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality | Indent |
|-------------------|------|-----------|----------------|---------------|--------|
| `itrader/config/system.py` (modify: add `runtime` eager + `sql` lazy) | config | request-response (read-model) | *itself* (current `SystemConfig`) | exact (in-place) | 4 spaces |
| `itrader/config/stream.py` or extend `config/exchange.py` (new `StreamSettings` for `_STREAM_RECONNECT_*`) | config | transform (static knobs) | `config/order.py::OrderConfig`, `config/exchange.py::ConnectionSettings` | exact (model shape) | 4 spaces |
| feed/provider config for `_WARMUP_MARGIN`/`_BACKFILL_PAGE` (new fields or model) | config | transform | `config/order.py::OrderConfig` | exact | 4 spaces |
| `itrader/core/enums/system.py` (add `HaltReason`) | enum | transform | `SystemStatus` (same file) | exact (same file) | 4 spaces |
| `price_handler/providers/okx_provider.py` (rewire) | provider | fold-rewire | current DEF+USE in file | in-place | 4 spaces |
| `portfolio_handler/account/venue.py` (rewire) | account | fold-rewire | current DEF+USE in file | in-place | 4 spaces |
| `execution_handler/exchanges/okx.py` (rewire) | exchange | fold-rewire | current DEF+USE in file | in-place | **TABS** |
| `price_handler/feed/live_bar_feed.py` (rewire `_WARMUP_MARGIN`) | feed | fold-rewire | current DEF+USE | in-place | 4 spaces |
| `universe/universe_handler.py` (rewire `_WARMUP_MARGIN`) | handler | fold-rewire | current DEF+USE | in-place | 4 spaces |
| `price_handler/providers/replay_provider.py` (rewire `_BACKFILL_PAGE`) | provider | fold-rewire | current DEF+USE | in-place | 4 spaces |
| `trading_system/live_trading_system.py` (delete `_OKX_*`/`_PAPER_*`, retire `'baseline-residual'`) | composition root | fold-rewire | current DEF+USE | in-place | tabs |
| `tests/unit/config/test_system_config.py` (new) | test | request-response | `tests/unit/config/test_order_config.py` | exact | 4 spaces |
| `tests/unit/core/test_halt_reason.py` (new) | test | request-response | `tests/unit/core/test_enums.py` | exact | 4 spaces |
| `tests/integration/test_okx_inertness.py` (extend) | test | request-response | *itself* | in-place | 4 spaces |

## Pattern Assignments

### `itrader/config/system.py` — add `runtime` (eager) + `sql` (lazy) (config, 4 spaces)

**Analog:** *itself* — current `SystemConfig` (read in full, lines 1-108).

**Current model shape to preserve** (lines 75-107): `BaseModel`, `model_config = ConfigDict(extra="ignore")` (→ flip to `"forbid"` per D-09), eager nested fields via `Field(default_factory=...)`, `from_dict`/`default` classmethods.

**Add exactly the RESEARCH-verified snippet** (RESEARCH.md §Resolved D-06, lines 85-112). Do NOT re-derive — the pydantic 2.13.4 idiom is locked:
```python
from functools import cached_property
from itrader.config.settings import Settings   # eager env layer (ITRADER_*)
from itrader.config.sql import SqlSettings      # lazy DB arm

class SystemConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")   # D-09 flip: ignore -> forbid
    # ... existing eager fields ...
    runtime: Settings = Field(default_factory=Settings)          # D-07 eager
    @cached_property
    def sql(self) -> SqlSettings:                                # D-05/D-06 lazy
        return SqlSettings()
```
**Also update** the stale `from_dict` docstring at line 78 ("Tolerate unknown keys from a YAML override") — no longer holds under `forbid`. **Keep `order` OUT** (D-03).

**Barrel re-export sites** (update both if adding public models like `StreamSettings`): `config/models.py` (imports at lines 33-39, `__all__` at 47) and `config/__init__.py` (`SystemConfig` at line 41, `__all__` at 91). `Settings`/`SqlSettings` are already importable; new `StreamSettings`/feed models must be added to both barrels.

---

### New `StreamSettings` / feed-provider config models (config, 4 spaces)

**Analog:** `config/order.py::OrderConfig` (lines 48-63) — the canonical thin-model shape — and `config/exchange.py::ConnectionSettings` (lines 137-145).

**Model shape to copy** (from `OrderConfig`):
```python
from pydantic import BaseModel, ConfigDict

class StreamSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")   # domain-model convention (forbid, not ignore)
    # fields with literal defaults equal to the retired constants (see fold table)
    @classmethod
    def default(cls) -> "StreamSettings":
        return cls()
```

**NAMING-COLLISION WARNING (RESEARCH.md line 285):** `ConnectionSettings` ALREADY exists at `config/exchange.py:137` with a *different* concept (`auto_connect`, `connection_timeout`, `retry_attempts`, `retry_delay`). Do NOT overload it silently. Either name the new block `StreamSettings` (distinct) or extend `ConnectionSettings` with a documented rationale (Claude's discretion). Note `ConnectionSettings` uses `Decimal` for time fields (`connection_timeout: Decimal = Decimal("30.0")`) — but the `_STREAM_RECONNECT_*` values are floats today (0.25/1.0/30.0); folding them as `float` avoids an oracle-invisible type change (they're live-only). Per CLAUDE.md, do not introduce float where Decimal is the money/time convention — but these are non-money supervisor knobs; match the existing float usage at the read sites.

**Field defaults must equal the retired constants exactly:**
| Field | Value | Retired constant |
|-------|-------|------------------|
| reconnect_debounce_s | 0.25 | `_STREAM_RECONNECT_DEBOUNCE_SECONDS` |
| reconnect_backoff_base_s | 1.0 | `_STREAM_RECONNECT_BACKOFF_BASE_SECONDS` |
| reconnect_backoff_cap_s | 30.0 | `_STREAM_RECONNECT_BACKOFF_CAP_SECONDS` |
| reconnect_retry_ceiling | 6 | `_STREAM_RECONNECT_RETRY_CEILING` |
| warmup_margin | 5 | `_WARMUP_MARGIN` |
| backfill_page | 1000 | `_BACKFILL_PAGE` |

**Pitfall 1 (RESEARCH.md line 297):** new config modules must import stdlib + pydantic ONLY (no ccxt/async/live) — `config/` is on the backtest import graph via `SystemConfig.default()`. Run the inertness gate after every fold.

---

### `itrader/core/enums/system.py` — add `HaltReason` (enum, 4 spaces)

**Analog:** `SystemStatus` (same file, lines 14-23) — bare `Enum` (NOT `str, Enum`), string values, stdlib-only imports (`from enum import Enum`, the core/enums dependency rule).

**Copy this exact style** (module already imports `from enum import Enum`; add member to `__all__` at line 11):
```python
class HaltReason(Enum):
    BASELINE_RESIDUAL = "baseline-residual"
    CONNECTOR_FATAL = "connector-fatal"
    RECONCILIATION_UNRESOLVED = "reconciliation-unresolved"
    DURABLE_HALT = "durable-halt"
```
**Preserve `.value` wire strings** — durable halt records persist reason strings (`storage/halt_record_store.py`); values must stay byte-compatible. **D-10 minimal:** exactly these 4 (the reasons reaching `halt()` today). Do NOT add `DRIFT` (comment-only) or `PAUSED_ON_DISCONNECT` (a pause, not a halt) — dead members violate D-10. Add `"HaltReason"` to the `__all__` list at line 11.

---

### Constant-fold rewire sites (fold-rewire)

Current DEF+USE pattern is uniform: a module-level `_CONST = value` (with a documented `# A3 [ASSUMED]` comment) read into a `self._x = _CONST` instance attr in `__init__`. The rewire replaces the module constant read with a config read.

**Example — `okx_provider.py` (4 spaces), current pattern:**
```python
# DEF (lines 116-119)
_STREAM_RECONNECT_DEBOUNCE_SECONDS = 0.25
...
# USE (lines 182-185)
self._reconnect_debounce_s = _STREAM_RECONNECT_DEBOUNCE_SECONDS
```
Rewire: `self._reconnect_debounce_s = stream_cfg.reconnect_debounce_s` where `stream_cfg` is injected (composition-root injection, NOT a global `config.` read — these are live-only handlers constructed with their config). The comment about "tunable from sandbox without monkeypatching" (see okx.py line ~155 area) confirms injection is the intended seam.

**Per-site indentation & injection notes:**
| File | Constants | Indent | Reader shape |
|------|-----------|--------|--------------|
| `price_handler/providers/okx_provider.py` | `_STREAM_RECONNECT_*` ×4 (116-119→182-185), `_BACKFILL_PAGE` (108→636,670 default-arg), `_OKX_INTERVALS` (95→207, **KEEP**) | 4 spaces | inject config → `self._x = cfg.x` |
| `portfolio_handler/account/venue.py` | `_STREAM_RECONNECT_*` ×4 (62-65→180-183) | 4 spaces | inject config |
| `execution_handler/exchanges/okx.py` | `_STREAM_RECONNECT_*` ×4 (57-60→157-160) | **TABS** | inject config; match tab indent |
| `execution_handler/exchanges/venue_correlation.py` | comment ref only (46) | TABS | update comment only |
| `price_handler/feed/live_bar_feed.py` | `_WARMUP_MARGIN` (66→286) | 4 spaces | inject feed config |
| `universe/universe_handler.py` | `_WARMUP_MARGIN` (73→467) | 4 spaces | inject config |
| `price_handler/providers/replay_provider.py` | `_BACKFILL_PAGE` (52→152 default-arg) | 4 spaces | inject config |
| `trading_system/live_trading_system.py` | `_OKX_STREAM_*`/`_PAPER_STREAM_*`/`_PAPER_EXPECTED_*` (76-106, delete), `'baseline-residual'` @810 | tabs | config-with-fixed-defaults |

**Critical fold cautions:**
- **`_OKX_INTERVALS` (okx_provider.py:95)** is a timeframe→token LOOKUP TABLE, NOT a scalar knob. Do NOT delete it (breaks OKX interval resolution). Excluded from the grep-clean set.
- **`_PAPER_*` (live_trading_system.py:98-106)** alias `PAPER_PARITY_*` constants feeding the `run_paper_replay()` parity assertion (lines 1520-1533). Fold as config-with-fixed-defaults EQUAL to current aliases — a value drift silently changes the parity gate meaning (Pitfall 4).
- **`'baseline-residual'` @ line 810** is the mandatory retirement (`self.halt('baseline-residual')` → `self.halt(HaltReason.BASELINE_RESIDUAL.value)` or the enum member per planner call; D-11 says P8 owns migrating `halt()` signature, so `.value` string keeps it wire-compatible in P1).

**Grep-clean gate (must return EMPTY after fold):**
```bash
grep -rn "_STREAM_RECONNECT" itrader/
grep -rn "_WARMUP_MARGIN" itrader/
grep -rn "_BACKFILL_PAGE" itrader/
grep -rn "_OKX_STREAM\|_PAPER_STREAM\|_PAPER_EXPECTED" itrader/
grep -rn "'baseline-residual'\|\"baseline-residual\"" itrader/   # empty EXCEPT enum .value def
```

---

### `tests/unit/config/test_system_config.py` (new test, 4 spaces)

**Analog:** `tests/unit/config/test_order_config.py` (read in full).

**Test-style to copy:**
```python
import pytest
import pydantic
from itrader.config.system import SystemConfig

pytestmark = pytest.mark.unit   # explicit marker (folder also auto-applies unit via conftest)

def test_...():
    """One-line docstring citing the requirement/decision."""
    ...
    with pytest.raises(pydantic.ValidationError):   # extra=forbid assertion idiom
        ...
```
**Encode the non-inferable observable checks (RESEARCH.md lines 350-354, 124-142):**
```python
import inspect
from functools import cached_property
from itrader import config as _cfg
assert isinstance(inspect.getattr_static(SystemConfig, "sql"), cached_property)
assert "sql" not in SystemConfig.model_fields
assert "sql" not in _cfg.__dict__            # register-vs-build: unbuilt at import
# runtime eager present; order NOT on SystemConfig; extra=forbid raises on bogus key
```

---

### `tests/unit/core/test_halt_reason.py` (new test, 4 spaces)

**Analog:** `tests/unit/core/test_enums.py` (read in full) — imports from `itrader.core.enums`, plain functions with one-line docstrings, `is`-identity + `.value` assertions.

**Encode:** exactly 4 members; `.value` strings equal the four call-site reasons; NO `DRIFT`/`PAUSED_ON_DISCONNECT` member (assert absence). Mirror the `test_enums.py` `assert X("value") is X.MEMBER` idiom.

---

### `tests/integration/test_okx_inertness.py` (extend, 4 spaces)

**Analog:** *itself* — subprocess `_PROBE` + `_FORBIDDEN` `sys.modules` tuple check.

**Add** (RESEARCH.md lines 144-149): after `import itrader...` in the probe, append
```python
from itrader import config as _cfg
assert "sql" not in _cfg.__dict__, "SqlSettings was BUILT at import (cached_property resolved)"
```
The lazy-`sql` property is a construction, not a module import — invisible to the `sys.modules` check, so this `__dict__` assertion is the airtight extension.

## Shared Patterns

### Pydantic domain-model shape
**Source:** `config/order.py::OrderConfig` (lines 48-63), `config/exchange.py::ConnectionSettings` (137-145)
**Apply to:** all new/extended config models
```python
class X(BaseModel):
    model_config = ConfigDict(extra="forbid")   # domain models forbid; env models (Settings/OkxSettings) ignore
    field: T = default
    @classmethod
    def default(cls) -> "X":
        return cls()
```

### Enum shape (core/enums dependency rule)
**Source:** `core/enums/system.py::SystemStatus` (14-23)
**Apply to:** `HaltReason`
Bare `Enum`, string values, `from enum import Enum` (stdlib ONLY — no `itrader` imports in `core/enums/`), member added to module `__all__`.

### Barrel re-export
**Source:** `config/models.py` (9-53), `config/__init__.py`
**Apply to:** any new public config model — add to BOTH barrels (import block + `__all__`).

### Test style
**Source:** `tests/unit/config/test_order_config.py`, `tests/unit/core/test_enums.py`
**Apply to:** new test files — `pytestmark = pytest.mark.unit`, module docstring citing D-NN, one-line function docstrings, `is`-identity + `pytest.raises(pydantic.ValidationError)` idioms.

## No Analog Found

None — this is a brownfield refactor; every target has an in-repo analog (often the file itself).

## Metadata

**Analog search scope:** `itrader/config/`, `itrader/core/enums/`, `tests/unit/config/`, `tests/unit/core/`, `tests/integration/`, all 8 fold-site files.
**Files scanned:** `config/system.py`, `config/order.py`, `config/exchange.py`, `config/models.py`, `config/__init__.py`, `core/enums/system.py`, `tests/unit/config/test_order_config.py`, `tests/unit/core/test_enums.py`, fold-site DEF/USE excerpts (okx_provider, okx exchange, live_bar_feed).
**Pattern extraction date:** 2026-07-09
</content>
</invoke>

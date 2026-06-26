# Phase 4: Hot-Path Discipline - Pattern Map

**Mapped:** 2026-06-24
**Files analyzed:** 6 (4 modified source + 2 new test) + 4 read-only/curated-edit source
**Analogs found:** 6 / 6

> **Source of truth:** `04-CONTEXT.md` (D-01..D-08); the spike `perf/results/PERF-BASELINE-RESULTS.md` IS the research. No RESEARCH.md this phase.
>
> **Indentation hazard (CLAUDE.md — match each file, NEVER normalize):**
> - `itrader/logger.py` → **4-space**
> - `itrader/config/settings.py` → **4-space**
> - `itrader/order_handler/admission/admission_manager.py` → **tab**
> - `itrader/strategy_handler/base.py` → **tab**
> - `itrader/portfolio_handler/position/position_manager.py` → **4-space**
> - `itrader/portfolio_handler/cash/cash_manager.py` → **tab** (verify before edit)
> - `itrader/order_handler/order_handler.py`, `strategy_handler/strategies_handler.py`, `execution_handler/exchanges/simulated.py` → **tab**
> - new test files → **4-space** (all tests under `tests/unit/` use 4-space)

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `itrader/logger.py` (MOD, D-02/D-08) | utility (logging) | request-response (per-call gate) | self (surrounding `ITraderStructLogger` wrapper methods, lines 196-240) | self / exact |
| `itrader/config/settings.py` (MOD, D-08) | config | transform (env→bool) | self (existing `Settings` fields, lines 26-32) | self / exact |
| `itrader/order_handler/admission/admission_manager.py` (MOD, D-01) | manager | event-driven (per-bar on_signal) | self (rejection log site + sibling `warning` call, lines 235-253) | self / exact |
| `itrader/strategy_handler/base.py` (MOD, D-05) | model (strategy ABC) | transform (per-signal snapshot) | self (`to_dict` :356 + `_apply_params` :146) | self / exact |
| `tests/unit/strategy/test_type_hints_equivalence.py` (NEW, D-07) | test | — | `tests/unit/portfolio/test_realised_pnl_accumulator.py` (Phase 3 D-03 precedent) | exact (equivalence-drift-lock pattern) |
| `tests/unit/strategy/test_strategy.py` `to_dict` snapshot (NEW assertion, D-07) | test | — | `tests/unit/strategy/test_strategy.py` (existing `to_dict` tests, lines 192-260) | exact (same file, same fixtures) |
| `tests/unit/core/test_logging_gate.py` (NEW, D-06) | test | — | `tests/unit/core/test_logger_config.py` | exact (same module-under-test, same fixtures) |
| `itrader/portfolio_handler/position/position_manager.py` (curated debug delete, D-04) | manager | event-driven | self (debug lines :198, :273) | self |
| `itrader/portfolio_handler/cash/cash_manager.py` (curated debug delete, D-04) | manager | event-driven | self (debug lines :366/:539/:571/:598/:624) | self |
| `itrader/order_handler/order_validator.py` (READ-ONLY, explains 2 reasons) | utility | — | n/a | read-only |

---

## Pattern Assignments

### `itrader/logger.py` — central level-gate + kill-switch (D-02, D-08) — 4-SPACE

**Analog:** self. The `ITraderStructLogger` wrapper already exists as the single chokepoint all 21 components route through. The gate lands inside the existing wrapper methods; no new abstraction.

**Current wrapper shape to extend** (lines 196-240) — each method is a bare pass-through today:
```python
    def __init__(self, log_name: str = "itrader"):
        self.logger = structlog.stdlib.get_logger(log_name)

    def bind(self, **new_values: Any) -> "ITraderStructLogger":
        bound_structlog = self.logger.bind(**new_values)
        new_logger = ITraderStructLogger.__new__(ITraderStructLogger)
        new_logger.logger = bound_structlog
        return new_logger

    def debug(self, event: str | None = None, *args: Any, **kw: Any) -> None:
        self.logger.debug(event, *args, **kw)

    def info(self, event: str | None = None, *args: Any, **kw: Any) -> None:
        self.logger.info(event, *args, **kw)

    def warning(self, event: str | None = None, *args: Any, **kw: Any) -> None:
        self.logger.warning(event, *args, **kw)

    warn = warning

    def error(self, event: str | None = None, *args: Any, **kw: Any) -> None:
        self.logger.error(event, *args, **kw)

    def critical(self, event: str | None = None, *args: Any, **kw: Any) -> None:
        self.logger.critical(event, *args, **kw)
```

**D-02 gate pattern to apply:** cache the stdlib logger in `__init__` (`self._stdlib = logging.getLogger(log_name)`), and CRITICAL — the `bind()` path builds via `__new__` and must explicitly carry `_stdlib` onto the new instance (see the existing `__new__` carry-over of `new_logger.logger`). Then each method short-circuits before the pipeline:
```python
    # shape (planner finalizes attribute name — Claude's Discretion):
    def debug(self, event: str | None = None, *args: Any, **kw: Any) -> None:
        if _DISABLE_LOGS or not self._stdlib.isEnabledFor(logging.DEBUG):
            return
        self.logger.debug(event, *args, **kw)
```
Use `logging.WARNING`/`logging.ERROR`/`logging.CRITICAL`/`logging.INFO` for the other methods.

**D-08 kill-switch pattern:** mirror the EXISTING module-level env helper idiom `_env_log_level` / `_env_json_logs` (lines 26-42) — a cached boolean checked first in each guard:
```python
def _env_json_logs() -> bool:                       # ← EXACT idiom to copy
    raw = os.environ.get("ITRADER_JSON_LOGS", "false")
    return raw.strip().lower() in ("1", "true", "yes")
```
NOTE (Pitfall 8, see `_env_log_level` docstring lines 29-35): resolve the bool from `os.environ` directly OR from `Settings`, but `ITRADER_DATABASE_URL` is a required-no-default `SecretStr` — do NOT instantiate `Settings()` at import time. The existing helpers read `os.environ` for exactly this reason. **D-08 declares the field in `settings.py` (the documented knob surface) but the logger must read it cache-once without forcing a `Settings()` build at import.**

**Root-level setLevel (where D-08's optional full-off would also act, lines 172-177):**
```python
    root_logger = logging.getLogger()
    for existing in list(root_logger.handlers):
        if getattr(existing, _ITRADER_HANDLER_FLAG, False):
            root_logger.removeHandler(existing)
    root_logger.addHandler(handler)
    root_logger.setLevel(log_level.upper())     # ← D-08 discretion: also drop this for true full-off
```

---

### `itrader/config/settings.py` — `ITRADER_DISABLE_LOGS` boolean (D-08) — 4-SPACE

**Analog:** self. The `Settings(BaseSettings)` class already has the `ITRADER_`-prefixed env layer; `ITRADER_DISABLE_LOGS` is a sibling boolean to `log_level`.

**Existing fields to mirror** (lines 20-33):
```python
class Settings(BaseSettings):
    """Process settings read from ``ITRADER_*`` environment variables."""

    model_config = SettingsConfigDict(env_prefix="ITRADER_", extra="ignore")

    # Backtest path reads these — safe, documented defaults.
    timezone: str = "Europe/Paris"
    log_level: str = "INFO"
    environment: str = "backtest"

    # Secrets: NO default -> ValidationError if a live path ever instantiates Settings
    database_url: SecretStr
```

**Pattern to add:** a defaulted boolean sibling to `log_level` (the `env_prefix="ITRADER_"` makes the env var `ITRADER_DISABLE_LOGS` automatically). A safe default keeps the backtest path env-free:
```python
    disable_logs: bool = False    # ITRADER_DISABLE_LOGS — D-08 full-off kill-switch
```
pydantic-settings coerces `"true"/"1"/"yes"` → `True` natively, so no custom parser needed (contrast with the logger's hand-rolled `_env_json_logs` — only used there to avoid the `Settings()` import-time `database_url` validation, Pitfall 8).

---

### `itrader/order_handler/admission/admission_manager.py` — demote + guard (D-01) — TAB

**Analog:** self. The rejection log site and its sibling `warning` call are both in `process_signal`.

**Current site to demote** (lines 234-237 — `error` → `warning` + `isEnabledFor` guard for the eager list-comp):
```python
				if not validation_result.success:
					error_msg = f"Signal validation failed: {validation_result.summary}"
					self.logger.error('%s - %s', error_msg,
									[msg.message for msg in validation_result.errors])
```

**Sibling `warning` call already present** (lines 251-253) — confirms `warning` is the right level and shows the established lazy `%s` + list-comp shape to keep:
```python
				if validation_result.has_warnings:
					self.logger.warning('Signal validation warnings: %s',
									   [msg.message for msg in validation_result.warnings])
```

**D-01 transformation:**
1. `error` → `warning` (30 < ERROR 40 ⇒ gates out at the `ITRADER_LOG_LEVEL=ERROR` benchmark level — *this demotion realizes the W1 win*; still emits at INFO real runs).
2. Wrap the f-string + list-comp in a cached `self.logger`-level `isEnabledFor(WARNING)` guard to skip the eager `[msg.message for msg in validation_result.errors]` (D-03: this is the ONE hot callsite with an expensive eager arg; the central gate cannot skip eager args because Python evaluates them before the call).

**Audit trail is independent of the log** (lines 240-248 — these run regardless of log level, so demoting/gating loses no forensic record, D-01):
```python
					primary.add_state_change(
						OrderStatus.REJECTED,
						validation_result.summary,
						triggered_by=OrderTriggerSource.VALIDATOR,
					)
					self.order_storage.add_order(primary)
					return [OperationResult.failure_result(error_msg, ...)]
```

**Read-only context** — `order_validator.py` line 391 (`"Quantity below minimum"`, the W1 dust spam) and 509/523 (`"Insufficient cash"`, the genuine out-of-cash reason) BOTH flow through `validate_order_pipeline` → this same log site → uniform `warning` treatment.

---

### `itrader/strategy_handler/base.py` — `_declared_hints` memoization (D-05) — TAB

**Analog:** self. `get_type_hints` is already centralized in `base.Strategy` at exactly two call sites; one `@cache` helper serves both.

**Hot site** — `to_dict` (line 356, per-signal — the ~2% W1 / ~14% W2 sink):
```python
	def to_dict(self) -> dict[str, Any]:
		snapshot: dict[str, Any] = {}
		for nm in get_type_hints(type(self)):              # ← :356 swap to _declared_hints(type(self))
			if nm in ("timeframe", "name"):
				continue
			val = getattr(self, nm, None)
```

**Cold site** — `_apply_params` (line 146, construct/reconfigure):
```python
		hints = get_type_hints(type(self))                  # ← :146 swap to _declared_hints(type(self))
		for nm in hints:
			default = getattr(type(self), nm, _MISSING)
```

**D-05 helper to add (module-level, mypy --strict-clean, name/placement is Claude's Discretion):**
```python
@cache
def _declared_hints(cls: type["Strategy"]) -> dict[str, Any]:
	return get_type_hints(cls)
```
- `type(self)` gives the concrete subclass → resolves once per class; `functools.cache` is thread-safe (live mode) and locks internally; no manual invalidation (annotations fixed at import; strategy-class count bounded).
- Both sites already only iterate keys (never mutate, never `.pop`) → the shared cached dict is read-only-safe. Byte-identical output by construction (same function, same keys + order).

**Investigation finding (why memoize, NOT remove):** neither site uses the resolved annotation *types* — `to_dict` reads keys only; `_apply_params` gets enum-coercion targets from the hand-maintained `_COERCE` dict (line 63, used at line 177), NOT from `hints[nm]`:
```python
_COERCE: dict[str, type[Enum]] = {           # ← :63 — confirms resolved types are unused
	"timeframe": Timeframe,
	...
}
		coerce = _COERCE.get(nm)             # ← :177 — coercion source, not hints[nm]
		if coerce is not None and not isinstance(val, coerce):
			val = coerce(val)
```
Removing resolution entirely is DEFERRED (byte-identity/key-ordering risk in a byte-exact phase).

---

### `tests/unit/strategy/test_type_hints_equivalence.py` (NEW, D-07) — 4-SPACE

**Analog:** `tests/unit/portfolio/test_realised_pnl_accumulator.py` — the Phase 3 D-03 precedent this phase explicitly mirrors (CONTEXT: "Direct mirror of Phase 3 D-03").

**Mirror these structural elements:**

1. **Module docstring** citing the decision + the equivalence contract (D-03 file lines 1-19 pattern): explain that `_declared_hints(cls)` replaces the per-signal `get_type_hints(type(self))` re-resolution, and that the test is the dedicated unit-level drift lock leaning on the oracle/determinism for the run-path numbers. Cite D-05 (memoize) + D-07 (equivalence test).

2. **`pytestmark`** (the strategy test dir auto-applies `unit` via conftest, but the precedent declares it explicitly — match `test_logger_config.py` line 34):
```python
pytestmark = pytest.mark.unit
```

3. **Independent oracle helper** — the D-03 precedent's exact pattern is a function reproducing the PRIOR behavior, asserted `==` against the new mechanism (test_realised_pnl_accumulator.py lines 57-68):
```python
def _resum_realised(pm: PositionManager) -> Decimal:
    """Independent oracle: reproduce the PRIOR dual open+closed full re-sum exactly."""
    total = Decimal('0.00')
    for position in pm.get_all_positions().values():
        total += position.realised_pnl
    ...
    return total
```
**Apply as:** assert `_declared_hints(cls) == get_type_hints(cls)` for a reference strategy class — same **keys AND order** (D-07: value-equality `==` is criterion #2's contract). The "oracle" here is the un-cached `get_type_hints(cls)` direct call.

4. **Reference strategy fixture** — use `SMAMACDStrategy` / `_sma_kwargs()` already imported in `test_strategy.py` (lines 41, 53-67), or build a class directly. The equivalence test operates on the CLASS (`type(strategy)` or `SMAMACDStrategy` directly), not an instance.

**Suggested cases** (mirror the D-03 multi-scenario coverage):
- `_declared_hints(SMAMACDStrategy) == get_type_hints(SMAMACDStrategy)` (keys + order).
- cache-identity: two calls return the SAME object (`is`) — proves memoization fires.
- subclass keying: `_declared_hints` on two different subclasses returns different dicts (no cross-class bleed).

---

### `tests/unit/strategy/test_strategy.py` — `to_dict` snapshot regression (NEW assertion, D-07) — 4-SPACE

**Analog:** same file. The existing `to_dict` tests are the direct template — add a snapshot-regression assertion alongside them.

**Existing idempotency test that already snapshots `to_dict()`** (lines 192-201) — the closest existing pattern:
```python
def test_init_is_idempotent():
    """D-11: calling init() again leaves identical state (to_dict() ==)."""
    strategy = SMAMACDStrategy(**_sma_kwargs())  # warmup == 100
    before = strategy.to_dict()
    strategy.init()
    after = strategy.to_dict()
    assert before == after
```

**Existing json-serializable snapshot test** (lines 203-219, `test_to_dict_is_json_serializable`) and the nested-container test (lines 221-260) show the established assertion style: build via `_sma_kwargs()`, call `strategy.to_dict()`, assert exact keys/values.

**D-07 snapshot regression to add:** a `to_dict()` snapshot for a reference strategy (`SMAMACDStrategy(**_sma_kwargs())`) asserting the FULL expected key set + values — locks byte-identical snapshot content/order end-to-end after the `_declared_hints` swap (D-07: "equivalence-test-only doesn't lock the full snapshot content/order"). Reuse the `_sma_kwargs()` fixture (lines 53-67) and the `json.dumps(snapshot)` round-trip pattern (line 217/259).

---

### `tests/unit/core/test_logging_gate.py` (NEW, D-06) — 4-SPACE

**Analog:** `tests/unit/core/test_logger_config.py` — same module-under-test (`itrader.logger`), reuse its fixtures and import style.

**Reuse the EXACT fixture + helper pattern** (test_logger_config.py lines 34-49):
```python
pytestmark = pytest.mark.unit


@pytest.fixture
def clean_root_logger():
    """Snapshot and restore root-logger handlers/level around each test."""
    root = logging.getLogger()
    saved_handlers = list(root.handlers)
    saved_level = root.level
    yield root
    root.handlers[:] = saved_handlers
    root.setLevel(saved_level)


def _itrader_handlers(root: logging.Logger) -> list[logging.Handler]:
    return [h for h in root.handlers if getattr(h, "_itrader_handler", False)]
```

**Reuse the `monkeypatch.setenv`/`delenv` + `init_logger()` driving pattern** (lines 64-71):
```python
def test_log_level_env_honored(monkeypatch, clean_root_logger):
    monkeypatch.setenv("ITRADER_LOG_LEVEL", "DEBUG")
    assert _env_log_level() == "DEBUG"
    init_logger()
    assert clean_root_logger.level == logging.DEBUG
```

**D-06 gate-transparency tests to add (contract from CONTEXT D-06):**
1. **Above level:** the wrapper emits identical content + fields as a direct structlog call (capture via a list-capturing handler or `structlog` testing capture).
2. **Below level:** nothing emits (set `ITRADER_LOG_LEVEL=ERROR`, call `.debug(...)`/`.warning(...)` → assert zero records captured — proves the `isEnabledFor` short-circuit).
3. **Admission-content equivalence:** the demoted admission line renders the **same content at `WARNING`** as the prior `error` content (D-06 — locks that demotion changes level/volume, NOT emitted content).
4. **`ITRADER_DISABLE_LOGS` (D-08):** set the env true → all levels short-circuit (assert zero records even at `error`/`critical`).

Use the `bind(component=...)` path (`get_itrader_logger().bind(component="Test")`) to exercise the `__new__` `_stdlib` carry-over (D-02) — a gate that doesn't carry `_stdlib` onto bound instances would `AttributeError`; this test is the lock for that.

---

## Shared Patterns

### Env-var-driven config knob (D-08)
**Source:** `itrader/logger.py::_env_log_level`/`_env_json_logs` (lines 26-42) + `itrader/config/settings.py::Settings` (lines 20-33)
**Apply to:** `ITRADER_DISABLE_LOGS` declaration (settings.py) + its cache-once read (logger.py)
**Critical gotcha (Pitfall 8):** NEVER instantiate `Settings()` at import time — `database_url: SecretStr` is required-no-default and raises `ValidationError` on every `import itrader`. The existing logger helpers read `os.environ` directly for exactly this reason. The pydantic `Settings` field is the documented knob surface; the runtime read must not force an import-time `Settings()` build.

### Equivalence drift-lock test (D-06/D-07)
**Source:** `tests/unit/portfolio/test_realised_pnl_accumulator.py` (Phase 3 D-03 precedent — entire file)
**Apply to:** both new test files
**Pattern:** module docstring citing the decision + "this is the dedicated unit-level drift lock; oracle/determinism are the run-path locks; no hot-path runtime guard is added (re-paying the cost is what the phase removes)"; an independent oracle reproducing the PRIOR behavior; `==` value-equality (criterion #2 contract); multi-scenario coverage.

### Test fixtures (logging + strategy)
**Source:** `test_logger_config.py` (`clean_root_logger`, `_itrader_handlers`, `monkeypatch` env driving) and `test_strategy.py` (`_sma_kwargs()`, `SMAMACDStrategy`, `json.dumps(to_dict())` round-trip)
**Apply to:** the new logging-gate and type-hint/snapshot tests respectively — reuse verbatim, do not re-invent.

### Lazy `%s` logging + cached `isEnabledFor` guard
**Source:** `admission_manager.py` lines 251-253 (sibling `warning` with `%s` + list-comp) and the D-01 transformation of lines 234-237
**Apply to:** the demoted admission line only (D-03: every other hot log call already passes in-hand values with lazy `%s`/kwargs — no per-site guards elsewhere).

---

## Curated `debug()` delete/keep (D-04 — planner proposes, owner signs off per line)

| Callsite | CONTEXT verdict | Indent |
|----------|-----------------|--------|
| `order_handler/order_handler.py:135` `'Processing signal ...'` | **KEEP** (live-trading visibility) | tab |
| `order_handler/order_handler.py:147` `'OrderEvent sent ...'` | **KEEP** | tab |
| `strategy_handler/strategies_handler.py:255` `'Strategy signal ...'` | **KEEP** | tab |
| `execution_handler/exchanges/simulated.py:298` `'Order executed ...'` | **KEEP** | tab |
| `portfolio_handler/position/position_manager.py:198` `'Position updated'` | **DELETE** (internal mechanics) | 4-space |
| `portfolio_handler/position/position_manager.py:273` `'Position market values updated'` | **DELETE** | 4-space |
| `portfolio_handler/cash/cash_manager.py:366` `'Fill cash flow applied'` | **DELETE** | 4-SPACE |
| `portfolio_handler/cash/cash_manager.py:539` `'Cash reserved'` | **DELETE** | 4-SPACE |
| `portfolio_handler/cash/cash_manager.py:571` `'Cash reservation released'` | **DELETE** | 4-SPACE |
| `portfolio_handler/cash/cash_manager.py:598` `'Margin locked'` | **DELETE** | 4-SPACE |
| `portfolio_handler/cash/cash_manager.py:624` `'Margin released'` | **DELETE** | 4-SPACE |
| `order_handler/admission/admission_manager.py:383` `'Processed signal ...'` | **DELETE** | tab |

**Rules:** `info()` is NEVER touched; levels are unchanged (no `debug`→`info` promotion); scope is hot-path only — no whole-codebase audit. The central gate (D-02) makes the KEEP lines free at the ERROR benchmark level while available at DEBUG for live debugging.

## No Analog Found

None — every file maps either to itself (modified source, the analog IS the surrounding code) or to a clear existing test precedent.

## Metadata

**Analog search scope:** `itrader/logger.py`, `itrader/config/settings.py`, `itrader/order_handler/admission/`, `itrader/strategy_handler/base.py`, `itrader/portfolio_handler/{position,cash}/`, `tests/unit/{core,strategy,portfolio}/`
**Files scanned:** ~14 (4 source-to-modify, 4 curated-edit/read-only source, 3 analog test files, 3 cross-ref)
**Pattern extraction date:** 2026-06-24

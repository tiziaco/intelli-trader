# Phase 2: Strategy Authoring Surface - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-06-12
**Phase:** 2-strategy-authoring-surface
**Areas discussed:** Config-layer fate + blast radius, Validation mechanism + cross-field rules, init() hook scope this phase, Reconfigure surface: Phase 2 vs Phase 4

---

## Config-layer fate + blast radius

### Q1: How far does the config-layer removal go this phase?

| Option | Description | Selected |
|--------|-------------|----------|
| Full delete | Delete config/strategy.py, SMA_MACDConfig, EmptyStrategyConfig; class-attribute surface fully replaces them; no dead dual-path | ✓ |
| Keep BaseStrategyConfig internal | Retire subclasses but keep BaseStrategyConfig as a hidden pydantic model built from declared attrs | |
| You decide | Planner picks cleanest byte-exact diff | |

**User's choice:** Full delete

### Q2: Source of truth for to_dict()/__str__ after removal?

| Option | Description | Selected |
|--------|-------------|----------|
| Read instance attrs | to_dict()/__str__ read real instance attrs directly; drop self.config; keep serialized shape byte-identical where observed | ✓ |
| Preserve config-shaped dict | Keep exact key set/shape, sourced from attrs | |
| You decide | Planner resolves per consumers | |

**User's choice:** Read instance attrs

### Q3: SignalRecord.config replacement?

| Option | Description | Selected |
|--------|-------------|----------|
| Snapshot dict from strategy | Replace config: BaseStrategyConfig with a plain params snapshot dict; model_dump callers become dict accessors; preserves SIG-02 queryability | ✓ |
| Keep typed snapshot object | New frozen dataclass snapshot type | |
| You decide | Planner picks | |

**User's choice:** Snapshot dict from strategy

### Q4: Migration breadth for e2e fixtures + tests?

| Option | Description | Selected |
|--------|-------------|----------|
| Migrate all, byte-exact | Migrate every site this phase (SMA_MACD, EmptyStrategy, e2e fixtures, all tests, run_backtest, cross-val); e2e 58/58 + oracle byte-exact | ✓ |
| Minimal + adapter shim | Migrate reference + run path; keep a shim for fixtures temporarily | |
| You decide | Planner decides scope; byte-exact gate non-negotiable | |

**User's choice:** Migrate all, byte-exact

---

## Validation mechanism + cross-field rules

### Q1: How does the base implement collect/apply/coerce/reject?

| Option | Description | Selected |
|--------|-------------|----------|
| Pure-python introspection | Inspect __annotations__/class attrs, apply kwargs, coerce enums manually, raise UnknownParamError; no pydantic; mypy sees real attrs | ✓ |
| Hidden pydantic from annotations | Build internal pydantic model from annotations for coercion/validation | |
| You decide | Planner picks cleanest mypy-strict + byte-exact mechanism | |

**User's choice:** Pure-python introspection

### Q2: Fate of short_window<long_window (HARD-02) + gt=0 constraints?

| Option | Description | Selected |
|--------|-------------|----------|
| Drop, add validate() hook | Drop Field(gt=0)+@model_validator; add optional overridable validate() hook; SMA_MACD keeps short<long assert there | ✓ |
| Drop entirely | Remove cross-field + constraints, no replacement | |
| You decide | Planner decides | |

**User's choice:** Drop, add validate() hook

### Q3: Required-no-default signaling + enum coercion targets?

| Option | Description | Selected |
|--------|-------------|----------|
| Bare annotation = required | Name in __annotations__ with no value = required; enum coercion on timeframe/order_type/direction; subclass knobs keep literal defaults | ✓ |
| Explicit REQUIRED sentinel | Use a sentinel default for required fields | |
| You decide | Planner picks | |

**User's choice:** Bare annotation = required

---

## init() hook scope this phase

### Q1: What does init() do in Phase 2 (indicators are Phase 3)?

| Option | Description | Selected |
|--------|-------------|----------|
| Empty re-runnable hook | init() introduced as overridable lifecycle hook called at end of construction, re-runnable/idempotent; SMA_MACD init() empty; indicators inline + max_window/warmup hand-set until Phase 3 | ✓ |
| Defer init() to Phase 3 | Ship only the param surface; add init() in Phase 3 | |
| You decide | Planner decides how much init() machinery lands now | |

**User's choice:** Empty re-runnable hook

### Q2: Idempotency posture / how much to build+prove now?

| Option | Description | Selected |
|--------|-------------|----------|
| Build seam, light test | Build re-runnable init() + a focused double-init() idempotency test; don't build full reconfig pipeline | ✓ |
| Seam only, no re-run test | Hook + call once; defer re-runnability testing to Phase 4 | |
| You decide | Planner decides idempotency proof scope | |

**User's choice:** Build seam, light test

---

## Reconfigure surface: Phase 2 vs Phase 4

### Q1: Strategy-level reconfigure method now, or init() seam + docs only?

| Option | Description | Selected |
|--------|-------------|----------|
| Strategy-level method now | Ship reconfigure(**kwargs): re-apply+coerce → re-validate → re-run init(); the sanctioned-reconfigure discipline; single-strategy scope; no handler/queue wiring | ✓ |
| Seam + discipline only | Ship only re-runnable init() + documented discipline; method lands with COMP-02 in Phase 4 | |
| You decide | Planner decides Phase 2 vs Phase 4 | |

**User's choice:** Strategy-level method now

### Q2: Any accidental-mutation guard this phase?

| Option | Description | Selected |
|--------|-------------|----------|
| Docs + method discipline only | No runtime guard; rely on documented sanctioned-method-only discipline + reconfigure method | ✓ |
| Lightweight guard | __setattr__ guard warning/blocking direct mutation outside the method | |
| You decide | Planner decides | |

**User's choice:** Docs + method discipline only

---

## Claude's Discretion

- name / strategy_id derivation details (default name source, optional name class attr).
- Exact snapshot-dict / to_dict() key shape (keeping observed serialized shapes byte-identical).
- Precise validate() hook signature/placement and how SMA_MACD's short<long assert is expressed.
- Internal structure of the introspection/coercion engine (mypy-strict + byte-exact).

## Deferred Ideas

- Auto-derived warmup/max_window from indicator recipes → Phase 3 (IND-01).
- Declared-indicator framework, model-B pre-eval reads, free-function crossover/crossunder → Phase 3 (IND-01).
- Handler-level uniform update_config on StrategiesHandler → Phase 4 (COMP-02).
- Indicator handle type (raw Series vs positional wrapper) → Phase 3 spec-time.
- SMA_MACD full migration onto the indicator framework (boundary-semantics match) → Phase 3.
- Indicator-based SL/TP consuming the decoupled recipe → future phase.
- Stateful/incremental indicator backends (IND-02) → deferred (W1-05 byte-exactness risk).

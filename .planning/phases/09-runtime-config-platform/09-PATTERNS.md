# Phase 9: Runtime-Config Platform - Pattern Map

**Mapped:** 2026-07-16
**Files analyzed:** 14 new/modified
**Analogs found:** 14 / 14 (every P9 file wires or clones an existing seam — RESEARCH: "P9 is mostly wiring + one restructure, not new machinery")

> **Indentation is per-file — verified by byte scan (do NOT generalize a package).**
> `itrader/config/`, `itrader/events_handler/events/`, `itrader/storage/`, `trading_system/route_registrar.py`,
> `trading_system/live_trading_system.py`, `itrader/__init__.py`, and `migrations/versions/` are all **4-space**.
> BUT `events_handler/full_event_handler.py` and `execution_handler/execution_handler.py` are **TABS**.
> (Also per memory: `engine_context.py` / `compose.py` / `backtest_trading_system.py` are TABS.)

> **Landmine (verified in code):** the Event base is `msgspec.Struct`, NOT a frozen `@dataclass`.
> CLAUDE.md's "frozen dataclass" language is stale. Copy `events/control.py` EXACTLY.

> **Path correction:** migrations live at **repo-root `migrations/versions/`** and `migrations/env.py`,
> NOT under `itrader/storage/migrations/`. The `system_stats` migration + `env.py` registration go there.

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `itrader/config/itrader_config.py` (NEW `ITraderConfig`) | config | transform | `itrader/config/system.py::SystemConfig` | exact (repurpose) |
| `itrader/config/system.py` (demote → `system:` sub-model; drop `PerformanceSettings`/`MonitoringSettings`) | config | transform | itself + `stream.py`/`safety.py` sub-models | exact |
| `itrader/config/` new `UniverseConfig` sub-model | config | transform | `MonitoringSettings` (2 kept fields) in `system.py` | exact |
| `itrader/__init__.py` (`config = SystemConfig.default()` → `config = ITraderConfig(...)`) | config/bootstrap | transform | existing `config`/`idgen` singleton block | exact |
| `itrader/events_handler/events/control.py` (add `ConfigUpdateEvent`) | event/model | event-driven | `StreamStateEvent`/`ConnectorFatalEvent` (same file) | exact |
| `itrader/events_handler/full_event_handler.py` (wire `CONFIG_UPDATE` route) | route table | event-driven | `STRATEGY_COMMAND: []` slot (same file) | exact |
| `itrader/trading_system/route_registrar.py` (register `CONFIG_UPDATE` consumer + `_on_config_update`) | route registrar | event-driven | `_on_stream_state`/`_on_connector_fatal` (same file) | exact |
| `itrader/trading_system/live_trading_system.py::add_event` (extend allowlist + ingress 400) | middleware/admission | request-response | existing `_EXTERNALLY_ADMISSIBLE` gate | exact |
| `itrader/trading_system/live_trading_system.py::build_live_system` (store construction + restart layering) | composition/factory | batch | existing `build_live_system` | role-match |
| `itrader/storage/system_stats_store.py` (NEW store + `build_system_stats_table`) | store/model | append-only | `equity_snapshots` table + `SystemStore` template | exact (clone) |
| `migrations/versions/system_stats.py` (NEW migration) | migration | schema | `migrations/versions/strategy_registry.py` | exact (clone) |
| `migrations/env.py` (register `build_system_stats_table`) | migration wiring | schema | existing `build_*_table(target_metadata)` block | exact |
| `itrader/storage/system_store.py` / `venue_store.py` (finalize surface, D-25) | store | CRUD | existing `upsert`/`get`/`read_all` | exact (likely no new methods) |
| `itrader/execution_handler/execution_handler.py::_resolve_rng_seed` (path move) | utility | transform | existing `_resolve_rng_seed` | exact |

## Pattern Assignments

### `itrader/config/itrader_config.py` — NEW `ITraderConfig` (config, transform) — 4-SPACE

**Analog:** `itrader/config/system.py::SystemConfig` (lines 87-162). The restructure REPURPOSES this class
(rename → `ITraderConfig`, add `frozen=True`, demote lifecycle fields, drop `Performance`/`Monitoring`).

**Class + `model_config` pattern** (`system.py:87-93`):
```python
class SystemConfig(BaseModel):
    """Main system configuration."""
    # D-09: reject unknown keys.
    model_config = ConfigDict(extra="forbid")
```
For `ITraderConfig`: `model_config = ConfigDict(frozen=True, extra="forbid")` (D-06/D-07).

**Frozen base params to keep DIRECTLY on the aggregator** (`system.py:95-103`) — identity + determinism (D-04/D-08):
```python
    name: str = "iTrader System"
    version: str = "1.0.0"
    environment: Environment = Environment.DEVELOPMENT
    debug_mode: bool = True
    data_dir: str = "data"
    log_dir: str = "logs"
    config_dir: str = "settings"
    cache_dir: str = "cache"
```
ADD `rng_seed: int = 42` here (moved off `PerformanceSettings`, D-09). ⚠ **Pitfall 5 (verified):** the
frozen guard ONLY protects fields DIRECTLY on the aggregator — a field nested in a mutable sub-model is
fully mutable. Every immutable-at-runtime key MUST be a direct base field.

**Mutable sub-model field pattern** (`system.py:105-127`) — each is `Field(default_factory=...)`:
```python
    stream: StreamSettings = Field(default_factory=StreamSettings)
    feed_provider: FeedProviderSettings = Field(default_factory=FeedProviderSettings)
    safety: SafetySettings = Field(default_factory=SafetySettings)
    runtime: Settings = Field(default_factory=Settings)   # env-leaf (D-08) — stays a FIELD, not root
```
New sub-models to add: `system` (demoted lifecycle), `universe` (ex-Monitoring 2 fields), `order`.
Each mutable sub-model gets `model_config = ConfigDict(validate_assignment=True)` (D-13).

**Inertness lever — KEEP the lazy `sql` accessor VERBATIM** (`system.py:134-148`, Pitfall 3 / GATE-01):
```python
    @cached_property
    def sql(self) -> "SqlSettings":
        from itrader.config.sql import SqlSettings   # lazy — keeps sqlalchemy off the backtest import graph
        return SqlSettings()
```

**Fields to DELETE** (D-09, re-grep `.performance.` / `.monitoring.` / field names before deleting):
`PerformanceSettings` (`system.py:46-59`, keep only `rng_seed`); `MonitoringSettings` (`system.py:62-84`,
keep `universe_poll_cadence_s`→`poll_cadence_s`, `universe_remove_policy`→`remove_policy` into `UniverseConfig`).
Lifecycle fields `system.py:129-132` (`enable_auto_restart` etc.) demote into the `system:` sub-model (D-08).

---

### `itrader/__init__.py` — singleton (config/bootstrap, transform) — 4-SPACE

**Analog:** the existing block (`__init__.py:1-13`):
```python
from itrader.config import SystemConfig
...
config = SystemConfig.default()   # → config = ITraderConfig(...)  (create ONCE, mutate in place)
logger = init_logger(config)
idgen = IDGenerator()
```
D-06: create ONCE at import with EMPTY persisted overrides (import-inert, no SQL/ccxt).
**Pitfall 6:** never REASSIGN `config` in the factory — the factory mutates `config.<sub>.<field>` in place,
so `from itrader import config` importers see every change.

---

### `itrader/events_handler/events/control.py` — `ConfigUpdateEvent` (event, event-driven) — 4-SPACE

**Analog:** `StreamStateEvent`/`ConnectorFatalEvent` in the SAME file (`control.py:37-71`). ⚠ **msgspec.Struct,
NOT dataclass.** Copy the exact shape:
```python
class StreamStateEvent(Event, frozen=True, kw_only=True, gc=False):
    type: ClassVar[EventType] = EventType.STREAM_STATE
    stream_name: str
    up: bool
```
For `ConfigUpdateEvent`: `type: ClassVar[EventType] = EventType.CONFIG_UPDATE` (slot already exists), plus
`scope: str`, `key: str`, `value: Any`. Import `from typing import ClassVar` (already at `control.py:30`);
add `Any`. **V7 secret-scrub note** (`control.py:18-23`): `value` must never carry a credential to a store.

---

### `itrader/events_handler/full_event_handler.py` — route slot (route table, event-driven) — ⚠ TABS

**Analog:** the pre-declared slot in the `_routes` literal (`full_event_handler.py:113`):
```python
			EventType.CONFIG_UPDATE: [],       # NEW (BUS-03) — CONTROL-plane scoped runtime config change
```
The empty slot exists; the live consumer is populated by `route_registrar.py` (below), not here. **This file
is TAB-indented** — do not add spaces.

---

### `itrader/trading_system/route_registrar.py` — register consumer + router (route registrar, event-driven) — 4-SPACE

**Analog:** `_on_stream_state`/`_on_connector_fatal` registration (`route_registrar.py:121-122`, its docstring
at line 27 already says *"The P9 CONFIG_UPDATE route populates the same way when its consumer lands"*):
```python
        routes[EventType.STREAM_STATE] = [self._on_stream_state]
        routes[EventType.CONNECTOR_FATAL] = [self._on_connector_fatal]

    def _on_stream_state(self, event: Any) -> None:
        """STREAM_STATE CONTROL consumer (SAFE-03/§11c): up -> resume, down -> pause."""
        ...
```
Add `routes[EventType.CONFIG_UPDATE] = [self._on_config_update]` and an `_on_config_update` method
implementing validate → persist → apply → push (D-15). Router skeleton is in RESEARCH §"engine-thread router".

---

### `itrader/trading_system/live_trading_system.py::add_event` — allowlist extend (admission, request-response) — 4-SPACE

**Analog:** `_EXTERNALLY_ADMISSIBLE` + the gate (`live_trading_system.py:53` and `:904-910`):
```python
_EXTERNALLY_ADMISSIBLE = frozenset({EventType.SIGNAL, EventType.STRATEGY_COMMAND})
...
        event_type = getattr(event, 'type', None)
        if event_type not in _EXTERNALLY_ADMISSIBLE:
            self.logger.warning('Rejected external add_event of type %s (D-10 fail-closed default-deny) ...')
            return False
```
D-23: add `EventType.CONFIG_UPDATE` (third type). Update the warning/docstring strings that enumerate
"only SIGNAL and STRATEGY_COMMAND". Add ingress-side 400-style validation (bad type/range → `return False`)
BEFORE the `global_queue.put`. **P9 tests MUST drive `add_event(ConfigUpdateEvent(...))` directly (D-23, mandatory).**

---

### `itrader/trading_system/live_trading_system.py::build_live_system` — factory (composition, batch) — 4-SPACE

**Analog:** existing `build_live_system` (`live_trading_system.py:931`). D-22: construct `SystemStore`/`VenueStore`
+ new `system_stats` store, then layer `defaults ← YAML ← env ← persisted` by field-wise `setattr` into the
mutable sub-models (D-10 recipe in RESEARCH — base params resolved at construction, persisted applied here).

---

### `itrader/storage/system_stats_store.py` — NEW append-only store (store, append-only) — 4-SPACE

**Analog A (table shape):** `equity_snapshots` (`portfolio_handler/storage/models.py:174-197`) — composite PK
`(natural_key, seq)`, `autoincrement=False`, `UtcIsoText` timestamp, no UUID surrogate:
```python
        tables["equity_snapshots"] = Table(
            "equity_snapshots", metadata,
            Column("portfolio_id", Uuid(as_uuid=True), primary_key=True),
            Column("seq", Integer, primary_key=True, autoincrement=False),   # backend writes seq, not the DB
            Column("timestamp", UtcIsoText, nullable=False),
            Column("total_equity", Numeric, nullable=False),
            ...
        )
```

**Analog B (store class + registrar single-source):** `SystemStore` (`storage/system_store.py:33-97`) —
`build_*_table` idempotent guard + schema-pure constructor (WR-03/D-14, no runtime `create_all`) + parameterized
Core (never f-string SQL):
```python
def build_system_store_table(metadata: MetaData) -> Table:
    if "system_store" in metadata.tables:
        return metadata.tables["system_store"]
    return Table("system_store", metadata, Column("key", String, primary_key=True), ...)

class SystemStore:
    def __init__(self, sql_engine: SqlEngine) -> None:
        self.backend = sql_engine
        self.engine: Engine = sql_engine.engine
        self.system_store: Table = build_system_store_table(sql_engine.metadata)
        self.logger = get_itrader_logger().bind(component="SystemStore")
    def upsert(self, key, value, at): ...      # delete-then-insert in one engine.begin()
```
For `system_stats`: needs `append(row, at)` + `read_recent(n)`/`read_all()` (D-25). Column set is Claude's
discretion (D-18 — start minimal: throttle_breach_count, error_count_{warning,error,critical}, queue_depth,
uptime_seconds, connector_up, stream_up). Money-typed columns → `Numeric` + Decimal end-to-end.

---

### `migrations/versions/system_stats.py` — NEW migration (migration, schema) — 4-SPACE

**Analog:** `migrations/versions/strategy_registry.py` (full file). Copy its structure verbatim:
```python
import itrader.storage.types   # ⚠ Pitfall 8 — autogenerate OMITS the UtcIsoText import; hand-add it

revision: str = "strategy_registry"
down_revision: Union[str, Sequence[str], None] = "venue_config"
...
        sa.Column("updated_at", itrader.storage.types.UtcIsoText(), nullable=False),
```
For `system_stats`: `revision="system_stats"`, `down_revision="strategy_registry"` (chain after P4's head —
current chain: `d10_halt_records → system_store → venue_config → strategy_registry`).

---

### `migrations/env.py` — register registrar (migration wiring, schema) — 4-SPACE

**Analog:** the registrar block (`migrations/env.py:62-79`):
```python
target_metadata = MetaData(naming_convention=NAMING_CONVENTION)
build_order_tables(target_metadata)
...
build_system_store_table(target_metadata)
build_venue_store_table(target_metadata)
build_strategy_registry_tables(target_metadata)
```
Add `from itrader.storage.system_stats_store import build_system_stats_table` (with the other imports at
`env.py:30-38`) and `build_system_stats_table(target_metadata)`. The metadata-parity gate auto-covers the new
table (env.py imports every registrar — verify the parity test enumerates dynamically, A3).

---

### `itrader/storage/system_store.py` / `venue_store.py` — finalize surface (store, CRUD) — 4-SPACE

**Analog:** existing methods. `SystemStore.upsert/get/delete/read_all` (`system_store.py:82-139`) already cover
`config.*` upsert/read for restart layering AND `state.*` upsert — both are namespaced KV keys (e.g.
`"state.status"`, `"config.system.enable_auto_restart"`). **Likely NO new methods needed (A2)** — the only
decision is the key-naming convention. `VenueStore` has `upsert(venue_name, config, enabled, at)`/`get`/
`list_enabled`/`read_all` (`venue_store.py:127-190`) + `_assert_no_secret_keys` recursive denylist
(`venue_store.py:56`) — sufficient for venue-scope config.

---

### `itrader/execution_handler/execution_handler.py::_resolve_rng_seed` — path move (utility, transform) — ⚠ TABS

**Analog:** the method itself (`execution_handler.py:70-82`) — ORACLE-GATED (Pitfall 2):
```python
	def _resolve_rng_seed(self) -> int:
		from itrader import config
		return int(config.performance.rng_seed)   # → config.rng_seed  (D-09; must still resolve to 42)
```
Change `config.performance.rng_seed` → `config.rng_seed` in the SAME plan as the restructure; run
`tests/integration/test_backtest_oracle.py` as the per-plan gate (byte-exact `134 / 46189.87730727451`).
**This file is TAB-indented.**

## Shared Patterns

### Registrar single-source (schema)
**Source:** `storage/system_store.py:33-54` + `migrations/env.py:62-79`
**Apply to:** the new `system_stats` store/table.
`build_*_table(metadata)` is the ONE definition feeding BOTH test-path `create_all` and Alembic
`target_metadata`. Idempotent guard `if "<name>" in metadata.tables: return metadata.tables["<name>"]`.

### msgspec.Struct events (event-driven)
**Source:** `events_handler/events/control.py:37-71`
**Apply to:** `ConfigUpdateEvent`.
`class X(Event, frozen=True, kw_only=True, gc=False)` + `type: ClassVar[EventType] = EventType.X`.
NEVER a frozen `@dataclass`. NEVER stringify an exception/payload into an event field (V7 secret-scrub).

### Schema-pure store construction (WR-03/D-14)
**Source:** `storage/system_store.py:69-76`
**Apply to:** `system_stats` store.
Constructor registers the table on `sql_engine.metadata` but NEVER runs `create_all` — production schema is
Alembic-owned; tests provision via `tests.support.schema.provision_schema`.

### Import inertness (GATE-01)
**Source:** `config/system.py:134-148` (lazy `sql` `@cached_property`)
**Apply to:** `ITraderConfig` + every new config sub-model.
`config/` imports only pydantic/stdlib. `config = ITraderConfig()` at import stays SQL/ccxt-free; persisted-
override LOADING happens in `build_live_system`, never at import. Gate: `tests/integration/test_okx_inertness.py`.

### handler.update_config push (D-01)
**Source:** `execution_handler/execution_handler.py:85-99` (`update_config` → exchange)
**Apply to:** the router's apply step. Every handler already has `update_config(...)` — reuse it; build no
observer/pubsub bus for config change propagation.

### Decimal money (correctness-critical)
**Source:** CLAUDE.md Money Policy; `equity_snapshots` `Numeric` columns
**Apply to:** any money-typed `system_stats` column. `Numeric` in the table; Decimal end-to-end; `float()`
only at the serialization edge.

## No Analog Found

None. Every P9 file clones or wires an existing seam.

## Metadata

**Analog search scope:** `itrader/config/`, `itrader/events_handler/events/`, `itrader/storage/`,
`itrader/trading_system/`, `itrader/execution_handler/`, `itrader/portfolio_handler/storage/`,
repo-root `migrations/`.
**Files scanned:** 10 read in full/part (control.py, system_store.py, system.py, strategy_registry.py,
models.py, venue_store.py, live_trading_system.py, route_registrar.py, __init__.py, execution_handler.py) + grep sweeps.
**Pattern extraction date:** 2026-07-16
</content>
</invoke>

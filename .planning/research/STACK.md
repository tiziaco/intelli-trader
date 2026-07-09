# Stack Research

**Domain:** Brownfield structural refactor of an event-driven algo-trading engine (v1.8 — Live System Refactor & Live-Readiness Hardening)
**Researched:** 2026-07-09
**Confidence:** HIGH

## Headline

**v1.8 needs ZERO new third-party dependencies.** Every mechanic the refactor introduces —
the two-tier priority `EventBus`, the three new durable stores + Alembic chain, the venue
registry/plugin system, and the runtime-config platform — is satisfied by (a) Python
**stdlib** constructs (`queue.PriorityQueue`, `itertools.count`, `typing.Protocol`,
`dataclasses`, `functools`) and (b) libraries **already pinned and validated** in the
codebase (SQLAlchemy 2.0, Alembic, pydantic 2 / pydantic-settings, msgspec, structlog,
uuid-utils). Adding a dependency for any of these would *actively regress* the inertness gate,
which is the opposite of the milestone's intent.

The rest of this document is the evidence for that verdict, item by item, plus the concrete
stdlib construct for each and the inertness impact.

---

## Recommended Stack

### Core Technologies (all EXISTING — no version change forced)

| Technology | Installed | Latest | Purpose in v1.8 | Verdict |
|------------|-----------|--------|-----------------|---------|
| Python stdlib `queue` / `itertools` / `typing` / `dataclasses` | 3.13 | 3.13 | `PriorityEventBus`, monotonic seq, `EventBus`/`VenuePlugin` Protocols, `EngineContext`/`VenueBundle` frozen dataclasses | **Use — no dependency** |
| SQLAlchemy | 2.0.50 | 2.0.51 | SQLAlchemy **Core** `Table`/`insert`/`select`/`update` for the 3 new stores (same pattern as `HaltRecordStore`) | **Keep** (2.0.50 is current-minus-one patch; no upgrade required for v1.8) |
| Alembic | 1.18.5 | 1.18.5 | Chain 3 new migrations after `d10_halt_records`; relocate `script_location` to project-root `migrations/` | **Keep — already latest** |
| pydantic + pydantic-settings | 2.13.4 / 2.14 | 2.13.x / 2.14 | Extend `SystemConfig` (eager/lazy/template split), `RuntimeConfig` overlay, per-store config models | **Keep** |
| msgspec | 0.21.1 | 0.21.x | Existing `Bar`/event structs — the priority-tuple wraps these unchanged | **Keep** |
| structlog | 24.4.0 | 24.x | `ErrorHandler` severity-mapped logging (existing) | **Keep** |
| uuid-utils | 0.16.0 | 0.16.x | UUIDv7 PKs for new store rows (via `idgen` singleton) | **Keep** |

### Supporting stdlib constructs (the actual "additions")

| Construct | Module | Where it lands | Why stdlib suffices |
|-----------|--------|----------------|---------------------|
| `queue.PriorityQueue` | `queue` | `events_handler/bus.py::PriorityEventBus` | Thread-safe priority heap with the same `.get/.put` surface as the existing `queue.Queue`; already the substrate the live engine thread expects |
| `itertools.count()` | `itertools` | `PriorityEventBus` seq generator | Thread-safe monotonic counter (the `__next__` increment is atomic under CPython's GIL); the unique tiebreaker that stops tuple comparison at `seq` |
| `typing.Protocol` | `typing` | `EventBus`, `ExecutionVenuePlugin`, `LiveDataProvider`, `PortfolioReadModel` (existing pattern) | Structural typing = zero-import registration; the codebase already uses this idiom (`PortfolioReadModel`, `_AlertSinkLike`) |
| `@dataclass(frozen=True)` | `dataclasses` | `EngineContext`, `VenueBundle`, tier enum carriers | Matches every existing event/value object; frozen = the single-writer/snapshot-read contract |
| `functools.cached_property` | `functools` | `SystemConfig.sql` lazy accessor | First-access resolution keeps Postgres `SqlSettings` off the import path (inertness) |
| `dict[(venue, account_id), LiveConnector]` | builtin | connector memoization at the composition root | A plain dict *is* the registry; entry-points/plugin libs would break lazy-import inertness |

### Development Tools (unchanged)

| Tool | Purpose | Notes |
|------|---------|-------|
| pytest + strict config | Test gate | `filterwarnings=["error"]`, strict markers — new `PriorityEventBus`/store tests must be warning-clean |
| mypy `--strict` | Type gate | New collaborators (bus, registries, stores) must be strict-clean; live subsystems may keep their `[[tool.mypy.overrides]]` |
| testcontainers (existing) | Postgres round-trip tests | New stores follow the `HaltRecordStore` test pattern (in-process SQLite `create_all` + Postgres testcontainer) |

## Installation

```bash
# NOTHING to install. All v1.8 mechanics are stdlib or already-pinned deps.
# Explicitly: do NOT add pypubsub / blinker / pluggy / stevedore / dynaconf /
# python-configuration / an entry-points plugin loader. Each would regress the
# inertness gate and duplicate a stdlib capability.
```

---

## Point-by-point evaluation (the five questions)

### 1. Two-tier priority `EventBus` — stdlib `queue.PriorityQueue` + `itertools.count()` ✅

**Verdict: stdlib, no new dependency.** `queue.PriorityQueue` (a thread-safe binary-heap
wrapper over `heapq`) is the correct substrate. No third-party bus (pypubsub, blinker,
zmq, an actor framework) is warranted: they add async/serialization/transport machinery the
single-consumer engine-thread model does not need, and every one of them would be a heavy
import that must NOT touch the backtest path.

**The tuple-ordering correctness point (addressed concretely):**

The heap orders `(tier, seq, event)` tuples by lexicographic comparison. Tuple comparison is
short-circuit: it compares `tier` first; on a tie it compares `seq`; only on a `seq` tie
would it reach `event`. Because frozen event dataclasses/`msgspec.Struct`s define **no
`__lt__`**, reaching `event` would raise `TypeError: '<' not supported`. The fix is that
`seq` is drawn from a single process-wide `itertools.count()`, so **`seq` is globally unique
by construction** — two entries can never tie on `seq`, so the comparison provably terminates
at `seq` and never dereferences `event`. This also gives strict FIFO *within* a tier (lower
`seq` = earlier `put`, dequeued first) and strict CONTROL-before-BUSINESS preemption *across*
tiers.

```python
# events_handler/bus.py  (4-space file — matches events_handler/events/ package)
import itertools, queue
from typing import Any, Protocol

_CONTROL = 0
_BUSINESS = 1
_CONTROL_EVENT_TYPES: frozenset = frozenset({...})  # STREAM_STATE, CONNECTOR_FATAL, CONFIG_UPDATE, STRATEGY_COMMAND

class PriorityEventBus:
    def __init__(self) -> None:
        self._q: "queue.PriorityQueue[tuple[int, int, Any]]" = queue.PriorityQueue()
        self._seq = itertools.count()          # thread-safe monotonic tiebreaker
    def put(self, event: Any) -> None:
        tier = _CONTROL if event.type in _CONTROL_EVENT_TYPES else _BUSINESS
        self._q.put((tier, next(self._seq), event))   # next(count) is atomic under GIL
```

Notes for the planner:
- `next(itertools.count())` is atomic under CPython (a single bytecode into C) — no extra
  lock needed for the counter. If the project ever targets a free-threaded (PEP 703) build,
  wrap `next(self._seq)` in a `threading.Lock`; document the assumption either way.
- The `FifoEventBus` (backtest) is a thin `queue.Queue` wrapper — it never constructs a
  `PriorityQueue`, so the priority path carries **zero oracle risk** (design §4a confirms).
- Keep the shared `.put/.get/.get_nowait/.qsize/.empty` surface so `compose_engine` is
  bus-agnostic; add `depth_by_tier()` for monitoring (unbounded-but-watched).

### 2. Alembic chain for 3 new stores + `migrations/` relocation ✅

**Verdict: no new dependency; a handful of concrete Alembic 2.0/1.18 gotchas to respect.**

**Current chain head (verified):**
`2cbf0bf6b0b6` (baseline) → `47f2b41f3ffe` → `p05_venue_order_id` →
`hl5_transaction_venue_trade_id` → **`d10_halt_records` (HEAD)**. The design's
"chained after `d10_halt_records`" is correct — `d10_halt_records` **is** the single head,
so the new linear chain is:

```
d10_halt_records → system_store → venue_config → strategy_registry
```

Concrete hazards to encode in the P4/P5 plans:

1. **Verify the head at plan time, don't assume.** Add `poetry run alembic heads` as a
   pre-flight; it must return exactly one head (`d10_halt_records` today). If P4's rename
   lands a data-migration or anyone branches, a second head silently breaks `upgrade head`.
2. **`down_revision` chains by revision *id*, not by file path.** Relocating the entire
   `migrations/` directory (including `versions/`) preserves the chain with **zero revision
   edits** — the id pointers are path-independent. Do NOT renumber or rewrite existing
   revisions during the move.
3. **`script_location` relocation is a one-line `alembic.ini` edit.** `alembic.ini` already
   sits at the project root and already uses the modern `%(here)s` token model +
   `path_separator = os` (Alembic ≥1.16 style). Change `script_location =
   itrader/storage/migrations` → `script_location = migrations`. Because `%(here)s` = the
   ini's directory (= project root), this resolves to `<root>/migrations`. `prepend_sys_path
   = .` stays, so `env.py`'s `from itrader.storage... import build_*_table` /
   `NAMING_CONVENTION` imports keep resolving against the installed package. (Alembic 1.16+
   also allows moving this into `[tool.alembic]` in `pyproject.toml` — **do not** adopt that
   here; keep the working `alembic.ini` to minimize the relocation blast radius.)
4. **`env.py` must gain three `build_*_table(target_metadata)` calls** (mirroring the existing
   `build_order_tables`/`build_portfolio_tables`/`build_signal_tables`/`build_halt_records_table`
   registrar pattern) so `--autogenerate` sees the new tables and never emits a spurious DROP.
   Each new store owns its own `build_*_table` registrar as the single source of truth shared
   by its `create_all(checkfirst=True)` test path and the Alembic autogen path.
5. **`NAMING_CONVENTION` stays the single source of truth** — new tables inherit it via the
   shared `MetaData`, so autogenerate emits deterministic, byte-stable constraint/index names
   (no churn across regenerations).
6. **`render_as_batch=True` is already set** in both `env.py` configure paths — the new
   migrations get portable (move-and-copy) ALTERs for free (SQLite/libSQL-safe).
7. **`SqlBackend → SqlEngine` rename (LR-18)** must also update `itrader/storage/__init__.py`
   (which re-exports `SqlBackend`), `env.py`'s `from itrader.storage.backend import
   NAMING_CONVENTION` (→ `storage.engine`), the storage factory, and `halt_record_store.py`'s
   `from itrader.storage import SqlBackend`. Grep for `SqlBackend` before landing — it is
   imported in ≥4 modules.

**SQLAlchemy version note:** 2.0.50 → 2.0.51 is the only available bump and is a patch
release; **not required** for v1.8. Do NOT jump to the 2.1 beta line (2.1.0b2) — it is
pre-release and would be a needless correctness risk on a money-bearing store.

### 3. Venue plugin/registry system — stdlib Protocol + dict registry ✅

**Verdict: stdlib, no new dependency. An entry-points / plugin library is DISQUALIFIED by the
inertness gate.**

`typing.Protocol` for the `ExecutionVenuePlugin` / `LiveDataProvider` contracts + a plain
`dict[str, Plugin]` registry with **lazy imports inside `build_bundle`** is exactly right and
is already the house idiom (`PortfolioReadModel`, `AbstractExchange`, the exchange sub-registry
in `ExecutionHandler`).

Why an entry-points/plugin lib (`importlib.metadata.entry_points`, `pluggy`, `stevedore`,
`straight.plugin`) is the **wrong** tool here:
- The core requirement is *"registering `'okx'` pulls no `ccxt.pro` until `build_bundle` is
  called."* Entry-point discovery mechanisms **eagerly import** the target module to resolve
  the object — the direct opposite of the lazy-import inertness contract. They would break
  `test_okx_inertness.py`.
- Plugin libs solve *third-party/out-of-tree* discovery. All venues here are first-party,
  in-repo, and known at composition time. A dict literal populated by the factory is simpler,
  fully typed under mypy, and trivially unit-testable.
- The `replay` "test-only plugin registered only by a fixture" pattern (design §8e) is a
  three-line `registry["replay"] = ReplayPlugin()` in a conftest — no framework needed.

```python
class ExecutionVenuePlugin(Protocol):
    name: str
    connector_key: str | None
    def build_bundle(self, *, ctx, spec, connector, simulated_exchange) -> "VenueBundle": ...
    def new_account(self, *, portfolio_ref, config) -> "Account": ...

class OkxPlugin:                       # concrete, registered eagerly, imports NOTHING heavy
    name = "okx"; connector_key = "okx"
    def build_bundle(self, *, ctx, spec, connector, simulated_exchange):
        from itrader.execution_handler.exchanges.okx import OkxExchange   # LAZY — first heavy import here
        ...
```

Connector memoization = a lazy `dict[(venue, account_id), LiveConnector]` at the composition
root (design §8c). Builtin dict; no library.

### 4. Runtime-config platform — SQLAlchemy Core + pydantic ✅

**Verdict: stdlib + existing deps, no new dependency. No config-overlay library warranted.**

The runtime-config platform is three things, each already covered:
- **The durable key-value store** (`SystemStore`: `(key, value_json, updated_at)`, namespaced
  keys, upsert) → SQLAlchemy **Core** over the shared `sql_engine`, identical to
  `HaltRecordStore`. `value_json` uses the existing `json_variant` type helper from
  `itrader/storage/types.py`. No document-store or KV library.
- **The overlay** (`RuntimeConfig` = `defaults ← YAML ← env ← persisted overrides`) → a
  pydantic model with an explicit merge in the live factory, injected as
  `EngineContext.config`. pydantic-settings already layers env/YAML; the persisted-override
  layer is a dict merge over the base model. **Do NOT add `dynaconf` / `python-configuration`
  / `hydra`** — they bring their own loader/lifecycle that conflicts with the "engine-thread-
  write, snapshot-read" single-writer contract and with the import-safety split (eager vs lazy
  `sql` accessor). The design's overlay is a deliberately small, auditable merge; a framework
  would obscure the allowlist/immutable-at-runtime governance (§6e).
- **The scoped mutation flow** (`ConfigUpdateEvent` on the CONTROL plane → engine-thread
  handler routes to owner store) → existing event + queue machinery. No library.

The allowlist of runtime-mutable keys (§6e) is a frozenset/dict literal validated with
pydantic type/range checks — again stdlib + pydantic.

### 5. Inertness — nothing forces a new dep onto the BACKTEST import path ✅

**Verdict: confirmed clean for every item.**

| v1.8 item | Backtest-path import cost | Inertness verdict |
|-----------|---------------------------|-------------------|
| `FifoEventBus` (backtest bus) | `import queue` (already imported) | Inert — no priority path, no heavy import |
| `PriorityEventBus` | Constructed only by the live factory | Never touched on the backtest path |
| 3 new SQL stores | `EngineContext(sql_engine=None)` on backtest → stores never built; SQL-heavy modules stay quarantined out of `storage/__init__.py` (as today) | Inert — same GATE-01 discipline as v1.6/v1.7 |
| `migrations/` relocation | `env.py` executed by Alembic only, never imported at runtime | Inert (unchanged) |
| Venue registry / plugins | Registering `'okx'` imports no `ccxt.pro`; concretions lazy-imported inside `build_bundle` | Inert — the core plugin contract *is* the inertness guarantee |
| `SystemConfig` extension | Eager fields plain-BaseModel; `sql` via `cached_property` (first-access); venue creds owned by plugin | Inert — Postgres `SqlSettings` never constructed at import |

Guarding test: `tests/integration/test_okx_inertness.py` stays the enforcement mechanism.
Every new live-only module must be lazy-imported inside a `LiveTradingSystem`/factory arm and
must NOT be re-exported from a package barrel (`__init__.py`) that the backtest path imports —
the exact rule that keeps `SqlBackend`'s SQL-heavy `sql_store` out of `storage/__init__.py`
today.

---

## Alternatives Considered

| Recommended | Alternative | When the alternative would win (it does not here) |
|-------------|-------------|---------------------------------------------------|
| stdlib `queue.PriorityQueue` + `itertools.count` | pypubsub / blinker / an actor lib (pykka) | If the engine needed multi-consumer fan-out or network transport. It has one consumer thread + one asyncio connector loop bridged by the queue — a bus library adds import weight and async surface for zero benefit and breaks inertness. |
| stdlib `Protocol` + dict registry | `importlib.metadata` entry-points / pluggy / stevedore | If venues were third-party/out-of-tree and discovered at install time. They are all first-party and eager discovery **breaks lazy-import inertness** — disqualifying. |
| SQLAlchemy Core `SystemStore` KV | Redis / an embedded KV (lmdb, sqlitedict) | If config/state needed sub-ms cross-process reads or a cache tier. The store is low-frequency operator/config state on the existing SQL spine; a second datastore is unjustified operational surface. |
| pydantic `RuntimeConfig` overlay | dynaconf / hydra / python-configuration | If the project wanted convention-driven multi-source config with its own lifecycle. It conflicts with the single-writer snapshot-read contract and the eager/lazy import-safety split; the explicit small merge is safer and auditable. |
| SQLAlchemy 2.0.50 (keep) | SQLAlchemy 2.1.0b2 | Never for a money store mid-refactor — it is a pre-release. Revisit 2.1 only after it goes stable and outside an oracle-gated milestone. |

## What NOT to Use

| Avoid | Why (specific problem) | Use Instead |
|-------|------------------------|-------------|
| `pluggy` / `stevedore` / entry-points plugin loader | Eager module import on discovery → breaks `test_okx_inertness.py` (registering `'okx'` must pull no `ccxt.pro`) | stdlib `Protocol` + dict registry + lazy import inside `build_bundle` |
| `blinker` / `pypubsub` / an actor framework | Multi-consumer/async transport the single-writer engine thread doesn't need; heavy import on a path that must stay light | `queue.PriorityQueue` + `itertools.count` |
| `dynaconf` / `hydra` / `python-configuration` | Own loader lifecycle fights the engine-thread-write/snapshot-read contract and the eager-vs-lazy import-safety split; obscures the runtime allowlist governance | pydantic `RuntimeConfig` overlay + explicit merge |
| Redis / lmdb / sqlitedict for `SystemStore` | Second datastore = new ops surface + a non-SQL money-adjacent store; no latency need | SQLAlchemy Core over the shared `sql_engine` (the `HaltRecordStore` template) |
| SQLAlchemy 2.1 beta | Pre-release on a money-bearing, oracle-gated milestone | Stay on 2.0.x (2.0.50; 2.0.51 optional patch) |
| Migrating Alembic config into `pyproject.toml [tool.alembic]` | Needless blast radius during the `migrations/` relocation; a known "No 'script_location' key" upgrade footgun | Keep `alembic.ini`; change only the `script_location` line |

## Stack Patterns by Variant

**If the project ever adopts a free-threaded (PEP 703, no-GIL) CPython build:**
- Wrap `next(self._seq)` in a `threading.Lock` in `PriorityEventBus`.
- Because `itertools.count().__next__` atomicity relies on the GIL today; document the
  assumption at the seam now.

**If a fourth+ durable store is added later:**
- Follow the same `build_*_table` registrar + `create_all(checkfirst=True)` test path +
  chained Alembic migration; add the registrar call to `env.py`. The pattern scales without
  new dependencies.

**If multi-provider concurrency (the deferred feed-router, §14) is built later:**
- Still stdlib: the two-registry decoupling already enables a `dict`-keyed provider-router;
  no library needed then either.

## Version Compatibility

| Package | Installed | Compatible / current | Notes |
|---------|-----------|----------------------|-------|
| SQLAlchemy | 2.0.50 | 2.0.51 latest 2.0.x | Keep; patch bump optional, not required. Avoid 2.1 beta. |
| Alembic | 1.18.5 | 1.18.5 latest | Already latest; uses modern `%(here)s`/`path_separator=os` ini model — relocation is a one-line edit. |
| pydantic / pydantic-settings | 2.13.4 / 2.14 | current 2.x | Keep; extend models only. |
| Python | 3.13 | 3.13 | All stdlib constructs (`PriorityQueue`, `itertools.count`, `Protocol`, `cached_property`) present and stable. |

## Integration Points (for the roadmap)

- **`SqlBackend` (→ `SqlEngine`, `storage/backend.py` → `storage/engine.py`)** — the 3 new
  stores each *compose* one `SqlEngine` by reference (has-a), exactly like `HaltRecordStore`.
  Rename touches `storage/__init__.py`, `env.py`, the storage factory, and `halt_record_store.py`.
- **`EventHandler` (`events_handler/full_event_handler.py`)** — the bus feeds `process_events()`;
  the `_on_handler_error` seam becomes the injected `ErrorPolicy` (removing the live monkeypatch),
  and live routes compose in via `LiveRouteRegistrar` (no subclass, no runtime `routes` mutation —
  the existing explicit-empty live route slots stay inert on the backtest handler).
- **Alembic chain** — new head progression `d10_halt_records → system_store → venue_config →
  strategy_registry`; `env.py` gains three `build_*_table` calls sharing `NAMING_CONVENTION`.

## Sources

- Installed versions verified locally: `poetry run python -c "import sqlalchemy, alembic, pydantic"` → SQLAlchemy 2.0.50, Alembic 1.18.5, pydantic 2.13.4 (HIGH)
- Migration chain head verified locally via `grep down_revision` over `itrader/storage/migrations/versions/` → head = `d10_halt_records` (HIGH)
- `alembic.ini` + `itrader/storage/migrations/env.py` + `itrader/storage/backend.py` + `itrader/storage/halt_record_store.py` (repo) — relocation/rename mechanics, `%(here)s`/`path_separator` model, `HaltRecordStore` template (HIGH)
- Design spec `docs/superpowers/specs/2026-07-07-v1.8-live-system-refactor-design.md` §4/§6/§7/§8 — bus tuple ordering, config platform, stores, venue registry (HIGH)
- [SQLAlchemy · PyPI](https://pypi.org/project/SQLAlchemy/) / [SQLAlchemy Releases](https://github.com/sqlalchemy/sqlalchemy/releases) — latest 2.0.x = 2.0.51; 2.1 line still beta (2.1.0b2) (HIGH)
- [Alembic 1.18.5 Configuration docs](https://alembic.sqlalchemy.org/en/latest/api/config.html) / [alembic · PyPI](https://pypi.org/project/alembic/) — 1.18.5 latest; `script_location` / `[tool.alembic]` (1.16+) relocation semantics (HIGH)

---
*Stack research for: v1.8 Live System Refactor — brownfield structural refactor, backtest-oracle + import-inertness gated*
*Researched: 2026-07-09*

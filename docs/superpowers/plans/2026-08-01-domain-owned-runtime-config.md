# Domain-Owned Runtime Config Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the central `ConfigRouter` and the duplicate facade ingress ladder with one config event per domain, each validated, persisted and applied by the handler that owns that config.

**Architecture:** Three new CONTROL-tier events (`OrderConfigEvent`, `PortfolioConfigEvent`, `UniverseConfigEvent`) are routed by `EventType` straight to the owning handler. Each consumer runs validate → persist → apply against its own Pydantic model and its own store, and is a loud no-op on a bad payload. Dispatch is the existing route table; default-deny comes from `EventHandler._dispatch` raising on an unrouted type plus `extra="forbid"` on each model. Additive work lands first (Phases 1–3); every deletion lands last (Phase 4), so nothing is removed before its replacement is proven.

**Tech Stack:** Python 3.13, Poetry, msgspec (events), Pydantic v2 (config models), SQLAlchemy 2.x Core + Alembic (stores), pytest.

**Design spec:** `docs/superpowers/specs/2026-08-01-domain-owned-runtime-config-design.md` — read it before starting. It records why each decision was made and which alternatives were rejected.

## Global Constraints

- **Indentation is PER FILE, never per package.** Measure before editing: `grep -c $'^\t' <file>`. TAB files touched by this plan: `itrader/order_handler/order_handler.py`, `itrader/execution_handler/execution_handler.py`, `itrader/execution_handler/exchanges/simulated.py`, `itrader/strategy_handler/strategies_handler.py`. Every other file this plan touches is 4-space. A mixed-indentation diff breaks a tab file.
- **Money is `Decimal` end-to-end.** No float for money anywhere.
- **Business time, never wall clock.** Stores take a caller-supplied `at`; use `event.time`.
- **`pyproject.toml` sets `filterwarnings = ["error", ...]`, `--strict-markers`, `--strict-config`.** Any unexpected warning fails the suite.
- **Test markers are folder-derived** (`tests/unit/` → `unit`, `tests/integration/` → `integration`). Do not hand-apply them.
- **Do not add `__init__.py` to `tests/unit/` subdirectories** — it creates duplicate top-level packages and breaks full-suite collection.
- **Run tests with `poetry run pytest`, not `make test`.** `make test` exports `ITRADER_DISABLE_LOGS=true` (breaks `caplog` assertions) and aborts on a missing `.env` in worktrees.
- **Two gates run at the end of every phase and must stay green:**
  - `poetry run pytest tests/integration/test_backtest_oracle.py -v` — byte-exact oracle: **134 trades / `46189.87730727451`**.
  - `poetry run pytest tests/integration/test_okx_inertness.py -v` — no live/SQL module may reach the backtest import graph.
- **`mypy --strict` covers `itrader/`.** The live stack has no `ignore_errors` override; new code must be strict-clean. Run `poetry run mypy itrader` before each commit.
- **Alembic chain head is `p112_portfolios_is_deleted`.** New migrations chain onto the current head linearly — never branch.
- **Do not add barrel re-exports for live/SQL modules.** `itrader/storage/universe_store.py` must be imported by path, never re-exported from a package `__init__.py`, or the inertness gate reddens.

---

## File Structure

**Created:**

| File | Responsibility |
|---|---|
| `itrader/storage/universe_store.py` | Durable cardinality-1 `universe_config` table + `UniverseStore` (`save_config`/`load_config`) |
| `migrations/versions/universe_config.py` | Alembic: create `universe_config` |
| `migrations/versions/drop_venue_config.py` | Alembic: drop `venue_store` |
| `itrader/storage/secret_guard.py` | Home for `_assert_no_secret_keys`, relocated out of the deleted `venue_store.py` |
| `tests/unit/events/test_config_events.py` | The three event structs + their factories |
| `tests/unit/storage/test_universe_store.py` | `UniverseStore` round-trip + registrar idempotence |
| `tests/unit/order/test_order_config_consumer.py` | `OrderHandler.on_config_update` |
| `tests/unit/portfolio/test_portfolio_config_consumer.py` | `PortfolioHandler.on_config_update` |
| `tests/unit/universe/test_universe_config_consumer.py` | `UniverseHandler.on_config_update` + live-apply of `remove_policy` |

**Modified:**

| File | Change |
|---|---|
| `itrader/core/enums/event.py` | +3 `EventType` members; −`CONFIG_UPDATE` (Phase 4) |
| `itrader/events_handler/bus.py` | +3 members in `_CONTROL_EVENT_TYPES`; −`CONFIG_UPDATE` (Phase 4) |
| `itrader/events_handler/events/order.py` / `portfolio.py` / `universe.py` | +1 event struct each |
| `itrader/events_handler/events/__init__.py` | +3 exports; −`ConfigUpdateEvent` (Phase 4) |
| `itrader/events_handler/events/control.py` | −`ConfigUpdateEvent` (Phase 4) |
| `itrader/order_handler/order_handler.py` (**TABS**) | +`on_config_update` |
| `itrader/portfolio_handler/portfolio_handler.py` | +`on_config_update`; −6 dead config methods (Phase 4) |
| `itrader/universe/universe_handler.py` | ctor takes `config: UniverseConfig` + `poll_timeframe: str` + `store`; +`on_config_update`; −`UniverseHandlerConfig` |
| `itrader/trading_system/route_registrar.py` | +3 routes, +2 handler refs; −`config_router` (Phase 4) |
| `itrader/trading_system/session_initializer.py` | +`universe_store`, ctor param rename; −`config_router` (Phase 4) |
| `itrader/trading_system/live/build.py` | build `UniverseStore`; −`ConfigRouter`/`VenueStore` (Phase 4) |
| `itrader/trading_system/live/system.py` | `_EXTERNALLY_ADMISSIBLE`; −ingress ladder (Phase 4) |
| `itrader/trading_system/live/bootstrap.py` | universe layering arm; −system + venue arms (Phase 4) |
| `itrader/config/itrader_config.py` | −`system` field (Phase 4) |
| `itrader/config/system.py` / `__init__.py` | −`SystemSettings` (Phase 4) |
| `itrader/storage/venue_account_store.py` | import guard from new home (Phase 4) |
| `tests/integration/test_okx_inertness.py` | +`universe_store` in the forbidden list and the registrar assertion |
| 8 test modules constructing `UniverseHandlerConfig` | two-param ctor change (Task 6) |

**Deleted (Phase 4 only):** `itrader/trading_system/config_router.py`, `itrader/storage/venue_store.py`, `tests/unit/trading_system/test_config_router.py`.

---

# PHASE 1 — Events, EventType, bus tiering

Purely additive. Nothing is routed; nothing changes behaviour.

### Task 1: EventType members and CONTROL tiering

**Files:**
- Modify: `itrader/core/enums/event.py:38` (insert after `CONFIG_UPDATE`)
- Modify: `itrader/events_handler/bus.py:48-53`
- Test: `tests/unit/events/test_config_events.py`

**Interfaces:**
- Produces: `EventType.ORDER_CONFIG`, `EventType.PORTFOLIO_CONFIG`, `EventType.UNIVERSE_CONFIG` — all CONTROL-tier on `PriorityEventBus`.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/events/test_config_events.py`:

```python
"""Per-domain runtime-config events: enum members, CONTROL tiering, struct shape."""

from datetime import UTC, datetime

from itrader.core.enums import EventType
from itrader.events_handler.bus import _CONTROL_EVENT_TYPES

_NOW = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)


def test_config_event_types_exist():
    assert EventType.ORDER_CONFIG.value == "ORDER_CONFIG"
    assert EventType.PORTFOLIO_CONFIG.value == "PORTFOLIO_CONFIG"
    assert EventType.UNIVERSE_CONFIG.value == "UNIVERSE_CONFIG"


def test_config_event_types_are_control_tier():
    # A config edit must not queue behind a bar backlog.
    for member in (
        EventType.ORDER_CONFIG,
        EventType.PORTFOLIO_CONFIG,
        EventType.UNIVERSE_CONFIG,
    ):
        assert member in _CONTROL_EVENT_TYPES
```

- [ ] **Step 2: Run test to verify it fails**

Run: `poetry run pytest tests/unit/events/test_config_events.py -v`
Expected: FAIL with `AttributeError: ORDER_CONFIG`

- [ ] **Step 3: Add the enum members**

In `itrader/core/enums/event.py`, immediately after the `CONFIG_UPDATE` line (`:38`), add (4-space file):

```python
    ORDER_CONFIG = "ORDER_CONFIG"            # order-domain runtime config edit (CONTROL)
    PORTFOLIO_CONFIG = "PORTFOLIO_CONFIG"    # per-portfolio runtime config edit (CONTROL)
    UNIVERSE_CONFIG = "UNIVERSE_CONFIG"      # universe runtime config edit (CONTROL)
```

- [ ] **Step 4: Add the CONTROL tiering**

In `itrader/events_handler/bus.py`, extend the `_CONTROL_EVENT_TYPES` frozenset (`:48-53`):

```python
_CONTROL_EVENT_TYPES: frozenset[EventType] = frozenset({
    EventType.STREAM_STATE,
    EventType.CONNECTOR_FATAL,
    EventType.CONFIG_UPDATE,
    EventType.STRATEGY_COMMAND,
    EventType.ORDER_CONFIG,
    EventType.PORTFOLIO_CONFIG,
    EventType.UNIVERSE_CONFIG,
})
```

- [ ] **Step 5: Run test to verify it passes**

Run: `poetry run pytest tests/unit/events/test_config_events.py -v`
Expected: PASS (2 tests)

- [ ] **Step 6: Commit**

```bash
git add itrader/core/enums/event.py itrader/events_handler/bus.py tests/unit/events/test_config_events.py
git commit -m "feat: add per-domain config EventType members on the CONTROL tier"
```

---

### Task 2: The three event structs

**Files:**
- Modify: `itrader/events_handler/events/order.py` (append)
- Modify: `itrader/events_handler/events/portfolio.py` (append)
- Modify: `itrader/events_handler/events/universe.py` (append)
- Modify: `itrader/events_handler/events/__init__.py`
- Test: `tests/unit/events/test_config_events.py` (extend)

**Interfaces:**
- Produces:
  - `OrderConfigEvent(time: datetime, updates: dict[str, Any])`, factory `OrderConfigEvent.edit(updates, *, time)`
  - `PortfolioConfigEvent(time: datetime, portfolio_id: PortfolioId, updates: dict[str, Any])`, factory `PortfolioConfigEvent.edit(portfolio_id, updates, *, time)`
  - `UniverseConfigEvent(time: datetime, updates: dict[str, Any])`, factory `UniverseConfigEvent.edit(updates, *, time)`
  - All are frozen `msgspec.Struct`s exported from `itrader.events_handler.events`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/events/test_config_events.py`:

```python
import uuid

import msgspec
import pytest

from itrader.core.ids import PortfolioId
from itrader.events_handler.events import (
    OrderConfigEvent,
    PortfolioConfigEvent,
    UniverseConfigEvent,
)


def test_order_config_event_factory_pins_type_and_payload():
    event = OrderConfigEvent.edit({"market_execution": "next_bar"}, time=_NOW)
    assert event.type is EventType.ORDER_CONFIG
    assert event.updates == {"market_execution": "next_bar"}
    assert event.time == _NOW
    assert event.created_at == _NOW


def test_portfolio_config_event_carries_typed_id():
    pid = PortfolioId(uuid.uuid4())
    event = PortfolioConfigEvent.edit(pid, {"limits": {"max_positions": 7}}, time=_NOW)
    assert event.type is EventType.PORTFOLIO_CONFIG
    assert event.portfolio_id == pid
    assert event.updates == {"limits": {"max_positions": 7}}


def test_universe_config_event_factory():
    event = UniverseConfigEvent.edit({"remove_policy": "force-close"}, time=_NOW)
    assert event.type is EventType.UNIVERSE_CONFIG
    assert event.updates == {"remove_policy": "force-close"}


def test_config_events_are_frozen():
    event = UniverseConfigEvent.edit({"remove_policy": "force-close"}, time=_NOW)
    with pytest.raises(AttributeError):
        event.updates = {}


def test_config_events_carry_uuidv7_identity():
    event = OrderConfigEvent.edit({"market_execution": "immediate"}, time=_NOW)
    assert isinstance(event.event_id, uuid.UUID)
    assert event.event_id.version == 7
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `poetry run pytest tests/unit/events/test_config_events.py -v`
Expected: FAIL with `ImportError: cannot import name 'OrderConfigEvent'`

- [ ] **Step 3: Add `OrderConfigEvent`**

Append to `itrader/events_handler/events/order.py` (4-space file):

```python
class OrderConfigEvent(Event, frozen=True, kw_only=True, gc=False):
    """An order-domain runtime config edit, addressed to ``OrderHandler``.

    ``updates`` is a PARTIAL delta with MERGE, not replace, semantics: a field omitted
    from the delta keeps its prior value rather than reverting to the model default.
    It is validated against ``OrderConfig`` by the consumer, so an unknown key is
    rejected by ``extra="forbid"`` — there is no separate allowlist.

    Construct via ``edit``, never by hand (the house factory convention).
    """

    type: ClassVar[EventType] = EventType.ORDER_CONFIG
    updates: dict[str, Any]

    @classmethod
    def edit(cls, updates: dict[str, Any], *, time: datetime) -> "OrderConfigEvent":
        """Build a complete order-config edit."""
        return cls(time=time, updates=updates)
```

Add `from datetime import datetime` to the imports if absent; `Any` and `ClassVar` are already imported.

- [ ] **Step 4: Add `PortfolioConfigEvent`**

Append to `itrader/events_handler/events/portfolio.py` (4-space file):

```python
class PortfolioConfigEvent(Event, frozen=True, kw_only=True, gc=False):
    """A per-portfolio runtime config edit, addressed to one ``Portfolio`` by id.

    ``portfolio_id`` is the TYPED identity — there is no scope string to parse and no
    UUID re-parse downstream. An id naming no live portfolio is a loud no-op at the
    consumer, never a raise into the queue.

    ``updates`` is a PARTIAL delta with MERGE, not replace, semantics, shaped like
    ``PortfolioConfig`` (e.g. ``{"limits": {"max_positions": 7}}``). Keys in
    ``IMMUTABLE_PORTFOLIO_CONFIG_KEYS`` are refused by ``Portfolio.update_config``.
    """

    type: ClassVar[EventType] = EventType.PORTFOLIO_CONFIG
    portfolio_id: PortfolioId
    updates: dict[str, Any]

    @classmethod
    def edit(
        cls, portfolio_id: PortfolioId, updates: dict[str, Any], *, time: datetime
    ) -> "PortfolioConfigEvent":
        """Build a complete per-portfolio config edit."""
        return cls(time=time, portfolio_id=portfolio_id, updates=updates)
```

Add `from datetime import datetime` and `from itrader.core.ids import PortfolioId` to the imports.

- [ ] **Step 5: Add `UniverseConfigEvent`**

Append to `itrader/events_handler/events/universe.py` (4-space file):

```python
class UniverseConfigEvent(Event, frozen=True, kw_only=True, gc=False):
    """A universe runtime config edit, addressed to ``UniverseHandler``.

    ``updates`` is a PARTIAL delta with MERGE, not replace, semantics, validated
    against ``UniverseConfig``. The editable surface is ``remove_policy`` ONLY:
    ``poll_cadence_s`` is construction-time because ``WorkerSupervisor`` captures it as
    a float at build (see the design spec, "The ``universe`` scope"), and a
    ``poll_cadence_s`` key is therefore refused as a live no-op.
    """

    type: ClassVar[EventType] = EventType.UNIVERSE_CONFIG
    updates: dict[str, Any]

    @classmethod
    def edit(cls, updates: dict[str, Any], *, time: datetime) -> "UniverseConfigEvent":
        """Build a complete universe-config edit."""
        return cls(time=time, updates=updates)
```

Add `from datetime import datetime` and `from typing import Any` to the imports.

- [ ] **Step 6: Export the three from the barrel**

In `itrader/events_handler/events/__init__.py`, add to the matching import groups and to `__all__`:

```python
from .order import OrderAckEvent, OrderConfigEvent, OrderEvent      # extend existing line
from .portfolio import PortfolioConfigEvent, PortfolioUpdateEvent   # extend existing line
from .universe import UniverseConfigEvent, UniversePollEvent, UniverseUpdateEvent
```

```python
    'OrderConfigEvent',
    'PortfolioConfigEvent',
    'UniverseConfigEvent',
```

Match the existing import lines exactly — read them before editing rather than assuming the current member list.

- [ ] **Step 7: Run tests to verify they pass**

Run: `poetry run pytest tests/unit/events/test_config_events.py -v`
Expected: PASS (7 tests)

- [ ] **Step 8: Run the type checker and both gates**

```bash
poetry run mypy itrader
poetry run pytest tests/integration/test_backtest_oracle.py tests/integration/test_okx_inertness.py -v
```
Expected: mypy clean; oracle 134 / `46189.87730727451`; inertness green.

- [ ] **Step 9: Commit**

```bash
git add itrader/events_handler/events/ tests/unit/events/test_config_events.py
git commit -m "feat: add OrderConfigEvent, PortfolioConfigEvent, UniverseConfigEvent"
```

---

# PHASE 2 — UniverseStore, migration, `UniverseHandler` holds `UniverseConfig`

### Task 3: `UniverseStore`

**Files:**
- Create: `itrader/storage/universe_store.py`
- Modify: `tests/integration/test_okx_inertness.py:80` (forbidden list) and `:393-418` (registrar assertion)
- Test: `tests/unit/storage/test_universe_store.py`

**Interfaces:**
- Produces: `build_universe_store_table(metadata: MetaData) -> Table` (table name `universe_config`); `UniverseStore(sql_engine: SqlEngine)` with `save_config(config: dict[str, Any], at: datetime) -> None`, `load_config() -> Optional[dict[str, Any]]`, `dispose() -> None`.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/storage/test_universe_store.py`. This mirrors `tests/unit/storage/test_system_store.py` exactly — including the `try/finally: store.dispose()` wrapper, which is **required**: `filterwarnings = ["error"]` turns an unclosed-SQLite `ResourceWarning` into a test failure.

```python
"""UniverseStore: cardinality-1 config round-trip + idempotent registrar.

4-space indentation (matches ``itrader/storage`` + the storage test convention). NO
``__init__.py`` in this dir. Every store is wrapped in ``try/finally: store.dispose()``
because ``filterwarnings=["error"]`` turns an unclosed-sqlite ResourceWarning into a
failure.
"""

from datetime import UTC, datetime

from sqlalchemy import MetaData

from itrader.config.sql import SqlSettings
from itrader.storage import SqlEngine
from itrader.storage.universe_store import UniverseStore, build_universe_store_table
from tests.support.schema import provision_schema

_AT1 = datetime(2026, 8, 1, 12, 0, 0, tzinfo=UTC)
_AT2 = datetime(2026, 8, 2, 9, 30, 0, tzinfo=UTC)


def _make_store() -> UniverseStore:
    """An in-memory durable double — the shared ``SqlEngine`` on ``:memory:`` SQLite."""
    store = UniverseStore(SqlEngine(SqlSettings.default()))
    provision_schema(store.backend)
    return store


def test_load_config_returns_none_when_never_saved() -> None:
    store = _make_store()
    try:
        assert store.load_config() is None
    finally:
        store.dispose()


def test_save_then_load_round_trips() -> None:
    store = _make_store()
    try:
        store.save_config({"poll_cadence_s": 60.0, "remove_policy": "force-close"}, _AT1)
        assert store.load_config() == {
            "poll_cadence_s": 60.0,
            "remove_policy": "force-close",
        }
    finally:
        store.dispose()


def test_second_save_overwrites_the_single_row() -> None:
    store = _make_store()
    try:
        store.save_config({"remove_policy": "force-close"}, _AT1)
        store.save_config({"remove_policy": "orphan-and-track"}, _AT2)
        assert store.load_config() == {"remove_policy": "orphan-and-track"}
    finally:
        store.dispose()


def test_build_universe_store_table_is_idempotent() -> None:
    metadata = MetaData()
    first = build_universe_store_table(metadata)
    second = build_universe_store_table(metadata)
    assert first is second
    assert set(metadata.tables) == {"universe_config"}
```

`provision_schema` takes the `SqlEngine` backend, so `UniverseStore` must expose it as `self.backend` — see Step 3.

- [ ] **Step 2: Run test to verify it fails**

Run: `poetry run pytest tests/unit/storage/test_universe_store.py -v`
Expected: FAIL with `ModuleNotFoundError: itrader.storage.universe_store`

- [ ] **Step 3: Write `UniverseStore`**

Create `itrader/storage/universe_store.py` (4 spaces — matches the `itrader/storage` spine):

```python
"""Durable universe config store — the cardinality-1 ``universe_config`` table.

A disciplined clone of the ``order_config`` singleton template
(``order_handler/storage/sql_storage.py``): ONE row under a constant String PK, the
portable JSON ``config_json`` blob, and a caller-supplied UTC-isoformat ``updated_at``
(clock-free store). The upsert is a portable delete-then-insert in one
``engine.begin()``. All SQL is parameterized SQLAlchemy Core against the constant
``Table`` — never f-string SQL.

Schema-pure: no runtime ``create_all``. ``build_universe_store_table`` is the SINGLE
source of truth feeding BOTH the test-path ``create_all`` and the Alembic migration.

Live-only. This module composes SQLAlchemy and must never reach the backtest import
graph — it is deliberately NOT re-exported from ``itrader/storage/__init__.py``
(asserted by ``tests/integration/test_okx_inertness.py``).
"""

from datetime import datetime
from typing import Any, Optional

from sqlalchemy import Column, MetaData, String, Table, delete, insert, select
from sqlalchemy.engine import Engine

from itrader.logger import get_itrader_logger
from itrader.storage import SqlEngine, UtcIsoText, json_variant

# The constant single-row PK. Universe config is a GLOBAL singleton: two saves leave ONE
# row. A dedicated table (not a column elsewhere) leaves room to key per-run later.
_UNIVERSE_CONFIG_ROW_ID: str = "universe_config"


def build_universe_store_table(metadata: MetaData) -> Table:
    """Register (idempotently) the single ``universe_config`` table and return it."""
    if "universe_config" in metadata.tables:
        return metadata.tables["universe_config"]
    return Table(
        "universe_config",
        metadata,
        Column("id", String, primary_key=True),
        Column("config_json", json_variant(), nullable=False),
        Column("updated_at", UtcIsoText, nullable=False),
    )


class UniverseStore:
    """Durable home for the universe scope's runtime config singleton."""

    def __init__(self, sql_engine: SqlEngine) -> None:
        # ``backend`` is the shared spine, kept because tests provision the schema through
        # it (``provision_schema(store.backend)``) and ``dispose`` delegates to it — never
        # ``engine.dispose()`` directly. Same shape as SystemStore.
        self.backend = sql_engine
        self.engine: Engine = sql_engine.engine
        self.universe_config: Table = build_universe_store_table(sql_engine.metadata)
        self.logger = get_itrader_logger().bind(component="UniverseStore")

    def dispose(self) -> None:
        """Dispose the shared backend engine (delegate, never ``engine.dispose()``)."""
        self.backend.dispose()

    def save_config(self, config: dict[str, Any], at: datetime) -> None:
        """Persist the GLOBAL universe config singleton (delete-then-insert one row)."""
        with self.engine.begin() as conn:
            conn.execute(
                delete(self.universe_config).where(
                    self.universe_config.c.id == _UNIVERSE_CONFIG_ROW_ID
                )
            )
            conn.execute(
                insert(self.universe_config),
                [
                    {
                        "id": _UNIVERSE_CONFIG_ROW_ID,
                        "config_json": config,
                        "updated_at": at,
                    }
                ],
            )

    def load_config(self) -> Optional[dict[str, Any]]:
        """Return the persisted universe config dict, or ``None`` when none saved."""
        with self.engine.connect() as conn:
            row = conn.execute(
                select(self.universe_config.c.config_json).where(
                    self.universe_config.c.id == _UNIVERSE_CONFIG_ROW_ID
                )
            ).first()
        if row is None:
            return None
        config: dict[str, Any] = dict(row[0])
        return config
```

- [ ] **Step 4: Run test to verify it passes**

Run: `poetry run pytest tests/unit/storage/test_universe_store.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Extend the inertness gate**

In `tests/integration/test_okx_inertness.py`, add `"itrader.storage.universe_store"` to the forbidden-module list beside `"itrader.storage.venue_store"` (around `:80`), and extend the registrar assertion (around `:393-418`) to build and assert the new table:

```python
    from itrader.storage.universe_store import build_universe_store_table
    universe_table = build_universe_store_table(metadata)
    assert not isinstance(universe_table, Engine)
```

and add `"universe_config"` to the expected `set(metadata.tables)`.

- [ ] **Step 6: Run the inertness gate**

Run: `poetry run pytest tests/integration/test_okx_inertness.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add itrader/storage/universe_store.py tests/unit/storage/test_universe_store.py tests/integration/test_okx_inertness.py
git commit -m "feat: add UniverseStore, the universe scope's durable config singleton"
```

---

### Task 4: Alembic migration for `universe_config`

**Files:**
- Create: `migrations/versions/universe_config.py`
- Modify: `tests/integration/storage/test_migrations.py` (expected-table list at `:56`)

**Interfaces:**
- Consumes: `build_universe_store_table` (Task 3) — the migration reproduces its column set by hand.
- Produces: revision `universe_config`, chained onto the current head `p112_portfolios_is_deleted`.

- [ ] **Step 1: Confirm the chain head**

```bash
grep -rn "^revision: str\|^down_revision" migrations/versions/*.py | grep -c .
poetry run alembic heads
```
Expected: exactly one head, `p112_portfolios_is_deleted`. If it differs, chain onto whatever `alembic heads` reports and note the change.

- [ ] **Step 2: Write the migration**

Create `migrations/versions/universe_config.py`, mirroring `migrations/versions/venue_config.py`:

```python
"""universe config

Add the durable universe config store — the ``universe_config`` table. A cardinality-1
singleton (constant String PK ``id``) carrying the portable JSON ``config_json`` and the
UTC-isoformat business ``updated_at``. Derived from the ``build_universe_store_table``
registrar (``itrader/storage/universe_store.py``) — the single source of truth the
test-path ``create_all`` and this deploy-path migration both reproduce.

Revision ID: universe_config
Revises: p112_portfolios_is_deleted
Create Date: 2026-08-01 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# Hand-authored custom-type import: ``updated_at`` uses the spine's ``UtcIsoText``
# TypeDecorator; autogenerate omits this import, so it is added by hand so
# ``alembic upgrade head`` resolves the name instead of raising NameError.
import itrader.storage.types

revision: str = "universe_config"
down_revision: Union[str, Sequence[str], None] = "p112_portfolios_is_deleted"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema — create the durable ``universe_config`` table."""
    op.create_table(
        "universe_config",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column(
            "config_json",
            sa.JSON().with_variant(postgresql.JSONB(), "postgresql"),
            nullable=False,
        ),
        sa.Column("updated_at", itrader.storage.types.UtcIsoText(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_universe_config")),
    )


def downgrade() -> None:
    """Downgrade schema — drop the ``universe_config`` table."""
    op.drop_table("universe_config")
```

- [ ] **Step 3: Add the table to the migration test's expected set**

In `tests/integration/storage/test_migrations.py`, add `"universe_config"` to the expected-table list (around `:56`) and register `build_universe_store_table(metadata)` alongside the other registrars (around `:278`).

- [ ] **Step 4: Run the migration test**

Run: `poetry run pytest tests/integration/storage/test_migrations.py -v`
Expected: PASS. Skips cleanly if Docker is unavailable (testcontainers) — if it skips, say so rather than claiming it passed.

- [ ] **Step 5: Commit**

```bash
git add migrations/versions/universe_config.py tests/integration/storage/test_migrations.py
git commit -m "feat: add the universe_config table migration"
```

---

### Task 5: `UniverseHandler` holds `UniverseConfig`

This is the largest edit surface in the plan: eight test modules construct `UniverseHandlerConfig` directly. The production change is small; the test migration is mechanical and wide.

**Files:**
- Modify: `itrader/universe/universe_handler.py:56` (`__all__`), `:64-79` (delete `UniverseHandlerConfig`), `:191-218` (ctor), `:565` (read site)
- Modify: `itrader/trading_system/session_initializer.py:39,51,62,151` (param type)
- Modify: `itrader/trading_system/live/system.py:42,442-445` (construction site)
- Modify: `tests/unit/universe/test_universe_poll.py`, `test_universe_warm_verify_gate.py`, `test_retry_policy_cr01.py`, `test_universe_warmup_consumers.py`, `tests/integration/test_reconfigure_positions.py`, `test_strategy_external_add_lifecycle.py`, `test_strategy_add_warmup.py`, `test_strategy_remove_flat.py`, `tests/integration/conftest.py:436,487`

**Interfaces:**
- Consumes: `itrader.config.universe.UniverseConfig` (existing: `poll_cadence_s: float`, `remove_policy: str`).
- Produces: `UniverseHandler(*, bus, universe, feed, config: UniverseConfig, poll_timeframe: str)`. `UniverseHandlerConfig` no longer exists. `self._config` holds the model; `self._timeframe` stays a plain `str`.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/universe/test_universe_config_consumer.py` with the ctor test only (the consumer test arrives in Task 8):

```python
"""UniverseHandler owns a UniverseConfig model, not a dataclass snapshot."""

import queue

from itrader.config.universe import UniverseConfig
from itrader.universe.universe_handler import UniverseHandler


def _handler(**kwargs):
    """Build a bare handler; every cross-domain seam stays unwired (inert)."""
    return UniverseHandler(
        bus=queue.Queue(),
        universe=kwargs.pop("universe", _StubUniverse()),
        feed=kwargs.pop("feed", _StubFeed()),
        config=kwargs.pop("config", UniverseConfig()),
        poll_timeframe=kwargs.pop("poll_timeframe", "1d"),
    )


def test_handler_holds_the_pydantic_model():
    config = UniverseConfig(remove_policy="force-close")
    handler = _handler(config=config)
    assert handler._config is config
    assert handler._config.remove_policy == "force-close"


def test_poll_timeframe_is_a_separate_construction_snapshot():
    handler = _handler(poll_timeframe="4h")
    assert handler._timeframe == "4h"
```

Copy `_StubUniverse` / `_StubFeed` from the existing stubs in `tests/unit/universe/test_universe_poll.py` rather than inventing new ones.

- [ ] **Step 2: Run test to verify it fails**

Run: `poetry run pytest tests/unit/universe/test_universe_config_consumer.py -v`
Expected: FAIL with `TypeError: __init__() got an unexpected keyword argument 'poll_timeframe'`

- [ ] **Step 3: Change the constructor**

In `itrader/universe/universe_handler.py` (4-space file):

Delete the `UniverseHandlerConfig` dataclass (`:64-79`) and drop it from `__all__` (`:56`), leaving `__all__ = ["UniverseHandler"]`.

Replace the ctor signature and the two unpack lines (`:191-218`):

```python
    def __init__(
        self,
        *,
        bus: "Queue[Any]",
        universe: Universe,
        feed: _SupportsWarmup,
        config: UniverseConfig,
        poll_timeframe: str,
    ) -> None:
        """Hold the bus + universe read-model + feed + the owned universe config.

        Parameters
        ----------
        config : UniverseConfig
            The OWNED, runtime-editable universe config. Held by reference and
            atomic-swapped by ``on_config_update`` — the handler is its sole reader.
        poll_timeframe : str
            The bar timeframe passed to ``feed.warmup`` on add, and the interval the
            re-warm cadence gate measures against. A CONSTRUCTION SNAPSHOT, not config:
            it must match the timeframe the venue stream actually subscribes to
            (``config.stream.okx_stream_timeframe``), so an independently editable copy
            could warm 1d bars while the stream delivers 1h.
        """
        self._bus = bus
        self._universe = universe
        self._feed = feed
        self._config = config
        self._timeframe = poll_timeframe
```

Add `from itrader.config.universe import UniverseConfig` to the imports. Keep every other line of the ctor body unchanged.

Replace the one `self._remove_policy` read at `:565`:

```python
        if self._config.remove_policy == _FORCE_CLOSE:
```

- [ ] **Step 4: Update the two production construction sites**

In `itrader/trading_system/live/system.py`, replace `:442-445`:

```python
            universe_handler_config = self._config.universe
            universe_poll_timeframe = self._config.stream.okx_stream_timeframe
```

and pass both through `SessionInitializer(...)` — rename its `universe_config` param's type to `UniverseConfig` and add `poll_timeframe: str`. Update the import at `:42` (`UniverseHandlerConfig` → `UniverseConfig` from `itrader.config.universe`).

In `itrader/trading_system/session_initializer.py`, update the import (`:39`), the ctor param type (`:62`), the docstring (`:51`), and the `UniverseHandler(...)` call (`:151`) to pass `config=self._universe_config, poll_timeframe=self._poll_timeframe`.

- [ ] **Step 5: Migrate the eight test modules**

In each of the nine call sites, replace the single `config=UniverseHandlerConfig(...)` argument with two arguments. The mechanical mapping:

| Before | After |
|---|---|
| `config=UniverseHandlerConfig(poll_timeframe="1d")` | `config=UniverseConfig(), poll_timeframe="1d"` |
| `config=UniverseHandlerConfig(poll_timeframe="1d", remove_policy="force-close")` | `config=UniverseConfig(remove_policy="force-close"), poll_timeframe="1d"` |

Sites: `tests/unit/universe/test_universe_poll.py:182,218`, `test_universe_warm_verify_gate.py:151`, `test_retry_policy_cr01.py:88`, `test_universe_warmup_consumers.py:152`, `tests/integration/test_reconfigure_positions.py:112`, `test_strategy_external_add_lifecycle.py:219`, `test_strategy_add_warmup.py:145`, `test_strategy_remove_flat.py:115`, `tests/integration/conftest.py:487`. Update the corresponding imports (`:39`, `:30`, `:30`, `:35`, `:31`, `:63`, `:46`, `:39`, `:436`).

- [ ] **Step 6: Run the full affected suites**

```bash
poetry run pytest tests/unit/universe tests/integration/test_reconfigure_positions.py tests/integration/test_strategy_add_warmup.py tests/integration/test_strategy_remove_flat.py tests/integration/test_strategy_external_add_lifecycle.py -v
poetry run mypy itrader
```
Expected: all PASS, mypy clean. `grep -rn "UniverseHandlerConfig" itrader/ tests/` must return nothing.

- [ ] **Step 7: Run both gates**

```bash
poetry run pytest tests/integration/test_backtest_oracle.py tests/integration/test_okx_inertness.py -v
```
Expected: oracle 134 / `46189.87730727451`; inertness green.

- [ ] **Step 8: Commit**

```bash
git add itrader/universe/universe_handler.py itrader/trading_system/session_initializer.py itrader/trading_system/live/system.py tests/
git commit -m "refactor: UniverseHandler owns a UniverseConfig model, not a dataclass snapshot"
```

---

# PHASE 3 — Consumers, routes, bootstrap layering

### Task 6: `OrderHandler.on_config_update`

**Files:**
- Modify: `itrader/order_handler/order_handler.py` (**TAB-indented** — verify with `grep -c $'^\t' itrader/order_handler/order_handler.py`)
- Test: `tests/unit/order/test_order_config_consumer.py`

**Interfaces:**
- Consumes: `OrderConfigEvent` (Task 2); `self.storage.save_config(config: dict, at: datetime)`; `self.order_manager.update_config(updates: dict)`.
- Produces: `OrderHandler.on_config_update(event: OrderConfigEvent) -> None` — the `ORDER_CONFIG` route consumer.

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/order/test_order_config_consumer.py`:

```python
"""OrderHandler.on_config_update — validate -> persist -> apply, loud no-op on refusal."""

from datetime import UTC, datetime

from itrader.core.enums import MarketExecution
from itrader.events_handler.events import OrderConfigEvent

_NOW = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)


def test_valid_update_persists_then_applies(order_handler):
    order_handler.on_config_update(
        OrderConfigEvent.edit({"market_execution": "next_bar"}, time=_NOW))
    assert order_handler.order_manager.market_execution is MarketExecution.NEXT_BAR
    assert order_handler.market_execution is MarketExecution.NEXT_BAR
    assert order_handler.storage.load_config() == {"market_execution": "next_bar"}


def test_unknown_key_is_a_loud_noop_and_persists_nothing(order_handler, caplog):
    before = order_handler.order_manager.market_execution
    order_handler.on_config_update(
        OrderConfigEvent.edit({"totally_unknown_key": 1}, time=_NOW))
    assert order_handler.order_manager.market_execution is before
    assert order_handler.storage.load_config() is None
    assert "Order config refused" in caplog.text


def test_bad_value_is_a_loud_noop_and_persists_nothing(order_handler, caplog):
    before = order_handler.order_manager.market_execution
    order_handler.on_config_update(
        OrderConfigEvent.edit({"market_execution": "not-a-mode"}, time=_NOW))
    assert order_handler.order_manager.market_execution is before
    assert order_handler.storage.load_config() is None
    assert "Order config refused" in caplog.text


def test_consumer_never_raises_into_the_queue(order_handler):
    # A raise here would reach the engine error boundary instead of being a no-op.
    order_handler.on_config_update(OrderConfigEvent.edit({"bad": object()}, time=_NOW))
```

Use this fixture, lifted from `tests/unit/order/test_order_update_config.py:56-60`:

```python
from queue import Queue

import pytest

from itrader.order_handler.order_handler import OrderHandler
from tests.support.venue_wiring import backtest_portfolio_handler


@pytest.fixture
def order_handler():
    q = Queue()
    ptf_handler = backtest_portfolio_handler(q)
    ptf_handler.add_portfolio("test_ptf", "default", 10000)
    return OrderHandler(q, ptf_handler)
```

`OrderHandler` defaults to `InMemoryOrderStorage`, which implements `save_config`/`load_config` — no SQL needed.

- [ ] **Step 2: Run tests to verify they fail**

Run: `poetry run pytest tests/unit/order/test_order_config_consumer.py -v`
Expected: FAIL with `AttributeError: 'OrderHandler' object has no attribute 'on_config_update'`

- [ ] **Step 3: Write the consumer**

Add to `itrader/order_handler/order_handler.py` beside `update_config` (`:104`). **TABS** — copy the indentation of the surrounding methods byte-for-byte:

```python
	def on_config_update(self, event: OrderConfigEvent) -> None:
		"""ORDER_CONFIG route consumer: validate -> persist -> apply.

		Persist-first: the durable row holds operator intent and a restart heals a
		failed apply. A bad payload is a LOUD NO-OP — warn and return, never a raise
		into the queue (the same contract ``on_strategy_command`` has). Unknown keys
		are rejected by ``OrderConfig``'s ``extra="forbid"``, so there is no separate
		allowlist to keep in sync.
		"""
		try:
			merged = OrderConfig.model_validate(
				recursive_merge(self.order_manager.order_config.model_dump(),
				                event.updates))
		except (pydantic.ValidationError, TypeError) as exc:
			self.logger.warning('Order config refused: %s', exc)
			return
		self.storage.save_config(merged.model_dump(mode='json'), event.time)
		self.order_manager.update_config(event.updates)
		self.market_execution = self.order_manager.market_execution
```

Add the imports: `pydantic`, `from itrader.config.order import OrderConfig`, `from itrader.outils.dict_merge import recursive_merge`, `from itrader.events_handler.events import OrderConfigEvent`.

`TypeError` is caught alongside `ValidationError` because a non-dict or unhashable payload from an external caller reaches `recursive_merge` before Pydantic sees it.

- [ ] **Step 4: Run tests to verify they pass**

Run: `poetry run pytest tests/unit/order/test_order_config_consumer.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Verify indentation was not normalised**

```bash
git diff --stat itrader/order_handler/order_handler.py
git diff itrader/order_handler/order_handler.py | grep -n "^+    " | head
```
Expected: the second command returns NOTHING. Any space-indented added line in this tab file is a defect — fix before committing.

- [ ] **Step 6: Commit**

```bash
git add itrader/order_handler/order_handler.py tests/unit/order/test_order_config_consumer.py
git commit -m "feat: OrderHandler consumes OrderConfigEvent (validate -> persist -> apply)"
```

---

### Task 7: `PortfolioHandler.on_config_update`

**Files:**
- Modify: `itrader/portfolio_handler/portfolio_handler.py` (4-space file)
- Test: `tests/unit/portfolio/test_portfolio_config_consumer.py`

**Interfaces:**
- Consumes: `PortfolioConfigEvent` (Task 2); `self.get_portfolio(portfolio_id) -> Portfolio` (raises `PortfolioNotFoundError`); `portfolio.state_storage.save_config(config, at)`; `portfolio.update_config(updates)` (raises `ConfigurationError` / `ImmutableConfigKeyError`).
- Produces: `PortfolioHandler.on_config_update(event: PortfolioConfigEvent) -> None`.

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/portfolio/test_portfolio_config_consumer.py`:

```python
"""PortfolioHandler.on_config_update — resolve id, persist to the portfolio's own store."""

import uuid
from datetime import UTC, datetime

from itrader.core.ids import PortfolioId
from itrader.events_handler.events import PortfolioConfigEvent

_NOW = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)


def test_valid_update_persists_to_the_portfolios_own_store(handler_with_portfolio):
    handler, portfolio = handler_with_portfolio
    handler.on_config_update(PortfolioConfigEvent.edit(
        portfolio.portfolio_id, {"limits": {"max_positions": 7}}, time=_NOW))
    assert portfolio.config.limits.max_positions == 7
    assert portfolio.state_storage.load_config()["limits"]["max_positions"] == 7


def test_unknown_portfolio_id_is_a_loud_noop(handler_with_portfolio, caplog):
    handler, _ = handler_with_portfolio
    handler.on_config_update(PortfolioConfigEvent.edit(
        PortfolioId(uuid.uuid4()), {"limits": {"max_positions": 7}}, time=_NOW))
    assert "no such portfolio" in caplog.text.lower()


def test_immutable_key_is_refused_and_persists_nothing(handler_with_portfolio, caplog):
    handler, portfolio = handler_with_portfolio
    before = portfolio.config.trading_rules.enable_margin
    handler.on_config_update(PortfolioConfigEvent.edit(
        portfolio.portfolio_id,
        {"trading_rules": {"enable_margin": not before}}, time=_NOW))
    assert portfolio.config.trading_rules.enable_margin is before
    assert portfolio.state_storage.load_config() is None
    assert "Portfolio config refused" in caplog.text


def test_bad_value_is_a_loud_noop_and_persists_nothing(handler_with_portfolio, caplog):
    handler, portfolio = handler_with_portfolio
    before = portfolio.config.limits.max_positions
    handler.on_config_update(PortfolioConfigEvent.edit(
        portfolio.portfolio_id, {"limits": {"max_positions": "not-an-int"}}, time=_NOW))
    assert portfolio.config.limits.max_positions == before
    assert portfolio.state_storage.load_config() is None
    assert "Portfolio config refused" in caplog.text
```

Use this fixture, built from `tests/unit/portfolio/test_update_config.py:52-53`:

```python
from queue import Queue

import pytest

from tests.support.venue_wiring import backtest_portfolio_handler


@pytest.fixture
def handler_with_portfolio():
    handler = backtest_portfolio_handler(global_queue=Queue(), environment="test")
    handler.add_portfolio("test_ptf", "default", 10000)
    portfolio = next(iter(handler.all_portfolios().values()))
    return handler, portfolio
```

The `test` environment selects in-memory portfolio state storage, which implements `save_config`/`load_config`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `poetry run pytest tests/unit/portfolio/test_portfolio_config_consumer.py -v`
Expected: FAIL with `AttributeError: ... has no attribute 'on_config_update'`

- [ ] **Step 3: Write the consumer**

Add to `itrader/portfolio_handler/portfolio_handler.py` (4 spaces), beside the other event consumers:

```python
    def on_config_update(self, event: PortfolioConfigEvent) -> None:
        """PORTFOLIO_CONFIG route consumer: resolve the id, persist, then apply.

        Persist-first, to the resolved Portfolio's OWN bound ``state_storage`` (already
        portfolio_id-scoped) — never a central store. An unknown id, an immutable key
        (``IMMUTABLE_PORTFOLIO_CONFIG_KEYS``, enforced by ``Portfolio.update_config``) or
        a bad value is a LOUD NO-OP: warn and return, never a raise into the queue.

        The candidate is validated by ``Portfolio.update_config`` itself, so the merge is
        run twice deliberately — once here to keep an invalid payload out of the store,
        once there as the domain object's own guard.
        """
        try:
            portfolio = self.get_portfolio(event.portfolio_id)
        except PortfolioNotFoundError:
            self.logger.warning(
                "Portfolio config refused: no such portfolio %s", event.portfolio_id)
            return
        try:
            validated = PortfolioConfig.model_validate(
                recursive_merge(portfolio.config.model_dump(), event.updates))
        except (pydantic.ValidationError, TypeError) as exc:
            self.logger.warning("Portfolio config refused: %s", exc)
            return
        if _names_immutable_key(event.updates):
            self.logger.warning(
                "Portfolio config refused: immutable key in %s", sorted(event.updates))
            return
        portfolio.state_storage.save_config(validated.model_dump(mode="json"), event.time)
        portfolio.update_config(event.updates)
```

Add a module-level helper beside the class:

```python
def _names_immutable_key(updates: Dict[str, Any]) -> bool:
    """True when ``updates`` names a runtime-immutable portfolio key at any depth.

    Checked BEFORE the persist so a refused key leaves nothing in the store. The set is
    shared with ``Portfolio.update_config``'s own guard, so the two cannot disagree.
    """
    for key, value in updates.items():
        if key in IMMUTABLE_PORTFOLIO_CONFIG_KEYS:
            return True
        if isinstance(value, dict) and _names_immutable_key(value):
            return True
    return False
```

Add the imports: `pydantic`, `PortfolioConfigEvent`, `IMMUTABLE_PORTFOLIO_CONFIG_KEYS` (from `itrader.config.portfolio`). `PortfolioConfig`, `PortfolioNotFoundError` and `recursive_merge` are already imported in this module — verify before adding.

- [ ] **Step 4: Run tests to verify they pass**

Run: `poetry run pytest tests/unit/portfolio/test_portfolio_config_consumer.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add itrader/portfolio_handler/portfolio_handler.py tests/unit/portfolio/test_portfolio_config_consumer.py
git commit -m "feat: PortfolioHandler consumes PortfolioConfigEvent"
```

---

### Task 8: `UniverseHandler.on_config_update`

**Files:**
- Modify: `itrader/universe/universe_handler.py` (ctor gains `store`, plus the consumer)
- Modify: `itrader/trading_system/session_initializer.py`, `itrader/trading_system/live/build.py`, `itrader/trading_system/live/system.py` (thread the store)
- Test: `tests/unit/universe/test_universe_config_consumer.py` (extend from Task 5)

**Interfaces:**
- Consumes: `UniverseConfigEvent` (Task 2); `UniverseStore` (Task 3).
- Produces: `UniverseHandler(*, bus, universe, feed, config, poll_timeframe, store: Optional[UniverseStore] = None)` and `UniverseHandler.on_config_update(event: UniverseConfigEvent) -> None`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/universe/test_universe_config_consumer.py`:

```python
from datetime import UTC, datetime

from itrader.events_handler.events import UniverseConfigEvent

_NOW = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)


class _StoreSpy:
    def __init__(self):
        self.saved = None

    def save_config(self, config, at):
        self.saved = (config, at)

    def load_config(self):
        return self.saved[0] if self.saved else None


def test_valid_update_persists_then_swaps():
    store = _StoreSpy()
    handler = _handler(config=UniverseConfig(), store=store)
    handler.on_config_update(
        UniverseConfigEvent.edit({"remove_policy": "force-close"}, time=_NOW))
    assert handler._config.remove_policy == "force-close"
    assert store.saved[0]["remove_policy"] == "force-close"
    assert store.saved[1] == _NOW


def test_unknown_key_is_a_loud_noop_and_persists_nothing(caplog):
    store = _StoreSpy()
    handler = _handler(store=store)
    handler.on_config_update(UniverseConfigEvent.edit({"nope": 1}, time=_NOW))
    assert store.saved is None
    assert "Universe config refused" in caplog.text


def test_bad_value_is_a_loud_noop_and_persists_nothing(caplog):
    store = _StoreSpy()
    handler = _handler(store=store)
    handler.on_config_update(
        UniverseConfigEvent.edit({"poll_cadence_s": -1.0}, time=_NOW))
    assert store.saved is None
    assert "Universe config refused" in caplog.text


def test_no_store_applies_live_and_warns_it_will_not_survive_restart(caplog):
    handler = _handler(store=None)
    handler.on_config_update(
        UniverseConfigEvent.edit({"remove_policy": "force-close"}, time=_NOW))
    assert handler._config.remove_policy == "force-close"
    assert "will not survive a restart" in caplog.text


def test_poll_cadence_edit_is_refused_not_silently_ignored(caplog):
    store = _StoreSpy()
    handler = _handler(store=store)
    handler.on_config_update(
        UniverseConfigEvent.edit({"poll_cadence_s": 30.0}, time=_NOW))
    assert store.saved is None
    assert "construction-time" in caplog.text


def test_rehydrate_applies_a_full_stored_dump_including_poll_cadence():
    # The store holds a FULL model dump. Replaying it through on_config_update would trip
    # the poll_cadence_s guard and drop remove_policy on every restart.
    handler = _handler(config=UniverseConfig(remove_policy="orphan-and-track"))
    handler.rehydrate_config({"poll_cadence_s": 30.0, "remove_policy": "force-close"})
    assert handler._config.remove_policy == "force-close"
    assert handler._config.poll_cadence_s == 30.0


def test_rehydrate_ignores_an_invalid_stored_row(caplog):
    handler = _handler(config=UniverseConfig(remove_policy="orphan-and-track"))
    handler.rehydrate_config({"poll_cadence_s": -1.0})
    assert handler._config.remove_policy == "orphan-and-track"
    assert "stored override invalid" in caplog.text
```

Extend the `_handler` helper from Task 5 to pass `store=kwargs.pop("store", None)`.

- [ ] **Step 1b: Write the live-apply regression test**

The tests above assert on `handler._config`, which would ALSO pass against the bug being fixed (the old code updated the config object while the running handler kept its snapshot). One test must drive the real read site.

Open `itrader/universe/universe_handler.py:565` to see the remove branch that reads `remove_policy`, and `tests/integration/test_strategy_remove_flat.py:115` for the minimum setup that reaches it (a handler with a portfolio read-model and one open position). Add to `tests/unit/universe/test_universe_config_consumer.py`:

```python
def test_remove_branch_uses_the_updated_policy():
    """The regression the old design missed: after an edit, the REMOVE PATH must take the
    force-close arm — not merely the config attribute."""
    handler = _handler(config=UniverseConfig(remove_policy="orphan-and-track"))
    # ... wire the portfolio read-model + one open position, per test_strategy_remove_flat
    handler.on_config_update(
        UniverseConfigEvent.edit({"remove_policy": "force-close"}, time=_NOW))
    # ... drive the remove branch and assert the force-close signal was emitted
```

Fill in the two elided sections from the existing test's setup. Do not merge this task until this test drives `:565` and fails when the swap at the end of `on_config_update` is commented out — verify that by commenting it out, running, and restoring.

- [ ] **Step 2: Run tests to verify they fail**

Run: `poetry run pytest tests/unit/universe/test_universe_config_consumer.py -v`
Expected: FAIL with `TypeError: __init__() got an unexpected keyword argument 'store'`

- [ ] **Step 3: Add the store param and the consumer**

In `itrader/universe/universe_handler.py` (4 spaces), add to the ctor signature after `poll_timeframe: str`:

```python
        store: Optional["UniverseStore"] = None,
```

and in the body:

```python
        # The universe scope's durable config home. ``None`` in the no-SQL live build:
        # the edit still applies live, with a warning that it will not survive a restart
        # (the same posture the in-memory order storage already has).
        self._store = store
```

Import under `TYPE_CHECKING` to keep the SQL module off this handler's import graph:

```python
if TYPE_CHECKING:
    from itrader.storage.universe_store import UniverseStore
```

Add the consumer:

```python
    def on_config_update(self, event: UniverseConfigEvent) -> None:
        """UNIVERSE_CONFIG route consumer: validate -> persist -> atomic-swap.

        The handler is the SOLE reader of its ``UniverseConfig``, so the apply step is a
        plain attribute rebind — the same shape ``OrderManager.update_config`` and
        ``Portfolio.update_config`` use. A bad payload is a LOUD NO-OP.

        ``poll_cadence_s`` validates but does NOT take effect: ``WorkerSupervisor``
        captured it as a float at construction. Editing it is refused rather than
        silently ignored — see the pending todo
        ``universe-poll-timer-into-universe-handler``.
        """
        if "poll_cadence_s" in event.updates:
            self.logger.warning(
                "Universe config refused: poll_cadence_s is construction-time until the "
                "poll timer moves into UniverseHandler")
            return
        try:
            merged = UniverseConfig.model_validate(
                recursive_merge(self._config.model_dump(), event.updates))
        except (pydantic.ValidationError, TypeError) as exc:
            self.logger.warning("Universe config refused: %s", exc)
            return
        if self._store is None:
            self.logger.warning(
                "Universe config applied WITHOUT persistence — no durable store wired; "
                "the change will not survive a restart")
        else:
            self._store.save_config(merged.model_dump(mode="json"), event.time)
        self._config = merged

    def rehydrate_config(self, stored: dict[str, Any]) -> None:
        """Restart-layer a PERSISTED universe config. NOT a runtime edit.

        Separate from ``on_config_update`` on purpose. The store holds a full
        ``UniverseConfig`` dump including ``poll_cadence_s``, so replaying it through the
        runtime path would trip that key's refusal guard and reject the whole row — the
        stored ``remove_policy`` would silently fail to layer on every restart. A stored
        row is already-accepted operator intent, so it validates and swaps without the
        editability guard and without re-persisting what was just read.

        KNOWN LIMITATION: a stored ``poll_cadence_s`` lands on ``self._config`` but does
        NOT reach ``WorkerSupervisor``, which captured its float at build — before boot
        runs. Resolved by the pending todo ``universe-poll-timer-into-universe-handler``.
        """
        try:
            self._config = UniverseConfig.model_validate(
                recursive_merge(self._config.model_dump(), stored))
        except (pydantic.ValidationError, TypeError) as exc:
            self.logger.warning(
                "Persisted universe config ignored — stored override invalid: %s", exc)
```

Add imports: `pydantic`, `recursive_merge`, `UniverseConfigEvent`. This module has no bound logger today — add `self.logger = get_itrader_logger().bind(component="UniverseHandler")` to the ctor if absent (check first; the module may already log via a module-level logger).

- [ ] **Step 4: Thread the store through the wiring**

In `itrader/trading_system/live/build.py`, beside the other store construction (`:206-207`):

```python
    universe_store = (
        UniverseStore(sql_engine) if sql_engine is not None else None)
```

with `from itrader.storage.universe_store import UniverseStore` at the top (path import — do NOT add a barrel re-export). Pass it to the facade, then through `SessionInitializer` to the `UniverseHandler(...)` call.

- [ ] **Step 5: Run tests to verify they pass**

```bash
poetry run pytest tests/unit/universe -v
poetry run mypy itrader
```
Expected: PASS, mypy clean.

- [ ] **Step 6: Commit**

```bash
git add itrader/universe/universe_handler.py itrader/trading_system/ tests/unit/universe/
git commit -m "feat: UniverseHandler consumes UniverseConfigEvent over its own store"
```

---

### Task 9: Routes and external ingress

**Files:**
- Modify: `itrader/trading_system/route_registrar.py:47-67` (ctor), `:69-122` (install)
- Modify: `itrader/trading_system/session_initializer.py:160-167` (registrar construction)
- Modify: `itrader/trading_system/live/system.py` (`_EXTERNALLY_ADMISSIBLE`)
- Test: `tests/integration/test_config_ingress.py` (rewrite)

**Interfaces:**
- Consumes: the three consumers (Tasks 6–8).
- Produces: `routes[EventType.ORDER_CONFIG] = [order_handler.on_config_update]` and the two siblings; the three types admitted by `add_event`.

- [ ] **Step 1: Write the failing test**

Rewrite `tests/integration/test_config_ingress.py` around the new events. Keep the file's package-less directory convention. Minimum coverage:

```python
def test_routes_point_at_the_owning_handlers(live_system):
    routes = live_system.engine.event_handler.routes
    assert routes[EventType.ORDER_CONFIG] == [
        live_system.engine.order_handler.on_config_update]
    assert routes[EventType.PORTFOLIO_CONFIG] == [
        live_system.engine.portfolio_handler.on_config_update]
    assert len(routes[EventType.UNIVERSE_CONFIG]) == 1


def test_add_event_admits_the_three_config_events(live_system):
    for event in (
        OrderConfigEvent.edit({"market_execution": "next_bar"}, time=_NOW),
        PortfolioConfigEvent.edit(_PID, {"limits": {"max_positions": 7}}, time=_NOW),
        UniverseConfigEvent.edit({"remove_policy": "force-close"}, time=_NOW),
    ):
        assert live_system.add_event(event) is True


def test_add_event_still_rejects_a_raw_order(live_system):
    assert live_system.add_event(_raw_order_event()) is False


def test_order_config_event_drains_to_applied_and_persisted(live_system):
    live_system.add_event(
        OrderConfigEvent.edit({"market_execution": "next_bar"}, time=_NOW))
    _drain_once(live_system)
    assert live_system.engine.order_handler.market_execution is MarketExecution.NEXT_BAR
    assert live_system.engine.order_handler.storage.load_config() == {
        "market_execution": "next_bar"}
```

Reuse the existing wiring helpers in the current `test_config_ingress.py` for building the system and draining one event.

- [ ] **Step 2: Run test to verify it fails**

Run: `poetry run pytest tests/integration/test_config_ingress.py -v`
Expected: FAIL — `KeyError: EventType.ORDER_CONFIG`

- [ ] **Step 3: Install the routes**

In `itrader/trading_system/route_registrar.py` (4 spaces), add `order_handler` and `portfolio_handler` to the ctor (required keyword params — the registrar holds only `StrategiesHandler` and `UniverseHandler` today), and in `install`:

```python
        # Per-domain runtime config. Each type has exactly ONE owner, so the route table
        # IS the dispatch — no scope parsing and no central router. An unrouted type
        # still raises NotImplementedError in EventHandler._dispatch.
        routes[EventType.ORDER_CONFIG] = [self._order_handler.on_config_update]
        routes[EventType.PORTFOLIO_CONFIG] = [self._portfolio_handler.on_config_update]
        routes[EventType.UNIVERSE_CONFIG] = [self._universe_handler.on_config_update]
```

In `session_initializer.py`, pass `order_handler=engine.order_handler, portfolio_handler=engine.portfolio_handler` at the `LiveRouteRegistrar(...)` construction.

- [ ] **Step 4: Admit the three at ingress**

In `itrader/trading_system/live/system.py`, extend `_EXTERNALLY_ADMISSIBLE` with `EventType.ORDER_CONFIG`, `EventType.PORTFOLIO_CONFIG`, `EventType.UNIVERSE_CONFIG`. Leave `_validate_config_ingress` in place for now — Phase 4 removes it with `CONFIG_UPDATE`.

- [ ] **Step 5: Run tests to verify they pass**

Run: `poetry run pytest tests/integration/test_config_ingress.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add itrader/trading_system/ tests/integration/test_config_ingress.py
git commit -m "feat: route the three config events to their owning handlers"
```

---

### Task 10: Restart layering for universe

**Files:**
- Modify: `itrader/trading_system/live/bootstrap.py::layer_persisted_overrides` (`:183` — note the real name is `layer_persisted_overrides`, NOT `_layer_persisted_config`)
- Modify: `itrader/trading_system/live/build.py` (the `_restart_sequence` partial that calls it)
- Test: `tests/integration/test_config_restart_layering.py` (extend)

**Interfaces:**
- Consumes: `UniverseStore.load_config()` (Task 3); `UniverseHandler.rehydrate_config(stored)` (Task 8).
- Produces: a universe arm in `layer_persisted_overrides`, guarded by the same `_DEGRADE_CLEAN` policy as its siblings, with two new keyword params `universe_store` and `universe_handler`.

> **Ordering constraint:** `layer_persisted_overrides` runs inside the boot sequence, but `UniverseHandler` is built by `SessionInitializer` during `start()`. Confirm which runs first before wiring — if the handler does not yet exist at layering time, the universe arm must move to just after `initializer.initialize()` in `live/system.py` rather than into `layer_persisted_overrides`. Check with `grep -n "layer_persisted_overrides\|initializer.initialize" itrader/trading_system/live/*.py` and follow the actual order; do not assume.

- [ ] **Step 1: Write the failing test**

Add to `tests/integration/test_config_restart_layering.py`, following the existing arms' style (reuse its `wiring` fixture):

```python
def test_persisted_universe_config_layers_on_boot(wiring):
    # A FULL model dump, exactly as UniverseHandler.on_config_update persists it.
    wiring.universe_store.save_config(
        {"poll_cadence_s": 60.0, "remove_policy": "force-close"}, _NOW)
    handler = _boot_and_get_universe_handler(wiring)
    assert handler._config.remove_policy == "force-close"


def test_missing_universe_table_degrades_clean(wiring_without_universe_table):
    # A not-yet-provisioned schema means "no persisted overrides yet", not a fault.
    handler = _boot_and_get_universe_handler(wiring_without_universe_table)
    assert handler._config.remove_policy == "orphan-and-track"
```

The first test is the regression guard for the bug this task's design avoids: routing a stored row through `on_config_update` would trip the `poll_cadence_s` refusal and drop `remove_policy` on every restart.

- [ ] **Step 2: Run test to verify it fails**

Run: `poetry run pytest tests/integration/test_config_restart_layering.py -v`
Expected: FAIL — the persisted value is not applied.

- [ ] **Step 3: Add the universe arm**

In `itrader/trading_system/live/bootstrap.py::layer_persisted_overrides`, add beside the order and portfolio arms (4 spaces):

```python
    try:
        universe_cfg = universe_store.load_config() if universe_store else None
        if universe_cfg:
            universe_handler.rehydrate_config(universe_cfg)
    except _DEGRADE_CLEAN as exc:
        logger.warning(
            "Skipping persisted UNIVERSE-config restart layering — schema unavailable or "
            "a stored override is invalid (%s); boot degrades clean", exc)
```

Add `universe_store: Any` and `universe_handler: Any` as keyword params to `layer_persisted_overrides` and pass them from the `_restart_sequence` call site in `build.py`.

This calls `rehydrate_config`, **not** `on_config_update`. Routing a stored row through the runtime path would trip the `poll_cadence_s` refusal guard and reject the whole row, so `remove_policy` would silently fail to layer on every restart. `rehydrate_config` also does not re-persist what it just read, so boot performs no write.

- [ ] **Step 4: Run tests to verify they pass**

Run: `poetry run pytest tests/integration/test_config_restart_layering.py -v`
Expected: PASS

- [ ] **Step 5: Run both gates and the full suite**

```bash
poetry run pytest tests -q
poetry run mypy itrader
```
Expected: all green. This is the last point before deletions — the tree must be fully green here.

- [ ] **Step 6: Commit**

```bash
git add itrader/trading_system/live/bootstrap.py itrader/trading_system/live/build.py tests/integration/test_config_restart_layering.py
git commit -m "feat: layer persisted universe config on restart"
```

---

# PHASE 4 — Deletions

Every replacement is proven before anything is removed. Each task must leave the suite green.

### Task 11: Delete `ConfigRouter`, `ConfigUpdateEvent` and the facade ingress ladder

**Files:**
- Delete: `itrader/trading_system/config_router.py`, `tests/unit/trading_system/test_config_router.py`
- Modify: `itrader/events_handler/events/control.py:74-105`, `itrader/events_handler/events/__init__.py`, `itrader/core/enums/event.py:38`, `itrader/events_handler/bus.py`
- Modify: `itrader/trading_system/live/system.py:30-32,244-245,300,315,455-461,732-735,744-830`
- Modify: `itrader/trading_system/route_registrar.py:54,64-67,112-122,148-162`
- Modify: `itrader/trading_system/session_initializer.py:68,81-84,164`
- Modify: `itrader/trading_system/live/build.py:67,362-377,425`

- [ ] **Step 1: Delete the router and its tests**

```bash
git rm itrader/trading_system/config_router.py tests/unit/trading_system/test_config_router.py
```

- [ ] **Step 2: Remove every `config_router` reference**

Drop the ctor param, the attribute, and the `_on_config_update` consumer from `route_registrar.py`; drop the param from `session_initializer.py`; drop the construction and the facade argument from `build.py`; drop the attribute and the `EventType.CONFIG_UPDATE` branch from `live/system.py`.

- [ ] **Step 3: Delete the facade ingress ladder**

Remove `_validate_config_ingress` (`:744-812`) and `_dry_validate_config_ingress` (`:814-830`) from `live/system.py`, the `EventType.CONFIG_UPDATE` guard in `add_event` (`:732-735`), `CONFIG_UPDATE` from `_EXTERNALLY_ADMISSIBLE`, and the now-unused imports at `:30-32` (`OrderConfig`, `SystemSettings`, `UniverseConfig`) plus `pydantic` and `uuid` if nothing else in the module uses them.

- [ ] **Step 4: Delete the event and its enum member**

Remove `ConfigUpdateEvent` from `events/control.py`, its export from `events/__init__.py`, `EventType.CONFIG_UPDATE` from `core/enums/event.py`, and its entry in `_CONTROL_EVENT_TYPES`.

- [ ] **Step 5: Verify nothing references the removed names**

```bash
grep -rn "ConfigRouter\|ConfigUpdateEvent\|CONFIG_UPDATE\|_validate_config_ingress" itrader/ tests/ scripts/
```
Expected: NO output. Docstring mentions count — update or delete them.

- [ ] **Step 6: Run the suite, mypy and both gates**

```bash
poetry run pytest tests -q && poetry run mypy itrader
```
Expected: all green.

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "refactor: delete ConfigRouter, ConfigUpdateEvent and the facade ingress ladder"
```

---

### Task 12: Delete `VenueStore`, relocate the secret guard, drop the table

**Files:**
- Create: `itrader/storage/secret_guard.py`
- Delete: `itrader/storage/venue_store.py` (and its unit tests, if any)
- Create: `migrations/versions/drop_venue_config.py`
- Modify: `itrader/storage/venue_account_store.py:55`, `itrader/trading_system/live/build.py:64,207,369,388,506,544`, `itrader/trading_system/live/bootstrap.py:187,244-264`, `tests/integration/test_okx_inertness.py`, `tests/integration/storage/test_migrations.py`

**Interfaces:**
- Produces: `itrader.storage.secret_guard._assert_no_secret_keys(config, *, path="config_json")` and `_SECRET_KEY_DENYLIST`, moved verbatim.

- [ ] **Step 1: Relocate the secret guard FIRST**

Create `itrader/storage/secret_guard.py` and move `_SECRET_KEY_DENYLIST` and `_assert_no_secret_keys` from `venue_store.py:36-78` verbatim, with the module docstring explaining it guards any JSON config column against credential keys. Update the import in `venue_account_store.py:55`.

- [ ] **Step 2: Verify the guard still works before deleting anything**

Run: `poetry run pytest tests/unit/storage -v`
Expected: PASS. The `venue_account_store` secret-rejection tests must still pass — they are the proof the relocation is faithful.

- [ ] **Step 3: Delete `VenueStore` and its wiring**

```bash
git rm itrader/storage/venue_store.py
```
Remove the construction in `build.py:207`, every `venue_store=` argument, and the venue arm of `layer_persisted_overrides` (`bootstrap.py:244-264`) along with its `venue_store` parameter.

- [ ] **Step 4: Write the drop migration**

Create `migrations/versions/drop_venue_config.py`, chained onto `universe_config`:

```python
"""drop venue config

Drop the ``venue_store`` table. Venue fee/slippage was only ever runtime-mutable for the
PAPER exchange (``ExecutionHandler.update_config`` targets ``(COMPUTE_VENUE,
DEFAULT_ACCOUNT_ID)``), a real venue's fees come from fills, and the ``enabled`` column
was written but never read (``list_enabled`` had no callers). The runtime venue-disable
knob lives on ``VenueAccountManager.set_enabled`` over ``venue_accounts``.

Revision ID: drop_venue_config
Revises: universe_config
Create Date: 2026-08-01 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

import itrader.storage.types

revision: str = "drop_venue_config"
down_revision: Union[str, Sequence[str], None] = "universe_config"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema — drop the ``venue_store`` table."""
    op.drop_table("venue_store")


def downgrade() -> None:
    """Downgrade schema — recreate ``venue_store`` (empty; rows are not recoverable)."""
    op.create_table(
        "venue_store",
        sa.Column("venue_name", sa.String(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column(
            "config_json",
            sa.JSON().with_variant(postgresql.JSONB(), "postgresql"),
            nullable=False,
        ),
        sa.Column("updated_at", itrader.storage.types.UtcIsoText(), nullable=False),
        sa.PrimaryKeyConstraint("venue_name", name=op.f("pk_venue_store")),
    )
```

- [ ] **Step 5: Update the two test inventories**

Remove `"itrader.storage.venue_store"` / `"venue_store"` from the forbidden list and registrar assertion in `tests/integration/test_okx_inertness.py`, and from the expected-table list in `tests/integration/storage/test_migrations.py`.

- [ ] **Step 6: Run the suite and mypy**

```bash
grep -rn "venue_store\|VenueStore" itrader/ tests/ | grep -v venue_account_store
poetry run pytest tests -q && poetry run mypy itrader
```
Expected: the grep returns only migration files; suite and mypy green.

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "refactor: drop VenueStore and the venue config scope"
```

---

### Task 13: Delete the dead handler config APIs

**Files:**
- Modify: `itrader/portfolio_handler/portfolio_handler.py:1308-1369` (**4 spaces**)
- Modify: `itrader/strategy_handler/strategies_handler.py:612-655` (**TABS**)
- Modify: `itrader/execution_handler/execution_handler.py:116-156` (**TABS**)
- Modify: `itrader/execution_handler/exchanges/simulated.py:820-836` (**TABS**)
- Modify: `itrader/portfolio_handler/portfolio.py:300-304` (docstring correction)
- Delete: the corresponding tests in `tests/unit/portfolio/test_update_config.py:52-134` and `tests/unit/strategy/test_strategies_handler_update_config.py`

- [ ] **Step 1: Delete `PortfolioHandler`'s dead config API**

Remove `update_config`, `get_config`, `validate_config`, `rollback_config`, `update_portfolio_config`, `get_portfolio_config`. **Keep** `self.config_data` and `self.max_portfolios` — they are read at `:324` (the portfolio-count limit) and `:1285`. Keep `_deep_merge` only if something still calls it; otherwise remove it too.

- [ ] **Step 2: Delete `StrategiesHandler.update_config`**

Remove the method (`:612-655`) and `tests/unit/strategy/test_strategies_handler_update_config.py`. It bypassed the trial-construct, direction re-gate, warmability check and persist that `StrategyLifecycleManager._on_reconfigure` performs — the `STRATEGY_COMMAND` path remains the only entrance.

- [ ] **Step 3: Delete the execution-side config methods**

Remove `ExecutionHandler.update_config` and `validate_config` (`:116-156`) and `SimulatedExchange.validate_config` (`:820-836`).

**Keep, do NOT delete:**
- `SimulatedExchange.update_config` — `configure()` delegates to it for `AbstractExchange` Protocol conformance (`:769-783`).
- `BacktestBarFeed.update_config` (`price_handler/feed/bar_feed.py:344`) — an interface-conformance stub that always raises. It is on the backtest path and out of scope.
- `Portfolio.update_config`, `OrderManager.update_config` — the apply primitives the new consumers call.

- [ ] **Step 4: Correct the stale docstring**

In `itrader/portfolio_handler/portfolio.py:300-304`, `update_config`'s docstring says its immutable-key refusal "duplicates a refusal `ConfigRouter` already makes". Replace with a statement of what is true now: this guard and `PortfolioHandler.on_config_update`'s pre-persist check both read `IMMUTABLE_PORTFOLIO_CONFIG_KEYS`, and this one is the domain object's own backstop for any caller reaching it directly.

- [ ] **Step 5: Verify indentation in the three TAB files**

```bash
git diff itrader/strategy_handler/strategies_handler.py itrader/execution_handler/ | grep -n "^+    "
```
Expected: NO output (deletions only, but verify nothing was reflowed).

- [ ] **Step 6: Run the suite and mypy**

```bash
poetry run pytest tests -q && poetry run mypy itrader
```
Expected: green. Check `tests/unit/execution/test_simulated_exchange_update_config.py` — it may cover `validate_config`; remove only those cases, keeping the `update_config` coverage.

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "refactor: delete the dead per-handler config APIs"
```

---

### Task 14: Delete the `system` config scope

**Files:**
- Modify: `itrader/config/system.py:40-60` (delete `SystemSettings`; **keep** `Environment` and `LogLevel`)
- Modify: `itrader/config/itrader_config.py` (delete the `system` field and its import)
- Modify: `itrader/config/__init__.py:36-40,103` (drop the re-export)
- Modify: `itrader/trading_system/live/bootstrap.py:207-223` (delete the system arm)
- Modify: `tests/unit/config/test_itrader_config.py` and any test asserting `config.system`

- [ ] **Step 1: Confirm the fields are still reader-less**

```bash
grep -rn "enable_auto_restart\|auto_restart_delay_seconds\|enable_graceful_shutdown\|shutdown_timeout_seconds\|config\.system\b" itrader/ scripts/
```
Expected: only `itrader/config/system.py` and the bootstrap arm about to be deleted. **If anything else appears, STOP** — a reader has been added since the spec was written, and this task needs re-scoping. Report it rather than deleting.

- [ ] **Step 2: Delete `SystemSettings` and the `config.system` field**

Remove the class from `config/system.py`, the field and import from `itrader_config.py`, and the import + `__all__` entry from `config/__init__.py`. `Environment` and `LogLevel` stay — `itrader_config.py` imports `Environment` and both are re-exported from the barrel.

- [ ] **Step 3: Delete the system arm of the restart layering**

Remove `bootstrap.py:207-223` (the `config.system.` / `config.universe.` `read_all()` loop) and the now-unused `SystemSettings` / `UniverseConfig` imports. `system_store` stays a parameter only if another arm still uses it; if not, drop it from the signature and the `build.py` call site. **`SystemStore` itself stays** — `state.last_started_at`, `state.last_error` and the halt record still use it.

- [ ] **Step 4: Run the suite, mypy and both gates**

```bash
poetry run pytest tests -q && poetry run mypy itrader
poetry run pytest tests/integration/test_backtest_oracle.py tests/integration/test_okx_inertness.py -v
```
Expected: all green; oracle 134 / `46189.87730727451`.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "refactor: delete the reader-less system config scope"
```

---

### Task 15: Documentation sync

**Files:**
- Modify: `CLAUDE.md` (the `ConfigRouter` / config-system paragraphs)
- Modify: `.planning/codebase/ARCHITECTURE.md` and `CONVENTIONS.md` if they name `ConfigRouter`

- [ ] **Step 1: Find every stale reference**

```bash
grep -rn "ConfigRouter\|CONFIG_UPDATE\|VenueStore\|SystemSettings" CLAUDE.md .planning/codebase/ docs/
```

- [ ] **Step 2: Update them**

In `CLAUDE.md`: the config-system section still describes `ITraderConfig` carrying a `system` sub-model, and the live section names `CONFIG_UPDATE` in `_EXTERNALLY_ADMISSIBLE` and in the routed-but-empty list. Replace with the three per-domain events and the ownership map. Leave the design spec and the pending todo alone — they are historical records and should keep their original wording.

- [ ] **Step 3: Commit**

```bash
git add -A
git commit -m "docs: sync CLAUDE.md and codebase docs with domain-owned runtime config"
```

---

## Verification checklist

Run after Task 15. Every line must pass before calling the work done.

```bash
poetry run pytest tests -q                                          # full suite
poetry run mypy itrader                                             # strict, zero errors
poetry run pytest tests/integration/test_backtest_oracle.py -v      # 134 / 46189.87730727451
poetry run pytest tests/integration/test_okx_inertness.py -v        # import boundary
poetry run alembic heads                                            # exactly one head
grep -rn "ConfigRouter\|ConfigUpdateEvent\|UniverseHandlerConfig" itrader/ tests/   # empty
```

# Phase 10: Strategies Registry ★ - Pattern Map

**Mapped:** 2026-07-17
**Files analyzed:** 11 (4 new / 7 modified)
**Analogs found:** 11 / 11 (exact: 8, role-match: 3)

> **This phase is wiring + extending existing surface.** Analogs were pre-pinned by CONTEXT/RESEARCH;
> this document's value-add is the **verbatim code excerpts** of those analogs plus **independently
> measured indentation** for every file.

## Indentation — MEASURED INDEPENDENTLY (load-bearing; do not generalize a package)

Measured by `grep -cP '^\t'` vs `grep -cP '^    '` per file, this session.

| File | tab lines | 4-space lines | Verdict |
|---|---|---|---|
| `itrader/strategy_handler/base.py` | 838 | 0 | **TABS** |
| `itrader/strategy_handler/strategies_handler.py` | 603 | 0 | **TABS** |
| `itrader/strategy_handler/pair_base.py` | 192 | 0 | **TABS** |
| `itrader/order_handler/admission/admission_manager.py` | 980 | 0 | **TABS** |
| `itrader/trading_system/compose.py` | 216 | 0 | **TABS** |
| `itrader/storage/strategy_registry_store.py` | 0 | 248 | **4-SPACE** |
| `itrader/storage/halt_record_store.py` | 0 | 93 | **4-SPACE** |
| `itrader/core/sizing.py` | 0 | 220 | **4-SPACE** |
| `itrader/events_handler/events/universe.py` | 0 | 79 | **4-SPACE** |
| `itrader/trading_system/live_trading_system.py` | 0 | 1434 | **4-SPACE** |
| `itrader/trading_system/route_registrar.py` | 0 | 121 | **4-SPACE** |
| `itrader/trading_system/session_initializer.py` | 0 | 126 | **4-SPACE** |
| `itrader/universe/universe_handler.py` | 0 | 559 | **4-SPACE** ⚠️ |
| `itrader/price_handler/feed/cache_registration.py` | 0 | 147 | **4-SPACE** |
| `migrations/versions/*.py` | 0 | — | **4-SPACE** |

### Disagreements with the source documents (both resolved in RESEARCH's favour)

1. **`universe/` indentation — CONTEXT is WRONG.** `10-CONTEXT.md` ("Established Patterns", ~line 359)
   claims "`strategy_handler/` and `universe/` are **tabs**." **Measured: `universe_handler.py` is
   0 tab / 559 space → 4-SPACE.** The `strategy_handler/` half of the claim is correct. RESEARCH's
   correction is confirmed. **Follow RESEARCH, not CONTEXT.**
2. **Migration head — CONTEXT is WRONG.** CONTEXT describes the chain ending at `strategy_registry`.
   **Measured `revision`/`down_revision` across `migrations/versions/`: head is `system_stats`**
   (`strategy_registry → module_config → system_stats`). RESEARCH's correction is confirmed. P10's
   `down_revision` **must be `"system_stats"`**.

**Derived rule for the new files:** codec in `core/` → **4-SPACE**; reconstruction collaborator in
`strategy_handler/` → **TABS**; migration → **4-SPACE**.

## File Classification

| New/Modified File | New? | Role | Data Flow | Closest Analog | Match |
|---|---|---|---|---|---|
| `itrader/trading_system/live_trading_system.py` | mod | composition root | event-driven / boot | *itself* — the P9 `ConfigRouter`/`VenueStore` gate `:1520-1555` | exact |
| `itrader/core/policy_codec.py` | **NEW** | utility (value-object codec) | transform | `itrader/core/sizing.py` | role-match |
| `itrader/strategy_handler/registry/rehydrate.py` | **NEW** | service collaborator | batch / boot | `order_handler/admission/admission_manager.py` | role-match |
| `itrader/strategy_handler/registry/__init__.py` | **NEW** | barrel | — | `order_handler/admission/__init__.py` | exact |
| `itrader/storage/strategy_registry_store.py` | mod | store | CRUD | *itself* + `halt_record_store.py` | exact |
| `migrations/versions/p10_*.py` | **NEW** | migration | schema | `migrations/versions/system_stats.py` | exact |
| `itrader/events_handler/events/universe.py` | mod | event | request-response | *itself* — `StrategyCommandEvent:100` | exact |
| `itrader/strategy_handler/strategies_handler.py` | mod | handler (verb dispatch) | event-driven | *itself* — `on_strategy_command:438` | exact |
| `itrader/strategy_handler/strategies_handler.py` | mod | handler (hot-path guard) | event-driven | *itself* — `calculate_signals:141` | exact |
| `itrader/universe/universe_handler.py` | read | warmup pipeline | event-driven | *itself* — `spawn_warmup:508` | exact |
| tests (12 new files) | **NEW** | test | — | `tests/unit/storage/test_strategy_registry_store.py` | exact |

---

## Pattern Assignments

### 1. `live_trading_system.py` — the rehydrate call site (THE most important excerpt)

**Analog:** itself, `live_trading_system.py:1520-1555`. **Indentation: 4-SPACE.**
**RESEARCH Item 2 conclusion:** rehydrate goes **inside this same gate, immediately after
`_layer_persisted_overrides(...)` ends at `:1555`.**

**The gate shape to copy — verbatim** (`:1519-1555`):

```python
    order_handler = engine.order_handler
    if system_store is not None:
        from itrader.core.clock import WallClock
        from itrader.storage.venue_store import VenueStore          # LAZY inside the gate — GATE-01
        from itrader.trading_system.config_router import ConfigRouter

        venue_store: Optional[Any] = VenueStore(system_db_backend)

        def _venue_kind(venue_name: str) -> bool:
            """(venue_name) -> True when the venue's execution arm is a SimulatedExchange (D-14)."""
            from itrader.execution_handler.exchanges.simulated import SimulatedExchange
            return isinstance(
                execution_handler.exchanges.get(venue_name), SimulatedExchange)

        facade._config_router = ConfigRouter(
            config=_system_config,
            system_store=system_store,
            venue_store=venue_store,
            order_handler=order_handler,
            portfolio_handler=portfolio_handler,
            execution_handler=execution_handler,
            venue_kind=_venue_kind,
            bus=global_queue,
            clock=WallClock(),
        )

        # RESTART LAYERING (D-10/D-22): apply persisted overrides on boot from each OWNING
        # store. Base params already resolved at construction (frozen); persisted overrides
        # touch only the mutable sub-models.
        _layer_persisted_overrides(
            _system_config,
            system_store=system_store,
            venue_store=venue_store,
            order_handler=order_handler,
            portfolio_handler=portfolio_handler,
            execution_handler=execution_handler,
        )
        # ★ P10 REHYDRATE GOES HERE (D-01) — portfolios are layered above (ordering
        #   constraint satisfied); session init reads strategies below.
```

**Four properties to copy exactly:**
1. **Gated on `system_store is not None`** — degrades to a clean no-op on the in-memory fallback.
2. **Lazy imports INSIDE the gate** — `StrategyRegistryStore` + the rehydrate collaborator must be
   imported here, never at module top (GATE-01 / `test_okx_inertness.py`).
3. **Construct the store from `system_db_backend`** — the same handle `VenueStore` takes.
4. **Never barrel-export** the store or the catalog.

**Ordering constraints this placement satisfies** (RESEARCH-verified, all four):
portfolios layered before (`:1250`) · session-init `wire_universe` + `register_strategy_warmup` read
the strategy list AFTER · the three `_initialize_live_session` monkeypatch tests stay reachable ·
GATE-01 inertness.

**The D-22 ingress needs NO change** (`live_trading_system.py:56-58`):
```python
_EXTERNALLY_ADMISSIBLE = frozenset(
    {EventType.SIGNAL, EventType.STRATEGY_COMMAND, EventType.CONFIG_UPDATE}
)
```

> **Do NOT blanket-wrap rehydrate in `except _degrade_clean`** — that inverts D-19's loud-infrastructure
> arm into a silent boot-with-zero-strategies, which D-19 calls "worse."

---

### 2. `core/policy_codec.py` (NEW, utility, transform) — the D-03 codec

**Analog:** `itrader/core/sizing.py`. **Indentation: 4-SPACE.** Must depend on nothing in `itrader`
(inertness + core→config direction).

**The six frozen dataclasses the codec must round-trip — field types verbatim:**

```python
# Source: itrader/core/sizing.py
@dataclass(frozen=True, slots=True)
class FractionOfCash:            # :94
    fraction: Decimal
    step_size: Decimal | None = None

@dataclass(frozen=True, slots=True)
class FixedQuantity:             # :118
    qty: Decimal
    step_size: Decimal | None = None

@dataclass(frozen=True, slots=True)
class RiskPercent:               # :138
    risk_pct: Decimal
    step_size: Decimal | None = None

@dataclass(frozen=True, slots=True)
class LeveredFraction:           # :162
    fraction: Decimal
    step_size: Decimal | None = None

@dataclass(frozen=True, slots=True, kw_only=True)
class PercentFromFill:           # :209
    sl_pct: Decimal
    tp_pct: Decimal
    trail_type: "TrailType | None" = None      # ⚠️ QUOTED forward ref, enum-in-union
    trail_value: Decimal | None = None

@dataclass(frozen=True, slots=True, kw_only=True)
class PercentFromDecision:       # :278   ← OMITTED by CONTEXT's D-03 list; a live SLTPPolicy member
    sl_pct: Decimal
    tp_pct: Decimal
```

**The two unions to derive the `kind → class` registry from** (`sizing.py:205`, `:301`):
```python
SizingPolicy = FractionOfCash | FixedQuantity | RiskPercent | LeveredFraction
SLTPPolicy   = PercentFromFill | PercentFromDecision
```
Derive via `typing.get_args()` — makes omitting a member structurally impossible (`PercentFromDecision`
was already missed once, in CONTEXT itself).

**The `trail_type` trap, at source** (`sizing.py:242` + `:264`) — the one field resisting generic coercion:
```python
    trail_type: "TrailType | None" = None
    ...
    def __post_init__(self) -> None:
        ...
            # TrailType is imported lazily here (config-enum exception): a module-level
            # runtime import would invert the core->config dependency direction.
            from itrader.config import TrailType
```
Three consequences for the codec: (a) `dataclasses.fields()[i].type` returns the raw **string**
`'TrailType | None'` → use `typing.get_type_hints`, not `field.type`; (b) `get_type_hints()` will
**raise `NameError`** — `TrailType` is deliberately not importable at `sizing.py` module level → pass an
explicit `localns`/`globalns`; (c) unwrap `X | None` and dispatch `Enum(value)` on the non-None arm.

**`__post_init__` re-validates on decode** (`sizing.py:112-114`) — the codec gets validation for free:
```python
    def __post_init__(self) -> None:
        _require_unit_interval("FractionOfCash", "fraction", self.fraction)
        _validate_step_size("FractionOfCash", self.step_size)
```

**Money boundary:** every `Decimal` field serializes to a **string**, re-enters via `to_money`/
`Decimal(str)`. Never `Decimal(float)`, never `float()`.

---

### 3. `strategy_handler/registry/` (NEW collaborator subdir) — D-05 reconstruction

**Analog:** `order_handler/admission/` + `order_handler/reconcile/`. **Indentation: TABS.**

Confirmed subdir shape (`ls`): each is exactly `__init__.py` + `<name>_manager.py`.

**The barrel to copy** (`order_handler/admission/__init__.py`, complete file):
```python
"""
Admission subdomain package.

Re-exports the AdmissionManager — the signal→order pipeline collaborator
(D-07/D-08/D-09) — so consumer import paths stay short after the order-manager
decomposition (pure move, D-12/D-13). It is NOT added to the order_handler top
barrel (D-12): it is an OrderManager implementation detail.
"""

from .admission_manager import AdmissionManager

__all__ = ["AdmissionManager"]
```
**Copy the "NOT added to the top barrel" property** — it is exactly what GATE-01 needs for the registry
collaborator (which reaches the store).

---

### 4. `storage/strategy_registry_store.py` (mod, store, CRUD) — the D-06 schema change

**Analog:** itself. **Indentation: 4-SPACE.**

**The registrar as it stands today** (`:48-91`) — note **`strategy_type` is ABSENT** (D-06 must add it):
```python
def build_strategy_registry_tables(metadata: MetaData) -> dict[str, Table]:
    """Register (idempotently) the registry + subscriptions tables on ``metadata``.

    Per-table idempotency guards on a shared backend ... Single source of truth for BOTH
    tables' schema feeding the test-path ``create_all`` and the Plan 04-03 Alembic autogenerate.
    """
    tables: dict[str, Table] = {}

    if "strategy_registry" in metadata.tables:
        tables["strategy_registry"] = metadata.tables["strategy_registry"]
    else:
        tables["strategy_registry"] = Table(
            "strategy_registry",
            metadata,
            # Natural NAME PK (D-06) — NOT the ephemeral runtime strategy_id UUID.
            Column("strategy_name", String, primary_key=True),
            Column("enabled", Boolean, nullable=False),
            Column("config_json", json_variant(), nullable=False),
            Column("updated_at", UtcIsoText, nullable=False),
        )
    # ... strategy_subscriptions (venue, symbol, timeframe) — D-06 DROPS this
    return tables
```

**The new child table copies the FK+composite-PK shape** of the dropped `strategy_subscriptions`
(`:75-89`):
```python
            Column(
                "strategy_name",
                String,
                ForeignKey("strategy_registry.strategy_name"),
                primary_key=True,
                nullable=False,
            ),
            Column("venue", String, primary_key=True, nullable=False),   # → portfolio_id
```

**Constructor pattern to preserve** (`:106-114`) — schema-pure, registrar-fed, bound logger:
```python
    def __init__(self, sql_engine: SqlEngine) -> None:
        self.backend = sql_engine
        self.engine: Engine = sql_engine.engine
        tables = build_strategy_registry_tables(sql_engine.metadata)
        self.strategy_registry: Table = tables["strategy_registry"]
        self.strategy_subscriptions: Table = tables["strategy_subscriptions"]
        # WR-03/D-14 — schema-pure: register the tables, never create them (Alembic-owned
        # in production; tests provision via tests.support.schema.provision_schema).
        self.logger = get_itrader_logger().bind(component="StrategyRegistryStore")
```

**Parameterized-Core write pattern (SEC-01) + the FK-driven update-never-delete rule** (`:120-139`):
```python
    def upsert(
        self, strategy_name: str, config: dict[str, Any], enabled: bool, at: datetime
    ) -> None:
        """Persist (or overwrite) a strategy's config + enabled flag with ``updated_at`` ``at``.

        ... The parent row is UPDATED (never deleted) when it already exists: deleting it would
        violate the ``strategy_subscriptions`` FK once child rows exist ... which the SQLite
        ``PRAGMA foreign_keys=ON`` hook (WR-02) now enforces on both dialects (CR-01).
        Parameterized Core (SEC-01).
        """
        with self.engine.begin() as connection:
            updated = connection.execute(
                update(self.strategy_registry)
                .where(self.strategy_registry.c.strategy_name == strategy_name)
                .values(enabled=enabled, config_json=config, updated_at=at)
            )
            if updated.rowcount == 0:
                # ... insert arm
```
**The new `strategy_portfolio_subscriptions` child inherits this FK constraint** → D-11's `remove` must
delete child rows **before** the registry row (RESEARCH P-6; existing precedent at `:208-220`).

**Registrar = single source of truth:** the D-06 change must land in **both** the registrar **and** a
migration, or the test-path `create_all` and prod schema diverge.

---

### 5. `migrations/versions/p10_*.py` (NEW) — D-06 drop + add

**Analog:** `migrations/versions/system_stats.py` (the current head). **Indentation: 4-SPACE.**
**`down_revision` must be `"system_stats"`** (measured; CONTEXT says `strategy_registry` — wrong).

**Verified chain:**
```
2cbf0bf6b0b6 → 47f2b41f3ffe → p05_venue_order_id → hl5_transaction_venue_trade_id
  → d10_halt_records → system_store → venue_config → strategy_registry
    → module_config → system_stats   ◄── HEAD (P10 chains here)
```

**Header + custom-type-import pattern to copy** (`system_stats.py:16-39`):
```python
Chained (NOT branched) onto ``module_config`` so the migration order stays linear:
``down_revision="module_config"``. This is the new single head ...

Revision ID: system_stats
Revises: module_config
Create Date: 2026-07-16 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# Hand-authored custom-type import (Pitfall 2/8): the ``timestamp`` column uses the spine's
# ``UtcIsoText`` TypeDecorator; autogenerate omits this import, so it is added by hand so
# ``alembic upgrade head`` resolves the name instead of raising ``NameError``.
import itrader.storage.types

revision: str = "system_stats"
down_revision: Union[str, Sequence[str], None] = "module_config"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None
```

**Table-creation + named-constraint + downgrade shape** (`:42-64`):
```python
def upgrade() -> None:
    """Create the append-only ``system_stats`` counter series (seq PK, no autoincrement)."""
    op.create_table(
        "system_stats",
        sa.Column("seq", sa.Integer(), autoincrement=False, nullable=False),
        sa.Column("timestamp", itrader.storage.types.UtcIsoText(), nullable=False),
        ...
        sa.PrimaryKeyConstraint("seq", name=op.f("pk_system_stats")),
    )


def downgrade() -> None:
    """Downgrade schema — drop the ``system_stats`` table."""
    op.drop_table("system_stats")
```
P10's migration additionally needs `op.drop_table("strategy_subscriptions")` +
`op.add_column("strategy_registry", ...strategy_type...)`, with the **inverse in `downgrade()`**.
(RESEARCH A1: the drop assumes the table is empty — unverifiable from source; verify on the target DB.)

---

### 6. `events/universe.py::StrategyCommandEvent` (mod, event) — the D-08 extension

**Analog:** itself, `:100`. **Indentation: 4-SPACE.** Events are **`msgspec.Struct`**, NOT the frozen
`@dataclass` CLAUDE.md describes. **The real Struct shape:**

```python
# Source: itrader/events_handler/events/universe.py:100-142
class StrategyCommandEvent(Event, frozen=True, kw_only=True, gc=False):
    """An add/remove-ticker command addressed to one strategy (D-09).
    ...
    - ``verb`` — ``"add_ticker"`` | ``"remove_ticker"`` today; the vocabulary
      grows to enable/disable/reconfigure later.
    ...
    Construct via the ``add_ticker`` / ``remove_ticker`` factory classmethods
    (the ``FillEvent.new_fill`` house convention), never by hand.
    """

    type: ClassVar[EventType] = EventType.STRATEGY_COMMAND
    strategy_name: str
    verb: str
    symbol: str

    @classmethod
    def add_ticker(cls, strategy_name: str, symbol: str, *,
                   time: datetime) -> "StrategyCommandEvent":
        """Build a complete ``add_ticker`` command (D-09, construct-complete)."""
        return cls(time=time, strategy_name=strategy_name,
                   verb="add_ticker", symbol=symbol)

    def __str__(self) -> str:
        return f"{self.type} ({self.strategy_name}, {self.verb}, {self.symbol})"

    def __repr__(self) -> str:
        return str(self)
```

**Struct rules for D-08's new field:** `type` is a `ClassVar` (not a field); `kw_only=True` relaxes the
defaults-after-non-defaults ordering; add `config: dict | None = None`; add **one factory classmethod
per new verb** (house convention — never construct by hand); extend `__str__`.

> **⚠️ FINDING (neither CONTEXT nor RESEARCH flags this): `symbol: str` is a REQUIRED field, but the
> D-09 verbs `enable` / `disable` / `remove` / `reconfigure` / `subscribe_portfolio` /
> `unsubscribe_portfolio` have NO symbol.** The planner must decide: default it (`symbol: str = ""`) or
> make it `str | None = None`. Either is Struct-legal under `kw_only=True`, but **every existing
> `__str__`/log-format and the `:498` `symbol = event.symbol` read assumes it is present.** This is a
> small but real edit the verb work cannot skip.

---

### 7. `strategies_handler.py::on_strategy_command` (mod, handler) — the D-09 verb surface

**Analog:** itself, `:438`. **Indentation: TABS.**

**The dispatch skeleton to extend** (`:473-512`) — locate-by-name → pair-guard → verb branches →
mutation-tracked follow-on:
```python
		by_name = {strategy.name: strategy for strategy in self.strategies}
		strategy = by_name.get(event.strategy_name)
		if strategy is None:
			# Unknown target — loud no-op (no mutation, no follow-on).
			self.logger.warning(
				'StrategyCommandEvent for unknown strategy %s (verb=%s, symbol=%s) — ignored',
				event.strategy_name, event.verb, event.symbol)
			return
		# CR-01: a PairStrategy is bound to an EXACT-2-ticker contract ...
		if isinstance(strategy, PairStrategy):
			self.logger.warning(
				'StrategyCommandEvent verb=%s refused for pair strategy %s — '
				'PairStrategy requires exactly 2 tickers and cannot be mutated via '
				'add/remove_ticker',
				event.verb, event.strategy_name)
			return
		symbol = event.symbol
		mutated = False
		if event.verb == "add_ticker":
			if symbol not in strategy.tickers:
				strategy.tickers.append(symbol)  # idempotent append
				mutated = True
		elif event.verb == "remove_ticker":
			...
```

**Patterns to copy into the new verbs:**
- **Loud no-op on unknown target** — `logger.warning` + `return`, never raise into the queue.
- **The CR-01 `isinstance(PairStrategy)` guard placed BEFORE the verb branches** — D-17 extends this
  same guard to `reconfigure`. Note the guard currently refuses **all** verbs for a pair; D-16 requires
  pairs to still `add`/`remove`/`enable`/`disable`/rehydrate, so **the blanket guard must become
  verb-scoped** (refuse `reconfigure` + ticker verbs; allow the lifecycle verbs). Flagging: the
  existing guard's placement is *broader* than D-16 permits.
- **The `mutated` flag gating the `UniversePollEvent` follow-on (IN-02)** — no control-plane churn on a
  no-op. D-09's "every verb persists" should be gated the same way.
- **Queue-only:** it emits `UniversePollEvent`; it never calls `UniverseHandler`.

---

### 8. `strategies_handler.py::calculate_signals` (mod, hot path) — the D-07 `is_active` guard

**Analog:** itself, `:141`. **Indentation: TABS.** ⚠️ **ORACLE-GATED — the one shared hot-path edit.**

**The exact loop head to edit** (`:158-168`):
```python
		for strategy in self.strategies:
			# Check if the strategy's timeframe is a multiple of the bar event time
			if not check_timeframe(event.time, strategy.timeframe):
				continue
			# PAIR-01 (D-01): a PairStrategy is dispatched ONCE per tick through a
			# typed two-leg branch (NOT the per-ticker loop below) — both legs are
			# evaluated together and fanned out per portfolio. ...
			if isinstance(strategy, PairStrategy):
				self._dispatch_pair(strategy, event)
				continue
```
**Copy the existing guard idiom exactly:** a `continue`-style guard at the top of the loop with a
decision-tagged comment. `is_active` defaults `True` and no backtest path calls `deactivate_strategy` →
behaviour-preserving. **Per-plan gate: `poetry run pytest tests/integration/test_backtest_oracle.py -x`
must stay byte-exact at `134 / 46189.87730727451`.**

---

### 9. `universe_handler.py` — the D-10/D-14 warmup pipeline (READ-ONLY reuse)

**Analog:** itself. **Indentation: 4-SPACE ⚠️ (CONTEXT says tabs — CONTEXT is WRONG; measured 0/559).**

Reuse `spawn_warmup:508` → `on_bars_loaded:516` → WR-02 warm-verify gate + CR-02 FAILED-retry
(`:383-394`). **Do not build a second warmup path** — `live_bar_feed.py:286-290` explicitly refuses a
second state-building path (the LX-09 lesson).

---

## Shared Patterns

### Lazy-import-inside-the-gate (GATE-01 inertness)
**Source:** `live_trading_system.py:1521-1523`, `:1529`, `:1563`
**Apply to:** every P10 touch of `StrategyRegistryStore` and the registry collaborator.
```python
    if system_store is not None:
        from itrader.storage.venue_store import VenueStore   # LAZY inside the gate
```
Never at module top; never barrel-exported. Gate: `tests/integration/test_okx_inertness.py`.

### Loud rejection over silent no-op
**Source:** `strategies_handler.py:477`, `:492`; `base.py:279` (`UnknownParamError`)
**Apply to:** D-02 duplicate name, D-10 unknown type, D-15 immutable/finer-than-base, D-17 pair
reconfigure, D-19 infrastructure arm.

### Registrar = single source of truth
**Source:** `strategy_registry_store.py:48-91` + `migrations/versions/system_stats.py`
**Apply to:** the D-06 schema change — **both** the registrar **and** the migration, or test-path and
prod schemas diverge. Stores are **schema-pure** (never `create_all` at runtime).

### Parameterized SQLAlchemy Core only (SEC-01)
**Source:** `strategy_registry_store.py:133-138`
**Apply to:** every new child-table query. **`strategy_type` arrives from an external
`STRATEGY_COMMAND` payload** — the catalog dict lookup IS the allowlist control; never
`importlib.import_module(strategy_type)` or `eval`.

### Bound component logger
**Source:** `strategy_registry_store.py:114`
```python
        self.logger = get_itrader_logger().bind(component="StrategyRegistryStore")
```

### Decision-tagged docstrings/comments
**Source:** every file read. Module docstrings and inline comments cite `D-NN` / `WR-NN` / `CR-NN` /
`SEC-01`. These tags are **load-bearing** references to planning artifacts — new P10 code must carry
its own `D-01..D-22` tags.

---

## No Analog Found

| File | Role | Data Flow | Reason |
|---|---|---|---|
| — | — | — | **None.** Every P10 file has a close in-repo analog. This is a wiring/extension phase; RESEARCH's "P10's dominant risk is **duplicating existing machinery**, not missing machinery" is confirmed by the pattern map. |

The only genuinely novel logic is the **generic dataclass codec's type-introspection** (`get_type_hints`
+ `get_args` union-unwrap + enum-in-Optional). Its closest in-repo precedent is `base.py:130-133`
`_declared_hints` (`@cache def _declared_hints(cls): return get_type_hints(cls)`) — copy that idiom, but
note it will **`NameError` on `PercentFromFill.trail_type`** without an explicit namespace.

---

## Metadata

**Analog search scope:** `itrader/trading_system/`, `itrader/strategy_handler/`, `itrader/storage/`,
`itrader/core/`, `itrader/order_handler/`, `itrader/events_handler/events/`, `itrader/universe/`,
`itrader/price_handler/feed/`, `migrations/versions/`
**Files scanned:** 14 indentation-measured + 10 migration revisions + 8 read for excerpts
**Independent verifications performed:** per-file indentation (14 files); full migration chain
(`revision`/`down_revision` grep); `order_handler/` subdir listing; `strategy_registry` registrar column
set
**Pattern extraction date:** 2026-07-17

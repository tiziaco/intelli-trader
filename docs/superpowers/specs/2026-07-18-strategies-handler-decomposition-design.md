# StrategiesHandler Decomposition — Design

**Date:** 2026-07-18
**Status:** SUPERSEDED IN PART — see the amendment below. Executed as phase 10.1 (plans 10.1-01 … 10.1-04), completed 2026-07-20.
**Scope:** Structural refactor of `itrader/strategy_handler/strategies_handler.py` (1648 lines). Behaviour-preserving; oracle byte-exact.

---

## Amendment (2026-07-20, phase 10.1)

This document is preserved as a historical design record, **not** as a description of what
shipped. Phase 10.1's research pass (`10.1-RESEARCH.md`) disproved five of its factual claims
with executed commands, found one material omission, and the owner made four decisions during
execution that deliberately superseded the design. Everything below this section is the
**original 2026-07-18 text**, corrected only for the method rename so it stays navigable.

### A. Five claims disproved by executed verification

1. **"The three live deps are constructor-visible."** They were **post-construction-injected** —
   three assignments at `live_trading_system.py:1630/1641/1642`, not constructor arguments. The
   design's proposed split assumed a constructor signature that did not exist.
2. **"`set_universe` is live-only."** It runs on the **backtest** path too
   (`universe_wiring.py:109`). Classifying it as live-only would have moved an oracle-critical
   call off the backtest import graph.
3. **"Five of the six function-local imports are load-bearing for GATE-01."** They were **not**.
   A clean-interpreter probe leaked **zero** forbidden modules and **zero** SQLAlchemy with all
   six hoisted to module top. The design's central justification for the lazy-import structure
   was false; the imports were dissolved outright.
4. **"`ErrorSeverity` / `ErrorEvent` are already imported at module top."** They were **not**, so
   handling them was an **add**, not the delete the design described.
5. **"312 test field-references."** The actual figure was **185** (113 handler-scoped).

### B. Material omission

The design enumerated the control-plane helpers but omitted **four module-level verb constants**
that the extracted control plane depends on — `_PAIR_REFUSED_VERBS`, `_POLL_FOLLOW_ON_VERBS`,
`_RECONFIGURE_IMMUTABLE`, `_RECONFIGURE_VERB_ONLY` (now `lifecycle/manager.py:94/101/122/125`).
Following the design literally would have produced a `NameError` at the first verb dispatch.

### C. Owner decisions that superseded the design

1. **Unconditional `__init__`-time construction.** Both collaborators are built in `__init__`
   from module-top imports — no `Optional`, no guard, no late-init helper. The design's
   lazy/optional shape was rejected outright.
2. **The three live deps are real at `__init__`.** `registry_store` is handler-owned via a new
   `StrategyRegistryStorageFactory` keyed on `(environment, sql_engine)`; `strategy_catalog` is
   an `Optional[Any]` `compose_engine` kwarg (D-01 forbids `itrader` importing a concrete
   strategy class); `portfolio_read_model` is a `compose.py` pass-through.
3. **Positive SQL-absence assertion replaced the `_FORBIDDEN` name-list entry.** The lifecycle
   module is on the backtest import graph **by design**, so the design's proposed name-list entry
   would have failed the gate immediately. `test_okx_inertness.py` now asserts SQL absence
   positively instead.
4. **`my_strategies/` excluded from the DECOMP-03 rename** (2026-07-20). It is gitignored and
   untracked, imported by nothing, and its same-named methods are a distinct legacy per-strategy
   API on the removed `AbstractStrategy` base — not the handler method.

### D. Single-owner read-through properties

The three live deps are exposed as read-through properties with a single owner. This was not in
the design and was required by the test surface: **28 post-construction assignments across 7 test
files** would otherwise have desynced from a manager holding captured values.

---

## Problem

`StrategiesHandler` has grown to 1648 lines and does three distinct jobs:

| Concern | Methods | ~Lines | Runs on |
|---|---|---|---|
| **Data plane** (signal generation / warmup) | `on_bar`, `_emit_intent`, `_dispatch_pair`, `on_bars_loaded`, `is_warm`, `set_universe` | ~300 | backtest **+** live |
| **Control plane** (STRATEGY_COMMAND verbs) | `on_strategy_command` + 13 helpers (`_add/_remove/_reconfigure_*_verb`, `_persist_strategy`, `_request_rewarm`, `_portfolio_id_from`, `_strategy_is_flat`, `_try_complete_removal`, `_reconfigure_*_check`, `_emit_reconfigure_apply_failure`, `on_fill`) | ~700 | **live only** |
| **Roster** (membership + registration rules) | `add_strategy`, `_direction_admissible`, `_recompute_min_timeframe`, `get_strategies_universe`, `update_config` | ~200 | both |

Two concrete symptoms:

1. **Mixed responsibilities in one file** — the live-only control plane (~700 lines) sits on top of the oracle-critical `on_bar` hot path.
2. **Load-bearing mid-function imports** — six function-local imports exist so the SQL/registry stack stays off the backtest import graph (**GATE-01 inertness**, gated by `tests/integration/test_okx_inertness.py`). Five are genuinely load-bearing today; one (`_emit_reconfigure_apply_failure`, lines 1041–1042: `ErrorSeverity`, `ErrorEvent`) is **not** — both modules are already imported at module top and pull no SQL.

## Goals

- Split the file along its natural seams into three well-bounded units.
- Move the live-only control plane off the backtest import graph so its imports live at module top — **dissolving the five load-bearing lazy imports**, not just the one accidental one.
- Rename the per-bar entry point — then the sole imperative-verb name on the BAR route — to `on_bar`, matching the documented `on_<event>()` callback convention (`CONVENTIONS.md`), as a **separately-verified step**.
- Keep the backtest oracle **byte-exact** (`46189.87730727451`, oracle 134) and `test_okx_inertness.py` green.
- Preserve the public handler surface so no external caller (compose, route registrar, tests) breaks, except the deliberate `on_bar` rename.

## Non-goals

- No behaviour change to any verb, the signal path, or pending-removal semantics.
- No change to the durable `registry/` store, `config_codec`, `catalog`, or event schemas.
- No new event types, no changes to route ordering.
- No `PairStrategy` reconfigure/ticker rework (still deferred, D-17/CR-01).

## Target architecture

Three units, mirroring the `order_handler/` collaborator-extraction precedent (`admission/`, `brackets/`, `lifecycle/`, `reconcile/`):

```
StrategiesHandler          (thin: data plane + queue seam)
   ├── ManagedStrategies   (shared: the live instance set + membership rules)
   └── StrategyLifecycleManager (live-only: STRATEGY_COMMAND verbs + fill-driven removal completion)
              └── depends on ManagedStrategies + live deps + feed + queue
```

The naming distinguishes three strategy-collection concepts that already coexist:

| Concept | What it holds | Home |
|---|---|---|
| `strategy_catalog` | Allowlist of strategy **types/classes** that may be built (D-10) | `registry/catalog.py` |
| `registry_store` | **Durable** (SQL) store of strategy **configs** surviving restart | `registry/` |
| **`ManagedStrategies`** | The **live, in-memory instances** the handler iterates each bar + runtime membership state | **new** |

### Unit 1 — `ManagedStrategies` (new)

**File:** `itrader/strategy_handler/managed_strategies.py` — **tab-indented** (match `strategies_handler.py` and the rest of `strategy_handler/`; do not normalize).

**Owns (the only genuinely-shared mutable state):**
- `strategies: list[Strategy]`
- `min_timeframe: timedelta | None`
- `_pending_removals: set[str]`
- `_allow_short_selling: bool`, `_enable_margin: bool` (registration policy)

**Methods (pure membership logic, no queue, no live deps):**
- `add_strategy(strategy)` — direction gate + duplicate-name reject + append + `min_timeframe` derivation (verbatim move of current `add_strategy`).
- `direction_admissible(direction) -> bool` (was `_direction_admissible`).
- `recompute_min_timeframe()` (was `_recompute_min_timeframe`).
- `get_universe() -> list[str]` (was `get_strategies_universe`, honouring the `_pending_removals` exclusion).
- `by_name() -> dict[str, Strategy]` — the repeated `{s.name: s for s in strategies}` lookup, factored once.
- `remove(strategy)` — drop from `strategies` (used by removal completion).
- pending-removal set ops: `mark_pending(name)`, `discard_pending(name)`, `is_pending(name)`, `is_empty_pending`.

**Depends on:** nothing beyond `core` + `Strategy`. Stays off the SQL graph.

### Unit 2 — `StrategyLifecycleManager` (new)

**File:** `itrader/strategy_handler/lifecycle/manager.py` (mirroring the `order_handler/lifecycle/` collaborator) — **tab-indented**, live-only module → **imports at module top**.

**Why "lifecycle", not "command":** this unit owns the full runtime lifecycle of a live strategy instance — `add` (birth), `reconfigure` (mutation), `disable` (quiesce), `remove` + `on_fill` completion (death). The STRATEGY_COMMAND verbs are the *inputs* that drive those transitions; `on_fill` is **not** a command but the fill-driven completion half of the `remove` lifecycle (the D-11 hook that drops a pending-removal strategy once its positions are flat). Naming it `...CommandProcessor` would make `on_fill` a category error; `StrategyLifecycleManager` is its natural home and follows the `<Domain>Manager` house convention (`OrderManager`, `CashManager`).

**Constructor deps (injected):**
- `managed: ManagedStrategies` (the shared roster)
- `global_queue: EventBus`
- `feed: BarFeed`
- `registry_store`, `strategy_catalog`, `portfolio_read_model` (the live-only injected deps)
- `_universe` set post-construction via `set_universe` (forwarded by the handler — see below)

**Moves (verbatim, private→as-is or de-underscored where they become the module's public surface):**
`on_strategy_command`, `on_fill`, `_add_strategy_verb`, `_remove_strategy_verb`, `_reconfigure_strategy_verb`, `_reconfigure_allowlist_check`, `_reconfigure_warmability_check`, `_emit_reconfigure_apply_failure`, `_persist_strategy`, `_request_rewarm`, `_portfolio_id_from`, `_strategy_is_flat`, `_try_complete_removal`.

`on_fill` moves here as a **lifecycle** concern (not a command): it re-scans `_pending_removals` and calls `_try_complete_removal`, i.e. it is the second half of the `remove` verb — `remove` initiates the pending removal, fills complete it once positions flatten. Its logic is coupled to `_pending_removals` (owned by `ManagedStrategies`) and `_try_complete_removal` (moved above), so it belongs with the removal verb it completes.

These call into `managed` for roster mutation (`managed.add_strategy`, `managed.remove`, `managed.direction_admissible`, `managed.recompute_min_timeframe`, `managed.by_name`, pending-removal ops) — **no back-reference to the handler**.

**Import story:** because this module is imported **only** on the live path (never re-exported from a package barrel, constructed only inside the live wiring arm — same discipline as the v1.7 live stack), its top-of-file imports may include `registry.config_codec`, `registry.rehydrate`, `registry.catalog`, `policy_codec`, and `price_handler.feed.cache_registration`. The five load-bearing lazy imports collapse to normal top imports. `test_okx_inertness.py` continues to guard that `import itrader` / the backtest path never reaches this module.

### Unit 3 — `StrategiesHandler` (slimmed, ~350 lines)

**Keeps (data plane + queue seam):**
- `on_bar` (renamed in DECOMP-03), `_emit_intent`, `_dispatch_pair`, `on_bars_loaded`, `is_warm`, `set_universe`, `update_config`.
- Constructs `self._managed = ManagedStrategies(...)` and, when live deps are present, `self._lifecycle = StrategyLifecycleManager(self._managed, ...)`. On the backtest path the live deps are absent, so `self._lifecycle` is `None` (never constructed).

**Public surface preserved via thin delegation (back-compat — tests and route registrar depend on these):**
- `on_strategy_command(event)` → `self._lifecycle.on_strategy_command(event)`
- `on_fill(event)` → `self._lifecycle.on_fill(event)`
- `add_strategy(strategy)` → `self._managed.add_strategy(strategy)`
- `get_strategies_universe()` → `self._managed.get_universe()`
- **Properties** (tests read these directly): `strategies` → `self._managed.strategies`; `min_timeframe` → `self._managed.min_timeframe`; `_pending_removals` → `self._managed._pending_removals`.

**Backtest guard (implementation note):** the delegating `on_strategy_command`/`on_fill` above are safe today **only** because neither route is wired into the backtest `_routes` — nothing ever calls them there, so `self._lifecycle` being `None` never bites. That is an *implicit* invariant. Guard each delegator with `assert self._lifecycle is not None` (or an explicit live-only `raise`) so that if a future change ever routes FILL / STRATEGY_COMMAND onto the backtest path, it fails **loud** at the seam instead of raising an opaque `AttributeError: 'NoneType' object has no attribute 'on_fill'`.

The hot-path text `for strategy in self.strategies` is therefore **byte-identical** — the `strategies` property returns the same list object `ManagedStrategies` owns. `on_bar` never edits its body; only the method name changes.

**`_universe` sharing:** the handler owns `self._universe` (hot-path readiness gate reads it). `set_universe(universe)` sets `self._universe` **and** (when live) forwards to `self._lifecycle.set_universe(universe)` (the lifecycle manager's `_request_rewarm` mutates `_universe.mark_failed`). Two references to one object, set together — explicit, no back-ref.

## The `on_bar` rename (separate, verified step)

The per-bar entry point was the only BAR-route consumer named as an imperative verb; every sibling callback is `on_<event>()`. Renamed to `on_bar`.

**Ripple (all mechanical grep-and-replace, but touches the route table → own verification):**
- `events_handler/full_event_handler.py:95` — the **only** route site. The BAR route lives in the base `_routes` literal that *both* modes reuse; `route_registrar.py` does not set the BAR route (it only sets `UNIVERSE_*` / `STRATEGY_COMMAND` / `BARS_*` and appends to `FILL`), so it needs **no** edit for this rename.
- **59 test call-sites** across ~14 files.
- `CLAUDE.md` canonical-flow diagram (line ~54, `strategies_handler.on_bar`) and `.planning/codebase/` docs referencing it.

**No compatibility alias.** This repo dislikes dead/duplicate surface; the call-sites are updated directly rather than leaving a shim under the old name.

## Wiring changes

- `trading_system/compose.py:227` — `StrategiesHandler(...)` constructor call: signature **unchanged**. Internal wiring (constructing `ManagedStrategies` + `StrategyLifecycleManager`) happens inside `__init__`, so compose is untouched except any read-back it already does.
- `route_registrar.py` — registrations reference `self._strategies_handler.on_strategy_command`, `.on_bars_loaded`, `.on_fill`; all preserved via handler delegation, so **no registrar edit** (it does not reference `on_bar`/the BAR route).
- `full_event_handler.py:95` — BAR route updated for the `on_bar` rename only.

## Testing & back-compat

- **No test reaches a private verb helper** (verified), so moving them into the processor is transparent.
- **Delegating properties** keep `handler._pending_removals` / `.min_timeframe` / `.strategies` reads working (312 field references across tests).
- **New unit tests** for `ManagedStrategies` in isolation (direction gate, dup reject, min_timeframe derivation, pending-removal set, universe exclusion) — a genuine test-surface win the current monolith can't offer.
- **Gate: `test_okx_inertness.py`** must stay green after imports move to the processor's module top.
- **Gate: oracle byte-exact** — `make test-integration` / the `test_backtest_oracle.py` value unchanged.
- **Gate: full unit suite** — the 4 verb/lifecycle test files (`test_strategy_command_verbs`, `test_reconfigure_atomic`, `test_reconfigure_allowlist`, `test_strategies_live_membership`) exercise the moved code through `on_strategy_command`.

## Risks & mitigations

| Risk | Mitigation |
|---|---|
| Oracle drift from touching the hot path | `strategies` property returns the same list object; `on_bar` body is unedited; oracle test is a gate. |
| Inertness regression (SQL pulled onto backtest graph) | Processor module is live-only, never barrelled, constructed only in the live arm; `test_okx_inertness.py` is a gate. |
| `on_bar` rename missing a call-site | Grep-driven; route-table + full-suite verification; it's the reason the rename is a separate step. |
| Hidden coupling via `_universe` between hot path and processor | `set_universe` forwards to both explicitly; documented. |

## Suggested sequencing (for the implementation plan)

1. Extract `ManagedStrategies` + delegating properties on the handler (no verb moves yet). Verify: full suite + oracle.
2. Extract `StrategyLifecycleManager`; move the 13 verb helpers + `on_strategy_command`/`on_fill`; hoist imports to module top; add the `self._lifecycle is not None` guards on the handler's delegators; delete the now-dead lazy imports (including the accidental 1041–1042). Verify: full suite + oracle + inertness.
3. Rename the per-bar entry point to `on_bar` across source, routes, tests, and docs. Verify: full suite + oracle + `test_dispatch_registry`.

Each step is independently green — the refactor never has a broken intermediate state.

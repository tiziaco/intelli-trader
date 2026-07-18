# StrategiesHandler Decomposition — Design

**Date:** 2026-07-18
**Status:** Draft (awaiting user review)
**Scope:** Structural refactor of `itrader/strategy_handler/strategies_handler.py` (1648 lines). Behaviour-preserving; oracle byte-exact.

## Problem

`StrategiesHandler` has grown to 1648 lines and does three distinct jobs:

| Concern | Methods | ~Lines | Runs on |
|---|---|---|---|
| **Data plane** (signal generation / warmup) | `calculate_signals`, `_emit_intent`, `_dispatch_pair`, `on_bars_loaded`, `is_warm`, `set_universe` | ~300 | backtest **+** live |
| **Control plane** (STRATEGY_COMMAND verbs) | `on_strategy_command` + 13 helpers (`_add/_remove/_reconfigure_*_verb`, `_persist_strategy`, `_request_rewarm`, `_portfolio_id_from`, `_strategy_is_flat`, `_try_complete_removal`, `_reconfigure_*_check`, `_emit_reconfigure_apply_failure`, `on_fill`) | ~700 | **live only** |
| **Roster** (membership + registration rules) | `add_strategy`, `_direction_admissible`, `_recompute_min_timeframe`, `get_strategies_universe`, `update_config` | ~200 | both |

Two concrete symptoms:

1. **Mixed responsibilities in one file** — the live-only control plane (~700 lines) sits on top of the oracle-critical `calculate_signals` hot path.
2. **Load-bearing mid-function imports** — six function-local imports exist so the SQL/registry stack stays off the backtest import graph (**GATE-01 inertness**, gated by `tests/integration/test_okx_inertness.py`). Five are genuinely load-bearing today; one (`_emit_reconfigure_apply_failure`, lines 1041–1042: `ErrorSeverity`, `ErrorEvent`) is **not** — both modules are already imported at module top and pull no SQL.

## Goals

- Split the file along its natural seams into three well-bounded units.
- Move the live-only control plane off the backtest import graph so its imports live at module top — **dissolving the five load-bearing lazy imports**, not just the one accidental one.
- Rename `calculate_signals` → `on_bar` to match the documented `on_<event>()` callback convention (`CONVENTIONS.md`), as a **separately-verified step**.
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
   └── StrategyCommandProcessor (live-only: all STRATEGY_COMMAND verb logic)
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

### Unit 2 — `StrategyCommandProcessor` (new)

**File:** `itrader/strategy_handler/commands/processor.py` — **tab-indented**, live-only module → **imports at module top**.

**Constructor deps (injected):**
- `managed: ManagedStrategies` (the shared roster)
- `global_queue: EventBus`
- `feed: BarFeed`
- `registry_store`, `strategy_catalog`, `portfolio_read_model` (the live-only injected deps)
- `_universe` set post-construction via `set_universe` (forwarded by the handler — see below)

**Moves (verbatim, private→as-is or de-underscored where they become the module's public surface):**
`on_strategy_command`, `on_fill`, `_add_strategy_verb`, `_remove_strategy_verb`, `_reconfigure_strategy_verb`, `_reconfigure_allowlist_check`, `_reconfigure_warmability_check`, `_emit_reconfigure_apply_failure`, `_persist_strategy`, `_request_rewarm`, `_portfolio_id_from`, `_strategy_is_flat`, `_try_complete_removal`.

These call into `managed` for roster mutation (`managed.add_strategy`, `managed.remove`, `managed.direction_admissible`, `managed.recompute_min_timeframe`, `managed.by_name`, pending-removal ops) — **no back-reference to the handler**.

**Import story:** because this module is imported **only** on the live path (never re-exported from a package barrel, constructed only inside the live wiring arm — same discipline as the v1.7 live stack), its top-of-file imports may include `registry.config_codec`, `registry.rehydrate`, `registry.catalog`, `policy_codec`, and `price_handler.feed.cache_registration`. The five load-bearing lazy imports collapse to normal top imports. `test_okx_inertness.py` continues to guard that `import itrader` / the backtest path never reaches this module.

### Unit 3 — `StrategiesHandler` (slimmed, ~350 lines)

**Keeps (data plane + queue seam):**
- `on_bar` (renamed from `calculate_signals`), `_emit_intent`, `_dispatch_pair`, `on_bars_loaded`, `is_warm`, `set_universe`, `update_config`.
- Constructs `self._managed = ManagedStrategies(...)` and, when live deps are present, `self._commands = StrategyCommandProcessor(self._managed, ...)`.

**Public surface preserved via thin delegation (back-compat — tests and route registrar depend on these):**
- `on_strategy_command(event)` → `self._commands.on_strategy_command(event)`
- `on_fill(event)` → `self._commands.on_fill(event)`
- `add_strategy(strategy)` → `self._managed.add_strategy(strategy)`
- `get_strategies_universe()` → `self._managed.get_universe()`
- **Properties** (tests read these directly): `strategies` → `self._managed.strategies`; `min_timeframe` → `self._managed.min_timeframe`; `_pending_removals` → `self._managed._pending_removals`.

The hot-path text `for strategy in self.strategies` is therefore **byte-identical** — the `strategies` property returns the same list object `ManagedStrategies` owns. `on_bar` never edits its body; only the method name changes.

**`_universe` sharing:** the handler owns `self._universe` (hot-path readiness gate reads it). `set_universe(universe)` sets `self._universe` **and** forwards to `self._commands.set_universe(universe)` (the processor's `_request_rewarm` mutates `_universe.mark_failed`). Two references to one object, set together — explicit, no back-ref.

## The `on_bar` rename (separate, verified step)

`calculate_signals` is the only BAR-route consumer named as an imperative verb; every sibling callback is `on_<event>()`. Rename to `on_bar`.

**Ripple (all mechanical grep-and-replace, but touches the route table → own verification):**
- `events_handler/full_event_handler.py:95` — the **only** route site. The BAR route lives in the base `_routes` literal that *both* modes reuse; `route_registrar.py` does not set the BAR route (it only sets `UNIVERSE_*` / `STRATEGY_COMMAND` / `BARS_*` and appends to `FILL`), so it needs **no** edit for this rename.
- **59 test call-sites** across ~14 files.
- `CLAUDE.md` canonical-flow diagram (line ~54, `strategies_handler.calculate_signals`) and `.planning/codebase/` docs referencing it.

**No compatibility alias.** This repo dislikes dead/duplicate surface; the call-sites are updated directly rather than leaving a `calculate_signals` shim.

## Wiring changes

- `trading_system/compose.py:227` — `StrategiesHandler(...)` constructor call: signature **unchanged**. Internal wiring (constructing `ManagedStrategies` + `StrategyCommandProcessor`) happens inside `__init__`, so compose is untouched except any read-back it already does.
- `route_registrar.py` — registrations reference `self._strategies_handler.on_strategy_command`, `.on_bars_loaded`, `.on_fill`; all preserved via handler delegation, so **no registrar edit** (it does not reference `calculate_signals`/the BAR route).
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
2. Extract `StrategyCommandProcessor`; move the 13 verb helpers + `on_strategy_command`/`on_fill`; hoist imports to module top; delete the now-dead lazy imports (including the accidental 1041–1042). Verify: full suite + oracle + inertness.
3. Rename `calculate_signals` → `on_bar` across source, routes, tests, and docs. Verify: full suite + oracle + `test_dispatch_registry`.

Each step is independently green — the refactor never has a broken intermediate state.

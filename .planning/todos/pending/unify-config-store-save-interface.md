---
status: deferred
created: "2026-07-16"
source: owner question 2026-07-16 during config_router dry-validate cleanup — "why don't all four config stores share one module.storage.save_config(...) interface?"
tags: [config, config-router, storage, persistence, refactor, interface-unification, protocol, feature-envy, deferred]
resolves_phase: ""
folded_into: ""
---

# Unify the config-persistence interface — one `store.save_config(...)` seam across all four scopes

**Origin:** While cleaning up `ConfigRouter._dry_validate_copy` (fast task `260716-cfg`), the owner noticed
`ConfigRouter` persists each scope through a DIFFERENT method/shape and asked whether all four could share
one `module.storage.save_config(...)` interface. Recorded as a deferred design item (not to be done now).

## Today's split (the four persist call-sites in `itrader/trading_system/config_router.py`)
- `order`     → `order_handler.storage.save_config(config, at)`          (`order_handler/base.py:277`)
- `portfolio` → `portfolio.state_storage.save_config(config, at)`        (`portfolio_handler/base.py:397`)
- `venue`     → `venue_store.upsert(venue_name, config, enabled, at)`    (`itrader/storage/venue_store.py:127`)
- `system`    → `system_store.upsert(key, value, at)`                    (`itrader/storage/system_store.py:82`)

## Finding — these are TWO real store shapes, not one
A blanket rename of `upsert`→`save_config` would be WRONG. The stores differ structurally:

1. **Bound single-record config stores (order, portfolio)** — ALREADY the target shape:
   `save_config(config, at)` + `load_config()`. Order is a cardinality-1 singleton table; the portfolio
   store instance is already bound to one portfolio. Neither needs a key argument. Nothing to change.

2. **Keyed multi-record stores (system, venue)** — genuinely different:
   - `system_store` is a **generic namespaced KV store** used for MORE than config (lifecycle state,
     universe knobs, arbitrary `config.<sub>.<field>` keys). Renaming its `upsert(key, value, at)` to
     `save_config` would misrepresent a general KV store as config-only.
   - `venue_store` is keyed by `venue_name` (many venues in one store) **and** carries a non-config
     `enabled` column (an operational flag, outside the D-05 secret-scrub). `save_config(config, at)`
     cannot express the key or the `enabled` payload.

So `save_config(config, at)` fits order/portfolio but not system/venue without distorting them.

## Two viable paths
- **Option A (light) — a `ConfigStore` Protocol.** Define `ConfigStore` (`save_config(config, at)` /
  `load_config()`); order + portfolio already satisfy it structurally. Leave system/venue as their native
  keyed stores. Gives a typed contract for the two config-record stores but the router still has two call
  shapes. Low effort, honest, but does NOT deliver the uniform `store.save_config(...)` seam the owner asked
  for.

- **Option B (full — RECOMMENDED) — a thin per-scope config-adapter.** Give `ConfigRouter` ONE uniform seam:
  it always calls `save_config(...)`; each scope's adapter delegates to the native method underneath
  (system → `upsert(key, …)`, venue → `upsert(name, config, enabled, …)`). This actually delivers the
  uniform interface AND lifts venue's `venue_name`/`enabled` handling OUT of the router — dissolving the
  router's cross-store feature-envy smell (the router currently knows each domain's private persistence
  shape). Cost: a small adapter layer.

## Why deferred (not done now)
- Owner explicitly asked to record, not implement.
- It is real design work (Protocol + adapters), not a mechanical rename — belongs in a planned phase, not a
  fast/quick task.
- Touches the live CONTROL-plane persistence seam (D-15 validate→persist→apply ordering, D-21/D-25
  each-module-owns-its-config); any change must preserve those invariants and the V7 secret-scrub boundary.

## Tie-in
- `ConfigRouter` (`trading_system/config_router.py`) is the sole consumer — the `_apply_system` /
  `_apply_order` / `_apply_venue` / `_apply_portfolio` persist steps are the four call-sites to unify.
- Option B is the concrete form of the "distribute persistence knowledge out of the router" idea discussed
  when reviewing the router's design (centralize-vs-distribute trade-off; the router intentionally centralizes
  the ordering contract today).
- Related invariants to preserve: D-15 (validate→persist→apply→push), D-21/D-25 (module-owned config, never
  centralized into SystemStore), V7 (venue secret-scrub in `VenueStore.upsert`).

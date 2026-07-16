---
phase: 09-runtime-config-platform
reviewed: 2026-07-16T11:37:16Z
depth: standard
files_reviewed: 22
files_reviewed_list:
  - itrader/config/itrader_config.py
  - itrader/config/system.py
  - itrader/events_handler/events/control.py
  - itrader/trading_system/config_router.py
  - itrader/trading_system/route_registrar.py
  - itrader/trading_system/live_trading_system.py
  - itrader/trading_system/session_initializer.py
  - itrader/trading_system/safety/safety_controller.py
  - itrader/order_handler/base.py
  - itrader/order_handler/storage/sql_storage.py
  - itrader/order_handler/storage/cached_sql_storage.py
  - itrader/order_handler/storage/in_memory_storage.py
  - itrader/portfolio_handler/base.py
  - itrader/portfolio_handler/storage/models.py
  - itrader/portfolio_handler/storage/sql_storage.py
  - itrader/portfolio_handler/storage/cached_sql_storage.py
  - itrader/portfolio_handler/storage/in_memory_storage.py
  - itrader/storage/system_stats_store.py
  - migrations/env.py
  - migrations/versions/module_config.py
  - migrations/versions/system_stats.py
  - itrader/execution_handler/execution_handler.py
findings:
  critical: 2
  warning: 4
  info: 0
  total: 6
status: resolved
resolved: 2026-07-16
resolution_note: >
  All 6 findings addressed (WR-04 was a real finding, fixed — not a non-finding).
  Fixes committed atomically (fix(09)/test(09)); full suite + oracle byte-exact +
  inertness + migrations + mypy --strict all green.
---

# Phase 9: Code Review Report

**Reviewed:** 2026-07-16T11:37:16Z
**Depth:** standard
**Files Reviewed:** 22
**Status:** resolved (all findings addressed 2026-07-16)

## Summary

Reviewed the Phase-9 runtime-config-platform changes: the `ConfigRouter`
validate→persist→apply→push path and scope→owner dispatch, the `add_event`
CONFIG_UPDATE ingress validation, the durable `save_config`/`load_config`
round-trips (order + portfolio), the two Alembic migrations, and the
`system_stats` store. Migration chain is a single linear head
(`…→strategy_registry→module_config→system_stats`) — verified, no branch. The
frozen-base / mutable-sub-model default-deny structure, Decimal handling, and
lazy-import inertness discipline all hold.

Two BLOCKER-class defects were found, both in the CONFIG_UPDATE actuation path
and both invisible to the current green test suite because they trigger only in
(a) the in-memory / no-Postgres wiring, and (b) the venue-scope fee/slippage
branch that carries no value-validation. The headline concern — "does a failed
persist leave the overlay mutated?" — is correctly handled for the system /
order / portfolio scopes (persist strictly precedes the live `setattr`/push),
but the **venue** scope inverts the ordering: it persists an unvalidated value
BEFORE the only step that validates it.

## Critical Issues

### [RESOLVED] CR-01: CONFIG_UPDATE route wired unconditionally, but the router is `None` in the in-memory wiring → `AttributeError` on every config update

**File:** `itrader/trading_system/route_registrar.py:134` (and `:161-170`); root cause `itrader/trading_system/live_trading_system.py:1473-1496`

**Issue:** `LiveRouteRegistrar.install()` sets the CONFIG_UPDATE route
**unconditionally**:

```python
routes[EventType.CONFIG_UPDATE] = [self._on_config_update]
```

and the consumer dereferences the router with no guard:

```python
def _on_config_update(self, event: Any) -> None:
    self._config_router.apply(event)
```

But `facade._config_router` is only ever constructed inside
`if system_store is not None:` in `build_live_system` (live_trading_system.py
:1473-1496). In the supported in-memory fallback (no
`ITRADER_DATABASE_*` credentials → `system_store is None`), `_config_router`
stays `None`, so `config_router=None` threads through
`SessionInitializer` → `LiveRouteRegistrar`, and the route is still installed.
When a `CONFIG_UPDATE` arrives via `add_event` (which admits it and passes
ingress validation — the ingress reads the `config` singleton, not any store),
the engine thread dispatches to `_on_config_update` and executes
`None.apply(event)` → `AttributeError`.

The live error policy (publish-and-continue) contains the crash, but the result
is: `add_event` returned `True` to the caller, then the update is silently
dropped with an internal error emitted per event — directly contradicting the
documented contract ("Degrades cleanly to no router / no layering… the
CONFIG_UPDATE route stays the empty slot", live_trading_system.py:1470-1471;
route_registrar.py:98-134).

**Fix:** Only install the route when a consumer exists.

```python
# route_registrar.py install()
if self._config_router is not None:
    routes[EventType.CONFIG_UPDATE] = [self._on_config_update]
```

Unrouted CONFIG_UPDATE then hits the existing `NotImplementedError` guard in
`_dispatch` (no silent drop), or — preferably — reject CONFIG_UPDATE at
`add_event` when `self._config_router is None` so the caller gets a truthful
`False`.

### [RESOLVED] CR-02: venue-scope fee/slippage value is persisted with NO validation before the validating push — poisons `VenueStore` and crashes the next boot

**File:** `itrader/trading_system/config_router.py:284-309`; boot-crash mechanism `itrader/trading_system/live_trading_system.py:1188-1210`

**Issue:** Every other scope dry-validates the value on a throwaway copy BEFORE
persisting (`_dry_validate_setattr` for system, `model_copy()`+`setattr` for
order, `PortfolioConfig.model_validate(...)` for portfolio). `_apply_venue` does
**not**: for `fee_model` / `slippage_model` it writes the raw value straight into
the persisted row and only validates later, inside the post-persist push:

```python
config[key] = value                                    # no validation
self._persist(lambda: self._venue_store.upsert(venue_name, config, enabled, now))  # PERSISTED
if key in _VENUE_FEE_SLIPPAGE_KEYS:
    self._execution_handler.update_config({key: value})   # <-- first & only validation
```

`execution_handler.update_config` → `SimulatedExchange.update_config`
(deep_merge → `model_validate` → **raises `ConfigurationError`**) is where an
invalid value is caught (execution_handler.py:86-101). By then the bad value is
already durably in `VenueStore`. This breaks the stated D-15
validate→persist→apply ordering for the venue scope (persist-before-validate),
and the raised `ConfigurationError` is NOT a `_RejectedUpdate`, so it escapes
`ConfigRouter.apply()`'s `except _RejectedUpdate` entirely (no `last_error`, no
deduped WARNING) — it just surfaces as an unhandled dispatch error.

Worse: on the next restart, `_layer_persisted_overrides` re-reads every
`VenueStore` row and re-pushes `fee_model`/`slippage_model`
(live_trading_system.py:1188-1197). That block only catches `SQLAlchemyError`
(`:1204`), so the re-raised `ConfigurationError` propagates out of
`_layer_persisted_overrides` → out of `build_live_system` → **the live system
fails to construct**. A single bad `venue:simulated fee_model=<garbage>` config
update (reachable in paper mode with a SQL spine — the venue-kind predicate
requires a simulated venue, which paper is) durably bricks the next boot.

**Fix:** Validate the venue value BEFORE persisting — mirror the other scopes by
dry-running `execution_handler.update_config` against a throwaway/rollback copy,
or model-validate the fee/slippage value against the exchange config model, and
raise `_RejectedUpdate(_REASON_VALIDATION_FAILED)` on failure so nothing is
persisted:

```python
if key in _VENUE_FEE_SLIPPAGE_KEYS:
    try:
        self._execution_handler.validate_config({key: value})  # dry, no apply
    except ConfigurationError as exc:
        raise _RejectedUpdate(_REASON_VALIDATION_FAILED) from exc
# ...then persist, then push
```

## Warnings

### [RESOLVED] WR-01: `enabled` is coerced with `bool(value)` — truthy strings like `"false"`/`"0"` become `True`

**File:** `itrader/trading_system/config_router.py:295-297`

**Issue:** The venue `enabled` flag is set via `enabled = bool(value)`. The
ingress check (`_validate_config_ingress`, live_trading_system.py:1068-1075)
returns `True` for the venue scope without any type check on the value, so a
JSON/string payload reaches the router unmodified. `bool("false")`,
`bool("0")`, and `bool("no")` all evaluate to `True`, silently enabling a venue
the caller intended to disable.

**Fix:** Reject non-bool `enabled` values at ingress (or coerce explicitly with a
strict parser). e.g. `if not isinstance(value, bool): raise _RejectedUpdate(...)`
in `_apply_venue`, and the matching structural check at ingress.

### [RESOLVED] WR-02: non-`_RejectedUpdate` store/read exceptions escape `ConfigRouter.apply()` instead of surfacing a deduped rejection

**File:** `itrader/trading_system/config_router.py:293` (venue `get`), `:328-331` (portfolio resolve)

**Issue:** `apply()` only wraps the persist WRITE in `_persist` (which maps any
exception to `_REASON_PERSIST_FAILED`). But `_apply_venue` calls
`self._venue_store.get(venue_name)` OUTSIDE that wrapper (`:293`), and
`_apply_portfolio` catches only `PortfolioNotFoundError` from
`get_portfolio(...)` (`:328-331`) — any other store/read exception (connection
loss, deserialization error) propagates out of `apply()` as a raw exception
rather than becoming a deduped WARNING `ErrorEvent` + `last_error`. This
undermines the D-16 "any rejection surfaces a deduped WARNING and applies nothing
live" contract and (combined with CR-02) contributes to unhandled dispatch
errors.

**Fix:** Route the venue `get` (and the portfolio resolution) through the same
reject-mapping guard, or broaden the `apply()` handler to convert unexpected
exceptions into a surfaced rejection rather than an escape.

### [RESOLVED] WR-03: restart layering catches only `SQLAlchemyError`, so a config-push validation error during boot crashes `build_live_system`

**File:** `itrader/trading_system/live_trading_system.py:1176-1210`

**Issue:** `_layer_persisted_overrides` re-applies persisted config on boot by
calling `order_handler.update_config(...)`, `execution_handler.update_config(...)`,
and `portfolio.update_config(...)`. These pushes can raise `ConfigurationError`
/ `pydantic.ValidationError` (not just `SQLAlchemyError`) if a stored value is
no longer valid (schema evolution, model-field tightening, or a poisoned row per
CR-02). The single `except SQLAlchemyError` (`:1204`) does not cover those, so a
bad persisted value turns boot into a hard failure instead of a degrade-clean
skip. The docstring's "degrade-clean" promise only holds for a missing schema,
not for a present-but-invalid row.

**Fix:** Broaden the boot-layering guard to also swallow-and-log config
validation/apply errors (per-scope, so one bad scope does not abort the others),
consistent with the best-effort restart-restore intent.

### [RESOLVED] WR-04: ingress `_validate_config_ingress` reads the mutable `config` singleton from the caller thread while the engine thread mutates it

**File:** `itrader/trading_system/live_trading_system.py:1024-1106`

**Issue:** `add_event` runs on the external/web caller thread and
`_validate_config_ingress` does `sub_model.model_copy()` + `setattr` on the live
`config` sub-models, while the engine thread's `ConfigRouter` performs
`setattr` on the same sub-models. The design's single-writer/single-reader
guarantee (config_router.py:56-57) covers the engine thread only; this ingress
read is a genuine cross-thread access of the mutable overlay with no
synchronization. Under CPython/GIL a torn/stale read is the likely worst case
(not corruption), and the router re-validates behind it, so impact is low — but
it is an undocumented concurrency seam that should be acknowledged or guarded.

**Fix:** Validate against a value-level check that does not read the shared live
model (e.g. dry-validate against a fresh default sub-model instance of the same
type, or take the engine's config lock), so ingress never races the writer.

---

_Reviewed: 2026-07-16T11:37:16Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_

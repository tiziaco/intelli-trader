---
phase: 09-runtime-config-platform
source: 09-REVIEW.md
fixed_at: 2026-07-16
status: complete
fixed: 6
skipped: 0
iterations: 1
method: gsd-executor custom fix pass (not the stock gsd-code-fixer) — chosen so the pass could also add regression tests and perform the WR-04 reachability determination
---

# Phase 09 — Code Review Fix Report

All **6** findings from `09-REVIEW.md` (2 critical + 4 warning) were fixed and regression-tested.
Each fix committed atomically; all gates independently re-run green afterward (oracle byte-exact
`46189.87730727451` / 134, OKX inertness, Alembic single-head + parity, full suite **2305 passed /
6 skipped** (+8 new tests), `mypy --strict` clean over 261 files). `09-REVIEW.md` frontmatter set to
`status: resolved` with each finding header tagged `[RESOLVED]`.

## Findings fixed

| ID | Sev | Fix | Commit | Regression test |
|----|-----|-----|--------|-----------------|
| CR-01 | critical | `LiveRouteRegistrar.install()` now installs the `CONFIG_UPDATE` route only when `_config_router is not None` (else leaves the pre-declared empty slot); `add_event` rejects `CONFIG_UPDATE` fail-closed when no durable router is wired; `_on_config_update` gained a defense-in-depth `None`-guard. Honors the documented "no SQL spine ⇒ empty slot / degrade cleanly" contract. | `6dfa0fe1` | in-memory-live `add_event(ConfigUpdateEvent)` → clean reject (no `AttributeError`, no false-`True`); route stays empty slot |
| CR-02 | critical | Added a `validate_config` dry twin to `ExecutionHandler` + `SimulatedExchange` (deep_merge → `model_validate`, no swap). `_apply_venue` now dry-validates fee/slippage via `execution_handler.validate_config(...)` **before** `_persist`, converting `ConfigurationError` → `_RejectedUpdate(validation-failed)`. Restores validate→persist→apply→push for the venue scope; `VenueStore` can no longer be poisoned. | `ad908542` | bad venue fee/slippage value → rejected before persist (`VenueStore` not written) + valid-path still applies |
| WR-01 | warning | Replaced `enabled = bool(value)` truthy-string coercion with a strict `isinstance(value, bool)` guard (non-bool → `_RejectedUpdate(validation-failed)`), enforced at both `_apply_venue` and the `add_event` ingress. | `ad908542` | non-bool `enabled` (e.g. `"false"`) → rejected; real bool → applies |
| WR-02 | warning | `ConfigRouter.apply()` now catches the known escaping types `(SQLAlchemyError, ConfigurationError, pydantic.ValidationError)` and converts them to a deduped WARNING rejection (`apply-failed`) instead of escaping to publish-and-continue. Not a bare `except Exception`. | `ad908542` | store/read error surfaced as a deduped WARNING (not an engine-boundary error) |
| WR-03 | warning | `_layer_persisted_overrides` boot-layering broadened from `SQLAlchemyError`-only to a per-scope `(SQLAlchemyError, ConfigurationError, pydantic.ValidationError, ValueError)` degrade-clean guard — an invalid persisted override is logged+skipped (one bad scope never aborts the others) instead of crashing `build_live_system`. | `4f909e96` | invalid persisted override degrades clean; a sibling scope still applies |
| WR-04 | warning | **Confirmed real (not a non-finding):** ingress `_dry_validate_config_ingress` was reading the live mutable `config` singleton via `model_copy()` on the caller thread (cross-thread read of the single-writer overlay). Now dry-validates against a **fresh default instance** of the same sub-model type (`model_cls()`); the `from itrader import config` read was removed from the ingress path. Per-field `validate_assignment` makes this an identical validator with no cross-thread access. | `6dfa0fe1` | covered by the CONFIG_UPDATE ingress rejection tests (structure-only validation) |

## Commits

- `ad908542` — fix(09): CR-02/WR-01/WR-02 — ConfigRouter validate-before-persist venue scope
- `6dfa0fe1` — fix(09): CR-01/WR-04 — fail-closed CONFIG_UPDATE ingress + race-free dry-validate
- `4f909e96` — fix(09): WR-03 — per-scope degrade-clean boot config layering
- `b18cffc0` — test(09): regression tests for Phase-9 review findings
- `10078011` — docs(09): mark 09-REVIEW findings resolved (CR-01/CR-02 + WR-01..04)

## Files changed

`itrader/trading_system/config_router.py`, `itrader/trading_system/route_registrar.py`,
`itrader/trading_system/live_trading_system.py`, `itrader/execution_handler/execution_handler.py`,
`itrader/execution_handler/exchanges/simulated.py`, and the three
`tests/*/test_config_*.py` regression files.

## Coverage gap addressed

These blockers survived plan-time execution + goal verification because no test drove (a) an
in-memory-live config update or (b) a bad venue fee/slippage value. The 8 regression tests above
close that gap — each fails pre-fix and passes post-fix.

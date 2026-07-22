---
title: Per-portfolio quarantine — replace the blunt global halt with per-portfolio isolation
created: 2026-07-22
source: v1.8 Phase 11 — deferred from plan 11-10 (owner decision)
severity: enhancement
resolves_phase: null
blocked_on: auth/principal layer (operator-only release) — FastAPI application layer, future milestone
---

## Why this is deferred, not dropped

No requirement demands it. `grep -i quarantine .planning/REQUIREMENTS.md` returns nothing. MPORT-02
(distinct-account invariant) is delivered by 11-08; MPORT-05 (`PortfolioSpec.account_id` +
per-portfolio reconcile) by 11-05 and 11-09. The quarantine was an enhancement layered on top: turn
the blunt global halt into per-portfolio isolation so one drifted account doesn't ground the whole
desk. Multi-portfolio-live works and is SAFE without it — the existing global arm stays untouched.

## What stays in place (the safety arm — DO NOT weaken when building this)

The engine is protected today by an unconditional structural refusal:
- `reconciliation_coordinator.py:_run_session_baseline_guard` scans every portfolio/symbol at
  startup and, on ANY unexplained `engine_qty` vs `venue_qty` residual, calls
  `self._halt(HaltReason.BASELINE_RESIDUAL.value)` (currently ~:334).
- `live_trading_system.py:842-849` then REFUSES to spawn the processing thread while halted.

Result today: one drifted account halts the whole engine. Blunt but safe. **This mechanism must
survive** — building the quarantine must not delete the `:842` refusal or the `:334` halt without a
proven, wired replacement, or the engine would trade a drifted account with a green suite (the exact
safety downgrade a 2026-07-22 audit caught in the original 11-10 draft).

## The design (owner chose "keep a global arm alongside")

The residual scan already returns a per-portfolio `List[BaselineResidual]`, each tagged with
`portfolio_id`/`account_id` (11-09 made it complete precisely for this). So the one-vs-all decision
is cheap — the data is already there:

    drifted = { r.portfolio_id for r in residuals }
    active  = { p.portfolio_id for venue-truth active portfolios }
    if drifted == active:  global halt        # shared fault (venue/clock/snapshot) — everyone drifted
    else:                  quarantine each     # isolated — one account's problem

Seven accounts don't independently develop unexplained exposure at the same instant; an all-accounts
residual is a shared-fault signal and must still halt globally. Only the ISOLATED case gets the
gentler per-portfolio path.

## What must be BUILT (none of it exists — grep quarantine in safety/ + admission/ returns 0)

1. **Quarantine state** on `SafetyController` — a per-portfolio set beside the existing global scalars
   (`safety_controller.py:140-149`), under the same `_status_lock`.
2. **The admission gate** — a one-clause guard in `AdmissionManager.process_signal`
   (`admission_manager.py:~176-235`, mirroring `_enforce_leaving_symbol_admission`) that REFUSES a
   new-entry order from a quarantined portfolio.
3. **THE WIRING GAP (the hard part).** `AdmissionManager` is constructed inside
   `OrderManager`/`OrderHandler` at `compose_engine` time (`live_trading_system.py:~1776`), but
   `SafetyController` is built ~400 lines later (`~:2177`). The quarantine predicate has no path to
   the gate today. Building this needs EITHER moving `SafetyController` construction before
   `compose_engine` and injecting a narrow read through `compose.py` → `order_handler.py` →
   `order_manager.py` → `admission_manager.py` (constructor injection, honours no-lazy-init), OR a
   minimal shared holder created before both. `compose.py`, `order_handler.py`, `order_manager.py`
   are the files a real build touches — none was in 11-10's scope, which is why it was deferred.
   **Prove it end-to-end**: drive a real `build_live_system`, quarantine a portfolio, enqueue a
   SignalEvent for it, assert NO OrderEvent is emitted (a unit test on a hand-built AdmissionManager
   proves nothing — that is the inert-deliverable trap this phase hit repeatedly).
4. **The coordinator swap** — replace ONLY the `self._halt(BASELINE_RESIDUAL)` call at the isolated
   branch with a per-portfolio quarantine callable injected like `halt` is. `self._halt` is ALSO
   handed to `VenueReconciler` as `halt_signal` for `RECONCILIATION_UNRESOLVED` (a genuinely global
   condition) — do NOT swap that. Signatures differ: `halt` is `Callable[[str], None]`, a quarantine
   callable is `(portfolio_id, reason, at)`.
5. **Operator release** — BLOCKED. A real "operator-only" release needs a principal/auth concept the
   codebase does not have. `add_event` authenticates nothing (`:1084-1113`); adding a release verb to
   its `_EXTERNALLY_ADMISSIBLE` allowlist WIDENS the surface (anyone who can send a SIGNAL could
   release), so it does NOT mitigate T-11-51 "unauthorized release". Until the FastAPI application
   layer exists, either expose release as a facade method like `reset_halt()`
   (`safety_controller.py:222`) — no external ingress — or wait. Do not put it on the ingress
   allowlist and call it operator-only.
6. **Read-model surface** — a `quarantined_portfolios` entry in `get_status()` mirroring the existing
   `_quarantined_strategies` three-site pattern (decl / snapshot / rehydrate). `str()` the
   `PortfolioId` (it is a `uuid.UUID` NewType) for JSON.

## Related deferred item — the RTCFG-06 venue-UID mismatch read-model surface

11-04 shipped the ALERT half of the D-04 venue-UID-mismatch surfacing and left the READ-MODEL half
(the `state.venue_uid_mismatch` KV write) explicitly unclaimed. It was going to ride into 11-10
"beside the quarantine surface" — but they are two DIFFERENT surfaces (the KV sink is
`SystemStore.upsert("state.*")` at `safety_controller.py:~505`; the quarantine list is the in-memory
`get_status()` dict) and it needs its own composition wiring (`system_store` threaded through
`venue_uid_guard.assert_venue_uid` → `VenueLifecycle` → `assemble_venue` → the composition root).
Same class as the quarantine (per-portfolio safety observability, needs composition wiring,
observe-only) — deferred with it. 11-04's must_have was updated to point here rather than at 11-10.

## Test enforcement (loud gates that will break and must be updated, not worked around)

- `tests/unit/trading_system/test_add_event_admission_guard.py:106` asserts the ingress allowlist
  frozenset EXACTLY — adding a release type breaks it.
- `tests/unit/events/test_dispatch_registry.py:116` asserts `set(routes) == set(EventType)` — a new
  CONTROL enum member forces a base-literal slot in `full_event_handler.py`, and a MISSING registrar
  entry then dispatches to `[]` SILENTLY (a no-op, not the promised raise). Gate the route explicitly.

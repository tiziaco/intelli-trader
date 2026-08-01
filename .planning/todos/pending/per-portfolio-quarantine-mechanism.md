---
title: Per-portfolio quarantine — replace the blunt global halt with per-portfolio isolation
created: 2026-07-22
updated: 2026-07-31
source: v1.8 Phase 11 — deferred from plan 11-10 (owner decision)
severity: enhancement
resolves_phase: null
blocked_on: auth/principal layer (operator-only release) — FastAPI application layer, future milestone
---

> **2026-07-31 refresh.** Every file/line citation below was re-verified against the v1.81 tree,
> where the live composition root split into `trading_system/live/build.py` + `system.py` and the
> mode-blind wiring seam became `trading_system/graph.py::build_handler_graph`. The design is
> UNCHANGED — only the coordinates moved, plus item 6, whose precedent was deleted.

## Why this is deferred, not dropped

No requirement demands it. `grep -i quarantine .planning/REQUIREMENTS.md` returns nothing. MPORT-02
(distinct-account invariant) is delivered by 11-08; MPORT-05 (`PortfolioSpec.account_id` +
per-portfolio reconcile) by 11-05 and 11-09. The quarantine was an enhancement layered on top: turn
the blunt global halt into per-portfolio isolation so one drifted account doesn't ground the whole
desk. Multi-portfolio-live works and is SAFE without it — the existing global arm stays untouched.

## What stays in place (the safety arm — DO NOT weaken when building this)

The engine is protected today by an unconditional structural refusal:
- `reconciliation_coordinator.py:_run_session_baseline_guard` (`:182`) scans every
  portfolio/symbol at startup and, on ANY unexplained `engine_qty` vs `venue_qty` residual, calls
  `self._halt(HaltReason.BASELINE_RESIDUAL.value)` (`:269`).
- `trading_system/live/system.py::start` then REFUSES to spawn the processing thread while halted
  (`if self._safety.is_halted():` at `:565`).

Result today: one drifted account halts the whole engine. Blunt but safe. **This mechanism must
survive** — building the quarantine must not delete the `start()` refusal or the coordinator halt
without a proven, wired replacement, or the engine would trade a drifted account with a green suite
(the exact safety downgrade a 2026-07-22 audit caught in the original 11-10 draft).

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
   (`safety_controller.py:96-103` — `_status`/`_status_lock`/`_last_error`/`_halt_reason`/
   `_submission_paused`/`_paused_reason`), under the same `_status_lock`.
2. **The admission gate** — a one-clause guard in `AdmissionManager.process_signal`
   (`admission_manager.py:142`, mirroring `_enforce_leaving_symbol_admission` at `:430`, which
   `process_signal` already calls at `:183`) that REFUSES a new-entry order from a quarantined
   portfolio.
3. **THE WIRING GAP — SEAM ALREADY DESIGNED (2026-07-22, re-verified 2026-07-31).** The v1.81 split
   moved the coordinates but not the constraint. Do NOT try to move `SafetyController` earlier: it is
   built at `live/build.py:304`, AFTER `build_handler_graph` at `:286`, because its
   `dispatch_fn=lambda ev: engine.event_handler._dispatch(ev)` closes over the `event_handler` the
   graph produces — moving it is a dead end. The seam that works:
   create a shared `quarantined: set[PortfolioId] = set()` in `build_live_system` BEFORE the graph
   call, right next to `bus = PriorityEventBus()` (`live/build.py:214`) — this is the exact pattern
   `bus` and the root-owned `exchange_registry` already use (the registry is likewise held BY
   REFERENCE so `bring_online` can write into it). Then:
     - pass a READ PREDICATE (`lambda pid: pid in quarantined`) into `build_handler_graph(...,
       quarantine_read=...)` → `OrderHandler` → `OrderManager` → `AdmissionManager` as a REAL
       constructor arg (`graph.py:84` already takes optional kwargs — `results_store`, `alert_sink`,
       `system_store`, `error_policy`, `strategy_catalog` — so this is idiomatic);
     - pass the SET ITSELF into `SafetyController(..., quarantine=quarantined)` as its write-target
       (its `quarantine_portfolio`/`release` methods mutate it).
   Single source of truth: ONE set, `SafetyController` writes, `AdmissionManager` reads through the
   predicate. No reordering, NO new class, and NO None-then-assign (both constructors receive a real
   object — the owner explicitly rejected the late-bind/None pattern).
   **Mode-blindness caveat (new in v1.81):** `build_handler_graph` is the SHARED seam — the backtest
   root calls it too. A new kwarg must default to a no-quarantine predicate so the backtest path
   stays byte-exact and carries no live-only concept.
   Files a real build touches: `live/build.py`, `graph.py`, `order_handler.py`, `order_manager.py`,
   `admission_manager.py`, `safety_controller.py` — none was in 11-10's scope, which is why it was
   deferred.
   **Prove it end-to-end**: drive a real `build_live_system`, quarantine a portfolio, enqueue a
   SignalEvent for it, assert NO OrderEvent is emitted (a unit test on a hand-built AdmissionManager
   proves nothing — that is the inert-deliverable trap this phase hit repeatedly).
4. **The coordinator swap** — replace ONLY the `self._halt(BASELINE_RESIDUAL)` call at the isolated
   branch with a per-portfolio quarantine callable injected like `halt` is. `self._halt` is ALSO
   handed to `VenueReconciler` as `halt_signal` for `RECONCILIATION_UNRESOLVED` (a genuinely global
   condition) — do NOT swap that. Signatures differ: `halt` is `Callable[[str], None]`, a quarantine
   callable is `(portfolio_id, reason, at)`.
5. **Operator release** — BLOCKED. A real "operator-only" release needs a principal/auth concept the
   codebase does not have. `add_event` authenticates nothing (`live/system.py:704`, allowlist at
   `:49`); adding a release verb to its `_EXTERNALLY_ADMISSIBLE` allowlist WIDENS the surface (anyone
   who can send a SIGNAL could release), so it does NOT mitigate T-11-51 "unauthorized release".
   Until the FastAPI application layer exists, either expose release as a facade method like
   `reset_halt()` (`safety_controller.py:158`) — no external ingress — or wait. Do not put it on the
   ingress allowlist and call it operator-only.
6. **Read-model surface — THE PRECEDENT THIS CITED IS GONE (2026-07-31).** It used to say "mirror the
   `_quarantined_strategies` three-site pattern (decl / snapshot / rehydrate)". That pattern was
   DELETED: the facade held strategy-domain state it never read, and the strategy domain now owns its
   own answer (`StrategiesHandler.get_strategies_status()`, `strategy_handler/status.py`) exactly as
   the venue domain owns `VenueAccountManager.get_accounts_status()`. `get_status()` is
   engine-operational facts only — do NOT re-add a domain list to it.
   The rule to follow instead: **the read surface lives with the owner of the state.** Item 1 puts
   the set on `SafetyController`, which is a SAFETY-PLANE fact, not portfolio-domain state — so it
   belongs in `status_snapshot()` (`safety_controller.py:196`) and reaches `get_status()` through the
   same delegation `halt_reason` / `paused` already use. That is legitimate and is NOT the pattern
   that was removed: the facade relays nothing it owns, it reads through to the owner.
   If the state ends up owned by the portfolio domain instead, give `PortfolioHandler` a
   `get_portfolios_status()` and model it on `AccountStatus`/`StrategyStatus` — raw facts plus a
   derived `state`, refusing to construct the combination that names nothing.
   Either way `str()` the `PortfolioId` (a `uuid.UUID` NewType) at the JSON edge.

## Related deferred item — the RTCFG-06 venue-UID mismatch read-model surface

11-04 shipped the ALERT half of the D-04 venue-UID-mismatch surfacing and left the READ-MODEL half
(the `state.venue_uid_mismatch` KV write) explicitly unclaimed. It was going to ride into 11-10
"beside the quarantine surface" — but they are two DIFFERENT surfaces (the KV sink is
`SystemStore.upsert("state.*")` at `safety_controller.py:415`; the quarantine list is the in-memory
status dict) and it needs its own composition wiring (`system_store` threaded through
`venue_uid_guard.assert_venue_uid` → `VenueLifecycle` → `assemble_venue` → the composition root).
Same class as the quarantine (per-portfolio safety observability, needs composition wiring,
observe-only) — deferred with it. 11-04's must_have was updated to point here rather than at 11-10.

## Test enforcement (loud gates that will break and must be updated, not worked around)

- `tests/unit/trading_system/test_add_event_admission_guard.py:109` asserts the ingress allowlist
  frozenset EXACTLY — adding a release type breaks it.
- `tests/unit/events/test_dispatch_registry.py:116` asserts `set(routes) == set(EventType)` — a new
  CONTROL enum member forces a base-literal slot in `full_event_handler.py`, and a MISSING registrar
  entry then dispatches to `[]` SILENTLY (a no-op, not the promised raise). Gate the route explicitly.

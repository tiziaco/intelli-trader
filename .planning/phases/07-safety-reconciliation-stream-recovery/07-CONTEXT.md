# Phase 7: Safety + Reconciliation + Stream Recovery - Context

**Gathered:** 2026-07-14
**Status:** Ready for planning

<domain>
## Phase Boundary

Extract the live-safety machinery out of the `LiveTradingSystem` God object into three focused,
independently-testable collaborators, convert connector flag side-channels into CONTROL events, and
add a net-new pre-trade throttle. Delivers (SAFE-01..06):

- **`SafetyController`** — pure state machine (no venue I/O): status latch (`VALID_STATUS_TRANSITIONS`,
  single `update_status`, `force=` reserved for `reset_halt`), `halt(reason)` (winner-only → CRITICAL
  `ErrorEvent` → durable `HaltRecordStore.record_halt`), `pause_submission`/`resume_submission` + the
  bounded deferred-protective queue, the dispatch gate (`gate_and_dispatch`), and
  `check_durable_halt_on_start()` (runs first, before any venue I/O).
- **`StreamRecoveryHandler`** — reconnect resume I/O (catch-up missed fills + account snapshot on the
  engine thread + all-streams-healthy gate → `resume_submission`); CF-2 `backfill_on_resume` lands
  loop-native (connector loop via the reconnect callback), never a second engine-thread ring writer.
- **`ReconciliationCoordinator`** — startup sequence (rehydrate → venue reconcile for venue-truth
  accounts → baseline guard), keyed on account *kind* (not `exchange=='okx'`); CF-7 guards the bare
  `str(matched["id"])` with a typed fail-loud error.
- **CONTROL routing** — connector stream up/down + fatal arrive as `StreamStateEvent` /
  `ConnectorFatalEvent` on the engine thread; the `_pending_stream_resume`/`_pending_connector_halt`
  flag side-channel is **deleted**.
- **SAFE-06 pre-trade throttle** — submit-rate + max-notional-per-order caps that reject risk-increasing
  order flow *before* submission.

**Live-only, backtest-dark.** The backtest oracle stays byte-exact (`134 / 46189.87730727451`) and
`test_okx_inertness.py` stays green — held as per-phase gates, not re-decided here.

**Architecture is locked by the design spec (§11).** This discussion covered only the genuinely open
implementation decisions (SAFE-06 throttle design + a few safety-policy edges + module placement).

</domain>

<decisions>
## Implementation Decisions

### SAFE-06 Pre-Trade Throttle
- **D-01 (Layer):** The throttle is an **operator-defined risk backstop** (defense-in-depth against a
  runaway strategy / bad loop / fat-finger), NOT a venue-compliance tool. Caps come from **config
  (owner-set)**, not derived from the exchange. The exchange's own API rate limits are a separate,
  already-solved concern at the connector (ccxt built-in token-bucket, `connectors/okx.py`, RES-01) —
  the throttle does not touch that layer.
- **D-02 (Breach action):** On a cap breach, **reject that order** → emit `FillEvent(REFUSED)`; the rest
  of order flow continues. It is a pre-trade sibling of `EnhancedOrderValidator`, complementing CF-1's
  post-error breaker — NOT a pause and NOT a halt (a per-order risk cap is not a systemic kill switch).
- **D-03 (Scope):** Caps are **global engine-wide** (one set across the engine). Per-`account_id` keying
  is a **shaped seam** for P11 multi-portfolio-live, not built now.
- **D-04 (Rate algorithm):** **Sliding-window count** — N orders per rolling T seconds off the injected
  clock. Chosen over token bucket / fixed window for determinism, isolation-testability, and no refill
  math (fits the pure-state-machine ethos; avoids conceptually duplicating the connector's token bucket).
- **D-05 (Protective bypass — CRITICAL for correctness):** A **single shared `OrderRiskRole` classifier**
  (CANCEL / PROTECTIVE / ENTRY) is reused by BOTH the SafetyController dispatch gate AND the throttle —
  one source of truth, no duplicate "what counts as protective" logic. Reuses the existing gate
  predicate (`live_trading_system.py:735–765`): CANCEL command → risk-reducing; PROTECTIVE →
  bracket child (`parent_order_id` set); ENTRY → parentless NEW (+ raw SIGNAL). The throttle **meters
  ENTRY only**; **CANCEL and PROTECTIVE orders bypass unconditionally and are NOT counted** toward the
  sliding window. This makes D-02's "reject that order" safe by construction — the throttle physically
  cannot touch a stop, bracket child, or cancel.
- **D-06 (Placement seam):** The throttle fires at the **pre-submit boundary** (ahead of venue send, per
  SAFE-06 "before submission"), invoked by the runner, sharing the D-05 risk-role classifier with the
  gate. NOT folded into `SafetyController.gate_and_dispatch` (keeps the pure state machine free of
  order-notional inspection), NOT in OrderHandler admission.
- **D-07 (Default caps):** Ship **10 orders / 10s window + $25,000 max-notional-per-order**, ON by
  default (conservative backstop, protects from first live run). Explicitly expected to need tuning per
  account equity — runtime-mutable in P9. *(Note: tighter than a purely non-blocking backstop; may block
  a legitimately large entry — flag during live validation.)*
- **D-08 (Modify/replace handling):** Throttle meters **ENTRY only** — parentless new-risk submissions.
  MODIFY/REPLACE on protective children (e.g. trailing-stop adjustments) already bypass via the
  PROTECTIVE role, so no notional-delta computation is needed in P7. Metering risk-increasing modifies is
  a possible later refinement (out of scope now).
- **D-09 (Breach observability):** On rejection → `FillEvent(REFUSED)` **+** increment a **breach counter**
  exposed in the read-model for P9's stats/state UI **+** emit a **WARNING-severity `ErrorEvent`**,
  **de-duped / rate-limited** so a runaway burst cannot flood the ERROR route.
- **D-10 (Notional reference price):** Max-notional check uses the order's **limit price when present,
  else the last mark / best available from the feed**. Measures a mispriced limit at its own price
  (catches fat-finger); market/stop orders with no limit fall back to mark.

### Safety-Policy Edges (live-only; no oracle risk)
- **D-11 (Deferred-protective overflow):** The pause-window protective-order queue
  (`deque(maxlen=_DEFERRED_PROTECTIVE_REPLAY_MAX=1000)`) currently **drops the oldest** on overflow —
  a silent, potentially position-un-protecting failure. **Change to escalate to HALT + CRITICAL alert on
  overflow.** Overflow of a 1000-deep queue means something is deeply wrong; convert the near-unreachable
  silent drop into a loud, latched stop. New behavior; needs one test.
- **D-12 (Stream-recovery resume failure):** On snapshot/catch-up-fills failure during reconnect resume,
  **keep the existing behavior — stay paused, retry on the next stream-up signal** (extract as-is).
  Staying paused is already safe (no new-risk submission while unhealthy); the next reconnect re-drives
  recovery. No failure-counter / halt-escalation added in P7.

### Config & Module Structure
- **D-13 (Config home):** Throttle/safety config lives in a **new `config/safety.py`**
  (`ThrottleSettings`/`SafetySettings`), matching the flat one-domain-per-file config convention
  (`stream.py`, `order.py`, `sql.py`).
- **D-14 (Mutability posture):** P7 ships **working static config caps + shapes the P9 mutation seam** (a
  settable caps object the P9 allowlist can later swap). P7 does **NOT** wire runtime `ConfigUpdateEvent`
  mutation — that is P9's job (RTCFG). Matches the SAFE-06 requirement split.
- **D-15 (Safety-component module home):** The safety trio + throttle live in a **new
  `trading_system/safety/` subpackage** (`safety_controller.py`, `stream_recovery_handler.py`,
  `pre_trade_throttle.py`). *Owner override of the recommended flat-modules option.* **Downstream
  awareness:** this is a *concern*-axis grouping; the intended future `trading_system/` **run-mode split**
  (`live/` + `backtest/` + shared root — see Deferred) is a *run-mode* axis. `safety/` is live-only, so
  when the split lands it will likely **nest under `live/`** (i.e. `live/safety/`) or dissolve into
  `live/`. Plan `safety/` so that move is cheap.
- **D-16 (`OrderRiskRole` classifier home):** The `OrderRiskRole` **enum joins `OrderCommand` in
  `core/enums/`** (shared primitive, zero coupling); the `classify()` function travels with
  `SafetyController` (which owns the dispatch gate). Both gate and throttle import the one predicate.
- **D-17 (`ReconciliationCoordinator` home — settled, not contested):** Lands in
  `portfolio_handler/reconcile/` next to `venue_reconciler.py` + `drift.py` — it already owns
  `venue_reconciler.py` (CF-7) and iterates portfolios.

### Claude's Discretion
- Exact typed error class for CF-7's `str(matched["id"])` guard (spec says "typed fail-loud error").
- De-dup/rate-limit mechanism specifics for D-09's WARNING `ErrorEvent` (e.g. first-breach + transition,
  or a min interval).
- Precise sliding-window data structure (deque of timestamps vs ring) for D-04.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Design source (authoritative — architecture is locked here)
- `docs/superpowers/specs/2026-07-07-v1.8-live-system-refactor-design.md` §11 (11a–11e) — the
  `SafetyController` (pure state machine), durable halt & startup refusal (§11b), connector-handoff →
  CONTROL routes with the flag machinery deleted (§11c), `StreamRecoveryHandler` resume I/O (§11c),
  `ReconciliationCoordinator` (§11d), facade cleanup (§11e). Also §12 (ErrorPolicy/ErrorHandler — P8
  context) and §13c (`LiveRouteRegistrar` — P7/P9 add CONTROL entries).
- `docs/superpowers/specs/2026-07-07-v1.8-live-system-refactor-design.md` CF table — **CF-2**
  (`backfill_on_resume` loop-native), **CF-7** (guard `str(matched["id"])` at `venue_reconciler.py:411`),
  **CF-8** (typed `HaltReason` for `baseline-residual` — already in `core/enums/system.py`).

### Requirements & roadmap
- `.planning/REQUIREMENTS.md` — SAFE-01..06 (lines 190–217) + milestone-wide gates (§15).
- `.planning/ROADMAP.md` → "Phase 7: Safety + Reconciliation + Stream Recovery" (goal + 5 success
  criteria).

### Existing code the extraction pulls from
- `itrader/trading_system/live_trading_system.py` — source of `halt`/`pause_submission`/
  `resume_submission`/`_replay_deferred_protective`/`_update_status`/`check_durable_halt` + the dispatch
  gate (`_dispatch_live`, lines 735–765) + the flag side-channel to delete
  (`_pending_stream_resume`/`_pending_connector_halt`, ~lines 215–221, 600–720).
- `itrader/portfolio_handler/reconcile/venue_reconciler.py`, `drift.py` — the reconcile the coordinator
  wraps (CF-7 guard site).
- `itrader/core/enums/system.py` — `SystemStatus`, `VALID_STATUS_TRANSITIONS`, `HaltReason` (already
  carries `CONNECTOR_FATAL`/`RECONCILIATION_UNRESOLVED`/`DURABLE_HALT`/`DRIFT`/`BASELINE_RESIDUAL`).
- `itrader/core/enums/` (`OrderCommand`) — home for the new `OrderRiskRole` enum (D-16).
- `itrader/config/` (`stream.py`, `order.py`) — pattern for the new `config/safety.py` (D-13).
- `itrader/trading_system/` — `live_runner.py`, `route_registrar.py`, `error_policy.py`,
  `worker_supervisor.py` (collaborator conventions; the runner invokes the pre-submit throttle, D-06).

### Gates (must stay green — restated, not re-decided)
- `tests/integration/test_okx_inertness.py` — import inertness.
- `tests/integration/test_backtest_oracle.py` — byte-exact `134 / 46189.87730727451`.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- **Dispatch-gate risk classification** (`live_trading_system.py:735–765`) — already splits orders into
  CANCEL / PROTECTIVE (`parent_order_id` set) / ENTRY. Extract as the shared `OrderRiskRole` classifier
  (D-05/D-16); both the SafetyController gate and the throttle consume it.
- **Deferred-protective queue** — `deque(maxlen=_DEFERRED_PROTECTIVE_REPLAY_MAX=1000)` +
  `_replay_deferred_protective()` already implement the pause-window defer/replay; extract into
  `SafetyController`, changing only the overflow policy (D-11).
- **`HaltReason` enum** — vocabulary already complete (`CONNECTOR_FATAL`, `RECONCILIATION_UNRESOLVED`,
  `DURABLE_HALT`, `DRIFT`, `BASELINE_RESIDUAL`); no new members needed for P7.
- **`VenueReconciler` / `drift.py`** — the reconcile the coordinator orchestrates.

### Established Patterns
- **Flat one-module-per-collaborator** under `trading_system/` (P1–P6 convention). D-15 deliberately
  deviates for the `safety/` subpackage — flag the deviation + the future-nest note.
- **Flat one-domain-per-file** under `config/` — new `config/safety.py` follows it (D-13).
- **CONTROL events + `LiveRouteRegistrar`** (§13c) — P7 registers `STREAM_STATE`/`CONNECTOR_FATAL`
  routes declaratively through the existing registrar; list order = execution order.
- **Injected clock + seeded RNG determinism** — the sliding-window throttle (D-04) reads the injected
  clock, never wall clock directly.

### Integration Points
- Runner (`live_runner.py`) invokes the pre-submit throttle at the order→execution boundary (D-06).
- Connector reconnect/fatal callbacks emit CONTROL events onto the bus instead of flipping flags (§11c);
  routed on the engine thread to `SafetyController.pause_submission` / `StreamRecoveryHandler.on_reconnect`
  / `SafetyController.halt`.
- Breach counter (D-09) surfaces through the status/read-model consumed by P9's stats/state UI.

</code_context>

<specifics>
## Specific Ideas

- Owner's framing of the throttle as **YOUR risk caps, not the exchange's** — drove D-01/D-02 (reject the
  offending order rather than pause/queue for venue compliance).
- Owner explicitly chose the `trading_system/safety/` subpackage over flat modules (D-15), tied to a
  broader intent to split `trading_system/` by run-mode (see Deferred).

</specifics>

<deferred>
## Deferred Ideas

- **`trading_system/` run-mode split** — introduce `trading_system/live/` + `trading_system/backtest/`
  subpackages, leaving only genuinely shared modules (`compose.py`, `engine_context.py`, `system_spec.py`,
  `universe_wiring.py`, `error_policy.py`) in the root. Behavior-preserving mechanical code-motion with
  its own oracle/inertness/import-sweep gate — best as its own inserted phase (mirrors how 6.1 seam-cleanup
  worked), NOT folded into P7. When it lands, the P7 `safety/` subpackage (D-15) likely nests under `live/`.
  *Owner-stated direction; the module is "already giving problems."*
- **Per-`account_id` throttle caps** — the D-03 global caps grow a per-account keying seam for P11
  multi-portfolio-live.
- **Runtime mutation of throttle caps** — D-14 shapes the seam; P9 (RTCFG) wires `ConfigUpdateEvent` +
  allowlist to actually mutate caps at runtime.
- **Metering risk-increasing MODIFY/REPLACE** — D-08 defers notional-delta metering of modifies (rare in
  this system; protective modifies already bypass).
- **Stream-recovery halt-escalation** — D-12 keeps retry-on-reconnect; a bounded-failure → halt escalation
  could be revisited if persistent venue flapping proves a visibility gap.

</deferred>

---

*Phase: 7-Safety + Reconciliation + Stream Recovery*
*Context gathered: 2026-07-14*

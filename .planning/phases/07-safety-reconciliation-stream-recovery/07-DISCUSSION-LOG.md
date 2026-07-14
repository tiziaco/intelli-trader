# Phase 7: Safety + Reconciliation + Stream Recovery - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-07-14
**Phase:** 7-Safety + Reconciliation + Stream Recovery
**Areas discussed:** SAFE-06 throttle design, Deferred-protective overflow, Stream-recovery resume failure, Throttle config & mutability, Module structure

---

## SAFE-06 Throttle — Breach action

Prefaced by a clarification: caps are **owner-defined risk backstops**, NOT venue-compliance (the
exchange's own API limits are already handled at the connector's ccxt token-bucket).

| Option | Description | Selected |
|--------|-------------|----------|
| Reject that order | FillEvent(REFUSED), flow continues; pre-trade sibling of EnhancedOrderValidator | ✓ |
| Pause submission | Quiesce all order flow until window clears / operator resumes | |
| Halt | Latched HALTED freeze | |

**User's choice:** Reject that order
**Notes:** Because the caps are the owner's own risk envelope, a breach means one order misbehaved — reject it, don't treat it as systemic.

## SAFE-06 Throttle — Cap scope

| Option | Description | Selected |
|--------|-------------|----------|
| Global engine-wide | One set of caps; per-account seam for P11 | ✓ |
| Per-account_id | Independent caps per account (P11-aligned, more state now) | |
| Per-symbol | Caps per instrument | |

**User's choice:** Global engine-wide

## SAFE-06 Throttle — Rate algorithm

| Option | Description | Selected |
|--------|-------------|----------|
| Sliding-window count | N orders per rolling T seconds off injected clock | ✓ |
| Token bucket | Refill rate + burst (duplicates connector's bucket) | |
| Fixed window | Simplest; allows 2x boundary bursts | |

**User's choice:** Sliding-window count

## SAFE-06 Throttle — Protective bypass (architectural clarification, user-initiated)

User asked whether there's an architecturally-correct way to bypass the throttle for protective orders.
Answer: it is *required* — the existing dispatch gate already classifies CANCEL / PROTECTIVE / ENTRY;
reuse that single predicate. Throttle meters ENTRY only; CANCEL/PROTECTIVE bypass uncounted. Captured as
D-05.

## SAFE-06 Throttle — Default caps

| Option | Description | Selected |
|--------|-------------|----------|
| Shape now, numbers from research | Pin shape; research proposes numbers vs venue/equity | |
| 20 orders / 10s, $100k/order | Non-blocking backstop | |
| 10 orders / 10s, $25k/order | Tighter, small-account; may need tuning | ✓ |

**User's choice:** 10 orders / 10s, $25k/order
**Notes:** Tighter caps chosen; flagged as likely to need tuning against live account equity.

## SAFE-06 Throttle — Modify/replace handling

| Option | Description | Selected |
|--------|-------------|----------|
| ENTRY only | Meter parentless new-risk only; protective modifies bypass | ✓ |
| Meter risk-increasing modifies | Compute notional delta on MODIFY/REPLACE (more logic) | |

**User's choice:** ENTRY only

## SAFE-06 Throttle — Breach observability

| Option | Description | Selected |
|--------|-------------|----------|
| REFUSED + counter + de-duped WARNING | Counter for P9 UI + WARNING ErrorEvent, flood-guarded | ✓ |
| REFUSED + counter only | Counter for P9 UI, no event | |
| REFUSED + log only | Minimal | |

**User's choice:** REFUSED + breach counter + de-duped WARNING

## SAFE-06 Throttle — Notional reference price

| Option | Description | Selected |
|--------|-------------|----------|
| Limit price if present, else last mark | Measures a mispriced limit at its own price | ✓ |
| Always last mark | Uniform; understates a limit far from mark | |

**User's choice:** Limit price if present, else last mark

## SAFE-06 Throttle — Placement seam (resolved via the bypass clarification)

Pre-submit boundary (ahead of send), invoked by the runner, sharing the risk-role classifier with the
gate. Not folded into SafetyController.gate_and_dispatch; not in OrderHandler admission. Captured as D-06.

---

## Deferred-protective overflow

| Option | Description | Selected |
|--------|-------------|----------|
| Escalate to halt on overflow | Latch HALTED + CRITICAL vs silent drop-oldest (bound 1000) | ✓ |
| Keep drop-oldest (as-is) | Behavior-preserving; retains silent-drop risk | |
| Raise the bound | Moves the cliff; still silent | |

**User's choice:** Escalate to halt on overflow
**Notes:** Bound is `_DEFERRED_PROTECTIVE_REPLAY_MAX = 1000`; overflow is near-unreachable but the silent drop of a protective order is unacceptable, so make it loud.

---

## Stream-recovery resume failure

| Option | Description | Selected |
|--------|-------------|----------|
| Retry on next reconnect (as-is) | Stay paused (safe), re-drive on next stream-up | ✓ |
| Escalate to halt after N failures | Bounded retries → halt + CRITICAL (operator visibility) | |
| Operator-only resume after a failure | Most conservative; noisiest | |

**User's choice:** Retry on next reconnect (extract as-is)

---

## Throttle config & mutability

| Option | Description | Selected |
|--------|-------------|----------|
| New config/safety.py | Dedicated ThrottleSettings/SafetySettings, flat-domain convention | ✓ (home) |
| Fold into existing config | Mix into order.py/exchange.py | |
| Static caps + P9 seam shaped | Working static caps + settable seam; no runtime wiring in P7 | ✓ (posture) |
| Defer all config to P9 | Hardcode until P9 | |

**User's choice:** New `config/safety.py`; static caps + P9 mutation seam shaped

---

## Module structure

User raised that `trading_system/` is too big and is "already giving problems"; intends to add
`live/` + `backtest/` subpackages later, leaving shared in the root — and leaned toward a subpackage for
the safety trio. Claude pushed back: a `safety/` (concern axis) is orthogonal to the intended `live/`
(run-mode axis), and the P7 trio is live-only, so it would belong under a future `live/`. Recommended
either keeping P7 flat + doing the split as its own inserted phase (A, recommended), or bootstrapping
`trading_system/live/` now (B). User chose the concern subpackage anyway.

| Option | Description | Selected |
|--------|-------------|----------|
| Keep flat, split later as own phase | P7 flat now; run-mode split as its own inserted phase | |
| Bootstrap trading_system/live/ now | Create live/, land P7 there (partial migration) | |
| Concern subpackage trading_system/safety/ | Group the trio cohesively (concern axis) | ✓ |

**User's choice:** `trading_system/safety/` subpackage (owner override of recommendation)
**Notes:** Captured with a downstream note (D-15) that `safety/` will likely nest under `live/` when the run-mode split lands. The run-mode split is logged as a deferred idea.

## OrderRiskRole classifier home

| Option | Description | Selected |
|--------|-------------|----------|
| Enum in core/enums, classify() with the gate | Shared primitive + logic with primary consumer | ✓ |
| Standalone module next to components | Neutral home, one extra module | |
| In the order domain (order_handler/) | Order-semantics-pure, adds cross-domain import | |

**User's choice:** Enum in `core/enums/`, `classify()` with the gate

---

## Claude's Discretion

- CF-7 typed error class for the `str(matched["id"])` guard.
- De-dup/rate-limit mechanism for the D-09 WARNING ErrorEvent.
- Sliding-window data structure specifics (D-04).

## Deferred Ideas

- `trading_system/` run-mode split (`live/` + `backtest/` + shared root) as its own behavior-preserving
  inserted phase; `safety/` likely nests under `live/` then.
- Per-`account_id` throttle caps (P11 seam).
- Runtime mutation of throttle caps (P9 / RTCFG).
- Metering risk-increasing MODIFY/REPLACE.
- Stream-recovery halt-escalation (revisit if venue flapping proves a visibility gap).

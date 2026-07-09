---
status: scheduled
created: "2026-07-07"
source: Phase 05.1 (v1.7) code review finding WR-04 — surfaced in the v1.7 milestone-audit review-file reconciliation (2026-07-07)
tags: [live, halt, observability, operator, ui, halt-vocabulary, fastapi-control-plane]
resolves_phase: "P1"
folded_into: "v1.8 spec §18 — CF-8 (P1 core/enums HaltReason [CFG-05] + P7 SafetyController consumes it); renumbered post-P4-merge"
---

# Session-start baseline guard halts with an off-vocabulary reason `'baseline-residual'` (WR-04)

**Origin:** Phase 05.1 (v1.7 Live-Path Remediation) code review,
`.planning/phases/05.1-live-path-remediation/05.1-REVIEW.md` finding **WR-04**. Confirmed still OPEN
at HEAD during the v1.7 milestone-audit review reconciliation (2026-07-07); not tracked anywhere until
now (previously only recorded in `.planning/v1.7-MILESTONE-AUDIT.md` tech_debt, which archives at
milestone close).

## The gap

The session-start post-reconcile baseline guard halts with a free-string reason:

```python
self.halt('baseline-residual')   # itrader/trading_system/live_trading_system.py:810
```

`'baseline-residual'` is **not part of the halt vocabulary** — it is not enumerated in
`itrader/core/enums/system.py` (`:20-23`) and the `halt()` docstring (`live_trading_system.py:834-835`)
does not list it. Any operator/monitoring/UI layer that classifies halts by a known reason set will not
recognize this one (it falls into an "unknown/other" bucket). This exact string is what surfaced in the
05.1 CONF-B online-run capture (`.planning/debug/05.1-confb-2026-07-04.md`) when the guard halted on the
non-flat demo account — i.e. it is a real, reachable live-path halt reason.

## Why it is minor (and deferrable)

- **No data/correctness impact.** The guard halts correctly (freeze-in-place is the right fail-safe);
  only the *reason label* is off-vocabulary. Positions/cash/ledger are untouched.
- **Dark on the backtest oracle** — the baseline guard is live-only; the SMA_MACD spot oracle
  (134 / `46189.87730727451`) never constructs it.

## Why it should still be fixed

It becomes directly load-bearing for the **FastAPI application-layer / control-plane** (see
`.planning/` memory `fastapi-application-layer-plan`): a status/monitoring surface that renders or routes
on halt reason needs every reachable halt reason to be in a known, typed vocabulary — otherwise a
`baseline-residual` halt shows up as unclassified and an operator can't tell a benign non-flat-start halt
from a genuine drift/orphan halt.

## Fix sketch

Add `BASELINE_RESIDUAL` (or a `HaltReason` enum member / documented vocabulary entry) to
`itrader/core/enums/system.py`, thread it through `halt()` and its docstring, and update the
baseline-guard call site to use the typed reason. Add/extend a unit assertion that the guard's halt
reason is in the known vocabulary. Live-only change — backtest oracle stays byte-exact and inert.

**Related:** the other v1.7 halt-path hardening todos (now in `todos/completed/`):
`durable-halt-refusal-sequenced-late-wr01`, `blocking-halt-write-on-asyncio-loop-wr02`.

## Deferral decision (2026-07-07, v1.7 milestone close)

**Deferred to the next milestone by owner decision.** `live_trading_system.py` will be
**fully refactored** in the next milestone, and the halt-reason storage/vocabulary system reviewed
as part of that work. Fixing WR-04 in isolation now (a typed `HaltReason` enum threaded through
`halt()`) would be redone by that refactor. The cosmetic doc-only patch was explicitly rejected as
not addressing the real weakness (untyped free-string halt reasons). Owned by the next-milestone
`live_trading_system.py` refactor + the FastAPI control-plane vocabulary design
(`fastapi-application-layer-plan`). No pre-close action.

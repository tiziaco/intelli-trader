---
phase: 02-m2a-identity-money-determinism
plan: 07
subsystem: events / type-gate / oracle-test
status: CHECKPOINT (paused — owner gate)
tags: [frozen-events, mypy-strict, oracle-tolerance, M2-03, D-15]
requires: ["02-03", "02-04", "02-05", "02-06"]
provides:
  - "frozen/slots immutable hot-path events (M2-03, Pattern F)"
  - "D-15 oracle split: behavioral identity EXACT + numeric bounded-tolerant"
affects:
  - itrader/events_handler/event.py
  - test/test_integration/test_backtest_oracle.py
  - test/test_events/test_event_immutability.py
tech-stack:
  added: []
  patterns: ["@dataclass(frozen=True, slots=True) on immutable events", "identity-EXACT / numeric-TOLERANT oracle split"]
key-files:
  created:
    - test/test_events/test_event_immutability.py
  modified:
    - itrader/events_handler/event.py
    - test/test_integration/test_backtest_oracle.py
decisions:
  - "Freeze only genuinely-immutable events: PingEvent, BarEvent, PortfolioUpdateEvent, ScreenerEvent"
  - "OrderEvent left MUTABLE — price/quantity rewritten by MatchingEngine.modify (discovered at runtime)"
  - "SignalEvent + FillEvent left MUTABLE — documented downstream mutation"
  - "D-15 tolerance set to rtol=1e-6, atol=5e-2 (5 cents) — just above observed ~2.7e-2 M2a drift"
metrics:
  duration: ~25 min (partial — paused at checkpoint)
  completed: 2026-06-04
---

# Phase 2 Plan 7: Strict-Gate + Frozen-Events + Oracle-Gate Consolidation Summary

**One-liner:** Froze the genuinely-immutable hot-path events (`frozen=True/slots=True`) and split
the backtest oracle into behavioral-identity-EXACT + numeric-bounded-tolerant (D-15); paused at the
owner gate because Task 2 (`make typecheck` clean) exceeds the plan's stated "minimal surgical fixes"
scope and the Task 4 phase gate is owner-gated.

## Status: CHECKPOINT — 2 of 4 tasks complete, paused for owner decision

This plan is `autonomous: false`. Tasks 1 and 3 are complete and committed. Task 2 surfaced a
scope discrepancy (below) that is an architectural-scale decision (Rule 4) and must not be resolved
unilaterally; Task 4 is an explicit owner-gated phase-close checkpoint. Both are returned for owner
input.

## Completed Work

### Task 1 — frozen/slots immutable events (M2-03, Pattern F) ✅ (TDD)
- **RED** (`ffe2a3c`): added `test/test_events/test_event_immutability.py` asserting frozen behavior
  for the immutable events and continued-mutability for the mutable ones.
- **GREEN** (`227dab3`): applied `@dataclass(frozen=True, slots=True)` to **PingEvent, BarEvent,
  PortfolioUpdateEvent, ScreenerEvent**.
- **Left MUTABLE** (each verified against real run-path mutation):
  - `SignalEvent` — `verified` (order_validator) + `quantity` (order_manager) rewritten post-build (Pitfall 4, M3 #11 blocker).
  - `FillEvent` — `price`/`quantity` rewritten by `SimulatedExchange` after fee/slippage (simulated.py:226,229).
  - `OrderEvent` — **discovered at runtime** that `MatchingEngine.modify` rewrites `price`/`quantity`
    of a resting order (matching_engine.py:59-61). The initial GREEN froze OrderEvent and the
    execution suite caught the `FrozenInstanceError`; OrderEvent was reverted to mutable and the test
    contract updated to assert its mutability. This is the Pattern-F "defer ambiguous events" path.
- **M3 boundary respected:** no `event_id`/`uuid4` change (`event.py:6` untouched).
- **Verify:** `test/test_events -q` → 25 passed.

### Task 3 — D-15 oracle split (behavioral-EXACT + numeric-TOLERANT) ✅ (`e9af665`)
- Trade **identity** columns `entry_date, exit_date, side, pair` asserted `check_exact=True`
  (behavioral LAW). Equity **timestamp grid** asserted EXACT. Summary `final_cash`, `trade_count`,
  `final_equity` asserted EXACT.
- Numeric trade/equity columns + summary `total_realised_pnl` asserted within a bounded transitional
  tolerance, each inline-flagged `# D-15 transitional — removed + re-frozen EXACT at M2b (Phase 3 SC4)`.
- **Tolerance set empirically:** observed M2a Decimal drift maxed at **~2.732e-2** (equity
  `total_equity`/`positions_value`) and **2.685e-2** (trade `total_sold`); `total_realised_pnl` drifts
  **9.563e-3**. Chosen `rtol=1e-6, atol=5e-2` (5 cents) — just above worst-case observed, tight enough
  to catch a dollar-level money bug, loose enough for sub-cent float→Decimal quantization.
- **Golden CSVs NOT overwritten** — the numerical-oracle re-baseline (DEF-02-04-A) stays owner-gated
  (CLAUDE.md golden-master discipline; re-freeze is Phase 3 / M2b work).
- **Verify:** `test/test_integration/test_backtest_oracle.py -x` → 1 passed.

### Full suite
- `poetry run pytest -q` → **299 passed**. Behavioral oracle (134 trades, dates/sides/pairs,
  final equity 53229.75) unchanged.

## Deviations from Plan

### [Rule 1 — Bug avoided] OrderEvent is not immutable
- **Found during:** Task 1 GREEN (execution suite `test_matching_engine` failed with
  `FrozenInstanceError`).
- **Issue:** plan/Pattern-F listed OrderEvent as a freeze candidate; the matching engine's
  resting-order `modify` mutates `OrderEvent.price`/`quantity` in the real run path.
- **Fix:** OrderEvent left mutable; immutability test updated to `test_order_event_stays_mutable`.
- **Files:** `itrader/events_handler/event.py`, `test/test_events/test_event_immutability.py`.
- **Commit:** `227dab3`.

## CHECKPOINT — Owner Decision Required

### Task 2 (`make typecheck` clean) — SCOPE ESCALATION (Rule 4)

`make typecheck` currently reports **922 errors in 83 files**. The plan framed Task 2 as "minimal,
surgical residual type-annotation fixes … `event.py` is the only additional file expected." Reality
does not match that model:

| Bucket | Errors | In M2a D-05 scope? |
|--------|--------|--------------------|
| `[no-untyped-def]` (missing annotations) | 339 | mixed |
| `[no-untyped-call]` | 100 | mixed |
| `[assignment]` (`=None` non-Optional) | 101 | mixed |
| `my_strategies/*` (OUT-of-band, separate repo) | 197 | **NO** (STATE.md "OUT") |
| `legacy_config.py` | 15 | likely NO |
| `postgresql_storage.py` (D-sql sibling) | 16 | likely NO |
| `price_handler` data_provider/exchange/live | 56 | partial (csv feed only is in-scope) |

Even a single confirmed in-scope file, `event.py`, carries **39** pure annotation-debt errors
(`__str__/__repr__` missing `-> str`, dunder param annotations, `dict`→`dict[str, X]`, `=None`→`Optional`,
`-> float` paths that `return None`). The in-scope surface spans ~50+ files and hundreds of edits.
This is the pre-existing untyped-def debt that **Plan 02-05 explicitly deferred to "Plan 07"**
(STATE.md: "mypy gate 316->906 is unmasked pre-existing untyped-def debt (not regression)").

This is an architectural-scale decision, not a surgical fix, and the plan is owner-gated. I did **not**:
- hand-annotate 50–83 files unilaterally (large diff, real regression risk on a behavior-preserving
  milestone), nor
- broaden the override list to suppress thousands of errors (would defeat the M2-03 "in-scope clean"
  intent and silently hide debt).

**Owner options for Task 2:**
1. **Full in-scope clean (as written):** authorize the multi-file annotation pass across the D-05
   in-scope set (events, enums, exceptions, config, portfolio, order, execution, strategy, csv feed,
   reporting) — large but bounded; excludes `my_strategies/*`, `legacy_config.py`, D-sql/D-oanda/D-live.
2. **Scope Task 2 down + add overrides:** confirm the precise D-05 in-scope file list, add documented
   `ignore_errors` overrides for the remaining out-of-scope modules (`my_strategies.*`, `legacy_config`,
   `postgresql_storage`, the non-csv `price_handler` adapters), and clean only the agreed in-scope set.
3. **Defer Task 2 to M2b:** record `make typecheck` clean as a deferred carry-over and close the phase
   on Tasks 1+3+4. (Conflicts with M2-03's stated DoD — needs explicit owner sign-off.)

Also flagged for whichever path is chosen: **SignalEvent.strategy_id** is annotated `int` but receives
a UUID-typed `StrategyId` (02-05 carry-over) — fix lands with the Task 2 pass.

### Task 4 — Phase gate (`checkpoint:human-verify`, gate="blocking")
Owner-run verification to close the phase: `make test` (green: 299), `make typecheck` (depends on Task
2 decision), oracle test (green), and review of the D-15 tolerance magnitude (`rtol=1e-6, atol=5e-2`).

## Self-Check: PASSED
- FOUND: itrader/events_handler/event.py
- FOUND: test/test_events/test_event_immutability.py
- FOUND: test/test_integration/test_backtest_oracle.py
- FOUND commits: ffe2a3c (RED), 227dab3 (GREEN), e9af665 (oracle)

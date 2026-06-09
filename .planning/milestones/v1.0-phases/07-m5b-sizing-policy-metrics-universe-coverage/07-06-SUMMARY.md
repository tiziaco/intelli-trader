---
phase: 07-m5b-sizing-policy-metrics-universe-coverage
plan: 06
subsystem: order-sltp
tags: [sltp-policy, d-13, fill-anchored-brackets, pattern-5-option-b, oracle-inert, byte-exact]
requires:
  - "07-01 (PercentFromFill/PercentFromDecision/SLTPPolicy in itrader/core/sizing.py)"
  - "07-04 (SignalEvent.sltp_policy typed field)"
  - "07-05 (resolver-wired OrderManager — this plan builds on its _resolve_signal_quantity/process_signal shape)"
provides:
  - "D-13 SLTP dispatch in _assemble_bracket_and_emit: explicit levels primary; PercentFromDecision priced from the decision price at assembly; PercentFromFill deferred to fill"
  - "Pending-bracket map (_pending_brackets, keyed by parent OrderId) + _create_fill_anchored_children riding the on_fill return-list rail (D-18 — manager never touches the queue)"
  - "_bracket_levels shared ± pct math (BUY: sl below / tp above anchor; mirrored for SELL), Decimal end-to-end"
  - "tests/unit/order/test_sltp_policy.py — 5 tests locking assembly pricing, fill anchoring, explicit precedence (both kinds), and rejected-parent discard"
affects:
  - 07-07/07-08 (the two owner-gated result-changing re-freezes — all inert workstreams are now complete)
tech-stack:
  added: []
  patterns:
    - "RESEARCH Pattern 5 Option B: PercentFromFill children created AT parent fill (IB attached-order semantics) — documented carve-out to create-all-then-emit (Phase 4 D-11)"
key-files:
  created:
    - tests/unit/order/test_sltp_policy.py
  modified:
    - itrader/order_handler/order_manager.py
decisions:
  - "Pending-bracket context is a manager-held frozen dataclass map (_PendingBracket keyed by parent order id) — the simpler of the two RESEARCH options (vs an entity field surviving storage round-trips); entries are in-memory only, matching the backtest-first scope"
  - "Explicit precedence implemented as a single guard: when EITHER explicit level is truthy the policy branch is never consulted — the pre-existing truthy semantics are preserved verbatim (the explicit path emits byte-identical entities)"
  - "Fill-anchored children are created on EXECUTED exchange truth even if the mirror add_fill was rejected (applied=False) — the exchange is the source of truth for fills; only the mirror update is skipped"
  - "on_fill's returned list renamed cancel_events -> out_events (it now carries WR-05 cancels AND fill-anchored child creations); WR-05 logic itself is untouched"
metrics:
  duration: "~8 min"
  completed: "2026-06-07"
  tasks: 2
  tests-added: 5
---

# Phase 7 Plan 06: Typed SLTPPolicy Mechanics — Decision-Time and Fill-Anchored Brackets Summary

D-13 delivered: explicit SL/TP levels stay primary, PercentFromDecision prices bracket children from the decision price at assembly, and PercentFromFill creates them only at the parent's actual fill via a pending-bracket map riding the on_fill return rail (Pattern 5 Option B — no placeholder-trigger hazard), with the golden oracle proven byte-exact through the whole change.

## Tasks Completed

| Task | Name | Commits | Key Files |
|------|------|---------|-----------|
| 1 | SLTP policy dispatch — decision-time pricing + fill-time child creation | 467611e | itrader/order_handler/order_manager.py |
| 2 | SLTP mechanics tests + inertness gate | f63f853 | tests/unit/order/test_sltp_policy.py |

## What Was Built

**Assembly-path dispatch (order_manager.py, tabs):** `_assemble_bracket_and_emit` now resolves effective `sl_price`/`tp_price` before child creation. Explicit precedence (D-13): when either explicit `stop_loss`/`take_profit` is truthy the path behaves EXACTLY as before — the policy is never consulted (the explicit branch passes the same objects to the same factories). Only a signal with no explicit level dispatches on `signal.sltp_policy` via `match` + `assert_never` over the `SLTPPolicy` union: `PercentFromDecision` computes `sl = price * (1 - sl_pct)`, `tp = price * (1 + tp_pct)` for a BUY (mirrored for SELL) from `to_money(signal.price)` using `Decimal("1")` string-path constants, then feeds the unchanged child-creation path; `PercentFromFill` skips child creation entirely and records a `_PendingBracket` (policy, ticker, action, quantity, exchange, strategy_id, portfolio_id) in the manager-held `_pending_brackets` dict keyed by the parent's id.

**Fill-time creation (Pattern 5 Option B):** in `on_fill`, an EXECUTED fill pops the parent's pending entry and `_create_fill_anchored_children` builds both children priced from `to_money(fill_event.price)` with the shared `_bracket_levels` math, stamps them with the fill's time, links them exactly as the assembly path does (children carry `parent_order_id`; parent's `child_order_ids` persisted via `update_order`), stores all, and returns their OrderEvents on the on_fill return list — the handler enqueues them (D-18). A CANCELLED/REFUSED reconciliation discards the pending entry: the children were never created, so the WR-05 orphan-cancellation logic is structurally untouched (T-07-15).

**Documentation in code:** the `_assemble_bracket_and_emit` docstring carries the carve-out ("PercentFromFill children are created at parent fill (IB attached-order semantics) — a documented exception to create-all-then-emit (Phase 4 D-11)") and the D-07 v1 limitation (children sized at entry, not resized by partial signal exits), repeated at the fill-time helper.

**Tests (5, tests/unit/order/test_sltp_policy.py, spaces, auto-marked unit):** PercentFromDecision BUY at 100 with sl 5% / tp 10% emits STOP 95 / LIMIT 110 with two-directional linkage on both events and stored entities; PercentFromFill emits ONLY the parent at assembly (storage holds 1 order), and an EXECUTED fill at 102 produces children priced 96.9 / 112.2 with full linkage and a consumed pending entry; explicit levels (90/120) win over both policy kinds (and PercentFromFill under explicit levels arms no pending bracket); a REFUSED parent discards the pending entry leaving exactly one REJECTED order with empty `child_order_ids`. Queue drained in teardown; fills driven portfolio-first (the canonical FILL dispatch order).

## Verification Evidence

- `tests/unit/order`: 124 passed (119 existing + 5 new) — explicit-levels bracket tests unchanged and green
- `make typecheck` (mypy --strict): Success, no issues in 129 source files
- Oracle inertness: `tests/integration/test_backtest_oracle.py` — **2 passed, byte-exact** (golden has no brackets; all SLTP mechanics are oracle-dark)
- Full suite: `make test` — **696 passed**
- Acceptance greps: `PercentFromFill`/`PercentFromDecision` (13 hits), `_pending_brackets` map attribute, "create-all-then-emit" carve-out wording, and the "D-07 v1 limitation" note all present in order_manager.py

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Worktree environment handling (carried from 07-01/07-05)**
- **Issue:** Worktree venv resolves `itrader` to the main checkout; `make` targets require a `.env`
- **Fix:** All test runs use `PYTHONPATH="$PWD"`; empty gitignored `.env` created locally. No repo files changed
- **Commit:** n/a

### Cosmetic rename (logic unchanged)

**2. on_fill local `cancel_events` renamed `out_events`.** The returned list now carries fill-anchored child creations alongside WR-05 cancels — the old name would lie. The WR-05 cancellation logic itself is byte-identical; only the variable name and the Returns docstring changed.

## TDD Gate Compliance

Task 2 carries `tdd="true"`, but its behaviors are the direct output of Task 1 of this same plan — a strict RED phase (failing test before implementation) was structurally impossible within the plan's own task order, exactly as in plans 07-04 and 07-05. The implementation commit (467611e, `feat(...)`) precedes the test commit (f63f853, `test(...)`) — gate sequence is feat-then-test rather than test-then-feat, flagged here per protocol. The byte-exact oracle gate and the hand-computed Decimal assertions provide the regression lock the RED phase would have.

## Authentication Gates

None.

## Known Stubs

None — no placeholder values or unwired data paths introduced. The pending-bracket map is fully wired end-to-end (assembly → fill → emitted children).

## Threat Model Mitigations Applied

- **T-07-14 (mitigate):** Option B implemented — PercentFromFill children do not exist until the parent fills; a premature child trigger is structurally unreachable (asserted: storage holds only the parent before the fill)
- **T-07-15 (mitigate):** pending entry discarded on parent CANCELLED/REJECTED reconciliation; unit-asserted (test_rejected_parent_discards_pending_bracket — no children ever exist, WR-05 untouched)
- **T-07-16 (mitigate):** byte-exact oracle gate passed post-edit (2 passed); full suite 696 green
- **T-07-SC (accept):** zero package installs performed

## Self-Check: PASSED

- itrader/order_handler/order_manager.py — FOUND (PercentFromFill, PercentFromDecision, _pending_brackets, carve-out + D-07 wording)
- tests/unit/order/test_sltp_policy.py — FOUND (5 tests: assembly pricing, fill anchoring, precedence x2, rejected-parent discard)
- Commits 467611e, f63f853 — FOUND in git log

---
phase: 01-config-centralization
plan: 03
subsystem: docs
tags: [conventions, d-03a, cf-6, doc-only]
requires: []
provides:
  - "CONVENTIONS.md Pinned Decisions item 4 carries the CF-6 D-03a substance (defense-in-depth + SimulatedExchange-only-where-called) without regressing to the pre-V17-16 framing"
affects:
  - .planning/codebase/CONVENTIONS.md
tech-stack:
  added: []
  patterns: []
key-files:
  created: []
  modified:
    - .planning/codebase/CONVENTIONS.md
decisions:
  - "Folded §6d nuance (exchange-side layer real only where called = SimulatedExchange; two standing conditions) into the existing post-fix D-10 framing rather than replacing it with the stale §6d text"
metrics:
  duration: ~4m
  completed: 2026-07-09
status: complete
---

# Phase 1 Plan 3: CF-6 D-03a Dual-Validator Doc Reconciliation Summary

Reconciled the D-03a dual-layer order-validator paragraph in `.planning/codebase/CONVENTIONS.md` (Pinned Decisions item 4) — folding in the still-valid §6d nuance (the exchange-side layer is real only where it is actually called, `SimulatedExchange`, plus the two standing conditions for D-03a) while preserving the current V17-16-fixed framing and NOT reintroducing the stale "aspirational" pre-fix wording. Closes CFG-06, the last v1.7 doc-consistency debt (CF-6).

## Tasks Completed

| Task | Name | Commit | Files |
| ---- | ---- | ------ | ----- |
| 1 | Reconcile the D-03a dual-validator paragraph in CONVENTIONS.md | (this plan's task commit) | .planning/codebase/CONVENTIONS.md |

## What Changed

The current CONVENTIONS.md item 4 already reflected the post-fix reality (D-10 made `LiveTradingSystem.add_event` fail-closed and SIGNAL-form, so the original bypass premise is obsolete). The `v17_audit_results.md §6d` source text predates the V17-16 fix and describes the live second layer as "aspirational / bypasses BOTH layers" — a since-fixed state.

Rather than pasting §6d verbatim (which would regress the doc), the still-valid substance was folded into the existing paragraph:

- The exchange-side layer is real only where it is actually called — today that is `SimulatedExchange`.
- D-03a stands on two conditions: (a) every live entry path routes through the admission pipeline (now guaranteed by D-10), and (b) a live venue wanting the second boundary-gate layer must wire its own `validate_order`/`validate_symbol` preflight the way `SimulatedExchange` does.

Preserved unchanged: the defense-in-depth / justified-by-decision framing, the D-03a / W4-09 citation, and the D-10 obsolescence note.

## Verification

All plan acceptance greps pass:

- `grep -F "defense-in-depth"` → hits item 4 (PASS)
- `grep -F "SimulatedExchange"` → hits item 4 (§6d "only real where it is called" nuance present) (PASS)
- `grep -Fc "aspirational"` → `0` (stale pre-fix wording not reintroduced) (PASS)
- Item 4 still cites both D-03a and D-10 (current framing preserved) (PASS)

No code or tests touched → the byte-exact oracle and OKX import-inertness gates are unaffected and were not re-run (doc-only plan, per project gate).

## Deviations from Plan

None - plan executed exactly as written.

## Self-Check: PASSED

- `.planning/codebase/CONVENTIONS.md` modified and present.
- All four acceptance criteria verified via grep.

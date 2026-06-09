---
phase: 01-codebase-map-clarity-baseline
plan: 01
subsystem: planning-artifacts
tags: [clar-01, fix-list, harvest, documentation-only]
requires: []
provides:
  - ".planning/codebase/FIX-LIST.md (harvested CLAR-01 fix-list, FL-NN schema)"
affects:
  - "v1.1 phases 2-9 (consume FIX-LIST.md via Eligible-in-phase column)"
tech-stack:
  added: []
  patterns: ["FL-NN stable-ID tabular fix-list keyed for cross-phase citation"]
key-files:
  created:
    - ".planning/codebase/FIX-LIST.md"
  modified: []
decisions:
  - "FIX-LIST.md co-located in .planning/codebase/ beside the map it derives from (discoverability for phases 2-9)"
  - "#10 (portfolio_id: int) pre-tagged eligible-in-Phase-5 (HARD-03 retype), status open"
  - "#7/#37 (portfolio.py bare ValueError) pre-tagged eligible-in-Phase-8 (admission gates), off golden path"
  - "Category C deferred items recorded with owning milestones, never actioned in v1.1"
metrics:
  duration: "~4 min"
  completed: 2026-06-09
  tasks: 1
  files: 1
---

# Phase 01 Plan 01: CLAR-01 Fix-List Harvest Summary

Harvested the objective, deduplicated CLAR-01 fix-list into a single committed
`.planning/codebase/FIX-LIST.md` using a stable `FL-NN` tabular schema with a pre-tagged
`Eligible-in-phase` column — derived from the existing codebase map (not a fresh
`gsd-map-codebase` run), with zero `itrader/`/`tests/` source touched.

## What Was Built

- **`.planning/codebase/FIX-LIST.md`** — a Markdown artifact with:
  - An honest, non-padding header stating it is harvested from the existing
    `.planning/codebase/` map (`CONCERNS.md` + `CONVENTIONS.md` + `STRUCTURE.md`) plus the two
    verified v1.0 residual carry-forwards, that it was NOT produced by a new map run, and that
    `v1.0-ARCHITECTURE-REVIEW.md` was not used as a source.
  - A scope-discipline section (no source touched; Category C deferred-but-recorded; golden
    master not re-baselined) and a column-schema legend.
  - A single 14-row table keyed by `FL-NN` with the exact required columns:
    `ID | Category | Description | File(s):line | Golden-path? | Eligible-in-phase | Status | Origin`.

### Fix-list rows (harvested, not invented)

| Row | What | Eligible / Status |
|-----|------|-------------------|
| FL-01 | `portfolio.py` bare `raise ValueError` → typed exception, 7 sites (101,103,124,183,410,431,436) | Phase 8 / open (#7/#37) |
| FL-02 | `portfolio_id: int` annotation carry-over (signal.py:84, order.py:52, fill.py:64) | Phase 5 / open (#10) |
| FL-03 | Stale `pytest.skip` masking FillStatus test (test_enums.py:25-40) | Phase 4 / open |
| FL-04 | Stringly-typed `order_type: str = "market"` on strategy base (base.py:27) — HARD-03 target | Phase 5 / open |
| FL-05..FL-14 | Category C record-but-defer: PostgreSQL stub, SQL injection, OANDA TODOs, my_strategies long_only, screener TODOs, no retry/backoff, Binance buffer, broad except, live zero-coverage, pandas-ta beta pin | deferred → owning milestone |

All carry-forward line numbers were re-verified against the current tree by grep before writing.

## Verification

- Plan automated check: `PASS` — `FIX-LIST.md` exists; `FL-NN` IDs, `Eligible-in-phase`,
  `Golden-path`, `portfolio.py`, `portfolio_id`, `deferred`, and `CONCERNS` provenance all present.
- Carry-forward asserts: `101` present (FL-01); `signal.py:84` present (FL-02).
- Deferred items: present (FL-05..FL-14, Status `deferred`).
- **Golden-master no-drift guard:** `git diff --name-only` / `--cached` show NO path under
  `itrader/` or `tests/` — the only changed file is `.planning/codebase/FIX-LIST.md`.

## Deviations from Plan

None — plan executed exactly as written. (Line references confirmed unchanged from the plan's
pre-verified values: portfolio.py 101/103/124/183/410/431/436; events signal.py:84, order.py:52,
fill.py:64; strategy base order_type:27; test_enums skip at :32 within the 25-40 block.)

## Notes

- Scope honored: documentation-only. No source file edited; the fix-list *records* line
  references and the cleanup happens in later phases along touched paths under the byte-exact
  golden-master gate.
- The list is deliberately short (4 open + 10 deferred). `CONVENTIONS.md` records no convention
  violations in the current tree beyond the carry-forwards, so no padding was added.

## Commits

- `645f092` docs(01-01): harvest CLAR-01 fix-list with FL-NN schema

## Self-Check: PASSED

- `.planning/codebase/FIX-LIST.md` — FOUND
- Commit `645f092` — FOUND

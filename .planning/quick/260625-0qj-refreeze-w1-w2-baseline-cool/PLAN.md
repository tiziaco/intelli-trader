---
quick_id: 260625-0qj
slug: refreeze-w1-w2-baseline-cool
created: 2026-06-25
status: in-progress
owner_gated: true
---

# Quick Task: Re-freeze v1.5 Gate (b) baseline on a cool machine + attribute the Phase-5 W1 win

## Why

The carried v1.5 todo (STATE.md Session Continuity + 06-05-SUMMARY.md "Pending Todo"):
`W1-BASELINE.json` is stuck at the **Phase-6 freeze 238.5 s / 162.7 MB** (2026-06-24). The 06-05
re-freeze read **259.1 s** but was deferred as thermal drift (W1 ran last after a W2 battery warmed
the box — memory `v15-perf-gateb-thermal-drift`). The machine is cool now (`pmset -g therm`: no
thermal/performance warning recorded), so re-freeze cleanly and attribute Phase 5.

## A/B endpoints (Phase-5 attribution)

- **OLD** = `de2e19f` (`5be5047^`) — Phase-6 engine tip, BEFORE any `05-*` code commit.
- **NEW** = HEAD `98e50b6` — Phase 5 complete (per-tick `ta` recompute removed + `feed.window()`
  slice cut; `05-01..05-03`).
- Method: `make perf-w1` at each commit, same cool box, same harness-at-that-commit. Verify
  `TOTAL fills` matches across commits so the delta is pure speed, not a workload change.

## Thermal method (bias control)

Bracket the OLD run between two NEW (HEAD) runs:
1. R1 = HEAD `make perf-w1`  (coolest slot)
2. R2 = OLD  `make perf-w1`  (`git checkout de2e19f` … then restore branch)
3. R3 = HEAD `make perf-baseline` (warmest slot; also the W1 re-freeze run)

If R1 ≈ R3, HEAD is thermally stable across the battery → the R2 vs HEAD delta is not a thermal
artifact. OLD is measured at a thermal state *between* the two HEAD points, bracketing out drift.

## Steps

1. ✅ Confirm machine cool (`pmset -g therm` clean; note moderate background load caveat).
2. A/B: R1 (HEAD) → R2 (OLD) → record deltas + fills-equivalence.
3. Re-freeze: `make perf-baseline` (W1, R3) + `make perf-w2-baseline` (W2, last/heaviest).
4. Gate (a): `poetry run pytest tests/integration/test_backtest_oracle.py -x -q` (expect 134 /
   46189.87730727451).
5. Write attribution note (`ATTRIBUTION.md`), update STATE.md (clear carried todo + Session
   Continuity line).
6. **OWNER-GATED:** present new frozen numbers + cool A/B deltas; get explicit sign-off BEFORE
   committing the frozen baseline (v1.5 Gate (b) re-baseline discipline).

## Out of scope

No engine code changes. No commit before owner sign-off.

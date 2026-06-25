---
quick_id: 260625-0qj
slug: refreeze-w1-w2-baseline-cool
date: 2026-06-25
status: complete
owner_gated: true
owner_signoff: "tiziaco (tiziano.iaco@gmail.com), 2026-06-25 — Approve & commit"
tags: [perf, gate-b, baseline, w1, w2, thermal, phase-5-attribution, v1.5]
gate_a: "GREEN — 134 / 46189.87730727451 (3 passed)"
---

# Quick 260625-0qj: Re-freeze v1.5 Gate (b) baseline (cool) + Phase-5 attribution

**Re-froze the v1.5 Gate (b) W1/W2 baselines on a verified-cool box and attributed the Phase-5 win via
a cool same-machine A/B. W1 153.7 s / 162.3 MB, W2 4.05 s @50 / 210.87 MB; Phase-5 W1 −40.1%, W2@50
−70.2%. Gate (a) byte-exact green. Owner sign-off obtained before commit. Clears the last carried v1.5 todo.**

## What was done

1. **Confirmed cool:** `pmset -g therm` → no thermal/performance warning recorded (the 06-05 throttle
   condition is absent). Background load moderate (~2.4, browser open) — caveat noted; immaterial given
   the +0.9% in-battery HEAD drift below.
2. **Cool same-machine A/B** (`make perf-w1`, OLD `de2e19f` = `5be5047^` vs NEW HEAD `98e50b6`, OLD
   bracketed between two HEAD runs):
   - R1 NEW (coolest) 152.322 s · R2 OLD (middle) 255.402 s · R3 NEW (warmest, freeze) 153.674 s.
   - Identical workload (1578 fills / 659 closed at both commits) → pure-speed delta.
   - HEAD drift R1→R3 = +0.9% → thermally stable, no throttle → OLD's 255.4 s is genuine.
   - **Phase-5 W1 win = −40.1%** (255.4→153.0 s, 102.4 s); robust −39.8%/−40.4% across slots. Mem flat (−0.2%).
3. **Re-froze baselines** (HEAD, cool, frozen_at 2026-06-25):
   - `make perf-baseline` → **W1-BASELINE.json: 153.7 s / 162.3 MB** (was 238.5 s / 162.7 MB).
   - `make perf-w2-baseline` → **W2-BASELINE.json: 4.05 s @50 / 210.87 MB** (was 13.61 s / 214.58 MB →
     **W2@50 −70.2%**; 1 sym 0.166 s, 10 sym 0.796 s).
4. **Gate (a):** `pytest tests/integration/test_backtest_oracle.py -x -q` → 3 passed
   (134 / 46189.87730727451). Held green throughout.
5. **Docs:** wrote `ATTRIBUTION.md` (deltas + frozen numbers + thermal provenance); updated STATE.md
   (carried todo CLEARED in the Current-Position NOTE + Session Continuity; Gate (b) locked-reference
   updated; Quick Tasks row added).
6. **Owner-gated freeze:** presented numbers → owner sign-off (tiziaco, "Approve & commit") obtained
   **before** committing the frozen baselines.

## Files changed

- `perf/results/W1-BASELINE.json` — re-frozen 153.7 s / 162.3 MB (cool HEAD).
- `perf/results/W2-BASELINE.json` — re-frozen 4.05 s @50 / 210.87 MB (cool HEAD).
- `.planning/STATE.md` — carried todo cleared; Gate (b) locked reference updated; quick row added.
- `.planning/quick/260625-0qj-refreeze-w1-w2-baseline-cool/{PLAN,ATTRIBUTION,SUMMARY}.md`.

No `itrader/` engine code touched. The OLD-code A/B used a transient detached `git checkout de2e19f`
in the main checkout (clean tree restored to the branch after) — avoids the worktree `.venv`
shadowing hazard entirely.

## Caveats / provenance

- Moderate background load (~2.4, browser open) during the run. Thermal throttling — the actual 06-05
  failure mode — was absent (`pmset` clean) and the +0.9% in-battery HEAD drift confirms the numbers
  are not thermally contaminated. This supersedes the deferred 06-05 reading (259.1 s, W1-ran-last).
- The −35.6% W1 vs the *stale* 238.5 s freeze is NOT the clean attribution (cross-session drift; OLD
  code reads 255.4 s on this box today). The honest Phase-5 W1 win is the same-session **−40.1%**.

## Next

- v1.5 (Backtest Performance Optimization) is ready for `/gsd-complete-milestone`.

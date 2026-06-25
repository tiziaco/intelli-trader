# v1.5 Gate (b) Re-Freeze + Phase-5 Attribution — Cool-Machine Run

**Date:** 2026-06-25 (~00:35–00:47 local)
**Machine state:** verified cool. `pmset -g therm` → *"No thermal warning level has been recorded /
No performance warning level has been recorded"* (the exact 06-05 throttle condition is **absent**).
Background load moderate (`load avg ~2.4`, a browser open) — noted as a caveat, but the in-battery
HEAD drift below proves no throttling contaminated the numbers.

## 1. Cool same-machine A/B — Phase-5 W1 attribution

Endpoints: **OLD = `de2e19f`** (`5be5047^`, Phase-6 engine tip, before any `05-*` commit) vs
**NEW = HEAD `98e50b6`** (Phase 5 complete: per-tick `ta` recompute removed + `feed.window()` slice
cut, `05-01..05-03`). Same `make perf-w1`, same box, harness-at-each-commit. OLD run bracketed
between two HEAD runs to bound thermal drift.

| Run | Code | Thermal slot | wall_clock_s | peak_mem_mb | fills / closed |
|-----|------|--------------|-------------:|------------:|----------------|
| R1  | NEW (HEAD) | coolest (1st) | **152.322** | 162.30 | 1578 / 659 |
| R2  | OLD (`de2e19f`) | middle (2nd) | **255.402** | 162.59 | 1578 / 659 |
| R3  | NEW (HEAD, freeze) | warmest (3rd) | **153.674** | 162.30 | 1578 / 659 |

- **Workload identical** at both commits — 1578 fills / 659 closed — so the delta is *pure speed*,
  not a workload change.
- **HEAD thermally stable:** R1→R3 drift = **+0.9%** across the whole battery → the box did not
  throttle; OLD's 255.4 s is genuine, not a thermal artifact.
- **Phase-5 W1 win:** OLD 255.4 s → HEAD (thermally-centered mean of R1,R3) 153.0 s =
  **−40.1% wall-clock (102.4 s faster).**
  - Coolest-case bound (R1 vs R2): −40.4%. Conservative bound (warmest HEAD R3 vs R2): −39.8%.
    The win is robust to thermal slot to within ±0.3 pts.
- **Peak memory flat:** 162.59 → 162.30 MB (−0.2%) — Phase 5 was a CPU/recompute win, as designed.

## 2. New frozen baselines (HEAD, cool, frozen_at 2026-06-25)

| Baseline | NEW (frozen this run) | PRIOR (Phase-6 freeze, 2026-06-24) | Δ |
|----------|----------------------:|-----------------------------------:|---|
| **W1** wall_clock | **153.7 s** | 238.5 s | −35.6% vs stale freeze |
| **W1** peak_mem | **162.3 MB** | 162.7 MB | −0.2% |
| **W2** wall_clock @ 50 sym | **4.05 s** | 13.61 s | **−70.2%** |
| **W2** peak_mem @ 50 sym | **210.87 MB** | 214.58 MB | −1.7% |

W2 sweep points (n_bars=3000, seed=42): 1 sym 0.166 s (was 0.425) · 10 sym 0.796 s (was 3.07) ·
50 sym 4.05 s (was 13.61). The per-symbol `ta` recompute removal dominates as symbol count grows —
the W2 path is where Phase 5 pays the most (−70% at 50 symbols).

> Note on the −35.6% W1 figure vs the *stale* 238.5 s: that is **not** the clean Phase-5 attribution
> (the 238.5 s was a cross-session Phase-6 freeze; the same OLD code reads 255.4 s on this box today
> — the +7.1% drift is exactly why §1 uses the same-session A/B, not the stale frozen number). The
> honest Phase-5 W1 win is the **−40.1%** in §1.

## 3. Gate (a) — oracle lock (held green throughout)

`poetry run pytest tests/integration/test_backtest_oracle.py -x -q` → **3 passed** — SMA_MACD
byte-exact **134 trades / final_equity 46189.87730727451**. The frozen W1-BASELINE.json stamps
`oracle_provenance.green_at_freeze: true`.

## 4. Thermal provenance / why this supersedes the 06-05 deferral

The 06-05 W1 re-freeze read **259.1 s** and was deferred as thermal drift — W1 ran *last*, after a
back-to-back W2 battery warmed the box (memory `v15-perf-gateb-thermal-drift`). This run inverts
that: W1 ran on a verified-cool box (clean `pmset`), W1 work ran *first*, and the bracketing HEAD
runs confirm +0.9% in-battery drift. The 153.7 s freeze is therefore a trustworthy cool reference;
the 259.1 s reading was never frozen and is now moot.

## 5. Owner sign-off (v1.5 Gate (b) re-baseline discipline)

Owner sign-off on the numbers above (W1 153.7 s / 162.3 MB, W2 4.05 s / 210.87 MB) **GRANTED**
before commit (v1.5 Gate (b) re-baseline discipline).

- [x] Owner sign-off: **tiziaco** (tiziano.iaco@gmail.com), 2026-06-25 — "Approve & commit".

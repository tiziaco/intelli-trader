# Phase 4 — Gate (b) Perf Attribution (PERF-03 + PERF-04)

**Measured:** 2026-06-24, same machine, back-to-back A/B. **Verdict: gate (b) PASS** — a
real, attributed wall-clock win of **−7.8% (mean)** / **−9.8% (best-of-2)**, well above the
≥5% bar, attributed to PERF-03 (logging gate) + PERF-04 (type-hint memoization). Peak memory
also down (−0.22%). The re-freeze of `W1-BASELINE.json` is held for the **blocking owner
sign-off** (Task 2), per the plan and the W1-perf thermal-drift caveat.

## 1. Machine state — NOT throttled, but under foreground contention

| Signal | Reading | Interpretation |
|--------|---------|----------------|
| `pmset -g therm` | "No thermal warning … No performance warning … No CPU power status" | **No thermal throttle** (unlike the Phase-3 box, which read inflated 268–317s) |
| `top -l` CPU | 9.3% user / 8.9% sys / **81.8% idle** | CPU not pinned; capacity available |
| load avg (1/5/15) | 3.95 / 3.36 / 3.09 | sustained foreground load on an 8-core box |
| top CPU procs | WindowServer, Safari, Slack, WebKit, a 2nd-project Python (11.7%) | **active foreground contention** — single-threaded W1 competes for cache/cores |

**Cool-machine call:** the box is **not thermally throttled** (the Phase-3 failure mode is
absent), but it is **not pristine-quiet** either — Safari/Slack/another Python interpreter are
live. This is handled the only honest way: a **same-machine back-to-back A/B**, which is
drift-immune to slow background contention because both trees see the same load in the same
window. Absolute numbers here run hot vs the cool-night 199.4s frozen reference (~240–270s for
*any* code), confirming the frozen-number compare is invalid today — exactly the
W1-perf thermal-drift caveat.

## 2. Baseline-provenance check — STALE (Phase-2), re-freeze still pending

`perf/results/W1-BASELINE.json` currently holds `wall_clock_s: 199.4`, `frozen_at: 2026-06-23`,
`peak_mem_mb: 169.8`. Per `.planning/phases/03-running-pnl-accumulator/03-02-SUMMARY.md`, the
**Phase-3 re-freeze was deliberately DEFERRED** (that box was thermally throttled; freezing
~268s would have corrupted the reference). So the committed baseline is the **pre-Phase-3
(Phase-2) number**. A naive frozen compare against 199.4s would over-credit Phase 4 by ~15%
(it would fold in Phase 2/3 wins + thermal drift). The gate-(b) verdict below therefore comes
**exclusively from the same-machine A/B**, never the stale frozen compare. The plan's
CRITICAL PRECONDITION is satisfied by NOT trusting 199.4s and measuring old-vs-new directly.

## 3. Same-machine A/B — old (pre-PERF-03/04) vs new

Method: revert the 6 PERF-03/04 files to commit `1240617` (the last commit before `cfe392e`,
i.e. pre-Plan-01/02), benchmark, restore HEAD, benchmark — back-to-back, same machine, same
`ITRADER_LOG_LEVEL=ERROR` (the level `make perf-w1` runs at; the worktree has no `.env`, so the
level was passed explicitly). Files reverted: `itrader/logger.py`,
`itrader/config/settings.py`, `itrader/order_handler/admission/admission_manager.py`,
`itrader/portfolio_handler/position/position_manager.py`,
`itrader/portfolio_handler/cash/cash_manager.py`, `itrader/strategy_handler/base.py`. Working
tree restored clean after (isEnabledFor=7, _declared_hints=6, `git status` empty).

| Tree | Run 1 | Run 2 | Best | Mean | peak_mem | fills/closed |
|------|------:|------:|-----:|-----:|---------:|:------------:|
| **OLD** (pre-PERF-03/04) | 269.4s | 264.4s | 264.4s | 266.9s | 163.04 MB | 1578 / 659 |
| **NEW** (PERF-03 + PERF-04) | 253.8s | 238.6s | 238.6s | 246.2s | 162.68 MB | 1578 / 659 |

**Delta (NEW − OLD), wall-clock:**

| Comparison | Δ | vs ≥5% bar |
|------------|----:|:----------:|
| mean vs mean | **−7.8%** | PASS |
| best vs best | **−9.8%** | PASS |
| worst-NEW vs best-OLD (conservative floor) | −4.0% | marginal |

**Peak memory:** 162.68 vs 163.04 MB = **−0.22%** (watched, never gates).

The NEW tree is faster in **every** pairing and the two clusters do not overlap on the mean.
Trade topology is byte-identical (1578 fills / 659 closed) across all four runs — same engine
behaviour, only the hot-path overhead changed.

## 4. Attribution to PERF-03 + PERF-04 (not noise)

- **ITRADER_LOG_LEVEL=ERROR confirmed** — both A/B legs ran at ERROR (the `make perf-w1`
  level), so the D-01 demotion win is realized. **Direct visible signature:** the OLD tree
  emitted the per-bar admission-rejection lines at `error` ("Signal validation failed: …
  Quantity … below minimum") — they print even at ERROR level on the old code. On the NEW
  tree these are demoted `error`→`warning` behind a cached `isEnabledFor(WARNING)` guard, so
  they gate out at ERROR entirely. That demotion is a measured, observable part of the win.
- **PERF-03 (logging gate, hotspot #4):** the central `isEnabledFor` short-circuit in every
  `ITraderStructLogger` wrapper (added in `25402ab`) skips the 9-processor structlog pipeline
  for below-level calls; Phase-3's Scalene map put `logger.py` at 4.11% CPU share — the gate
  removes most of that at the ERROR benchmark level.
- **PERF-04 (type-hint memoization, hotspot #6):** `_declared_hints` (`aeab4d8`) memoizes the
  per-signal `get_type_hints(type(self))` MRO walk in `Strategy.to_dict` (hot, per-signal).
- The ~−7.8% mean is consistent with the combined hotspot share these two targeted (logging
  ~4–6% W1 + type-hints ~2% W1) plus the demoted-error-log I/O removed at ERROR level.

**Scalene cross-check:** OPTIONAL per the plan, and deliberately **not re-run** here — a fresh
~16-min `--cpu-only` profile would further heat an already-contended box (corrupting any
subsequent timing) and the Phase-3 `scalene-w1.json` map already locates these two hotspots
(logger 4.11%, strategy/base 2.49%). The drift-immune signal relied on is the 2-vs-2
non-overlapping A/B plus the visible error-log demotion, both of which are robust to the
foreground contention present today.

## 5. Gate (a) green at measurement

`tests/integration/test_backtest_oracle.py` — **3 passed** (byte-exact 134 /
46189.87730727451). Engine on-contract; the perf changes alter no engine numbers.

## 6. Conclusion + re-freeze gate

- **Gate (b): PASS** — same-machine A/B, mean **−7.8%** (best −9.8%) wall-clock, peak mem
  −0.22%, attributed to PERF-03 + PERF-04, topology byte-identical, oracle byte-exact.
- **Honest caveats:** measured under foreground app contention (not a pristine quiet box); the
  conservative worst-NEW/best-OLD floor is −4.0% (just under the bar) while mean/best clear it.
  The machine is NOT thermally throttled (the Phase-3 failure mode is absent).
- **Re-freeze of `W1-BASELINE.json` is held for Task 2 (blocking owner sign-off).** Per the
  thermal-drift caveat and the milestone gate, the owner decides whether to (a) approve the
  re-freeze now using a clean run on this (un-throttled but contended) machine, or (b) defer the
  freeze to a confirmed-quiet machine — to avoid baking contention noise into the locked
  Phase-5 reference. The executor will NOT auto-freeze: the freeze is gated on explicit sign-off.

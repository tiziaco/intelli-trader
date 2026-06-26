# Plan 08-04 — D-03 Attribution Gate — SUMMARY

**Status:** Complete (owner-signed-off)
**Date:** 2026-06-25
**Type:** measurement / attribution / owner-gated re-freeze (no engine optimization of its own)

## What this gate did

The D-03 gate between the Phase-8 deterministic wins (08-01/02/03) and the msgspec layer (08-05).
Each candidate win was individually attributed via a same-machine, position-balanced, cool-box A/B
(`OPT BASE BASE OPT OPT BASE BASE OPT`, fresh interpreter per run, one discarded warmup, trust only the
within-session OPT-vs-BASE delta — never the frozen-baseline compare; memory `v15-perf-gateb-thermal-drift`).
Keep-only-measured (D-02) was applied, then the cool W1/W2 baseline was re-frozen under owner sign-off as
the new locked reference for 08-05.

## Per-win verdicts (see 08-04-ATTRIBUTION.md for run-by-run numbers)

| Req | Win | W1 Δ | Verdict | Action |
|-----|-----|------|---------|--------|
| 1 | valuation fusion (08-01) | −15.0% (W2 −5.0%) | REGRESSION | **REVERTED** — proper single-pass design deferred to todo |
| 2 | Position cache (08-02) | +15.0% | ATTRIBUTABLE | KEPT |
| 3 | itertuples prebuild (08-03) | +0.65% (noise) / W2 overlap | NOISE on the gate | **KEPT — owner override** (code-quality/allocation; runs outside the timed loop) |
| 4 | to_dict cache (08-03) | +2.08% | ATTRIBUTABLE | KEPT |
| 5 | `_aligned` audit (08-02) | n/a (no prod code) | — | KEPT as-is |

## Key finding

The 08-01 "fusion" was a **measured −15% W1 regression**, not a win: both accessors still called
`_fused_valuation()` independently (two passes/bar) AND it computed a discarded per-bar `aggregate_notional`
Decimal — strictly more work. Reverted. The genuine opportunity (compute-once-per-bar valuation piggybacked
on the existing `update_position_market_values` write pass, O(1) accessors) is captured, profile-first-gated,
in `.planning/todos/pending/single-pass-portfolio-valuation.md`.

## Owner override (keep-only-measured exception)

Req 3 itertuples kept despite a noise-band W1 because the prebuild runs once at wiring — outside the
benchmark's timed region, so "noise" is a measurement-scope artifact, not evidence of no value. Kept on
idiomatic + lower-allocation (~69k fewer throwaway pandas Series) + byte-exact grounds. Owner tiziaco,
2026-06-25. Documented explicitly as a code-quality keep, NOT a measured perf win, so 08-05's DTO-only
D-02 carve-out is not contradicted.

## Re-frozen baselines (new locked references for 08-05)

- **W1: 17.436 s / 153.44 MB** → `perf/results/W1-BASELINE.json` (workload byte-identical 1578 fills / 659 closed)
- **W2 @50: 2.686 s / 164.62 MB** → `perf/results/W2-BASELINE.json` (n_bars=3000, seed=42)
- Regression guard re-run: PASS (W1 16.7 s, Δ −4.2% vs new baseline, peak-mem flat, exit 0)

## Gate (a) — byte-exact on the shipped (kept) set

- `poetry run pytest tests/integration/test_backtest_oracle.py` → 3 passed, **134 / 46189.87730727451**
- `poetry run mypy` (strict) → clean, 188 source files
- Box cool (`pmset -g therm`) before / during / after the entire attribution + re-freeze session

## Owner sign-off

APPROVED — tiziaco (tiziano.iaco@gmail.com), 2026-06-25. See 08-04-ATTRIBUTION.md sign-off block.

## Key files

- `.planning/phases/08-hot-path-fusion-prebuild-msgspec-gated/08-04-ATTRIBUTION.md` (created)
- `.planning/phases/08-hot-path-fusion-prebuild-msgspec-gated/08-04-SUMMARY.md` (this file)
- `perf/results/W1-BASELINE.json` (re-frozen)
- `perf/results/W2-BASELINE.json` (re-frozen)
- `.planning/todos/pending/single-pass-portfolio-valuation.md` (deferred design)
- `itrader/portfolio_handler/position/position_manager.py` (Req-1 fusion reverted)
- `itrader/price_handler/feed/bar_feed.py` (Req-3 itertuples kept)

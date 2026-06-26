# Plan 08-06 — Final Phase-8 Gate — SUMMARY

**Status:** Complete (owner-signed-off)
**Date:** 2026-06-25
**Type:** measurement / attribution / owner-gated final re-freeze (no engine code of its own)

## What this gate did

The final Phase-8 gate (D-03): a FRESH same-machine A/B for the msgspec migration (08-05) on the cool
re-frozen baseline from 08-04 (the discarded spike's A/B was NOT inherited), then the final cool W1/W2
re-freeze under owner sign-off as the locked Phase-8 reference.

## Fresh msgspec A/B (BASE 2c01499 pre-msgspec vs OPT msgspec HEAD)

Position-balanced 8-run (`OPT BASE BASE OPT OPT BASE BASE OPT`), fresh interpreter per run, one warmup
discarded, within-session OPT-vs-BASE delta only.

| Axis | OPT mean | BASE mean | Δ | Separation |
|------|----------|-----------|---|------------|
| **W1** (the gate) | 22.421 s | 24.123 s | **+7.06% faster** | clean — max OPT 23.566 < min BASE 23.765 |
| **W2 @50** (scaling) | 4.262 s | 4.769 s | **+10.64% faster** | clean — max OPT 4.338 < min BASE 4.644 |

Both axes **exceed** the spike expectation (+3.82% W1 / +6.72% W2@50) in the same direction (cooler
session, stronger separation). The events+Bar slice is the A/B-attributed headline win. The 5 extra
DTOs (FillDecision/CancelDecision/SignalRecord/Transaction/TrailState, ~1578 fires/run ≈4% of ~69k Bar
volume) land in noise and are **NOT reverted** (D-02 carve-out — they ship under the byte-exact oracle
gate for a uniform value-object layer).

## Scalene corroboration (mechanism check, OPT profile)

| Frame | BASE | OPT |
|-------|------|-----|
| dataclass construction (`<exec@dataclasses.py:498>`) CPU share | 13.32% | 5.13% |
| msgspec CPU share | — | 0.00% (C-construction invisible to Scalene) |

Construction frame roughly halved (−8.18 pp); the per-field `object.__setattr__` loop is gone.

## Gate (a) — full Phase-8 stack, byte-exact

- `poetry run pytest tests/integration/test_backtest_oracle.py` → 3 passed, **134 / 46189.87730727451**
  (byte-exact + behavioral identity + determinism double-run, zero tolerance)
- `poetry run pytest tests` → **1340 passed, 0 failed**
- `poetry run mypy` (strict) → clean, 188 source files
- `pmset -g therm` clean at every checkpoint (before/during/after the full A/B + re-freeze)

## Final Phase-8 locked baselines (re-frozen cool)

- **W1: 15.736 s / 152.79 MB** → `perf/results/W1-BASELINE.json` (workload byte-identical 1578 fills / 659 closed)
- **W2 @50: 2.303 s / 163.47 MB** → `perf/results/W2-BASELINE.json` (n_bars=3000, seed=42)
- Regression guard re-run: PASS (W1 15.7 s, Δ −0.1% vs new baseline, exit 0)

## Owner sign-off

APPROVED — tiziaco (tiziano.iaco@gmail.com), 2026-06-25. See 08-06-ATTRIBUTION.md sign-off block.

## Phase-8 net (gate (b))

Relative to the pre-Phase-8 deterministic-wins baseline (08-04, W1 17.4 s), the msgspec layer adds
**+7.06% W1 / +10.64% W2@50** on top of the kept deterministic wins (Position cache +15% W1, to_dict
+2% W1). Final locked Phase-8 reference: **W1 15.736 s / W2@50 2.303 s**, oracle byte-exact throughout.

## Key files

- `.planning/phases/08-hot-path-fusion-prebuild-msgspec-gated/08-06-ATTRIBUTION.md` (created)
- `.planning/phases/08-hot-path-fusion-prebuild-msgspec-gated/08-06-SUMMARY.md` (this file)
- `perf/results/W1-BASELINE.json`, `perf/results/W2-BASELINE.json` (re-frozen, final Phase-8 reference)

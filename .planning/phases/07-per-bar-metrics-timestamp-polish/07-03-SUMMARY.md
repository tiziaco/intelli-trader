# 07-03 SUMMARY — Close Phase 7: prove Gate (a) + Gate (b)

**Plan:** 07-03 (wave 2, depends_on 07-01 + 07-02) · **Requirement:** PERF-07
**Type:** verification / measurement only · **Status:** COMPLETE
**Files modified:** `perf/results/W1-BASELINE.json` (re-frozen)

## Objective

Prove both phase gates after Plans 01+02 landed: Gate (a) byte-exact correctness and
Gate (b) the measurable W1 win. Phase 7 is byte-exact — the memoization (D-01) and the
three deletions (D-02/D-03/D-04) must change **zero** engine numbers.

## Task 1 — Gate (a): byte-exact correctness lock ✅ PASS

| Check | Command | Result |
|-------|---------|--------|
| Oracle byte-exact | `pytest tests/integration/test_backtest_oracle.py -x` | 3 passed — fresh full backtest equals frozen `tests/golden/` EXACT (no float tolerance), incl. `final_equity 46189.87730727451` / **134 trades** |
| Full suite (strict) | `poetry run pytest tests` | **1295 passed** under `filterwarnings=[error]` / `--strict-markers` / `--strict-config` (post-merge run at HEAD) |
| Typecheck | `make typecheck` | `mypy --strict` clean — Success, 188 source files |
| Determinism | oracle run ×2 | both runs pass against the identical frozen golden → reproducible |

Gate (a) holds: the deletions/memoization changed nothing in the engine numbers.

## Task 2 — Gate (b): W1 re-profile + same-machine A/B + cool-machine re-freeze ✅ PASS

**Human checkpoint resolved:** machine verified cool, re-freeze approved.

### Same-machine A/B (primary attribution — interleaved PRE/POST/PRE/POST)

PRE = commit `3bc2d55` (code-identical to pre-phase; that commit only touched STATE.md).
POST = HEAD `d53ea2b` (07-01 + 07-02 merged). Same interpreter (`.venv/bin/python`),
`PYTHONPATH` shadowing the editable install with each tree's source. Workload
**byte-identical both trees: 1578 fills / 659 closed positions.**

| | Run 1 | Run 2 | Median |
|---|---|---|---|
| PRE (unoptimized) | 33.93s | 33.59s | ~33.76s |
| POST (optimized) | 24.98s | 25.15s | ~25.07s |

**W1 wall-clock −25.7%** (33.76s → 25.07s), matching the predicted ~24% combined CPU reclaim.

### Scalene CPU-share delta (cross-check) — `scalene-w1-pre07.json` vs `scalene-w1.json`

| File (hotspot) | PRE CPU% | POST CPU% | Δ pts | Decision |
|----------------|---------:|----------:|------:|----------|
| `time_parser.py` — `_aligned` (`astimezone`/`replace`/`total_seconds`) | 8.66 | 4.05 | −4.61 | D-01 memo: per-call recompute ~halved |
| `metrics_manager.py` — debug-log eager args + `_metrics_cache.clear()` + trim | 12.06 | 1.23 | −10.83 | D-02/D-04/D-03: `.clear()` 2.92→**0**, debug line gone |
| `in_memory_storage.py` — snapshot trim copy | 5.86 | 0.00 | −5.86 | D-03: gone entirely |

Combined ~**21 CPU points** reclaimed — both attribution methods (A/B wall-clock and
Scalene CPU share) agree the win landed. All four targeted hotspots confirmed gone or
materially reduced.

### Regression guard + re-freeze

- `make perf-w1 --check` (vs prior 28.3s baseline): **W1 25.1s, Δ −11.5%**, peak_mem flat (−0.1%), exit 0 — no slowdown, guard PASS.
- `make perf-baseline` (cool, approved): re-froze `perf/results/W1-BASELINE.json` →
  **W1 19.6s / 162.2 MB**, oracle green at freeze (134 / 46189.87730727451), workload 1578/659.

### Note on the frozen number vs the A/B number

The single re-freeze run sampled 19.6s, faster than the A/B POST median (~25s) — laptop
run-to-run / scheduling variance. The **trustworthy win statement** is the same-machine
A/B (**−25.7%**) + Scalene (**−21 CPU pts**), per locked guidance
`v15-perf-gateb-thermal-drift` (never attribute via the frozen-baseline Δ% on a single
sample). The frozen 19.6s is simply the new locked reference point for the next phase.

## Deviations

- None functional. `perf/results/scalene-w1.json` / `scalene-w1-pre07.json` are gitignored
  profiling artifacts (not committed); only `W1-BASELINE.json` is tracked and changed —
  matches the plan `files_modified`.

## Self-Check: PASSED

Gate (a) byte-exact (oracle + 1295-green suite + mypy --strict + determinism) and
Gate (b) measurable, dual-attributed W1 win (−25.7% A/B, −21 CPU pts) with baseline
re-frozen on a verified-cool machine. Both gates hold.

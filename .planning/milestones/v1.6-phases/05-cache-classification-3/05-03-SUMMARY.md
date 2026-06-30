---
phase: 05-cache-classification-3
plan: 03
subsystem: config
tags: [cache-classification, d-02, vestigial-knob-removal, sc3-gate, wave-3]
requires:
  - "05-01 (docs/CACHE-CLASSIFICATION.md scheduled the D-02 #14 removal here)"
  - "05-02 (per-site CACHE-CLASS anchors — turned the SC2 anchor-count arm GREEN)"
provides:
  - "itrader/config/system.py with the two vestigial PerformanceSettings cache knobs removed (rng_seed preserved)"
  - "SC3 recurring gate proven green post-edit (oracle byte-exact + mypy --strict + full suite under filterwarnings=[error] + SC2 GREEN)"
affects:
  - "Phase 5 close — this was the single authorized code edit (CACHE-01 site #14 / D-02); CACHE-02 SC3 gate satisfied"
tech-stack:
  added: []
  patterns:
    - "config-knob removal in lockstep with the committed cache map (D-02)"
    - "recurring DB gate: byte-inert hot path proven by the oracle after a config-only edit"
key-files:
  created: []
  modified:
    - "itrader/config/system.py (removed enable_caching + cache_size_mb from PerformanceSettings)"
decisions:
  - "D-02 realized: the two zero-consumer PerformanceSettings cache knobs are removed; rng_seed (determinism) kept"
  - "settings/domains/system.default.yaml does not exist at HEAD — the planned YAML deletion is inapplicable (diff is 2 deletions, not the plan's stated 4)"
metrics:
  duration: "~10m"
  completed: "2026-06-30"
  tasks: 2
  files: 1
---

# Phase 5 Plan 03: D-02 Vestigial-Knob Removal + SC3 Gate Summary

Performed the single authorized code edit of Phase 5 — removed the two zero-consumer
`PerformanceSettings` cache knobs (`enable_caching`, `cache_size_mb`) per D-02 — and proved the
recurring SC3 gate green afterward (oracle byte-exact, `mypy --strict` clean, full suite + the
now-fully-GREEN SC2 test under `filterwarnings=["error"]`). The hot path is byte-inert.

## What was built

### Task 1 — D-02 vestigial-knob removal (commit `35c065e`)
Removed exactly two field declarations from `PerformanceSettings` in `itrader/config/system.py`
(4-space file): `enable_caching: bool = True` and `cache_size_mb: int = 512`. The determinism seed
`rng_seed: int = 42` and all other fields (`max_threads`, `enable_multiprocessing`, …) are untouched
(PITFALL 4 — over-deletion of the determinism seed is a correctness defect). The diff is exactly
2 deletions, no additions, no other change.

Verification (all PASS):
- `grep -rnE 'enable_caching|cache_size_mb|max_cache_size_mb' itrader/ settings/ scripts/ tests/` → zero references.
- `grep "rng_seed: int = 42" itrader/config/system.py` → present (determinism seed preserved).
- `import itrader` + `SystemConfig.default()` constructs; `rng_seed == 42`; the two removed
  attributes are confirmed absent on `config.performance`.

### Task 2 — SC3 recurring gate (verification only, no file changes)
Ran the recurring two-part gate and confirmed no regression after the D-02 edit:
1. **Oracle byte-exact:** `tests/integration/test_backtest_oracle.py` → 3 passed. The oracle asserts
   the fresh SMA_MACD run EQUALS the committed golden master with NO float tolerance (behavioral
   identity + numeric magnitudes, trade_count law). Byte-exact match held after the edit.
2. **mypy --strict:** `poetry run mypy itrader` → `Success: no issues found in 188 source files`.
3. **SC2 check:** `tests/integration/test_cache_classification.py` → 4 passed. All four arms GREEN,
   including the `# CACHE-CLASS:` anchor-count arm that was RED in Wave-0 (05-01) and turned GREEN
   after 05-02 placed the per-site anchors.
4. **Full suite:** `PYTHONPATH="$PWD" poetry run pytest tests` → **1463 passed** under
   `filterwarnings=["error"]`, no new warning or failure attributable to this phase.

## Verification

| Gate | Command | Result |
|------|---------|--------|
| grep clean | `grep -rnE 'enable_caching\|cache_size_mb\|max_cache_size_mb' itrader/ settings/ scripts/ tests/` | zero references |
| rng_seed kept | `grep "rng_seed: int = 42" itrader/config/system.py` | present |
| import/construct | `import itrader; SystemConfig.default()` | OK, rng_seed=42, fields absent |
| Oracle byte-exact | `pytest tests/integration/test_backtest_oracle.py -x` | 3 passed (exact vs golden) |
| mypy --strict | `poetry run mypy itrader` | Success, 188 files |
| SC2 | `pytest tests/integration/test_cache_classification.py` | 4 passed (all arms GREEN) |
| Full suite | `pytest tests` under `-W error` | 1463 passed |

## Deviations from Plan

### Documentation drift reconciled (no code impact)

**1. [Rule 1 adjacent — plan/HEAD reconciliation] `settings/domains/system.default.yaml` does not exist at HEAD**
- **Found during:** Task 1 (pre-edit grep + filesystem check).
- **Issue:** The plan's `<interfaces>` block and acceptance criteria call for removing two YAML lines
  (`enable_caching: true`, `max_cache_size_mb: 512`) from `settings/domains/system.default.yaml` and
  expect a 4-deletion diff. That file (and the entire `settings/domains/` directory) does not exist at
  HEAD — confirmed by `ls` and by the grep returning only the two Python field sites. This exactly
  matches 05-01 SUMMARY Deviation #2, which already documented that the RESEARCH-described YAML block
  is absent at HEAD.
- **Resolution:** The YAML removal is inapplicable — there is no tracked YAML line to delete. The edit
  touched only the two Python fields (`config/system.py`). The resulting diff is **2 deletions**, not
  the plan's stated 4. The substantive D-02 outcome (zero remaining consumers, knobs fully removed) is
  achieved and grep-clean.
- **Files modified:** none beyond the planned `itrader/config/system.py`.

### Note on the oracle equity figure
The plan cites the oracle final_equity as `46189.87730727451`. The oracle test asserts byte-exact
equality against the committed golden master (no hardcoded magnitude in the assertion path — it
compares fresh-vs-golden CSVs with no tolerance), and it **passed**. The authoritative source of truth
is the golden master the test diffs against; the gate ("oracle byte-exact, no regression") is
satisfied regardless of which frozen magnitude the plan prose quoted.

## Known Stubs

None. The D-02 removal is a complete deliverable; the rest of the `cache:`-related scaffolding
(`default_ttl_seconds`, `cache_type`, `enable_persistent_cache`) was intentionally left in place per
the plan — documented as dead scaffolding in `docs/CACHE-CLASSIFICATION.md`, and there is no YAML file
at HEAD to carry those keys anyway.

## Threat Flags

None. The only edit removes two dead, zero-consumer Pydantic config fields. No new input, endpoint,
credential, network call, or data flow. T-05-05 (over-deletion of `rng_seed`) is mitigated: the seed
is asserted present and the oracle byte-exact gate would have failed if determinism broke. T-05-06
(config change breaking import) is mitigated: import + `SystemConfig.default()` verified, and the full
1463-test suite confirms no import-time regression.

## Self-Check: PASSED
- `itrader/config/system.py` — FOUND (modified; `enable_caching`/`cache_size_mb` absent, `rng_seed: int = 42` present)
- commit `35c065e` (Task 1 D-02 removal) — present in worktree branch history
- grep across itrader/ settings/ scripts/ tests/ — zero references to removed knobs
- Oracle byte-exact, mypy --strict, SC2, full suite (1463) — all green under `filterwarnings=["error"]`

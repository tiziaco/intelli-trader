---
phase: 05-cache-classification-3
verified: 2026-06-30T14:00:00Z
status: passed
score: 9/9 must-haves verified
overrides_applied: 0
re_verification: null
gaps: []
deferred: []
human_verification: []
---

# Phase 5: Cache Classification Verification Report

**Phase Goal:** Every ad-hoc cache / `lru_cache` across `itrader/` is inventoried and classified (a/b/c) with routing decisions documented and the v1.5 hot path left unchanged — classify, do not rewrite or unify.
**Verified:** 2026-06-30T14:00:00Z
**Status:** passed
**Re-verification:** No — initial verification

---

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | `docs/CACHE-CLASSIFICATION.md` exists, is committed, and classifies every live cache site (a/a-infra/a-engine/b/c/c-config/d) with file:line references grouped by class | ✓ VERIFIED | File at 199 lines; 14 live sites across all 7 classes confirmed by reading the doc |
| 2 | The three Phase-4 `CachedSql*Storage._cache` caches carry class (d) with Phase-4 D-04 pointer | ✓ VERIFIED | Sites d1/d2/d3 in the map; prose table cites "Phase-4 D-04 / RETAIN-01/02/03" for each |
| 3 | The Q7 "do NOT unify into one Arrow-backed object" decision is recorded, cross-referenced to FEATURES anti-features and PITFALLS Pitfall 3, and cites §Q8 | ✓ VERIFIED | `docs/CACHE-CLASSIFICATION.md:27-39` — DECISION block present; "FEATURES.md — anti-features" and "PITFALLS.md — Pitfall 3" cross-refs present; "§Q8" cited at line 47 |
| 4 | "classify, do not rewrite or unify" boundary statement is present; class (a)/(b)/(c) sites are marked LEAVE ALONE or documentation-only | ✓ VERIFIED | Boundary statement at doc line 17; every class section opens with a LEAVE ALONE / documentation-only paragraph |
| 5 | The SC2 test exists and passes all 4 arms under `filterwarnings=["error"]` | ✓ VERIFIED | `PYTHONPATH=$PWD poetry run pytest tests/integration/test_cache_classification.py -v` → 4 passed, 0 failed |
| 6 | `grep -rn "CACHE-CLASS:" itrader/` returns exactly 14 anchors, each in a file named in the doc's machine-readable live-site block | ✓ VERIFIED | 14 anchors confirmed by direct grep; all 12 files match the doc inventory |
| 7 | No class-(a) hot-path logic, class-(b) index logic, or class-(c) memo body was changed — only inert comment lines + 2 config field deletions | ✓ VERIFIED | Code review (05-REVIEW.md) confirms: "every other change is a single inert `# CACHE-CLASS:` comment line"; oracle 3/3 byte-exact proves hot-path inertness |
| 8 | `PerformanceSettings.enable_caching` and `cache_size_mb` are removed from `itrader/config/system.py`; `rng_seed: int = 42` is untouched | ✓ VERIFIED | `grep -n "rng_seed\|enable_caching\|cache_size_mb" itrader/config/system.py` returns only the `rng_seed` line; zero hits for removed fields |
| 9 | Recurring gates: SMA_MACD oracle byte-exact, `mypy --strict` clean, full suite green under `filterwarnings=["error"]` | ✓ VERIFIED | Oracle: 3 passed; mypy: "Success: no issues found in 210 source files"; full suite: 1463 passed |

**Score:** 9/9 truths verified

---

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `docs/CACHE-CLASSIFICATION.md` | Authoritative committed cache-classification map (CACHE-01/SC1, D-01 home #1) | ✓ VERIFIED | 199 lines; grouped-by-class layout; 14 live sites + 2 removed; Q7 decision; D-02 note; machine-readable block |
| `tests/integration/test_cache_classification.py` | Runnable SC2 grep-matches-inventory assertion (4 arms) | ✓ VERIFIED | 4 passed, 0 failed; no `__init__.py` (package-less); pathlib+re only; no warnings emitted |
| `itrader/config/system.py` | D-02: `enable_caching` and `cache_size_mb` removed; `rng_seed: int = 42` kept | ✓ VERIFIED | Fields absent; rng_seed present; `SystemConfig.default()` constructs |
| 14 `# CACHE-CLASS:` anchors across 12 `itrader/` source files | D-01 home #2: drift-proof per-site anchors | ✓ VERIFIED | `grep -rn "CACHE-CLASS:" itrader/` returns exactly 14 lines across 12 files |

---

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `tests/integration/test_cache_classification.py` | `docs/CACHE-CLASSIFICATION.md` | `_live_inventory()` parses machine-readable block; anchors cross-checked against doc | ✓ WIRED | `_DOC_PATH = _REPO_ROOT / "docs" / "CACHE-CLASSIFICATION.md"` confirmed; all 4 arms doc-driven |
| `docs/CACHE-CLASSIFICATION.md` | `.planning/research/ARCHITECTURE.md §Q8` | "promoted from `§Q8`" citation and source attribution | ✓ WIRED | Doc line 47: "from **`§Q8`** of `.planning/research/ARCHITECTURE.md`" |
| 14 source-file anchors | `docs/CACHE-CLASSIFICATION.md` | `— see docs/CACHE-CLASSIFICATION.md` in each anchor comment | ✓ WIRED | Confirmed via grep output: every anchor line ends with `— see docs/CACHE-CLASSIFICATION.md` |

---

### Data-Flow Trace (Level 4)

Not applicable. This phase delivers documentation artifacts and inert code annotations. No dynamic data rendering or runtime data flows involved.

---

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| SC2 test all 4 arms green | `PYTHONPATH=$PWD poetry run pytest tests/integration/test_cache_classification.py -v` | 4 passed | ✓ PASS |
| Oracle byte-exact (134 trades) | `poetry run pytest tests/integration/test_backtest_oracle.py -q` | 3 passed | ✓ PASS |
| mypy --strict over itrader | `poetry run mypy itrader` | Success: no issues found in 210 source files | ✓ PASS |
| Full suite under filterwarnings=["error"] | `PYTHONPATH=$PWD poetry run pytest tests -q --tb=no` | 1463 passed | ✓ PASS |
| D-02 grep clean (tracked code) | `grep -rnE "enable_caching\|cache_size_mb\|max_cache_size_mb" itrader/ scripts/ tests/` | zero hits | ✓ PASS |
| CACHE-CLASS anchor count | `grep -rn "CACHE-CLASS:" itrader/` | exactly 14 anchors | ✓ PASS |

---

### Probe Execution

No probe scripts declared for this phase. Step 7c: SKIPPED (documentation/annotation phase — no executable probes).

---

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|-------------|-------------|--------|---------|
| CACHE-01 | 05-01, 05-02 | Every ad-hoc cache / `lru_cache` / scattered in-memory lookup inventoried and classified (a/b/c) as documented classification + routing, not a rewrite | ✓ SATISFIED | `docs/CACHE-CLASSIFICATION.md` classifies all 14 live sites; 14 CACHE-CLASS anchors provide the D-01 home #2 drift anchor; SC2 test 4/4 green |
| CACHE-02 | 05-01, 05-02, 05-03 | v1.5 hot path left unchanged; Q7 no-Arrow decision recorded and cross-referenced; grep surface matches inventory exactly | ✓ SATISFIED | Q7 DECISION block in doc; review confirmed comment-only diffs on all hot-path files; oracle byte-exact 3/3; SC2 arms 1/2/3/4 all green |

---

### Anti-Patterns Found

No debt-marker comments (TBD/FIXME/XXX) introduced by this phase. No placeholder return stubs. No float-for-money. The three code-review findings all affect the documentation deliverable, not the classification correctness or runtime behavior:

| File | Issue | Severity | Impact on Phase Goal |
|------|-------|----------|---------------------|
| `docs/CACHE-CLASSIFICATION.md` (prose tables + machine-readable block) | WR-01: cited `file:line` references are off by 1-2 at HEAD because 05-02 anchors were inserted above definition lines, shifting them down — the doc claims "line numbers re-verified" but was written before anchors were placed | ⚠ Warning | Non-blocking. Classifications are correct; all 14 sites correctly identified and classed. A reader navigating to the cited line lands on the anchor comment (1-2 lines above the definition) rather than the definition itself. SC2 test does not guard line numbers (only file membership + count), so this drift is not caught automatically. The doc's core deliverable — complete, correct classification — is intact. |
| `tests/integration/test_cache_classification.py` (lines 15-17, 149-153, 160-162) | WR-02: module docstring and test docstring still describe the anchor arm as "EXPECTED RED until 05-02" and "Wave-0 RED state" — but 05-02 has run and all 4 arms are GREEN | ⚠ Warning | Non-blocking. The test passes correctly; the misleading commentary describes the pre-05-02 state and could confuse a future maintainer. No behavioral impact. |
| `docs/CACHE-CLASSIFICATION.md:163-166` | IN-01: doc asserts "settings/domains/system.default.yaml does not exist" — an untracked local copy exists on disk (gitignored at `.gitignore:60`). The operative scoped claim ("no *tracked* YAML sets these keys") is correct and the conclusion ("no migration required") holds via Pydantic `extra="ignore"` | ℹ Info | Non-blocking. The D-02 removal is complete on all tracked files; the untracked YAML contains a mis-keyed variant (`max_cache_size_mb`) that Pydantic silently drops. The factual phrasing "does not exist" is wrong at the file-system level but the operative claim and migration conclusion are both correct. |

**Debt-marker gate:** No TBD/FIXME/XXX markers introduced. Gate: PASS.

---

### Review Findings — Impact Assessment

The code review (05-REVIEW.md, 0 Blocker / 2 Warning / 1 Info) reached the same conclusion: "The functional goal of the phase is met." My independent assessment confirms this judgment:

**WR-01 (stale line numbers):** The success criteria require "every ad-hoc cache inventoried and tagged" with "documented classification + routing." The classifications ARE correct. The line number references in the prose tables are navigation aids pointing to specific code locations; being off by 1-2 lines due to anchor insertion is a quality defect, not a classification incompleteness. The SC2 test's "grep surface matches inventory exactly" is measured by the SC2 test itself (4/4 green), which checks file membership and count — not line accuracy. The phase goal does not specify line-number accuracy as a success condition. **NOT A BLOCKER.**

**WR-02 (stale test docstring):** The test passes and correctly guards against new undocumented caches. The misleading "EXPECTED RED" framing is in comments only. **NOT A BLOCKER.**

**IN-01 (file existence claim):** The D-02 removal is complete on all tracked code (`itrader/`, `scripts/`, `tests/`). The untracked settings file is gitignored and its content is inert (Pydantic drops unknown keys). The migration conclusion is correct. **NOT A BLOCKER.**

---

### Human Verification Required

None. All success criteria are programmatically verifiable:
- Classification completeness: read doc + count sites
- Classification correctness: reviewed against ARCHITECTURE.md §Q8 + code review
- SC2 test: runs and passes
- Hot-path inertness: oracle byte-exact
- mypy + suite: automated gates

---

### Gaps Summary

No gaps. All 9 must-have truths are VERIFIED. Both CACHE-01 and CACHE-02 requirements are SATISFIED. The three review findings (WR-01, WR-02, IN-01) are documentation quality issues that do not block the phase goal:

- The cache inventory is complete (all 14 live sites classified).
- The routing decisions are documented (Q7 no-Arrow, classify-not-rewrite, per-class LEAVE ALONE / documentation-only tags).
- The hot path is byte-inert (oracle 3/3, review confirms comment-only diffs).
- The drift guard exists and passes (SC2 4/4 green).
- D-02 vestigial-knob removal is complete and grep-clean on tracked code.

The three non-blocking findings from the code review are candidly surfaced above for the maintainer's awareness. They represent polish work that would strengthen the doc's self-consistency, but do not prevent the phase goal from being achieved.

---

_Verified: 2026-06-30T14:00:00Z_
_Verifier: Claude (gsd-verifier)_

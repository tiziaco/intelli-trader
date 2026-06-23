# Phase 1: Perf Tooling & Baseline - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-06-23
**Phase:** 1-perf-tooling-baseline
**Areas discussed:** Baseline freeze artifact + guard, Gate (b) measurement rigor, Cross-validation scope (TOOL-03), Runner output/invocation contract

---

## Baseline freeze artifact + regression guard

| Option | Description | Selected |
|--------|-------------|----------|
| JSON file + soft guard | `perf-baseline` writes committed `perf/results/W1-BASELINE.json`; `perf-w1` prints delta + soft regression guard fails on slowdown beyond tolerance | ✓ |
| JSON file, manual compare | Write the committed JSON but no auto-assert; human reads delta each phase | |
| Markdown number only | Frozen number documented in PERF-BASELINE-RESULTS.md; fully manual, no machine-readable artifact | |

**User's choice:** JSON file + soft guard
**Notes:** The JSON file IS "the locked reference" every later phase diffs against. "Soft" guard = a tooling assert that protects the gate, kept separate from the byte-exact oracle (which stays the correctness lock).

---

## Gate (b) measurement rigor

| Option | Description | Selected |
|--------|-------------|----------|
| Best-of-N + noise band | Run N times, report min + median; pass only if it beats frozen median beyond a noise band | |
| Single run + tolerance | One timed run; "measurable" = improvement beyond a fixed ±X% tolerance | ✓ |
| You decide | Let planning pick N and threshold from observed variance | |

**User's choice:** Single run + tolerance — **threshold ≥5%**
**Notes:** Each phase targets a large named CPU chunk (37% / 13% / 24%), so genuine wins clear the ~1–2% run-to-run noise easily. ≥5% chosen as the confident-real-win bar. This is a milestone-wide bar inherited by Phases 2–6. Peak memory tracked alongside (no separate threshold).

---

## Cross-validation scope (TOOL-03)

| Option | Description | Selected |
|--------|-------------|----------|
| Drop TOOL-03 entirely | Remove cross-val runners + `perf-crossval`; correctness proven by the byte-exact oracle; v1.0 evidence stays valid; updates REQUIREMENTS/ROADMAP | ✓ |
| Keep as one-shot sanity | Non-repeatable on-demand evidence refresh of the v1.0 numerical cross-val | |
| Keep TOOL-03 as specified | Build the repeatable numerical cross-val runners (belt-and-suspenders) | |

**User's choice:** Drop TOOL-03 entirely
**Notes:** User opened this — questioned whether comparing a vectorized framework (backtesting.py/backtrader) to event-driven iTrader makes sense ("as we said in another session"). Disentangled: W1/W2 are iTrader-only timing runs (gate (b) — kept); the framework comparison only lived in the not-yet-built TOOL-03 cross-val. In a behavior-preserving milestone the byte-exact oracle proves correctness by *invariance*, so external numerical agreement adds no signal, and a *speed* comparison to a vectorized engine is apples-to-oranges. Authorized the requirements ripple (REQUIREMENTS.md / ROADMAP.md / v1.5-ROADMAP.md). Phase 1 now carries 3 requirements (TOOL-01/02/04).

---

## Runner output / invocation contract

| Option | Description | Selected |
|--------|-------------|----------|
| --json + pin frozen window | Add `--json` structured emit (feeds baseline file + soft-guard delta), keep stdout summary; pin the 2-month frozen window (2026-04-23→06-23) as the perf-w1/perf-baseline default; env still overrides | ✓ |
| --json, keep 6-mo default | Add `--json` but keep current 6-month default window; gated slice set via env each run | |
| You decide | Let planning settle flags + default window | |

**User's choice:** --json + pin frozen window
**Notes:** Makes the gated number reproducible with no env vars to remember; `W1_START_DATE`/`W1_END_DATE` overrides preserved for ad-hoc slices.

---

## Claude's Discretion

- Exact JSON schema/field names of `W1-BASELINE.json`, the soft-guard failure-message wording, and how `perf-w2` surfaces its scaling table — within D-01/D-02/D-06.
- Whether the soft-guard lives inside the runner (`--json` compare mode) or a thin `perf-check` wrapper — the contract (D-02) is what matters.

## Deferred Ideas

- Cross-validation against external frameworks — dropped from v1.5; revive the v1.0 force-match methodology only for a future result-changing re-baseline.
- Best-of-N / median timing — revisit only if observed variance exceeds the ≥5% band.
- 100/200-symbol W2 scaling point (PERF-08, v2/deferred) — only if large universes become a target.

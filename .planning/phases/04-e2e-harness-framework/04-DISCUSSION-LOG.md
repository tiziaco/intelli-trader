# Phase 4: E2E Harness & Framework - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-06-09
**Phase:** 4-E2E Harness & Framework
**Areas discussed:** Scenario contract shape, Scenario spec/strategy + SMA_MACD relocation, Golden fixture format & output location, Scenario input data, Phase-4 scope & canary, Freeze flow, Subsystem folder grouping, Marker & make-target wiring, Shared serialization seam, scenario.py config composition

---

## Scenario Contract Shape

| Option | Description | Selected |
|--------|-------------|----------|
| Per-folder one-line test | Each leaf has its own test_*.py calling a shared run_scenario fixture in conftest.py; descendant of backtest_engine factory; self-contained; parallel-safe | ✓ |
| Auto-discovered (parametrized) | One parametrized collector walks folders → 30 nodes, no per-folder Python; least boilerplate but the collector is a shared "clever" piece | |
| Declarative manifest | scenario.py/yaml dict the harness reads; dropped — a strategy is code, needs a registry to express declaratively | |

**User's choice:** Per-folder one-line test calling shared run_scenario fixture.
**Notes:** User explicitly wanted to keep it simple and build on the existing pytest system / continuity with the existing test infrastructure. Recommendation reasoning: pytest continuity + literal E2E-03 satisfaction + Phase 6 parallel-wave safety (adding a scenario edits only its own folder).

---

## Scenario Spec / Strategy + SMA_MACD Relocation

| Option | Description | Selected |
|--------|-------------|----------|
| Spec object + defer SMA_MACD to Phase 5 | Per-folder scenario.py typed spec; shared tests/e2e/strategies/ library; SMA_MACD relocation deferred to Phase 5 | ✓ |
| Spec object + move SMA_MACD now | Same, but relocate SMA_MACD in Phase 4 (touches run_backtest.py + 5 tests + golden re-prove) | |
| Spec object + leave SMA_MACD permanently | Same, but SMA_MACD stays in itrader/ forever | |

**User's choice:** Spec object + defer SMA_MACD to Phase 5.
**Notes:** User liked the Python spec object (option 1 of the original 3) but raised that strategies will be reused across scenarios, so they shouldn't be defined inline — proposed a shared strategy folder, and proposed moving SMA_MACD into the e2e tree as "not a production strategy." Verified: SMA_MACD is the committed oracle strategy (imported by scripts/run_backtest.py + 5 test files; Phase 5 re-validates byte-exact against it). Resolution: build the shared e2e strategy library now; defer SMA_MACD relocation to Phase 5 (its natural home), with a caveat that destination needs care (run_backtest.py would otherwise import from tests/).

---

## Golden Fixture Format & Output Location

| Option | Description | Selected |
|--------|-------------|----------|
| Diff-what's-frozen, in-memory, golden/ subfolder | Produce all in memory, diff only golden files present; default trades+summary, equity opt-in; no output/ in leaf | ✓ |
| Always freeze + diff all three | Uniform trades+equity+summary every scenario; noisier goldens, harder to hand-verify | |
| You decide | Left to planning within constraints | |

**User's choice:** Diff-what's-frozen, in-memory, golden/ subfolder.
**Notes:** User asked what's best and where scenario results are saved (an output folder per leaf?). Reframed: trades+summary default (summary already carries final_equity + metrics block), equity opt-in for Phase 9 path-sensitive cases. No committed output/ folder — fresh results in-memory, tmp_path only if disk debugging needed (parallel-safe). Only the freeze step writes into golden/.

---

## Scenario Input Data

| Option | Description | Selected |
|--------|-------------|----------|
| Committed contrived leaf-local + shared tests/e2e/data/ | Contrived tiny CSVs in leaf; reusable inputs (BTCUSD slice, real datasets) shared; real CsvPriceStore; contrived not sliced for fills | ✓ |
| Single shared sliced BTCUSD for scenarios | One short slice across scenarios; can't produce controllable hand-computable fills | |
| You decide | Left to planning within constraints | |

**User's choice:** Committed contrived leaf-local + shared tests/e2e/data/.
**Notes:** User liked committed CSV files and asked about a tests/data folder slicing the real BTCUSD. Flagged the key correctness nuance: slices can't produce limit-touch/gap-through/OCO-priority on demand (works against hand-verify-once), so fill scenarios use contrived bars; slices only fit canary/smoke. Shared folder structured like the strategy library (leaf-local for specific, shared for reusable).

---

## Phase-4 Scope & Canary

| Option | Description | Selected |
|--------|-------------|----------|
| One contrived canary scenario | One minimal hand-verifiable scenario proving the harness scaffolding + copy-template | ✓ |
| Canary using the shared BTCUSD slice | Realistic data, but golden trades not hand-derivable; less useful as template | |
| Zero scenarios — pure infra | Leanest, but harness unproven until Phase 6, no template | |

**User's choice:** One contrived canary scenario.
**Notes:** A canary proves the new e2e scaffolding (marker, make target, run_scenario, scenario.py, golden/ diff, warning-clean) is wired right — the engine itself is already proven by test_backtest_oracle.py. Doubles as the Phase 6-9 copy-template.

---

## Freeze Flow (hand-verify-once-then-freeze, E2E-04)

| Option | Description | Selected |
|--------|-------------|----------|
| --freeze flag + per-scenario VERIFY note | Diff-only normal runs, deliberate --freeze writes goldens; committed hand-derivation note per scenario | ✓ |
| --freeze flag only | Regen flag, no required derivation note; weaker on "verified for correctness" | |
| VERIFY note only, manual golden files | Strong note, but ad-hoc/error-prone golden regen | |

**User's choice:** Deliberate --freeze flag + per-scenario VERIFY note.
**Notes:** Goldens never auto-heal (drift fails); regen is a deliberate flag; each scenario commits a short hand-derivation (VERIFY.md or scenario.py docstring) — the human-verification artifact a reviewer checks. Mirrors tests/golden/REFREEZE-*.md.

---

## Subsystem Folder Grouping

| Option | Description | Selected |
|--------|-------------|----------|
| By engine subsystem | Stable domain dirs (matching/cost/sizing/sltp/admission/position/cash/multi/robustness/metrics); maps to Phase 6-9 clusters | ✓ |
| By phase | phaseN_* dirs; brittle, couples tree to roadmap ordering | |
| You decide | Left to planning within constraints | |

**User's choice:** By engine subsystem.
**Notes:** Exact dir names/depth left to planning, subject to subsystem-grouped + stable names.

---

## Marker & Make-Target Wiring

| Option | Description | Selected |
|--------|-------------|----------|
| e2e marker (not slow), in default test, + make test-e2e | Folder-derived e2e marker; tiny scenarios so not slow; stays in make test; make test-e2e focused bucket | ✓ |
| e2e excluded from default test | make test runs -m 'not e2e'; e2e only via make test-e2e; regressions not in default run | |
| You decide | Left to planning within constraints | |

**User's choice:** e2e marker (not slow), in default test, + make test-e2e.
**Notes:** Extend the existing tests/conftest.py auto-marking hook; register e2e in pyproject. Scenarios are ~10 bars so not slow → stay in default suite for regression safety.

---

## Shared Serialization Seam

| Option | Description | Selected |
|--------|-------------|----------|
| Extract to shared itrader.reporting | Move build_summary/build_metrics_block/attach_slippage out of run_backtest.py; parameterize constants; both oracle + harness import one path | ✓ |
| Harness re-implements its own | Leave run_backtest.py untouched; risks format drift | |
| You decide | Left to planning within constraints | |

**User's choice:** Extract to shared itrader.reporting.
**Notes:** build_trade_log/build_equity_curve already shared; the summary/metrics/slippage assembly is stranded in scripts/run_backtest.py. Extraction must stay oracle-dark (guarded by test_backtest_oracle.py). CLAR-02 cleanup along a touched path.

---

## scenario.py Config Composition

| Option | Description | Selected |
|--------|-------------|----------|
| Thin ScenarioSpec reusing real config models | Fields are real engine types (strategies, PortfolioConfig list, ExchangeConfig, data, window); lists for multi-entity | ✓ |
| Raw kwargs/dicts | Loose dicts translated in run_scenario; untyped, can drift | |
| You decide | Left to planning within constraints | |

**User's choice:** Thin ScenarioSpec reusing real config models.
**Notes:** No parallel config schema; reuses production config; lists handle Phase 9 multi-strategy/multi-portfolio.

---

## Claude's Discretion

- Exact tests/e2e/ directory names/depth (subsystem-grouped).
- Exact ScenarioSpec field set + run_scenario signature.
- VERIFY artifact form (VERIFY.md vs scenario.py docstring).
- How contrived CSVs are authored (hand-written vs small emit-helper).
- Precise --freeze mechanism (pytest option vs env var).
- Canary's exact strategy/data shape.

## Deferred Ideas

- Relocate SMA_MACD_strategy.py out of itrader/ → Phase 5 (destination needs care re: run_backtest.py importing from tests/).
- Actual E2E scenario coverage → Phases 6-9.
- Real ETH/SOL/AAVE differing-spans E2E run → Phase 9 (ROBUST), via this harness, using full committed datasets.

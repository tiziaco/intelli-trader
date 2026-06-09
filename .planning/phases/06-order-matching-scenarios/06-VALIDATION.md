---
phase: 6
slug: order-matching-scenarios
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-06-09
---

# Phase 6 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 8.x (E2E marker `e2e`; Phase 4 harness `run_scenario`) |
| **Config file** | `pyproject.toml` (`[tool.pytest.ini_options]`, `filterwarnings=["error"]`); `tests/e2e/conftest.py` (harness + `--freeze`) |
| **Quick run command** | `poetry run pytest tests/e2e/matching/<leaf> -v` (single leaf) |
| **Full suite command** | `poetry run pytest tests/e2e/matching/ tests/integration/test_backtest_oracle.py -v` |
| **Estimated runtime** | ~5–20 seconds (contrived bars are tiny; oracle gate adds a few s) |

---

## Sampling Rate

- **After every task commit:** Run the leaf's `poetry run pytest tests/e2e/matching/<leaf> -v`
- **After shared-infra changes:** Run `poetry run pytest tests/integration/test_backtest_oracle.py -v` (the oracle MUST stay byte-exact — `on_tick=None` default)
- **After every plan wave:** Run the full E2E matching suite + oracle gate
- **Before `/gsd:verify-work`:** Full suite must be green AND every scenario `--freeze`-locked
- **Max feedback latency:** 20 seconds

---

## Per-Task Verification Map

> Leaf scenarios are golden-locked: the automated proof is "the frozen golden set matches a fresh run" (exact no-tolerance diff, Phase 4 D-08). Each leaf is its own one-line per-folder test. Threat refs N/A — this is a test-authoring phase exercising existing engine behavior (no new attack surface; security gate satisfied by the no-new-production-surface argument in each PLAN's `<threat_model>`).

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 06-01-* | 01 | 1 | (shared infra) + MATCH-01 | — | N/A (test infra; `on_tick=None` keeps oracle byte-exact) | e2e + oracle | `poetry run pytest tests/e2e/matching/market_next_bar_open tests/integration/test_backtest_oracle.py -v` | ❌ W0 | ⬜ pending |
| 06-02-* | 02 | 2 | MATCH-02, MATCH-03 | — | N/A | e2e golden | `poetry run pytest tests/e2e/matching/ -k "limit or stop" -v` | ❌ W0 | ⬜ pending |
| 06-03-* | 03 | 2 | MATCH-04, MATCH-05 | — | N/A | e2e golden (orders-snapshot) | `poetry run pytest tests/e2e/matching/ -k "bracket or priority" -v` | ❌ W0 | ⬜ pending |
| 06-04-* | 04 | 2 | MATCH-06 | — | N/A | e2e golden | `poetry run pytest tests/e2e/matching/ -k "gap" -v` | ❌ W0 | ⬜ pending |
| 06-05-* | 05 | 2 | MATCH-07, MATCH-08 | — | N/A (operator `on_tick` actions) | e2e golden (orders-snapshot) | `poetry run pytest tests/e2e/matching/ -k "modify or cancel or never_fill" -v` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

*Wave/plan/leaf grouping is indicative — the planner sets the final slice (D-11 one-leaf-per-fill-shape, D-12 batched verify clusters, D-13 foundational plan first).*

---

## Wave 0 Requirements

- [ ] `tests/e2e/strategies/scripted_emitter.py` — generic parametrized scripted-emitter (D-01/D-04, generalizes `single_market_buy.py`)
- [ ] Shared `ScenarioSpec`/`Action` module under `tests/e2e/` — promoted from per-leaf (RESEARCH gap #4) to carry the `actions` timeline (D-06/D-07)
- [ ] `tests/e2e/conftest.py` — `on_tick` driving + orders-snapshot opt-in diff wiring (mirrors `equity.csv` opt-in branch)
- [ ] Orders-snapshot serializer in `itrader/reporting/` (D-08: business columns only, no UUID/wall-clock)
- [ ] `on_tick=None` hook on `TradingSystem._run_backtest`/`run()` (oracle-inert default)

*Shared infra is built and committed FIRST in the D-13 foundational plan (non-parallel), before the parallel scenario wave — parallel leaves must not edit shared files.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Hand-derivation of each scenario's expected fill (trigger/open price, fill quantity, OCO outcome) before `--freeze` | MATCH-01..08 | Golden correctness cannot be self-asserted by the test — a wrong golden would freeze wrong behavior. Each leaf's VERIFY note must be hand-checked against `bars.csv` + the documented `_evaluate` fill formula. | Per D-12: review in ~4 requirement-cluster sittings (entries 01/02/03; brackets+OCO+priority 04/05; gaps 06; modify/cancel/never-fill 07/08). Confirm VERIFY note math, then `--freeze`. |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify (golden diff) or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references (shared infra in foundational plan)
- [ ] No watch-mode flags
- [ ] Feedback latency < 20s
- [ ] Oracle gate (`test_backtest_oracle.py`) green after every shared-infra change
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending

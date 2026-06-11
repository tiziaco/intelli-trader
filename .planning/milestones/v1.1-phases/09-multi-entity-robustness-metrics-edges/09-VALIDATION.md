---
phase: 9
slug: multi-entity-robustness-metrics-edges
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-06-10
---

# Phase 9 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.
> Derived from `09-RESEARCH.md` § Validation Architecture. This is a **coverage phase** —
> the behavior space is the multi-entity × robustness × degenerate-metrics matrix; the ~8
> hand-verified leaves are the SAMPLES and the ROBUST-04 double-run test is the
> sampling-adequacy proof that each sample is itself reproducible.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 8.4.2 (`testpaths=["tests"]`, `--strict-markers`, `filterwarnings=["error"]`) |
| **Config file** | `pyproject.toml [tool.pytest.ini_options]` |
| **Quick run command** | `poetry run pytest tests/e2e/<cluster> -m e2e -x` |
| **Full suite command** | `make test` (full) / `make test-e2e` (e2e only) |
| **Estimated runtime** | ~tiny per leaf (hand-sized fixtures); full e2e tree seconds |

---

## Sampling Rate

- **After every task commit:** Run the leaf's own `poetry run pytest tests/e2e/<leaf> -m e2e -x`
- **After every plan wave:** Run `make test-e2e` (full e2e tree) + the determinism test
- **Before `/gsd:verify-work`:** `make test` full suite green — **including the BTCUSD oracle byte-exact** (`make test-integration`) after the per-portfolio serializer lands
- **Max feedback latency:** seconds (tiny contrived/sliced fixtures)

---

## Per-Task Verification Map

> Requirement → sampled behavior → automated command. "File Exists" ❌ = produced by a Wave
> leaf or the foundational plan (Wave 0), not pre-existing.

| Requirement | Behavior sampled | Test Type | Automated Command | File Exists |
|-------------|------------------|-----------|-------------------|-------------|
| MULTI-01 | one strategy, two tickers (rides existing `trades.csv` `pair` column) | e2e leaf | `pytest tests/e2e/multi/two_tickers -m e2e` | ❌ Wave |
| MULTI-02 | two strategies, one portfolio | e2e leaf | `pytest tests/e2e/multi/two_strategies -m e2e` | ❌ Wave |
| MULTI-03 | one strategy → >1 portfolio, cash isolation (per-portfolio snapshot) | e2e leaf | `pytest tests/e2e/multi/fanout_portfolios -m e2e` | ❌ Foundational canary + serializer |
| MULTI-04 | two strategies contend for one portfolio's cash (cash-ledger REJECTED) | e2e leaf | `pytest tests/e2e/multi/contended_cash -m e2e` | ❌ Wave |
| ROBUST-01 | SOL absent bar (2023-06-24 / 2023-06-25) → no fill, no crash | e2e leaf (real sliced) | `pytest tests/e2e/robust/sparse_bar -m e2e` | ❌ Wave |
| ROBUST-02 | AAVE mid-run listing (2021-07-15) + differing ends, union window | e2e leaf (real sliced) | `pytest tests/e2e/robust/union_window -m e2e` | ❌ Wave |
| ROBUST-03 | no-trade / flat / losing → finite metrics + explicit no-NaN/no-inf | 3 e2e leaves | `pytest tests/e2e/robust/{no_trade,flat,losing} -m e2e` | ❌ Wave + no-NaN guard (foundational) |
| ROBUST-04 | double-run byte-identical across all new scenarios | parametrized determinism test | `pytest tests/e2e/robust/test_determinism.py -m e2e` | ❌ Foundational (double-run scaffold) |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky — all ⬜ pending at plan time.*

---

## Wave 0 Requirements (foundational plan — D-06)

- [ ] `tests/e2e/conftest.py` — per-portfolio snapshot serializer + `exists()`-gated opt-in wiring in `_assemble`/`_freeze`/`_diff` (D-01); keyed on `PortfolioSpec.name`, NOT the UUIDv7 `PortfolioId`; out of core `TRADE_COLUMNS`
- [ ] `tests/e2e/robust/test_determinism.py` (+ exposing `_build_and_run`/`_assemble` from conftest) — in-process double-run self-compare scaffold (D-04)
- [ ] No-NaN / no-inf guard helper for the ROBUST-03 degenerate leaves (D-05)
- [ ] ONE canary leaf (MULTI-03 fanout candidate) proving the wiring end-to-end
- [ ] BTCUSD oracle re-run byte-exact (`make test-integration`) after the serializer lands

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Per-leaf VERIFY hand-derivation | all leaves | A frozen golden proves *stability*, not *correctness* — ground truth must be hand-derived BEFORE `--freeze` | Author each leaf's VERIFY note (mirroring `smoke/single_market_buy/scenario.py`) deriving expected fills/cash/metrics by hand, then `--freeze` to lock |

---

## Undersampled Edges (flagged for the planner)

- **MULTI-03 isolation** is asserted by roll-up, not trade-level. Two portfolios with *identical* cash/trades would still pass if the engine accidentally shared state but produced symmetric numbers. **MITIGATION:** author the two fanout portfolios with **asymmetric starting cash** (e.g. 10_000 vs 5_000) so A's numbers are provably ≠ B's.
- **MULTI-04** is one bar / one contention — does not sample the loser *recovering* on a later bar. Likely out-of-shape for one leaf; fold only if a contrast is the point (D-01 discretion).
- **ROBUST-02 union window** can show mid-run-listing OR differing-end-dates cleanly in one leaf. Consider whether one slice shows BOTH or whether two folds are clearer (one-shape-per-leaf favors NOT cramming both).
- **ROBUST-01** absent-bar should be positioned so a signal/position is **live across the gap** (proving no fill AND no crash on the matching path), not merely a warmup gap where nothing is at stake.

---

## Validation Sign-Off

- [ ] All requirements have an automated e2e leaf or Wave 0 (foundational) dependency
- [ ] Sampling continuity: every leaf carries its own `pytest -m e2e` command
- [ ] Wave 0 covers all MISSING references (serializer, double-run scaffold, no-NaN guard, canary, oracle re-run)
- [ ] No watch-mode flags
- [ ] Feedback latency < seconds (tiny fixtures)
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending

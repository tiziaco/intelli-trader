---
phase: 5
slug: incremental-indicators-fragile-oracle-gated-last
status: ready
nyquist_compliant: true
wave_0_complete: false
created: 2026-06-24
updated: 2026-06-24
---

# Phase 5 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 8.x (Poetry) — `filterwarnings=["error"]`, `--strict-markers`, `--strict-config`; only `unit`/`integration`/`slow`/`e2e` markers (folder-derived, NO decorator) |
| **Config file** | `pyproject.toml` (`[tool.pytest.ini_options]`) |
| **Quick run command** | `poetry run pytest tests/unit/strategy -q` |
| **Full suite command** | `poetry run pytest tests` (NOT `make test` — it exports `ITRADER_DISABLE_LOGS=true` and breaks caplog tests; MEMORY note) |
| **Oracle gate** | `poetry run pytest tests/integration/test_backtest_oracle.py -x -q` (oracle lives in `tests/integration/`; `tests/golden/` = 0-collected artifacts) |
| **Static gate** | `poetry run mypy itrader` (`--strict`, 187 files) |
| **Worktree note** | prepend `PYTHONPATH="$PWD"` (editable-install shadowing); run the oracle/full suite in the MAIN checkout (worktree `make test` aborts on missing `.env`) |

---

## Sampling Rate

- **After every task commit:** `poetry run pytest tests/unit/strategy -q` (fast indicator unit + convergence).
- **After every plan wave:** `poetry run pytest tests` (full suite via Poetry) + `poetry run mypy itrader`.
- **Before `/gsd:verify-work` (phase gate):** oracle green + cross-val PASS confirmed (P5-D02) + golden re-frozen + determinism double-run byte-identical + `make perf-w1` shows the locked W1 improvement (Gate b).
- **Max feedback latency:** ~5–10 s per task commit (unit subset); full suite ~minutes (oracle backtest dominates).

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| A-T1 | 05-01 | 1 | PERF-05 | T-05A-02 | Capacity keys off raw-bar consumers; deep cache deferred | static | `poetry run mypy itrader` | ✅ create | ⬜ pending |
| A-T2 | 05-01 | 1 | PERF-05 | T-05A-01 | 7-rule contract + D-08/D-10 cursor byte-for-byte; G1 base_tf<=min(tf) | integration | `poetry run pytest tests/integration/test_backtest_oracle.py -x -q` | ✅ exists | ⬜ pending |
| A-T3 | 05-01 | 1 | PERF-05 | T-05A-01/02 | Newest-bar unify single source; G1 ordering assertion | integration | `poetry run pytest tests/integration/test_bar_cache_registration.py -x -q` | ❌ W0 | ⬜ pending |
| B-T1 | 05-02 | 1 | PERF-05 (SC1/SC1b/SC3b/SC3c) | T-05B-01/02 | ta-convergence post-warmup; reset reproduces fresh; causal guard | unit | `poetry run pytest tests/unit/strategy/test_indicator_convergence.py tests/unit/strategy/test_indicator_reset.py tests/unit/strategy/test_causal_guard.py tests/unit/strategy/test_indicators.py -x -q` | ❌ W0 (3 new) | ⬜ pending |
| B-T2 | 05-02 | 1 | PERF-05 (P5-D10/D19/D20) | T-05B-02 | Per-symbol fan-out, independent readiness, gap=no-update; non-causal rejected | unit | `poetry run pytest tests/unit/strategy -x -q` | ✅ exists | ⬜ pending |
| B-T3 | 05-02 | 1 | PERF-05 (SC2/SC2b/SC3) | T-05B-01 | Re-baseline: behavioral identity 134 + cross-val 1% rel tol BEFORE freeze | integration+manual | `poetry run pytest tests/integration/test_backtest_oracle.py -x -q` + cross-val harness (P5-D02) | ✅ exists (re-freeze) | ⬜ pending |
| C-T1 | 05-03 | 2 | PERF-05 (P5-D13/D14) | T-05C-01 | Drop self.bars/feed.window; gap skip stays; oracle byte-exact vs new ref | integration+unit | `poetry run pytest tests/integration/test_backtest_oracle.py tests/unit/strategy -x -q` | ✅ exists | ⬜ pending |
| C-T2 | 05-03 | 2 | PERF-05 (P5-D15/D09) | T-05C-01/02 | β fit-once-frozen; both-legs guard; non-finite-z guard; β->money fence | unit | `poetry run pytest tests/unit/strategy/test_pair_dispatch.py tests/unit/strategy/test_pair_strategy.py -x -q` | ✅ exists | ⬜ pending |
| C-T3 | 05-03 | 2 | PERF-05 (SC4b/P5-D13a/D18) | T-05C-01 | Count/date fixtures migrated off self.bars, firing preserved; determinism | unit+e2e+integration | `poetry run pytest tests tests/integration/test_backtest_oracle.py -q && poetry run mypy itrader` | ✅ exists | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/integration/test_bar_cache_registration.py` — capacity-derivation deferral + ladder, G5 newest-bar unify (single source), G1 `base_timeframe <= min(timeframe)` assertion (Plan A / A-T3)
- [ ] `tests/unit/strategy/test_indicator_convergence.py` — the P5-D17 ta-convergence test, all four indicators, post-warmup, `atol=1e-9/rtol=1e-6` (Plan B / SC1)
- [ ] `tests/unit/strategy/test_indicator_reset.py` — `reset()` -> re-feed reproduces a fresh run (Plan B / SC3b / P5-D19)
- [ ] `tests/unit/strategy/test_causal_guard.py` — non-causal adapter rejection; all v1 adapters causal=True (Plan B / SC3c / P5-D20)
- [ ] Re-baseline the existing EMA/RSI unit tests in `tests/unit/strategy/test_indicators.py` to the new incremental values (Plan B / SC1b / P5-D12)
- [ ] Re-freeze `tests/golden/{trades.csv,equity.csv,summary.json}` AFTER cross-val PASS (Plan B / SC2 / P5-D02 — owner-gated blocking checkpoint)
- [ ] Framework install: NONE — pytest/mypy/ta/backtesting.py/backtrader all present and pinned.

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| W1 perf re-freeze (Gate b) | PERF-05 / SC4 | Thermally sensitive; same-machine A/B on a cool machine | `make perf-w1` prints delta vs `perf/results/W1-BASELINE.json`; attribute via Scalene CPU-share if throttled; re-freeze on a cool machine per `04-PERF-ATTRIBUTION.md` (P5-D03) |
| Oracle re-baseline freeze | PERF-05 / SC2b | Owner sign-off required before the golden is re-frozen (P5-D02) | Plan 05-02 Task 3 blocking-human checkpoint: cross-val PASS within 1% rel tol BEFORE freezing; if the trade SET moves, BLOCK pending owner adjudication |

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references
- [x] No watch-mode flags
- [x] Feedback latency acceptable (unit subset ~seconds; full suite oracle-bound)
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** ready

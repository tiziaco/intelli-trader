---
phase: 6
slug: m5a-backtest-validity-fills-data-pipeline
status: planned
nyquist_compliant: true
wave_0_complete: false
created: 2026-06-06
---

# Phase 6 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 8.4.2 (strict markers, strict config, filterwarnings=error) |
| **Config file** | `pyproject.toml` |
| **Quick run command** | `poetry run pytest -m unit -x -q` |
| **Full suite command** | `make test` |
| **Estimated runtime** | ~60 seconds |

---

## Sampling Rate

- **After every task commit:** Run the task's targeted command + `poetry run pytest tests/integration/test_backtest_oracle.py -q` (the D-21 tripwire — mandatory on every structural commit)
- **After every plan wave:** Run `make test` + `make typecheck`
- **Before `/gsd:verify-work`:** Full suite green + oracle re-frozen with the owner-signed expected-diff note
- **Max feedback latency:** 90 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 06-01 T1 | 06-01 | 1 | M5-02 | T-06-01 | Decimal(str) entry, never Decimal(float) | unit | `poetry run pytest tests/unit/core/test_bar.py -x -q && make typecheck` | ❌ created by task | ⬜ pending |
| 06-01 T2 | 06-01 | 1 | M5-02 | T-06-02 | oracle byte-exact (inert gate) | full + integration | `make test && make typecheck && poetry run pytest tests/integration/test_backtest_oracle.py -q` | ✅ | ⬜ pending |
| 06-02 T1 | 06-02 | 1 | M5-05 | T-06-06/07 | quarantine unreachable from run loop; mypy gate intact | typecheck + smoke | `make typecheck && poetry run pytest tests/integration/test_backtest_smoke.py -x -q` | ✅ | ⬜ pending |
| 06-02 T2 | 06-02 | 1 | M5-05 | T-06-04/05 | loud typed errors, no silent None (FR7) | unit | `poetry run pytest tests/unit/price/test_csv_store.py -x -q && make typecheck && poetry run pytest tests/integration/test_backtest_oracle.py -q` | ❌ created by task | ⬜ pending |
| 06-03 T1 | 06-03 | 2 | M5-01/03/05 | T-06-08/09 | completed-bars visibility; safe alias map | import + typecheck | `poetry run python -c "from itrader.price_handler.feed import BarFeed, BacktestBarFeed" && make typecheck` | ❌ created by task | ⬜ pending |
| 06-03 T2 | 06-03 | 2 | M5-01/03/05 | T-06-08/10/11 | look-ahead regression both directions; megaframe keys | unit + oracle | `poetry run pytest tests/unit/price/test_bar_feed.py -x -q && make test && poetry run pytest tests/integration/test_backtest_oracle.py -q` | ❌ created by task | ⬜ pending |
| 06-04 T1 | 06-04 | 2 | M5-01 | T-06-12/14 | limit-or-better; no float/quantize in matching | unit + oracle | `poetry run pytest tests/unit/execution/test_matching_engine.py tests/unit/order -x -q && poetry run pytest tests/integration/test_backtest_oracle.py -q` | ✅ extend | ⬜ pending |
| 06-04 T2 | 06-04 | 2 | M5-04 | T-06-13/15 | typed validation raises; maker/taker real context; no slippage on limits | unit + full + oracle | `poetry run pytest tests/unit/execution -x -q && make test && make typecheck && poetry run pytest tests/integration/test_backtest_oracle.py -q` | ❌ fee/slippage files created by task | ⬜ pending |
| 06-05 T1 | 06-05 | 3 | M5-03/05 | T-06-16/18 | push-only asof; same tick grid | integration + full | `poetry run pytest tests/integration/test_backtest_smoke.py -x -q && poetry run pytest tests/integration/test_backtest_oracle.py -q && make test` | ✅ | ⬜ pending |
| 06-05 T2 | 06-05 | 3 | M5-05 | T-06-17/19 | run path offline/read-only; PriceHandler gone | full + backtest | `make test && make typecheck && poetry run pytest tests/integration/test_backtest_oracle.py -q && make backtest` | ✅ | ⬜ pending |
| 06-06 T1 | 06-06 | 4 | M5-01 | T-06-20/22/23 | next-open fills; last-bar edge; same-bar OCO | unit + integration (oracle red expected, uncommitted) | `poetry run pytest tests/unit/execution tests/unit/order tests/integration/test_execution_handler_routing.py -x -q` | ✅ extend | ⬜ pending |
| 06-06 T2 | 06-06 | 4 | M5-01 | T-06-21 | owner-gated re-freeze (D-23) | human checkpoint | `test -s tests/golden/REFREEZE-M5A.md` (note drafted; approval manual) | ❌ created by task | ⬜ pending |
| 06-06 T3 | 06-06 | 4 | M5-01 | T-06-21 | atomic flip+goldens+note commit; determinism double-run | full + backtest | `make test && make typecheck && poetry run pytest tests/integration/test_backtest_oracle.py -q && make backtest` | ✅ | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

No separate Wave 0 plan: every new test file lands WITH the component it locks (D-24
test-with-code), inside the same task/commit — satisfying the Nyquist rule per task.

- [x] Resampling look-ahead / completed-bars rule (M5-01) → `tests/unit/price/test_bar_feed.py` (06-03 T2)
- [x] Fill semantics: limit-or-better (06-04 T1), next-bar-open market fills (06-06 T1) → `tests/unit/execution/test_matching_engine.py` extensions
- [x] Bar struct construction + immutability (M5-02) → `tests/unit/core/test_bar.py` (06-01 T1)
- [x] Fee/slippage model corrections (M5-04) → `tests/unit/execution/test_fee_models.py`, `test_slippage_models.py` (06-04 T2)
- [x] Provider/Store/Feed read-only run path (M5-05) → `tests/unit/price/test_csv_store.py` (06-02 T2)
- [x] Shared `make_bar`/`make_bar_event` fixtures land in the SAME commit as the BarEvent change (06-01 T2, Pitfall 9)

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Oracle re-freeze review (06-06 T2) | M5-01 | Result-changing fills require human sign-off on the new golden numbers (D-23) | Read tests/golden/REFREEZE-M5A.md; spot-check 3 trades vs the raw CSV (new fill == next row's Open); confirm trade-count/equity deltas are fully explained; type "approved" |

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references (test-with-code, same commit)
- [x] No watch-mode flags
- [x] Feedback latency < 90s
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** pending execution

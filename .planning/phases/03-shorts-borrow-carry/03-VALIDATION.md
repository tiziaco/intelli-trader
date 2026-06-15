---
phase: 3
slug: shorts-borrow-carry
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-06-15
---

# Phase 3 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 8.x (`pyproject.toml [tool.pytest.ini_options]`, `filterwarnings=["error"]`, `--strict-markers`) |
| **Config file** | `pyproject.toml` (existing — no Wave 0 install needed) |
| **Quick run command** | `poetry run pytest tests/unit/order tests/unit/portfolio -q` |
| **Full suite command** | `make test` |
| **Estimated runtime** | ~60–120 seconds (full suite) |

---

## Sampling Rate

- **After every task commit:** Run the targeted unit subset for the touched domain (e.g. `poetry run pytest tests/unit/portfolio -q`)
- **After every plan wave:** Run `make test`
- **Before `/gsd:verify-work`:** Full suite green + `mypy --strict` clean + determinism double-run byte-identical
- **Max feedback latency:** ~30 seconds (targeted subset)

---

## Per-Task Verification Map

> Populated by the planner from RESEARCH.md §Validation Architecture. One row per task; every functional task maps to an automated pytest command unless listed under Manual-Only.

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| TBD | TBD | TBD | SHORT-01 | — | N/A | unit | `poetry run pytest tests/unit/strategy -k short_registration` | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | SHORT-02 | — | N/A | unit | `poetry run pytest tests/unit/order -k cover_arm` | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | SHORT-03 | — | N/A | unit | `poetry run pytest tests/unit/portfolio -k short_pnl` | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | CARRY-01 | — | N/A | unit | `poetry run pytest tests/unit/portfolio -k borrow_interest` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky. The planner replaces TBD rows with concrete task IDs.*

---

## Wave 0 Requirements

- [ ] New unit test files for: short registration gate (two-flag), side-agnostic cover-arm + clamp-to-flat, short PnL wiring, borrow-interest accrual + days-basis + `BORROW_INTEREST` op, each WR residual fix (WR-01/03/04/05 + WR-02)
- [ ] Three **parked** e2e scenarios (hand-verified literals, real run path, NOT `--freeze`d, never BTCUSD): pure short round-trip, short-with-carry, partial cover — templated on `tests/e2e/levered_long/test_levered_long_scenario.py`

*Existing pytest infrastructure covers the framework; only new test modules are added.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| SMA_MACD golden held byte-exact | D-10 | Golden re-baseline is owner-gated, deferred to Phase 4/XVAL-01 | Run the SMA_MACD backtest; assert oracle 134 trades / `46189.87730727451` unchanged (carry-off / shorts-off defaults keep it byte-exact) |
| Parked short e2e scenarios | SHORT-03 / CARRY-01 / D-10 | Frozen as golden only at Phase 4 under cross-validation + owner sign-off | Run the three parked scenarios; confirm against hand-computed literals in a VERIFY note (no `--freeze`) |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 30s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending

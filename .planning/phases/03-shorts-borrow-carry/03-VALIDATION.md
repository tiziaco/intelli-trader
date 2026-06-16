---
phase: 3
slug: shorts-borrow-carry
status: draft
nyquist_compliant: true
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

> Populated by the planner from RESEARCH.md §Validation Architecture. One row per functional task; every functional task maps to an automated pytest command unless listed under Manual-Only. Wave 0 (Plan 02) seeds collectible skipped stubs for every selector below BEFORE its production plan runs.

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 03-01-T1 | 03-01 | 1 | CARRY-01 | T-03-01 | Decimal-typed default `Decimal("0")` (money integrity) | unit | `poetry run pytest tests/unit/core -q -k instrument` | ✅ exists | ⬜ pending |
| 03-01-T2 | 03-01 | 1 | CARRY-01 | T-03-03 | First-class auditable BORROW_INTEREST op | unit | `poetry run pytest tests/unit/portfolio -q -k cash_operation` | ✅ exists | ⬜ pending |
| 03-02-T1 | 03-02 | 1 | SHORT-01/02/03,CARRY-01 | T-03-05 | Every selector collects ≥1 test (no false-green) | unit | `poetry run pytest <8 modules> -q --co -k "<14 tokens>"` | ❌ W0 (this task creates) | ⬜ pending |
| 03-02-T2 | 03-02 | 1 | SHORT-03/CARRY-01 | T-03-04 | Parked e2e collectible; never BTCUSD | e2e | `poetry run pytest tests/e2e/{short_roundtrip,short_carry,partial_cover} -q -m e2e --co` | ❌ W0 (this task creates) | ⬜ pending |
| 03-03-T1 | 03-03 | 2 | SHORT-01 | T-03-07 | Non-LONG_ONLY admitted only under both flags | unit | `poetry run pytest tests/unit/strategy -q -k short_registration` | ✅ via W0 | ⬜ pending |
| 03-03-T2 | 03-03 | 2 | SHORT-01 | T-03-06 | Default-off → SMA_MACD byte-exact | integration | `make test-integration` (134 / `46189.87730727451`) | ✅ exists | ⬜ pending |
| 03-04-T1 | 03-04 | 2 | SHORT-02 | T-03-08 | Side-agnostic cover; clamp-to-flat; long-exit byte-exact | unit | `poetry run pytest tests/unit/order -q -k "cover_arm or over_cover_clamp or cover_magnitude"` | ✅ via W0 | ⬜ pending |
| 03-04-T2 | 03-04 | 2 | SHORT-03 | T-03-09 | Leverage floor at 1; SHORT PnL confirmed | unit | `poetry run pytest tests/unit/order -q -k leverage_floor && poetry run pytest tests/unit/portfolio -q -k short_pnl` | ✅ via W0 | ⬜ pending |
| 03-05-T1 | 03-05 | 2 | CARRY-01 | T-03-11 | Days basis from bar business time (no wall clock) | unit | `poetry run pytest tests/unit/portfolio -q -k "days_basis or borrow_interest"` | ✅ via W0 | ⬜ pending |
| 03-05-T2 | 03-05 | 2 | CARRY-01 | T-03-12 | Decimal carry debit via BORROW_INTEREST op | unit | `poetry run pytest tests/unit/portfolio -q -k "borrow_interest or borrow_interest_op or days_basis"` | ✅ via W0 | ⬜ pending |
| 03-06-T1 | 03-06 | 3 | SHORT-02 | T-03-15/16/17 | WR-01/02/03/05 seam hardening | unit | `poetry run pytest tests/unit/portfolio -q -k "funds_invariant_lock or release_symmetry or open_commission_accumulator or universe_unwired"` | ✅ via W0 | ⬜ pending |
| 03-06-T2 | 03-06 | 3 | SHORT-03/CARRY-01 | T-03-04 | Parked e2e against hand-computed literals | e2e | `poetry run pytest tests/e2e/{short_roundtrip,short_carry,partial_cover} -q -m e2e` | ✅ via W0 | ⬜ pending |
| 03-06-T3 | 03-06 | 3 | D-10 | T-03-18 | Owner-gated sign-off; nothing `--freeze`d | manual | (checkpoint:human-verify — see Manual-Only) | — | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky.*

---

## Wave 0 Requirements

- [ ] New unit test files for: short registration gate (two-flag), side-agnostic cover-arm + clamp-to-flat, short PnL wiring, borrow-interest accrual + days-basis + `BORROW_INTEREST` op, each WR residual fix (WR-01/03/04/05 + WR-02) — seeded as collectible skipped stubs by **Plan 02 Task 1** (selectors: `short_registration`, `cover_arm`, `over_cover_clamp`, `leverage_floor`, `cover_magnitude`, `short_pnl`, `borrow_interest`, `borrow_interest_op`, `release_symmetry`, `days_basis`, `funds_invariant_lock`, `open_commission_accumulator`, `universe_unwired`)
- [ ] Three **parked** e2e scenarios (hand-verified literals, real run path, NOT `--freeze`d, never BTCUSD): pure short round-trip, short-with-carry, partial cover — templated on `tests/e2e/levered_long/test_levered_long_scenario.py` — seeded as collectible skipped stubs by **Plan 02 Task 2**, authored in **Plan 06 Task 2**

*Existing pytest infrastructure covers the framework; only new test modules are added. Two RESEARCH-cited file names were corrected by 03-PATTERNS.md: `test_position.py` → `test_position_manager.py`; `test_strategies_handler.py` → new `test_strategies_handler_registration.py`.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| SMA_MACD golden held byte-exact | D-10 | Golden re-baseline is owner-gated, deferred to Phase 4/XVAL-01 | Run the SMA_MACD backtest; assert oracle 134 trades / `46189.87730727451` unchanged (carry-off / shorts-off defaults keep it byte-exact) |
| Parked short e2e scenarios | SHORT-03 / CARRY-01 / D-10 | Frozen as golden only at Phase 4 under cross-validation + owner sign-off | Run the three parked scenarios (Plan 06); confirm against hand-computed literals in a VERIFY note (no `--freeze`); owner-gated checkpoint 03-06-T3 |

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies (checkpoint 03-06-T3 is the only manual task)
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references (Plan 02 seeds every selector + the 3 parked e2e dirs)
- [x] No watch-mode flags
- [x] Feedback latency < 30s (targeted subset)
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** planner-approved (Nyquist contract satisfied — Wave 0 in Plan 02 precedes all functional verify targets)

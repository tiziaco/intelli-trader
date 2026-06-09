---
phase: 5
slug: m4-money-transaction-correctness
status: ready
nyquist_compliant: true
wave_0_complete: false
created: 2026-06-06
---

# Phase 5 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 8.4.2 (`filterwarnings=["error"]`, `--strict-markers`, `--strict-config`) |
| **Config file** | `pyproject.toml` (single marker home; folder-derived TYPE markers in layered conftests) |
| **Quick run command** | `poetry run pytest tests/unit -q -x` |
| **Full suite command** | `make test && make typecheck` (429+ collected) |
| **Estimated runtime** | unit ~30s; full suite + typecheck ~120s; oracle integration ~60s |

---

## Sampling Rate

- **After every task commit:** Run `poetry run pytest tests/unit -q -x` + the task's targeted test file
- **After every money-path or event-retype commit:** ALSO run `poetry run pytest tests/integration/test_backtest_oracle.py -q` (CONTEXT requires both byte-exact oracle layers green at EVERY commit)
- **After every plan wave:** Run `make test && make typecheck && poetry run pytest tests/integration/test_backtest_oracle.py -q`
- **Before `/gsd:verify-work`:** Full suite + typecheck + all integration tests green; `git diff --quiet tests/golden/` exits 0
- **Max feedback latency:** ~120 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 05-01-01 | 01 | 1 | M4-06 | T-05-01/02 | history stays queryable (audit) | unit | `poetry run pytest tests/unit/order/test_order_storage.py -q` | ✅ (rewrite) | ⬜ pending |
| 05-01-02 | 01 | 1 | M4-03 | — | N/A | unit+oracle | `poetry run pytest tests/unit/order -q` + oracle | ✅ (update) | ⬜ pending |
| 05-02-01 | 02 | 1 | M4-05 | T-05-03 | single-writer contract documented | suite (absence) | `make test` + oracle | ✅ (no lock tests exist) | ⬜ pending |
| 05-02-02 | 02 | 1 | M4-05 | T-05-SC | dep removal only | suite | `poetry run python -c "import itrader"` + `make test` | ✅ | ⬜ pending |
| 05-03-01 | 03 | 2 | M4-04 | T-05-05 | frozen view mutation raises | unit | `poetry run pytest tests/unit/core/test_portfolio_read_model.py -q` | ❌ W0 (created in-task) | ⬜ pending |
| 05-03-02 | 03 | 2 | M4-04/M4-01 | T-05-07 | reserve raises typed on shortfall | unit | `poetry run pytest tests/unit/portfolio/test_cash_manager.py tests/unit/core/test_portfolio_read_model.py -q` | ✅ (extend) | ⬜ pending |
| 05-03-03 | 03 | 2 | M4-04 | T-05-06 | concrete import dead, mypy-enforced | unit+typecheck | `make test && make typecheck` + oracle | ✅ (update) | ⬜ pending |
| 05-04-01 | 04 | 2 | M4-07 | T-05-08 | REFUSED still emits auditable FillEvent | unit | `poetry run pytest tests/unit/execution -q` | ✅ (rewrite) | ⬜ pending |
| 05-04-02 | 04 | 2 | M4-07 | T-05-09 | survivors frozen | unit+typecheck | `make test && make typecheck` + oracle | ✅ (update) | ⬜ pending |
| 05-05-01 | 05 | 3 | M4-02/M4-01 | T-05-11/13 | invariant checks balance; no quantize on trade path | unit | `poetry run pytest tests/unit/portfolio/test_cash_manager.py -q` | ✅ (extend) | ⬜ pending |
| 05-05-02 | 05 | 3 | M4-02 | T-05-10/12 | failed validation mutates nothing | unit+oracle | `poetry run pytest tests/unit/portfolio -q` + `make test` + oracle | ✅ (heavy rewrite) | ⬜ pending |
| 05-06-01 | 06 | 4 | M4-01 | T-05-14/15/16 | reserve-fail → audited REJECTED, nothing emitted | unit | `poetry run pytest tests/unit/order/test_order_manager.py -q` | ✅ (extend) | ⬜ pending |
| 05-06-02 | 06 | 4 | M4-01 | T-05-17 | reserved == 0 post-run; gate never rejects in golden run | integration | `poetry run pytest tests/integration/test_reservation_inertness.py tests/integration/test_backtest_oracle.py -q` | ❌ W0 (created in-task) | ⬜ pending |
| 05-07-01 | 07 | 5 | M4-07 | T-05-18/19 | to_money-only crossings; no Decimal×float | unit+oracle | `poetry run pytest tests/unit/events tests/unit/execution -q` + oracle | ✅ (update) | ⬜ pending |
| 05-07-02 | 07 | 5 | M4-08 | T-05-20 | oracle assertions unmodified; byte-exact | integration+gate | `make test && make typecheck && poetry run pytest tests/integration/ -q && git diff --quiet tests/golden/` | ✅ | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

All Wave 0 gaps from RESEARCH are created **inside the task that needs them** (tdd="true" tasks
with explicit `<behavior>` blocks) — no standalone Wave 0 plan needed:

- [ ] `tests/unit/core/test_portfolio_read_model.py` — created in 05-03 Task 1 (M4-04 conformance + frozen PositionView)
- [ ] Reservation-lifecycle coverage in `tests/unit/portfolio/test_cash_manager.py` — extended in 05-03 Task 2 (per-reference reserve/release, idempotent release, full precision) and 05-05 Task 1 (fee field, full-precision fill flow, balance-based invariant)
- [ ] Admission check-and-reserve coverage in `tests/unit/order/test_order_manager.py` — extended in 05-06 Task 1 (reserve-fail → audited REJECTED, BUY-only, brackets exempt)
- [ ] Settlement-ordering regression test (failed validation leaves position AND cash untouched) — added in 05-05 Task 2
- [ ] `tests/integration/test_reservation_inertness.py` — created in 05-06 Task 2 (D-14 mandated golden-run trace)
- Framework install: none needed

---

## Manual-Only Verifications

All phase behaviors have automated verification. The M4-08 escape hatch ("any numeric difference
is explained") is owner-gated: if an oracle diff survives investigation, execution STOPS and the
finding goes to COVERAGE-INDEX §E for an owner decision — that decision step is human by design,
not a manual test.

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| §E owner decision on irreducible oracle diff | M4-08 | Governance gate, not a test | Only reached if byte-exact fails after investigation; present diff + root cause to owner |

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies (created in-task)
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references (in-task creation, mapped above)
- [x] No watch-mode flags
- [x] Feedback latency < 120s
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** pending

---
phase: 02
slug: m2a-identity-money-determinism
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-06-04
---

# Phase 02 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 8.4.2 (+ pytest-cov, pytest-html, pytest-watch) |
| **Config file** | `pyproject.toml` `[tool.pytest.ini_options]` — strict markers/config; `filterwarnings=["error", ...]` |
| **Quick run command** | `poetry run pytest test/test_order_handler test/test_portfolio_handler -q` |
| **Full suite command** | `make test` (`poetry run pytest`) |
| **Type gate (new, D-06)** | `make typecheck` → `poetry run mypy itrader` |
| **Estimated runtime** | ~60–120 seconds (full suite); ~5–10s quick |

---

## Sampling Rate

- **After every task commit:** Run the relevant quick unit command for the touched area.
- **After every plan wave:** Run `make test` + `make typecheck`.
- **Before `/gsd:verify-work`:** `make test` green, `make typecheck` clean, AND
  `test_backtest_oracle.py` green with the D-15 tolerance (behavioral identity EXACT,
  numeric within bound).
- **Max feedback latency:** ~120 seconds.

---

## Per-Task Verification Map

| Req ID | Behavior | Test Type | Automated Command | File Exists |
|--------|----------|-----------|-------------------|-------------|
| M2-01 | `idgen` returns stdlib `uuid.UUID` (UUIDv7); ids unique + time-ordered | unit | `poetry run pytest test/test_outils/test_id_generator.py -x` | ❌ W0 (new) |
| M2-01 | Storage keys + flat index are native `UUID`; lookup/removal by UUID works | unit | `poetry run pytest test/test_order_handler/test_order_storage.py -x` | ✅ extend |
| M2-02 | `core.money.quantize` HALF_UP per-instrument; `to_money` uses `str()`; no float round-trip | unit | `poetry run pytest test/test_core/test_money.py -x` | ❌ W0 (new) |
| M2-02 | Transaction/portfolio money fields `Decimal`; `cash += float(...)` removed | unit | `poetry run pytest test/test_portfolio_handler -k decimal -x` | ❌ W0 (new) |
| M2-03 | `mypy --strict` clean over in-scope package | type | `make typecheck` | ❌ W0 (config new) |
| M2-04 | Each converted base is real ABC/Protocol; `SimulatedExchange` conforms | unit | `poetry run pytest test/test_execution_handler/test_exchanges -x` | ✅ extend |
| M2-05 | Injected `Clock` returns bar time; engine `datetime.now()` removed; seeded `Random` injected | unit | `poetry run pytest test/test_core/test_clock.py test/test_execution_handler -k rng -x` | ❌ W0 (new) |
| M2a (oracle) | Behavioral identity EXACT + numeric within D-15 tolerance | integration/slow | `poetry run pytest test/test_integration/test_backtest_oracle.py -x` | ✅ MODIFY (D-15) |

*Status legend: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `test/test_outils/test_id_generator.py` — covers M2-01 (uuid7 type, uniqueness, ordering)
- [ ] `test/test_core/test_money.py` — covers M2-02 (quantize HALF_UP, per-instrument scale, `to_money`)
- [ ] `test/test_core/test_clock.py` — covers M2-05 (Clock returns bar time; advance contract)
- [ ] `pyproject.toml` `[tool.mypy]` + `[[tool.mypy.overrides]]` — M2-03 gate config (none today)
- [ ] `Makefile` `typecheck` target — M2-03 / D-06 (none today)
- [ ] `conftest.py` `DIR_MARKERS` — add `"test_outils": "unit"`, `"test_core": "unit"` if new dirs
      created (else new tests won't get marker auto-applied; `--strict-markers` is active)
- [ ] **MODIFY** `test/test_integration/test_backtest_oracle.py` — split identity-exact from
      numeric-tolerant (D-15)
- [ ] Install: `poetry add uuid-utils@^0.16.0` and `poetry add --group dev mypy` (latest)

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Cross-entity `NewType` ID mix-ups are caught | M2-03 / D-12 | `mypy --strict` surfaces these statically, not at runtime | Inspect `make typecheck` output: no `OrderId`/`PortfolioId` cross-assignment errors |

*All other phase behaviors have automated verification.*

---

## Validation Sign-Off

- [ ] All tasks have automated verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 120s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending

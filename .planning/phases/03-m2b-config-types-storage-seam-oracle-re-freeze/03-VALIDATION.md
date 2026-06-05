---
phase: 03
slug: m2b-config-types-storage-seam-oracle-re-freeze
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-06-05
---

# Phase 03 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.
> Derived from `03-RESEARCH.md` § Validation Architecture.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 8.4.2 (+ pytest-cov 5.0, pytest-html 4.2) |
| **Config file** | `pyproject.toml` `[tool.pytest.ini_options]` (testpaths/markers/filterwarnings); `test/conftest.py` → `tests/conftest.py` (fixtures + auto-marking) after D-13 reorg |
| **Quick run command** | `poetry run pytest -m "unit" -q` (post-reorg: `tests/unit`) |
| **Full suite command** | `make test` (`poetry run pytest`) |
| **Estimated runtime** | ~30–60 seconds (full suite) |

**Strict gates (any violation fails the suite):** `--strict-markers`, `--strict-config`, `filterwarnings=["error"]`; plus `make typecheck` = `mypy --strict` after any config/enum/type change.

---

## Sampling Rate

- **After every task commit:** `poetry run pytest -m unit -q` + the specific touched test; `make typecheck` after any config/enum/type change.
- **After every plan wave:** `make test` (full suite) + `pytest tests/integration/test_backtest_oracle.py::test_oracle_behavioral_identity` (the D-18 behavioral law — must stay green at EVERY commit).
- **Before `/gsd:verify-work`:** Full suite green + `mypy --strict` clean + D-17 inertness gate byte-exact + D-16 re-freeze landed.
- **Max feedback latency:** ~60 seconds (full suite).

---

## Per-Requirement Verification Map

| Req ID | Behavior | Test Type | Automated Command | File Exists |
|--------|----------|-----------|-------------------|-------------|
| M2-06 | `PortfolioConfig.model_validate(d).model_dump(mode="json")` round-trips; `Settings` raises on missing secret | unit | `pytest tests/unit/config/test_config_models.py -x` | ❌ W0 |
| M2-07 | `FillStatus("executed")` parses case-insensitively; unknown raises a clear error | unit | `pytest tests/unit/core/test_enums.py -x` | ❌ W0 |
| M2-08 | `PortfolioStateStorage` round-trips positions/transactions/cash/metrics; factory returns in-memory for backtest | unit | `pytest tests/unit/portfolio/test_state_storage.py -x` | ❌ W0 |
| M2-09 | `add_state_change` uses event time (not `datetime.now()`); `modify_order` routes through it | unit | `pytest tests/unit/order/test_order_timestamps.py -x` | ❌ W0 (extend existing order tests) |
| M2-10 | `to_timedelta("1W")` works, `to_timedelta("1M")` raises, `check_timeframe` fires on golden grid | unit | `pytest tests/unit/outils/test_time_parser.py -x` | partial (existing `test_outils`) |
| M2-11 | Dead modules deleted; suite still green (no import of deleted names) | integration | `make test` (collection succeeds) | ✅ (negative: collection) |
| M2-12 | All `unittest.TestCase` converted; identical collected count each commit | meta | `pytest --collect-only -q \| wc -l` unchanged | ✅ (existing suite) |
| M2-13 | Behavioral identity EXACT; numeric columns EXACT after re-freeze; D-17 inertness gate passes | integration | `pytest tests/integration/test_backtest_oracle.py -x` | ✅ (modify D-16/D-17/D-18) |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky — populate Task IDs during planning.*

---

## Wave 0 Requirements

- [ ] `poetry add pydantic@^2.13 pydantic-settings@^2.14` — the only framework install (Pydantic is NOT currently a dependency; must be lockfile-tracked)
- [ ] `tests/unit/config/test_config_models.py` — covers M2-06 (round-trip + fail-loud secret)
- [ ] `tests/unit/core/test_enums.py` — covers M2-07 (case-insensitive `_missing_` + unknown raises)
- [ ] `tests/unit/portfolio/test_state_storage.py` — covers M2-08 (seam round-trip + factory)
- [ ] `tests/unit/order/test_order_timestamps.py` — covers M2-09 (event-time, modify_order path)
- [ ] Extend `tests/unit/outils/test_time_parser.py` — covers M2-10 (`1W` ok, `1M` raises, epoch anchor)
- [ ] Modify `tests/integration/test_backtest_oracle.py` — D-16 (remove xfail + tolerance), D-17 (inertness ref), D-18 (keep behavioral law)
- [ ] Root + `unit/` + `integration/` conftests with type-marker registration (pick exactly ONE home — `pyproject.toml markers` OR `pytest_configure`, never both) — D-13

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| D-17 inertness diff explanation | M2-13 | A non-zero behavioral/numeric diff at the inertness gate BLOCKS re-freeze pending owner explanation (logged as COVERAGE-INDEX §E delta) — requires human judgment, not an assertion | If `test_oracle_behavioral_identity` or the inertness comparison diverges: STOP, investigate the `time_parser` firing shift, do NOT re-baseline behavior |

*All other phase behaviors have automated verification.*

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 60s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending

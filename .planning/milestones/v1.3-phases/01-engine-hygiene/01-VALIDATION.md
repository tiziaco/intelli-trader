---
phase: 1
slug: engine-hygiene
status: draft
nyquist_compliant: true
wave_0_complete: true
created: 2026-06-12
---

# Phase 1 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.
> Byte-exact hygiene phase: existing infrastructure fully covers every requirement; no Wave 0 work needed.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest `^8.4.2` (`testpaths = ["tests"]`, `minversion = "8.0"`; `filterwarnings=["error"]`, `--strict-markers`, `--strict-config`) |
| **Config file** | `pyproject.toml` `[tool.pytest.ini_options]` |
| **Quick run command** | `poetry run pytest tests/unit/portfolio/test_position_manager.py -q` (item 1) |
| **Full suite command** | `make test` |
| **Estimated runtime** | quick ~few seconds · full suite minutes |

---

## Sampling Rate

- **After every task commit:** the item's local check — `poetry run pytest tests/unit/portfolio/test_position_manager.py -q` (item 1); `make typecheck` (items 2/4/5/6/7).
- **After every plan wave:** `make typecheck` + `poetry run pytest tests/e2e`.
- **Before `/gsd:verify-work`:** Phase byte-exact gate must be green (see below).
- **Max feedback latency:** quick check < ~10s.

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 01-item-1 | 01 | 1 | HYG-01 (1) | — / — | N/A — test-only rewrite, still green | unit | `poetry run pytest tests/unit/portfolio/test_position_manager.py -q` | ✅ (19 tests) | ⬜ pending |
| 01-item-2 | 01 | 1 | HYG-01 (2) | — / — | N/A — stale override removal | static | `make typecheck` | ✅ | ⬜ pending |
| 01-item-3 | 01 | 1 | HYG-01 (3) | — / — | N/A — dead constant removal | static | `make typecheck` | ✅ | ⬜ pending |
| 01-item-4 | 01 | 1 | HYG-01 (4) | — / — | Validator rejects non-Decimal (isinstance guard updated) | static | `make typecheck` | ✅ | ⬜ pending |
| 01-item-5 | 01 | 1 | HYG-01 (5) | — / — | N/A — verify-only (already removed in 2ffbeb8) | static | `grep -n StrategyId itrader/order_handler/order_manager.py` (expect no match) | ✅ | ⬜ pending |
| 01-item-6 | 01 | 1 | HYG-01 (6) | — / — | N/A — value-identical constant consolidation | static | `make typecheck` | ✅ | ⬜ pending |
| 01-item-7 | 01 | 1 | HYG-01 (7) | — / — | N/A — doc-comment softening | static | `make typecheck` | ✅ | ⬜ pending |
| 01-gate | 01 | 1 | HYG-01 (whole) | — / — | Golden master byte-exact (134 trades / 46189.87730727451) | integration | `make test-integration` | ✅ | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

*Existing infrastructure covers all phase requirements.* The 19-case position-manager unit test, the 58 e2e scenarios, the `tests/integration/test_backtest_oracle.py` byte-exact gate, and `mypy --strict` (172 files) cover every requirement. No new test files, fixtures, or framework install needed.

---

## Manual-Only Verifications

*All phase behaviors have automated verification.*

---

## Phase Byte-Exact Gate (run in order)

1. `make typecheck` — `mypy --strict` clean
2. `make test-integration` — golden oracle exact: **134 trades / `final_equity 46189.87730727451`** (no-tolerance frame-equal)
3. `poetry run pytest tests/e2e` — 58/58
4. `make test` — full suite green

---

## Validation Sign-Off

- [x] All tasks have automated verify or Wave 0 dependencies
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references (none — existing infra suffices)
- [x] No watch-mode flags
- [x] Feedback latency < 10s (quick checks)
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** pending

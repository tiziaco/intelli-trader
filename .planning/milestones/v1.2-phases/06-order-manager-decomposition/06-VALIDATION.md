---
phase: 6
slug: order-manager-decomposition
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-06-11
---

# Phase 6 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.
> This is a **pure code-motion** phase (D-00/D-13): the verification gate is also the entire
> correctness proof. Behavior must stay byte-exact after EACH extraction step (D-10/D-11).

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 8.4.2 (`--strict-markers`, `--strict-config`, `filterwarnings=["error", ...]`) |
| **Config file** | `pyproject.toml [tool.pytest.ini_options]` (`testpaths=["tests"]`) |
| **Quick run command** | `poetry run pytest tests/unit/order/ -q && poetry run mypy itrader` |
| **Full suite command** | `poetry run pytest tests/integration/test_backtest_oracle.py tests/e2e -m "integration or e2e" -q && poetry run mypy itrader` |
| **Estimated runtime** | ~30s unit slice; integration+e2e a few min |

*Markers: only `unit`, `integration`, `slow`, `e2e` declared; type auto-applied by folder via `tests/conftest.py`.*

---

## Sampling Rate

- **After every task commit:** `poetry run pytest tests/unit/order/ -q && poetry run mypy itrader` (fast feedback, < 30s)
- **After every plan wave / extraction step (D-11 full gate):** `poetry run pytest tests/integration/test_backtest_oracle.py tests/e2e -m "integration or e2e" -q && poetry run mypy itrader` — byte-exact 134 trades / `final_equity 46189.87730727451` + 58/58 e2e + strict clean
- **At the `reconcile/` extraction step (additionally):** `poetry run pytest tests/e2e/robust/test_determinism.py -q` (double-run byte-identical)
- **Before `/gsd:verify-work`:** full `poetry run pytest tests/ -q` green + `mypy itrader` clean
- **Max feedback latency:** ~30 seconds (unit slice)

---

## Per-Task Verification Map

> One plan per D-10 extraction step. The golden-master byte-exact gate runs after EVERY step —
> a break points at exactly one extraction. Task IDs are placeholders the planner finalizes.

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 06-01-* | 01 BracketBook in-place (D-10 step 1) | 1 | MOD-01 | — | `_pending_brackets`→`BracketBook` wrapper byte-equal; test_sltp_policy survives (dict-compat dunders) | unit + integration | `poetry run pytest tests/unit/order/test_sltp_policy.py tests/integration/test_backtest_oracle.py -q` | ✅ | ⬜ pending |
| 06-01-* | 01 BracketBook unit test (D-15) | 1 | MOD-01 (new) | — | `arm`/`get`/`consume`/`refresh_quantity` + idempotent `consume`→`None` on missing key | unit | `poetry run pytest tests/unit/order/test_bracket_book.py -q` | ❌ W0 | ⬜ pending |
| 06-02-* | 02 extract `brackets/` (D-10 step 2) | 2 | MOD-01 | — | golden byte-exact after move | integration + e2e | `poetry run pytest tests/integration/test_backtest_oracle.py tests/e2e -m "integration or e2e" -q` | ✅ | ⬜ pending |
| 06-03-* | 03 extract `admission/` (D-10 step 3) | 3 | MOD-01 | — | golden byte-exact after move | integration + e2e | `poetry run pytest tests/integration/test_backtest_oracle.py tests/e2e -m "integration or e2e" -q` | ✅ | ⬜ pending |
| 06-04-* | 04 extract `lifecycle/` (D-10 step 4) | 4 | MOD-01 | — | golden byte-exact after move | integration + e2e | `poetry run pytest tests/integration/test_backtest_oracle.py tests/e2e -m "integration or e2e" -q` | ✅ | ⬜ pending |
| 06-05-* | 05 extract `reconcile/` FRAGILE LAST (D-10 step 5) | 5 | MOD-01 | — | `should_release`/`try`/`finally` interplay byte-for-byte unchanged (criterion 2); `on_fill` moved intact | integration + e2e + determinism | `poetry run pytest tests/integration/test_backtest_oracle.py tests/e2e -m "integration or e2e" -q && poetry run pytest tests/e2e/robust/test_determinism.py -q` | ✅ | ⬜ pending |
| 06-05-* | static gate (every step) | 1-5 | MOD-01 | — | `mypy --strict` clean across all source | static | `poetry run mypy itrader` | ✅ | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/unit/order/test_bracket_book.py` — the ONE new lean unit test for the `BracketBook`
  primitive (D-15). Asserts: `arm`+`get` round-trip; `consume` returns the entry and removes it;
  `consume` on a missing key returns `None` (idempotent — mirrors current `pop(.., None)`);
  `refresh_quantity` replaces only the quantity (preserves other `_PendingBracket` fields via
  `replace(...)`); and the dict-compat dunders (`== {}`, `in`, `len`) if `BracketBook` keeps
  `test_sltp_policy.py` unchanged. **4-space indented** (NEW test code follows `tests/` house style;
  the MOVED production code stays TAB).

*No framework install needed — pytest 8.4.2 + mypy present.*

---

## Manual-Only Verifications

All phase behaviors have automated verification. The golden-master oracle, e2e suite (58/58),
determinism harness, and facade-level unit tests are frozen and present — pure code-motion is
fully provable by re-running them after each extraction.

---

## Validation Sign-Off

- [ ] All tasks have automated verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references (only `test_bracket_book.py`)
- [ ] No watch-mode flags
- [ ] Feedback latency < 30s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending

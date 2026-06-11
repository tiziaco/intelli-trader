---
phase: 3
slug: hot-path-performance
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-06-11
---

# Phase 3 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.
>
> **Verification law (D-01/D-02):** byte-exact oracle proves correctness; deterministic
> behavioral asserts prove each optimization actually landed; wall-clock benchmarks are
> REJECTED (environment-flaky). Both layers are required — the oracle cannot detect a
> silently-reverted `.copy()`; the asserts cannot prove end-to-end numbers.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest ^8.4.2 (`filterwarnings=["error"]`, `--strict-markers`, `--strict-config`) |
| **Config file** | `pyproject.toml` `[tool.pytest.ini_options]` (`testpaths=["tests"]`) |
| **Quick run command** | `poetry run pytest tests/unit/portfolio/ tests/unit/price/ -q` (or the specific new test file with `-x`) |
| **Full suite command** | `make test` (+ `make test-integration` for the oracle, `make test-e2e` for scenarios) |
| **Static gate** | `poetry run mypy itrader` (strict) |
| **Estimated runtime** | ~60 seconds (unit quick run); full suite + oracle + e2e a few minutes |

> Markers (`unit`/`integration`/`e2e`) are auto-applied from the folder via `tests/conftest.py` — do NOT hand-add. From a git worktree, prepend `PYTHONPATH="$PWD"` to avoid editable-install shadowing.

---

## Sampling Rate

- **After every task commit:** Run the new behavioral assert(s) for that optimization + `poetry run mypy itrader` (`poetry run pytest <new test file> -x`)
- **After every plan wave:** Run `make test-unit` (or `tests/unit/portfolio/ tests/unit/price/`)
- **Before `/gsd:verify-work`:** byte-exact oracle green (`make test-integration`) + full e2e green (`make test-e2e`) + `mypy --strict` clean
- **Max feedback latency:** ~60 seconds (quick unit run)

---

## Per-Task Verification Map

| Optimization (Req) | Behavior to prove | Test Type | Automated Command | File Exists | Status |
|--------------------|-------------------|-----------|-------------------|-------------|--------|
| PERF-01 copy-drop (D-03) | All 5 getters return the SAME live container (no `.copy()`) | unit / object-identity | `poetry run pytest tests/unit/portfolio/test_state_storage.py -x` (`assert get_X() is get_X()` ×5) | ❌ W0 — extend test_state_storage.py | ⬜ pending |
| PERF-01 caller audit (D-05) | No *test* mutates a getter result then asserts storage unchanged | unit / grep-audit | grep `tests/unit/portfolio/` for mutate-then-assert; migrate any hit | ❌ W0 — executor audit task | ⬜ pending |
| PERF-01 snapshot accessors (D-06) | `snapshot_count()`/`get_latest_snapshot()` replace never-firing trim copy | unit / accessor-behavior | `poetry run pytest tests/unit/portfolio/test_metrics_manager.py tests/unit/portfolio/test_state_storage.py -x` | ❌ W0 — add accessor tests | ⬜ pending |
| PERF-03 prebuilt Bars (D-07/08/09) | `current_bars()` serves prebuilt `Bar`s — NO per-tick `Bar.from_row` | unit / call-presence (no-call) | `poetry run pytest tests/unit/price/test_bar_feed.py -x` (monkeypatch sentinel onto `Bar.from_row`, assert never called per tick) | ❌ W0 — add no-call assert | ⬜ pending |
| PERF-03 look-ahead safety | Window visibility + bit-identical values unchanged | unit (existing) | `tests/unit/price/test_bar_feed.py` rules 1-7 + `tests/unit/core/test_bar.py` stay green | ✅ exists | ⬜ pending |
| PERF-03 MACD-guard reorder (W1-12 / **D-02**) | MACD computed inside the SMA guard; firing tick byte-identical | **code-review + oracle ONLY — NO new test** | reviewer confirms MACD moved inside `if short_sma>=long_sma`; oracle proves identical trades | ✅ oracle covers (D-02) | ⬜ pending |
| PERF-02 W1-07 on_fill guard hoist | Non-EXECUTED fill = early no-op; EXECUTED unchanged; guard precedes correlation-id alloc | unit / behavioral | `poetry run pytest tests/unit/portfolio/test_on_fill_status_guard.py -x` | ✅ file exists — confirm/extend | ⬜ pending |
| PERF-02 W1-08 Decimal re-wraps | `Decimal(str(Decimal))` removed; totals identical | oracle + mypy | `make test-integration` + `poetry run mypy itrader` | ✅ oracle + mypy | ⬜ pending |
| PERF-02 W1-03 open_position_count ×2 | Single call cached locally; identical value | oracle + mypy | `make test-integration` + `poetry run mypy itrader` | ✅ oracle + mypy | ⬜ pending |
| PERF-02 W1-14 is_connected ×2-3 | Redundant checks removed; identical fill path | oracle + e2e | `make test-integration` + `make test-e2e` | ✅ oracle + e2e | ⬜ pending |
| PERF-02 W1-09 load-time copy | `raw[expected_cols].copy()` removed; identical loaded frame | oracle + existing csv-store unit | `make test-integration` + `poetry run pytest tests/unit/price/test_csv_store.py` | ✅ oracle + existing test | ⬜ pending |
| Cross-cutting correctness (ALL) | 134 trades / final_equity 46189.87730727451 EXACT | integration / byte-exact oracle | `make test-integration` → `test_backtest_oracle.py` (`check_exact=True`, no tolerance) | ✅ exists — must stay green | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/unit/portfolio/test_state_storage.py` — add object-identity asserts for the 5 getters (PERF-01/D-03) + accessor-behavior asserts for `snapshot_count`/`get_latest_snapshot` (D-06)
- [ ] `tests/unit/portfolio/test_metrics_manager.py` — assert the trim path uses the count/last accessors (D-06) and the never-firing trim still does not fire
- [ ] `tests/unit/price/test_bar_feed.py` — add the no-call `Bar.from_row` sentinel assert for `current_bars()` (PERF-03/D-07)
- [ ] `tests/unit/portfolio/test_on_fill_status_guard.py` — confirm/extend the non-EXECUTED no-op guard survives the W1-07 hoist
- [ ] **Audit task (D-05):** grep `tests/unit/portfolio/` for any test that mutates a getter result and asserts storage unchanged; migrate it (caller `.copy()`s locally)

*No framework install needed — pytest/mypy/pandas all present and green.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| MACD-guard reorder is byte-identical | PERF-03 / W1-12 | D-02 owner constraint forbids any new unit test against `SMA_MACD_strategy` | Code review: confirm MACD computed inside `if short_sma >= long_sma` guard (SMA_MACD_strategy.py ~line 66); rely on byte-exact oracle for the numeric proof |

---

## Validation Sign-Off

- [ ] All tasks have an automated verify or a Wave 0 dependency (except the D-02 manual-only MACD reorder)
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references (5 behavioral-assert/audit items above)
- [ ] No watch-mode flags
- [ ] Feedback latency < 60s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending

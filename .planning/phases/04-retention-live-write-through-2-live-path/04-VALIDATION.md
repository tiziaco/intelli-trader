---
phase: 04
slug: retention-live-write-through-2-live-path
status: draft
nyquist_compliant: true
wave_0_complete: false
created: 2026-06-30
---

# Phase 04 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 8.x (`filterwarnings=["error"]`, `--strict-markers`, `--strict-config`) |
| **Config file** | `pyproject.toml [tool.pytest.ini_options]` |
| **Quick run command** | `poetry run pytest tests/unit -q` |
| **Full suite command** | `poetry run pytest tests` (integration needs Docker for testcontainers Postgres) |
| **Estimated runtime** | ~unit fast; integration gated on testcontainers Postgres (skips without Docker) |

---

## Sampling Rate

- **After every task commit:** Run the touched concern's test file, e.g. `poetry run pytest tests/integration/storage/test_cached_sql_order_storage.py -x` (or `tests/unit -q` for the quarantine test).
- **After every plan wave:** Run `poetry run pytest tests/integration/storage -m integration` + `poetry run mypy itrader` (with Docker up).
- **Before `/gsd:verify-work`:** Full suite green + `mypy --strict` clean (GATE-02) + SMA_MACD oracle byte-exact (GATE-01) + W1/W2 A/B within ±5%.
- **Max feedback latency:** unit < ~30s; integration bounded by container spin-up.

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 04-01 T1 | 04-01 | 1 | RETAIN-02/03 | T-04-08 | Failing order-wrapper suite (evict/read-through, flat-RSS, bracket-resident, open-only rehydrate, crash-restart, within-method atomicity) | integration | `pytest tests/integration/storage/test_cached_sql_order_storage.py --collect-only` | ❌ Wave 0 | ⬜ pending |
| 04-01 T2 | 04-01 | 1 | RETAIN-01/02/03 | T-04-08 | CachedSqlOrderStorage store-first + purge gate + bracket-resident + read-through + rehydrate | integration | `pytest tests/integration/storage/test_cached_sql_order_storage.py -x` | ❌ Wave 0 | ⬜ pending |
| 04-01 T3 | 04-01 | 1 | RETAIN-01 | T-04-09 | Order factory 'live' arm wraps; backtest path SQL-free | unit/probe | local quarantine probe (subprocess gate in 04-04) | ✅ exists | ⬜ pending |
| 04-02 T1 | 04-02 | 1 | RETAIN-02/03 | T-04-03 | portfolio_account_state table + migration + failing portfolio-wrapper suite | integration | `pytest tests/integration/storage/test_cached_sql_portfolio_storage.py --collect-only` | ❌ Wave 0 | ⬜ pending |
| 04-02 T2 | 04-02 | 1 | RETAIN-01/02/03 | T-04-03 | CachedSqlPortfolioStateStorage store-first + read-through + rehydrate + save/load_account_state; cross-portfolio isolation | integration | `pytest tests/integration/storage/test_cached_sql_portfolio_storage.py -x` | ❌ Wave 0 | ⬜ pending |
| 04-02 T3 | 04-02 | 1 | RETAIN-01 | T-04-09 | Portfolio factory 'live' arm wraps; portfolio.py:93 untouched (D-01) | unit/probe | local quarantine probe (subprocess gate in 04-04) | ✅ exists | ⬜ pending |
| 04-03 T1 | 04-03 | 1 | RETAIN-01 | T-04-01 | CachedSqlSignalStorage append-only mirror + failing signal suite | integration | `pytest tests/integration/storage/test_cached_sql_signal_storage.py -x` | ❌ Wave 0 | ⬜ pending |
| 04-03 T2 | 04-03 | 1 | RETAIN-01 | T-04-09 | Signal factory 'live' arm wraps; live_trading_system.py:113 untouched (D-01) | unit/probe | local quarantine probe (subprocess gate in 04-04) | ✅ exists | ⬜ pending |
| 04-04 T1 | 04-04 | 2 | GATE-01 | T-04-09 | Clean-interpreter import-quarantine (no sqlalchemy/cached_sql_storage on backtest path) | unit | `pytest tests/unit/storage/test_import_quarantine.py -x` | ❌ Wave 0 | ⬜ pending |
| 04-04 T2 | 04-04 | 2 | GATE-01/GATE-02 | T-04-09 | Oracle byte-exact + W1/W2 A/B + mypy --strict + full suite | gate | `pytest tests/integration/test_backtest_oracle.py -x && mypy --strict …` | ✅ exists | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] Reuse the existing session-scoped testcontainers Postgres fixture (`pg_backend`, Phase 1 D-10) — no new framework install
- [ ] `tests/integration/storage/test_cached_sql_order_storage.py` — RETAIN-02/03 + Pitfall 7/8 (order seam, wired end-to-end) — created in 04-01 T1
- [ ] `tests/integration/storage/test_cached_sql_portfolio_storage.py` — RETAIN-02/03 + accumulator crash-restart + cross-portfolio isolation — created in 04-02 T1
- [ ] `tests/integration/storage/test_cached_sql_signal_storage.py` — append-only mirror — created in 04-03 T1
- [ ] `tests/unit/storage/test_import_quarantine.py` — GATE-01 clean-interpreter quarantine — created in 04-04 T1
- [ ] No `tests/integration/storage/__init__.py` / `tests/unit/storage/__init__.py` (package-collision hazard, auto-memory)

*Existing infrastructure (pytest + testcontainers Postgres harness) covers all phase requirements — Wave 0 adds test stubs only, no framework install.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| _none anticipated_ | RETAIN-01/02/03, GATE-01 | — | All phase behaviors verifiable via pytest + testcontainers Postgres |

*All phase behaviors have automated verification.*

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references
- [x] No watch-mode flags
- [x] Feedback latency < 30s (unit)
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** planner-populated 2026-06-30

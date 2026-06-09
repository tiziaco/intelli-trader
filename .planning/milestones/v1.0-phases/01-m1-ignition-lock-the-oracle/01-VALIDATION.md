---
phase: 1
slug: m1-ignition-lock-the-oracle
status: draft
nyquist_compliant: true
wave_0_complete: false
created: 2026-06-04
---

# Phase 1 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.
> Derived from RESEARCH.md "Validation Architecture" (Nyquist enabled).

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 8.4.2 (+ pytest-cov 5.0.0) |
| **Config file** | `pyproject.toml` `[tool.pytest.ini_options]` (markers + `filterwarnings=["error"]` + `--strict-markers` + `--strict-config`) |
| **Quick run command** | `poetry run pytest test/ -m "unit" -q` (smoke + fast units) |
| **Full suite command** | `poetry run pytest test/ -q` (274 legacy component tests + new smoke/integration) |
| **Estimated runtime** | ~5s quick (smoke) / full suite + slow integration covers full 2018→2026 run |

---

## Sampling Rate

- **After every task commit:** Run `poetry run pytest test/ -m "unit" -q`
- **After every plan wave:** Run `poetry run pytest test/ -q`
- **Before `/gsd:verify-work`:** Full suite green + integration oracle diff exact (behavioral + numerical, D-13)
- **Max feedback latency:** ~5s (quick) — full integration run is `slow`-marked, run at wave merge / phase gate

---

## Per-Task Verification Map

| Req ID | Behavior | Test Type | Automated Command | File Exists |
|--------|----------|-----------|-------------------|-------------|
| M1-01 | `from itrader.trading_system... import TradingSystem` succeeds (config shadowing fixed) | smoke (unit) | `poetry run pytest test/test_smoke -m unit` | ❌ Wave 0 |
| M1-02 | no `AttributeError` on `config.TIMEZONE` | smoke (unit) | covered by run-a-few-bars smoke | ❌ Wave 0 |
| M1-03 | `to_timedelta('1d')` returns `timedelta(days=1)` (no None on daily path) | smoke (unit) | covered by smoke (loop runs) | ❌ Wave 0 |
| M1-04 | strategy runs without `FutureWarning` (`.iloc[-1]`, `fillna=False`) | smoke (unit) | smoke runs ≥`max_window` bars; `filterwarnings=error` catches FutureWarning | ❌ Wave 0 |
| M1-05 | `record_metrics` invoked per-`Portfolio`; loop completes per-tick | smoke (unit) | smoke asserts run completes | ❌ Wave 0 |
| M1-06 | orders carry `qty > 0` (fraction-of-cash sizing in OrderManager seam) | smoke (unit) | smoke asserts ≥1 trade with non-zero qty | ❌ Wave 0 |
| M1-07 | non-trivial trade log + equity curve on golden CSV | integration (slow) | `poetry run pytest test/test_integration -m integration` | ❌ Wave 0 |
| M1-08 | fresh run == frozen golden (oracle captured + committed) | integration (slow) | integration diffs `output/` vs `test/golden/` (behavioral + numerical exact, D-13) | ❌ Wave 0 |
| M1-09 | 8 declared markers actually applied (path-based auto-marking) | meta | `poetry run pytest test/ --collect-only -q`; `-m portfolio`/`-m events`/… select | ❌ Wave 0 (conftest) |
| M1-10 | 274 legacy tests stay green + run-path integration test exists | full suite | `poetry run pytest test/ -q` | partial (legacy ✅, new ❌) |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `test/conftest.py` — shared fixtures (`global_queue`, golden-file paths, backtest-engine factory) + `pytest_collection_modifyitems` path→marker auto-marking (D-14/D-15). No conftest exists today.
- [ ] `test/test_smoke/test_backtest_smoke.py` — import→construct→run a handful of bars; assert completes + ≥1 non-zero-qty trade (D-16)
- [ ] `test/test_integration/test_backtest_oracle.py` — full 2018→2026 run; diff fresh vs `test/golden/` (D-16)
- [ ] `test/golden/{trades.csv,equity.csv,summary.json}` — frozen oracle, promoted from a blessed `output/` run (D-11)
- [ ] `scripts/run_backtest.py` + `make backtest` target — the committed, reproducible oracle generator (D-05)
- [ ] No framework install needed — pytest 8.4.2 already present

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Blessing/promoting the first oracle run into `test/golden/` | M1-08 | The first oracle has no prior baseline to diff against — a human must inspect the trade log + equity curve for plausibility before freezing | Run `make backtest`, inspect `output/{trades.csv,equity.csv,summary.json}` for a non-trivial trade count and a sane equity curve, then copy into `test/golden/` and commit |

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references
- [x] No watch-mode flags
- [x] Feedback latency < 5s (quick) — full integration is `slow`-marked
- [x] `nyquist_compliant: true` set in frontmatter

> Note: `wave_0_complete` stays `false` — the Wave 0 scaffolding (`test/conftest.py`, smoke, integration,
> `test/golden/`) is BUILT during execution, not at plan time. Flip it to `true` only once those files exist.

**Approval:** approved 2026-06-04

---
phase: 06
slug: pair-trading-flagship
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-06-17
---

# Phase 06 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.
> Derived from 06-RESEARCH.md "## Validation Architecture" + D-11. This phase is the flagship
> demo, NOT the correctness oracle — the ETH/BTC run is locked as a STABILITY snapshot, not a
> hand-verified oracle.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 8.4.2 (`testpaths=["tests"]`, `minversion="8.0"`) |
| **Config file** | `pyproject.toml [tool.pytest.ini_options]` — `filterwarnings=["error"]`, `--strict-markers`, `--strict-config` |
| **Markers (only these declared)** | `unit`, `integration`, `slow`, `e2e` — type marker auto-applied from folder via `tests/conftest.py` |
| **Quick run command** | `poetry run pytest tests/unit/strategy -q` |
| **Full suite command** | `make test` (main checkout; in a worktree use `poetry run pytest tests` — see MEMORY: worktree .env abort) |
| **Typecheck gate** | `poetry run mypy` (strict over `itrader`) |
| **Estimated runtime** | ~quick: a few seconds; full incl. snapshot: ~tens of seconds |

---

## Sampling Rate

- **After every task commit:** `poetry run pytest tests/unit/strategy -q && poetry run mypy`
- **After every plan wave:** `poetry run pytest tests/unit tests/integration -q` (the snapshot is slow — runs in the integration leg)
- **Before `/gsd:verify-work`:** Full suite green + `mypy` clean + determinism double-run byte-identical
- **Max feedback latency:** quick loop < ~10s

---

## Per-Task Verification Map

> All map to the single phase requirement PAIR-01. Threat refs are correctness-shaped, not
> security-shaped (no external input surface — see Manual-Only / research Security Domain).

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| (planner) | — | — | PAIR-01 | — | β-fit (log-OLS) yields expected β on a fixture window | unit | `pytest tests/unit/strategy/test_pair_strategy.py -k beta -x` | ❌ W0 | ⬜ pending |
| (planner) | — | — | PAIR-01 | — | z-score math (rolling mean/std, crossing detection) | unit | `pytest tests/unit/strategy/test_pair_strategy.py -k zscore -x` | ❌ W0 | ⬜ pending |
| (planner) | — | — | PAIR-01 | — | dispatch emits BOTH legs once per tick | unit | `pytest tests/unit/strategy/test_pair_dispatch.py -k both_legs -x` | ❌ W0 | ⬜ pending |
| (planner) | — | — | PAIR-01 | — | require-both-present guard (one leg absent → skip) | unit | `pytest tests/unit/strategy/test_pair_dispatch.py -k both_present -x` | ❌ W0 | ⬜ pending |
| (planner) | — | — | PAIR-01 | — | β-weighted per-leg quantities (N vs β·N) on the SignalEvents | unit | `pytest tests/unit/strategy/test_pair_dispatch.py -k beta_weighted -x` | ❌ W0 | ⬜ pending |
| (planner) | — | — | PAIR-01 | — | close-only exit is no-op when flag-driven flat (D-12) | integration | `pytest tests/integration/test_pair_exit_safety.py -x` | ❌ W0 | ⬜ pending |
| (planner) | — | — | PAIR-01 | — | full ETH/BTC run output matches STABILITY snapshot (NOT oracle) | integration/slow | `pytest tests/integration/test_pair_flagship_snapshot.py -x` | ❌ W0 | ⬜ pending |
| (planner) | — | — | PAIR-01 | — | determinism double-run byte-identical | integration | `pytest tests/integration/test_pair_flagship_snapshot.py -k determinism -x` | ❌ W0 | ⬜ pending |
| (planner) | — | — | PAIR-01 | — | `mypy --strict` clean over new modules | gate | `poetry run mypy` | n/a | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky. Task IDs filled by the planner; every PLAN task must map to a row here.*

---

## Wave 0 Requirements

- [ ] `tests/unit/strategy/test_pair_strategy.py` — β-fit (log-OLS) + z-score math on hand-computed fixtures (D-11)
- [ ] `tests/unit/strategy/test_pair_dispatch.py` — dispatch emits both legs, both-present guard (D-02), β-weighted quantities (D-08)
- [ ] `tests/integration/test_pair_exit_safety.py` — close-only / safe-when-flat exit (D-12 trace as a live test: quantity-free `exit_fraction=1.0` exit no-ops when flat)
- [ ] `tests/integration/test_pair_flagship_snapshot.py` — STABILITY snapshot of the ETH/BTC run + determinism double-run. **MUST be labeled a stability lock, NOT a correctness oracle** (D-11). Mirror the diff mechanic in `tests/integration/test_backtest_oracle.py` (pandas frame-equal on deterministic columns), but the snapshot is generated, not hand-verified.
- [ ] Snapshot artifact location: a **NEW** directory (e.g. `tests/golden/pair/` or `tests/integration/pair_snapshot/`) — do **NOT** touch `tests/golden/{trades,equity}.csv` (the SMA_MACD oracle; D-11 says this phase does NOT re-baseline the golden master).

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Cointegration p-value is logged as a diagnostic, not gated | PAIR-01 (D-10 resolution) | The run intentionally does NOT pass strict Engle-Granger; the value is reported, not asserted | Inspect the run's logged coint p-value; confirm the run completes regardless of `p ≥ 0.05` |
| Single-sided-liquidation re-entry edge case (D-07 × D-12) | PAIR-01 (D-12 resolution) | Accepted + documented for the flagship; the snapshot captures whatever happens — no assertion that it does/doesn't fire | Review the snapshot run for whether a liquidated leg was re-opened; record finding to size the deferred guard follow-up |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < ~10s (quick loop)
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending

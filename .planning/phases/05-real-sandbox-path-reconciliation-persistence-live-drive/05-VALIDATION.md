---
phase: 5
slug: real-sandbox-path-reconciliation-persistence-live-drive
status: populated
nyquist_compliant: true
wave_0_complete: false
created: 2026-07-02
updated: 2026-07-04
scope: 05-13 (WR-05 correlation-state remediation — R1/R2/R3 narrow slice)
---

# Phase 5 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.
> **Reopened scope (2026-07-04):** this file now tracks plan **05-13** (WR-05). Plans
> 05-01…05-12 are shipped/executed and are not re-tracked here.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 8.x |
| **Config file** | pyproject.toml (`[tool.pytest.ini_options]`) |
| **Quick run command** | `poetry run pytest tests/unit/execution -q` |
| **Full suite command** | `make test` (main checkout) / `poetry run pytest tests` (worktree) |
| **Estimated runtime** | unit/execution ~seconds; oracle integration ~30s; full suite ~minutes |

---

## Sampling Rate

- **After every task commit:** Run the task's `<verify><automated>` command (see per-task map).
- **After the plan wave:** Run `poetry run pytest tests/unit/execution tests/integration/test_backtest_oracle.py tests/integration/test_okx_inertness.py -q`.
- **Before `/gsd:verify-work`:** Full suite must be green (`make test` in main checkout; `poetry run pytest tests` in a worktree — `make test` aborts on missing `.env`).
- **Max feedback latency:** < 60s for the unit/execution + oracle sampling loop.

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 05-13-01 | 13 | 1 | RECON-02 / WR-05 R1–R3 | T-05-13-01 | RED suite pins bounded/release/dedup contracts before impl (fail-first) | unit | `poetry run pytest tests/unit/execution/test_venue_correlation.py -q` | ❌ W0 (created by this task) | ⬜ pending |
| 05-13-02 | 13 | 1 | RECON-02 / WR-05 R1 + R3 | T-05-13-01, T-05-13-03 | encapsulated index bounds correlation state (deque(maxlen) ring); lock-guarded cross-thread access preserved (WR-03) | unit | `poetry run pytest tests/unit/execution/test_okx_fill_idempotency.py tests/unit/execution/test_okx_exchange.py -q && poetry run mypy itrader` | ✅ (test_okx_exchange.py, test_okx_fill_idempotency.py, test_okx_sandbox_recon.py exist; repointed here) | ⬜ pending |
| 05-13-03 | 13 | 1 | RECON-02 / WR-05 R2 | T-05-13-02, T-05-13-04 | fill-driven release-on-terminal (drain-then-evict, emit-outside-lock — no lost fill / WR-02 regression); oracle byte-exact + inertness (no backtest touch) | unit + integration | `poetry run pytest tests/unit/execution/test_venue_correlation.py tests/unit/execution/test_okx_fill_idempotency.py tests/integration/test_backtest_oracle.py tests/integration/test_okx_inertness.py -q && poetry run mypy itrader` | ✅ (oracle + inertness gates exist; test_venue_correlation.py from 05-13-01) | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

*Nyquist: every 05-13 task carries an `<automated>` verify (no manual-only task). Task 05-13-01
is the fail-first (RED) scaffold that Tasks 02/03 turn GREEN — the phase's Wave-0 test dependency
is satisfied in-plan, so no separate Wave-0 file is outstanding for 05-13.*

---

## Wave 0 Requirements

- [x] Fail-first `test_venue_correlation.py` (socket-free direct-index suite) — created by Task 05-13-01 (the RED scaffold Tasks 02/03 satisfy).
- [ ] N/A — no recorded-OKX fixture / `FakeLiveConnector` scaffold needed for 05-13 (the existing `_FakeConnector` in `test_okx_fill_idempotency.py` covers the OkxExchange delegation checks; the index is tested with no connector at all).

*05-13 is a bounded encapsulation + release-on-terminal refactor of a live-only module; its
Wave-0 obligation is the in-plan RED suite, not new network/fixture infrastructure.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| W1/W2 within the v1.5 frozen baseline (15.7s / 152.8MB) | WR-05 zero-backtest gate | No in-suite perf benchmark harness; W1/W2 are measured out-of-band and are thermally sensitive (prior-learning). Structurally enforced by the inertness gate (backtest path imports no async/connector code). | Confirm `test_okx_inertness.py` GREEN as the structural proxy; if a benchmark box is available, run the W1/W2 bench and compare against the frozen baseline (same-machine A/B, not a cross-machine wall-clock compare). Record the result in 05-13-SUMMARY.md. |

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies (05-13-01 RED scaffold satisfies the Wave-0 dep in-plan)
- [x] Sampling continuity: no 3 consecutive tasks without automated verify (all 3 tasks automated)
- [x] Wave 0 covers all MISSING references (the only ❌/W0 file — `test_venue_correlation.py` — is created by Task 05-13-01)
- [x] No watch-mode flags
- [x] Feedback latency < 60s (unit/execution + oracle sampling loop)
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** populated for 05-13 (2026-07-04)

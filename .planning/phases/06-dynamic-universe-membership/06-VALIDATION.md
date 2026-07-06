---
phase: 6
slug: dynamic-universe-membership
status: ready
nyquist_compliant: true
wave_0_complete: false
created: 2026-07-06
---

# Phase 6 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 8.x (+ pytest-asyncio, configured `asyncio_mode` — COV-01) |
| **Config file** | pyproject.toml (`[tool.pytest.ini_options]`) |
| **Quick run command** | `poetry run pytest tests/unit -q` |
| **Full suite command** | `make test` (in a worktree use `poetry run pytest tests` — `.env` abort, memory) |
| **Estimated runtime** | ~10 seconds (unit) / full suite per Makefile |
| **Perf runner** | `make perf-w1` (W1 benchmark + `--check` regression guard) / `make perf-w2` (scaling sweep) |

---

## Sampling Rate

- **After every task commit:** Run the task's `<automated>` command (each < 5s).
- **After every plan wave:** Run `poetry run pytest tests/unit tests/integration -q`.
- **Before `/gsd:verify-work`:** Full suite green + oracle byte-exact + paper-parity + inertness.
- **Max feedback latency:** 15 seconds.

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 06-01-01 | 01 | 1 | UNIV-01 | T-06-01-DOS | Emitted UNIVERSE_UPDATE never raises NotImplementedError (explicit-empty route ships with the enum member) | unit | `poetry run pytest tests/unit/events/test_universe_update_event.py -x -q` | ❌ W0 (RED, authored in-task) | ⬜ pending |
| 06-01-02 | 01 | 1 | UNIV-01 | T-06-01-TAMPER | slice-assign `_members[:]` preserves the feed's by-identity bind (id() identity test) | unit | `poetry run pytest tests/unit/universe/test_universe_apply.py -x -q` | ❌ W0 (RED, authored in-task) | ⬜ pending |
| 06-02-01 | 02 | 1 | UNIV-02 | T-06-02-SPOOF | subscribe/unsubscribe registry; symbols filtered by D-06 upstream (plan 03) | unit (async, mocked connector) | `poetry run pytest tests/unit/price/test_okx_dynamic_subscribe.py -x -q` | ❌ W0 (RED, authored in-task) | ⬜ pending |
| 06-02-02 | 02 | 1 | UNIV-02 | T-06-02-TAMPER | per-symbol supervisor keys (no `"candles"` collision); `confirm='0'` snapshot dropped | unit (async) | `poetry run pytest tests/unit/price/test_warmup_on_add.py -x -q` | ❌ W0 (RED, authored in-task) | ⬜ pending |
| 06-03-01 | 03 | 2 | UNIV-01 | — | pure selection seam, holds NO queue/feed (purity-by-construction) | unit | `poetry run pytest tests/unit/universe/test_universe_selection.py -x -q` | ❌ W0 (RED, authored in-task) | ⬜ pending |
| 06-03-02 | 03 | 2 | UNIV-01 | T-06-03-SPOOF | `validate_symbol` (D-06) filters desired BEFORE `apply`; emit-only-on-non-empty delta | unit | `poetry run pytest tests/unit/universe/test_universe_poll.py -x -q` | ❌ W0 (RED, authored in-task) | ⬜ pending |
| 06-04-01 | 04 | 3 | UNIV-02 | T-06-04-EOP | leaving-symbol admission gate audited-REJECTS new entries, allows sanctioned exits | unit | `poetry run pytest tests/unit/order/test_leaving_symbol_admission.py -x -q` | ❌ W0 (RED, authored in-task) | ⬜ pending |
| 06-04-02 | 04 | 3 | UNIV-02 | T-06-04-TAMPER | orphan-and-track DEFERS unsubscribe until flat; detach-on-flat FILL | unit | `poetry run pytest tests/unit/universe/test_universe_poll.py -x -q` | ❌ W0 (RED, extends 06-03-02) | ⬜ pending |
| 06-04-03 | 04 | 3 | UNIV-02 | T-06-04-TAMPER | deterministic multi-symbol replay proof (orphan defer-until-flat + force-close settle-then-detach) | integration (paper/replay) | `poetry run pytest tests/integration/test_universe_remove_policy.py tests/integration/test_universe_force_close.py -x -q` | ❌ W0 (fixture + tests authored in-task) | ⬜ pending |
| 06-05-01 | 05 | 4 | UNIV-01 / UNIV-02 | T-06-05-DOS | membership-driven subscribe (warmup-before-subscribe); oracle byte-exact | integration | `poetry run pytest tests/integration/test_backtest_oracle.py tests/integration/test_paper_parity.py -x -q` | ✅ exists | ⬜ pending |
| 06-05-02 | 05 | 4 | UNIV-01 / UNIV-02 | T-06-05-TAMPER, T-06-05-DOS | live-only route mutation (backtest `_routes` literal untouched); no W1/W2 regression via `make perf-w1` / `make perf-w2` | integration | `poetry run pytest tests/integration/test_okx_inertness.py tests/integration/test_backtest_oracle.py tests/integration/test_paper_parity.py -x -q` | ✅ exists (+ extended `_FORBIDDEN`) | ⬜ pending |
| 06-05-03 | 05 | 4 | UNIV-02 | T-06-05-SPOOF | gated live-demo DATA subscribe/unsubscribe; `sandbox=True` asserted before any op | e2e (gated) | `poetry run pytest -m "not live" tests/e2e/test_okx_dynamic_universe.py -q` (CI-safe) + `-m live` human-check | ❌ W0 (authored in-task) | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

**Milestone gate (06-05, recurring):** SMA_MACD backtest oracle byte-exact (`134` / `46189.87730727451`, `check_exact=True`), determinism double-run identical, no W1/W2 regression vs the v1.5 frozen baseline (15.7s / 152.8 MB). Perf is measured by the executor with `make perf-w1` (`--check` regression guard vs `perf/results/W1-BASELINE.json`; on a thermally-throttled box use a same-machine A/B, not a bare frozen compare — memory: v1.5 perf-gate thermal drift) and recorded in the 06-05 SUMMARY per the Phase-5 (05-09) convention.

---

## Wave 0 Requirements

- Test stubs are authored **in-task** (the RED step): every code-producing task is `tdd="true"` and creates its own test file before implementation. No separate pre-execution Wave 0 scaffold is required — there are no `MISSING` `<automated>` references across the five plans.
- Intra-plan shared dependency: the multi-symbol replay fixture in `tests/integration/conftest.py` (06-04-03) must exist before `test_universe_remove_policy.py` / `test_universe_force_close.py` run — both authored in the same task.
- Reused existing infrastructure (no authoring needed): `tests/integration/test_backtest_oracle.py`, `tests/integration/test_paper_parity.py`, `tests/integration/test_okx_inertness.py` (milestone gates).

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Live OKX dynamic data subscribe/unsubscribe (demo) | UNIV-02 | Requires a live OKX demo WS session (sandbox=True); not deterministic in CI (fenced by `-m "not live"`) | Run `poetry run pytest tests/e2e/test_okx_dynamic_universe.py -x -q -m live`; subscribe ETH/USDC mid-run against the demo, observe closed (`confirm=='1'`) bars arrive; unsubscribe, observe the stream stop |

The automated half of this behavior (`-m "not live"` collection + sandbox-assert structure) IS covered by 06-05-03's `<automated>` command; only the live-observed run is manual.

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references (none — all tests authored in-task as RED steps)
- [x] No watch-mode flags
- [x] Feedback latency < 15s
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** approved 2026-07-06

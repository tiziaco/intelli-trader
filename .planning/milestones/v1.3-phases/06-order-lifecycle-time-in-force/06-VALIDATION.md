---
phase: 6
slug: order-lifecycle-time-in-force
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-06-13
---

# Phase 6 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest ^8.4.2 (`testpaths=["tests"]`, `--strict-markers`, `--strict-config`, `filterwarnings=["error"]`) |
| **Config file** | `pyproject.toml [tool.pytest.ini_options]` |
| **Quick run command** | `poetry run pytest tests/unit/order tests/unit/execution -x` |
| **Full suite command** | `make test` |
| **Estimated runtime** | quick ~10s · full suite ~minutes (includes 58 e2e leaves) |

---

## Sampling Rate

- **After every task commit:** Run `poetry run pytest tests/unit/order tests/unit/execution -x`
- **After every plan wave:** Run `make test`
- **Before `/gsd:verify-work`:** Full suite green + `poetry run mypy itrader` clean + SMA_MACD oracle byte-exact (`134 / 46189.87730727451`) + determinism double-run identical + owner sign-off on the attribution report.
- **Max feedback latency:** ~10 seconds (quick), full suite per wave.

---

## Per-Task Verification Map

> Plan/task IDs assigned by the planner; this maps the LIFE-01 behaviors to their verification.

| Behavior | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|----------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| Run-end resting order → EXPIRED, nothing stuck PENDING | LIFE-01 | — | N/A (engine-internal) | e2e | `poetry run pytest tests/e2e/matching/never_fill -m e2e` (re-baselined to EXPIRED) | ⚠️ EXISTS (re-baseline) | ⬜ pending |
| SL+TP brackets on still-open position → EXPIRED, position stays open (D-02) | LIFE-01 | — | N/A | e2e | `poetry run pytest tests/e2e/sltp/from_decision_held tests/e2e/sltp/from_fill_held -m e2e` (re-baselined) | ⚠️ EXIST (re-baseline goldens) | ⬜ pending |
| `expire_all_resting` local transition + idempotent release + emit, deterministic order (D-08/D-10) | LIFE-01 | — | N/A | unit | `poetry run pytest tests/unit/order/ -k "expire" -x` | ❌ W0 (new) | ⬜ pending |
| Reconcile EXPIRED arm + idempotency on already-EXPIRED order (D-09 LANDMINE) | LIFE-01 | reconcile integrity | no double-release, no invalid transition | unit | `poetry run pytest tests/unit/order/ -k "reconcile and expir" -x` | ❌ W0 (extend) | ⬜ pending |
| `OrderCommand.EXPIRE` removes resting + emits `FillEvent(EXPIRED)`; no spurious fill for non-resting order | LIFE-01 | — | N/A | unit | `poetry run pytest tests/unit/execution/ -k "expire" -x` | ❌ W0 (new) | ⬜ pending |
| Final drain after sweep emits no SIGNAL / new ORDER(NEW) (D-08 non-cascade) | LIFE-01 | — | N/A | unit/integration | assert queue has no SignalEvent / OrderEvent(NEW) after drain | ❌ W0 (new) | ⬜ pending |
| SMA_MACD oracle byte-exact after wiring (D-04 equity-neutrality) | LIFE-01 | — | N/A | integration | `make test-integration` (oracle test) | ✅ EXISTS — must stay byte-exact | ⬜ pending |
| Determinism double-run byte-identical (D-06) | LIFE-01 | — | N/A | integration | existing determinism double-run gate | ✅ EXISTS | ⬜ pending |
| Dead-path removal: `create_order`/`create_orders_from_signal` gone, `mypy --strict` clean, enum still resolves (D-03 / Pitfall 1) | LIFE-01 | narrows unvalidated surface | KEEP `CREATE_ORDERS_FROM_SIGNAL` enum (live `bracket_manager` uses it) | static + unit | `poetry run mypy itrader` + `make test` | ✅ gate EXISTS | ⬜ pending |
| EXPIRED appears in `count_orders_by_status` / `build_orders_snapshot` for free (D-12) | LIFE-01 | — | N/A | unit | `poetry run pytest tests/unit/order/ -k "count_orders_by_status" -x` | ⚠️ extend existing | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/unit/order/test_expire_all_resting.py` (or extend `test_lifecycle_manager.py`) — sweep order (D-10), local transition, idempotent release, `OrderEvent(EXPIRE)` emission — covers LIFE-01 sweep.
- [ ] Extend `tests/unit/order/` reconcile branch-coverage with the EXPIRED arm + the idempotent-already-EXPIRED case (D-09 LANDMINE) — covers LIFE-01 reconcile.
- [ ] `tests/unit/execution/` EXPIRE-command arm test (remove resting + emit EXPIRED; no spurious fill for non-resting order) — covers exchange arm.
- [ ] Non-cascade assertion (D-08) — verify the post-sweep drain emits no SIGNAL / new ORDER(NEW).
- [ ] Re-purpose `tests/e2e/matching/never_fill` as the D-05 positive-proof leaf (it already builds the far-from-market resting-order scenario; its docstring asserting "no run-end expiry" is now wrong and must flip to assert EXPIRED).
- [ ] Re-baseline goldens for the 3 affected e2e leaves (`matching/never_fill`, `sltp/from_decision_held`, `sltp/from_fill_held`) — execution-time, under owner sign-off, via the `--freeze` discipline.

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Owner sign-off on the run-end-disposition attribution report | LIFE-01 (Success Criterion 3) | Re-baseline posture is owner-gated by project discipline (STATE.md §Milestone Gate v1.3) — the new golden disposition is frozen ONLY after explicit owner approval of the attribution (which orders expire, equity/metric impact). | Present the attribution report (3 affected leaves + byte-exact SMA_MACD oracle confirmation); owner approves before `--freeze` of any re-baselined golden. |

---

## Validation Sign-Off

- [ ] All tasks have automated verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < ~10s (quick) / full suite per wave
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending

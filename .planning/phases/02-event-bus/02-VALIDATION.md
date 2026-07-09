---
phase: 2
slug: event-bus
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-07-09
---

# Phase 2 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.
> Derived from `02-RESEARCH.md` § Validation Architecture. Task IDs are seeded at
> requirement granularity; the planner/executor refines exact `NN-PP-TT` IDs once plans exist.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest ^8.4.2 (`minversion="8.0"`, `--strict-markers --strict-config`, `filterwarnings=["error"]`) |
| **Config file** | `pyproject.toml [tool.pytest.ini_options]` (`testpaths=["tests"]`) |
| **Quick run command** | `poetry run pytest tests/unit/events -x` |
| **Full suite command** | `make test` (main checkout) or `poetry run pytest tests` (worktree — see worktree `.env` memory) |
| **Estimated runtime** | ~8 seconds full unit suite; oracle+inertness integration ~a few seconds |

---

## Sampling Rate

- **After every task commit:** Run `poetry run pytest tests/unit/events/test_event_bus.py -x` (fast — pure stdlib, no data load)
- **After every plan wave / per-PLAN gate:** Run `poetry run pytest tests/integration/test_backtest_oracle.py tests/integration/test_okx_inertness.py -x` (the two milestone gates — oracle byte-exact + import inertness). **Determinism double-run:** run the oracle twice, assert identical `134 / 46189.87730727451`.
- **Before `/gsd-verify-work` (phase gate):** Full suite green + `poetry run mypy itrader` clean on new/edited in-scope code + `poetry.lock` byte-unchanged (no new dependency in P1–P12).
- **Max feedback latency:** ~10 seconds (quick unit run)

---

## Per-Task Verification Map

> Seeded at requirement granularity from RESEARCH § Phase Requirements → Test Map.
> Planner substitutes concrete Task IDs (`02-PP-TT`) during planning.

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 02-*-* | TBD | 1 | BUS-01 | — | Both buses satisfy Protocol; `.put()`/`get_nowait()` surface; no call-site change | unit | `poetry run pytest tests/unit/events/test_event_bus.py -x` | ❌ W0 | ⬜ pending |
| 02-*-* | TBD | 1 | BUS-02 | — | `(tier,seq,event)` ordering: CONTROL preempts, within-tier FIFO, event never compared, `Event < Event` raises `TypeError` | unit | `poetry run pytest tests/unit/events/test_event_bus.py -k priority -x` | ❌ W0 | ⬜ pending |
| 02-*-* | TBD | 1 | BUS-03 | — | 3 CONTROL `EventType`s exist + assigned CONTROL via `_CONTROL_EVENT_TYPES`; backtest wires `FifoEventBus` | unit | `poetry run pytest tests/unit/events/test_event_bus.py -k control_types -x` | ❌ W0 | ⬜ pending |
| 02-*-* | TBD | 2 | BUS-04 / CTX-01 | — | `compose_engine(ctx, spec)` signature; internal `queue.Queue()` deleted | unit/integration | `poetry run pytest tests/integration/test_okx_inertness.py -x` | ✅ (extend) | ⬜ pending |
| 02-*-* | TBD | 2 | CTX-02 | — | Order + Strategies handlers own storage from `(environment, sql_engine)`; `.storage` readable back | unit | `poetry run pytest tests/unit/order tests/unit/strategy -x` | ✅/❌ new case | ⬜ pending |
| 02-*-* | TBD | 2 | CTX-03 / oracle | — | Backtest → same in-memory instances → byte-exact `134 / 46189.87730727451` | integration | `poetry run pytest tests/integration/test_backtest_oracle.py -x` | ✅ | ⬜ pending |
| 02-*-* | TBD | 2 | inertness | — | `FifoEventBus`/`EngineContext(sql_engine=None)` pull nothing heavy; import builds no `SqlSettings` | integration | `poetry run pytest tests/integration/test_okx_inertness.py -x` | ✅ (extend register-vs-build) | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/unit/events/test_event_bus.py` — covers BUS-01/02/03 (Protocol conformance for both buses; priority ordering + non-orderability negative test; `_CONTROL_EVENT_TYPES` tier assignment). **Do NOT add `tests/unit/events/__init__.py`** — the empty-`__init__` package-collision hazard (project memory) breaks full-suite collection; keep `tests/unit/*` package-less.
- [ ] Extend `tests/integration/test_okx_inertness.py` — add the register-vs-build assertion that constructing `EngineContext(sql_engine=None)` + `FifoEventBus` pulls no SQLAlchemy/ccxt (append to `_PROBE` and/or an in-process assertion that `FifoEventBus()` and the backtest `compose_engine` build no `SqlSettings`).
- [ ] New handler-storage unit cases: `OrderHandler(..., environment='backtest', sql_engine=None)` yields `InMemoryOrderStorage` and exposes `.storage`; same for `StrategiesHandler` → in-memory signal store.
- Framework install: none — pytest infra already present.

---

## Manual-Only Verifications

All phase behaviors have automated verification. The two milestone gates (`test_backtest_oracle.py`, `test_okx_inertness.py`) plus new `tests/unit/events/test_event_bus.py` cover every requirement.

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 10s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending

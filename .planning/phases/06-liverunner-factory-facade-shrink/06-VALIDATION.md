---
phase: 6
slug: liverunner-factory-facade-shrink
status: approved
nyquist_compliant: true
wave_0_complete: false
created: 2026-07-13
approved: 2026-07-13
---

# Phase 6 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.
> Derived from `06-RESEARCH.md` § Validation Architecture. This phase is **oracle-sensitive** — the gates below are load-bearing.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest ^8.4.2 — `testpaths=["tests"]`, `filterwarnings=["error"]`, `--strict-markers`, `--strict-config` |
| **Config file** | `pyproject.toml [tool.pytest.ini_options]` |
| **Quick run command** | `poetry run pytest tests/integration/test_backtest_oracle.py -x -q` |
| **Full suite command** | `make test` (⚠ aborts in worktrees on missing `.env` → use `poetry run pytest tests` there — MEMORY: worktree-make-test-env-abort; note `make test` exports `ITRADER_DISABLE_LOGS=true` which fails caplog warn-assertions) |
| **Estimated runtime** | oracle ~a few s; full suite ~7–8 s |

---

## Sampling Rate

- **After every task commit:** Run `poetry run pytest tests/integration/test_backtest_oracle.py -x -q` (byte-exact oracle) + `poetry run mypy itrader`
- **After every plan wave:** Run `poetry run pytest tests/integration/test_okx_inertness.py tests/integration/test_paper_parity.py -x -q` (inertness + paper-parity), then full `poetry run pytest tests`
- **Before `/gsd-verify-work`:** Full suite green + oracle byte-exact double-run identical
- **Max feedback latency:** ~10 s

---

## Load-Bearing Gates (from RESEARCH.md § Validation Architecture)

| Gate | Signal | Command | Applies to |
|------|--------|---------|------------|
| **Byte-exact oracle** | `134 / 46189.87730727451` (`check_exact=True`) + determinism double-run | `poetry run pytest tests/integration/test_backtest_oracle.py -x -q` run **twice**, assert identical | **per-PLAN gate ON the `wire_universe` (RUN-04) plan** — milestone's highest oracle risk |
| **Inertness** | live decomposition imports no `ccxt.pro` on the backtest path | `poetry run pytest tests/integration/test_okx_inertness.py -x -q` (extend register-vs-build to the new `build_live_system`/`LiveRunner`/registrar surface; file already anticipates `build_live_system` at `:84`) | RUN-01/02/03/05/06 — continuous |
| **Paper-parity** | must stay green **CONTINUOUSLY** | `poetry run pytest tests/integration/test_paper_parity.py -x -q` | RUN-01..07 + TEST-01 — continuous, esp. through the TEST-01 relocation |
| **mypy strict** | new modules in strict scope typecheck | `poetry run mypy itrader` | per-plan |
| **Warning-as-error** | `filterwarnings=["error"]` green — esp. `PytestCollectionWarning` on `Test*` classes → `__test__ = False` (D-22) | full/targeted suite | per-plan (TEST-01 critical) |

---

## Per-Task Verification Map

*Populated as plans are created (task IDs do not exist yet). Every task must map to one of the load-bearing gates above or a Wave 0 dependency. The `wire_universe` (RUN-04) plan carries the byte-exact oracle double-run as its per-task gate.*

| Task ID | Plan | Wave | Requirement | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------------|-----------|-------------------|-------------|--------|
| 06-01-01 | 01 | 1 | RUN-04 | oracle byte-exact preserved | integration | `poetry run pytest tests/integration/test_backtest_oracle.py -x -q` (×2, identical) | ✅ | ⬜ pending |
| _(remaining rows filled at plan time)_ | | | | | | | | |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] Extend `tests/integration/test_okx_inertness.py` register-vs-build assertions to the new factory/runner/registrar surface (anticipated at `:84`); after TEST-01, re-author the `:155` `ReplayDataPlugin` import assertion to assert the PRODUCTION path no longer registers `replay` at all (the stronger post-D-21 invariant).
- [ ] Add a collection-safety assertion for the relocated `Test*` classes — a test that imports the fixture module and asserts pytest collected **0** items from it (proves `__test__ = False` holds under `filterwarnings=["error"]`).
- [ ] `tests/unit/price/test_replay_provider.py` follows `ReplayDataProvider` → `tests/` (rename import to `TestLiveDataProvider`).

*Existing infrastructure (oracle, inertness, paper-parity) covers the core RUN-01..07 requirements; the above are additive gaps the relocation/decomposition introduces.*

---

## Structural-Only Verifications (verified at P6 close, NOT by a numeric gate)

| Behavior | Requirement | Why Not Automated | Check Instructions |
|----------|-------------|-------------------|--------------------|
| Facade shrink is structural — NOT the literal `~200` lines | RUN-03 | `~200-line facade` is a **milestone-EXIT gate verified at P7 close** (D-03); P7 depends on P6 so the extraction physically can't finish in P6 | At P6 close verify STRUCTURE: `build_live_system` owns the wiring; `LiveRunner` owns the drain loop; `__init__` sheds `exchange`/`to_sql`/`queue_timeout`/`max_idle_time`; `print_status`/`get_statistics` deleted; session-init → `wire_universe`/`SessionInitializer`; routes → `LiveRouteRegistrar`. **MUST NOT fail RUN-03 for a ~600–700-line interim facade.** |
| Live constructs `PriorityEventBus`; CONTROL routes NOT registered | D-23 / RUN-01 | Inert without CONTROL events (BUSINESS tier + monotonic `seq` = strict FIFO); no oracle/behavior signal at P6 | Assert `build_live_system` wires live onto `PriorityEventBus` and that `LiveRouteRegistrar` registers only the BUSINESS/live route set (`UNIVERSE_POLL/UPDATE`, `STRATEGY_COMMAND`, `BARS_LOADED`, `BARS_LOAD_FAILED`, `FILL`) — CONTROL entries (`STREAM_STATE`/`CONNECTOR_FATAL`/`CONFIG_UPDATE`) absent (their P7/P9 consumers don't exist) |

---

## Validation Sign-Off

*Verified by gsd-plan-checker against the 7 plans on 2026-07-13 (Dimension 8 all-pass).*

- [x] All tasks have an automated verify (mapped to a load-bearing gate) or a Wave 0 dependency
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 references are all covered by tasks (inertness extension → 06-06 Task 3; collection-safety → 06-07 Task 3; relocated provider test → 06-07). *(`wave_0_complete` stays `false` until those tasks EXECUTE — planned ≠ built.)*
- [x] No watch-mode flags
- [x] Feedback latency < 10s
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** approved 2026-07-13 (plan-checker; 0 blockers)

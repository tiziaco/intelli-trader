---
phase: 9
slug: runtime-config-platform
# status lifecycle: draft (seeded by plan-phase) → validated (set by validate-phase §6)
# audit-milestone §5.5 distinguishes NOT-VALIDATED (draft) from PARTIAL (validated + nyquist_compliant: false) (#2117)
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-07-16
---

# Phase 9 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.
> Seeded from `09-RESEARCH.md` §Validation Architecture + §Security Domain.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest ^8.4.2 (Poetry-run) |
| **Config file** | `pyproject.toml` `[tool.pytest.ini_options]` (`filterwarnings=["error"]`, `--strict-markers`, `--strict-config`) |
| **Quick run command** | `poetry run pytest tests/unit/config tests/unit/storage -x` |
| **Full suite command** | `make test` (in worktrees: `poetry run pytest tests` — `make test` aborts on missing `.env`) |
| **Estimated runtime** | ~8 s (quick unit run); full suite several minutes |

**Per-phase GATE tests (must stay green on every restructure task):**
- `poetry run pytest tests/integration/test_backtest_oracle.py -x` — byte-exact `134 / 46189.87730727451`
- `poetry run pytest tests/integration/test_okx_inertness.py -x` — `config/` restructure stays SQL/ccxt-import-free

---

## Sampling Rate

- **After every task commit:** Run `poetry run pytest tests/unit/config tests/unit/storage -x` + **both GATE commands** (oracle + inertness) on any config-restructure or `rng_seed`-path task.
- **After every plan wave:** Run `make test` (or `poetry run pytest tests`).
- **Before `/gsd-verify-work`:** Full suite green + both GATE tests green.
- **Max feedback latency:** ~8 s (quick run) / ~seconds (GATE tests).

---

## Per-Task Verification Map

> Task IDs are assigned by the planner (Step 8). This map is filled per-plan during planning/execution.
> The requirement→behaviour→command spine below is lifted from `09-RESEARCH.md` §Validation Architecture.

| Requirement | Behavior | Threat Ref | Test Type | Automated Command | File Exists | Status |
|-------------|----------|------------|-----------|-------------------|-------------|--------|
| RTCFG-01 | Frozen base blocks base-param setattr; sub-model mutate + `validate_assignment` coercion/constraints; unhashable gotcha | T-9-tamper (frozen key) | unit | `poetry run pytest tests/unit/config/test_itrader_config.py -x` | ❌ W0 | ⬜ pending |
| RTCFG-02 | Router validate→persist→apply→push; default-deny unknown scope/key | T-9-massassign | unit + integration | `poetry run pytest tests/unit/trading_system/test_config_router.py -x` | ❌ W0 | ⬜ pending |
| RTCFG-03 | Persisted overrides re-layered at boot | — | integration | `poetry run pytest tests/integration/test_config_restart_layering.py -x` | ❌ W0 | ⬜ pending |
| RTCFG-04 | Immutable keys (`rng_seed`/`environment`) rejected | T-9-frozen-key | unit | (part of `test_itrader_config.py`) | ❌ W0 | ⬜ pending |
| RTCFG-05 | Live-venue fee/slippage rejected; sim allowed (venue-kind predicate) | T-9-venue-kind | unit | `poetry run pytest tests/unit/trading_system/test_config_router.py -k venue_kind` | ❌ W0 | ⬜ pending |
| RTCFG-06 | `system_stats` append + `state.*` upsert; lock-free reads | — | unit + integration | `poetry run pytest tests/unit/storage/test_system_stats_store.py -x` | ❌ W0 | ⬜ pending |
| D-23 (ingress) | External `CONFIG_UPDATE` drives the path directly via `add_event` | T-9-event-inject | integration | new test driving `add_event(ConfigUpdateEvent(...))` | ❌ W0 | ⬜ pending |
| GATE (oracle) | `rng_seed` path move stays byte-exact | — | integration | `poetry run pytest tests/integration/test_backtest_oracle.py -x` | ✅ | ⬜ pending |
| GATE (inertness) | `config/` restructure stays SQL/ccxt-free | — | integration | `poetry run pytest tests/integration/test_okx_inertness.py -x` | ✅ | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/unit/config/test_itrader_config.py` — frozen base blocks base-param setattr, sub-model mutate, `validate_assignment` coercion/constraints, unhashable gotcha (RTCFG-01/04)
- [ ] `tests/unit/trading_system/test_config_router.py` — validate→persist→apply→push, default-deny, venue-kind predicate, persist-failure-rejects (RTCFG-02/05)
- [ ] `tests/integration/test_config_restart_layering.py` — persisted overrides survive restart (RTCFG-03)
- [ ] `tests/unit/storage/test_system_stats_store.py` — `system_stats` append + read; `state.*` upsert (RTCFG-06/D-18)
- [ ] External-ingress integration test driving `add_event(ConfigUpdateEvent(...))` directly (D-23 — **mandatory**, no FastAPI driver yet)
- [ ] Metadata-parity gate extension for `system_stats` (registrar single-source; likely auto-covered by `env.py` import — verify the existing parity test enumerates registrars dynamically)
- [ ] Keep `tests/unit/config/` **package-less** — no `__init__.py` (avoid the top-level package collision; see memory `test-dir-init-py-package-collision`)

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| — | — | — | — |

*All phase behaviors have automated verification. The FastAPI ingress + auth surface is out of scope (LR-01); P9 drives the external `CONFIG_UPDATE` path directly in tests (D-23).*

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < ~8s (quick run)
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending

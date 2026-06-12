---
phase: 2
slug: strategy-authoring-surface
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-06-12
---

# Phase 2 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest ^8.4.2 (`minversion = "8.0"`, `testpaths = ["tests"]`) |
| **Config file** | `pyproject.toml` `[tool.pytest.ini_options]` (`filterwarnings=["error"]`, `--strict-markers`, `--strict-config`) |
| **Quick run command** | `poetry run pytest tests/unit/strategy/ -x` (a.k.a. `make test-strategy`) |
| **Full suite command** | `make test` (unit + integration + e2e + oracle) |
| **Estimated runtime** | ~quick <10s · full suite ~minutes |

---

## Sampling Rate

- **After every task commit:** Run `poetry run pytest tests/unit/strategy/ -x` (engine + hook unit coverage)
- **After every plan wave:** Run `make test-strategy && poetry run pytest tests/integration/ -x`
- **Before `/gsd:verify-work`:** `make test` full suite green (incl. `test_backtest_oracle` + 58 e2e) AND `mypy --strict` clean
- **Max feedback latency:** ~10 seconds (quick) / minutes (full)

---

## Per-Task Verification Map

> Task IDs are assigned by the planner. This map seeds the requirement→test mapping
> from RESEARCH §"Validation Architecture"; the planner fills per-task IDs into the
> `<automated>` fields of each PLAN.md task.

| Requirement | Secure Behavior | Test Type | Automated Command | File Exists |
|-------------|-----------------|-----------|-------------------|-------------|
| STRAT-01 | reject unknown kwarg → `UnknownParamError` | unit | `poetry run pytest tests/unit/strategy/test_strategy_config.py -k unknown -x` | ❌ W0 |
| STRAT-01 | reject missing-required → `MissingParamError` | unit | `poetry run pytest tests/unit/strategy/test_strategy_config.py -k missing_required -x` | ❌ W0 |
| STRAT-01 | kwargs override class-attr default | unit | `poetry run pytest tests/unit/strategy/test_strategy_config.py -k override -x` | ❌ W0 |
| STRAT-01 | str→enum coercion (`timeframe="1d"`→timedelta on instance) | unit | `poetry run pytest tests/unit/strategy/test_strategy_config.py -k coerce -x` | ❌ W0 |
| STRAT-01 | non-enum knob NOT coerced | unit | `poetry run pytest tests/unit/strategy/test_strategy_config.py -k no_coerce_int -x` | ❌ W0 |
| STRAT-01 | `validate()` rejects `short>=long` (HARD-02) | unit | `poetry run pytest tests/unit/strategy/test_strategy_config.py -k short_lt_long -x` | ⚠️ migrate |
| STRAT-01 | `init()` idempotent (call twice → identical state) | unit | `poetry run pytest tests/unit/strategy/test_strategy.py -k idempotent -x` | ❌ W0 |
| STRAT-01 | `reconfigure(**kwargs)` re-applies + re-validates | unit | `poetry run pytest tests/unit/strategy/test_strategy.py -k reconfigure -x` | ❌ W0 |
| STRAT-01 | SignalRecord carries dict snapshot (D-04) | unit | `poetry run pytest tests/unit/strategy/test_signal_store.py -k record_fields -x` | ⚠️ migrate |
| STRAT-01 | BTCUSD oracle byte-exact (134 / 46189.87730727451) | integration | `poetry run pytest tests/integration/test_backtest_oracle.py -x` | ✅ gate |
| STRAT-01 | e2e 58/58 byte-exact | e2e | `poetry run pytest tests/e2e/ -x` | ✅ gate |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/unit/strategy/test_strategy_config.py` — **rewrite** from `BaseStrategyConfig` pydantic tests to the class-attribute-surface tests (unknown / missing-required / override / coerce / no-coerce). D-05 note explicitly calls for rewrite-not-delete.
- [ ] `tests/unit/strategy/test_strategy.py` — add idempotency test (D-11) + reconfigure test (D-12); migrate construction to the kwargs surface.
- [ ] `tests/unit/strategy/test_signal_store.py` — migrate `record.config is strategy.config` (identity) + `model_dump()` to dict-shape `==` assertions (D-04).
- [ ] `itrader/core/exceptions/strategy.py` — NEW module: `UnknownParamError`, `MissingParamError` (subclass `ValidationError`).
- [ ] No framework install needed (pytest already present).

---

## Manual-Only Verifications

*All phase behaviors have automated verification.* The byte-exact gate (oracle + e2e) and `mypy --strict` are the dominant cross-checks; everything else is unit-covered.

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 10s (quick) / full suite green before verify
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending

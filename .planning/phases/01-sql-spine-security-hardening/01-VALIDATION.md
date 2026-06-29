---
phase: 01
slug: sql-spine-security-hardening
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-06-27
---

# Phase 01 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.
> Derived from `01-RESEARCH.md` → "Validation Architecture". Task IDs are assigned at planning time;
> the requirement-level map below is the contract each plan's tasks must satisfy.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 8.4.2 (+ pytest-cov, pytest-html); `filterwarnings=["error", ...]`, `--strict-markers`, `--strict-config` |
| **Config file** | `pyproject.toml [tool.pytest.ini_options]`; type markers folder-derived in `tests/conftest.py` |
| **Quick run command** | `poetry run pytest tests/integration/storage -q` |
| **Full suite command** | `poetry run pytest tests` (the gate — avoid `make test` in this worktree; it exports `ITRADER_DISABLE_LOGS=true` and aborts on missing `.env`) |
| **Estimated runtime** | ~20–30 s (spine round-trip subset); full suite per v1.5 baseline |

---

## Sampling Rate

- **After every task commit:** Run `poetry run pytest tests/integration/storage -q` + `poetry run mypy itrader`
- **After every plan wave:** Run `poetry run pytest tests` (full suite, strict)
- **Before `/gsd:verify-work`:** Full suite green + oracle byte-exact + W1/W2 within v1.5 ±5% + FL-06 grep gates clean
- **Max feedback latency:** ~30 s (storage subset)

---

## Per-Requirement Verification Map

> Task IDs (`01-NN-NN`) are bound by the planner. Each requirement below MUST map to at least one
> `<automated>` verify in a plan task, or to a Wave 0 fixture/stub.

| Requirement | Behavior | Test Type | Automated Command | File Exists |
|-------------|----------|-----------|-------------------|-------------|
| SPINE-03 | UUIDv7 id round-trips value-equal on SQLite | unit/integration | `pytest tests/integration/storage/test_spine_roundtrip.py -k sqlite -x` | ❌ W0 |
| SPINE-03 | UUIDv7 + business-time round-trip value-equal on **Postgres** | integration | `pytest tests/integration/storage/test_spine_roundtrip.py -k postgres -x` | ❌ W0 (testcontainers) |
| SPINE-03 | business-time lossless + identical bytes across two runs (determinism) | unit | `pytest tests/integration/storage/test_spine_roundtrip.py -k determinism -x` | ❌ W0 |
| SPINE-01 | backend selected by `SqlSettings` alone (SQLite vs PG URL) | unit | `pytest tests/unit/storage/test_sql_settings.py -x` | ❌ W0 |
| SPINE-02 | single `SqlBackend` composed (never inherited) by storage concerns | unit | `pytest tests/unit/storage/test_sql_backend.py -x` | ❌ W0 |
| SEC-01 | no `user:pass@` in any source file | grep gate | `! grep -rIn 'user:pass@\|:1234@' itrader/` | ❌ W0 |
| SEC-01 | no f-string inside `text()` | grep gate | `! grep -rIn "text(f'" itrader/` (+ review `text(f"`) | ❌ W0 |
| SEC-01 | reworked `SqlHandler` reads/writes single `prices` table parameterized | unit | `pytest tests/unit/price_handler/test_sql_handler.py -x` | ❌ W0 |
| MIG-01 | results/research DB has no `alembic_version` table; live chain applies | integration | `pytest tests/integration/storage/test_migrations.py -x` | ❌ W0 |
| GATE-02 | new spine code `mypy --strict` clean | static | `poetry run mypy itrader` | ✅ (gate exists) |
| GATE-02 | full suite green under `filterwarnings=["error"]` | suite | `poetry run pytest tests` | ✅ |
| GATE-01 | oracle byte-exact 134 / `46189.87730727451` | integration | `poetry run pytest tests/integration/test_backtest_oracle.py -x` | ✅ (oracle exists) |
| GATE-01 | no W1/W2 regression vs 15.7 s / 152.8 MB | perf | same-machine A/B benchmark | ✅ (v1.5 harness) |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/integration/storage/conftest.py` — session-scoped `pg_engine` testcontainers `PostgresContainer` fixture + Docker-absent skip/xfail (D-11)
- [ ] `tests/integration/storage/test_spine_roundtrip.py` — SPINE-03 (UUIDv7 + business-time; SQLite + PG; determinism bytes)
- [ ] `tests/unit/storage/test_sql_settings.py` — SPINE-01 driver/URL selection
- [ ] `tests/unit/storage/test_sql_backend.py` — SPINE-02 composition (no god base)
- [ ] `tests/unit/price_handler/test_sql_handler.py` — SEC-01 reworked handler behavior
- [ ] `tests/integration/storage/test_migrations.py` — MIG-01 (`create_all()` vs Alembic; no `alembic_version` on results DB)
- [ ] Framework install: `poetry add --group dev alembic@^1.18.5 "testcontainers[postgresql]@^4.14.2"`
- [ ] FL-06 grep gates wired as a pytest test or Makefile check

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| W1/W2 perf no-regression | GATE-01 | Thermally sensitive; needs same-machine A/B on a cool box (see v1.5 perf-gate note) | Run the v1.5 benchmark harness before/after on the same machine; attribute via CPU-share, not frozen-baseline compare |
| Postgres round-trip when Docker absent | SPINE-03 | testcontainers needs a Docker daemon | If Docker unavailable, the PG test skips/xfails (D-11); run on a Docker host to exercise the PG arm |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 30s (storage subset)
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending

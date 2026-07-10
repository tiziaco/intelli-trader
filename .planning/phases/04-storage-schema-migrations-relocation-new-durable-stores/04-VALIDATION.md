---
phase: 4
slug: storage-schema-migrations-relocation-new-durable-stores
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-07-09
---

# Phase 4 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.
> Derived from `04-RESEARCH.md` § Validation Architecture. The Per-Task Verification
> Map is populated after PLAN.md files exist (via `/gsd-validate-phase` or the executor).

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 8.4.2 (`filterwarnings=["error"]`, `--strict-markers`, `--strict-config`) |
| **Config file** | `pyproject.toml` `[tool.pytest.ini_options]` |
| **Quick run command** | `poetry run pytest tests/integration/storage tests/integration/test_okx_inertness.py -q` |
| **Full suite command** | `make test` |
| **Estimated runtime** | quick ~10–30s · full suite ~1–2 min |

> **Gotcha (from memory):** `make test` exports `ITRADER_DISABLE_LOGS=true` and aborts on a
> missing `.env` inside worktrees. In the main checkout `make test` is the gate; in a worktree
> use `poetry run pytest tests` and re-run `make test` from main.

---

## Sampling Rate

- **After every task commit:** Run the quick command (storage + inertness).
- **After every plan wave:** Run `make test` (full suite).
- **Oracle gate (per-PLAN):** `poetry run pytest tests/integration/test_backtest_oracle.py` must
  stay byte-exact (`46189.87730727451`) — any store/migration change that moves it is a defect.
- **Before `/gsd-verify-work`:** Full suite must be green.
- **Max feedback latency:** ~30 seconds (quick command).

---

## Observable Properties (from RESEARCH.md § Validation Architecture)

The Nyquist sampling edges each phase requirement's tests MUST observe:

| Requirement | Observable edge (what a test samples) | Test type |
|-------------|----------------------------------------|-----------|
| SQL-01 | `migrations/` exists at project root; `itrader/storage/migrations/` gone; `alembic.ini script_location = migrations`; `env.py` still imports `build_*_table` + `NAMING_CONVENTION` from `itrader.storage`; migrations absent from built wheel | integration |
| SQL-02 | `alembic upgrade head` succeeds on a clean DB; `alembic heads` == exactly 1 (`strategy_registry`); `create_all`-vs-Alembic DDL parity holds for the full chain | integration |
| STORE-01 | `SystemStore` namespaced `(key, value_json, updated_at)` upsert → get round-trips; upsert overwrites same key | unit (SQLite `SqlEngine`) |
| STORE-02 | `VenueStore` per-venue config + `enabled` round-trips; `list_enabled` returns only enabled; write-time secret-key denylist raises `ValidationError` (D-05) | unit (SQLite `SqlEngine`) |
| STORE-03 | `StrategyRegistryStore` registry + normalized `strategy_subscriptions` child table round-trip; rehydrate JOINs both; `list_active` filter (D-04) | unit (SQLite `SqlEngine`) |
| STORE-04 | Restart survival: write → **dispose engine** → re-open over the **same file-backed** SQLite DB → read back identical state (not `:memory:`) | unit |
| STORE-05 | Backtest path untouched: oracle byte-exact + `test_okx_inertness.py` green (extended register-vs-build assertion for relocated migrations + 3 new registrars) | integration |

---

## Per-Task Verification Map

*Populated after PLAN.md files exist. Run `/gsd-validate-phase 4` post-planning to fill.*

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| _pending planning_ | — | — | — | — | — | — | — | — | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] Existing infrastructure covers all phase requirements — `tests/integration/storage/test_migrations.py`,
      `tests/integration/test_okx_inertness.py`, and `tests/integration/test_backtest_oracle.py` already exist;
      this phase **extends** them rather than installing a framework. New store unit tests follow the
      `HaltRecordStore` SQLite-`SqlEngine` fixture pattern.

*No framework install needed — pytest is present and configured.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| "migrations out of the shipped wheel" (observed, not just configured) | SQL-01 | Requires a real `poetry build` + wheel inspection | `poetry build`; unzip `dist/*.whl`; assert no `migrations/` entry (optional automated gate — see RESEARCH open question 1) |

*All other phase behaviors have automated verification.*

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 30s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending

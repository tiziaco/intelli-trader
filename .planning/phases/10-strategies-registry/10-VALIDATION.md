---
phase: 10
slug: strategies-registry
# status lifecycle: draft (seeded by plan-phase) → validated (set by validate-phase §6)
# audit-milestone §5.5 distinguishes NOT-VALIDATED (draft) from PARTIAL (validated + nyquist_compliant: false) (#2117)
status: validated
nyquist_compliant: true
wave_0_complete: true
created: 2026-07-17
validated: 2026-07-17
---

# Phase 10 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.
> Seeded by `/gsd-plan-phase` from `10-RESEARCH.md` § Validation Architecture.
> The **Per-Task Verification Map** is seeded at requirement granularity; task IDs are
> bound once plans exist (`/gsd-validate-phase` fills them).

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest ^8.4.2 (+ pytest-cov ^7.1.0) |
| **Config file** | `pyproject.toml::[tool.pytest.ini_options]` (`testpaths=["tests"]`, `filterwarnings=["error"]`, `--strict-markers`, `--strict-config`) |
| **Quick run command** | `poetry run pytest tests/unit/strategy tests/unit/storage tests/unit/core -x -q` |
| **Full suite command** | `poetry run pytest tests -q` |
| **Estimated runtime** | ~8 seconds (unit); full suite ~60s |

**Marker axis:** TYPE (`unit`/`integration`/`e2e`) auto-applied by `tests/conftest.py` from folder
location; PURPOSE (`smoke`/`live`) hand-applied.

**Known gotchas (project memory — do not re-discover):**
- `make test` exports `ITRADER_DISABLE_LOGS=true`, which fails `caplog` warn-assertion tests. Use
  `poetry run pytest` as the gate, not `make test`.
- `make test` aborts in git worktrees on a missing `.env` — run `poetry run pytest tests` there.
- Do **not** add `__init__.py` to `tests/unit/<x>` dirs — an empty `__init__.py` in both
  `tests/unit/<x>` and `tests/integration/<x>` creates two top-level `<x>` packages and breaks
  full-suite collection (isolated runs still pass, which hides it).

---

## Sampling Rate

- **After every task commit:** `poetry run pytest tests/unit/strategy tests/unit/storage tests/unit/core -x -q`
- **After every plan wave:** `poetry run pytest tests/unit tests/integration -q`
- **Per plan touching `calculate_signals` (D-07):** `poetry run pytest tests/integration/test_backtest_oracle.py -x` — **MANDATORY per-plan gate** (the CONTEXT pins this; it is the one shared-hot-path edit)
- **Per plan touching `core/` or the catalog seam:** `poetry run pytest tests/integration/test_okx_inertness.py -x` — **MANDATORY**
- **Before `/gsd-verify-work`:** full suite green
- **Max feedback latency:** ~8 seconds (unit quick run)

---

## Per-Task Verification Map

> Seeded at **requirement** granularity from RESEARCH § Validation Architecture. Task IDs bind at
> `/gsd-validate-phase`. `File Exists` ❌ W0 = the plan's Wave 0 must create it.

| Requirement | Behavior | Test Type | Automated Command | File Exists | Status |
|---|---|---|---|---|---|
| STRAT-01 | `list_active × catalog × codec` → registered instances at construction (D-01) | unit | `poetry run pytest tests/unit/strategy/test_rehydrate.py -x` | ❌ W0 | ✅ green |
| STRAT-01 | Full restart lifecycle: seed rows → build → rehydrate → same instance resumes | integration | `poetry run pytest tests/integration/test_strategy_registry_restart.py -x` | ❌ W0 | ✅ green |
| STRAT-01 | D-21 empty registry → boots, zero strategies, no error | unit | `poetry run pytest tests/unit/strategy/test_rehydrate.py -k empty -x` | ❌ W0 | ✅ green |
| STRAT-01 | D-19 quarantine: unknown `strategy_type` → skip + CRITICAL via `alert_sink`, healthy siblings load, **row NOT mutated** | unit | `poetry run pytest tests/unit/strategy/test_rehydrate.py -k quarantine -x` | ❌ W0 | ✅ green |
| STRAT-01 | D-19 infrastructure: catalog not injected → **fail loud** | unit | `poetry run pytest tests/unit/strategy/test_rehydrate.py -k no_catalog -x` | ❌ W0 | ✅ green |
| STRAT-01 | D-06 schema: `strategy_portfolio_subscriptions` CRUD + FK delete order | unit | `poetry run pytest tests/unit/storage/test_strategy_registry_store.py -x` | ✅ extend | ✅ green |
| STRAT-01 | Migration up/down against head `system_stats` (**not** `strategy_registry` — CONTEXT is stale) | integration | `poetry run pytest tests/integration/storage/test_migrations.py -x` | ✅ extend | ✅ green |
| STRAT-01 | D-03 codec round-trip: **all 6** policies incl. `PercentFromDecision` + `trail_type` enum-in-union | unit | `poetry run pytest tests/unit/core/test_policy_codec.py -x` | ❌ W0 | ✅ green |
| STRAT-01 | D-03 money boundary: Decimals round-trip **as strings**; no float ever appears | unit | `poetry run pytest tests/unit/core/test_policy_codec.py -k decimal -x` | ❌ W0 | ✅ green |
| STRAT-01 | D-04 round-trip loss-free per shipped strategy (`cls(**decode(encode(s))) == s` on declared surface) | unit | `poetry run pytest tests/unit/strategy/test_config_roundtrip.py -x` | ❌ W0 | ✅ green |
| STRAT-02 | Each verb (`add`/`remove`/`enable`/`disable`/`subscribe_portfolio`/`unsubscribe_portfolio`) applies **and persists** (D-09) | unit | `poetry run pytest tests/unit/strategy/test_strategy_command_verbs.py -x` | ❌ W0 | ✅ green |
| STRAT-02 | D-02 duplicate-name loud reject | unit | `poetry run pytest tests/unit/strategy/test_strategy_command_verbs.py -k duplicate -x` | ❌ W0 | ✅ green |
| STRAT-02 | D-10 unknown `strategy_type` loud reject | unit | `poetry run pytest tests/unit/strategy/test_strategy_command_verbs.py -k unknown_type -x` | ❌ W0 | ✅ green |
| STRAT-02 | D-07 `disable` → no new entries, indicators stay **WARM**, `enable` trades next bar with no re-warm | unit | `poetry run pytest tests/unit/strategy/test_is_active_gate.py -x` | ❌ W0 | ✅ green |
| STRAT-02 | D-09 `add_ticker`/`remove_ticker` now **also persist `config_json`** | unit | `poetry run pytest tests/unit/strategy/test_strategy_command_verbs.py -k ticker -x` | ❌ W0 | ✅ green |
| STRAT-02 | D-10 `add` on a COLD symbol → dark → `BarsLoaded` → ready → trades | integration | `poetry run pytest tests/integration/test_strategy_add_warmup.py -x` | ❌ W0 | ✅ green |
| STRAT-02 | D-11 `remove` force-flats before dropping; sub rows deleted | integration | `poetry run pytest tests/integration/test_strategy_remove_flat.py -x` | ❌ W0 | ✅ green |
| STRAT-03 | D-13 ordering: bad config → **live untouched** (not torn); persist-fail → reject | unit | `poetry run pytest tests/unit/strategy/test_reconfigure_atomic.py -x` | ❌ W0 | ✅ green |
| STRAT-03 | D-12 reconfigure KEEPS open positions | integration | `poetry run pytest tests/integration/test_reconfigure_positions.py -x` | ❌ W0 | ✅ green |
| STRAT-03 | D-14 window grew → dark+re-warm; shrank/unchanged → stays warm | unit | `poetry run pytest tests/unit/strategy/test_reconfigure_atomic.py -k warm -x` | ❌ W0 | ✅ green |
| STRAT-03 | D-15 allowlist: `strategy_type` immutable; `tickers` via verbs only; finer-than-base **rejected** | unit | `poetry run pytest tests/unit/strategy/test_reconfigure_allowlist.py -x` | ❌ W0 | ✅ green |
| STRAT-03 | **F-1 (CONFIRMED REAL)**: coarser-timeframe reconfigure actually warms — or is loud-rejected | unit | `poetry run pytest tests/unit/strategy/test_reconfigure_allowlist.py -k timeframe -x` | ❌ W0 | ✅ green |
| STRAT-03 | P-4: partial reconfigure merges; persisted `config_json` = post-merge FULL set | unit | `poetry run pytest tests/unit/strategy/test_reconfigure_atomic.py -k merge -x` | ❌ W0 | ✅ green |
| STRAT-03 | D-17 pair reconfigure refused (loud, documented no-op) | unit | `poetry run pytest tests/unit/strategy/test_pair_dispatch.py -k reconfigure -x` | ✅ extend | ✅ green |
| D-22 | External path: `add_event(StrategyCommandEvent.add(...))` → full lifecycle → **restart** → resumes | integration | `poetry run pytest tests/integration/test_strategy_external_add_lifecycle.py -x` | ❌ W0 | ✅ green |
| **GATE** | Backtest oracle byte-exact `134 / 46189.87730727451` | integration | `poetry run pytest tests/integration/test_backtest_oracle.py -x` | ✅ | ✅ green |
| **GATE** | Import inertness (codec in `core/` + catalog seam stay SQL/ccxt-free; store import lazy) | integration | `poetry run pytest tests/integration/test_okx_inertness.py -x` | ✅ | ✅ green |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [x] `tests/unit/core/test_policy_codec.py` — STRAT-01 (D-03 codec, all 6 policies, money boundary)
- [x] `tests/unit/strategy/test_rehydrate.py` — STRAT-01 (D-01/D-19/D-21)
- [x] `tests/unit/strategy/test_config_roundtrip.py` — STRAT-01 (D-04 round-trip per shipped strategy)
- [x] `tests/unit/strategy/test_strategy_command_verbs.py` — STRAT-02 (D-09/D-02/D-10)
- [x] `tests/unit/strategy/test_is_active_gate.py` — STRAT-02 (D-07)
- [x] `tests/unit/strategy/test_reconfigure_atomic.py` — STRAT-03 (D-13/D-14/P-4)
- [x] `tests/unit/strategy/test_reconfigure_allowlist.py` — STRAT-03 (D-15, F-1)
- [x] `tests/integration/test_strategy_registry_restart.py` — STRAT-01
- [x] `tests/integration/test_strategy_add_warmup.py` — STRAT-02 (D-10)
- [x] `tests/integration/test_strategy_remove_flat.py` — STRAT-02 (D-11)
- [x] `tests/integration/test_reconfigure_positions.py` — STRAT-03 (D-12)
- [x] `tests/integration/test_strategy_external_add_lifecycle.py` — D-22 (the FastAPI stand-in)
- [x] Shared fixture: a **test strategy catalog** + a seeded `strategy_registry` fixture. Place in
      `tests/support/` (matches the `tests/support/replay_harness.py` precedent) — **not** a
      `conftest.py` in a package-less unit dir.
- Framework install: **none needed** — pytest is present.

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| A1: `strategy_registry` / `strategy_subscriptions` tables are empty in the deployed DB before D-06's drop | STRAT-01 | A DB-state claim, unverifiable from source. The store has no production writer (constructed only in tests), so confidence is high — but a drop is destructive if wrong. | Run `SELECT count(*) FROM strategy_registry;` and `SELECT count(*) FROM strategy_subscriptions;` against any deployed DB before applying the migration. The plan should gate the drop on this, or write the migration non-destructively on non-empty. |

> **A1 status — PENDING (pre-deploy step, NOT a merge blocker).** No automated run in this repo
> can inspect a deployed DB's row counts. Plan 02's migration guard makes a wrong assumption fail
> loud rather than destroy data, so this is a checklist item for the deploy operator, not a gate on
> merging the phase. It stays PENDING by design.

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references
- [x] No watch-mode flags
- [x] Feedback latency < 10s
- [x] `nyquist_compliant: true` set in frontmatter

**Measured gate results (10-09 sweep, 2026-07-17):**

- Full suite `poetry run pytest tests -q`: **2530 passed, 6 skipped, 0 warnings** (the 6 skips are
  OKX-credential-gated e2e/live tests — no credentials in CI).
- Oracle `test_backtest_oracle.py`: **green, byte-exact 134 / 46189.87730727451** (P10 is
  live-only / backtest-dark).
- Inertness `test_okx_inertness.py`: **green** (codec in `core/` + catalog seam stay SQL/ccxt-free;
  `strategy_registry_store` / `registry.rehydrate` / `policy_codec` imports stay LAZY inside the
  rehydrate gate — every remaining reference is a function-body import, none barrel-exported).
- `poetry run mypy itrader`: **clean (244 source files)**. `core/policy_codec.py` and
  `strategy_handler/registry/` are NOT under any `ignore_errors` override
  (`grep -c 'policy_codec\|strategy_handler.registry' pyproject.toml` == 0).
- Dead-import sweep on the `live_trading_system.py` mypy-blindspot: **clean** — every P10-introduced
  name (`_quarantined_strategies`, the `strategy_catalog` param, and the 3 lazy imports) is consumed.

**Approval:** validated — all automated gates green; A1 remains a pre-deploy manual step.

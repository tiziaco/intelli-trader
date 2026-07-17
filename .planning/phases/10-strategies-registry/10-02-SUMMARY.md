---
phase: 10-strategies-registry
plan: 02
subsystem: storage
tags: [schema, migration, strategy-registry, d-06, d-18, d-02]
requires:
  - "itrader/storage/strategy_registry_store.py (P4 store)"
  - "migrations/versions/system_stats.py (chain head)"
provides:
  - "strategy_registry.strategy_type column"
  - "strategy_portfolio_subscriptions table + CRUD"
  - "p10_strategy_portfolio_subs migration (new single head)"
affects:
  - "tests/integration/test_okx_inertness.py (registrar table-set assertion)"
  - "tests/integration/storage/test_migrations.py (chain head + _NEW_TABLES)"
tech-stack:
  added: []
  patterns:
    - "registrar-as-single-source-of-truth (build_* feeds create_all + Alembic target_metadata)"
    - "loud-rejection-over-silent-destruction applied to a destructive schema op (A1 guard)"
    - "batch_alter_table for SQLite-portable column ALTERs"
key-files:
  created:
    - migrations/versions/p10_strategy_portfolio_subs.py
  modified:
    - itrader/storage/strategy_registry_store.py
    - tests/unit/storage/test_strategy_registry_store.py
    - tests/integration/storage/test_migrations.py
    - tests/integration/test_okx_inertness.py
decisions:
  - "portfolio_id is String, not Uuid — Strategy.subscribed_portfolios is typed list[PortfolioId | int], so a Uuid column would reject the legal int arm"
  - "strategy_type ADD COLUMN carries a transient server_default='UNKNOWN' — the A1 guard counts the CHILD table and does not prove strategy_registry is empty; backfilled rows quarantine loudly at rehydrate (D-19)"
metrics:
  duration: ~25m
  tasks: 2
  files: 5
  completed: 2026-07-17
status: complete
---

# Phase 10 Plan 02: D-06 Data Model Summary

Reshaped `strategy_registry` to the D-06 instance model — `strategy_type` column, a
`strategy_portfolio_subscriptions` fan-out child replacing the misdirected P4
`strategy_subscriptions` table — in both the registrar and a replay-safe Alembic migration
that refuses to destroy operator data.

## What Was Built

**Task 1 — registrar + store CRUD** (`itrader/storage/strategy_registry_store.py`)

- `strategy_registry` gained a non-null `strategy_type` (the catalog key rehydrate resolves,
  D-01). `strategy_name` remains the sole PK (D-02); `enabled` remains its own column (D-06).
- New `strategy_portfolio_subscriptions` table: composite PK
  `(strategy_name FK → strategy_registry.strategy_name, portfolio_id)`.
- The P4 `strategy_subscriptions` (venue, symbol, timeframe) table is gone from the registrar.
- API changes:
  - `upsert(strategy_name, strategy_type, config, enabled, at)` — new `strategy_type` param,
    written in both the UPDATE and INSERT arms; update-never-delete preserved (CR-01 FK).
  - Removed `set_subscriptions` / `strategies_subscribed_to`.
  - Added `set_portfolio_subscriptions` (DELETE-then-INSERT replace in one transaction,
    bumps parent `updated_at`), `add_portfolio_subscription` (idempotent probe-then-insert),
    `remove_portfolio_subscription` (no-op when absent), `portfolio_subscriptions` (id-ASC).
  - `get` / `list_active` / `read_all` carry `strategy_type`; `list_active` is now
    `strategy_name`-ASC ordered; `read_all` returns `portfolio_ids: list[str]`.
  - `delete` retargets the child DELETE, keeping children-before-parent order (P-6).

**Task 2 — migration** (`migrations/versions/p10_strategy_portfolio_subs.py`)

- `down_revision = "system_stats"` — the **measured** chain head. `10-CONTEXT.md` claimed the
  chain ended at `strategy_registry`; that was stale by two revisions (`module_config`,
  `system_stats`). Verified by reading every `down_revision` in `migrations/versions/`.
- `upgrade()`: A1 guard → add `strategy_type` → create the portfolio child → drop the P4 table.
- `downgrade()`: true inverse — restores `strategy_subscriptions` with its original
  composite-PK shape, drops the portfolio child, drops `strategy_type`.
- New single head: `p10_strategy_portfolio_subs` (`alembic heads` confirms one head).

## The A1 Guard (T-10-08)

`upgrade()` executes a parameter-free `SELECT count(*) FROM strategy_subscriptions` **before
any destructive op** and raises `RuntimeError` naming the table, the row count, and the
required manual step when non-zero. RESEARCH A1's "the tables are empty in every deployed DB"
is a DB-state claim that could not be verified from source; a wrong drop is unrecoverable, so
the migration counts first and refuses loudly rather than destroying data on an assumption.
Two tests pin both halves: the raise happens, and the table plus its row survive.

## Key Decisions

**`portfolio_id` is `String`, not `Uuid`.** The plan said "use String, but confirm against the
portfolio store's column type and match it." Those two instructions conflict: the portfolio
store keys on `Uuid(as_uuid=True)`. `String` is correct — `Strategy.subscribed_portfolios` is
typed `list[PortfolioId | int]` (`base.py:194`; the comment there confirms "both shapes are
legal") and `to_dict` already serializes via `str(pid)`. A `Uuid` column would reject the legal
`int` arm. The portfolio-owned tables differ because their key is strictly a `PortfolioId`.
Pinned by an assertion in `test_build_strategy_registry_tables_shape`.

**`strategy_type` ADD COLUMN needs a transient `server_default`.** The plan's rationale said
"the guard above proves there are none" — that is not accurate: the A1 guard counts
`strategy_subscriptions` (the child), which says nothing about `strategy_registry` (the
parent). A deployed DB may hold registry rows, so the non-null add uses
`server_default="UNKNOWN"`, then drops the default via `batch_alter_table` so the column
matches the registrar (which declares no default). Backfilled `UNKNOWN` rows quarantine
loudly at rehydrate (D-19) rather than silently mis-instantiating. The two-step is therefore
load-bearing, not just dialect defensiveness.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] `test_okx_inertness.py` asserted the old registrar table set**

- **Found during:** Task 1
- **Issue:** The plan's `read_first` grep targeted `set_subscriptions` /
  `strategies_subscribed_to` call sites, which are test-only as predicted — but
  `tests/integration/test_okx_inertness.py:355,363` also asserts the registrar's returned
  table names (`{"strategy_registry", "strategy_subscriptions"}`). The plan did not list this
  file. Leaving it would have broken the phase's own inertness gate.
- **Fix:** Updated both assertions to `strategy_portfolio_subscriptions` with a D-06 comment.
- **Files modified:** `tests/integration/test_okx_inertness.py`
- **Commit:** 4e9a33f4

**2. [Rule 3 - Blocking] Orphaned `Subscription` type alias**

- **Found during:** Task 1
- **Issue:** The module-level `Subscription = tuple[str, str, str]` alias described the dropped
  table's row shape and had no remaining referent.
- **Fix:** Removed. Verified no importers across `itrader` and `tests`.
- **Commit:** 4e9a33f4

### Transient red state between task commits

Commit 4e9a33f4 (Task 1) left `test_create_all_vs_migration_parity` failing by construction:
the registrar declared the D-06 schema while the migration did not yet exist. This is inherent
to the plan's task split (the plan itself notes the change must land in both, and the parity
test exists precisely to catch a one-sided landing). Task 2's commit 730cf899 restored green;
the full suite passes at HEAD. Noted so a future bisect through 4e9a33f4 is not mistaken for a
real regression.

### Test-count note

The plan specified 9 store behaviors and 6 migration behaviors; 17 store tests and 6 new
migration tests were written. The extra store tests cover the empty-set clear, per-strategy
scoping, `updated_at` bump, and `get`-on-missing — cheap edge coverage on the same surface.
The A1 guard got two tests (the refusal itself, and the row count appearing in the message).

## Verification

| Gate | Result |
|------|--------|
| `pytest tests/unit/storage/test_strategy_registry_store.py -x -q` | 17 passed |
| `pytest tests/integration/storage/test_migrations.py -x -q` | 13 passed |
| `alembic heads` | `p10_strategy_portfolio_subs (head)` — exactly one |
| `pytest tests/unit tests/integration -q` | **2247 passed, 2 skipped, 0 failed** |
| `mypy` (strict, whole package) | Success — no issues in 239 source files |
| Backtest oracle (`134 / 46189.87730727451`) | green (ran within the integration suite) |
| `test_okx_inertness.py` | green (store import stays lazy) |

Task 1 acceptance greps all pass: `strategy_subscriptions` occurrences (2) are all inside
`strategy_portfolio_subscriptions` (23); `strategy_type` ×14; old defs 0; new defs 4;
`order_by` 3; D-06 ×10; D-18 ×3; tabs 0; no stale `set_subscriptions` /
`strategies_subscribed_to` references anywhere.

Task 2 acceptance greps all pass: `down_revision` → `system_stats` ×1, → `strategy_registry`
×0; revision id ×1; count guard present; `drop_table("strategy_subscriptions")` ×1;
`op.create_table` ×2; tabs 0; D-06 ×6.

The two skips are pre-existing OKX-credential opt-ins, unrelated to this plan.

## Manual Verification Required

Before applying this migration to any **deployed** database, run:

```sql
SELECT count(*) FROM strategy_subscriptions;
SELECT count(*) FROM strategy_registry;
```

The A1 guard turns a non-empty `strategy_subscriptions` into a loud upgrade failure rather
than data loss, so this is a pre-flight convenience, not a safety net. A non-zero
`strategy_registry` count means existing rows will backfill `strategy_type='UNKNOWN'` and be
quarantined at rehydrate (D-19) until corrected.

## Known Stubs

None.

## Threat Flags

None. The plan's `<threat_model>` covers the introduced surface: T-10-07 (parameterized Core
throughout — no f-string SQL; the A1 guard's count is parameter-free and constant),
T-10-08 (the guard), T-10-09 (registrar/migration parity, pinned by
`test_p10_migrated_schema_matches_the_registrar` plus the whole-chain parity test),
T-10-10 (named FK + children-before-parent delete, pinned by two store tests).

## For the Next Plan

- `read_all()` returns `portfolio_ids: list[str]`; `list_active()` is `strategy_name`-ASC
  ordered and carries `strategy_type` — the rehydrate (D-01) read surface is ready.
- `add_portfolio_subscription` / `remove_portfolio_subscription` are the D-09
  subscribe/unsubscribe verb backing.
- `upsert` now requires `strategy_type` positionally after `strategy_name`.
- The store remains **unwired** — no production writer yet. `build_live_system` construction
  and rehydrate are downstream plans.

## Self-Check: PASSED

All 4 created/modified source files verified present on disk. All 4 commits verified in
`git log`: c4358e22, 4e9a33f4, 301932de, 730cf899.

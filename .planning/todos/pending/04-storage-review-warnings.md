---
status: open
created: "2026-07-10"
source: 04-REVIEW.md (phase-04 code-review gate, post-remediation deferral)
tags: [storage, sql, test-robustness, alembic-parity, fk-drift, datetime-guard, deferred, WR-01, WR-02, WR-03]
resolves_phase: ""
---

# Phase-04 storage review — deferred hardening warnings (WR-01 / WR-02 / WR-03)

**Origin:** The phase-04 code-review gate (`04-REVIEW.md`) surfaced one BLOCKER (CR-01) plus three
Warnings and two Info nits. CR-01, IN-01, IN-02 were fixed in-run (commits `53a90b07`, `6b623549`).
The three Warnings are hardening improvements with judgment calls (WR-01 in particular may surface
further latent schema drift once the parity test actually inspects FKs), so they were **owner-approved
to defer** rather than fold into the closing pass of a completed phase.

## Deferred items

- **WR-01 — migration↔registrar parity test compares only column-*name* sets.**
  `tests/integration/storage/test_migrations.py::test_create_all_vs_migration_parity` asserts equal
  table sets + per-table column-name sets, but does NOT compare FK definitions (incl. `ondelete`), PK
  composition, nullability, or indexes. This is exactly why CR-01's missing-`ondelete` FK slipped the
  "parity" gate green. **Fix:** also compare, per new table, `inspector.get_foreign_keys` (incl.
  `options.ondelete`), `inspector.get_pk_constraint`, and per-column `nullable`. **Watch:** turning this
  on may reveal additional pre-existing registrar↔migration drift — triage each before tightening.

- **WR-02 — cross-file Postgres cleanup depends on alphabetical test-collection order.**
  `tests/integration/storage/test_cached_sql_portfolio_storage.py`'s autouse
  `_drop_operational_portfolio_tables` fixture only works because that file sorts before
  `test_migrations.py`. Brittle to file renames / `pytest-randomly` / changed collection order.
  **Fix:** each Postgres-touching storage test self-cleans its own tables in teardown
  (the `downgrade base` pattern), or use a function-scoped drop-all-registered-tables fixture that
  does not depend on inter-file order.

- **WR-03 — durable stores bind caller `at` into `UtcIsoText` with no naive-datetime boundary guard.**
  `UtcIsoText.process_bind_param` hard-raises `ValueError` on a tz-naive datetime; the durable stores
  (halt/system/venue/strategy-registry) bind `at`/`created_at` directly, unlike `SqlOrderStorage`
  which guards with `_ensure_utc` (tagged WR-03 there). Robustness/consistency gap — the D-07 contract
  says callers pass tz-aware datetimes and every current test honors it, so this is not a proven live
  failure. **Fix:** apply the same `_ensure_utc`-style normalization at each durable-store boundary
  (consider centralizing in `UtcIsoText`), OR assert the tz-aware precondition with a typed domain
  error so a naive value fails as a clear precondition violation, not a raw codec `ValueError`.

## Suggested handling

A small follow-up: `/gsd-plan-phase 04 --gaps` (or `/gsd-code-review 04 --fix` scoped to these three),
or fold into the next storage-touching phase. Not oracle-relevant; live-only / test-robustness surface.

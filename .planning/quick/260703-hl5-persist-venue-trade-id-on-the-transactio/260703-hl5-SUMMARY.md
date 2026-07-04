---
phase: quick-260703-hl5
plan: 01
subsystem: portfolio-storage
tags: [CR-01, persistence, migration, live-recon]
requires:
  - "Transaction.venue_trade_id (uncommitted CR-01 field, transaction.py:47)"
  - "p05_venue_order_id migration (HEAD before this plan)"
provides:
  - "transactions.venue_trade_id nullable String column"
  - "hl5_transaction_venue_trade_id Alembic migration (chained off p05)"
  - "venue_trade_id threaded through both transaction mappers (write + read)"
affects:
  - "live recon/dedup idempotency-key survival across restart"
tech-stack:
  added: []
  patterns: ["nullable-column + batch_alter_table migration (mirrors p05)"]
key-files:
  created:
    - itrader/storage/migrations/versions/hl5_transaction_venue_trade_id.py
    - "tests/integration/storage/test_sql_portfolio_storage.py::test_transaction_venue_trade_id_round_trip"
  modified:
    - itrader/portfolio_handler/storage/models.py
    - itrader/portfolio_handler/storage/sql_storage.py
    - tests/integration/storage/test_sql_portfolio_storage.py
decisions:
  - "Plain nullable column only — no partial UNIQUE index (dialect-awkward across sqlite-batch + Postgres); mirrors p05 precedent, follow-up noted in migration docstring."
metrics:
  duration: ~2min
  completed: 2026-07-03
---

# Quick 260703-hl5: Persist venue_trade_id on the transactions table — Summary

Persisted the CR-01 venue idempotency key on the durable settlement record: added a
nullable `transactions.venue_trade_id` column via a chained Alembic migration, threaded
the field through both SQL transaction mappers, and proved write -> rehydrate survival
(non-None and None) with a Postgres round-trip test. The SQL layer no longer drops the
venue's own trade id (FIX ExecID / Nautilus TradeId) on rehydrate.

## What Was Built

- **Task 1 — schema + migration** (`a111075b`): added `Column("venue_trade_id", String, nullable=True)`
  to the `transactions` Table (4-space indent preserved) with a CR-01 decision comment; created
  `hl5_transaction_venue_trade_id.py` chained off `p05_venue_order_id`, adding/dropping the column
  via `batch_alter_table` (sqlite-compat). No partial UNIQUE index — documented follow-up.
- **Task 2 — mappers** (`c4ecd2b7`): `_transaction_to_row` now writes `transaction.venue_trade_id`;
  `_row_to_transaction` rehydrates `Transaction(venue_trade_id=row["venue_trade_id"])`. String-id
  plumbing only — no numeric/Decimal or fill_id/UUID handling touched.
- **Task 3 — round-trip test** (`b142cbc5`): `test_transaction_venue_trade_id_round_trip` proves a
  non-None `"OKX-EXEC-9001"` survives `add_transaction` -> `get_transaction_history` and the None
  default round-trips as None. No new pytest marker (folder-derived integration marker).

## Verification Results (actual)

- `poetry run pytest tests/integration/storage/test_sql_portfolio_storage.py -v` → **17 passed** in 2.57s.
  A live Postgres backend WAS available, so the round-trip tests actually RAN (did not skip) — the new
  `test_transaction_venue_trade_id_round_trip` passed against real Postgres.
- `poetry run pytest tests/integration/test_backtest_oracle.py -q` → **3 passed** — frozen SMA_MACD
  oracle stays byte-exact.
- `poetry run mypy itrader` → **Success: no issues found in 226 source files** (strict-clean).
- Task 1 automated import/chain check → `ok` (down_revision == p05_venue_order_id, column present).

## Deviations from Plan

None — plan executed exactly as written.

## Working-Tree Discipline

Executed on the MAIN working tree per instruction (depends on the uncommitted CR-01
`Transaction.venue_trade_id` field). Each commit staged ONLY its own files via explicit
`git add <path>` (verified with `git diff --cached --name-only` before every commit). The other
uncommitted changes (CR-01 dedup + WR-01/02/04 across okx.py, fill.py, portfolio_handler.py,
venue_reconciler.py, live_trading_system.py, 05-REVIEW.md, and test files) remain undisturbed.

## Commits

- `a111075b` feat(quick-260703-hl5): add nullable transactions.venue_trade_id column + migration
- `c4ecd2b7` feat(quick-260703-hl5): thread venue_trade_id through transaction mappers
- `b142cbc5` test(quick-260703-hl5): venue_trade_id persistence round-trip

## Self-Check: PASSED

- FOUND: itrader/storage/migrations/versions/hl5_transaction_venue_trade_id.py
- FOUND: commits a111075b, c4ecd2b7, b142cbc5
- Modified files present: models.py, sql_storage.py, test_sql_portfolio_storage.py

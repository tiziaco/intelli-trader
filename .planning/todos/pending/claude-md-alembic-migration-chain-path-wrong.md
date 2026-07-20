---
status: open
created: "2026-07-20"
source: quick task 260720-owe (WR-04 / Option B1) — planner correction, independently verified
tags: [docs, claude-md, alembic, storage, doc-rot, low-effort]
resolves_phase: ""
---

# CLAUDE.md points at the wrong path for the Alembic migration chain

**Severity:** documentation only — no code defect. But it actively misled a planning pass, so it is
worth correcting rather than leaving.

## The claim

`CLAUDE.md:114` (the v1.7 "Durable store" bullet) reads:

> **Durable store** — `storage/` is the shared SQL spine: `SqlBackend` (`backend.py`, …),
> `types.py`, `halt_record_store.py`, and **an Alembic migration chain under `storage/migrations/`**.

## The reality (verified 2026-07-20)

- `itrader/storage/migrations/` **does not exist**.
- The Alembic chain lives at the **repo root**: `migrations/` (`env.py`, `script.py.mako`,
  `versions/`), with `alembic.ini` at the root setting `script_location = migrations`.
- `migrations/versions/` currently holds 9 revisions, including
  `p10_strategy_portfolio_subs.py`, `strategy_registry.py`, `d10_halt_records.py`,
  `p05_venue_order_id.py`, `hl5_transaction_venue_trade_id.py`.
- Per `.planning/STATE.md:211`, the chain was **relocated to the repo root in Phase 04-01**. The
  CLAUDE.md bullet was simply never updated to follow it.

## Why it matters

This is not a cosmetic path typo. During quick task `260720-owe`, the stale bullet propagated into a
task brief as the stronger and wholly false claim *"there is NO Alembic chain in this repo"*, which
was then used as a reason to defer schema work (the "B2" item). The deferral happened to be correct
on other grounds, but it was nearly recorded against a fabricated constraint. A wrong path in the
one file agents are told to treat as authoritative reliably becomes a wrong *premise* downstream.

## Fix

Update `CLAUDE.md:114` to say the Alembic chain lives at the repo root (`migrations/`, driven by
`alembic.ini`), not under `storage/`. While there, sanity-check the rest of that v1.7 bullet against
the tree — `backend.py`, `types.py`, and `halt_record_store.py` were all confirmed present under
`itrader/storage/`, so only the migrations clause is wrong.

Optionally cross-check the neighbouring platform-requirements note that still describes
`PostgreSQLOrderStorage` as a `NotImplementedError` placeholder in
`itrader/order_handler/storage/postgresql_storage.py` — CLAUDE.md's own Architecture section states
that file was **removed** (D-05/D-06), so the two sections contradict each other. Same class of rot,
same file, worth one pass.

## Suggested handling

`/gsd-quick` one-liner, or fold into the next `/gsd-docs-update` run.

---
status: open
created: "2026-07-20"
source: quick task 260720-owe (WR-04 / Option B1), deferred "B2" half
tags: [storage, sql, schema, alembic, strategy-registry, portfolio-id, consistency, deferred, WR-04]
resolves_phase: ""
---

# B2 — align `strategy_portfolio_subscriptions.portfolio_id` to a `Uuid` column

**Origin:** Quick task `260720-owe` closed WR-04 by removing the vestigial `int` arm from
`Strategy.subscribed_portfolios` (`list[PortfolioId | int]` → `list[PortfolioId]`). That task was
scoped deliberately to **B1 only** — the type narrowing and the dead comments. This file records the
**B2** half that was consciously left alone.

## What B2 is

`migrations/versions/p10_strategy_portfolio_subs.py` declares
`strategy_portfolio_subscriptions.portfolio_id` as `String`, not `Uuid`. The portfolio-owned tables
elsewhere in the schema use `Uuid`. B2 would align them.

## Why it was deferred (and why the original rationale was partly wrong)

The deferral is **correct**, but it was originally recorded against a **false premise** worth
correcting here so nobody re-derives it:

- ❌ *Claimed:* "there is no Alembic chain in this repo, so there is no migration mechanism."
- ✅ *Actual:* the chain **exists** — it was relocated to the **repo root** (`migrations/`, with
  `alembic.ini` setting `script_location = migrations`) during Phase 04-01. It is `itrader/storage/migrations/`
  that does not exist. See the companion todo `claude-md-alembic-migration-chain-path-wrong.md`.

So a migration mechanism **is** available. The surviving reasons to defer are:

1. **Zero correctness benefit.** With the `int` arm gone, `portfolio_id` is always a UUIDv7-backed
   `PortfolioId`. `String` still round-trips it losslessly: `base.py` serializes via `str(pid)`
   (`to_dict` / snapshot paths) and `registry/rehydrate.py::_resolve_portfolio_id` parses it back
   with `PortfolioId(uuid.UUID(raw))`, raising `StrategyConfigError` on anything malformed. The
   column type is a **consistency** improvement, not a defect fix.
2. **It needs a schema decision, not just a migration.** Changing the column type touches the
   registrar/`create_all` path, the migration↔registrar parity test, and the serialization seam on
   both sides. Whether the codebase wants `Uuid` columns uniformly (and what that implies for the
   SQLite results store vs Postgres) is a design call, not a mechanical edit.

## What "done" looks like

- Decide the project-wide policy: are portfolio-id columns `Uuid` everywhere, or is `String` +
  parse-on-read the accepted seam?
- If `Uuid`: add an Alembic revision under `migrations/versions/`, update the registrar so
  `create_all` and the migration chain stay in parity (see `04-storage-review-warnings.md` WR-01 —
  the parity test currently compares column *names* only and would not catch a type divergence), and
  drop the now-unnecessary `str(pid)` / parse hop if it becomes dead.
- If `String` stays: no code change — the justifying comments were already rewritten onto the
  surviving serialization rationale by `260720-owe` (task `owe-03`), so nothing is stale.

## Suggested handling

Fold into the next storage/schema-touching phase, alongside the WR-01 parity-test tightening from
`04-storage-review-warnings.md` — those two want to land together, since a type change is exactly
what the current name-only parity gate would wave through.

Not oracle-relevant. Live/persistence surface only.

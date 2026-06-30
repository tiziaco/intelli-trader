# Phase 2: Results Store (#1) - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-06-29
**Phase:** 2-Results Store (#1)
**Areas discussed:** Persistence trigger / wiring, runs schema (Float columns), Artifact frame model, settings JSON contents, DB persistence model, Read API shape, save_run contract, Factory/selection, Dump-failure policy, Aggregate equity alignment, top_runs determinism, Missing-run reads

---

## Persistence trigger / wiring

| Option | Description | Selected |
|--------|-------------|----------|
| Composition root / caller | persist_run() helper called by the caller after run() | |
| Engine run(persist=...) opt-in | Engine owns the post-loop dump via an opt-in flag | ✓ |

**User's choice:** Engine-owned opt-in. Then refined: store injected at composition + `run(persist: bool)` toggle (see Factory/selection area — supersedes per-call store).
**Notes:** Followed by sub-decisions — injection (initially "run(persist_store=...) per call", later re-locked to composition-injected + boolean) and run grain.

### Run grain (sub-question)
**User's choice:** One `runs` row per `run()` call (the compounded result), BUT also capture per-portfolio metrics + an aggregate. User: "if i run a simulation with 2 strategy the goal is to see how they compound together, but at the same time i'd like to see how they perform singularly." → resolved as `runs` (aggregate) + `run_portfolios` child table.

### Per-portfolio breakdown storage (sub-question)
| Option | Description | Selected |
|--------|-------------|----------|
| run_portfolios child table | Per-strategy metrics in real indexed columns, individually rankable | ✓ |
| per_portfolio JSON in runs row | Breakdown as a JSON blob, not SQL-queryable per strategy | |

**User's choice:** run_portfolios child table.

---

## runs schema — Float columns

| Option | Description | Selected |
|--------|-------------|----------|
| Store all, rank by all | Every metric as indexed Float column; compute total_return + calmar; widen MetricName | ✓ |
| Keep allow-list minimal (4) | Only the 4 already-declared rankable metrics | |

**User's choice:** Store all, rank by all.
**Notes:** Surfaced a real mismatch — ABC allow-list declared sharpe/total_return/max_drawdown/calmar, but engine computes sharpe/sortino/cagr/max_drawdown/profit_factor/win_rate. Reconciled by computing the two missing + widening the allow-list.

---

## Artifact frame model

### Row structure
| Option | Description | Selected |
|--------|-------------|----------|
| Typed row per frame | One row per (run_id, portfolio_id, artifact_type ∈ {equity_curve, trade_log}) | ✓ |
| Combined blob per portfolio | Both frames in one JSON object per portfolio | |

**User's choice:** Typed row per frame.

### Blob vs exploded tables (user-raised)
| Option | Description | Selected |
|--------|-------------|----------|
| Keep serialized blob | Locked RESULT-02 choice; metrics already queryable in runs/run_portfolios | ✓ |
| Exploded tables | run_trades + run_equity per-row tables (reverses RESULT-02) | |
| Hybrid: trades exploded, equity blob | Middle ground | |

**User's choice:** Keep serialized blob.
**Notes:** User asked the trade-offs of exploded tables; flagged it reverses an Owner Decision; cross-run analytics already covered by metric columns.

### Encoding
| Option | Description | Selected |
|--------|-------------|----------|
| gzip'd JSON (mtime=0) | to_json(orient='split') + gzip mtime=0; ~10× smaller, byte-deterministic | ✓ |
| Plain JSON text | Uncompressed, simplest, larger | |

**User's choice:** gzip'd JSON (mtime=0).
**Notes:** User asked for a reminder of frame contents + sizes before choosing.

---

## settings JSON contents

| Option | Description | Selected |
|--------|-------------|----------|
| Full config + per-strategy params | Full SystemConfig model_dump + strategy params | |
| Curated subset + per-strategy params | Curated essentials + strategy params | ✓ (refined) |

**User's choice:** Curated subset — but "the curated set should include all relevant information (e.g. type of order, fee model, other risk parameters)." Refined to an explicit curated envelope of all result-relevant fields (not bare minimum, not raw dump). Config inspection confirmed a raw dump would be noisy AND miss exchange/order config.
**Notes:** Confirmed the run-level (runs.settings) vs per-strategy (run_portfolios.params) split.

---

## DB persistence model

| Option | Description | Selected |
|--------|-------------|----------|
| On-disk file default | results.db accumulates across runs; create_all(checkfirst=True); :memory: for tests | ✓ |
| In-memory default | :memory:, ephemeral per process | |

**User's choice:** On-disk file default.
**Notes:** "Ephemeral" reinterpreted as no-Alembic / disposable schema, not in-memory.

---

## Read API shape

| Option | Description | Selected |
|--------|-------------|----------|
| Widen signature (explicit) | get_artifact(run_id, portfolio_id, artifact_type) -> one frame | |
| Return keyed collection | get_artifact(run_id) -> {(portfolio_id, artifact_type): df} | ✓ |

**User's choice:** Return keyed collection.

---

## save_run input contract

| Option | Description | Selected |
|--------|-------------|----------|
| Typed frozen value object | RunRecord + per_portfolio; atomic runs+run_portfolios write | ✓ |
| Raw dict | Untyped payload | |

**User's choice:** Yes, lock it (typed RunRecord, atomic write, separate widened save_artifact).
**Notes:** User asked "what's best here?" → recommended typed object + atomic write; confirmed.

---

## Factory / selection

| Option | Description | Selected |
|--------|-------------|----------|
| Direct construction | SqlResultsStore(backend) directly; ABC is the extension seam | ✓ |
| ResultsStoreFactory for symmetry | One-arm factory mirroring other storages | |

**User's choice:** Direct construction. User then proposed initializing the store at composition + `run(persist=True/False)` boolean — "would be cleaner no?" → re-locked the wiring: composition-injected store + boolean toggle (supersedes per-call store from the wiring area).

---

## Dump-failure policy

| Option | Description | Selected |
|--------|-------------|----------|
| Log-and-warn, don't abort | Persistence failure logged, run() returns | |
| Re-raise / fail-fast | Abort on persist failure | |
| Configurable | strict_persist flag; default log-and-warn | ✓ |

**User's choice:** "make it configurable" → `strict_persist` flag on the store/SqlSettings (composition-time), default log-and-warn.

---

## Aggregate equity alignment

| Option | Description | Selected |
|--------|-------------|----------|
| Outer-join + forward-fill | Union index, ffill, leading = starting cash; handles mixed timeframes | ✓ |
| Inner-join (intersection) | Only shared timestamps; loses resolution | |
| Assume identical grid | Strict, raise on mismatch | |

**User's choice:** Outer-join + forward-fill.
**Notes:** User asked "does it take into account that the time frame might be different?" — this was the deciding factor; only outer-join + ffill handles mixed-cadence portfolios. Aggregate-metric annualization basis flagged for plan time.

---

## top_runs determinism

| Option | Description | Selected |
|--------|-------------|----------|
| Per-metric direction + run_id tiebreak | Direction map + stable UUIDv7 tiebreak; columns indexed | ✓ |
| Single DESC + tiebreak | Always DESC (max_drawdown ranks backwards) | |

**User's choice:** Per-metric direction + run_id tiebreak.
**Notes:** User confirmed metric is caller-selectable (incl. final_equity) from the widened allow-list.

---

## Missing-run reads

| Option | Description | Selected |
|--------|-------------|----------|
| Return empty (total reads) | get_artifact -> {}; top_runs -> [] | |
| Raise on unknown run_id | get_artifact -> ResultsNotFound; top_runs empty-safe | ✓ |

**User's choice:** Raise on unknown run_id (ResultsNotFound); top_runs stays empty-safe.

---

## Claude's Discretion

- Exact `itrader/results/` package layout, ORM model definitions, field types, index shapes,
  curated-serializer implementation, `ResultsNotFound` placement.
- Strategy-param introspection seam (how to read class-attribute params for run_portfolios.params).
- `max_drawdown` sign convention verification; mixed-timeframe annualization basis (plan-time).
- Whether a 5th ABC method (`top_portfolios`) is added for per-strategy ranking.

## Deferred Ideas

- Exploded per-row frame tables (rejected for Phase 2; possible future analytical surface).
- Optuna sweep / sampler loop (v2 OPT-01 — substrate only this phase).
- Postgres / second results backend (not needed; ABC leaves the door open).
- `single-pass-portfolio-valuation.md` todo — reviewed, NOT folded (perf, orthogonal).

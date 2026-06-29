# Phase 2: Results Store (#1) - Context

**Gathered:** 2026-06-29
**Status:** Ready for planning

<domain>
## Phase Boundary

Land the **concrete `Sql`-backed results store** behind the Phase-1 `ResultsStore` ABC
(`itrader/results/base.py`). Every backtest/optimization `run()` can persist end-to-end onto a
SQLite database: a `runs` summary row (aggregate metrics as `Float` columns + a curated JSON
settings column, Optuna-FK-ready), per-strategy `run_portfolios` rows, and `run_artifacts` frame
blobs (equity-curve / trade-log as gzip'd JSON text — **no Parquet, no `pyarrow`**). Validated
oracle-dark by DB round-trip + byte-determinism tests on in-process SQLite, before any live path
depends on the spine.

**Requirements (from REQUIREMENTS.md):** RESULT-01, RESULT-02, RESULT-03, RESULT-04 (recurring
gates GATE-01 byte-exact oracle + no W1/W2 regression; GATE-02 `mypy --strict` + `filterwarnings`).

**In scope:** the concrete `SqlResultsStore` + ORM models under `itrader/results/`; the `runs` /
`run_portfolios` / `run_artifacts` schema (`create_all`, ephemeral); the `RunRecord`/`PortfolioRecord`
value objects; the curated settings serializer; the aggregate-equity-curve builder; gzip'd-JSON
artifact encode/decode; the engine `run(persist=...)` opt-in hook + composition-time store injection;
the widened `ResultsStore` ABC surface; DB round-trip / byte-determinism tests on in-process SQLite.

**Out of scope (other phases / locked OUT):** the three operational SQL backends (Phase 3 — OPS);
write-through / working-set cache / rehydration (Phase 4 — RETAIN); cache classification (Phase 5 —
CACHE); the Optuna sweep / sampler loop (v2 OUT — substrate only, schema stays FK-ready);
`pyarrow`/Parquet (locked OUT); exploded per-row frame tables (considered, rejected — see D-09);
operational money / `Numeric` typing (Phase 3 — results store is all-`Float`).

</domain>

<decisions>
## Implementation Decisions

### Persistence trigger & lifecycle (Area 1 + refined in Area 8)
- **D-01:** Persistence is triggered by the **engine**: `TradingSystem.run(persist: bool = False)`.
  `persist=True` performs a **post-loop batch dump**; `persist=False` (default) skips it entirely.
  The dump is off the hot path — the run loop touches no SQL (GATE-01 inertness is structural).
- **D-02:** The `ResultsStore` is **constructed directly** (`SqlResultsStore(backend)` — NO factory,
  see D-19) and **injected once at engine composition** (`SystemSpec` / `compose_engine` /
  `build_backtest_system`, default `None`), not passed per call. The store's identity lives with the
  engine so the future sweep loop composes once and calls `run(persist=True)` in a loop.
  *(This supersedes an earlier mid-discussion choice to pass the store instance per call — the
  composition-injected store + boolean toggle is cleaner and was explicitly re-locked.)*
- **D-03:** **Guard:** `run(persist=True)` with no store injected raises a clear configuration error.
- **D-04:** The **oracle / golden path composes store-free** (`results_store=None`, `persist` defaults
  `False`) → dump code never executes → byte-exact `134 / 46189.87730727451` preserved.

### Run grain & schema shape (Area 1)
- **D-05:** **One `runs` row per `run()` call** = the **aggregate** result (all portfolios compounded).
  Its `Float` metric columns are computed on a **combined equity curve** (see D-14).
- **D-06:** A **`run_portfolios` child table** (`run_id` FK, `portfolio_id`, `name`, the same `Float`
  metric columns, `params` JSON) holds **per-strategy** metrics so each strategy is individually
  queryable/rankable — the user's goal: see strategies *compounded* (runs) AND *singularly*
  (run_portfolios). Mirrors the existing per-portfolio metrics loop (`print_metrics_summary`).
- **D-07:** **`run_artifacts`** carries a **nullable `portfolio_id`** and a **typed-row-per-frame**
  layout: PK `(run_id, portfolio_id, artifact_type)` with `artifact_type ∈ {equity_curve, trade_log}`.

### Metric columns & ranking allow-list (Area 2)
- **D-08:** **Store all metrics as indexed `Float` columns** (analytical store, cheap): `sharpe`,
  `sortino`, `cagr`, `calmar`, `max_drawdown`, `profit_factor`, `win_rate`, `total_return`,
  `final_equity`, `total_realised_pnl`, `trade_count`. **Compute the two missing ones** —
  `total_return = final_equity/starting_cash - 1`; `calmar = cagr/abs(max_drawdown)` (both trivial).
  Same column set on `runs` (aggregate) and `run_portfolios` (per-strategy).
- **D-09 (artifact storage — blob, NOT exploded):** Frames persist as a **serialized blob**, one
  `run_artifacts` row per frame — **NOT exploded into per-trade / per-bar relational tables**. This
  honors the locked RESULT-02 / design-note decision ("single serialized blob… NOT exploded into
  per-bar rows"). Exploded tables were discussed (row-level cross-run SQL) and **rejected**: ~2,900
  equity rows/portfolio/run → millions at sweep scale, heavier dump, rigid schema. Cross-run analytics
  already live in the `runs` + `run_portfolios` **metric columns** — the frames are bulk artifacts you
  reload whole (chart / re-analyze), not query targets.
- **D-10 (encoding):** Each frame = `df.to_json(orient='split')` (clean dtype/index round-trip) →
  **gzip with header `mtime=0`** + fixed `compresslevel` (the one gzip determinism trap). ~10× smaller
  (matters at sweep scale); **byte-deterministic** once `mtime` is pinned. Round-trips to a value-equal
  DataFrame (RESULT-02 / RESULT-04).

### Curated settings envelope (Area 4)
- **D-11:** The settings JSON is a **curated, hand-picked envelope of result-relevant fields** — NOT a
  raw `model_dump` (which would drag in `SystemConfig` noise: dirs/ports/restart-timeouts, and would
  *miss* the exchange/order config that isn't nested in `SystemConfig`). A planner-built explicit
  serializer.
  - **`runs.settings`** (run-level): run window (`tickers`, `timeframe`, `start_date`, `end_date`,
    `starting_cash`), `rng_seed`, `fee_model` (type + params), `slippage_model` (type + params),
    `market_execution` (order type), exchange limits (`min_order_size`, `max_order_size`,
    `supported_symbols`), failure-sim (`simulate_failures`, `failure_rate`).
  - **`run_portfolios.params`** (per-strategy): strategy class name + alpha params (`fast_window`,
    `slow_window`, `signal_window`, …) + the strategy-declared risk knobs (`sizing_policy`,
    `sltp_policy`, `direction`) — the knobs a future sweep varies (so they live per-strategy, since a
    2-strategy run can differ).

### DB persistence model (Area 5)
- **D-12:** The results store defaults to an **on-disk SQLite file** (e.g. `output/results.db`, path
  configurable via `SqlSettings`) that **accumulates runs across invocations**; `create_all(checkfirst=True)`
  is idempotent so re-runs append, not clobber. **"Ephemeral" (RESULT-03) means no Alembic chain
  (`create_all`, disposable schema) — NOT in-memory.** `:memory:` stays the default for the **tests**
  (round-trip / determinism). This is what makes "query top-N runs later" + multi-session sweeps work.
  ⚠ Planner: reconcile with Phase-1 `SqlSettings.default = ':memory:'` (D-02/D-12 there) — the results
  store layer sets its own on-disk path rather than relying on the generic SQLite default.

### Read / write API contract (Areas 6 + 7 + robustness 4)
- **D-13 (save):** Caller passes a **typed frozen `RunRecord`** (`run_id` + aggregate `RunMetrics` +
  `settings` dict + `per_portfolio: list[PortfolioRecord(portfolio_id, name, metrics, params)]`).
  **`save_run(record)` writes the `runs` row AND the `run_portfolios` rows in ONE transaction** (atomic
  — the cross-run surface never sees a run whose per-portfolio breakdown is missing). Matches the
  codebase's frozen-DTO convention (`FillDecision` etc.), `mypy --strict`-clean.
  **`save_artifact(run_id, portfolio_id, artifact_type, frame)`** writes frames separately (large
  blobs kept out of the summary payload) but within the same logical persist step.
- **D-14 (aggregate equity — read-model math):** The combined equity curve = **outer-join on the union
  timestamp index + forward-fill** each portfolio's `total_equity` (leading pre-activity values =
  that portfolio's starting cash), then sum across portfolios. **Chosen because it correctly handles
  DIFFERENT TIMEFRAMES** (a 1h + a 1d strategy in one run snapshot at different cadences) — ffill marks
  the coarse portfolio at its last value; inner-join would discard fine resolution, identical-grid
  would *raise* on mixed timeframes. Reduces to an exact per-bar sum when timeframes match.
  ⚠ Planner: the aggregate-metric **annualization basis** for mixed-timeframe runs needs an explicit
  decision (existing metrics annualize daily, `PERIODS=365`, from v1.5); default to the daily basis
  for the single-timeframe common case, pick the finest/dominant timeframe otherwise.
- **D-15 (read shape):** `get_artifact(run_id)` returns a **keyed collection**:
  `{(portfolio_id, artifact_type): DataFrame}` — one call loads every frame for a run, ABC signature
  unchanged (just return-type refined). Round-trip test asserts a specific frame within the dict.
- **D-16 (missing reads):** `get_artifact(unknown_id)` **raises `ResultsNotFound`** (a `NotFoundError`
  subclass in the `ITraderError` hierarchy — explicit lookup of a nonexistent run is a caller bug).
  `top_runs` is **empty-safe** (`[]` on an empty table / fewer-than-`n`).

### Dump-failure policy (robustness 1)
- **D-17:** **Configurable**, via a `strict_persist` flag on the **store / `SqlSettings`, set at
  composition** (so `run()` keeps its single clean `persist` boolean):
  - default `strict_persist=False` → **log-and-warn** (ERROR + `exc_info`); `run()` returns normally,
    in-memory results stay usable (a sweep doesn't lose 999 good runs because run 500's write failed —
    persistence is a post-loop side-effect that can't corrupt run state).
  - `strict_persist=True` → **re-raise** (fail-fast-consistent for a deliberate single run).

### top_runs determinism (robustness 3)
- **D-18:** `top_runs(metric, n)` — `metric` is **caller-selectable** from the widened `MetricName`
  allow-list (incl. `final_equity`). A **per-metric direction map**: higher-is-better for
  sharpe/sortino/cagr/calmar/total_return/profit_factor/win_rate/final_equity/total_realised_pnl/trade_count;
  `max_drawdown` ranks by **smallest magnitude** (⚠ verify its sign convention in `reporting/metrics.py`
  at plan time). `ORDER BY {metric} {dir}, run_id ASC` — UUIDv7 `run_id` is the **stable deterministic
  tiebreak** (Success Criterion 3). Rankable `Float` columns indexed. Same ranking surface available on
  `run_portfolios` for single-strategy ranking.

### ABC widening (consolidated — Phase 1 fixed `ResultsStore` at 4 methods; Phase 2 owns the concrete surface)
- The Phase-1 `ResultsStore` ABC is **widened** in Phase 2:
  - `MetricName` `Literal` widened to all rankable metrics (D-08/D-18).
  - `get_artifact(run_id)` return-type refined to the keyed collection (D-15).
  - `save_artifact` signature widened to `(run_id, portfolio_id, artifact_type, frame)` (D-13).
  - `save_run` input typed as `RunRecord` (D-13).
  - ⚠ Planner flag: per-strategy ranking on `run_portfolios` may warrant a **5th method**
    (e.g. `top_portfolios`). Phase 1 deliberately fixed the surface at 4 — reconcile at plan time
    (add the method, or expose run_portfolios ranking through `top_runs` with a target arg).

### Claude's Discretion
- Exact package layout under `itrader/results/` (e.g. `sql_storage.py` + `models.py` / `records.py`);
  ORM/Core table definitions and the SQLAlchemy declarative shape; precise `RunMetrics`/`RunRecord`/
  `PortfolioRecord` field types; which exact columns get composite vs single indexes; the
  curated-serializer implementation; `ResultsNotFound` placement in `core/exceptions/`.
- The **strategy-param introspection seam** — how to extract a strategy's class-attribute params for
  `run_portfolios.params` (v1.3 STRAT-01 made params class attributes overridable via kwargs; planner/
  researcher confirms the introspectable accessor).

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### ⚠️ Precedence (read FIRST)
- `.planning/PROJECT.md` → "Current Milestone: v1.6" + "Owner Decisions (research-time, supersede the
  seed)" — the **authoritative locked scope**. Results store = **all-`Float`**, **no Parquet/`pyarrow`**,
  **no `DecimalAsText`**, **substrate only** (no sweep loop). Where the seed/research differ, Owner
  Decisions win.

### Requirements & scope
- `.planning/REQUIREMENTS.md` — RESULT-01/02/03/04 (full text), GATE-01/02, the Out-of-Scope table.
- `.planning/ROADMAP.md` → "Phase 2: Results Store (#1)" — the four Success Criteria (incl. the
  byte-determinism criterion 3 + the GATE-01 recurring gate).
- `.planning/STATE.md` → "Milestone Gate (v1.6 — DB-gated)" + indentation/FL-06 notes.

### The seam this phase implements (read the code)
- `itrader/results/base.py` — the Phase-1 `ResultsStore` ABC + the `MetricName` allow-list this phase
  widens. 4-space indentation. Phase 2 lands the concrete `Sql`-backed impl beside it.
- `itrader/storage/backend.py`, `itrader/storage/types.py` — the Phase-1 `SqlBackend` (Engine +
  MetaData + Core constructs) and the cross-dialect type helpers the store **composes** (`Uuid`,
  `JSON().with_variant(JSONB, "postgresql")`). 4-space.
- `itrader/config/sql.py` — `SqlSettings` / `SqlDriver` (SQLite default `:memory:`); the results store
  sets its own on-disk path (D-12) + carries the `strict_persist` knob (D-17).

### Data sources the persist hook reads (post-run, queue-only rule)
- `itrader/reporting/frames.py` — `build_trade_log` / `build_equity_curve` + `TRADE_COLUMNS` /
  `EQUITY_COLUMNS`. The two frames per portfolio (the artifact source). **Pure, duck-typed** — do not
  add handler imports.
- `itrader/reporting/summary.py` — `build_summary` + `build_metrics_block` (the metric formulas:
  sharpe/sortino/cagr/max_drawdown/profit_factor/win_rate). `print_metrics_summary` = the per-portfolio
  loop the `run_portfolios` capture mirrors.
- `itrader/reporting/metrics.py` — the pure metric functions (D-16 backtesting.py-matched, `PERIODS=365`,
  ddof=1). Source for the aggregate-curve metrics + the `max_drawdown` sign convention (D-18 verify).
- `scripts/run_backtest.py` (L103-131) — how the oracle reads portfolio state after `run()` and builds
  frames/summary today (the model for the persist hook; the oracle stays store-free per D-04).

### Composition seam (where the store is injected)
- `itrader/trading_system/backtest_trading_system.py` — `TradingSystem.run()` (gains `persist`),
  `build_backtest_system` (the composition root the user highlighted; injects the store).
- v1.3 `SystemSpec` / `compose_engine` composition API — the modern injection seam for `results_store`.

### Research (HIGH-confidence; predates Owner Decisions — apply with the precedence note)
- `.planning/research/SUMMARY.md`, `.planning/research/ARCHITECTURE.md` (composition-not-inheritance;
  the four ABCs), `.planning/research/PITFALLS.md` (Pitfall 10/11 UUIDv7/JSON determinism; gzip/JSON
  byte-stability), `.planning/notes/persistence-milestone-design.md` §"Results store (#1)" (the
  `runs` + `run_artifacts` blob design; "NOT exploded into per-bar rows").
- `.planning/phases/01-sql-spine-security-hardening/01-CONTEXT.md` — Phase-1 spine decisions
  (D-01..D-16) the results store builds on.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `itrader/results/base.py::ResultsStore` — the ABC seam already exists (added Phase 1); Phase 2
  implements + widens it. `MetricName` allow-list already present.
- `itrader/storage/` spine (`SqlBackend`, `types.py` `Uuid` + JSON/JSONB variant helper) — composed
  by the store; `config/sql.py` `SqlSettings` selects/builds the engine.
- `itrader/reporting/{frames,summary,metrics}.py` — pure, duck-typed builders producing exactly the
  frames (equity/trade) + metrics the store persists. One formula source, reused, not reimplemented.

### Established Patterns
- **Frozen-DTO contract** between layers (`FillDecision`, `_PendingBracket`) → `RunRecord` /
  `PortfolioRecord` follow it (D-13).
- **Composition (has-a) over inheritance** — the store holds a `SqlBackend` by reference (SPINE-02),
  no cross-concern god base.
- **Factory string-arm** is the backend-selection idiom for the *operational* storages (in_memory vs
  postgresql) — but the results store is **single-backend SQLite, no mode split**, so it is constructed
  **directly** (D-19 below), the ABC being the real extension seam.
- **4-space indentation** throughout the new surface (`itrader/results/`, `itrader/storage/`,
  `config/`) — do NOT normalize to tabs.

### Integration Points
- New concrete modules under `itrader/results/` (beside `base.py`).
- `TradingSystem.run()` gains the `persist` boolean; `build_backtest_system` / `SystemSpec` inject the
  store (default `None`).
- Tests: in-process SQLite (`:memory:`) round-trip + byte-determinism (RESULT-04); reuse the Phase-1
  test harness. No testcontainers needed here (Postgres is Phase 3).

### Factory decision (Area 8)
- **D-19:** **No `ResultsStoreFactory`** — construct `SqlResultsStore(backend)` directly. The other
  factories exist for a real in_memory-vs-SQL fork; the results store has one backend and no
  backtest/live split, so a one-arm factory is ceremony. The `ResultsStore` ABC is the extension seam
  if a second backend ever appears.

</code_context>

<specifics>
## Specific Ideas

- Owner's framing of "curated settings": **all result-relevant info** (order type, fee model, slippage,
  risk params) — deliberately selected, not a bare minimum and not a blind full dump (D-11).
- Owner wants a **multi-strategy run** to show both the **compounded** result (the run) AND each
  strategy **singularly** (run_portfolios) — drove the runs/run_portfolios split (D-05/D-06).
- Owner specifically asked whether alignment copes with **different timeframes** — it does, via
  outer-join + ffill (D-14); this was the deciding factor over inner-join / identical-grid.
- Owner prefers the **compose-once, toggle-per-run** ergonomics (`run(persist=True/False)`) over passing
  the store each call (D-02).
- Dump-failure handling made **configurable** at owner's request (D-17), defaulting to the
  sweep-friendly log-and-warn.

</specifics>

<deferred>
## Deferred Ideas

- **Exploded per-row frame tables** (`run_trades` / `run_equity` for row-level cross-run SQL) —
  discussed and rejected for Phase 2 (scale/rigidity, reverses RESULT-02). Could be revisited as a
  separate analytical surface in a future milestone if row-level querying becomes a real need.
- **Optuna sweep / sampler loop** — v2 OPT-01; Phase 2 ships only the FK-ready substrate (nullable
  study/trial ids on `runs`).
- **Postgres / second results backend** — not needed (research-only SQLite); the ABC + direct
  construction leave the door open without a factory now.

### Reviewed Todos (not folded)
- **`single-pass-portfolio-valuation.md`** (matched at score 0.6) — a **performance** optimization
  (per-bar portfolio valuation), matched only on generic keywords (phase/gate/regression/byte/exact).
  Orthogonal to the results store — belongs to a future perf pass, profile-first gated. **NOT folded.**

</deferred>

---

*Phase: 2-Results Store (#1)*
*Context gathered: 2026-06-29*

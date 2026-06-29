# Phase 2: Results Store (#1) - Pattern Map

**Mapped:** 2026-06-29
**Files analyzed:** 13 (new + modified)
**Analogs found:** 13 / 13

> Indentation hazard (CLAUDE.md): every file in this phase lives in a **4-space** layer
> (`itrader/results/`, `itrader/storage/`, `itrader/config/`, `itrader/core/exceptions/`)
> EXCEPT the composition root + spec under `itrader/trading_system/` which are **TABS**.
> Match the file you edit — never normalize. Each assignment below pins the indentation.

---

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality | Indent |
|-------------------|------|-----------|----------------|---------------|--------|
| `itrader/results/sql_storage.py` (NEW) | service / storage | CRUD + file-I/O (blobs) | `itrader/price_handler/store/sql_store.py::SqlHandler` | exact (Core-table + injected `SqlBackend`) | 4-space |
| `itrader/results/models.py` (NEW) | model (Core tables) | transform (schema) | `sql_store.py` `Table(...)` block (L79-92) | role-match | 4-space |
| `itrader/results/records.py` (NEW) | model (frozen DTOs) | request-response | `matching_engine.py::FillDecision` + `system_spec.py::SystemSpec` | exact (frozen value object) | 4-space |
| `itrader/results/serializers.py` (NEW — curated settings + agg curve) | utility | transform | `reporting/summary.py::build_summary` + `reporting/frames.py` | role-match | 4-space |
| `itrader/results/base.py` (MODIFY — widen ABC) | model (ABC seam) | request-response | self (current 4-method ABC) | exact (in-place widen) | 4-space |
| `itrader/results/__init__.py` (MODIFY — barrel) | config (barrel) | n/a | `itrader/storage/__init__.py` | exact | 4-space |
| `itrader/config/sql.py` (MODIFY — `strict_persist` + on-disk path) | config | n/a | self (`SqlSettings`) | exact (add fields) | 4-space |
| `itrader/core/exceptions/results.py` (NEW — `ResultsNotFound`) | model (exception) | n/a | `core/exceptions/portfolio.py::PortfolioNotFoundError` | exact | 4-space |
| `itrader/core/exceptions/__init__.py` (MODIFY — export) | config (barrel) | n/a | self | exact | 4-space |
| `itrader/trading_system/compose.py` (MODIFY — `results_store` param) | composition | request-response | self (`compose_engine` + `Engine`) | exact | **TABS** |
| `itrader/trading_system/backtest_trading_system.py` (MODIFY — `run(persist=)` + inject) | composition | event-driven (post-loop) | self (`run()` + `build_backtest_system`) | exact | **TABS** |
| `itrader/trading_system/system_spec.py` (MODIFY — optional `results_store`) | model (frozen spec) | n/a | self (`SystemSpec`) | exact | **TABS** |
| `tests/unit/results/test_sql_results_store.py` (NEW) | test | CRUD round-trip + determinism | Phase-1 spine `:memory:` harness | role-match | 4-space |

---

## Pattern Assignments

### `itrader/results/sql_storage.py` (service/storage, CRUD + blob file-I/O) — 4-space

**Analog:** `itrader/price_handler/store/sql_store.py::SqlHandler` — the only existing
concrete that composes the spine, registers a Core `Table` on `backend.metadata`, and does
parameterized read/write. Copy its shape wholesale.

**Imports pattern** (`sql_store.py` L44-51) — Core constructs + spine helpers, no ORM:
```python
from typing import Any
import pandas as pd
from sqlalchemy import Column, Float, String, Table, bindparam, insert, select
from itrader.config import TIMEZONE
from itrader.logger import get_itrader_logger
from itrader.storage import SqlBackend, UtcIsoText
```
For this store also pull `Uuid`/`UuidType` + `json_variant` from `itrader.storage`
(`itrader/storage/__init__.py` re-exports them), plus `ForeignKey`, `delete` from sqlalchemy.

**Composition + idempotent table registration** (`sql_store.py` L70-96) — copy verbatim,
substituting the three results tables and `create_all(checkfirst=True)` (D-12 idempotent
append). Note the "reuse already-registered table on a shared backend" guard:
```python
def __init__(self, backend: SqlBackend) -> None:
    self.backend = backend
    self.engine = backend.engine
    metadata = backend.metadata
    if "prices" in metadata.tables:           # → "runs" / "run_portfolios" / "run_artifacts"
        self.prices = metadata.tables["prices"]
    else:
        self.prices = Table("prices", metadata, Column(...), ...)
    self.prices.create(self.engine, checkfirst=True)   # → metadata.create_all(engine, checkfirst=True)
    self.logger = get_itrader_logger().bind(component="SQLHandler")  # → "SqlResultsStore"
```
⚠ This store carries `strict_persist` (D-17) — read it off the injected `SqlSettings`/store
ctor, NOT off `run()`. Default `False` → log `error(..., exc_info=True)` and return; `True`
→ re-raise. The logging idiom is CLAUDE.md's `self.logger.error(..., exc_info=True)`.

**Atomic multi-row write — ONE transaction** (`sql_store.py` L124-132). `save_run(record)`
must write the `runs` row AND all `run_portfolios` rows inside a single `engine.begin()`
block (D-13 atomicity):
```python
with self.engine.begin() as connection:
    connection.execute(insert(self.runs), [run_row])
    if portfolio_rows:
        connection.execute(insert(self.run_portfolios), portfolio_rows)
```
`save_artifact(run_id, portfolio_id, artifact_type, frame)` is a separate `engine.begin()`
INSERT of one gzip-blob row (large blobs kept out of the summary payload, D-13).

**Parameterized read + missing-read raise** (`sql_store.py` L134-152, read pattern). For
`get_artifact(run_id)` build `select(...).where(col == bindparam("run_id"))`; if the result
set is empty raise `ResultsNotFound(run_id)` (D-16). Return the **keyed collection**
`{(portfolio_id, artifact_type): DataFrame}` (D-15) by decoding each blob row.

**`top_runs` — allow-list column ORDER BY, never an f-string** (the core SQL-injection guard
documented in `results/base.py` L25-29). `metric` is constrained to `MetricName`, so resolve
the actual `Column` via a dict keyed by the literal, then ORDER BY **DESC for every metric**
(D-18); tiebreak `run_id ASC`:
```python
column = self._metric_columns[metric]            # MetricName Literal → bound Column object
# DESC for ALL metrics — incl. max_drawdown, which is stored NEGATIVE (see sign trap below):
# largest (closest-to-zero) signed value = least-bad drawdown = best run.
direction = column.desc()
stmt = select(self.runs).order_by(direction, self.runs.c.run_id.asc()).limit(n)
```
`top_runs` is empty-safe: an empty/short table returns `[]` (D-16). ⚠ `max_drawdown` sign trap —
`reporting/metrics.py` L47-56 returns **NEGATIVE** drawdown, so "smallest magnitude / least-bad
drawdown" = **largest (closest-to-zero) signed value** = `ORDER BY max_drawdown DESC` — the SAME
direction as every other metric. Do NOT branch `asc()` for `max_drawdown`.

**gzip-JSON determinism** (D-10, no analog in code — research PITFALLS 10/11). Pin
`mtime=0` and a fixed `compresslevel`:
```python
buf = io.BytesIO()
payload = frame.to_json(orient="split").encode("utf-8")
with gzip.GzipFile(fileobj=buf, mode="wb", compresslevel=6, mtime=0) as gz:
    gz.write(payload)
blob = buf.getvalue()           # byte-deterministic across runs (RESULT-04)
# decode: pd.read_json(io.StringIO(gzip.decompress(blob).decode("utf-8")), orient="split")
```

---

### `itrader/results/models.py` (model — Core table definitions) — 4-space

**Analog:** the `Table("prices", metadata, Column(...))` block in `sql_store.py` L79-92 —
this codebase uses **SQLAlchemy Core `Table`**, NOT declarative ORM. Match that.

**Column-type vocabulary** (from `itrader/storage/types.py`):
- `run_id` PK / FK + `portfolio_id` → `Uuid(as_uuid=True)` (re-exported `Uuid`/`UuidType`,
  `types.py` L31-34) — round-trips to a native `uuid.UUID` on SQLite (D-08 single UUIDv7).
- metric columns (`sharpe`, `sortino`, `cagr`, `calmar`, `max_drawdown`, `profit_factor`,
  `win_rate`, `total_return`, `final_equity`, `total_realised_pnl`, `trade_count`) → `Float`,
  **indexed** (`Column(..., Float, index=True)`) for rankable `ORDER BY` (D-08/D-18).
  Same column set on `runs` AND `run_portfolios` (D-08).
- `settings` / `params` JSON → `json_variant()` (`types.py` L67-69 — `JSON` on SQLite,
  `JSONB` on Postgres).
- artifact blob → `LargeBinary` (gzip bytes) or `Text` (b64/utf-8) — text blob per RESULT-02
  ("not a columnar binary format"; `results/base.py` L13-15).
- business time, if any timestamp column lands → `UtcIsoText` (`types.py` L37-64).

**Schema shapes** (from CONTEXT D-05/06/07):
- `runs`: PK `run_id` (Uuid); the 11 `Float` metric columns; `settings` json_variant;
  nullable `study_id` / `trial_id` (Uuid, Optuna-FK-ready substrate, deferred sweep).
- `run_portfolios`: `run_id` FK → `runs.run_id`, `portfolio_id` (Uuid), `name` (String),
  the same 11 `Float` metric columns, `params` json_variant. Composite/relevant indexes at
  discretion.
- `run_artifacts`: PK `(run_id, portfolio_id, artifact_type)`; `portfolio_id` **nullable**
  (D-07 — aggregate-level frames); `artifact_type` String ∈ `{equity_curve, trade_log}`;
  blob column. Typed-row-per-frame (NOT exploded per-bar — D-09).

Register all three on the injected `backend.metadata` (same shared-metadata pattern as
`sql_store.py` L74-77), then `metadata.create_all(engine, checkfirst=True)`.

---

### `itrader/results/records.py` (model — frozen DTOs) — 4-space

**Analog A (frozen value object, kw_only):** `matching_engine.py::FillDecision` (L80-91) —
the codebase frozen-DTO convention. Note it uses `msgspec.Struct`; the spec dataclasses
(`system_spec.py` L38-104) use `@dataclass(frozen=True)`. Either matches the convention;
prefer `@dataclass(frozen=True, slots=True, kw_only=True)` for mypy-strict plain DTOs (no
serialization need) — but the `results/` layer is 4-space, so do not paste the tab-indented
`system_spec.py` lines.

```python
@dataclass(frozen=True)
class FillDecision(...):   # matching_engine L80-91 — frozen, kw_only, doc-anchored
    order_event: OrderEvent
    fill_price: Decimal
    reason: str
```

**Analog B (nested frozen spec with `list[...]` of child frozen objects):**
`system_spec.py::SystemSpec` holding `portfolios: list[PortfolioSpec]` (L79-104) — exact
shape for `RunRecord` holding `per_portfolio: list[PortfolioRecord]`.

Build per D-13:
- `RunMetrics` (frozen) — the 11 metric `float`s (D-08).
- `PortfolioRecord` (frozen) — `portfolio_id`, `name`, `metrics: RunMetrics`, `params: dict`.
- `RunRecord` (frozen) — `run_id: uuid.UUID`, `metrics: RunMetrics`, `settings: dict`,
  `per_portfolio: list[PortfolioRecord]`.

⚠ Money policy: metric values are **`float`** here (results store is all-`Float`, CONTEXT
Precedence + D-08). This is the analytical store, not the money ledger — `float` is correct,
not a Decimal defect.

---

### `itrader/results/serializers.py` (utility — curated settings + aggregate equity) — 4-space

**Analog (pure, duck-typed builder, explicit field selection):** `reporting/summary.py::build_summary`
(L129-163) — the curated-dict pattern. It hand-picks keys into a dict (NOT a `model_dump`),
exactly the D-11 "curated envelope" requirement:
```python
return {
    "ticker": ticker, "timeframe": timeframe, "start_date": start_date,
    "end_date": end_date, "starting_cash": float(starting_cash),
    "final_cash": float(portfolio.cash), ...
}
```
Build two curated serializers (D-11):
- `runs.settings` — run window + `rng_seed` + `fee_model`/`slippage_model` (type+params) +
  `market_execution` + exchange limits + failure-sim. Source the live values off the engine's
  config objects at persist time.
- `run_portfolios.params` — per-strategy via the **introspection seam** below.

**Strategy-param introspection seam** (Claude's-discretion item) — analog
`strategy_handler/base.py::Strategy.to_dict()` / `_build_to_dict_snapshot()` (L672-761). It
already produces a JSON-safe dict of the full declared param surface (windows, `sizing_policy`
repr, `sltp_policy`, `direction.value`, `strategy_name`). Read `params` from
`strategy.to_dict()` rather than re-introspecting `get_type_hints` — it is the existing,
cached, JSON-safe accessor (D-05/D-06). Filter to the result-relevant knobs (D-11).

**Aggregate equity curve (D-14)** — analog `reporting/frames.py::build_equity_curve`
(L66-85) for the per-portfolio `total_equity` series shape + the `astype(float)` + `sort_values`
+ `reset_index(drop=True)` idiom. The aggregate is NEW logic: outer-join each portfolio's
`total_equity` on the union timestamp index, forward-fill (leading = starting cash), sum
across portfolios. Then feed the combined series into the **existing** `reporting/metrics.py`
formulas (do NOT reimplement): `compute_returns`/`sharpe`/`sortino`/`cagr`/`max_drawdown` +
the two computed ones — `total_return = final_equity/starting_cash - 1` (or
`metrics.total_return`, L143-155) and `calmar = cagr/abs(max_drawdown)` (`metrics.calmar`,
L227-236). ⚠ Planner: pin the mixed-timeframe annualization basis (`PERIODS=365` default,
metrics.py L39).

---

### `itrader/results/base.py` (MODIFY — widen the ABC in place) — 4-space

Self-analog: the current 4-method ABC (full file above). Apply the consolidated widening
block (CONTEXT "ABC widening"):
- L29 `MetricName` Literal → all 11 rankable metrics (D-08/D-18).
- `save_run` param typed `RunRecord`; returns `uuid.UUID` (D-13).
- `save_artifact` signature → `(run_id, portfolio_id, artifact_type, frame)` (D-13).
- `get_artifact(run_id)` return-type → `dict[tuple[uuid.UUID, str], pd.DataFrame]` (D-15).
- ⚠ Planner flag: decide on a 5th `top_portfolios` method vs a `target` arg on `top_runs`
  (per-strategy ranking, CONTEXT). Keep NumPy-docstring style (existing convention).

---

### `itrader/config/sql.py` (MODIFY — add `strict_persist` + on-disk path) — 4-space

Self-analog: `SqlSettings` (L45-61). Add a `strict_persist: bool = False` field (D-17) and
ensure an on-disk results path is selectable (D-12). Two reconciliation options for the
planner (D-12 ⚠): either (a) add a results-specific default path field and let the results
store build its `SqlSettings` with `database="output/results.db"`, or (b) construct
`SqlSettings(database="output/results.db")` at composition. Keep `ConfigDict(extra="forbid")`
+ the `default()` classmethod convention (L53-61). Tests keep `:memory:` (CONTEXT D-12).

---

### `itrader/core/exceptions/results.py` (NEW) + `__init__.py` (MODIFY) — 4-space

**Analog:** `core/exceptions/portfolio.py::PortfolioNotFoundError` (L59-64) — exact template
for a `NotFoundError` subclass:
```python
class PortfolioNotFoundError(NotFoundError):
    def __init__(self, portfolio_id: PortfolioIdLike):
        self.portfolio_id = portfolio_id
        super().__init__("Portfolio", portfolio_id)
```
Write `ResultsNotFound(NotFoundError)` taking `run_id`, calling `super().__init__("Run", run_id)`.
Import `NotFoundError` from `.base`. Then add it to `core/exceptions/__init__.py` imports +
`__all__` (existing barrel pattern, L9-63).

---

### `itrader/trading_system/compose.py` (MODIFY — thread `results_store`) — **TABS**

Self-analog: `compose_engine` (L109-249) + the `Engine` dataclass (L81-106). Add a
`results_store: Optional[ResultsStore] = None` keyword param to `compose_engine`, add the
field to the `Engine` dataclass (default `None`, like `universe`, L106), and pass it through
in the final `Engine(...)` construction (L236-249). The store is injected, not built here
(D-02 — the factory selects backends; the seam stays mode-agnostic, L13-19). Indentation is
**TABS** — match every existing line in this file.

---

### `itrader/trading_system/backtest_trading_system.py` (MODIFY — `run(persist=)` + inject) — **TABS**

Self-analog: `run()` (L183-229) and `build_backtest_system` (L245-309).

**`run(persist: bool = False)`** — extend the existing signature (L183-184). The post-run
read-block model is **`scripts/run_backtest.py` L103-122** (the persist hook reads portfolio
state AFTER `run()`, queue-only):
```python
portfolio = system.portfolio_handler.get_portfolio(portfolio_id)
trades = build_trade_log(portfolio)
equity = build_equity_curve(portfolio)
summary = build_summary(portfolio, trades, ticker=..., ...)
summary["metrics"] = build_metrics_block(equity, trades)
```
The existing `print_summary` block (L205-229) already loops active portfolios + builds
per-portfolio metric bags via `reporting` — mirror that loop to assemble `PortfolioRecord`s
(this is the `run_portfolios` capture, D-06). Guard (D-03): `persist=True` with
`engine.results_store is None` raises a clear `ConfigurationError`
(`core/exceptions/base.py` L28-42). On `persist=False` (default) the dump never executes →
oracle byte-exact (D-04). The dump is OFF the run loop (post `self.runner.run(...)`, L203).

**`build_backtest_system`** — inject the store at composition (D-02): pass
`results_store=spec.results_store` (or a composed default) into `compose_engine` at L269-278,
alongside `order_storage`/`signal_store`. Construct it **directly** — `SqlResultsStore(backend)`,
NO factory (D-19) — contrast the `OrderStorageFactory.create('backtest')` arm (L258) which
exists only for the in_memory/SQL fork the results store does not have.

---

### `itrader/trading_system/system_spec.py` (MODIFY — optional `results_store`) — **TABS**

Self-analog: `SystemSpec` (L79-104). Add `results_store: Any = None` as a defaulted field so
existing call sites (oracle/e2e) stay store-free (D-04). Frozen dataclass, **TABS**, field
names otherwise must not change (e2e reads by name, L13-19).

---

### `tests/unit/results/test_sql_results_store.py` (NEW) — 4-space

**Analog:** Phase-1 spine `:memory:` harness (CONTEXT Integration Points — reuse it). Build a
`SqlBackend(SqlSettings())` (`:memory:` default, `config/sql.py` L55-61), wrap in
`SqlResultsStore`, exercise: (1) `save_run` + `save_artifact` → `get_artifact` round-trip
asserts a value-equal DataFrame for a specific `(portfolio_id, artifact_type)` key (D-15,
RESULT-02); (2) byte-determinism — encode the same frame twice, assert identical gzip bytes
(RESULT-04, D-10); (3) `top_runs(metric, n)` ordering + `run_id ASC` tiebreak (D-18); (4)
`get_artifact(unknown)` raises `ResultsNotFound` (D-16); (5) `top_runs` empty-safe `[]`.
⚠ Test-strictness: `filterwarnings=["error"]` + `--strict-markers` — folder-derived `unit`
marker; keep `tests/unit/results/` package-less (MEMORY: __init__.py collision).

---

## Shared Patterns

### Composition over inheritance (has-a `SqlBackend`)
**Source:** `itrader/storage/backend.py` L18-40 + `sql_store.py` L70-72.
**Apply to:** `SqlResultsStore`, `models.py`.
Hold the injected `SqlBackend` by reference (`self.backend` / `self.engine = backend.engine`);
register tables on `backend.metadata`; delegate engine lifecycle to `backend.dispose()` (never
call `engine.dispose()` directly — `backend.py` L32-40, WR-03).

### Cross-dialect column types (the only encoding vocabulary)
**Source:** `itrader/storage/types.py` (`Uuid`/`UuidType` L31-34, `UtcIsoText` L37-64,
`json_variant()` L67-69).
**Apply to:** every column in `models.py`. Do NOT hand-roll per-dialect TEXT/BLOB switches
(types.py L9-11). Money never lands here — all-`Float` (types.py L18-21, CONTEXT Precedence).

### Parameterized Core SQL, never string-interpolated identifiers
**Source:** `sql_store.py` L124-187 (every read/write/delete uses `bindparam` against a
constant table name) + the `MetricName` allow-list rationale in `results/base.py` L25-29.
**Apply to:** `sql_storage.py`. Column names in `ORDER BY` resolve through a `MetricName`→`Column`
dict; values are always bound. This is the SQL-injection guard (Phase-1 FL-06 target).

### GATE-01 import inertness (keep SQL off the backtest hot path)
**Source:** `storage/__init__.py` L1-8 + `sql_store.py` L39-41 — the SQL-heavy backend is
deliberately NOT re-exported at package level so the backtest import path stays SQL-free.
**Apply to:** `results/__init__.py` — barrel-export `ResultsStore` ABC + records, but keep
`SqlResultsStore` (which imports SQLAlchemy) out of the default import path so a store-free
(`persist=False`) run never imports SQL. The dump is structurally off the run loop (D-01).

### Pure duck-typed reporting builders (one formula source, reused)
**Source:** `reporting/frames.py`, `reporting/summary.py`, `reporting/metrics.py` (all pure,
pandas+stdlib only, zero handler imports).
**Apply to:** `serializers.py` + the `run(persist=)` hook. Reuse `build_trade_log` /
`build_equity_curve` / `build_metrics_block` / the `metrics.py` formulas — do NOT
reimplement. Keep new builders pure + duck-typed (no handler imports), matching the purity
contract (frames.py L11-15).

### Bound-logger + error policy
**Source:** CLAUDE.md + `sql_store.py` L94.
**Apply to:** `SqlResultsStore` — `self.logger = get_itrader_logger().bind(component="SqlResultsStore")`.
D-17 dump-failure: `strict_persist=False` → `self.logger.error(..., exc_info=True)` and return;
`True` → re-raise.

---

## No Analog Found

| Concern | Role | Reason | Planner guidance |
|---------|------|--------|------------------|
| gzip-JSON byte-deterministic encode/decode (D-10) | utility | No gzip/blob encoder exists in the codebase | Use research PITFALLS 10/11: `gzip.GzipFile(..., mtime=0, compresslevel=<fixed>)` + `df.to_json(orient="split")` |
| aggregate equity outer-join + ffill across portfolios (D-14) | utility/transform | Existing builders are single-portfolio; no multi-portfolio union exists | New logic; feed result into existing `metrics.py` formulas. Pin mixed-timeframe annualization basis |
| `metadata.create_all(checkfirst=True)` for multiple tables | schema | `sql_store.py` creates ONE table via `Table.create`; no multi-table `create_all` site | Use `metadata.create_all(engine, checkfirst=True)` (idempotent, D-12) — Alembic chain is explicitly out (RESULT-03) |

---

## Metadata

**Analog search scope:** `itrader/results/`, `itrader/storage/`, `itrader/config/`,
`itrader/reporting/`, `itrader/trading_system/`, `itrader/core/exceptions/`,
`itrader/price_handler/store/`, `itrader/execution_handler/`, `itrader/strategy_handler/`,
`itrader/order_handler/storage/`, `scripts/`.
**Files scanned:** 14 read in full/targeted + directory/grep sweeps.
**Pattern extraction date:** 2026-06-29

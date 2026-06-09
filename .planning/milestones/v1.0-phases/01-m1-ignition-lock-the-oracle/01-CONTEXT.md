# Phase 1: M1 — Ignition + Lock the Oracle - Context

**Gathered:** 2026-06-04
**Status:** Ready for planning

<domain>
## Phase Boundary

Make the backtest path **import and run** `SMA_MACD` end-to-end on the golden CSV
producing real (non-zero-quantity) trades, then **capture and commit the reference
output** (the behavioral + numerical oracle) and stand up the **test skeleton**.

This is the only milestone built *without* an oracle to check against, so it is kept
**ruthlessly minimal**. The WHAT is fully locked by `REQUIREMENTS.md` (M1-01…M1-10)
and ROADMAP Phase 1's four success criteria — this discussion only resolved the HOW
for decisions that determine the oracle numbers and the seams M1 leaves behind.

**In scope (from REQUIREMENTS.md M1-01…M1-10):** fix the ignition-blocking bugs
(config/import cascade, `config.TIMEZONE` access, `to_timedelta` None, `SMA_MACD`
`[-1]`/`fillna`, `record_metrics` target), feed the golden CSV, add minimal real
sizing, run the full PING→BAR→SIGNAL→ORDER→FILL loop, capture+commit the oracle,
stand up the pytest skeleton (markers + conftest + smoke + integration), keep the
274 existing component tests green.

**Out of scope (deferred to later milestones — see Deferred Ideas):** UUIDv7,
Decimal money, `mypy --strict`, injected clock / seeded RNG, config→Pydantic
(M2); event immutability / dispatch registry (M3); CashManager routing / atomic
transactions (M4); the real Provider/Store/Feed price split, fee/slippage
correctness, full strategy-declared sizing policy, cross-validation (M5).

</domain>

<decisions>
## Implementation Decisions

### Golden Run Configuration (defines the oracle)
- **D-01:** **Dataset = `data/BTCUSD_1d_ohlcv_2018_2026.csv`** (user-provided, owner-approved).
  This **SUPERSEDES** the `data/BTCUSD_1d_ohlcv_01_01_2021-04_06_2026.csv` filename
  referenced in `PROJECT.md`, `REQUIREMENTS.md`, `ROADMAP.md`, and `CLAUDE.md`.
  Format is **Binance-klines**: comma-delimited, **ascending (oldest-first)**, **3076
  daily bars**, header `Open time, Open, High, Low, Close, Volume, Close time, Quote
  asset volume, Number of trades, Taker buy base asset volume, Taker buy quote asset
  volume, Ignore`, timestamps like `2018-01-01 00:00:00.000000 UTC`. (The old
  CoinMarketCap file `…01_01_2021-04_06_2026.csv` is a *different, worse* format —
  semicolon-delimited, descending, `name="2781"`, only 398 rows / 13 months — and is
  NOT used.) ⚠ Planning should flag the doc references for update (gap-discovery delta).
- **D-02:** **Date window = full range 2018-01-01 → 2026-06-03**, pinned **explicitly**
  in the run script (not "whole file") so the oracle is insulated if the CSV is ever
  regenerated/extended. ~100 warmup bars (`max_window=100`) then ~2976 tradeable bars.
- **D-03:** **SMA_MACD parameters = code defaults**: `short_window=50, long_window=100,
  FAST=6, SLOW=12, WIN=3`. No new constants to justify.
- **D-04:** **Starting cash = $10,000; fees = 0; slippage = 0.** Cleanest possible
  oracle — pure trade math, easiest to cross-validate in M5. Fee/slippage correctness
  is explicitly an M5 concern, so the (M5-flagged-as-buggy) fee model is deliberately
  kept out of the M1 oracle.
- **D-05:** **Run invocation = a committed Python run script + a new `make backtest`
  target** (satisfies success criterion #1). The script is version-controlled and IS
  the reproducible oracle generator. NOT the notebook (`iTrader_backtester.ipynb` is
  not cleanly reproducible in CI).
- **D-06:** **Ticker = `BTCUSD`** (matches the dataset). Strategy subscribes to this
  single ticker on the `1d` timeframe. *(Claude's discretion — adjust if a different
  symbol string is required by the universe/price-handler wiring.)*

### CSV Data Feed
- **D-07:** **Minimal `csv`/offline branch INSIDE `PriceHandler`** (option 1, not a
  standalone provider). It reads the local CSV into `self.prices` and **skips
  `SqlHandler`/`CCXT` construction** entirely (today `PriceHandler.__init__` builds a
  `SqlHandler()` requiring PostgreSQL, and `load_data()` reads SQL/CCXT — none of that
  may run on the offline backtest path).
  - Rationale: `PriceHandler` is passed into **four** components in
    `TradingSystem.__init__` (`DynamicUniverse`, `StrategiesHandler`,
    `ScreenersHandler`, `StatisticsReporting`). A standalone provider would force
    rewiring all four and pre-judge the M5 Provider/Store/Feed design — that's not
    minimal. The in-`PriceHandler` branch touches zero consumers and naturally becomes
    the read-only offline read path M5 formalizes.
  - The golden-master discipline (M2–M4 behavior-preserving; M5 may change results)
    means this minimal feed is *not* risky to rework later — M5 owns the real split.

### Minimal Position Sizing (M1-06, the stranded `quantity=0` seam)
- **D-08:** **Rule = fraction of available cash: `qty = (0.95 × available_cash) / price`**,
  fractional BTC. SMA_MACD is long-only single-position; 95% leaves a small buffer so
  float/rounding can't overshoot available cash and trip a cash check. Scales with
  equity → clean compounding equity curve.
- **D-09:** **Seam = `OrderManager.on_signal` path** — compute quantity where it
  currently reads `signal_event.quantity` (order_manager.py ~lines 245/256/312/357),
  pulling portfolio cash + the current bar price. This is the architecturally-correct
  place locked by PROJECT.md (#24/#31: "order/risk layer resolves per-portfolio qty")
  and the natural home M5 (M5-06) grows the full policy / `RiskManager.check_cash` into.
  Do NOT fix sizing in the strategy/position_sizer (wrong layer).

### Oracle Capture & Regression Test
- **D-10:** **Format = CSV trade log + CSV equity curve + JSON summary** (final cash +
  metrics). CSV for the line-by-line git-diffable series; JSON for structured/typed metrics.
- **D-11:** **Two locations:** fresh `make backtest` output → **`output/` (gitignored —
  add `output/` to `.gitignore`)**; the **frozen oracle → `test/golden/` (committed)**.
  Flow: `make backtest` writes `output/`; a blessed run is promoted/copied into
  `test/golden/` and committed (honors M1-08 "captured and committed"); the integration
  test diffs a fresh run against `test/golden/`.
- **D-12:** **Determinism = capture only deterministic fields.** Exclude wall-clock
  `created_at`/audit timestamps and integer order-ID *values* (non-deterministic until
  M2's injected clock + UUIDv7). Capture bar-derived times, sides, quantities, prices,
  cash, metrics. **Identify each trade by `entry_time`/`exit_time`/`side`, not by ID.**
  No M1 determinism code change — the oracle survives the M2 clock/UUIDv7 switch
  unchanged because it never depended on those values. (SMA_MACD has no RNG.) Do NOT
  pull M2 determinism work forward.
- **D-13:** **Assertion = behavioral exact + numerical exact, re-baselined at boundaries.**
  Trade timing + sides + sequence asserted EXACTLY (behavioral oracle, law M2–M4).
  Numbers asserted exactly *within* M1; the golden file is re-frozen only after M2
  (float→Decimal shift) and after M5 — the two sanctioned re-baseline points in
  PROJECT.md. No float tolerance (M1 runs are bit-reproducible; tolerance would mask
  real regressions).

### Test Skeleton (M1-09 / M1-10)
- **D-14:** **Markers applied by path-based auto-marking in a root `test/conftest.py`**
  via `pytest_collection_modifyitems` — map directory → marker
  (`test_portfolio_handler`→`portfolio`, `test_events`→`events`,
  `test_order_handler`→`orders`, `test_execution_handler`→`execution`,
  `test_strategy`→`strategy`, etc.) plus `unit`/`integration`. The 8 declared markers
  become "actually applied" with **zero edits to the 30 legacy `unittest.TestCase`
  files**, and it works on `unittest.TestCase` (marks applied at collection). NOTE:
  all 30 existing test files are `unittest.TestCase` (not pytest-native) — they *run*
  under pytest today; the unittest→pytest-native **bulk conversion is M2b, NOT M1**.
- **D-15:** **Single root `test/conftest.py`** holding shared fixtures (`global_queue`,
  golden-file paths, a backtest-engine factory) + the auto-marking hook. No conftest
  exists today. Per-package conftests deferred unless needed.
- **D-16:** **Smoke vs integration split:** Smoke (fast, `unit`) = import→construct→run
  a handful of bars, assert it completes and produces ≥1 trade. Integration
  (`integration` + `slow`) = full 2018→2026 run, diff fresh `output/` vs `test/golden/`
  (behavioral exact + numerical exact per D-13).

### Claude's Discretion
- Exact ticker string (D-06) if the universe/price-handler wiring needs a specific symbol.
- Exact filenames/column schemas within `output/` and `test/golden/` (trade-log columns,
  equity-curve granularity, which metrics in the JSON summary) — keep human-readable and diffable.
- Exact directory→marker mapping details and conftest fixture signatures.
- Run-script location/name (e.g. `scripts/run_backtest.py`) and how `make backtest` invokes it.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Authoritative analysis (source of truth — do NOT re-derive requirements)
- `.planning/REFACTOR-BRIEF.md` — program goal/scope, locked decisions, golden-master discipline, definition-of-done
- `.planning/COVERAGE-INDEX.md` — all 105 items → milestone (the coverage contract); §E logs gap-discovery deltas
- `.planning/codebase/ARCHITECTURE-REVIEW.md` — 40 design findings (#1–40); #34 Critical = M1 ignition
- `.planning/codebase/CONCERNS.md` — 65 concrete defects (TD/KB/SEC/PERF/FR/SL/DEP/MF/TC); M1 touches KB11/KB15/KB16/KB17/KB18/KB20, TD2
- `.planning/PROJECT.md` — milestone breakdown, key decisions, constraints, gap-discovery protocol
- `.planning/REQUIREMENTS.md` — M1-01…M1-10 (the locked WHAT for this phase)
- `.planning/ROADMAP.md` — Phase 1 goal + 4 success criteria

### Codebase maps
- `.planning/codebase/ARCHITECTURE.md` — component graph, event flow, data flow
- `.planning/codebase/STRUCTURE.md` — module layout
- `.planning/codebase/CONVENTIONS.md` — tabs vs spaces, naming, logging, error handling
- `.planning/codebase/TESTING.md` — test layout and strictness
- `.planning/codebase/STACK.md`, `.planning/codebase/INTEGRATIONS.md`

### Golden dataset
- `data/BTCUSD_1d_ohlcv_2018_2026.csv` — THE golden dataset (Binance-klines format; see D-01). Supersedes the filename in the docs above.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `itrader/trading_system/backtest_trading_system.py` — the engine wiring + `run()` loop already exists (PING loop, `process_events`, `record_metrics`). The run script builds on this.
- `itrader/strategy_handler/SMA_MACD_strategy.py` — the reference strategy exists (top-level, not in gitignored `my_strategies/`).
- `itrader/strategy_handler/position_sizer/{fixed,variable}_sizer.py` — existing sizers (stranded); NOT the M1 seam (sizing goes in OrderManager per D-09), but informative.
- `itrader/reporting/` (`StatisticsReporting`) — existing metrics/summary computation for the JSON summary.
- `pyproject.toml` — 8 markers already declared (`unit, integration, slow, portfolio, events, orders, execution, strategy`); `filterwarnings=["error"]`, `--strict-markers`, `--strict-config`.

### Established Patterns
- Queue-only cross-domain communication; handlers receive `global_queue`, emit events.
- Handler/Manager split; `on_<event>` callbacks; `OrderStorageFactory.create('backtest')` → in-memory.
- Tab indentation in handler modules; spaces in `config/` and newer modules — match the file.

### Integration Points / Files to touch (M1 bugfixes + seams)
- `itrader/price_handler/data_provider.py` — add the `csv`/offline branch (D-07); `__init__` builds `SqlHandler()`, `_init_exchange` only knows `binance`, `load_data` reads SQL/CCXT.
- `itrader/trading_system/backtest_trading_system.py` — **KB18/M1-05 bug**: `record_metrics(ping_event.time)` is called on `self.portfolio_handler` (should be per-`Portfolio`). Also `datetime.now()` for duration only.
- `itrader/strategy_handler/SMA_MACD_strategy.py` — **KB15/M1-04 bugs**: `short_sma[-1]`/`long_sma[-1]` positional-on-label indexing → `.iloc[-1]`; `fillna='False'` (string) → `fillna=False`; uses `self.timeframe * window` (timeframe must be a timedelta → ties to `to_timedelta`/`config.TIMEZONE`, M1-02/M1-03).
- `itrader/order_handler/order_manager.py` + `order_handler.py` — sizing seam at `on_signal` (D-08/D-09); currently `quantity=signal_event.quantity` passthrough.
- `itrader/config/` + import cascade — M1-01 (config package/flat-module shadowing; price-handler→trading-system import chain).
- `test/` — add root `conftest.py` (D-14/D-15), smoke + integration tests (D-16); 30 `unittest.TestCase` files exist, no conftest today.

</code_context>

<specifics>
## Specific Ideas

- User explicitly replaced the dataset mid-discussion with a richer 8.4-year Binance-klines
  file (`data/BTCUSD_1d_ohlcv_2018_2026.csv`) — wants the oracle built on the broader span
  covering multiple market regimes (2018 bear, 2021 bull, 2022 crash, 2024–26).
- User wants regenerable run artifacts segregated from the committed regression baseline:
  `output/` (gitignored) for fresh runs, `test/golden/` (committed) for the frozen oracle.

</specifics>

<deferred>
## Deferred Ideas

- **Standalone CSV data provider / real Provider–Store–Feed split** → **M5a** (M5-04). M1 uses
  a minimal in-`PriceHandler` branch (D-07); the proper data-layer abstraction is M5's job.
- **Full strategy-declared sizing policy + `RiskManager.check_cash` for position increases +
  `VariableSizer`** → **M5b** (M5-06). M1 seeds only the minimal fraction-of-cash rule (D-08/D-09).
- **Injected clock + seeded RNG + UUIDv7 + Decimal money** → **M2** (M2-01…M2-04). M1 deliberately
  avoids these; the oracle excludes the volatile fields they'd make deterministic (D-12).
- **Fee/slippage correctness** → **M5a** (M5-03). M1 runs zero fees/slippage (D-04).
- **Bulk `unittest` → pytest-native conversion** → **M2b** (M2-09). M1 only stands up the
  skeleton (markers + conftest + 2 new tests) and keeps the 30 legacy files green (D-14).
- **Doc reference update** (PROJECT/REQUIREMENTS/ROADMAP/CLAUDE.md still name the old
  `…01_01_2021-04_06_2026.csv`) — log as a COVERAGE-INDEX §E gap-discovery delta for owner approval.

</deferred>

---

*Phase: 1-m1-ignition-lock-the-oracle*
*Context gathered: 2026-06-04*

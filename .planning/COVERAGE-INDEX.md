# Coverage Index — Findings & Defects → Milestones

> **Purpose:** the exhaustive bridge between the analysis and the work plan. Every architecture
> finding (#1–40 in `ARCHITECTURE-REVIEW.md`) **and** every concrete defect (`CONCERNS.md`, here
> assigned stable IDs) maps to a milestone **or** an explicit DEFERRED tag — so nothing is silently
> dropped. This is the requirement source GSD's `gsd-roadmapper` coverage-validates, and the
> fixed-vs-not ledger you track against (GSD's `STATE.md` becomes the live status once phases run).
>
> **Read with:** `REFACTOR-BRIEF.md` (scope, locked decisions, golden-master, milestone goals).
>
> **STATUS — v1.0 (Backtest-Correctness Refactor) shipped 2026-06-08.** Status column below reconciled
> at milestone close against the milestone audit (`milestones/v1.0-MILESTONE-AUDIT.md`) + cross-phase
> integration check. Every in-scope (M1–M5) item is ☑ Done or ◑ (done with a tracked residual);
> every `D-*`/`OUT` item is ⊘ Deferred (intentionally out of v1.0, see Section D / ROADMAP backlog).

## Legend

**Milestones:** `M1` Ignition · `M2` Foundations · `M3` Events & dispatch · `M4` Money & txn ·
`M5` Backtest validity/metrics/strategy/data.
**Deferred (out of this program):** `D-live` · `D-sql` · `D-screener` · `D-compliance` · `D-oanda`.
**Other:** `OUT` = resolved out-of-band (`my_strategies/*` relocation) · `M1→M2` = span (partial in
first, completed in second).
**Status:** ☑ Done (in-scope, delivered & verified in v1.0) · ◑ In-scope delivered with a tracked
residual carried to a future milestone · ⊘ Deferred out of v1.0 (`D-*` / `OUT`; not built by design) ·
☐ Planned (none remain in scope). For spans with a deferred half (e.g. `M2 (seam) + D-sql (backend)`),
☑ marks the **in-scope** deliverable; the deferred counterpart stays enumerated in Section D.

---

## Section A — Architecture findings (40)

| ID | Finding | Severity | Milestone | Status |
|----|---------|----------|-----------|:--:|
| 1 | Event dispatch loop: empty/get race + fused routing/ordering | High | M3 | ☑ |
| 2 | Event bus: keep in-house dispatch registry | Medium | M3 | ☑ |
| 3 | Market-data payload: replace pandas Series with a `Bar` struct | High | M5 *(rel. M3)* | ☑ |
| 4 | Resampling per tick: precompute frames | High | M5 | ☑ |
| 5 | Determinism: seed RNG, inject clock, flat order index | Medium | M2 | ☑ |
| 6 | Cross-handler coupling: order_handler → portfolio_handler | High | M4 | ☑ |
| 7 | Error handling: own domain errors; translate at FastAPI edge | High | M3 + `D-live` *(edge)* | ◑ |
| 8 | Transfer objects & typing: mypy strict + frozen dataclasses | High | M2 | ☑ |
| 9 | OrderHandler/OrderManager split + interface standardization | Medium | M4 | ☑ |
| 10 | ID strategy: UUIDv7 (rust `uuid-utils`) | **Critical** | M2 | ◑ |
| 11 | Event schema: linkage IDs, event_id, immutability, enums | High | M3 | ☑ |
| 12 | Settings/secrets: `pydantic-settings` | High | M2 *(settings)* + `D-live` *(secrets)* | ☑ |
| 13 | Config package over-engineering: collapse to Pydantic models | High | M2 | ☑ |
| 14 | Reporting layer: delete dead `EngineLogger`; split compute/present/persist | Medium | M5 *(persist→`D-sql`)* | ☑ |
| 15 | Type placement: centralize enums; entities in own modules | Medium | M2 | ☑ |
| 16 | Transaction `TransactionContext` write-only + control-flow bug | Medium | M4 | ☑ |
| 17 | Monetary values `float` vs `Decimal` → Decimal end-to-end | High | M2 | ☑ |
| 18 | Portfolio-handler storage abstraction (seam now, Postgres later) | High | M2 *(seam)* + `D-sql` *(backend)* | ☑ |
| 19 | Order lifecycle audit: durable storage + deterministic timestamps | Medium | M2 *(timestamps)* + `D-sql` *(durable)* | ☑ |
| 20 | Dead ABC enforcement (Py2 `__metaclass__`) — 8 unenforced bases | High | M2 | ☑ |
| 21 | Backtest validity: look-ahead, fill realism, bar-timing | High | M5 | ☑ |
| 22 | Trade path bypasses `CashManager` (float round-trip) | **Critical** | M4 | ☑ |
| 23 | Transaction non-atomicity: no rollback, broken return contract | High | M4 | ☑ |
| 24 | Strategy composition fiction; `calculate_signal` inconsistent | High | M1→M5 | ☑ |
| 25 | Data ingestion robustness (retry/timeout/pagination) | High | `D-sql` / `D-live` *(CSV path needs none)* | ⊘ |
| 26 | SQL persistence: table-name injection + SQLAlchemy-2.0 | High | `D-sql` | ⊘ |
| 27 | Exchange/data adapter abstraction; resting-book persistence | High | M5 *(price seam)* + `D-live` *(book persist)* | ☑ |
| 28 | Fee/slippage models: maker fees dead, tiered broken | Medium | M5 | ☑ |
| 29 | Intra-portfolio coupling + thread-safety theater | Medium | M4 | ☑ |
| 30 | Price handler god-object → Provider/Store/Feed + lifecycle | High | M5 *(in-mem/CSV; SQL→`D-sql`)* | ☑ |
| 31 | Strategy handler: sizing migration stranded (qty=0); policy resolution | High | M1→M5 | ◑ |
| 32 | Screeners handler: output discarded; orphaned dispatcher | High | `D-screener` *(orphan delete→M2)* | ⊘ |
| 33 | Universe: collapse to thin symbol-set stub | Medium | M5 | ☑ |
| 34 | Config migration half-finished & silently fatal (run path won't import) | **Critical** | M1→M2 | ☑ |
| 35 | `trading_system/` orchestration broken/duplicated/untested | High | M1 *(backtest)* + `D-live` *(TradingInterface, live threading)* | ☑ |
| 36 | `time_parser.py` timing-correctness bugs | High | M1→M2 | ☑ |
| 37 | Exception hierarchy + logging inconsistent/partly dead | Medium | M3 | ◑ |
| 38 | Reporting `performance/plots/base`: broken metrics + pandas-2 | High | M5 | ☑ |
| 39 | Execution `result_objects/base`: vestigial DTOs + fake ABC | Medium | M4 *(frozen/Decimal/ABC ride M2)* | ☑ |
| 40 | Testing strategy: unittest→pytest, layout, conftests, run-path coverage | High | M1 *(skeleton/smoke/markers)* + ongoing *(bulk conversion)* | ☑ |

**Residuals (◑) carried forward — tracked, non-blocking (see `milestones/v1.0-MILESTONE-AUDIT.md`):**
- **#7 / #37** (M3-03): a few bare `raise ValueError(...)` remain in `portfolio.py` (off the golden path) instead of typed domain exceptions → opportunistic cleanup (N+1 map-codebase pass).
- **#10** (M2-01): single UUIDv7 scheme delivered; `portfolio_id: int` annotation carry-over remains on Signal/Order/Fill events (runtime-correct, carries UUID) → annotation cleanup.
- **#31** (M5-06): strategy-declared sizing fully resolved engine-side; the `SHORT_ONLY` BUY-to-cover arm is missing (oracle-dark — golden strategy is LONG_ONLY) → **N+2** (margin/shorts milestone).

---

## Section B — Concrete defects (`CONCERNS.md`, 65)

IDs assigned here for traceability. "Parent" = the architecture finding this defect is an instance of.

### Tech Debt (TD)

| ID | Defect | Milestone | Parent | Status |
|----|--------|-----------|:--:|:--:|
| TD1 | PostgreSQL order storage entirely unimplemented | `D-sql` | 18 | ⊘ |
| TD2 | Dual config system (flat `config.py` vs package) | M1→M2 | 34 | ☑ |
| TD3 | `SqlHandler` hardcodes personal DB username | `D-sql` | 26 | ⊘ |
| TD4 | Dead modules (`legacy_config`, `profiling`, `outils/strategy`, `my_strategies`) | M2 *(my_strategies=`OUT`)* | 14 | ☑ |
| TD5 | `legacy_config.py` no callers (dup of TD4) | M2 | 13 | ☑ |
| TD6 | Rolling statistics unfinished stubs | M5 | 38 | ☑ |
| TD7 | `VariableSizer` position sizing incomplete (`#TODO`) | M5 | 31 | ☑ |
| TD8 | `DynamicUniverse` no asset removal | `D-screener` *(moot once #33 stub)* | 33 | ⊘ |
| TD9 | Compliance/`long_only` in strategy layer | `D-compliance` | — | ⊘ |
| TD10 | `RiskManager.check_cash` skips position-increase | M5 | 31/24 | ☑ |
| TD11 | `OANDA.py` hardcodes config file path | `D-oanda` | — | ⊘ |

### Known Bugs (KB)

| ID | Defect | Milestone | Parent | Status |
|----|--------|-----------|:--:|:--:|
| KB1 | `raise NotImplemented` (not `NotImplementedError`) in dispatch | M3 | 1 | ☑ |
| KB2 | `is np.nan` identity comparison always False | M5 | 38 | ☑ |
| KB3 | Live system double-queues events | `D-live` | 35 | ⊘ |
| KB4 | `get_statistics` calls non-existent method | `D-live` | 35 | ⊘ |
| KB5 | `BINANCE_Live` ping hardcoded to every 5th bar | `D-live` | — | ⊘ |
| KB6 | CCXT pagination duplicates boundary bar / truncates | `D-sql` | 25 | ⊘ |
| KB7 | `read_prices` `.freq` from `inferred_freq` raises on gaps | `D-sql` | 26 | ⊘ |
| KB8 | OANDA adapter cannot construct (`load_markets()`) | `D-oanda` | 27 | ⊘ |
| KB9 | Live Binance streamer dead (ImportError + attr confusion) | `D-live` | — | ⊘ |
| KB10 | Price adapter contract mismatch (`get_all_symbols`) | `D-oanda` *(seam def. M5)* | 27 | ⊘ |
| KB11 | **Orders created with `quantity=0`** (sizing migration unfinished) | M1→M5 | 31 | ☑ |
| KB12 | Screener output computed then discarded (both paths) | `D-screener` | 32 | ⊘ |
| KB13 | Dead + broken `assign_symbol` (screener→strategy bridge) | `D-screener` | 32 | ⊘ |
| KB14 | Orphaned duplicate `EventHandler` in `screener_event_handler.py` | M2 *(delete)* | 32 | ☑ |
| KB15 | **`SMA_MACD` label indexing `[-1]` + string `fillna='False'`** | **M1** | 24/38 | ☑ |
| KB16 | **Config package shadows flat `config.py` → run path unimportable** (VERIFIED) | M1→M2 | 34 | ☑ |
| KB17 | **`config.TIMEZONE` attr access on a dict → AttributeError** (VERIFIED) | M1→M2 | 34/36 | ☑ |
| KB18 | **`record_metrics` called on wrong object** (VERIFIED) | **M1** | 35 | ☑ |
| KB19 | `TradingInterface` cannot construct or create an order | `D-live` | 35 | ⊘ |
| KB20 | **`to_timedelta` returns `None` for upper/week/month** (VERIFIED) | **M1**→M2 | 36 | ☑ |
| KB21 | `check_timeframe` anchors firing to UTC midnight | M2 *(M1 tolerable: golden data is UTC daily)* | 36 | ◑ |
| KB22 | `my_strategies/*` import non-existent `BaseStrategy` | `OUT` | — | ⊘ |
| KB23 | `reporting/performance.py`/`plots.py` removed pandas/plotly APIs + drawdown | M5 | 38 | ☑ |
| KB24 | Portfolio domain exceptions raised with wrong argument | M3 | 37 | ☑ |

**Residual (◑):** **KB21** — `check_timeframe` epoch-anchored & byte-exact on the daily-UTC golden path; weekly/DST anchoring correctness deferred via documented caveat + follow-up todo (`.planning/todos/pending/weekly-anchor-time-parser.md`).

### Security (SEC)

| ID | Defect | Milestone | Parent | Status |
|----|--------|-----------|:--:|:--:|
| SEC1 | DB-table identifier injection in price SQL layer | `D-sql` *(do early if SQL used; CSV path moot)* | 26 | ⊘ |
| SEC2 | Default DB credentials in source | `D-live` | 12 | ⊘ |
| SEC3 | `oanda.cfg` hardcoded relative path | `D-oanda` | — | ⊘ |

### Performance Bottlenecks (PERF)

| ID | Defect | Milestone | Parent | Status |
|----|--------|-----------|:--:|:--:|
| PERF1 | `time.sleep(0.1)` in simulated exchange connect | M5 | 21/28 | ☑ |
| PERF2 | Unseeded `random` in slippage/failure sim | M2 | 5 | ☑ |
| PERF3 | In-memory order storage O(n) nested-dict lookup | M4 | 9 | ☑ |
| PERF4 | Strategy direct access to `price_handler.prices` | M5 | 30/31 | ☑ |

### Fragile Areas (FR)

| ID | Defect | Milestone | Parent | Status |
|----|--------|-----------|:--:|:--:|
| FR1 | `BarEvent.get_last_close` type-branches around data inconsistency | M5 | 3 | ☑ |
| FR2 | `process_events` `get(False)` inside `empty()` race | M3 | 1 | ☑ |
| FR3 | Strategies hold `self.portfolio=None` never populated | M5 *(most files `OUT`)* | 24/31 | ☑ |
| FR4 | Deprecated `fillna(method='ffill')` in OANDA | `D-oanda` | — | ⊘ |
| FR5 | `statistics._to_sql` deprecated `engine.execute` | `D-sql` | 14 | ⊘ |
| FR6 | `load_data` downloads from network in run path | M5 | 30 | ☑ |
| FR7 | Bare `except:` in price accessors → silent `None` | M5 | 30 | ☑ |
| FR8 | `to_megaframe` drops tz-naive symbols + misaligns keys | M5 | 30 | ☑ |
| FR9 | Screener frequency triggering untested | `D-screener` | 32 | ⊘ |
| FR10 | `volume_spyke` SMA window argument ignored | `D-screener` | 32 | ⊘ |

### Scaling Limits (SL)

| ID | Defect | Milestone | Parent | Status |
|----|--------|-----------|:--:|:--:|
| SL1 | In-memory order storage for live (unbounded) | `D-sql` | 18 | ⊘ |
| SL2 | Single `queue.Queue` for all event types (priority) | `D-live` *(not needed for backtest)* | 1/2 | ⊘ |

### Dependencies at Risk (DEP)

| ID | Defect | Milestone | Parent | Status |
|----|--------|-----------|:--:|:--:|
| DEP1 | `tpqoa` for OANDA (unmaintained) | `D-oanda` | — | ⊘ |
| DEP2 | SQLAlchemy `engine.execute` removed in 2.0 | `D-sql` | 14 | ⊘ |

### Missing Critical Features (MF)

| ID | Defect | Milestone | Parent | Status |
|----|--------|-----------|:--:|:--:|
| MF1 | No live order persistence | `D-sql` | 18 | ⊘ |
| MF2 | No compliance layer in order handler | `D-compliance` | — | ⊘ |
| MF3 | No reconnection logic for Binance WebSocket | `D-live` | — | ⊘ |

### Test Coverage Gaps (TC)

| ID | Defect | Milestone | Parent | Status |
|----|--------|-----------|:--:|:--:|
| TC1 | **Entire run path (orchestration/timing/config) untested** (Critical) | **M1** | 40/35 | ☑ |
| TC2 | Price handler + exchange adapters untested | M5 *(CSV/store)* + `D-oanda` *(adapters)* | 30 | ☑ |
| TC3 | Screeners untested | `D-screener` | 32 | ⊘ |
| TC4 | Reporting & statistics untested | M5 | 38 | ☑ |
| TC5 | Live trading system untested | `D-live` | 35 | ⊘ |
| TC6 | Universe untested | M5 | 33 | ☑ |

---

## Section C — Milestone roll-up

Counts include span items in **each** milestone they touch.

| Milestone | Findings | Defects | Notable | Status |
|---|---|---|---|:--:|
| **M1** Ignition | 24*, 31*, 34*, 35*, 36*, 40* | KB11*, KB15, KB16*, KB17*, KB18, KB20*, TD2*, TC1 | The only milestone built without an oracle — keep ruthlessly minimal | ☑ |
| **M2** Foundations | 5, 8, 10, 12*, 13, 15, 17, 18*, 19*, 20, 24→, 34→, 36→ | KB14, KB21, TD4, TD5, PERF2 | Re-freeze numerical oracle here | ☑ |
| **M3** Events & dispatch | 1, 2, 3(rel.), 7*, 11, 37 | KB1, KB24, FR2 | Behavior-preserving | ☑ |
| **M4** Money & txn | 6, 9, 16, 22, 23, 29, 39 | PERF3 | Contains 2nd Critical (#22); value-preserving | ☑ |
| **M5** Validity/metrics/data | 3, 4, 14*, 21, 24→, 27*, 28, 30*, 31→, 33, 38 | KB2, KB23, TD6, TD7, TD10, PERF1, PERF4, FR1, FR3, FR6, FR7, FR8, TC2*, TC4, TC6 | Re-baseline + external cross-validation | ☑ |

`*` = partial / has a deferred or span counterpart. `→` = completes a span started earlier.

**Criticals (3):** #10 → M2 · #22 → M4 · #34 → M1. Only #34 blocks execution outright (it's the
ignition fix). **All three delivered in v1.0** (#10 with the annotation residual noted above).

---

## Section D — Deferred register (not in this program)

All rows below are ⊘ (intentionally out of v1.0; promote with the ROADMAP backlog milestones N+1…N+4).

| Tag | Items | Future milestone |
|---|---|---|
| `D-live` | #7(edge), #12(secrets), #35(TradingInterface/threading), KB3, KB4, KB5, KB9, KB19, MF3, SEC2, SL2, TC5 | Live mode (N+4) |
| `D-sql` | #25, #26, #14(persist), #18(backend), #19(durable), TD1, TD3, KB6, KB7, SEC1, FR5, SL1, DEP2, MF1 | Persistence (N+3) |
| `D-screener` | #32, TD8, KB12, KB13, FR9, FR10, TC3 | Screener / rebalance loop (N+4) |
| `D-compliance` | TD9, MF2 | Compliance layer |
| `D-oanda` | TD11, KB8, KB10, SEC3, FR4, DEP1, TC2(adapters) | Adapter milestone (multi-asset, deferred) |
| `OUT` | #/defects scoped only to `my_strategies/*`: KB22, parts of TD4/TD9/FR3/PERF4 | Resolved by repo relocation |

**Coverage assertion (closed at v1.0):** all 40 findings + all 65 defects appear in Section A/B exactly
once with a milestone or deferred tag. Every in-scope (M1–M5) item is ☑ Done or ◑ (delivered with a
tracked residual: #7, #10, #31, KB21). Every `D-*`/`OUT` item is ⊘ Deferred. Spans entirely inside the
program (`M1→M2`, `M1→M5`) reached their final milestone and are ☑; spans with a deferred half are ☑ on
the in-scope deliverable with the deferred counterpart still listed above.

---

## Section E — Discovered during execution

> Issues found **after** the baseline review (Sections A/B) — surfaced during GSD research, per-phase
> planning, the M1 golden-master capture, or the M5 cross-validation. This is a **delta log**, not a
> re-audit: only items NOT already in Sections A/B belong here. Sections A/B remain the baseline
> coverage contract; this section extends it.

### Triage protocol (mandatory for every new item)

1. **Confirm it's a delta.** Check it isn't already captured (possibly under a different framing) in
   Section A/B. If it is, link to that ID instead of adding a row.
2. **Assign a stable ID.** New finding → `A41`, `A42`, … (continues Section A). New defect → next free
   number in its `CONCERNS.md` category prefix (`TD12`, `KB25`, `FR11`, …), or `DX1`, `DX2`, … if it
   fits no existing category.
3. **Scope-tag it** using the same rules as the baseline: a milestone (`M1`–`M5`, or a span like
   `M1→M5`) **only if** it is genuinely backtest-correctness work; otherwise a deferred tag
   (`D-live` / `D-sql` / `D-screener` / `D-compliance` / `D-oanda`) or `OUT`. **Do not default a new
   item into the phase that found it.**
4. **Get approval before it changes any plan.** Add the row with status ☐ and **flag for owner
   approval**. A new item NEVER silently joins the running phase's scope — that would corrupt the
   golden-master behavior contract (M2–M4 must stay behavior-preserving; M5 is the only
   result-changing milestone).
5. **On approval,** the assigned milestone's plan picks it up; `STATE.md` tracks live status.

### Log

| ID | Item | Severity / category | Milestone | Found by (phase / mechanism) | Status |
|----|------|---------------------|-----------|------------------------------|:--:|
| DX1 | **Golden dataset swapped** — the `data/BTCUSD_1d_ohlcv_01_01_2021-04_06_2026.csv` named across the docs only contained 398 rows / 13 months (2025-05→2026-06) in a CoinMarketCap format (`;`-delimited, descending, `name="2781"`). Replaced by owner with `data/BTCUSD_1d_ohlcv_2018_2026.csv` (Binance-klines: comma, ascending, 3076 daily bars, 2018-01-01→2026-06-03). Doc references (PROJECT/REQUIREMENTS/ROADMAP/REFACTOR-BRIEF/CLAUDE.md) updated to the new filename. | DX — input/data | M1 | Phase 1 `/gsd-discuss-phase` (golden-run config) | ☑ |

**Note on dynamic discovery:** the highest-yield sources here are expected to be the **M1 reference
capture** and **M5 external cross-validation** (vs `backtesting.py` / `backtrader`), not static
re-reading — behavioral/accounting bugs are invisible to the static review that produced Sections A/B.
When such a bug appears, triage it here the same way; do not hotfix it outside its assigned milestone.

# iTrader — Backtest-Correctness Refactor

## What This Is

iTrader is an event-driven algorithmic trading framework (Python 3.13, Poetry) for backtesting
and live execution, where all components communicate through a shared FIFO event queue. This
project is a **brownfield structural refactor** of that framework: make it run **correctly in
backtest mode** end-to-end on one reference strategy (`SMA_MACD`) over a fixed golden dataset,
fixing every structural issue surfaced in the architecture review, and leave behind an engine
whose results are trustworthy and regression-locked.

## Core Value

A single backtest run of `SMA_MACD` on `data/BTCUSD_1d_ohlcv_01_01_2021-04_06_2026.csv` produces
**correct, deterministic, cross-validated numbers** — if nothing else works, the backtest path
must import, run, and yield trustworthy results.

## Requirements

### Validated

<!-- Inferred from existing code + 274 passing component tests. These work today. -->

- ✓ Component-level domains exist and are unit-tested — portfolio (cash/position/transaction/metrics),
  order handler (manager/validator/storage), execution (simulated exchange + matching engine),
  strategy composition scaffolding — existing
- ✓ Event-driven core: `global_queue` + `EventHandler.process_events()` dispatch — existing
- ✓ In-memory order storage backend + `SimulatedExchange`/`MatchingEngine` resting-book matching — existing
- ✓ 274 component tests pass under pytest strictness (`filterwarnings=["error"]`, strict markers) — existing

### Active

<!-- The backtest-correctness program. Organized by milestone M1–M5 (see ROADMAP). -->

**M1 — Ignition + lock the oracle**
- [ ] Run path imports and `SMA_MACD` runs end-to-end on the golden CSV producing a non-trivial trade log + equity curve (#34, #35-backtest)
- [ ] Capture + commit the reference output (trade log, equity curve, final cash/metrics) — the behavioral + numerical oracle
- [ ] Test skeleton: pytest migration scaffold, markers applied, run-path smoke + integration test (#40-skeleton, TC1)
- [ ] Minimal real position sizing in the order/risk seam so orders are no longer `quantity=0` (KB11, #24/#31 minimal)
- [ ] Fix ignition-blocking bugs: `SMA_MACD` `[-1]`/`fillna` (KB15), `record_metrics` target (KB18), `to_timedelta` None (KB20), config import cascade (KB16/KB17/TD2)

**M2 — Foundations**
- [ ] UUIDv7 via `uuid-utils` as the single ID scheme (#10 Critical, #11-ids, #18/#19 ids)
- [ ] Decimal money end-to-end, no float round-trips (#17)
- [ ] `mypy --strict` clean; frozen/typed DTOs; real ABCs replacing Py2 `__metaclass__` (#8, #20)
- [ ] Determinism: seeded RNG + injected clock + flat order index (#5, PERF2)
- [ ] Config collapsed to Pydantic models + `pydantic-settings`; type placement centralized (#12-settings, #13, #15)
- [ ] `time_parser` timing correctness finalized (#36, KB21); delete dead modules (TD4, TD5, KB14)
- [ ] Re-freeze the numerical oracle (float→Decimal precision shift)

**M3 — Event & dispatch core**
- [ ] Immutable events with linkage IDs + `event_id`; enums not strings (#11)
- [ ] Race-free dispatch registry separating routing from ordering (#1, #2, FR2, KB1)
- [ ] Unified domain errors + logging; portfolio exceptions constructed correctly (#7-domain, #37, KB24)
- [ ] Behavioral oracle unchanged

**M4 — Money & transaction correctness**
- [ ] Cash flows through `CashManager` — no float setter bypass (#22 Critical)
- [ ] Atomic transactions with rollback + correct return contract (#16, #23)
- [ ] Order handler facade/manager/storage layering; read path through manager; O(1) order lookup (#6, #9, #29, PERF3)
- [ ] Execution result DTOs frozen/Decimal/real-ABC (#39)
- [ ] Value-preserving against the oracle (any numeric diff explained)

**M5 — Backtest validity, fills, metrics, strategy/data**
- [ ] Fix look-ahead / fill realism / bar-timing; `Bar` struct payload; precomputed resample frames (#21, #3, #4, FR1)
- [ ] Fee/slippage correctness (#28); price-handler split into Provider/Store/Feed, offline-deterministic read path (#30, FR6/FR7/FR8, PERF1/PERF4)
- [ ] Full strategy-declared sizing policy resolved per-portfolio; risk cash checks (#24, #31, TD7, TD10, KB11 final)
- [ ] Reporting/metrics correctness (#14-compute, #38, KB2, KB23, TD6); universe stub (#33)
- [ ] Strategy/data/reporting/universe test coverage (TC2-CSV, TC4, TC6)
- [ ] Engine **cross-validated vs `backtesting.py` + `backtrader`**; final numerical oracle frozen

### Out of Scope

<!-- Deferred to future milestones with explicit tags. Reasoning prevents re-adding. -->

- **Live mode** (`D-live`) — Binance streaming, WebSocket reconnection, restart sync, venue
  reconciliation, `TradingInterface`/API order path, live threading lifecycle, env-only secrets —
  whole separate risk surface; this program is backtest-first
- **SQL persistence** (`D-sql`) — order storage Postgres backend, price store, reporting-to-SQL,
  config JSONB, table-injection hardening — backtest uses in-memory + golden CSV; SQL is a
  live/persistence concern
- **Screener wiring** (`D-screener`) — rebalance loop (screener→universe→strategy) — a feature, not
  a correctness blocker; backtest runs a fixed ticker set
- **Compliance layer** (`D-compliance`) — `long_only`/`short_only` centralization — tied to strategy
  relocation + a future order-handler feature
- **OANDA + Binance adapters** (`D-oanda` / `D-live`) — not on the CSV-backed backtest path
- **`my_strategies/*`** (`OUT`) — contains IP; user relocates it to a separate repo before work
  starts; resolved by removal, not refactor

## Context

- **Authoritative analysis already exists.** Do not re-derive requirements. The source of truth is
  four planning docs: `.planning/REFACTOR-BRIEF.md` (goal/scope/locked decisions/golden-master
  discipline), `.planning/COVERAGE-INDEX.md` (all 105 items → milestone, the coverage contract),
  `.planning/codebase/ARCHITECTURE-REVIEW.md` (40 design findings #1–40), `.planning/codebase/CONCERNS.md`
  (65 concrete defects).
- **Coverage contract.** Every Section A finding (#1–40) and Section B defect (TD/KB/SEC/PERF/FR/SL/DEP/MF/TC)
  maps to a milestone or a DEFERRED/OUT tag. No in-scope item may be left unmapped. Span items
  (`M1→M2`, `M1→M5`) start in one phase and complete in a later one.
- **Three Criticals:** #34 (M1, the only one that blocks execution — run path won't import today),
  #10 (M2, UUIDv7), #22 (M4, cash bypasses CashManager).
- **Codebase map** lives in `.planning/codebase/` (ARCHITECTURE, STACK, STRUCTURE, CONVENTIONS,
  TESTING, INTEGRATIONS).
- **Gap discovery is bounded.** New issues found during research / planning / the M1 capture / the
  M5 cross-validation are logged as deltas in COVERAGE-INDEX §E with a stable ID and a scope tag,
  flagged for owner approval — never silently folded into the running phase (it would corrupt the
  golden-master behavior contract).

## Constraints

- **Tech stack**: Python 3.13, Poetry, event-driven single-`global_queue` architecture — components
  emit events, never call across domains directly
- **Money**: Decimal end-to-end — float for money is a correctness defect (locked decision)
- **IDs**: single UUIDv7 scheme via the Rust-backed `uuid-utils` package (locked decision)
- **Determinism**: seeded RNG + injected clock — runs must be reproducible
- **Golden-master discipline**: M2–M4 are behavior-preserving against the M1 behavioral oracle;
  the numerical oracle re-baselines at exactly two points (after M2, after M5); M5 is the only
  milestone allowed to change results, validated by external cross-validation
- **Test strictness**: `pyproject.toml` sets `filterwarnings=["error"]`, `--strict-markers`,
  `--strict-config` — any unexpected warning fails the suite; every marker must be declared
- **Indentation**: tabs in handler modules; spaces in `config/` and newer modules — match the file
- **Import side effects**: `itrader/__init__.py` initializes `config`, `logger`, `idgen` singletons
  on import
- **Definition of done** (program-level, REFACTOR-BRIEF §1): `SMA_MACD` runs end-to-end producing a
  non-trivial trade log + equity curve; `mypy --strict` clean; no float money; single UUIDv7 scheme;
  deterministic; 274 component tests green (migrated to pytest) + a run-path integration test;
  metrics cross-validated against `backtesting.py` and `backtrader`; final numerical reference frozen

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Money = Decimal end-to-end | Float round-trips defeat careful Decimal math; financial correctness (#17, #22) | — Pending |
| IDs = UUIDv7 via `uuid-utils` | Integer scheme overflows BIGINT; time-ordered, index-friendly, Rust-backed perf (#10) | — Pending |
| Backtest-correctness-first | Live is a separate risk surface; get the engine trustworthy first | — Pending |
| Keep in-house event bus | Need deterministic synchronous ordered dispatch; libraries optimize for the opposite (#1, #2) | — Pending |
| Config → Pydantic + pydantic-settings | Collapses 3300-line over-engineered package; one model is both backtest-dict and live-JSONB path (#12, #13) | — Pending |
| Strategy declares sizing *policy* + SL/TP; order/risk layer resolves per-portfolio qty | Current sizing migration is stranded (qty=0); put the seam in the architecturally-correct place (#24, #31) | — Pending |
| Universe → documented thin stub | Collapse false "dynamic" complexity; screener wired later (#33) | — Pending |
| Golden-master two-layer oracle | Behavioral oracle (trade timing) law M2–M4; numerical oracle re-baselines only after M2 & M5 | — Pending |

## Evolution

This document evolves at phase transitions and milestone boundaries.

**After each phase transition** (via `/gsd-transition`):
1. Requirements invalidated? → Move to Out of Scope with reason
2. Requirements validated? → Move to Validated with phase reference
3. New requirements emerged? → Add to Active (and log deltas in COVERAGE-INDEX §E)
4. Decisions to log? → Add to Key Decisions
5. "What This Is" still accurate? → Update if drifted

**After each milestone** (via `/gsd:complete-milestone`):
1. Full review of all sections
2. Core Value check — still the right priority?
3. Audit Out of Scope — reasons still valid?
4. Update Context with current state

---
*Last updated: 2026-06-04 after initialization*

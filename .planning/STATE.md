---
gsd_state_version: 1.0
milestone: v1.0
milestone_name: milestone
status: ready_to_plan
stopped_at: Phase 03 complete (9/9) — ready to discuss Phase 4
last_updated: 2026-06-05T10:54:12.118Z
last_activity: 2026-06-05
progress:
  total_phases: 8
  completed_phases: 3
  total_plans: 22
  completed_plans: 22
  percent: 38
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-06-04)

**Core value:** A single backtest run of `SMA_MACD` on the golden BTCUSD CSV produces correct, deterministic, cross-validated numbers — the backtest path must import, run, and yield trustworthy results.
**Current focus:** Phase 4 — m3 — event & dispatch core

## Current Position

Phase: 4
Plan: Not started
Status: Ready to plan
Last activity: 2026-06-05

Progress: [██████████] 100%

## Performance Metrics

**Velocity:**

- Total plans completed: 14
- Average duration: — min
- Total execution time: 0.0 hours

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| 01 | 5 | - | - |
| 03 | 9 | - | - |

**Recent Trend:**

- Last 5 plans: —
- Trend: —

*Updated after each plan completion*
| Phase 01 P01 | 12 | 3 tasks | 4 files |
| Phase 01 P02 | 10 | 2 tasks | 1 files |
| Phase 01 P03 | 13 | 3 tasks | 3 files |
| Phase 01 P04 | 22 | 3 tasks | 8 files |
| Phase 01 P05 | 18 | 3 tasks | 4 files |
| Phase 02 P01 | 6 | 2 tasks | 6 files |
| Phase 02 P02 | 4 | 4 tasks | 6 files |
| Phase 02 P03 | 13 | 3 tasks | 11 files |
| Phase 02 P05 | 22 | 3 tasks | 12 files |
| Phase 02 P04 | 20 | 3 tasks | 9 files |
| Phase 02 P06 | 8 | 3 tasks | 7 files |
| Phase 02 P07 | 180 | 4 tasks | 5 files |
| Phase 03 P01 | 3 | 3 tasks | 10 files |
| Phase 03 P02 | 2 | 1 tasks | 4 files |
| Phase 03 P03 | 5 | 2 tasks | 11 files |
| Phase 03 P04 | 9 | 1 tasks | 2 files |
| Phase 03 P05 | 90 | 3 tasks | 42 files |
| Phase 03 P06 | 9 | 1 tasks | 15 files |
| Phase 03 P07 | 18 | 2 tasks | 16 files |
| Phase 03 P08 | 95 | 2 tasks | 51 files |
| Phase 03 P09 | 8 | 3 tasks | 4 files |

## Accumulated Context

### Decisions

Decisions are logged in PROJECT.md Key Decisions table. Recent decisions affecting current work:

- Money = Decimal end-to-end (float money is a correctness defect)
- IDs = single UUIDv7 scheme via `uuid-utils`
- Golden-master two-layer oracle: behavioral oracle (trade timing) is law M2→M4; numerical oracle re-baselines only after M2 (Phase 3) and after M5 (Phase 8)
- Position sizing: strategy declares policy + SL/TP, order/risk layer resolves per-portfolio quantity; M1 implements the minimal seam (Phase 1) so M5 extends rather than replaces it (Phase 7)
- [Phase ?]: D-07: csv/offline feed lives inside PriceHandler, skips SqlHandler + CCXT (Phase 1 Plan 2)
- Plan 01-04: oracle generator pins dataset/window/cash/params as literals; equity sourced from metrics snapshots (not the broken _prepare_data)
- Plan 01-04: DEF-01-B(3) resolved as sizing-before-validation (narrow gate), preserving test_zero_quantity_signal; long-only SELL exit sizes to close the open long
- Plan 01-04: DEF-01-A resolved with minimal float-coercion at the fill->transaction commission boundary (overlaps M4 #22 — reconcile at M4)
- [Phase ?]: Plan 01-05: blessed BTCUSD SMA_MACD oracle frozen into committed test/golden/ and regression-locked by an exact (no-tolerance, D-13) run-path integration test; Phase 01 complete
- [Phase ?]: Plan 01-05: DEF-01-C (no margin/liquidation model — un-liquidated short liability drives total_equity negative) BLESSED into the M1 oracle as current-behavior-to-preserve, deferred to M5
- [Phase ?]: Plan 02-01: mypy --strict gate (make typecheck) stood up with deferral overrides for 7 D-live/D-sql/D-oanda/D-screener modules (D-05/D-06); gate runs but errors deferred to Plan 07
- [Phase ?]: Plan 02-01: UUID Wave 0 scaffold lands red (asserts stdlib uuid.UUID type); money/clock scaffolds co-located with Plan 02 to avoid same-wave scaffold race
- [Phase ?]: Plan 02-03: single UUIDv7 scheme via uuid_utils.compat.uuid7(); integer type-prefix scheme deleted (D-12/D-13/D-14)
- [Phase ?]: Plan 02-03: InMemoryOrderStorage native-UUID keyed + flat Dict[uuid.UUID, Order] index for O(1) lookup (D-14, PERF2); nested dicts retained, scan elimination deferred to M4-06
- [Phase ?]: Plan 02-03: removed int(portfolio_id) coercion in portfolio_handler.on_fill (Rule 1/3 deviation; file unowned by phase-02 plans) to keep suite green post UUID migration
- [Phase ?]: Plan 02-05: 11 dead metaclass bases converted to 3 runtime_checkable Protocols + 8 real ABCs (D-07/D-08b)
- [Phase ?]: Plan 02-05: minimal-conformance ABC carve-out — Universe.get_assets and AbstractStatistics methods left non-abstract (run-path subclasses don't implement them; deep rework deferred M5b #33/#38)
- [Phase ?]: Plan 02-05: SimulatedExchange.configure added (Pitfall 3, D-08) delegating to update_config; conforms to AbstractExchange Protocol. Strategy.calculate_signal now @abstractmethod (#20 real enforcement)
- [Phase ?]: Plan 02-05: mypy gate 316->906 is unmasked pre-existing untyped-def debt (not regression), deferred to Plan 07; SignalEvent.strategy_id int->StrategyId retype noted for Plan 07
- [Phase ?]: Plan 02-04: money Decimal at entity boundaries; float execution+sizing untouched (M4)
- [Phase ?]: Plan 02-04: portfolio.cash Decimal end-to-end (#17 round-trip removed); aggregate read-props kept float; cash via CashManager + Decimal aggregates deferred to M4 #22
- [Phase ?]: Plan 02-04: DEF-02-04-A golden numeric oracle drift (behavioral oracle preserved, only numeric cols) deferred to Pattern E + owner-gated post-M2 numerical re-baseline
- [Phase ?]: Plan 02-07: owner approved phase-close gate — D-15 numeric tolerance (rtol=1e-6, atol=5e-2 / 5c) accepted, identity+equity columns exact, time-boxed to M2b numerical re-freeze (Phase 3 SC4)
- [Phase ?]: Plan 02-07: frozen=True/slots=True on PingEvent/BarEvent/PortfolioUpdateEvent/ScreenerEvent (M2-03); SignalEvent/FillEvent/OrderEvent left mutable (runtime mutation); make typecheck clean across D-05 in-scope package (Option 2 overrides for deferred subsystems)
- [Phase 03]: Plan 03-01: D-17 inertness reference captured from unmodified M2a-end HEAD (final_equity 53229.685, 134 trades) — byte-exact baseline for the 03-09 oracle re-freeze gate
- [Phase 03]: Plan 03-01: pydantic ^2.13 + pydantic-settings ^2.14 added as lockfile-tracked Poetry deps (unblocks config collapse 03-05)
- [Phase 03]: Plan 03-01: 5 Wave-0 characterization stubs (M2-06..10) under current test/ tree, skip/importorskip-gated, move into tests/unit/... at 03-08; suite 300 pass / 11 skip / 1 xfail
- [Phase ?]: Plan 03-02: four dead modules purged (legacy_config, outils/profiling, outils/strategy, events_handler/screener_event_handler) via D-13 mechanical-delete, zero importers re-verified; flat config.py shadow left for 03-05
- [Phase ?]: Plan 03-03: FillStatus + 4 manager enums relocated to core/enums as class-based with _missing_ case-insensitive parse; string->enum maps deleted (D-04/D-05); OrderStatus/FillStatus/TransactionState kept DISTINCT; behavioral oracle byte-exact
- [Phase 03]: Plan 03-04: check_timeframe epoch-aligned via a single replaceable _aligned seam (D-06/D-07); to_timedelta case-insensitive + week + month-specific raise + None-guard + raise-on-unknown (D-08); dead helpers deleted; behavioral oracle byte-exact (D-18)
- [Phase ?]: Plan 03-05: config/ collapsed to Pydantic v2 (5 domain models + models.py aggregate) + pydantic-settings Settings with fail-loud required-no-default SecretStr database_url (M2-06); flat config.py shadow + importlib shim + getters/registry/provider/validator/schema deleted (D-01); FORBIDDEN_SYMBOLS concat bug fixed in core/constants.py; consumers construct models directly; behavioral oracle byte-exact, mypy --strict clean
- [Phase ?]: Plan 03-06: portfolio_handler reorganized into position/ transaction/ cash/ metrics/ subdomain packages via history-preserving git mv (D-11); package __init__ re-exports + enum re-exports from core.enums keep consumer paths short; suite/typecheck/behavioral-oracle green, zero behavior change
- [Phase ?]: Plan 03-08: test/ -> tests/ via history-preserving git mv split by TYPE (unit mirrors package, integration holds cascade/smoke/oracle); folder-derived TYPE markers in layered conftests, single registration home (pyproject markers)
- [Phase ?]: Plan 03-08: 29 unittest.TestCase files converted to pytest one-file-per-commit at constant 346 collected; filterwarnings=['error'] intact (leaks fixed via yield-teardown queue drains); D-16/D-17 oracle numeric re-freeze deferred to 03-09
- [Phase ?]: Plan 03-08: Rule 1 fix - Task 1 commit 33c3281 recorded git-mv renames but dropped tracked-file content edits (git add aborted on stale 'test' pathspec); corrected in 6a623ae so committed HEAD collects 346 on fresh checkout
- [Phase ?]: Plan 03-09: numerical oracle re-frozen byte-exact at M2b end-state (final_equity 53229.68512642488, replacing stale M1 float 53229.75); D-15 tolerance + DEF-02-08-A xfail closed; numeric cols check_exact=True; behavioral identity unchanged (D-18); one of PROJECT.md's two sanctioned numeric re-baseline points
- [Phase ?]: Plan 03-09: D-17 inertness gate byte-exact (behavioral AND numeric) vs M2A-INERTNESS-REF before re-freeze — M2b structural changes proven numerically inert, no time_parser firing shift

### Pending Todos

None yet.

### Blockers/Concerns

- Phase 1 first work is Critical #34: the run path does not import today (the only Critical that blocks execution). Everything downstream depends on resolving it, then capturing + committing the reference output.
- Golden-master gates are hard phase-boundary criteria: end of Phase 3 (re-freeze numerical oracle), Phases 4–5 behavior/value-preserving, end of Phase 8 (cross-validate + freeze final oracle).
- New issues found during execution go to COVERAGE-INDEX §E (delta log) with owner approval — never silently folded into the running phase.

## Deferred Items

Items explicitly out of this program's scope (see PROJECT.md Out of Scope / COVERAGE-INDEX §D):

| Category | Item | Status | Deferred At |
|----------|------|--------|-------------|
| D-live | Live mode (Binance streaming, TradingInterface, live threading, secrets) | Deferred | Program start |
| D-sql | SQL persistence backends (order/price/reporting/config) | Deferred | Program start |
| D-screener | Screener / rebalance loop wiring | Deferred | Program start |
| D-compliance | Compliance layer (long_only/short_only) | Deferred | Program start |
| D-oanda | OANDA + Binance adapters | Deferred | Program start |
| OUT | `my_strategies/*` (relocated to separate repo by user) | Out-of-band | Program start |

## Session Continuity

Last session: 2026-06-05T10:38:09.573Z
Stopped at: Completed 03-09-PLAN.md
Resume file: None

---
phase: 02-m2a-identity-money-determinism
plan: 07
subsystem: events / type-gate / oracle-test
status: CHECKPOINT (paused — Task 4 owner phase-close gate)
tags: [frozen-events, mypy-strict, oracle-tolerance, M2-03, D-15, in-scope-clean]
requires: ["02-03", "02-04", "02-05", "02-06"]
provides:
  - "frozen/slots immutable hot-path events (M2-03, Pattern F)"
  - "make typecheck (mypy --strict) clean across the D-05 in-scope package (M2-03)"
  - "D-15 oracle split: behavioral identity EXACT + numeric bounded-tolerant"
affects:
  - itrader/events_handler/event.py
  - test/test_integration/test_backtest_oracle.py
  - test/test_events/test_event_immutability.py
  - "~60 in-scope itrader modules (catalogued below — Task 2 annotation pass)"
  - pyproject.toml
tech-stack:
  added: []
  patterns:
    - "@dataclass(frozen=True, slots=True) on immutable events"
    - "identity-EXACT / numeric-TOLERANT oracle split"
    - "documented ignore_errors overrides for out-of-scope deferred subsystems (Option 2)"
    - "Decimal/float coercion only at existing M2a boundaries; behavior-preserving"
key-files:
  created:
    - test/test_events/test_event_immutability.py
  modified:
    - itrader/events_handler/event.py
    - test/test_integration/test_backtest_oracle.py
    - pyproject.toml
    - "~60 in-scope itrader modules (Task 2)"
decisions:
  - "Freeze only genuinely-immutable events: PingEvent, BarEvent, PortfolioUpdateEvent, ScreenerEvent"
  - "OrderEvent left MUTABLE — price/quantity rewritten by MatchingEngine.modify (discovered at runtime)"
  - "SignalEvent + FillEvent left MUTABLE — documented downstream mutation"
  - "D-15 tolerance set to rtol=1e-6, atol=5e-2 (5 cents) — just above observed ~2.7e-2 M2a drift"
  - "Task 2 = Option 2 (owner): clean in-scope set; out-of-scope debt deferred via documented overrides"
  - "SignalEvent.strategy_id + OrderEvent.strategy_id int->StrategyId (02-05 carry-over) landed"
  - "portfolio_id int<->PortfolioId(UUID) inconsistency bridged with documented unions; full retype deferred"
metrics:
  duration: ~3 h (Tasks 1-3 + the full Task 2 in-scope annotation pass)
  completed: 2026-06-04
---

# Phase 2 Plan 7: Strict-Gate + Frozen-Events + Oracle-Gate Consolidation Summary

**One-liner:** Froze the genuinely-immutable hot-path events (`frozen=True/slots=True`), drove
`make typecheck` (mypy --strict) to **clean across the entire D-05 in-scope package** under the
owner's Option-2 scope (out-of-scope debt documentedly deferred), and split the backtest oracle
into behavioral-identity-EXACT + numeric-bounded-tolerant (D-15). Paused at the owner-gated
Task 4 phase-close checkpoint.

## Status: CHECKPOINT — Tasks 1, 2, 3 complete; paused at Task 4 (owner phase-close gate)

## Completed Work

### Task 1 — frozen/slots immutable events (M2-03, Pattern F) ✅ (TDD)
- **RED** (`ffe2a3c`): added `test/test_events/test_event_immutability.py`.
- **GREEN** (`227dab3`): `@dataclass(frozen=True, slots=True)` on **PingEvent, BarEvent,
  PortfolioUpdateEvent, ScreenerEvent**. SignalEvent/FillEvent/OrderEvent left mutable (runtime
  mutation verified). M3 event-id boundary untouched. `test/test_events -q` → 25 passed.

### Task 3 — D-15 oracle split (behavioral-EXACT + numeric-TOLERANT) ✅ (`e9af665`)
- Identity columns (`entry_date, exit_date, side, pair`) + equity timestamp grid +
  `final_cash/trade_count/final_equity` asserted `check_exact=True`.
- Numeric columns within `rtol=1e-6, atol=5e-2` (5 cents — just above observed ~2.732e-2 worst
  drift), each inline-flagged `# D-15 transitional — removed + re-frozen EXACT at M2b (Phase 3 SC4)`.
- Golden CSVs NOT overwritten (numeric re-baseline stays owner-gated, Phase 3).

### Task 2 — make typecheck clean across the D-05 in-scope package (M2-03) ✅ (`d85729a`)

Owner decision **Option 2 — scope down + documented overrides**. `make typecheck` went from
**922 errors / 83 files → 0 errors / 157 files clean**.

**Mandated items landed:**
- `SignalEvent.strategy_id` `int`→`StrategyId` (02-05 carry-over); `OrderEvent.strategy_id` too.
- Dead local `old_status` at `order.py` removed (Pylance-flagged).

**In-scope annotation pass (~60 modules, all behavior-preserving):** events_handler, core/enums,
core/exceptions, full config domain (core/portfolio/system/exchange + `__init__` exports), logger,
outils, universe, full portfolio_handler module (portfolio + 4 managers + handler + transaction +
position + validators), full execution_handler (handler, simulated, matching_engine, fee/slippage
models, result_objects), strategy_handler (base, SMA_MACD, empty, strategies_handler, sizers, risk,
sltp), the csv price feed (`data_provider.py` + `price_handler/base.py` + exchange/base), reporting
base + performance, trading_system backtest engine + ping_generator.

**Documented `ignore_errors` overrides (out-of-scope debt, each commented):**
`my_strategies.*` (separate repo), `legacy_config`, `postgresql_storage` (D-sql),
`config.exchange.schema` (dormant validator vs old API), `reporting.statistics`/`engine_logger`/
`plots` (D-sql/viz, off backtest path), `events_handler.screener_event_handler` (dead D-screener),
plus the existing D-live/D-sql/D-oanda/D-screener set. Third-party stub-ignores: pandas, pytz,
scipy, plotly, sklearn, statsmodels, tqdm, yaml.

**Verify:** `make typecheck` exits 0 (157 files). `make test` → 299 passed. Oracle → 1 passed.

## Deviations from Plan

### [Rule 1 — Bug avoided] OrderEvent is not immutable
- Found during Task 1 GREEN; OrderEvent left mutable, test updated. Commit `227dab3`.

### [Rule 1 — Bugs fixed in dormant code during Task 2]
- `ExecutionErrorCode.TIMEOUT` member added — `ExecutionTimeoutError` referenced a non-existent
  enum value (AttributeError at raise-time). `core/enums/execution.py`. Commit `d85729a`.
- `super.__init__(...)` → `super().__init__(...)` in `Empty_strategy` (missing parens → TypeError).
- `raise NotImplemented(...)` → `raise NotImplementedError(...)` in `full_event_handler` (NotImplemented
  is not an exception).
- `time_parser.format_timeframe` / `outils/strategy` module-level `@staticmethod` misuse → None-guards
  + decorator cleanup.
- All caught by mypy, fixed inline, suite stays green.

### [Scope — owner-approved Option 2] portfolio_id int↔PortfolioId
- The 02-05 portfolio_id migration is incomplete: events carry `int` portfolio_id while entities
  assign a UUID `PortfolioId`. Bridged at boundaries with documented `PortfolioId | int` unions and a
  `PortfolioIdLike` exception alias rather than forcing the full retype (Rule 4 — deferred, not
  mandated by Task 2). Documented inline at each seam.

## CHECKPOINT — Task 4: Phase gate (`checkpoint:human-verify`, gate="blocking", OWNER-GATED)

All automated verification is complete and green. Awaiting owner "approved" to close the phase
(NOT auto-closed). Verification results gathered for owner review:

| Gate | Result |
|------|--------|
| `make typecheck` (mypy --strict, in-scope) | **PASS** — exit 0, 157 files, 0 errors |
| `make test` (full suite) | **PASS** — 299 passed |
| `poetry run pytest test/test_integration/test_backtest_oracle.py -x` | **PASS** — 1 passed |
| Behavioral oracle (trade timing + sides + sequence) | **UNCHANGED** from M1 |

**D-15 tolerance magnitude for owner review:** `rtol=1e-6`, `atol=5e-2` (5 cents), set just above
the worst observed M2a Decimal drift (~2.732e-2). Documented inline with the M2b re-freeze note
(`# D-15 transitional — removed + re-frozen EXACT at M2b (Phase 3 SC4)`). Identity columns
(`entry_date, exit_date, side, pair`), equity timestamp grid, and `final_cash/trade_count/final_equity`
remain `check_exact=True`.

**Final reference numbers (frozen golden, unchanged):** final_equity **53229.75**, final_cash
**53229.75**, **trade_count 134**, total_realised_pnl ≈ 43229.70 (drifts 9.563e-3, within tolerance).

**Owner question (per plan how-to-verify step 4):** is the 5-cent tolerance tight enough to catch
dollar-level money bugs yet loose enough for sub-cent Decimal/quantization drift? It is bounded,
documented, and time-boxed to M2b.

**Resume signal:** Type "approved" to close the phase, or describe the tolerance/behavior concern.

## Self-Check: PASSED
- FOUND: itrader/events_handler/event.py
- FOUND: test/test_events/test_event_immutability.py
- FOUND: test/test_integration/test_backtest_oracle.py
- FOUND: pyproject.toml ([tool.mypy] overrides extended — Option 2)
- FOUND commits: ffe2a3c (RED), 227dab3 (GREEN), e9af665 (oracle), d85729a (typecheck clean)
- VERIFIED: `make typecheck` exit 0 (157 files); `make test` 299 passed; oracle 1 passed

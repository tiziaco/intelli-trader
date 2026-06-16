---
phase: 04-liquidation-cross-validation-re-baseline
plan: 03
subsystem: portfolio_handler (isolated-margin liquidation engine)
tags: [liquidation, LIQ-01, LIQ-02, LIQ-03, D-01-CORR, D-03-CORR, D-04, D-05, D-07, oracle-dark]
requirements-completed: [LIQ-01, LIQ-02, LIQ-03]
dependency-graph:
  requires:
    - "04-00: Wave-0 unit stubs (test_liquidation.py, test_liquidation_reconcile.py) un-skipped + filled"
    - "04-01: OrderTriggerSource.LIQUIDATION + Instrument/TradingRules.liquidation_fee_rate (default 0)"
    - "04-02: WR-04 assert-before-release call-order on the margin-lock seam (the WB the floor reads)"
  provides:
    - "BAR-route per-position liquidation breach check + forced-close mint/emit (PortfolioHandler)"
    - "set_order_storage write-seam (analog of set_universe) wired in compose.py + live_trading_system.py"
    - "Corrected isolated liq-price + explicit min(loss+penalty, WB) cap (closes DEF-01-C)"
  affects:
    - "04-04 e2e author — the LOCKED wiring is set_order_storage at compose.py + live parity; full_event_handler.py untouched; no execution-time fork remains"
tech-stack:
  added: []
  patterns:
    - "NARROW INJECTED WRITE-SEAM (set_order_storage) mirroring set_universe — NOT a raw handler-to-handler call, NOT an ORDER-route enqueue"
    - "direct portfolio-side FillEvent(EXECUTED) on the BAR route at time=bar_time (D-04 — settle on breach bar, not next-bar-open)"
    - "deterministic (ticker, open_time, position_id) breach sort for byte-identical double-run"
key-files:
  created: []
  modified:
    - "itrader/portfolio_handler/portfolio_handler.py (4 SPACES — liq math + breach pass + mint/emit + set_order_storage seam)"
    - "itrader/trading_system/compose.py (TABS — set_order_storage injection)"
    - "itrader/trading_system/live_trading_system.py (4 SPACES — live-parity set_order_storage)"
    - "tests/unit/portfolio/test_liquidation.py (LIQ-01/02 unit tests filled)"
    - "tests/unit/order/test_liquidation_reconcile.py (LIQ-03 reconcile tests filled)"
decisions:
  - "portfolio_handler.py is 4-SPACE indented (the file's actual convention) — the plan/interfaces said TABS; matched the file, never normalized (CLAUDE.md tab/space hazard)"
  - "compose.py is TAB-indented (matched the file); live_trading_system.py is 4-SPACE (matched the file) — the plan said both 4-SPACE"
  - "Forced-close Order mints a FRESH StrategyId (idgen.generate_strategy_id) — Position carries no strategy_id; a forced deleverage is owned by no strategy, the LIQUIDATION trigger source distinguishes it in the trade log"
  - "_is_breached takes the liq_price directly (computed once by the breach pass) — not recomputed per call"
metrics:
  duration-min: 28
  completed: 2026-06-16
  tasks: 3
  files: 5
---

# Phase 4 Plan 03: Isolated-Margin Liquidation Engine Summary

The heart of Phase 4: a bar-close maintenance-margin breach now force-closes the position at
the corrected isolated liquidation price (D-01-CORR), loss EXPLICITLY capped at the allocated
isolated margin WB (D-03-CORR/D-07 — closes DEF-01-C), penalty charged in commission (D-05),
reconciling EXECUTED→FILLED via a real `OrderTriggerSource.LIQUIDATION`-tagged Order registered
in the injected `order_storage` (the `set_order_storage` write-seam, LIQ-03) with NO new
`FillStatus` — deterministically and oracle-dark (SMA_MACD byte-exact at 134 / 46189.87730727451).

## What Was Built

**Task 1 — liq math + capped loss + deterministic breach collection (LIQ-01/02):**
- `_isolated_liq_price` — corrected D-01-CORR: LONG `(entry − WB/|size|)/(1 − MMR)`, SHORT
  `(entry + WB/|size|)/(1 + MMR)`; hand-verified long 80.808080… / short 118.811881… for the
  worked case (Entry=100, |size|=200, WB=4000, MMR=0.01). Decimal end-to-end, no `Decimal(float)`.
- `_liquidation_penalty` = `fee_rate × |size| × liq_price` (D-05, rides `FillEvent.commission`).
- `_capped_realized_loss` = `min(realized_loss_magnitude + penalty, WB)` — the EXPLICIT clamp
  (D-03-CORR/D-07). Unit test asserts the loss-magnitude alone is < WB at the maintenance liq
  price (buffer retained, clamp not by-construction) AND that a fat fee makes it TRIGGER (≤ WB).
- `_collect_breaches` / `_collect_breaches_over_prices` — post-carry breach pass (D-02 placement),
  flags LONG `close <= liq` / SHORT `close >= liq`, skips spot/unlevered (`wb <= 0`) and
  non-positive marks, sorts `(ticker, open_time, position_id)` (Pitfall 3). Commits `bdb86e7` (RED),
  `6d4c285` (GREEN).

**Task 2 — set_order_storage seam + mint/emit forced-close on the BAR route (LIQ-03/D-04):**
- `set_order_storage(order_storage)` + `self._order_storage` field on PortfolioHandler — the
  NARROW INJECTED WRITE-SEAM analog of `set_universe`.
- `_liquidate_position` — mints a REAL opposite-side `Order` (SELL closes a long / BUY a short,
  qty = `|net_quantity|`), tags it `OrderTriggerSource.LIQUIDATION`, registers it via
  `order_storage.add_order` (Pitfall 4 — without this the reconcile early-returns and the mirror
  never reaches FILLED), and emits `FillEvent.new_fill("EXECUTED", …, price=liq_price,
  commission=penalty, time=bar_time)` DIRECTLY on the queue — NOT routed through
  ExecutionHandler/SimulatedExchange (D-04/Pitfall 6). The liq price is quantized to the
  instrument price scale ONLY here, at the FillEvent boundary (Pitfall 5).
- `_run_liquidation_pass` wired into `update_portfolios_market_value` AFTER the mark+carry loop.
- `compose.py` (TABS) + `live_trading_system.py` (4 SPACES) inject the SAME `order_storage`
  instance the OrderHandler/ReconcileManager hold. `full_event_handler.py` untouched. Commits
  `9966c85` (RED), `130533a` (GREEN).

**Task 3 — byte-exact oracle + determinism guard (proof gate, no code change):**
- The liquidation engine + the `set_order_storage` injection are oracle-dark on the SMA_MACD spot
  path (no locked margin / liquidation_fee_rate=0 → zero breaches → never written). Oracle held
  byte-exact; double-run identical.

## Verification

- `pytest tests/unit/portfolio/test_liquidation.py tests/unit/order/test_liquidation_reconcile.py` → 12 passed.
- `pytest tests/integration/test_backtest_oracle.py` → 3 passed (byte-exact 134 / 46189.87730727451, D-11); double-run identical.
- `pytest tests/unit/portfolio/` → 262 passed; `pytest tests/unit/order/` → 223 passed (no regression).
- `mypy --strict itrader` → Success, no issues in 163 source files.
- e2e liquidation stubs (`forced_liq_long`/`forced_liq_short`/`levered_long_into_liquidation`) collect cleanly → 3 skipped (04-04 fills them).
- No `Decimal(float)` in the new math (Pitfall 5).

## LOCKED Wiring (for the 04-04 e2e author)

The `set_order_storage` write-seam is injected at `compose.py` (immediately after the
`OrderHandler` construction, TAB-indented) and at `live_trading_system.py` (after its
`OrderHandler`, 4-SPACE) with the SAME `order_storage` instance — mirroring `set_universe`.
`full_event_handler.py` is untouched (it only receives wired handlers). No execution-time fork
remains: the liquidation forced-close settles on the breach bar via the direct portfolio-side
`FillEvent`, never an ORDER-route enqueue.

## Deviations from Plan

### [Rule 1 — Indentation correction] portfolio_handler.py is 4-SPACE, not TABS
- **Found during:** Task 1
- **Issue:** The plan and `<interfaces>` repeatedly say `portfolio_handler.py` is TABS. The file
  is actually 4-SPACE indented (verified: zero leading-tab lines; all `def`s start with 4 spaces).
- **Fix:** Matched the file's real convention (4 SPACES) per the CLAUDE.md tab/space hazard rule
  ("ALWAYS match the indentation of the file being edited; never normalize"). compose.py IS TABS
  (matched); live_trading_system.py IS 4-SPACE (matched) — the plan said both were 4-SPACE.
- **Files modified:** itrader/portfolio_handler/portfolio_handler.py, itrader/trading_system/compose.py
- **Commit:** 6d4c285, 130533a

### [Plan-premise clarification] forced-close Order strategy_id
- The plan says mint "the same strategy_id … as the position". `Position` carries NO `strategy_id`
  field. Resolved within scope: the forced-close mints a fresh `StrategyId` via
  `idgen.generate_strategy_id()`. A forced deleverage is owned by no strategy; the
  `OrderTriggerSource.LIQUIDATION` tag is what distinguishes it from a strategy-driven close in the
  trade log. The fill→order audit chain stays real (the order is registered and resolvable by
  `get_order_by_id(fill.order_id, portfolio_id)`).

## Threat-Model Coverage

- **T-04-03-NEG (mitigate):** explicit `min(loss+penalty, WB)` clamp; unit test asserts loss ≤ WB
  for a fat-penalty case. Held.
- **T-04-03-DET (mitigate):** deterministic `(ticker, open_time, position_id)` sort; fills stamped
  `time=bar_time`; oracle double-run identical. Held.
- **T-04-03-PREC (mitigate):** Decimal end-to-end via `to_money`/string entry; quantize only at the
  FillEvent price boundary; no `Decimal(float)`. Held.
- **T-04-03-MIR (mitigate):** real forced-close Order registered in the INJECTED order_storage;
  reconcile reaches FILLED; unregistered-order no-op guard asserted (Pitfall 4). Held.
- **T-04-03-SEAM (mitigate):** narrow injected `set_order_storage` seam (analog of set_universe) —
  NOT a raw cross-domain call, NOT an ORDER-route enqueue; same order_storage instance. Held.
- **T-04-03-ORC (mitigate):** default-off → zero breaches; injection oracle-dark; byte-exact gate. Held.
- **T-04-03-LA (mitigate):** settle on the BREACH bar via direct queue emission, bar_time stamp —
  never routed through ExecutionHandler. Held.
- **T-04-03-SC (accept):** no package installs. N/A.

## Known Stubs

None — the liquidation engine is fully implemented. The e2e liquidation leaves
(`tests/e2e/forced_liq_*`, `levered_long_into_liquidation`) remain Wave-0 skipped stubs by design,
filled by 04-04 (documented in 04-00-SUMMARY).

## Self-Check: PASSED

Files (all present):
- itrader/portfolio_handler/portfolio_handler.py — contains `OrderTriggerSource.LIQUIDATION`, `set_order_storage`, `get_locked_margin_for`
- itrader/trading_system/compose.py — contains `set_order_storage`
- itrader/trading_system/live_trading_system.py — contains `set_order_storage`
- tests/unit/portfolio/test_liquidation.py, tests/unit/order/test_liquidation_reconcile.py

Commits (all in git log):
- bdb86e7 (Task 1 RED), 6d4c285 (Task 1 GREEN)
- 9966c85 (Task 2 RED), 130533a (Task 2 GREEN)

## TDD Gate Compliance

Both behavior-adding tasks followed RED→GREEN: a `test(...)` commit precedes each `feat(...)`
commit (bdb86e7→6d4c285, 9966c85→130533a). RED was proven failing before GREEN in both cases.

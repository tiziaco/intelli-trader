---
phase: 07-m5b-sizing-policy-metrics-universe-coverage
plan: 04
subsystem: strategy-contract
tags: [pure-alpha, signal-intent, typed-signal-event, fan-out, oracle-inert, d-12]
requires:
  - "07-01 (SizingPolicy/SignalIntent/TradingDirection vocabulary in core/sizing.py)"
provides:
  - "Pure Strategy ABC: abstract generate_signal(ticker, bars) -> SignalIntent | None (D-12, M5-06 contract clause)"
  - "buy()/sell() intent sugar returning SignalIntent (to_money SL/TP entry preserved)"
  - "Typed SignalEvent: sizing_policy/direction/allow_increase/max_positions/exit_fraction/sltp_policy — strategy_setting dict deleted everywhere (D-01)"
  - "Handler-side SignalEvent construction + per-portfolio fan-out in StrategiesHandler.calculate_signals (relocated from Strategy._generate_signal)"
  - "D-08 LONG_SHORT registration rejection in add_strategy"
  - "SMA_MACD/empty_strategy converted value-identically with golden typed declarations (FractionOfCash 0.95, LONG_ONLY, allow_increase=False)"
affects:
  - 07-05 (order layer reads the typed signal fields; deletes position_sizer/ incl. the variable_sizer interim fix)
  - 07-07 (signal-path tests reuse the typed create_mock_signal harness defaults)
tech-stack:
  added: []
  patterns:
    - "Pure-function strategy contract: intent in, event construction handler-side (the #24 boundary)"
    - "WR-12 sparse-ticker guard precedes generate_signal (handler stamps price from event.bars[ticker].close)"
key-files:
  created: []
  modified:
    - itrader/events_handler/events/signal.py
    - itrader/strategy_handler/base.py
    - itrader/strategy_handler/strategies_handler.py
    - itrader/strategy_handler/SMA_MACD_strategy.py
    - itrader/strategy_handler/empty_strategy.py
    - itrader/strategy_handler/position_sizer/variable_sizer.py
    - tests/unit/strategy/test_strategy.py
    - tests/unit/order/test_on_signal.py
    - tests/unit/order/test_order_handler.py
    - tests/unit/order/test_stop_limit_orders.py
    - tests/unit/order/test_order_manager.py
    - tests/unit/portfolio/transaction/test_transaction_init.py
    - tests/unit/events/test_event_immutability.py
    - tests/unit/events/test_events.py
decisions:
  - "Absent-SL/TP default preserved exactly: SignalIntent carries None; the handler stamps to_money(0) == Decimal('0') at SignalEvent construction — byte-identical to the legacy _generate_signal(sl=0, tp=0) path"
  - "buy()/sell() convert SL/TP via to_money at intent construction (the same single D-04 string-path entry the legacy code applied at event construction) so SignalIntent honestly carries Decimal | None"
  - "D-08 rejection raises ValueError('LONG_SHORT requires the margin/liquidation milestone — declare LONG_ONLY or SHORT_ONLY (D-08)') — plain ValueError, loud and test-locked; no new exception type minted"
  - "trading_interface.py needed NO change: it constructs OrderEvent directly (never SignalEvent) — the plan's premise about its explicit-quantity SignalEvent path was stale"
  - "M5-06 calculate_signal clause delivered as generate_signal @abstractmethod; full M5-06 completion still rides 07-05 (resolver wiring)"
metrics:
  duration: "~20 min"
  completed: "2026-06-07"
  tasks: 3
  tests-added: 8
---

# Phase 7 Plan 04: Strategy Contract — Pure Alpha + Typed SignalEvent Summary

Strategies are now pure alpha functions returning SignalIntent; StrategiesHandler owns stamping, typed policy attachment, per-portfolio fan-out, and enqueueing; the untyped strategy_setting dict is dead in every file — and the full oracle is byte-exact (behavioral AND numeric), proving the entire D-12 rewrite inert.

## Tasks Completed

| Task | Name | Commits | Key Files |
|------|------|---------|-----------|
| 1 | SignalEvent retype — typed policy fields replace strategy_setting | 5cd6948 | itrader/events_handler/events/signal.py + 8 constructor sites |
| 2 | Pure Strategy ABC + handler-side fan-out + SMA_MACD/empty_strategy conversion | 234d824 | itrader/strategy_handler/{base,strategies_handler,SMA_MACD_strategy,empty_strategy}.py |
| 3 | Intent-contract tests + inertness gate | ba4fc20 | tests/unit/strategy/test_strategy.py |

## What Was Built

**SignalEvent (signal.py, spaces):** `strategy_setting: dict[str, Any]` deleted; the event now carries `sizing_policy: SizingPolicy`, `direction: TradingDirection`, `allow_increase: bool = False`, `max_positions: int = 1`, `exit_fraction: Decimal = Decimal("1")`, `sltp_policy: SLTPPolicy | None = None`. All typed imports come from `itrader.core.sizing` only (Pitfall 3 — no order_handler import; cycle-safe). frozen/slots/kw_only and the `field(default=EventType.SIGNAL, init=False)` tag untouched.

**Strategy ABC (base.py, tabs):** `generate_signal(ticker, bars) -> SignalIntent | None` is the @abstractmethod (replaces calculate_signal, D-12 name). `__init__` requires `sizing_policy` (no default — honest contract) and accepts `direction`/`allow_increase`/`max_positions` keywords; the `max_allocation` float kwarg is dead. `global_queue`, `last_event`, `last_time()`, `_generate_signal`, `setting_to_dict` all deleted; `subscribed_portfolios` stays (handler reads it for fan-out); `to_dict` serializes the typed declarations. `buy()`/`sell()` are thin sugar returning `SignalIntent` with optional sl/tp/exit_fraction passthrough — no queue, no event.

**StrategiesHandler (tabs):** `calculate_signals` keeps the timeframe gate and push-based window; the relocated construction stamps `time=event.time`, `price=to_money(bar.close)`, parses `OrderType(strategy.order_type)`, attaches policy/direction/allow_increase/max_positions from the strategy object and `exit_fraction`/SL/TP from the intent, fans out per subscribed portfolio, enqueues. The WR-12 sparse-ticker guard (`event.bars.get(ticker) is None` -> log + skip) now precedes `generate_signal`. Dead `assign_symbol` deleted (#31); `strategy.global_queue = ...` assignment deleted; `add_strategy` rejects `TradingDirection.LONG_SHORT` loudly (D-08 — inert, golden declares LONG_ONLY). `get_strategies_universe` stays.

**SMA_MACD (tabs, value-identical per RESEARCH Pattern 4/A2):** `last_time = bars.index[-1]` replaces `self.last_time()`; indicator windows/triggers byte-for-byte; triggers `return self.buy(ticker)`/`self.sell(ticker)`; fall-through returns None; the commented-out short block stays dead. Constructor declares `FractionOfCash(Decimal("0.95"))` (string-path literal, Pitfall 1), `TradingDirection.LONG_ONLY`, `allow_increase=False` (D-03/D-08/D-10 declarations — enforcement comes with 07-05).

**Tests (8 new in test_strategy.py):** pure-function tests on a hand-engineered 120-bar bullish SMA/MACD crossover frame (construction documented and verified against the ta library: uptrend for the SMA filter, 8-bar dip for negative MACD hist, +30 final-bar bounce for the >= 0 flip); too-short frame -> None; golden-declaration assertions; sugar tests; handler fan-out with a real StrategiesHandler + stub feed (1 portfolio -> 1 stamped event, 2 -> 2); WR-12 guard; D-08 rejection.

## Verification Results

- `tests/unit/strategy` + `tests/unit/order` + `tests/unit/events`: green
- `make test`: 652 passed
- `make typecheck` (mypy --strict): clean, 139 files
- `poetry run pytest tests/integration/test_backtest_oracle.py -q`: **2 passed — byte-exact** (behavioral identity AND numeric values; the D-12 contract rewrite is proven inert)
- `grep -rn "strategy_setting\|setting_to_dict" itrader/ tests/`: zero hits

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] base.py interim shim in Task 1**
- **Found during:** Task 1 (the per-task `make typecheck` gate)
- **Issue:** The plan defers base.py's SignalEvent construction fix to Task 2, but Task 1's typecheck verify cannot pass while `_generate_signal` still passes `strategy_setting=` to the retyped event
- **Fix:** Minimal interim shim — typed fields derived from the legacy attrs (`FractionOfCash(Decimal(str(self.max_allocation)))`, LONG_ONLY); Task 2 deleted the whole construction as planned
- **Files modified:** itrader/strategy_handler/base.py
- **Commit:** 5cd6948

**2. [Rule 3 - Blocking] variable_sizer.py read signal.strategy_setting**
- **Found during:** Task 1 grep-audit (site not in the plan's files list)
- **Issue:** `DynamicSizer.size_order` read the deleted dict — mypy --strict would fail
- **Fix:** Reads the typed fields (`signal.max_positions`; allocation from `signal.sizing_policy` when FractionOfCash, else the legacy 0.80 default). Zero importers exist; the whole package dies in plan 07-05 (D-04) — this fix only keeps the gate green until then
- **Files modified:** itrader/strategy_handler/position_sizer/variable_sizer.py
- **Commit:** 5cd6948

**3. [Rule 1 - Bug] tz-naive event times in the new fan-out tests**
- **Found during:** Task 3 (fan-out test emitted no signal)
- **Issue:** `check_timeframe`'s `_aligned` seam converts via `astimezone(pytz.utc)` — a naive midnight is treated as local time and lands off the UTC midnight grid
- **Fix:** Test event times are tz-aware (`datetime(2024, 1, 2, tzinfo=UTC)`), matching the seam's documented tz-aware contract
- **Files modified:** tests/unit/strategy/test_strategy.py
- **Commit:** ba4fc20

### Plan-premise corrections (no code change)

**4. trading_interface.py constructs OrderEvent, not SignalEvent.** The plan's Task 1 instruction to fill typed fields on its "explicit-quantity SignalEvent path" is stale — the file puts `OrderEvent`s directly onto the queue and never builds a `SignalEvent`. No change needed or made.

**5. Grep-audit surfaced 6 additional test constructor sites** beyond the plan's list (test_order_handler, test_stop_limit_orders, test_order_manager x2, test_transaction_init, test_event_immutability, test_events) — all converted to the golden typed defaults per the plan's "fix any additional site the grep surfaces" instruction (commit 5cd6948).

## TDD Gate Compliance

Task 3 carries `tdd="true"`, but its behavior (the intent contract) was implemented by Task 2 of this same plan by design — a strict RED phase (failing test before implementation) was structurally impossible. The pre-existing test file DID fail against the Task-2 contract (abstract-method errors), and the conversion commit (ba4fc20, `test(...)`) locks the new behavior; the implementation commit (234d824, `feat(...)`) precedes it. Gate sequence is feat-then-test rather than test-then-feat — flagged here per protocol.

## Authentication Gates

None.

## Known Stubs

None — no placeholder values or unwired data paths introduced. (`variable_sizer.py`'s 0.80 fallback for non-FractionOfCash policies mirrors its legacy default; the file has zero importers and is deleted by plan 07-05.)

## Self-Check: PASSED

- All 14 modified files exist on disk
- Commits 5cd6948, 234d824, ba4fc20 present in git log
- `grep -rn "strategy_setting|setting_to_dict"` returns nothing
- Oracle byte-exact post-rewrite

---
phase: 07-m5b-sizing-policy-metrics-universe-coverage
reviewed: 2026-06-08T10:30:00Z
depth: standard
files_reviewed: 47
files_reviewed_list:
  - itrader/core/exceptions/__init__.py
  - itrader/core/exceptions/order.py
  - itrader/core/portfolio_read_model.py
  - itrader/core/sizing.py
  - itrader/events_handler/events/signal.py
  - itrader/events_handler/full_event_handler.py
  - itrader/order_handler/order_manager.py
  - itrader/order_handler/order_validator.py
  - itrader/order_handler/sizing_resolver.py
  - itrader/portfolio_handler/portfolio_handler.py
  - itrader/price_handler/feed/bar_feed.py
  - itrader/reporting/__init__.py
  - itrader/reporting/frames.py
  - itrader/reporting/metrics.py
  - itrader/reporting/plots.py
  - itrader/strategy_handler/base.py
  - itrader/strategy_handler/empty_strategy.py
  - itrader/strategy_handler/SMA_MACD_strategy.py
  - itrader/strategy_handler/strategies_handler.py
  - itrader/trading_system/backtest_trading_system.py
  - itrader/trading_system/live_trading_system.py
  - itrader/universe/__init__.py
  - itrader/universe/membership.py
  - scripts/run_backtest.py
  - tests/integration/test_backtest_oracle.py
  - tests/integration/test_event_wiring.py
  - tests/integration/test_reservation_inertness.py
  - tests/unit/core/test_portfolio_read_model.py
  - tests/unit/core/test_sizing.py
  - tests/unit/events/test_dispatch_registry.py
  - tests/unit/events/test_error_flow.py
  - tests/unit/events/test_event_immutability.py
  - tests/unit/events/test_events.py
  - tests/unit/order/test_admission_rules.py
  - tests/unit/order/test_on_signal.py
  - tests/unit/order/test_order_handler.py
  - tests/unit/order/test_order_manager.py
  - tests/unit/order/test_order_validator.py
  - tests/unit/order/test_sizing_resolver.py
  - tests/unit/order/test_sltp_policy.py
  - tests/unit/order/test_stop_limit_orders.py
  - tests/unit/portfolio/transaction/test_transaction_init.py
  - tests/unit/price/test_bar_feed.py
  - tests/unit/reporting/test_metrics.py
  - tests/unit/reporting/test_plots_smoke.py
  - tests/unit/strategy/test_strategy.py
  - tests/unit/universe/test_membership.py
findings:
  critical: 1
  warning: 9
  info: 9
  total: 19
status: issues_found
---

# Phase 7: Code Review Report

**Reviewed:** 2026-06-08T10:30:00Z
**Depth:** standard
**Files Reviewed:** 47
**Status:** issues_found

## Summary

Reviewed the M5B deliverables: typed sizing vocabulary (`core/sizing.py`), the
`SizingResolver` and its wiring into `OrderManager` (admission gates, SLTP
policy, fill-anchored brackets), the universe collapse to `derive_membership`,
the reporting rewrite (`frames`/`metrics`/`plots`), the pure strategy contract,
the bar feed factory relocation, and the supporting test suite plus both
trading-system composition roots.

The golden FractionOfCash/LONG_ONLY path is carefully byte-exactness-preserving
and well tested. The defects found are concentrated in the paths the new typed
vocabulary *declares* but the engine does not fully implement: SHORT_ONLY
covers are mis-sized (and can silently flip a SHORT_ONLY book long), the
documented `SignalIntent.quantity` field is silently dropped at fan-out, and
`step_size` quantization is only correct for power-of-ten steps. Several state-
hygiene gaps exist around `_pending_brackets`, and a handful of error paths
swallow exceptions in ways that conflict with the project's fail-fast,
trust-the-numbers posture. Golden files were not reviewed (owner-approved per
scope).

## Narrative Findings (AI reviewer)

## Critical Issues

### CR-01: SHORT_ONLY covers are sized as entries — a BUY cover can flip a SHORT_ONLY book long

**File:** `itrader/order_handler/order_manager.py:893-894`, `itrader/order_handler/order_manager.py:975-1004`; `itrader/strategy_handler/strategies_handler.py:152-157`
**Issue:** The admission layer explicitly blesses a BUY against an open short as
a "cover/exit" (`_enforce_position_admission`, lines 893-894: "neither gate
applies"), and the direction gate allows it (SHORT_ONLY + BUY with an open
short passes, lines 809-819). But `_resolve_signal_quantity` has **no cover
arm**: its only exit branch is `action is Side.SELL and net_quantity > 0`
(line 975). An unsized SHORT_ONLY BUY-with-open-short therefore falls through
to the ENTRY dispatch (line 999) and is sized by `FractionOfCash` —
`0.95 * available_cash / price` — instead of `resolve_exit(abs(net_quantity),
exit_fraction)`. Consequences: (a) `exit_fraction` is silently ignored for
short exits; (b) whenever `0.95 * cash / price > |short qty|`, the fill nets
the book LONG under a SHORT_ONLY declaration — exactly the class of direction
violation the D-08 gate was built to kill, now produced *by* the sanctioned
path. SHORT_ONLY is fully reachable: `add_strategy` rejects only LONG_SHORT,
and the SELL short-entry path sizes and emits (your own
`test_long_short_direction_passes_the_gate` demonstrates the entry mechanics).
There is no test covering the SHORT_ONLY cover path.
**Fix:** Either of:
```python
# Option (a) — add the cover arm in _resolve_signal_quantity, mirroring the long exit:
if signal_event.action is Side.BUY and open_position is not None and open_position.net_quantity < 0:
	return self.sizing_resolver.resolve_exit(
		abs(open_position.net_quantity),
		signal_event.exit_fraction,
		signal_event.sizing_policy.step_size,
	)
```
```python
# Option (b) — if shorts are truly out of v1 scope (D-09), close the door at registration,
# exactly like LONG_SHORT:
if strategy.direction is not TradingDirection.LONG_ONLY:
	raise ValueError("Only LONG_ONLY is admissible until the margin/liquidation milestone")
```
Option (b) is the smaller, oracle-dark change consistent with the D-09 "shorts
need the margin model" stance; option (a) is required if SHORT_ONLY is meant to
be usable now.

## Warnings

### WR-01: `SignalIntent.quantity` is silently dropped at fan-out

**File:** `itrader/strategy_handler/strategies_handler.py:89-106`; `itrader/core/sizing.py:252-261`
**Issue:** `SignalIntent` documents `quantity` as "Explicit caller-supplied
quantity; `None` means resolver decides", and the order layer honors an
explicit quantity (`_resolve_signal_quantity` line 951). But
`StrategiesHandler.calculate_signals` constructs the `SignalEvent` without
`quantity=intent.quantity` — the field is never read anywhere
(`grep intent.quantity` returns nothing). Any strategy returning an
explicit-quantity intent gets silently re-sized by its declared policy: an
order quantity different from the one the strategy declared, with no warning.
**Fix:** Add the field to the fan-out construction:
```python
signal = SignalEvent(
	...,
	exit_fraction=intent.exit_fraction,
	quantity=intent.quantity,
	sltp_policy=getattr(strategy, 'sltp_policy', None),
)
```
(or, if explicit intent quantities are intentionally unsupported, delete the
field from `SignalIntent` and its docstring so the contract is honest).

### WR-02: `step_size` quantization snaps to the Decimal exponent, not the step value

**File:** `itrader/order_handler/sizing_resolver.py:113-116`, `itrader/order_handler/sizing_resolver.py:150-157`
**Issue:** `qty.quantize(policy.step_size, rounding=ROUND_DOWN)` rounds to the
*exponent* of `step_size`, not to multiples of it. This is only correct when
the step is exactly `1 x 10^n`. Counterexamples: `step_size=Decimal("0.5")`
produces quantities on the 0.1 grid (2.3 passes, which is not a multiple of
0.5); `step_size=Decimal("0.010")` (the common exchange-filter string repr)
has exponent -3 and quantizes to the 0.001 grid instead of 0.01;
`step_size=Decimal("5")` quantizes to integers, not multiples of 5. D-05's
documented contract ("quantize ROUND_DOWN to the step") is violated for every
non-power-of-ten step, producing exchange-rejectable quantities. The
construction validator (`_validate_step_size`) only checks positivity, so
nothing catches this. Same defect in `resolve_exit`. Additionally, a sized
partial exit smaller than one step quantizes to 0 and surfaces as a confusing
validator `INVALID_QUANTITY` rejection rather than a sizing-domain outcome.
**Fix:**
```python
def _quantize_to_step(qty: Decimal, step: Decimal) -> Decimal:
    return (qty / step).to_integral_value(rounding=ROUND_DOWN) * step
```
Use it in both `resolve_entry` and `resolve_exit`; optionally raise
`SizingPolicyViolation` when the result is zero. (If only 10^n steps are
intended for v1, enforce that in `_validate_step_size` instead.)

### WR-03: `_pending_brackets` hygiene — entries leak on local cancel, assembly failure, and survive order modification

**File:** `itrader/order_handler/order_manager.py:596-604`, `itrader/order_handler/order_manager.py:1129-1193`, `itrader/order_handler/order_manager.py:232-238`
**Issue:** Three gaps in the PercentFromFill pending-bracket lifecycle:
1. `cancel_order` (the local-terminal path that WR-04 made authoritative)
   never pops `self._pending_brackets[order.id]`. A locally-cancelled
   PercentFromFill parent leaves its pending entry armed forever; if an
   EXECUTED fill later arrives for that order (the WR-02 race the code itself
   handles), `on_fill` still creates, stores, and emits the children
   (line 232 keys off `status == EXECUTED` regardless of `applied`), linking
   live SL/TP children to a CANCELLED parent.
2. The pending entry is registered at assembly time (line 596) *before*
   `add_order` runs; if storage raises afterwards, the failure path releases
   the reservation (WR-03 in code) but leaves the pending entry orphaned.
3. `modify_order` changing the parent's quantity does not update
   `pending.quantity` — fill-anchored children are later created at the stale
   assembly-time quantity.
**Fix:** Pop the entry in `cancel_order` on a successful terminal transition
and in the `_assemble_bracket_and_emit` exception handler
(`self._pending_brackets.pop(primary.id, None)`); in `modify_order`, either
refresh `pending.quantity` via `dataclasses.replace` or reject quantity
modification of an armed PercentFromFill parent. Gate child creation in
`on_fill` on `applied` being True.

### WR-04: `OrderManager.on_fill` swallows all reconciliation exceptions — reservation release can be skipped silently

**File:** `itrader/order_handler/order_manager.py:239-240` (with release at 205-207)
**Issue:** The entire reconciliation body — mirror transition, storage update,
**reservation release**, orphan-child cancellation, fill-anchored child
creation — sits in one `try` whose handler is
`self.logger.error('Error reconciling fill...', order_id, e)` with no
`exc_info` and no re-raise. If anything raises before line 205 (e.g.
`add_fill` raising instead of returning False, or `update_order` failing), the
terminal release never runs and the BUY's reservation is stuck for the rest of
the run — exactly the T-05-17 buying-power corruption the release machinery
exists to prevent — while the run continues producing silently-wrong numbers.
This contradicts the project's fail-fast backtest policy (the portfolio side
of the same FILL re-raises through `_on_handler_error`).
**Fix:** Narrow the `try` to the mirror-transition block, or re-raise after
logging (backtest policy), and at minimum move the
`portfolio_handler.release(...)` call into a `finally` so a terminal fill
always releases. Add `exc_info=True` to the log call.

### WR-05: Mutable default argument in the reference strategy

**File:** `itrader/strategy_handler/SMA_MACD_strategy.py:24`
**Issue:** `def __init__(self, timeframe, tickers: list[str] = [], ...)` — the
classic shared-mutable-default pitfall. All `SMA_MACD_strategy()` instances
constructed without `tickers` share one list object as `self.tickers`; any
mutation (e.g. a future `tickers.append`) bleeds across instances and into
`derive_membership`. Also, an empty default tickers list means a
default-constructed strategy silently trades nothing.
**Fix:**
```python
def __init__(self, timeframe: str, tickers: list[str] | None = None, ...):
	super().__init__("SMA_MACD", timeframe, list(tickers or []), ...)
```

### WR-06: SLTP policy has no declaration seam on the Strategy base — feature unreachable through the typed contract

**File:** `itrader/strategy_handler/base.py:26-50`; `itrader/strategy_handler/strategies_handler.py:105`
**Issue:** The handler attaches `sltp_policy=getattr(strategy, 'sltp_policy',
None)`, but `Strategy.__init__` accepts no `sltp_policy` parameter and never
sets the attribute. The D-13 engine-side SLTP feature delivered this phase can
only be reached by monkey-setting an undeclared attribute on a strategy
instance (the unit tests bypass this by constructing `SignalEvent` directly).
Every other declaration (sizing_policy, direction, allow_increase,
max_positions) is a typed constructor kwarg; this one is a stringly-typed
`getattr` hole that mypy cannot check and that typos silently turn into
"no policy".
**Fix:** Add `sltp_policy: SLTPPolicy | None = None` to `Strategy.__init__`
(and `to_dict`), set `self.sltp_policy = sltp_policy`, and replace the
`getattr` with `strategy.sltp_policy`.

### WR-07: Ping grid derived from `store.symbols()[0]` only — crashes on empty store, silently drops ticks for other symbols

**File:** `itrader/trading_system/backtest_trading_system.py:153-154`
**Issue:** `self.time_generator.set_dates(self.store.index(self.store.symbols()[0]))`
raises an opaque `IndexError` when the store has no symbols (empty data dir /
bad path), and for multi-symbol stores it derives the entire simulation clock
from the *first* symbol's bar index. Symbols whose bars fall on dates absent
from symbol[0]'s calendar (the feed and megaframe explicitly support sparse
multi-symbol universes — see `duo_feed` tests) never tick: their bars are
silently never delivered, never matched, never marked. No warning is emitted.
**Fix:** Fail loudly on an empty store
(`if not self.store.symbols(): raise ConfigurationError(...)`) and derive the
ping grid from the union of all symbol indexes
(`reduce(pd.Index.union, (self.store.index(s) for s in symbols))`), or at
minimum log a warning naming the symbol whose calendar was chosen.

### WR-08: Mark-to-market failures are swallowed per portfolio — equity marks go silently stale

**File:** `itrader/portfolio_handler/portfolio_handler.py:362-370`
**Issue:** `update_portfolios_market_value` wraps each portfolio's
`update_market_value_of_portfolio` in `except Exception` + `logger.warning`
and continues. In a project whose core value is "numbers you can trust", a
failed mark leaves the equity curve carrying stale position values for that
tick with only a log line — downstream `record_metrics` snapshots, the
drawdown/sharpe block, and the frozen oracle all consume the corrupted value
without any error event. This is inconsistent with `on_fill`'s D-10 fail-fast
contract on the very same dispatch path.
**Fix:** Re-raise (letting the registry's `_on_handler_error` backtest policy
abort the run), or publish a `PortfolioErrorEvent` through
`_publish_error_event` so the failure at least reaches the ERROR route instead
of a debug-level log stream.

### WR-09: Live loop records equity before the tick's BAR is processed, and continues after partial dispatch

**File:** `itrader/trading_system/live_trading_system.py:257-268`, `itrader/trading_system/live_trading_system.py:281-286`
**Issue:** Two ordering defects in the rewritten `_event_processing_loop`:
1. On a TIME event it dispatches (which only *enqueues* the BAR event) and then
   immediately calls `portfolio.record_metrics(event.time)` — the BAR's
   mark-to-market runs on the *next* loop iteration, so every live equity
   snapshot is taken against the previous tick's marks. The backtest path
   drains the whole tick before recording; live diverges by one bar.
2. The outer `except Exception: ... continue` combined with the fail-fast
   `_on_handler_error` re-raise means a FILL whose `portfolio.on_fill` raises
   skips `order_handler.on_fill` entirely (mirror never reconciles, reservation
   never releases) and the loop keeps running on divergent state. The
   `EventHandler` docstring says live should *override* `_on_handler_error`
   with publish-and-continue; this loop instead catches around `_dispatch`,
   which is not equivalent.
**Fix:** Record metrics only after the queue is drained for the tick (or after
the BAR event is dispatched, not the TIME event); implement the documented
live policy as an `EventHandler` subclass overriding `_on_handler_error`
instead of catch-and-continue around `_dispatch`. (D-live scope — but this
code was modified this phase, so the drift is fresh.)

## Info

### IN-01: Stale member count in PortfolioReadModel module docstring

**File:** `itrader/core/portfolio_read_model.py:32-39`
**Issue:** The OQ1 paragraph still says "the Protocol carries exactly SIX
members" while the Protocol now declares seven (`total_equity` added by Plan
07-01, correctly documented further down and in the tests).
**Fix:** Update the count and member list in the OQ1 paragraph.

### IN-02: Dead duplicate `get_strategies_universe` after the membership relocation

**File:** `itrader/strategy_handler/strategies_handler.py:111-128`
**Issue:** `derive_membership` relocated this union logic "verbatim", but the
original method was left behind and now has zero callers (grep across
`itrader/` and `scripts/` finds only the definition). It also shadows the
`tuple` builtin in its comprehension. Two divergence-prone copies of the
membership union now exist.
**Fix:** Delete the method (or delegate it to `derive_membership([s for s in self.strategies])`).

### IN-03: Unused imports

**File:** `itrader/trading_system/backtest_trading_system.py:33`; `itrader/trading_system/live_trading_system.py:4-5,25`; `itrader/order_handler/order_validator.py:1-2`
**Issue:** `EventType` (backtest system); `time`, `json`, `TimeEvent`,
`OrderEvent` (live system); `datetime`, `Dict` (order_validator) are imported
and never used.
**Fix:** Remove them (mypy --strict with warn-unused-ignores will not catch
unused imports; ruff/flake8 F401 would).

### IN-04: `_FakeReadModel` no longer satisfies the Protocol it claims to

**File:** `tests/unit/order/test_order_manager.py:270-303`
**Issue:** The docstring says it "Satisfies the runtime_checkable Protocol
structurally (D-16)", but it lacks `total_equity`, so
`isinstance(_FakeReadModel(), PortfolioReadModel)` is now False. Tests pass
only because `OrderManager` never isinstance-checks; any future runtime guard
or a RiskPercent-sizing test through this fake will break confusingly.
**Fix:** Add `total_equity(self, portfolio_id): return self._cash` (and fix
the docstring), keeping it aligned with `_ConformingFake` in
`test_portfolio_read_model.py`.

### IN-05: Event test fixtures bypass the Decimal/typed-ID contracts

**File:** `tests/unit/events/test_event_immutability.py:66-90`; `tests/unit/events/test_events.py:31-39`; `tests/unit/order/test_order_manager.py:93-98`
**Issue:** Fixtures construct `SignalEvent`/`OrderEvent`/`FillEvent` with float
money (`price=42.0`, `commission=0.1`) and string strategy/portfolio ids
despite the fields being declared `Decimal`/`StrategyId`. Frozen dataclasses
don't validate, so the tests pass while exercising a type shape the run path
never produces — weakening the "Decimal end-to-end" lock these very tests
exist to enforce.
**Fix:** Build fixtures with `Decimal("...")` string-path literals and typed
ids, matching `test_events.py`'s signal fixture.

### IN-06: `cagr` year basis uses point count, not elapsed duration

**File:** `itrader/reporting/metrics.py:115`
**Issue:** `years = len(equity) / periods` counts n points as n days; n points
span n-1 bar intervals, and backtesting.py (the Phase 8 cross-validation
reference) computes CAGR from actual elapsed duration. The off-by-one is
negligible at 3000 bars but will show up as a small systematic mismatch in the
Phase 8 cross-validation of short windows. The value is frozen in the golden
metrics block, so changing it later costs a re-freeze.
**Fix:** Consider `years = (len(equity) - 1) / periods` (or document the pin
as a deliberate divergence before Phase 8 freezes comparisons).

### IN-07: `Strategy.max_window` defaults to 0 — empty windows for forgetful subclasses

**File:** `itrader/strategy_handler/base.py:50`; `itrader/price_handler/feed/bar_feed.py:319`
**Issue:** A concrete strategy that forgets to override `max_window` gets
`feed.window(..., max_window=0, ...)` → an always-empty frame; strategies
indexing `bars.index[-1]` (the SMA_MACD pattern) then raise `IndexError` deep
in `calculate_signals`. A loud default would fail at construction instead.
**Fix:** Make `max_window` a required constructor kwarg or validate
`max_window > 0` in `StrategiesHandler.add_strategy`.

### IN-08: Vestigial `getattr` for a required FillEvent field

**File:** `itrader/order_handler/order_manager.py:155-157`
**Issue:** `order_id = getattr(fill_event, 'order_id', None)` guards against a
missing field, but since M3-01 `FillEvent` requires `order_id` at construction
(`test_fill_event_requires_order_id`). The defensive branch is dead and hides
the real contract.
**Fix:** Read `fill_event.order_id` directly.

### IN-09: `plots.py` uses tabs inside the otherwise space-indented new reporting package

**File:** `itrader/reporting/plots.py` (whole file)
**Issue:** `metrics.py` and `frames.py` (same new M5-07 package) use 4-space
indentation per the "newer modules use spaces" convention; `plots.py` carried
tabs over from the legacy module. Mixed styles within one new package invite
match-the-file confusion.
**Fix:** Re-indent `plots.py` with spaces (whitespace-only change).

---

_Reviewed: 2026-06-08T10:30:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_

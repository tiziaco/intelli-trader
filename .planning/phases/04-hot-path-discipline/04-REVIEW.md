---
phase: 04-hot-path-discipline
reviewed: 2026-06-24T00:00:00Z
depth: standard
files_reviewed: 10
files_reviewed_list:
  - itrader/config/settings.py
  - itrader/logger.py
  - itrader/order_handler/admission/admission_manager.py
  - itrader/portfolio_handler/cash/cash_manager.py
  - itrader/portfolio_handler/position/position_manager.py
  - itrader/strategy_handler/base.py
  - perf/results/W1-BASELINE.json
  - tests/unit/core/test_logging_gate.py
  - tests/unit/strategy/test_strategy.py
  - tests/unit/strategy/test_type_hints_equivalence.py
findings:
  critical: 0
  warning: 5
  info: 6
  total: 11
status: issues_found
---

# Phase 4: Code Review Report

**Reviewed:** 2026-06-24T00:00:00Z
**Depth:** standard
**Files Reviewed:** 10
**Status:** issues_found

## Summary

Phase 04 ("hot-path-discipline") is a v1.5 performance phase whose central deliverable is the
hot-path logging gate (`ITraderStructLogger` cached `isEnabledFor` short-circuit + the
`ITRADER_DISABLE_LOGS` kill-switch), the admission-rejection `error→warning` demotion, the
`@functools.cache`-memoized `_declared_hints`, and the O(1) realised-PnL accumulator. These
optimizations are correctness-sensitive because the milestone gate is behavior-preserving
against the SMA_MACD byte-exact oracle (134 trades / final_equity 46189.87730727451).

The logging gate itself is implemented carefully and is genuinely side-effect-free at enabled
levels: the `_stdlib.isEnabledFor` check is read-only, the kill-switch is a cached bool checked
first, and the `bind()`-via-`__new__` carry-over of `_stdlib` is correctly handled (and
regression-locked by `test_bind_carries_stdlib_for_gate`). The money path stays Decimal
end-to-end on every hot site I traced; the remaining `float()` casts are confined to exception
constructors, logging `str()`/`float()` edges, and `get_*_info`/`get_*_summary` serialization
methods — none on the trade-settlement path. The admission `error→warning` demotion preserves
emitted content (verified by `test_admission_line_warning_renders_same_content_as_error`).

No Critical defects were found (no float-on-money on a hot path, no determinism violation on the
oracle path, no security/injection issue). The findings below are latent correctness bugs on
off-oracle code paths, gate/funnel-discipline edge cases, and test-isolation/quality concerns.

## Narrative Findings (AI reviewer)

## Warnings

### WR-01: `calculate_position_metrics` raises `TypeError` on any open position (naive/aware datetime subtraction)

**File:** `itrader/portfolio_handler/position/position_manager.py:389-390`
**Issue:** For an **open** position (`exit_date is None`), `end_time` is set to
`datetime.now()` — a tz-**naive** wall-clock value. `position.entry_date` is sourced from
`transaction.time` (event-derived, tz-**aware** on the run path — see `position.py:232`,
`entry_date = transaction.time`). The subtraction `(end_time - position.entry_date).days`
then raises `TypeError: can't subtract offset-naive and offset-aware datetimes`. So
`calculate_position_metrics(position_id)` crashes for any live/open position rather than
returning metrics. It is off the SMA_MACD oracle path (which is why it survives the gate),
but it is a real latent crash, and `datetime.now()` is also a determinism smell (wall clock,
banned on event-derived paths).
**Fix:** Use a tz-consistent, event-derived "now":
```python
end_time = position.exit_date
if end_time is None:
    end_time = datetime.now(position.entry_date.tzinfo)  # match entry_date awareness
holding_period = (end_time - position.entry_date).days
```

### WR-02: `_apply_params` leaves the strategy partially mutated when a `reconfigure` validation fails mid-pass

**File:** `itrader/strategy_handler/base.py:146-216` (reached via `reconfigure` → `_apply_params`)
**Issue:** `_apply_params` `setattr`s each resolved value onto `self` inside the loop
(line 200) and only validates `tickers` (lines 210-216) and re-resolves `timeframe`
(lines 227-240) AFTER the loop. If `reconfigure(tickers="BTCUSDT", short_window=30)` is
called, `short_window` is already committed to `self` and `self.timeframe` is rolled forward
before the post-loop `tickers` guard raises `ValueError`. There is no transactional rollback,
so a `reconfigure` that "rejects loudly" leaves the instance in a partially reconfigured state
— violating the reasonable caller expectation that a rejected reconfigure leaves prior state
intact. Same hazard for a bad `_COERCE` value raising at line 199 after earlier fields were set.
**Fix:** Resolve and validate the full kwarg set into a local dict first, committing to `self`
only after every check (shape, coercion, unknown/missing) passes; or snapshot the affected
attributes and restore them in an `except` before re-raising.

### WR-03: realised-PnL accumulator correctness depends on a hand-maintained split funnel with no run-path enforcement

**File:** `itrader/portfolio_handler/position/position_manager.py:304-358, 477-492`
**Issue:** `get_total_realized_pnl` returns the cached `_realised_pnl_accumulator` (PERF-02),
fed via `apply_realised_increment` from TWO disjoint sources: the Portfolio settle arms (normal
close path through `_close_position` at line 192) and a *manual* feed inside
`close_all_positions` (line 491). The "do not also feed from `_close_position`" rule is enforced
only by a prose comment. `_close_position` (line 206) is shared by both paths, so any future
edit that moves the increment into it double-counts the emergency path, and any edit that drops
a settle-arm feed silently undercounts — either way `get_total_realized_pnl` drifts the equity
curve and the oracle, with no hot-path guard catching it (`assert_accumulator_consistent` is a
gated test-only seam, deliberately never called at runtime).
**Fix:** Single-source the funnel (feed the increment in exactly one place — ideally
`_close_position` — and remove the other feeds), OR add a single end-of-run
`assert_accumulator_consistent()` call in backtest teardown so a desync fails loud at run end
without re-paying the per-bar O(positions) cost.

### WR-04: `_json_default` re-raises and can crash the ERROR-route JSON log sink on a stray field

**File:** `itrader/logger.py:66-98`
**Issue:** `_json_default` raises `TypeError` for any object that is not a `uuid.UUID`. In
`_uuid_safe_json_serializer`, the chained `structlog_default` is consulted only when
`_json_default` raises, and if structlog injected no `default` (future structlog version, or a
direct call without one) `structlog_default is None`, so the bare `TypeError` propagates and
the entire log emit fails. On the ERROR route this turns a single non-serializable context
value (a `Decimal`, a `datetime`, a custom object) into a crash of the last-resort error sink.
JSON logging is opt-in (`ITRADER_JSON_LOGS`), so this is off the default backtest path, but in
JSON/live mode it converts a benign serialization gap into a logging-pipeline failure.
**Fix:** Make the JSON sink total — never raise — mirroring the strategy `_json_safe` discipline:
```python
def _json_default(obj: object) -> str:
    if isinstance(obj, uuid.UUID):
        return str(obj)
    return repr(obj)  # a log sink must never crash on a stray field
```

### WR-05: `_capture_via_direct_structlog` reconfigures structlog globally and never restores it (test-isolation hazard)

**File:** `tests/unit/core/test_logging_gate.py:215-236`
**Issue:** The helper calls `structlog.configure(...)` with a throwaway `PrintLoggerFactory`
chain and never restores the prior config. Tests in this file that run afterward happen to call
`init_logger()` first (which re-`configure`s), masking the leak — but any test, in this file or
another, that depends on the `init_logger`/`setup_logging` structlog config WITHOUT calling it
itself would observe the leaked config. Under `filterwarnings=["error"]` and pytest ordering
this is exactly the kind of hidden coupling that produces later flakiness. This is a
test-reliability defect (in scope).
**Fix:** Snapshot and restore: capture `structlog.get_config()` (or the configured processors)
at entry and `structlog.configure(...)` back in a `finally`, or move the helper behind a
fixture that restores config on teardown (mirroring the `clean_root_logger` fixture pattern).

## Info

### IN-01: `datetime.now()` (naive) in `calculate_position_metrics` is a wall-clock determinism smell

**File:** `itrader/portfolio_handler/position/position_manager.py:389`
**Issue:** Independent of WR-01's TypeError, a bare naive `datetime.now()` introduces a
wall-clock read inconsistent with the codebase convention (other admin paths use
`datetime.now(UTC)`; event-tied paths use event-derived time).
**Fix:** At minimum use `datetime.now(UTC)` (which also resolves WR-01); ideally thread an
event-derived "now".

### IN-02: Magic-number threshold `> 0.5` in the price-change sanity check

**File:** `itrader/portfolio_handler/position/position_manager.py:243`
**Issue:** `if price_change_ratio > 0.5:` uses an inline float literal in a Decimal comparison
context, while sibling tunables in the class are named class attributes
(`max_concentration_pct`, `tolerance`, `precision`).
**Fix:** Promote to a named Decimal class attribute (e.g.
`self.large_price_change_ratio = Decimal("0.5")`) and compare Decimal-to-Decimal.

### IN-03: `numpy` imported but unused in `position_manager.py`

**File:** `itrader/portfolio_handler/position/position_manager.py:10`
**Issue:** `import numpy as np` has no reference in the module (all numerics are Decimal).
Dead import.
**Fix:** Remove `import numpy as np`.

### IN-04: `operation = self._create_operation(...)` return value bound but never used

**File:** `itrader/portfolio_handler/cash/cash_manager.py:179, 239, 300`
**Issue:** Three call sites bind `operation = self._create_operation(...)` and never reference
the local again (the record is appended to storage inside the helper). The unused binding is
dead and inconsistent with the `apply_fill_cash_flow`/`reserve_cash` sites that already discard
the return.
**Fix:** Drop the assignment: `self._create_operation(...)`.

### IN-05: Unconverted incoming `amount` placed into the `InvalidTransactionError` payload

**File:** `itrader/portfolio_handler/cash/cash_manager.py:645-649`
**Issue:** The non-positive guard raises `InvalidTransactionError(..., {"amount": amount})`
with the *unconverted* `amount` (possibly a float), so a binary-float artifact can surface in
the structured error/audit payload. Low impact (error path only) but inconsistent with the
module's "Decimal until the serialization edge" discipline.
**Fix:** Stringify or convert first: `{"amount": str(to_money(amount))}`.

### IN-06: `Strategy.evaluate` non-re-entrancy is documented but not enforced (relevant to a perf milestone)

**File:** `itrader/strategy_handler/base.py:313-343`
**Issue:** `evaluate` mutates shared instance state (`self.bars`, `self.now`, registered
handles) before dispatch and relies on a single-writer contract enforced only by prose. In a
performance milestone where parallel strategy evaluation is a plausible future optimization, a
second writer would silently race on the per-tick snapshot.
**Fix:** Optional for v1.5 scope: add a cheap debug-build re-entrancy guard (set/clear a flag
around the body and `assert` it) so a future parallelism change trips loudly instead of
corrupting a snapshot.

---

_Reviewed: 2026-06-24T00:00:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_

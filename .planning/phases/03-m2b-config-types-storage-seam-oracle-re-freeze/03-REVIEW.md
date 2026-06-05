---
phase: 03-m2b-config-types-storage-seam-oracle-re-freeze
reviewed: 2026-06-05T00:00:00Z
depth: standard
files_reviewed: 11
files_reviewed_list:
  - itrader/config/models.py
  - itrader/config/settings.py
  - itrader/core/enums/execution.py
  - itrader/core/enums/portfolio.py
  - itrader/outils/time_parser.py
  - itrader/portfolio_handler/base.py
  - itrader/portfolio_handler/storage/in_memory_storage.py
  - itrader/portfolio_handler/storage/storage_factory.py
  - itrader/portfolio_handler/portfolio.py
  - itrader/order_handler/order.py
  - tests/integration/test_backtest_oracle.py
findings:
  critical: 0
  warning: 5
  info: 4
  total: 9
status: issues_found
---

# Phase 03: Code Review Report

**Reviewed:** 2026-06-05T00:00:00Z
**Depth:** standard
**Files Reviewed:** 11
**Status:** issues_found

## Summary

This was a behavior-preserving structural refactor (M2b). I traced the storage seam end-to-end
into the four managers that consume it, compared the new `_aligned`/`to_timedelta` time logic
against the prior implementation in git, and verified the Decimal-vs-float boundaries on the
cash/transaction path.

The headline finding: the new `_aligned` epoch-grid alignment is **NOT** behavior-preserving for
weekly or any non-day-divisor timeframe — it only coincides with the old midnight-of-day anchor
for the daily golden case. The docstring asserts the oracle is "unchanged," which is true only for
the pinned 1d run; for `1W`/`7h`/etc. the firing days change. The golden SMA_MACD oracle is daily
at 00:00 UTC, so the regression-locked numbers are unaffected, but the seam carries a latent
behavior change that contradicts its own documented invariant.

No BLOCKER-tier defects were proven against the daily golden path. The Decimal money boundaries on
the cash/transaction path are consistent, the storage seam is correctly shared across managers in a
real `Portfolio`, and the oracle output does not source any wall-clock field. Findings below are
robustness, determinism-hygiene, and documentation-accuracy issues.

## Warnings

### WR-01: `_aligned` epoch-grid anchor silently changes firing behavior for non-daily timeframes

**File:** `itrader/outils/time_parser.py:127-145`
**Issue:** The previous `check_timeframe` anchored alignment to **midnight of the event day**
(`time.replace(hour=0, minute=0, second=0, microsecond=0)`), so any timeframe fired on every
midnight regardless of unit. The new `_aligned` anchors to the **Unix epoch grid**
(`int(ts.timestamp()) % int(tf.total_seconds()) == 0`). These diverge for any timeframe that does
not evenly divide a 24h day-from-midnight. Verified concretely:
- Weekly (`timedelta(weeks=1)`): old fired on every midnight (Mon/Sun/etc.); new fires only on
  **Thursdays** (epoch 1970-01-01 was a Thursday). `2018-01-01` (Mon) → old `True`, new `False`.
- `7h`: old fired at every midnight; new never fires at midnight.

The docstring claims "the behavioral oracle is unchanged" — that is only true for the daily golden
bars at 00:00 UTC (which I confirmed align identically). For any other timeframe this is an
undocumented behavior change. The old daily-anchor weekly behavior was arguably itself wrong, so
the new epoch grid may be an improvement — but it must be documented as a deliberate behavior
change, not asserted as preservation.
**Fix:** Either (a) narrow the docstring to state explicitly that only day-divisor timeframes
anchored at 00:00 UTC are preserved and that weekly/non-divisor timeframes now fire on the epoch
grid (different days), or (b) if midnight-relative weekly firing must be preserved, restore a
day-anchored grid for sub-week units:
```python
def _aligned(ts: datetime, tf: timedelta) -> bool:
    # day-relative anchor preserves the prior midnight grid for all sub-day/day units
    midnight = ts.replace(hour=0, minute=0, second=0, microsecond=0)
    return int((ts - midnight).total_seconds()) % int(tf.total_seconds()) == 0
```

### WR-02: Standalone manager fallback creates divergent (unshared) storage backends

**File:** `itrader/portfolio_handler/cash/cash_manager.py:66-71` (and the identical block in
`position/position_manager.py:65-70`, `transaction/transaction_manager.py:55-60`,
`metrics/metrics_manager.py:95-100`)
**Issue:** Each manager's `__init__` does
`storage = getattr(portfolio, "state_storage", None)` and, if `None`, calls
`PortfolioStateStorageFactory.create("backtest")` to mint its **own** backend. In a real
`Portfolio` this never triggers (`_init_managers` sets `self.state_storage` before constructing
managers, so all four share one seam). But if more than one manager is constructed standalone
against the same lightweight test portfolio that lacks `state_storage`, **each manager gets a
separate store** — a `CashManager`'s reserved cash and a `PositionManager`'s positions would live
in disjoint containers, silently breaking any cross-manager invariant (e.g. reserved-cash <
position-driven balance checks). This is a latent correctness trap in test scaffolding and any
future direct-manager construction.
**Fix:** Hoist the fallback so a single seam is created once and shared. Either require the
portfolio to always carry `state_storage` (assert, don't silently fabricate), or have the first
manager that needs it set it back onto the portfolio:
```python
storage = getattr(portfolio, "state_storage", None)
if storage is None:
    storage = PortfolioStateStorageFactory.create("backtest")
    try:
        portfolio.state_storage = storage  # share with sibling managers
    except AttributeError:
        pass
self._storage = storage
```

### WR-03: `Order.created_at` is wall-clock `datetime.now()` despite the phase's event-derived-timestamp goal

**File:** `itrader/order_handler/order.py:59-60`
**Issue:** `created_at` and `updated_at` default to `field(default_factory=datetime.now)` —
naive wall-clock, non-deterministic, and timezone-naive (unlike the event-derived `self.time`).
`updated_at` is overwritten on the first `add_state_change` (which `new_order`/`new_stop_order`/
`new_limit_order` all trigger), so it ends up event-derived in practice — but `created_at` is
**never reset** and remains wall-clock for the order's whole life. The phase explicitly finalizes
"event-derived order timestamps" (D-12) and `add_state_change` carefully threads event time, yet
this construction-boundary field bypasses that policy. It does not currently reach the oracle
output (`scripts/run_backtest.py` serializes `Position.to_dict()` + `PortfolioSnapshot`, never
`Order.created_at`), so the golden master is safe — but it is a determinism leak waiting to bite
the moment any order field is serialized, and it contradicts the stated invariant.
**Fix:** Make `created_at` event-derived from the order's own time. Since `time` is a required
field, set it in `__post_init__`:
```python
def __post_init__(self) -> None:
    self.price = to_money(self.price)
    self.quantity = to_money(self.quantity)
    self.filled_quantity = to_money(self.filled_quantity)
    # event-derived (D-12): never wall-clock
    self.created_at = self.time
    self.updated_at = self.time
```
(remove the `datetime.now` default factories).

### WR-04: `add_fill` records full-precision `fill_quantity`/`total_filled` in audit data, but `fill_price` may be non-Decimal

**File:** `itrader/order_handler/order.py:313-356`
**Issue:** `add_fill` normalizes `fill_quantity = to_money(fill_quantity)` but does **not** normalize
`fill_price` before storing it into `additional_data["fill_price"]` (line 348). The signature types
it `Decimal`, but the audit record will faithfully carry whatever the exchange passed (int/float),
producing mixed-type audit data and, if that data is later summed/compared against Decimal money,
a `TypeError` or a float-contaminated value. The money-domain boundary (D-04) is enforced for
quantity here but not for the price written into the same record.
**Fix:** Normalize at the boundary:
```python
fill_price = to_money(fill_price)
...
additional_data = {
    "fill_quantity": fill_quantity,
    "fill_price": fill_price,
    ...
}
```

### WR-05: `_load_run_backtest_module` does not guard `spec`/`spec.loader` being `None`

**File:** `tests/integration/test_backtest_oracle.py:58-63`
**Issue:** `importlib.util.spec_from_file_location` returns `Optional[ModuleSpec]` and
`spec.loader` is `Optional`. If `_RUN_BACKTEST` is moved/renamed (a plausible refactor since the
script path is hard-coded two parents up), `spec` is `None` and the test dies with an opaque
`AttributeError: 'NoneType' object has no attribute 'loader'` rather than a clear "oracle generator
not found" message — masking the real cause of an integration failure.
**Fix:**
```python
if not _RUN_BACKTEST.exists():
    pytest.fail(f"oracle generator missing: {_RUN_BACKTEST}")
spec = importlib.util.spec_from_file_location("run_backtest", _RUN_BACKTEST)
assert spec is not None and spec.loader is not None, f"cannot load {_RUN_BACKTEST}"
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
```

## Info

### IN-01: Stale `OrderType` re-export name collision between `config.models` and `core.enums`

**File:** `itrader/config/models.py:56,69`
**Issue:** `config.models` re-exports a Pydantic `OrderType` (from `config.trading`), while the
order domain uses `core.enums.OrderType` (`order.py:11`). Two distinct `OrderType` symbols with the
same name in the public import surface invite a wrong-import bug (`from itrader.config.models import
OrderType` silently gives the config enum, not the order enum). Not a defect today, but a naming
hazard worth a disambiguating alias or a docstring note.
**Fix:** Consider exporting the config one as `TradingOrderType` in `models.__all__`, or document
the distinction in the module docstring.

### IN-02: `TIMEZONE` resolved from a Pydantic field default via private-ish `model_fields` access

**File:** `itrader/config/__init__.py:83`
**Issue:** `TIMEZONE = str(Settings.model_fields["timezone"].default)` reads the default off the
class without instantiating (deliberately, to avoid the fail-loud secret). This is correct for
Pydantic v2, but it bypasses any future validator/normalizer on `timezone` and will break if the
field gains a `default_factory` (then `.default` is `PydanticUndefined`). Low risk; flagging for
maintainability.
**Fix:** Add a brief comment that this intentionally reads the raw default and must be revisited if
`timezone` ever gains a `default_factory` or validator.

### IN-03: Leftover TODO comment in `Order.add_state_change`

**File:** `itrader/order_handler/order.py:294-295`
**Issue:** `# TODO: check if i have to store the state changes permanently in sql when in live
trading / production` — a tracked-work marker left inline. Harmless but should be tracked in the
plan/issue tracker rather than the source.
**Fix:** Move to the deferred-work list (D-sql) and remove the inline TODO, or convert to a
referenced ticket id.

### IN-04: Unused convenience method `PortfolioStateStorageFactory.create_in_memory`

**File:** `itrader/portfolio_handler/storage/storage_factory.py:64-76`
**Issue:** `create_in_memory()` is provided "for testing and backtesting" but the only production
caller (`portfolio.py:91`) uses `create("backtest")`. No reviewed caller uses `create_in_memory`.
This mirrors the order-storage factory verbatim, so it is intentional parity, but it is currently
dead in the portfolio path.
**Fix:** Keep for API parity (acceptable) or drop until a caller needs it. No action required if
parity with `OrderStorageFactory` is the goal — note it as intentional.

---

_Reviewed: 2026-06-05T00:00:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_

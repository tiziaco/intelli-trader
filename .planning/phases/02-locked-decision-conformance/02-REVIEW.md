---
phase: 02-locked-decision-conformance
reviewed: 2026-06-11T00:00:00Z
depth: standard
files_reviewed: 11
files_reviewed_list:
  - itrader/order_handler/order_handler.py
  - itrader/order_handler/order_manager.py
  - itrader/execution_handler/exchanges/simulated.py
  - itrader/core/ids.py
  - itrader/outils/id_generator.py
  - itrader/events_handler/events/error.py
  - itrader/portfolio_handler/portfolio_handler.py
  - tests/unit/order/test_order_manager.py
  - tests/unit/execution/exchanges/test_simulated_exchange.py
  - tests/unit/portfolio/test_portfolio_handler.py
  - tests/e2e/conftest.py
findings:
  critical: 0
  warning: 1
  info: 2
  total: 3
status: issues_found
---

# Phase 2: Code Review Report

**Reviewed:** 2026-06-11
**Depth:** standard
**Files Reviewed:** 11
**Status:** issues_found

## Summary

This phase is a behavior-preserving type-conformance pass (v1.2): float→Decimal at the
size-limit and modify-order boundaries, and a legacy `str` correlation-id scheme migrated
to the single UUIDv7 `idgen` scheme. I traced every changed line through its consumers.

Verification performed:
- `mypy --strict` is clean across all 7 changed source files.
- The three modified/added tests pass.
- The size-limit comparisons (`event.quantity < self._min_order_size`, etc.) are now
  Decimal-vs-Decimal because `OrderEvent.quantity` and `config.limits.min_order_size` are
  both `Decimal` — no `TypeError` and value-preserving, so the golden oracle is unaffected.
- `modify_order` Decimal args flow through `to_money(Decimal(...))`, which is value-preserving
  (`Decimal(str(Decimal("28.0")))`), so no numeric drift.
- The correlation-id migration flows the UUID only into `PortfolioErrorEvent.correlation_id`
  and a structured-log dict — never into arithmetic or `.startswith()` on the engine path.

One genuine regression was found on the **live JSON-logging error path** (WR-01): the
correlation-id type change from `str` to `uuid.UUID` breaks `JSONRenderer` serialization.
It does not perturb the backtest golden oracle (error path never fires on a green run), but
it crashes error logging in live mode exactly when an error is being reported. Two lower-severity
serialization-consistency items round out the findings.

## Narrative Findings (AI reviewer)

## Warnings

### WR-01: correlation_id UUID breaks JSON-renderer error logging in live mode

**File:** `itrader/portfolio_handler/portfolio_handler.py:85-87`, surfacing at `itrader/events_handler/full_event_handler.py:163`

**Issue:** `_generate_correlation_id` changed from returning a `str` (`f"ph_{uuid4().hex[:12]}"`)
to returning a `uuid.UUID` (`CorrelationId(idgen.generate_correlation_id())`). That value lands
verbatim in the ERROR-route log context:

```python
context: dict[str, Any] = {
    ...
    "correlation_id": event.correlation_id,   # now a uuid.UUID
}
log_method("Error event consumed", **context)
```

The logger is configured with a bare `structlog.processors.JSONRenderer()` and no custom
`serializer`/`default` (`itrader/logger.py:110`). `JSONRenderer` defaults to `json.dumps`,
which raises `TypeError: Object of type UUID is not JSON serializable` (confirmed empirically).
When `ITRADER_JSON_LOGS` is enabled — i.e. production live mode, per CLAUDE.md "console (color)
or JSON renderer" — `_log_error_event` raises inside the logging call while trying to report a
failure. The old `str` correlation id serialized fine, so this is a regression introduced by
this phase.

Scope note: this does NOT affect the backtest golden oracle. Backtest uses the console renderer
and the error path never fires on a green run (documented carve-out at portfolio_handler.py:96-98).
The defect is live-mode-only, but it degrades error observability precisely when it matters most,
and it is a behavior change the phase did not intend.

(Pre-existing sibling: `portfolio_id` at full_event_handler.py:167 is also a UUID and has the
same latent issue — not introduced by this phase, but the fix below covers both.)

**Fix:** Make the JSON renderer UUID-safe at the serialization edge rather than stringifying
at every call site. In `itrader/logger.py`:
```python
import json, uuid

def _json_default(obj: object) -> str:
    if isinstance(obj, uuid.UUID):
        return str(obj)
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")

log_renderer = structlog.processors.JSONRenderer(
    serializer=lambda obj, **kw: json.dumps(obj, default=_json_default, **kw)
)
```
Alternatively, coerce at the log boundary in `_log_error_event` (`"correlation_id": str(event.correlation_id) if event.correlation_id else None`), but the renderer-level fix also closes the `portfolio_id` gap.

## Info

### IN-01: get_exchange_info now emits raw Decimal while get_config_dict still emits float (serialization inconsistency)

**File:** `itrader/execution_handler/exchanges/simulated.py:463-464` vs `624-625`

**Issue:** Removing `float(...)` from the `_min_order_size`/`_max_order_size` caches (init at
102-103, re-derive at 609-610) silently changed the output type of the public
`get_exchange_info()` serialization dict, which now exposes `Decimal` objects:
```python
'limits': {
    'min_order_size': self._min_order_size,   # was float, now Decimal
    'max_order_size': self._max_order_size
},
```
Meanwhile `get_config_dict()` at 624-625 still wraps the same config values in `float(...)`.
So two sibling serialization methods on the same class now report the size limits with different
types. No production consumer of `get_exchange_info` exists (only `test_exchange_info`, which
does not assert the value type, so the suite stays green), but the divergence is a latent
correctness/serialization trap: anything that JSON-encodes `get_exchange_info` output will hit
the same `Decimal`-not-serializable wall as WR-01.

**Fix:** Pick one convention for the serialization edge. Since CLAUDE.md says `float()` belongs
only at the serialization/logging edge, prefer floating both serializer dicts:
```python
'limits': {
    'min_order_size': float(self._min_order_size),
    'max_order_size': float(self._max_order_size),
},
```
(The caches themselves correctly stay Decimal — only the serialized view should float.)

### IN-02: stale "float" comment after Decimal type change in modify_order

**File:** `itrader/order_handler/order_manager.py:1133-1134`

**Issue:** The comment still reads "coerce the **float** modify args at this boundary" although
`new_price`/`new_quantity` are now typed `Optional[Decimal]`:
```python
# Apply the modification. Order money is Decimal (M2a); coerce the
# float modify args at this boundary.
success = order.modify_order(
    to_money(new_price) if new_price is not None else None,
    ...)
```
The `to_money()` call is still correct and value-preserving for a Decimal input, but the comment
now misdescribes the argument type and will mislead future readers about whether a float can
still arrive here.

**Fix:** Update the comment to reflect the Decimal contract, e.g. "normalize the Decimal modify
args through the money entry point at this boundary" (or drop the "float" word).

---

_Reviewed: 2026-06-11_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_

---
phase: 02-locked-decision-conformance
fixed_at: 2026-06-11T00:00:00Z
review_path: .planning/phases/02-locked-decision-conformance/02-REVIEW.md
iteration: 1
findings_in_scope: 3
fixed: 3
skipped: 0
status: all_fixed
---

# Phase 2: Code Review Fix Report

**Fixed at:** 2026-06-11
**Source review:** .planning/phases/02-locked-decision-conformance/02-REVIEW.md
**Iteration:** 1

**Summary:**
- Findings in scope: 3 (fix_scope=all — includes Info findings)
- Fixed: 3
- Skipped: 0

## Fixed Issues

### WR-01: correlation_id UUID breaks JSON-renderer error logging in live mode

**Files modified:** `itrader/logger.py`, `tests/unit/core/test_logger_config.py`
**Commit:** c353122
**Applied fix:** Made the JSON renderer UUID-safe at the serialization edge rather than
stringifying at every call site, preserving the single-UUIDv7 scheme (DEC-03) — the
`CorrelationId` UUID type was NOT reverted. Added a module-level `_json_default(obj)` that
stringifies `uuid.UUID` and re-raises `TypeError` for other types, plus a
`_uuid_safe_json_serializer(obj, **kw)` wrapper wired into
`structlog.processors.JSONRenderer(serializer=...)`.

Implementation note: structlog's `JSONRenderer` injects its own `default` handler into the
serializer kwargs, so naively passing `default=_json_default` to `json.dumps` raised
`TypeError: json.dumps() got multiple values for keyword argument 'default'`. The wrapper pops
structlog's `default` from `kw` and chains it after `_json_default`, so both the UUID coercion
and structlog's native fallback keep working. This single renderer-level fix also closes the
latent `portfolio_id` UUID gap noted in the finding.

Added three tests: `_json_default` stringifies UUID, `_json_default` rejects other types, and a
full `JSONRenderer` render of a `uuid.UUID` `correlation_id` produces valid JSON with the UUID
as a string.

### IN-01: get_exchange_info emitted raw Decimal while get_config_dict emitted float

**Files modified:** `itrader/execution_handler/exchanges/simulated.py`
**Commit:** fd688cf
**Applied fix:** Wrapped `min_order_size`/`max_order_size` in `float(...)` inside the
`get_exchange_info()` `limits` dict, matching the existing `float(...)` convention in the sibling
`get_config_dict()`. Per CLAUDE.md money policy, `float()` belongs only at the
serialization/logging edge — the `_min_order_size`/`_max_order_size` caches themselves correctly
remain `Decimal`; only the serialized view is floated. Tab indentation preserved (handler module).

### IN-02: stale "float" comment after Decimal type change in modify_order

**Files modified:** `itrader/order_handler/order_manager.py`
**Commit:** 6c404f0
**Applied fix:** Updated the comment at the `modify_order` money boundary from "coerce the float
modify args at this boundary" to "normalize the Decimal modify args through the money entry point
at this boundary", reflecting the `Optional[Decimal]` contract of `new_price`/`new_quantity`.
Comment-only change; no behavior change. Tab indentation preserved.

## Verification

All fixes verified against the phase's behavior-preserving constraints.

**Golden oracle (byte-exact preserved):**
```
poetry run pytest tests/integration -q
============================= 12 passed in 12.09s ==============================
```
`tests/integration/test_backtest_oracle.py` passed (134 trades / final_equity 46189.87730727451
unchanged — the error path the WR-01 fix touches never fires on a green backtest run, and the
IN-01/IN-02 changes are serialization/comment-only).

**mypy --strict (clean):**
```
poetry run mypy itrader
Success: no issues found in 139 source files
```

**Full test suite:**
```
poetry run pytest -q
============================= 814 passed in 14.11s =============================
```

No findings skipped. No source files left in a broken state. No uncommitted source changes remain.

---

_Fixed: 2026-06-11_
_Fixer: Claude (gsd-code-fixer)_
_Iteration: 1_

---
phase: 02-locked-decision-conformance
reviewed: 2026-06-11T00:00:00Z
depth: standard
files_reviewed: 13
files_reviewed_list:
  - itrader/order_handler/order_handler.py
  - itrader/order_handler/order_manager.py
  - itrader/execution_handler/exchanges/simulated.py
  - itrader/core/ids.py
  - itrader/outils/id_generator.py
  - itrader/events_handler/events/error.py
  - itrader/portfolio_handler/portfolio_handler.py
  - itrader/logger.py
  - tests/unit/order/test_order_manager.py
  - tests/unit/execution/exchanges/test_simulated_exchange.py
  - tests/unit/portfolio/test_portfolio_handler.py
  - tests/unit/core/test_logger_config.py
  - tests/e2e/conftest.py
findings:
  critical: 0
  warning: 0
  info: 2
  total: 2
status: issues_found
---

# Phase 02: Code Review Report

**Reviewed:** 2026-06-11
**Depth:** standard
**Files Reviewed:** 13
**Status:** issues_found (2 Info only — fixes confirmed correct)

## Summary

Iteration-2 re-review of the three fixes applied in the `--fix --auto` loop
(c353122 WR-01 UUID-safe JSON serializer in `logger.py`; fd688cf IN-01/IN-02
`float()` size limits in `get_exchange_info`; 6c404f0 IN-02 stale comment in
`order_manager.modify_order`).

All three fixes are correct and introduced no new defects. Verification
performed:

- **logger.py WR-01:** Confirmed against the installed structlog source that
  `JSONRenderer.__init__` does `dumps_kw.setdefault("default", _json_fallback_handler)`
  and calls `serializer(event_dict, **self._dumps_kw)`. The fix correctly
  `pop`s the injected `default` out of `**kw` and chains it after `_json_default`,
  so there is NO duplicate-`default` `TypeError` and structlog's native
  `__structlog__`/`repr` fallback survives. Exercised four ways at runtime:
  UUID coercion with structlog's default present, with `__structlog__` objects,
  with extra kwargs (`indent`) passing through, and the defensive no-`default`
  branch (re-raises `TypeError` correctly). Console-renderer mode is untouched —
  the serializer is wired only inside the `if json_logs:` branch.
- **simulated.py IN-01/IN-02:** `get_exchange_info()['limits']` now emits
  `float(...)` for `min_order_size`/`max_order_size`, matching `get_config_dict`.
  Decimal end-to-end on the hot path is preserved (`_min_order_size`/
  `_max_order_size` cached as Decimal; `validate_order` runs Decimal-vs-Decimal).
  `float()` appears only at this serialization edge — compliant with money policy.
- **order_manager.py IN-02:** Comment correctly updated from "coerce the float
  modify args" to "normalize the Decimal modify args"; the code already routes
  through `to_money(...)` (the documented Decimal entry point) — comment now
  matches behavior.

**Gates re-run and green:** golden oracle byte-exact
(`tests/integration/test_backtest_oracle.py` 3 passed — 134 trades /
46189.87730727451 unchanged); `mypy --strict` clean on all four modified source
files; full unit suite 744 passed (including the 113 tests across the four
modified test files).

The single-UUIDv7 scheme (`ids.py`, `id_generator.py`) and the frozen
`ErrorEvent`/`PortfolioErrorEvent` hierarchy (`error.py`) are unchanged and
conformant. No BLOCKER or WARNING findings. Two pre-existing Info-level
consistency notes are recorded below; neither was in the prior fix scope and
neither affects correctness, determinism, money policy, or the oracle.

## Info

### IN-01: Residual Decimal/float serialization inconsistency in exchange config dicts

**File:** `itrader/execution_handler/exchanges/simulated.py:480`, `:627-632`
**Issue:** The IN-02 fix normalized only the `get_exchange_info()['limits']`
block to `float()`. Two sibling serialization sites still emit raw `Decimal`
objects, so the same diagnostic dicts mix `float` and `Decimal` value types:
- `get_exchange_info()['statistics']['total_volume']` (line 480) — raw `Decimal`,
  while peer money fields in the same method are now `float`.
- `get_config_dict()` `fee_rate`/`maker_rate`/`taker_rate`/`base_slippage_pct`/
  `slippage_pct` (lines 627-632) — raw `Decimal`, while `failure_rate`/
  `min_order_size`/`max_order_size` in the same dict are `float`.

This is NOT a correctness or money-policy defect: both methods are
diagnostic/serialization helpers with no production consumer
(`get_config_dict` is called only by `portfolio.to_dict` for the portfolio
config, not the exchange; the exchange dicts are exercised only by unit tests),
and the unit test only asserts the float-ness of `min_order_size`/`failure_rate`.
A downstream `json.dumps` of either dict would still raise on the raw-Decimal
fields, so the inconsistency is latent. Flagged for awareness, not as a blocker.
**Fix:** For full internal consistency, wrap the remaining money fields at the
same serialization edge:
```python
# get_exchange_info statistics block
'total_volume': float(self._total_volume),
# get_config_dict
'fee_rate': float(self.config.fee_model.fee_rate) if self.config.fee_model.fee_rate is not None else None,
'maker_rate': float(self.config.fee_model.maker_rate) if self.config.fee_model.maker_rate is not None else None,
# ...and the other Decimal rate fields, guarding None
```
Defer if these helpers are slated for removal; not required for the phase.

### IN-02: Stale `order_id: int` / `portfolio_id: int` type hints under the single-UUIDv7 scheme

**File:** `itrader/order_handler/order_handler.py:121,131,158,167,222,228,240,274,290,308,326` and `itrader/order_handler/order_manager.py:1087,1094,1100,1175,1182`
**Issue:** Phase 02 locks the single-UUIDv7 ID scheme (D-12/D-13 — ids are
`uuid.UUID`, the integer scheme is deleted). The `OrderHandler`/`OrderManager`
public API still annotates `order_id: int` and `portfolio_id: int` (and the
docstrings say "The ID of the order to modify : int"), while the e2e harness and
`PortfolioHandler` pass native `uuid.UUID` order/portfolio ids through these
exact methods (`tests/e2e/conftest.py:267-273` calls
`cancel_order(order.id, portfolio_id)` with UUIDs). The mismatch is silent
because these symbols are routed through dict lookups (not arithmetic) and the
order-handler module is not in mypy's strict file set on this path, but the
annotation now actively misleads a reader about the locked ID contract.
**Fix:** Retype to the nominal id aliases (or `Any` bridge, matching
`PortfolioHandler`'s deferred-retype note at portfolio_handler.py:70-73):
```python
def modify_order(self, order_id: OrderId, ..., portfolio_id: Optional[PortfolioId] = None, ...)
```
and update the corresponding "int" docstring lines. Tracking-only — the
portfolio_id retype is explicitly deferred per the documented carry-over.

---

_Reviewed: 2026-06-11_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_

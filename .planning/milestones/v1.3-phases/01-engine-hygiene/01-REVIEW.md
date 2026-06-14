---
phase: 01-engine-hygiene
reviewed: 2026-06-12T00:00:00Z
depth: standard
files_reviewed: 8
files_reviewed_list:
  - itrader/core/money.py
  - itrader/core/sizing.py
  - itrader/order_handler/sizing_resolver.py
  - itrader/order_handler/brackets/levels.py
  - itrader/portfolio_handler/portfolio.py
  - itrader/portfolio_handler/validators.py
  - itrader/order_handler/reconcile/reconcile_manager.py
  - tests/unit/portfolio/test_position_manager.py
findings:
  critical: 0
  warning: 2
  info: 3
  total: 5
status: issues_found
---

# Phase 01: Code Review Report

**Reviewed:** 2026-06-12T00:00:00Z
**Depth:** standard
**Files Reviewed:** 8
**Status:** issues_found

## Summary

This is a behavior-preserving engine-hygiene phase (HYG-01). The diff against
`a703532` consists of: (1) consolidating three module-private `_ONE = Decimal("1")`
copies (`core/sizing.py`, `order_handler/sizing_resolver.py`,
`order_handler/brackets/levels.py`) into a single public `core.money.ONE`;
(2) rewriting `test_position_manager.py` asserts from the private `pm._storage.*`
accessors to the public `pm.get_all_positions()` / `pm.get_closed_positions()`
query APIs; (3) removing a stale `mypy` override for the already-deleted
`events_handler.screener_event_handler` module; (4) removing the dead
`TOLERANCE = 1e-3` constant from `portfolio.py`; (5) retyping the
`PortfolioValidator.validate_transaction_data` signature/`isinstance` checks from
`float` to `decimal.Decimal`; and (6) a docstring-only clarification in
`reconcile_manager.py`.

Verification performed:
- `mypy --strict` is clean on the 5 in-scope production files touched.
- All 19 tests in `test_position_manager.py` pass; the new public-API asserts are
  exact delegations to the old `_storage` calls (`get_all_positions()` ->
  `_storage.get_positions()`, `get_closed_positions()` -> `_storage.get_closed_positions()`),
  so the rewrite is behavior-equivalent.
- No import cycle is introduced by `core.sizing` -> `core.money` (`money.py` imports
  stdlib only; `core/enums` and `core/exceptions` do not import `money`). Imports
  of the three consumer modules + `ONE` succeed at runtime.
- `Decimal("1") == ONE` is `True`, so the `exit_fraction == ONE` no-op equality
  check in `resolve_exit` is unaffected by the consolidation.
- No leftover `_ONE` or `TOLERANCE` references remain anywhere; `Decimal` imports
  are still required in `sizing_resolver.py` and `levels.py` (used in annotations),
  so no unused-import was introduced.
- The removed mypy override targeted a file that no longer exists on disk and is
  imported nowhere — the override was genuinely stale and safe to remove.
- The `reconcile_manager.py` docstring change is code-free and its claim is
  accurate: `from ..brackets import BracketBook` (line 41) triggers
  `brackets/__init__.py`, which imports `BracketManager` at line 10, so the class
  IS loaded at runtime regardless of the `TYPE_CHECKING` guard.

The consolidation, dead-constant removal, override removal, test rewrite, and doc
fix are all correct and behavior-preserving. The two findings below concern the
validator retype, which lands on dead code and silently narrows accepted types.

## Warnings

### WR-01: Validator retype narrows accepted types and rejects `int`, on a module with zero callers

**File:** `itrader/portfolio_handler/validators.py:36-43`
**Issue:** The retype changed the runtime guards from
`isinstance(price, (int, float))` to `isinstance(price, decimal.Decimal)` for
`price`, `quantity`, and `commission`. This is not a pure annotation change — it
is a **behavioral narrowing**. The old check accepted `int` and `float`; the new
check accepts ONLY `decimal.Decimal` and now **rejects plain `int`** (e.g.
`price=50000`, `commission=0`), which are commonly used at construction sites.
Any future caller that passes an `int` quantity/commission (legal across much of
the engine) would now raise `InvalidTransactionError` where it previously passed.

This is latent rather than live because the entire module is currently dead code
(see WR-02), so no caller is affected today. But the change ships a stricter
runtime contract than the surrounding codebase assumes, which will surface as a
spurious rejection if the validator is ever wired in. Money is `Decimal`
end-to-end, but `int` is a valid Decimal-domain entry value that the project's
`to_money` path accepts (`Decimal(str(1))`).

**Fix:** Either keep the runtime guard tolerant of the int that the engine
routinely produces, or document that callers must pre-normalize to Decimal. If
strict-Decimal-only is the intended contract, retain it but add an explicit note
and a test pinning the rejection of non-Decimal inputs:
```python
if not isinstance(price, decimal.Decimal) or price <= 0:
    # NOTE: int is intentionally rejected — callers must enter the Decimal
    # domain via to_money() before validation.
    raise InvalidTransactionError(f"Price must be a positive Decimal, got {price!r}")
```

### WR-02: Retyped validator is fully dead code — the fix decorates an unreachable module

**File:** `itrader/portfolio_handler/validators.py:16-158`
**Issue:** `PortfolioValidator` (and `PositionValidator`) have **zero importers**
across `itrader/` and `tests/` — `grep` for `PortfolioValidator`,
`PositionValidator`, and every `validators`-module import path returns nothing
outside the file itself. `validate_transaction_data` (the method retyped this
phase), `validate_portfolio_data`, `validate_sufficient_funds`,
`validate_cash_balance`, `to_decimal`, `from_decimal`, and the entire
`PositionValidator` are unreachable. The phase invests in retyping a method that
can never execute, while the module's other still-`float`-typed surfaces
(`validate_portfolio_data(cash: float)` at line 60, `PositionValidator` taking
`float` args at lines 131-134, `to_decimal(value: Union[int, float])` at line 117)
were left inconsistent — so the file now mixes a Decimal-strict method with
float-typed siblings, which is worse for the next reader than a uniformly stale
module.

**Fix:** Prefer deleting the dead module (or the dead methods) over retyping them;
a Decimal retype on unreachable code carries maintenance cost without behavioral
value. If the module is being kept as a planned future seam, retype it
consistently (all money args to `Decimal`) rather than one method, and add a
docstring noting it is not yet wired so a reviewer does not assume it is live.

## Info

### IN-01: `ONE` is exported but absent from `core/money.py`'s public surface contract

**File:** `itrader/core/money.py:27-30`
**Issue:** `ONE` is now a cross-module public constant (imported by `core/sizing.py`,
`sizing_resolver.py`, and `brackets/levels.py`), but `money.py` defines no
`__all__`, so the public surface is implicit. The sibling module `core/sizing.py`
does declare `__all__`. Relying on implicit export for a constant that is now a
documented shared primitive is slightly inconsistent with the module's own
"single canonical public money primitive" framing.

**Fix:** Add `__all__ = ["ONE", "to_money", "quantize"]` to `money.py` to pin the
intended public surface, matching the `__all__` convention used in `core/sizing.py`
and `sizing_resolver.py`.

### IN-02: `exit_fraction`/slippage `Decimal("1")` literals not consolidated to `ONE`

**File:** `itrader/core/sizing.py:241`
**Issue:** The phase consolidated the three named `_ONE` constants but left
inline `Decimal("1")` literals that represent the same canonical value —
`exit_fraction: Decimal = Decimal("1")` (`sizing.py:241`, `signal.py:93`,
`signal_record.py:81`, `base.py:133/151`) and the slippage-factor neutrals
(`fixed_slippage_model.py:95`, `linear_slippage_model.py:111`,
`zero_slippage_model.py:44`, `simulated.py:207/228`). This is consistent with the
phase's stated scope (only the three *named* `_ONE` constants), so it is not a
defect, but the "single canonical money primitive" goal is only partially
realized. Dataclass field defaults in particular cannot mechanically swap to `ONE`
without confirming evaluation-time semantics.

**Fix:** Out of scope for this phase. If full consolidation is desired later, swap
the slippage/`simulated` neutrals to `ONE` first (plain expressions, trivially
safe); evaluate the dataclass-default swaps separately since `Decimal("1") == ONE`
holds but the literal default is also a documentation anchor (D-07).

### IN-03: `validate_transaction_data` upper-bound checks compare Decimal against bare int magic numbers

**File:** `itrader/portfolio_handler/validators.py:49-53`
**Issue:** After the retype, `price > 1_000_000` and `quantity > 1_000_000`
compare a `decimal.Decimal` against a bare `int` literal. Decimal-vs-int
comparison is well-defined in Python so this is correct, but the `1_000_000`
magic numbers are undocumented sanity bounds in the same method that was just
made Decimal-strict. (Same dead-code caveat as WR-02 applies.)

**Fix:** If the module is kept, hoist the bounds to named module constants
(e.g. `_MAX_REASONABLE_PRICE = decimal.Decimal("1000000")`) so the Decimal domain
is consistent and the thresholds are named.

---

_Reviewed: 2026-06-12T00:00:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_

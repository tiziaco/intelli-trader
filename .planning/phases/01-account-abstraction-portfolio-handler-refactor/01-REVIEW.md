---
phase: 01-account-abstraction-portfolio-handler-refactor
reviewed: 2026-07-01T00:00:00Z
depth: standard
files_reviewed: 17
files_reviewed_list:
  - itrader/portfolio_handler/account/base.py
  - itrader/portfolio_handler/account/venue.py
  - itrader/portfolio_handler/account/simulated.py
  - itrader/portfolio_handler/account/__init__.py
  - itrader/connectors/base.py
  - itrader/connectors/__init__.py
  - itrader/portfolio_handler/portfolio.py
  - itrader/portfolio_handler/portfolio_handler.py
  - itrader/portfolio_handler/cash/__init__.py
  - itrader/portfolio_handler/storage/sql_storage.py
  - itrader/portfolio_handler/validators.py
  - itrader/reporting/cash_operations.py
  - itrader/core/enums/portfolio.py
  - itrader/trading_system/__init__.py
  - itrader/trading_system/backtest_trading_system.py
  - itrader/trading_system/system_spec.py
  - scripts/run_backtest.py
findings:
  critical: 0
  warning: 2
  info: 3
  total: 5
status: issues_found
---

# Phase 01: Code Review Report

**Reviewed:** 2026-07-01
**Depth:** standard
**Files Reviewed:** 17
**Status:** issues_found

## Summary

Reviewed the account-abstraction refactor that extracted `SimulatedCashAccount` /
`SimulatedMarginAccount` from the deleted `CashManager`, re-pointed `Portfolio` and
`PortfolioHandler` onto the new account leaf, stripped `user_id`, and deleted
`cash_manager.py`. The oracle-critical backtest path (spot, no margin) is clean —
the byte-exact constraint was preserved. No critical correctness defects exist on
the golden path.

Two warnings concern the margin/liquidation surface, which is oracle-dark but will
become the first live-mode crash vector once margin portfolios are wired in Phase 2
or beyond. Three info items are pre-existing verbatim code-motion artefacts or minor
inconsistencies in explicitly-unwired seams.

---

## Warnings

### WR-01: `add_portfolio` does not propagate `_universe` to newly-created margin accounts when called after `set_universe`

**File:** `itrader/portfolio_handler/portfolio_handler.py:153-199` (and `set_universe` at line 328)

**Issue:** `set_universe` iterates every existing portfolio and calls `account.set_universe(universe)` for each margin leaf (lines 344-348). However, `add_portfolio` stores the new `Portfolio` directly and never checks whether `self._universe` is already set. If `add_portfolio` is called **after** `set_universe` — which is the standard live/API pattern (the system starts, universe is built, then a new portfolio is opened) — the new margin account's `_universe` stays `None`.

The resulting failure is latent but deterministic: on the very next BAR that has any position in that portfolio, `_run_liquidation_pass` proceeds (it only checks the **handler's** `self._universe`, which is not None), calls `_collect_breaches_over_prices`, which also only checks the handler's `_universe`, and eventually calls `account._liq_inputs(position)` which dereferences `account._universe` directly at line 915 of `simulated.py` — `AttributeError: 'NoneType' object has no attribute 'instrument'`.

In the backtest golden path this is safe because all portfolios are added before the Trap-4 `set_universe` call. In any scenario where a margin portfolio is added after universe setup (live mode, API, test that wires universe first), the run crashes on the first liquidation-pass tick.

**Fix:** In `add_portfolio`, after storing the new portfolio, propagate the universe if already set:

```python
# After self._portfolios[portfolio.portfolio_id] = portfolio
account = portfolio.account
if self._universe is not None and isinstance(account, SimulatedMarginAccount):
    account.set_universe(self._universe)
```

This mirrors the existing `set_universe` propagation loop and closes the gap for portfolios added after universe setup.

---

### WR-02: `SimulatedMarginAccount._liq_inputs` dereferences `self._universe` without a None guard — inconsistent with `maintenance_margin`

**File:** `itrader/portfolio_handler/account/simulated.py:914-915`

**Issue:** `maintenance_margin()` has an explicit guard:

```python
if positions and self._universe is None:
    raise StateError(...)
```

`_liq_inputs` has no such guard — it calls `self._universe.instrument(position.ticker)` directly at line 915 with no prior None check. Because `_liq_inputs` is invoked only inside the breach-detection loop in `_collect_breaches_over_prices`, which checks the **handler's** `self._universe` (not the account's), the account-level None state is never screened before the call.

The practical failure mode is identical to WR-01: an account constructed with `_universe = None` (because `add_portfolio` was called after `set_universe`) will crash with an opaque `AttributeError` rather than the informative `StateError` that `maintenance_margin` raises. This is an inconsistency in the defensive-programming discipline — one public method is protected, the sibling is not.

**Fix:** Add the same guard as `maintenance_margin`:

```python
def _liq_inputs(self, position: Position) -> "tuple[Decimal, Decimal, Decimal]":
    if self._universe is None:
        raise StateError(
            position.id,
            "universe-unwired",
            required_state="universe-wired (call set_universe)",
            operation="_liq_inputs",
        )
    wb = self.get_locked_margin_for(str(position.id))
    instrument = self._universe.instrument(position.ticker)
    ...
```

This converts the latent `AttributeError` into the domain `StateError` that the rest of the codebase expects, and removes the asymmetry between `maintenance_margin` and `_liq_inputs`.

---

## Info

### IN-01: `get_cash_operations(limit=0)` silently returns all operations instead of zero — verbatim code-motion bug preserved

**File:** `itrader/portfolio_handler/account/simulated.py:511`

**Issue:** The guard `if limit:` is falsy when `limit=0`. A caller passing `limit=0` to mean "return no operations" instead receives the full unrestricted list. This is a pre-existing bug in `CashManager` preserved verbatim by the D-05 byte-exact code-motion constraint. It is low-impact (no known caller passes `limit=0`) but is a latent correctness trap.

**Fix:** Change `if limit:` to `if limit is not None:` at line 511. This correctly handles the `limit=0` edge case while preserving the `limit=None` (no restriction) default.

---

### IN-02: Dead variable `old_state` in `Portfolio.set_state`

**File:** `itrader/portfolio_handler/portfolio.py:147`

**Issue:**

```python
old_state = self._state   # captured …
self._state = new_state
self._state_transitions.append((new_state, datetime.now(UTC)))  # … never used
```

`old_state` is assigned but never read; it was presumably intended for the log call or for a state-changed event payload, neither of which materialised. The variable adds noise and misleads a reader into searching for the use site.

**Fix:** Remove the `old_state = self._state` line (line 147). The mutation and the history append are self-contained and need no local capture.

---

### IN-03: `validators.py:validate_portfolio_data` accepts `cash=0` while `add_portfolio` rejects `cash <= 0` — inconsistency in the explicitly-unwired seam

**File:** `itrader/portfolio_handler/validators.py:97-98`

**Issue:** The module header documents that this is "a NOT-YET-WIRED seam … every method here is unreachable on the live run path." Despite being unwired, `validate_portfolio_data` checks `if not isinstance(cash, (int, float)) or cash < 0` — accepting zero — while `add_portfolio` raises `PortfolioValidationError` when `cash <= 0`. If this seam is ever wired without updating the validator, a `cash=0` call would pass validation but fail in `add_portfolio`, producing a confusing layered error. The inconsistency is low-impact today given the seam is unwired, but degrades the correctness contract of the validator at the moment it is connected.

**Fix:** Change the cash check in `validate_portfolio_data` to match `add_portfolio`'s stricter policy:

```python
if not isinstance(cash, (int, float)) or cash <= 0:
    raise InvalidTransactionError(f"Initial cash must be positive, got {cash}")
```

---

_Reviewed: 2026-07-01_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_

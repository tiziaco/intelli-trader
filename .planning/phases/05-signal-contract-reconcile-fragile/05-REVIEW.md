---
phase: 05-signal-contract-reconcile-fragile
reviewed: 2026-06-13T00:00:00Z
depth: standard
files_reviewed: 24
files_reviewed_list:
  - itrader/core/sizing.py
  - itrader/events_handler/events/order.py
  - itrader/order_handler/admission/admission_manager.py
  - itrader/order_handler/brackets/bracket_book.py
  - itrader/order_handler/brackets/bracket_manager.py
  - itrader/order_handler/brackets/levels.py
  - itrader/order_handler/order.py
  - itrader/order_handler/order_validator.py
  - itrader/order_handler/reconcile/reconcile_manager.py
  - itrader/reporting/orders.py
  - itrader/strategy_handler/base.py
  - itrader/strategy_handler/signal_record.py
  - itrader/strategy_handler/strategies_handler.py
  - scripts/cross_validate_limit.py
  - scripts/crossval/backtesting_py_limit_run.py
  - scripts/crossval/backtrader_limit_run.py
  - scripts/crossval/limit_entry_strategy.py
  - tests/e2e/matching/entries/limit_entry_crossval/scenario.py
  - tests/e2e/matching/entries/limit_entry_crossval/test_scenario.py
  - tests/e2e/strategies/scripted_emitter.py
  - tests/unit/core/test_sizing.py
  - tests/unit/order/test_action_side_typing.py
  - tests/unit/order/test_admission_snapshot.py
  - tests/unit/order/test_reconcile_manager.py
  - tests/unit/strategy/test_signal_factories.py
findings:
  critical: 0
  warning: 4
  info: 5
  total: 9
status: issues_found
---

# Phase 5: Code Review Report

**Reviewed:** 2026-06-13
**Depth:** standard
**Files Reviewed:** 24
**Status:** issues_found

## Summary

Reviewed the Phase 5 signal-contract + reconcile-extraction changeset: the typed
sizing vocabulary (`core/sizing.py`), the `OrderEvent`/`SignalEvent` Side narrowing,
the four extracted order-handler collaborators (`AdmissionManager`,
`BracketManager`/`BracketBook`/`levels`, `ReconcileManager`), the validator, the
strategy authoring surface, and the LIMIT-entry cross-validation scripts + e2e leaf.

The phase's load-bearing invariants hold up under adversarial tracing:

- **RECON-01 (idempotent terminal release in `finally`)** is intact:
  `should_release` is armed AFTER the terminal status and BEFORE further work
  (`reconcile_manager.py:222`); the `finally` runs `_release_reservation`
  (`:281`); the inner re-raise is correctly gated on `not body_raised` (`:316`)
  so a release failure never masks the original body exception. The unknown-status
  early-return holds the reservation (`:219`). All three terminal transitions
  release exactly once.
- **str→Side narrowing** is consistent: every comparison uses `is Side.X` /
  `in (Side.BUY, Side.SELL)`; no residual `.value` comparison bugs or string-literal
  comparisons against a `Side` were found. The serialization edge correctly emits
  `.value` (`reporting/orders.py:91`).
- **Money is Decimal end-to-end**: no `Decimal(float)` anywhere — every entry uses
  `to_money` or `Decimal(str(...))`, including all three cross-val script runners.
- **Determinism**: no wall-clock / unseeded `random` use; timestamps are
  event-derived; the crafted strategy is a pure date-keyed lookup.
- **SCRIPT-ONLY isolation**: confirmed by grep — no file under `tests/` imports
  `backtesting`/`backtrader` or any `*_limit_run` runner. Only
  `limit_entry_strategy.py` (itrader-only imports) is shared into `tests/`, which
  is the documented-safe carve-out.
- **Indentation**: every reviewed file is internally consistent (order/strategy
  handlers tabs; core/events/reporting/scripts/tests 4-space). No mixed-indentation
  defect. (`order_handler/order_validator.py` is 4-space rather than the tab house
  style, but it is internally consistent and not modified to a mixed state — noted as Info.)

No BLOCKER-tier defects found. The findings below are robustness, dead-code, and
maintainability concerns.

## Warnings

### WR-01: `_classify()` result is computed but never used — latent divergence hazard

**File:** `itrader/order_handler/reconcile/reconcile_manager.py:206`
**Issue:** `terminal, _transition = self._classify(fill_event.status)` assigns two
locals that are never read. The actual terminal-ness decision is duplicated in the
`if/elif/elif/else` chain immediately below (`:207-219`). The `_classify` helper
exists "for READABILITY only" per its docstring, but a helper whose return value is
discarded is worse than no helper: a future edit that changes the FillStatus→terminal
mapping in `_classify` (e.g. adding `EXPIRED`) without also editing the dispatch chain
(or vice-versa) creates a silent inconsistency, and `_classify` will read as the
authority while the chain is what actually runs. This is exactly the "two sources of
truth for the same fact" pattern. Either consume the result or delete the call.
**Fix:**
```python
# Option A — make _classify load-bearing (single source of truth):
terminal, _transition = self._classify(fill_event.status)
if not terminal:
    self.logger.warning('Unhandled fill status %s for order %s; order left active',
                        fill_event.status, order_id)
    return out_events
if fill_event.status == FillStatus.EXECUTED:
    applied = self._apply_executed(order, fill_event, order_id)
elif fill_event.status == FillStatus.CANCELLED:
    self._apply_cancelled(order)
else:  # REFUSED — the only remaining terminal status
    self._apply_refused(order)
should_release = True
# Option B — if the chain must stay authoritative, delete the dead _classify call.
```

### WR-02: `assert intent.entry_price is not None` is stripped under `-O`, can build a `SignalEvent(price=None)`

**File:** `itrader/strategy_handler/strategies_handler.py:154`
**Issue:** For a non-MARKET intent the code relies on a bare `assert` to narrow
`entry_price` from `Decimal | None` to `Decimal` before constructing the
`SignalEvent`. Python's `assert` is removed when the interpreter runs with `-O`
(`PYTHONOPTIMIZE`). If a typed factory invariant is ever violated (a hand-built
intent, a future factory bug) under `-O`, this silently constructs
`SignalEvent(price=None)` — a `None` flowing into a field typed `Decimal`, which
then propagates into sizing/admission and corrupts the run with a non-Decimal money
value instead of failing loudly. The codebase's stated philosophy is "fail loud"
(D-06). Use an explicit raise.
**Fix:**
```python
else:
    if intent.entry_price is None:
        raise ValueError(
            f"non-MARKET intent for {ticker} missing entry_price "
            f"(order_type={intent.order_type})")
    entry_price = intent.entry_price
```

### WR-03: `OrderEvent.__str__` treats `stop_price == Decimal("0")` as absent

**File:** `itrader/events_handler/events/order.py:67`
**Issue:** `if self.stop_price:` is a truthiness test on a `Decimal`. A legitimate
`stop_price` of `Decimal("0")` (or `Decimal("0.00")`) is falsy, so the stop segment
is silently dropped from the string representation, making the log/debug output
misrepresent the order. While a zero stop price is unusual, the entity allows it
(`stop_price: Decimal | None`), and `__str__`/`__repr__` are used in error logs and
audit trails where an accurate, non-misleading rendering matters. Test the sentinel
explicitly.
**Fix:**
```python
if self.stop_price is not None:
    base += f", stop: {round(self.stop_price, 4)}"
```

### WR-04: `_estimate_commission` trusts the injected estimator to return Decimal — float would silently poison the reservation

**File:** `itrader/order_handler/admission/admission_manager.py:83-85` (used at `:220`)
**Issue:** `_estimate_commission` returns `self.commission_estimator(order.quantity,
order.price)` with no money-domain normalization. The result is added directly into
the cash-reservation cost: `cost = primary.price * primary.quantity +
self._estimate_commission(primary)` (`:220`). If any injected estimator returns a
`float` (e.g. a percent-fee model computing `qty * price * 0.001`), this performs
`Decimal + float`, which raises `TypeError` in the reserve path — or, worse, if an
estimator returns a `Decimal` built from a float, it imports binary-float-repr error
into the reservation amount, violating the Decimal-end-to-end money policy at a
correctness-critical site. The module docstring asserts "Money is Decimal end-to-end
via `to_money`," but the estimator return is the one un-guarded money input.
Normalize at the boundary.
**Fix:**
```python
def _estimate_commission(self, order: Order) -> Decimal:
    if self.commission_estimator is None:
        return Decimal("0")
    return to_money(self.commission_estimator(order.quantity, order.price))
```

## Info

### IN-01: `BracketBook.__eq__` without `__hash__` makes instances unhashable

**File:** `itrader/order_handler/brackets/bracket_book.py:84-90`
**Issue:** Defining `__eq__` on a non-dataclass class implicitly sets `__hash__ =
None`, making `BracketBook` instances unhashable. This is currently harmless
(`BracketBook` is a mutable owner-object never used as a dict key or set member), but
it is an undocumented side effect of the dict-compat dunders added for
`test_sltp_policy.py`. If a future caller ever puts a `BracketBook` in a set/dict it
will get a non-obvious `TypeError`. Consider an explicit `__hash__ = None` with a
comment, or document that the object is intentionally unhashable.
**Fix:** Add `__hash__ = None  # mutable owner — intentionally unhashable` for intent clarity.

### IN-02: `cross_validate_limit.py` dereferences `spec`/`spec.loader` without a None guard

**File:** `scripts/cross_validate_limit.py:90-94`
**Issue:** `importlib.util.spec_from_file_location(...)` can return `None`, and
`spec.loader` can be `None`; `spec.loader.exec_module(cf)` (`:94`) would raise
`AttributeError` on a missing/relocated `tests/e2e/conftest.py` rather than a clear
error. This is a SCRIPT-ONLY evidence generator (not gating, not on the run path),
so impact is low, but a one-line guard yields a located failure if the conftest path
drifts.
**Fix:**
```python
spec = importlib.util.spec_from_file_location("e2e_conftest_limit", "tests/e2e/conftest.py")
if spec is None or spec.loader is None:
    raise RuntimeError("could not load tests/e2e/conftest.py for the LIMIT cross-val")
```

### IN-03: `_apply_executed` / `_apply_cancelled` / `_apply_refused` typed `order: Any`

**File:** `itrader/order_handler/reconcile/reconcile_manager.py:113, 142, 147, 284`
**Issue:** The reconcile arms and `_release_reservation` annotate `order` (and
`order_id`) as `Any`, defeating mypy on the very fragile, last-extracted module the
phase is most worried about. The concrete type is `Order` (imported transitively).
Tightening `order: "Order"` would let `--strict` catch a future typo against the
mirror API (e.g. a renamed `add_fill`) at check time rather than runtime. Verbatim
code-motion preserved the loose typing; this is a chance to harden the seam.
**Fix:** Annotate `order: "Order"` (forward-ref import under `TYPE_CHECKING`) on the arms and `_release_reservation`.

### IN-04: `order_validator.py` uses 4-space indentation inside the tab-house `order_handler/` package

**File:** `itrader/order_handler/order_validator.py` (entire file)
**Issue:** Per CLAUDE.md the `order_handler/` handler modules use tabs, but
`order_validator.py` is 4-space throughout. The file is internally consistent (0
tabs), so this is NOT a mixed-indentation defect and the "match the file you edit"
rule means it should stay 4-space. Flagged only so the inconsistency with the
sibling tab modules is on record — do not normalize.
**Fix:** None required; keep matching the file. (Documentation/awareness only.)

### IN-05: Strategy `__post_init__`-style `created_at`/`updated_at` default `None` with `# type: ignore` is fragile

**File:** `itrader/order_handler/order.py:64-65, 96-99`
**Issue:** `created_at`/`updated_at` are declared `field(default=None)  # type:
ignore[assignment]` and filled in `__post_init__` only when still `None`. This works,
but a caller who explicitly passes `created_at=None` (rather than omitting it) gets
the event-time default silently, and the `type: ignore` masks the declared-type lie
for the whole field. Consider `field(default=None, init=...)` semantics or a sentinel
to make "caller did not supply" unambiguous. Low priority — the run path always
omits them.
**Fix:** Optional — introduce a private sentinel instead of `None`-means-default, or document the init contract on the field.

---

_Reviewed: 2026-06-13_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_

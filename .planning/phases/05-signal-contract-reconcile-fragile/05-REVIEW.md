---
phase: 05-signal-contract-reconcile-fragile
reviewed: 2026-06-13T00:00:00Z
depth: standard
files_reviewed: 7
files_reviewed_list:
  - itrader/order_handler/reconcile/reconcile_manager.py
  - itrader/strategy_handler/strategies_handler.py
  - itrader/events_handler/events/order.py
  - itrader/order_handler/admission/admission_manager.py
  - itrader/order_handler/brackets/bracket_book.py
  - itrader/order_handler/order.py
  - scripts/cross_validate_limit.py
findings:
  critical: 0
  warning: 0
  info: 0
  total: 0
status: clean
fix_iterations: 3
resolved_findings: 9
---

> **Auto-fix loop converged (3 iterations).** Iteration 1: 4 WARNING + 5 INFO from the
> initial review — 8 fixed (WR-01..WR-04, IN-01, IN-02, IN-03, IN-05); IN-04 needs no
> change (4-space `order_validator.py` is intentional, do-not-normalize). Iteration 2:
> re-review confirmed all 8 resolved with no regressions, surfaced 1 new INFO (the WR-01
> refactor's bare `else` could mis-handle a future 4th terminal status). Iteration 3:
> that INFO fixed — the `on_fill` dispatch now has an explicit `elif REFUSED` + a
> fail-loud `else: raise NotImplementedError`. Final state: 0 open findings; mypy
> --strict clean (182 files), oracle byte-exact (134 / 46189.87730727451), full suite
> 978, reconcile invariant net green. The body below is the iteration-2 re-review record.

# Phase 5: Code Review Report (iteration 2 — re-review after auto-fix)

**Reviewed:** 2026-06-13
**Depth:** standard
**Files Reviewed:** 7
**Status:** issues_found

## Summary

Re-review of the 8 auto-fixes applied to the prior Phase 5 review
(WR-01..WR-04, IN-01, IN-02, IN-03, IN-05). All eight prior findings are
**RESOLVED**, and the fixes introduced **no BLOCKER-tier or WARNING-tier
regressions**. The single new item below is an Info-level latent coupling
introduced by the WR-01 refactor.

Verification performed:

- **mypy --strict clean** across all six in-scope `itrader/` modules
  (`reconcile_manager`, `bracket_book`, `admission_manager`,
  `strategies_handler`, `events/order`, `order`) — `Success: no issues found`.
  This confirms IN-01 (`__hash__: ClassVar[None]` pin) and IN-03
  (`order: "Order"` forward-ref) are strict-clean.
- **No circular import**: importing `reconcile_manager`, `bracket_book`,
  `admission_manager` together succeeds; the `Order`/`BracketManager`
  forward-refs sit under `TYPE_CHECKING` (IN-03).
- **Tests green**: 257 order+strategy unit tests pass, including the six
  reconcile-manager cases that explicitly cover the RECON-01 invariant
  (body-raise-still-releases, body-raise+release-failure-does-not-mask,
  unknown-status-holds-reservation, three happy-path single-release).
- **Indentation preserved**: every fixed line matches its file's house style
  (`strategies_handler`/`admission_manager` tabs; `events/order` 4-space;
  `bracket_book` tabs) — no mixed-indentation defect introduced.

Per-finding verification:

- **WR-01 (RECON-01 intact — BLOCKER-sensitive)** — VERIFIED SAFE. The fix
  (`reconcile_manager.py:207-221`) makes `_classify` load-bearing: `terminal`
  is consumed, the non-terminal case early-returns BEFORE `should_release` is
  armed (`:208-215`, reservation intentionally HELD), and the old `elif
  REFUSED` collapsed to a bare `else`. The arming point (`should_release =
  True`, `:224`) is still AFTER the terminal status and BEFORE further work;
  the `try`/`finally` release-once skeleton (`:200`/`:278-283`), the
  `_release_reservation` `should_release` guard (`:303`), and the `if not
  body_raised: raise` re-raise gate (`:318`) are byte-identical to pre-fix. The
  `applied=False` (add_fill-rejected) EXECUTED path still arms the release,
  skips `update_order`, and skips fill-anchored children — unchanged. The new
  `else`-is-REFUSED dispatch is correct because `_classify` already filtered to
  exactly `{EXECUTED, CANCELLED, REFUSED}` (see IN-01 below for the residual
  coupling note).
- **WR-04 (`_estimate_commission` `to_money` wrap)** — VERIFIED value-identity.
  `to_money(x) == Decimal(str(x))`; for a Decimal-returning estimator
  `Decimal(str(Decimal_v))` round-trips exactly (no double-normalization, no
  precision change), and a float-returning estimator now enters via the string
  path instead of poisoning the reserve with binary-float-repr or raising
  `Decimal + float`. The downstream `cost = price*qty + _estimate_commission`
  (`admission_manager.py:226`) is unaffected for the current Decimal estimator.
- **WR-02 (explicit raise replaces bare assert)** — RESOLVED. `strategies_handler.py:158-161`
  raises `ValueError` (survives `-O`) for a non-MARKET intent with
  `entry_price is None`; no `SignalEvent(price=None)` can be built.
- **WR-03 (`is not None` guard)** — RESOLVED + behaviorally confirmed:
  `OrderEvent.__str__` now renders the stop segment for `stop_price=Decimal("0")`
  (`events/order.py:70`).
- **IN-01 (`__hash__` pin)** — RESOLVED, mypy-clean (`bracket_book.py:100`,
  `__hash__: ClassVar[None] = None`); runtime `BracketBook.__hash__ is None`.
- **IN-02 (spec/loader None guard)** — RESOLVED (`cross_validate_limit.py:96-99`);
  SCRIPT-ONLY isolation intact (no `tests/`/`itrader/` import of the limit
  runners or reference engines).
- **IN-03 (`order: "Order"` forward-ref)** — RESOLVED, no circular import,
  mypy-clean.
- **IN-05 (init-contract documentation)** — addressed via the expanded
  `order.py:64-73` comment documenting the `None`-means-default init contract;
  the field shape is unchanged (intentionally, per the prior Info disposition).

## Narrative Findings (AI reviewer)

### Info

#### IN-01: WR-01 fix introduces a latent coupling between `_classify` terminal-set and the dispatch `else`

**File:** `itrader/order_handler/reconcile/reconcile_manager.py:216-221`
**Issue:** The WR-01 fix correctly made `_classify` the single source of truth
for *terminal-ness* (the early-return at `:208`), but the per-status dispatch
chain now ends in a bare `else:  # REFUSED` (`:220-221`) instead of the prior
explicit `elif fill_event.status == FillStatus.REFUSED`. This is correct today
**only because** `_classify` returns `terminal=True` for exactly
`{EXECUTED, CANCELLED, REFUSED}`, so after the non-terminal early-return the
`else` can only be REFUSED. However, the two are now coupled at a distance: if a
future edit adds a new terminal status to `_classify` (e.g. `EXPIRED ->
(True, OrderStatus.EXPIRED)`) without also adding a matching `elif` arm, that
status would silently fall into the REFUSED `else` and be reconciled as a
rejection (`_apply_refused` -> `reject_order`) — a wrong-mirror-transition bug
with no error. The prior explicit `elif REFUSED` + unknown-`else` shape failed
*loud* (the unknown status hit the warning + held the reservation); the new
shape fails *silent-wrong* for an unmapped-but-terminal status. This is a
maintainability/robustness concern, not a current defect — the current
`FillStatus` terminal set is exactly the three handled — so it is Info, not a
Warning.
**Fix:** Make the REFUSED arm explicit again so the dispatch is exhaustive over
the named terminal statuses and an unmapped-but-terminal status cannot be
mis-routed:
```python
if fill_event.status == FillStatus.EXECUTED:
    applied = self._apply_executed(order, fill_event, order_id)
elif fill_event.status == FillStatus.CANCELLED:
    self._apply_cancelled(order)
elif fill_event.status == FillStatus.REFUSED:
    self._apply_refused(order)
else:
    # _classify said terminal but no arm handles it — fail loud rather
    # than silently rejecting (defends against a future _classify edit).
    raise NotImplementedError(
        f"terminal fill status {fill_event.status} has no dispatch arm")
```

---

_Reviewed: 2026-06-13_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard (iteration 2 re-review)_

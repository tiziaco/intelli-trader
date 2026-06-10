---
phase: 08-admission-position-management-cash-edges
reviewed: 2026-06-10T00:00:00Z
depth: standard
files_reviewed: 14
files_reviewed_list:
  - itrader/reporting/cash_operations.py
  - tests/e2e/conftest.py
  - tests/e2e/strategies/scripted_emitter.py
  - tests/e2e/admission/scale_in/scenario.py
  - tests/e2e/admission/scale_out/scenario.py
  - tests/e2e/admission/re_entry/scenario.py
  - tests/e2e/admission/max_positions/scenario.py
  - tests/e2e/cash/release_cancelled/scenario.py
  - tests/e2e/cash/release_refused/scenario.py
  - tests/e2e/cash/release_rejected/scenario.py
  - tests/e2e/admission/scale_in/test_scenario.py
  - tests/e2e/admission/max_positions/test_scenario.py
  - tests/e2e/cash/release_rejected/test_scenario.py
  - tests/unit/reporting/test_cash_operations.py
findings:
  critical: 0
  warning: 3
  info: 3
  total: 6
status: issues_found
---

# Phase 8: Code Review Report

**Reviewed:** 2026-06-10
**Depth:** standard
**Files Reviewed:** 14
**Status:** issues_found

## Summary

Adversarial review of the Phase 8 cash-ledger serializer (`itrader/reporting/cash_operations.py`),
the E2E harness seam change in `tests/e2e/conftest.py`, the seven scenario golden-master
hand-derivations, and the unit fixtures. I cross-checked every claim in the production
serializer and the conftest seam against the real engine source (`simulated.py`, `cash_manager.py`,
`exchange.py`, `order.py`) and verified each frozen golden CSV byte-for-byte against its VERIFY
hand-derivation.

**High-level assessment:** The serializer is small and disciplined; the conftest seam is correctly
scoped (guarded by `exchange_config is not None`, so the 6 `exchange=None` leaves are provably
unaffected — verified against the diff). All seven golden CSVs match their hand-derivations exactly,
and the documented gate-before-sizing (`quantity=0`) vs gate-after-sizing (`quantity=1000`)
distinction between `max_positions` and `release_rejected` is correct against `order_manager.py`.

The defects found are all **latent determinism/robustness gaps in the row-ordering contract** — not
present-day failures, because every current golden has < 10 distinct references and no full-key
collisions. They will silently misorder or non-deterministically order rows the moment a future
cash-edge leaf crosses those thresholds, which is exactly the failure mode this no-tolerance
regression-lock framework exists to prevent. No security issues (offline test/serializer code, no
I/O of untrusted input, no secrets, no injection surface).

## Warnings

### WR-01: `ORDER-{n}` correlation label sorts lexicographically — row order breaks at >= 10 distinct references

**File:** `itrader/reporting/cash_operations.py:83`, sorted at `:94-95`; mirrored in `tests/e2e/conftest.py:122` (`_CASH_OPS_SORT_KEYS`)
**Issue:** The derived correlation is the string `f"ORDER-{n}"`, and `build_cash_operations` sorts the
frame by `["correlation", "operation_type", "amount"]`. String sort is lexicographic, so for >= 10
distinct references the order becomes `ORDER-1, ORDER-10, ORDER-11, ..., ORDER-2, ...` rather than the
first-appearance numeric order the module docstring (`:24-31`) and every scenario VERIFY note promise
("first-appearance order"). Verified: `sorted(['ORDER-1','ORDER-2','ORDER-10','ORDER-3']) ==
['ORDER-1','ORDER-10','ORDER-2','ORDER-3']`. This is deterministic (so it will not flap), but it
silently violates the documented ordinal-order contract and will make a future >= 10-reference golden
unreadable and mis-aligned versus its hand-derivation. The current goldens top out at `ORDER-5`
(scale_in), so the defect is latent, not active.
**Fix:** Zero-pad the ordinal so lexicographic order equals numeric order, e.g.

```python
return f"ORDER-{self._ordinals[ref]:04d}"
```

or sort on a separate numeric key carried alongside the label. If you change the label format you must
re-freeze the existing cash goldens (scale_in / release_cancelled / release_refused) under `--freeze`
after re-verifying.

### WR-02: cash-ops sort has no stable tiebreak when (correlation, operation_type, amount) collide

**File:** `tests/e2e/conftest.py:122` (`_CASH_OPS_SORT_KEYS`) and `itrader/reporting/cash_operations.py:94-95`
**Issue:** The sort key set is `["correlation", "operation_type", "amount"]` with no further tiebreak.
If two rows share all three (e.g. two `RESERVATION`s of the same amount on the same derived order, or
two equal-amount partial `TRANSACTION_DEBIT`s collapsed under one ordinal), `sort_values` row order is
not guaranteed across the fresh vs golden frames, so the row-aligned `assert_frame_equal` in
`_diff_frame` can spuriously fail. This is the EXACT failure the author already fixed for the
orders-snapshot — `_ORDERS_SORT_KEYS` got `time` appended as a trailing tiebreak with an explicit IN-02
comment (`conftest.py:111-116`) — but the cash-ops path was given no equivalent unique trailing key.
The inline comment at `conftest.py:117-121` even claims `amount` IS that tiebreak, which is only true
when amounts differ. Latent: no current golden has a full-key collision.
**Fix:** Add a deterministic trailing tiebreak the same way orders did. Since the deterministic source
fields (`balance_before`/`balance_after`) are already in the frame, extend the cash-ops sort to
`["correlation", "operation_type", "amount", "balance_before", "balance_after"]`, and correct the
misleading comment that calls `amount` a sufficient tiebreak.

### WR-03: seam unconditionally re-inits fee/slippage models, diverging from the `update_config` contract it claims to mirror

**File:** `tests/e2e/conftest.py:277-291`
**Issue:** The seam comment (`:266-274`, `:281-289`) states it reproduces `SimulatedExchange.update_config`
"exactly". It does not: `update_config` (`simulated.py:~595-606`) gates each re-init behind a kwarg
check — `if any(k.startswith('fee_') ...): self.fee_model = self._init_fee_model()` and the analogous
slippage/limits guards — whereas the seam unconditionally calls `_init_fee_model()`,
`_init_slippage_model()`, and re-derives both size caches every time `spec.exchange is not None`. For
the only current non-None leaf (`release_refused`, zero-fee/zero-slippage defaults) the result is
identical, so this is not an active bug. But it is a correctness trap for any future spec that carries a
non-default `ExchangeConfig`: the unconditional re-init reads `simulated.config` for fields the spec may
have left at construction-time defaults, so the seam can silently reset models the author did not intend
to change — the opposite of the conservative "only the size caches move" intent stated at `:289`.
**Fix:** Mirror `update_config`'s conditional guards, or (simpler and more honest) call the real
`simulated.update_config(...)` with the explicit fields the spec carries instead of hand-reassembling
its internals. At minimum, correct the "exactly as ... update_config does" comments to state that the
seam re-inits unconditionally and is only safe today because the sole non-None spec uses zero-cost
defaults.

## Info

### IN-01: `build_cash_operations` applies `_float_or_none` to balances but raw `float()` to `amount`

**File:** `itrader/reporting/cash_operations.py:88` vs `:89-90`
**Issue:** `amount` uses `float(op.amount)` directly while balances use the `None`-guarded
`_float_or_none`. `CashOperation.amount` is typed non-optional `Decimal` (`cash_manager.py:36`), so this
is safe today, but the asymmetry is a small inconsistency: a future duck-typed producer (the input is
deliberately duck-typed per the docstring) that emits `amount=None` would crash here rather than
degrade gracefully like the balances do.
**Fix:** For uniformity and duck-typing robustness, route `amount` through `_float_or_none` too, or add
a one-line comment noting `amount` is contractually non-None whereas balances are `Optional`.

### IN-02: scale_in VERIFY prose describes release-then-debit ordering, but frozen balances prove debit-then-release

**File:** `tests/e2e/admission/scale_in/scenario.py:60-61` (and the analogous prose in re_entry `:52-53`)
**Issue:** The prose says "release the 4_000 reservation, debit 4_000". The frozen golden proves the
opposite within-tick order: `ORDER-2 TRANSACTION_DEBIT 10000.00 -> 6000.00` then `ORDER-1
RELEASE_RESERVATION 6000.00 / 6000.00` (the release records `self._balance` AFTER the debit, confirmed
against `cash_manager.py:435-446`). The frozen numbers are internally self-consistent and correct; only
the prose ordering in the VERIFY note is reversed. Because VERIFY notes are the human contract behind
each freeze (Pitfall 5), the prose should match the actual settlement order.
**Fix:** Reword to "debit 4_000 from the balance, then release the held 4_000 reservation (the release
records the post-debit balance 6_000)".

### IN-03: harness threads only `portfolios[0]` through `_make_on_tick` / `_assemble` despite the multi-emitter `max_positions` leaf

**File:** `tests/e2e/conftest.py:315,320-321,331-332,338`
**Issue:** `_build_and_run` passes `portfolio_ids[0]` to the operator hook and `_assemble` queries the
order mirror / cash ledger from `portfolios[0]` only. This is correct for every Phase 8 leaf (all
single-portfolio, including `max_positions` which uses two emitters on ONE portfolio), and the asserts
in `_build_and_run:299` and `_make_on_tick` guard the obvious failure modes well. Flagging only so the
single-portfolio assumption is a conscious, documented boundary before Phase 9's multi-portfolio cash
isolation work, which will need the harness to generalize beyond `portfolios[0]`.
**Fix:** No change required for Phase 8. Add a short comment at `:320` marking the `portfolios[0]`
read as a Phase-8 single-portfolio simplification to be revisited in Phase 9.

---

_Reviewed: 2026-06-10_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_

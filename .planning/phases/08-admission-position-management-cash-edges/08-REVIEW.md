---
phase: 08-admission-position-management-cash-edges
reviewed: 2026-06-10T00:00:00Z
depth: standard
files_reviewed: 14
files_reviewed_list:
  - itrader/reporting/cash_operations.py
  - tests/e2e/conftest.py
  - tests/e2e/strategies/scripted_emitter.py
  - tests/e2e/admission/max_positions/scenario.py
  - tests/e2e/admission/max_positions/test_scenario.py
  - tests/e2e/admission/re_entry/scenario.py
  - tests/e2e/admission/re_entry/test_scenario.py
  - tests/e2e/admission/scale_in/scenario.py
  - tests/e2e/admission/scale_in/test_scenario.py
  - tests/e2e/admission/scale_out/scenario.py
  - tests/e2e/admission/scale_out/test_scenario.py
  - tests/e2e/cash/release_cancelled/scenario.py
  - tests/e2e/cash/release_refused/scenario.py
  - tests/e2e/cash/release_rejected/scenario.py
findings:
  critical: 0
  warning: 2
  info: 3
  total: 5
status: issues_found
---

# Phase 08: Code Review Report

**Reviewed:** 2026-06-10
**Depth:** standard
**Files Reviewed:** 14
**Status:** issues_found

## Summary

This phase adds a determinism-safe cash-ledger snapshot serializer
(`itrader/reporting/cash_operations.py`), the full E2E scenario harness
(`tests/e2e/conftest.py` — wholly new in this diff range), the generic
`ScriptedEmitter` strategy fixture, and seven regression-lock scenario leaves
(four admission, three cash-edge). I ran the suite: all 7 scenarios pass and the
committed goldens are internally self-consistent and match their hand-derived
VERIFY notes.

Code quality is high — heavy decision-anchored documentation, Decimal kept internal
with `float()` only at the serialization edge, no float-money defects, no secrets,
no dangerous calls. My adversarial focus was therefore on (a) whether the goldens
actually catch the regressions they claim to lock, and (b) latent correctness traps
in the serializer/diff machinery that the current small fixtures do not exercise. No
BLOCKERs surfaced. The findings below are robustness gaps that do not bite the
committed fixtures but will produce silent wrong behavior or spurious failures as
soon as a future leaf crosses a boundary the current ones do not.

## Warnings

### WR-01: `correlation` ordinal uses string sort — ORDER-10 sorts before ORDER-2

**File:** `itrader/reporting/cash_operations.py:83,94-95` and `tests/e2e/conftest.py:122,558`
**Issue:** The derived correlation label is `f"ORDER-{n}"` (a string), and both the
serializer's internal sort (`sort_values(["correlation", ...])`, line 94) and the
harness diff sort (`_CASH_OPS_SORT_KEYS = ["correlation", "operation_type",
"amount"]`, conftest:122 consumed at conftest:558) sort it lexicographically. With
ten or more distinct references the row order becomes `ORDER-1, ORDER-10, ORDER-11,
..., ORDER-2`, not numeric order. Because fresh and golden sort identically the diff
will not spuriously fail, but the frozen golden row order stops tracking
first-appearance/chronological order, which silently defeats the human-readability
contract the serializer docstring sells ("a RESERVATION matchable to its RELEASE",
lines 22-31) and makes any future hand-verification of a 10+-order cash ledger
error-prone. The committed leaves top out at ORDER-5 (scale_in), so this is latent
today.
**Fix:** Zero-pad the ordinal so lexical sort equals numeric sort:
```python
return f"ORDER-{self._ordinals[ref]:03d}"
```
or sort on a numeric key extracted from the ordinal rather than the raw label, and
apply the same change wherever `_CASH_OPS_SORT_KEYS` is consumed so both producers
agree.

### WR-02: `build_cash_operations` reads duck-typed attributes with no guard — shape drift fails opaquely

**File:** `itrader/reporting/cash_operations.py:85-91`
**Issue:** The row comprehension reads `op.reference_id`, `op.operation_type.name`,
`op.amount`, `op.balance_before`, `op.balance_after` directly on a deliberately
duck-typed input ("`CashOperation`-shaped objects, NO handler import", docstring
lines 6-9). If `CashOperation` ever drops/renames a field, or `operation_type` is
ever a plain string instead of an enum (no `.name`), every cash-edge leaf fails with
a bare `AttributeError` deep inside a list comprehension, with no indication of which
field or which operation is malformed — the opposite of the explanatory
hard-failure discipline the harness applies elsewhere (conftest:299 portfolio
assertion, conftest:216-223 operator predicate). For a test-infra serializer whose
whole job is to make cash-ledger regressions diagnosable, an opaque attribute crash
is a quality gap.
**Fix:** Pin the contract or fail with a field-naming message, e.g.
```python
required = ("reference_id", "operation_type", "amount",
            "balance_before", "balance_after")
for op in operations:
    missing = [a for a in required if not hasattr(op, a)]
    if missing:
        raise TypeError(f"cash operation {op!r} missing fields {missing}")
```
At minimum assert `operation_type` exposes `.name` so the failure names the cause.

## Info

### IN-01: `amount` is the only tiebreak after (correlation, operation_type) — relies on a stable sort, not a unique key

**File:** `itrader/reporting/cash_operations.py:94-95`, `tests/e2e/conftest.py:122`
**Issue:** Rows are ordered by `(correlation, operation_type, amount)`. Two
operations sharing all three (e.g. two equal-amount RESERVATIONs on the same derived
order) have no deterministic tiebreak beyond pandas' stable mergesort preserving the
upstream `get_cash_operations()` insertion order. That upstream order is
deterministic in single-threaded backtest, so the goldens are reproducible today,
but the sort key is not a total order while the docstring oversells it as "a stable
business key so order is reproducible across runs" (lines 29-31).
**Fix:** Document the stable-sort + deterministic-source dependency, or carry a
source index as the final tiebreak: `frame["_seq"] = range(len(frame))`, sort with
`_seq` last, then drop it — making the key total.

### IN-02: `float_format=FLOAT_FORMAT` is silently inert on Decimal-object columns

**File:** `tests/e2e/conftest.py:474-475,517` (interacts with frozen `trades.csv`
goldens, e.g. `tests/e2e/admission/scale_out/golden/trades.csv`)
**Issue:** `_freeze`/`_roundtrip` pass `float_format=FLOAT_FORMAT` to `to_csv`, but
the engine emits money columns as `Decimal` objects (object dtype), and pandas'
`float_format` only formats genuine float cells. The scale_out golden shows the
artifact directly — `avg_sold` is frozen as `135.000000000000000000000` (full
Decimal repr) while sibling float columns are `135.0000000000` (10 dp). The diff
survives only because `read_csv` re-parses both sides to identical floats. This is a
pre-existing harness property (Phase 4) now carried over the cash columns; it works
but is fragile — a money column that stays Decimal on both sides would compare
full-precision strings, masking or fabricating sub-10dp drift the FLOAT_FORMAT
contract intends to normalize.
**Fix:** Out of this phase's strict scope (inherited harness behavior) but worth a
tracking note: cast money columns to float before `to_csv`, or apply `FLOAT_FORMAT`
via an explicit map so the 10-dp normalization the docstring promises
(conftest:509-514) actually reaches Decimal columns.

### IN-03: `release_refused` VERIFY note understates the harness seam it depends on

**File:** `tests/e2e/cash/release_refused/scenario.py:48-52`
**Issue:** The note says `min_order_size` is "left at its small default" and only
`max_order_size` is the lever. That is true of the `ExchangeConfig`, but the harness
seam (conftest:290-291) re-derives BOTH `_min_order_size` and `_max_order_size` from
the spec config whenever `spec.exchange is not None`. This leaf is safe (default min
0.001, qty 40), but the note implies only `max_order_size` is threaded, which
misrepresents the seam a future cash-edge author will copy from this leaf — a
min-driven REFUSED scenario authored from this note would not realize the min cache
is also live.
**Fix:** Add one line: "the harness re-derives both `_min_order_size` and
`_max_order_size` from `spec.exchange` (conftest:290-291); this leaf relies on the
default min (0.001) and only moves `max_order_size`."

---

_Reviewed: 2026-06-10_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_

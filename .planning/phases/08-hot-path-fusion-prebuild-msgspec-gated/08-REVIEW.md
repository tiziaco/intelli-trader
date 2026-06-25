---
phase: 08-hot-path-fusion-prebuild-msgspec-gated
reviewed: 2026-06-25T18:30:00Z
depth: standard
files_reviewed: 14
files_reviewed_list:
  - itrader/core/bar.py
  - itrader/events_handler/events/base.py
  - itrader/events_handler/events/error.py
  - itrader/events_handler/events/fill.py
  - itrader/events_handler/events/market.py
  - itrader/events_handler/events/order.py
  - itrader/events_handler/events/signal.py
  - itrader/execution_handler/matching_engine.py
  - itrader/portfolio_handler/position/position.py
  - itrader/portfolio_handler/transaction/transaction.py
  - itrader/price_handler/feed/bar_feed.py
  - itrader/strategy_handler/base.py
  - itrader/strategy_handler/signal_record.py
  - pyproject.toml
findings:
  critical: 0
  warning: 2
  info: 3
  total: 5
status: issues_found
---

# Phase 8: Code Review Report

**Reviewed:** 2026-06-25T18:30:00Z
**Depth:** standard
**Files Reviewed:** 14
**Status:** issues_found

## Summary

Phase 8 migrates `Bar`, the full `Event` hierarchy (+ `SignalRecord`, `TrailState`,
`FillDecision`, `CancelDecision`), and `Transaction` from frozen/slotted dataclasses to
`msgspec.Struct`, and adds three hot-path caches: a fill-invalidated `net_quantity`/`avg_price`
cache on `Position`, a per-instance `to_dict` static cache on `Strategy`, and an `itertuples`-based
`{ts: Bar}` prebuild in `BacktestBarFeed`.

I verified the four highest-risk seams the prompt called out:

1. **Transaction msgspec field reordering** — `fill_id` moved from `field(kw_only=True)` to a plain
   positional field placed immediately after `id`. Every construction site (production
   `portfolio_handler.py` and all unit tests) passes the first 8 fields positionally + `fill_id=`
   by keyword, so the new ordering aligns. The `__post_init__` Decimal normalization is preserved
   and fires on the non-frozen struct. No defect.
2. **Position fill-invalidated cache** — a grep audit confirms the six cached inputs are mutated
   ONLY in `__init__` and `update_position`, and `update_position` resets both caches. `close_position`
   touches only `current_price`/`is_open` (not cache inputs), so it correctly skips invalidation.
   No correctness defect.
3. **Bar itertuples prebuild** — `str()` parity between the old `iterrows()` Series path and the new
   `itertuples()` native-scalar path is byte-identical across all 15,380 OHLCV values of the golden
   dataset (verified empirically), preserving the D-14 `Decimal(str(x))` contract.
4. **msgspec is construction-only** — there is NO `encode`/`decode`/`to_builtins`/`convert` call
   anywhere in `itrader/`; the only struct utility used is `msgspec.structs.replace` (in-memory copy,
   verified to preserve Decimal + identity fields). No Decimal-coercing serialization path was
   introduced.

The byte-exact oracle (134 trades / 46189.87730727451) passes, `mypy --strict` is clean across all
changed files, and the full affected unit-test surface (303 portfolio/events/execution +
130 strategy/price + 60 Phase-8-specific) is green.

The two WARNINGs below concern a real shared-mutable-state regression introduced by the
`Strategy.to_dict` cache (latent, not yet triggered) and a documentation/contract drift in the
`itertuples` parity guarantee. The Info items are doc-drift and minor hygiene.

## Warnings

### WR-01: `Strategy.to_dict` cache shares nested mutable values across every SignalRecord

**File:** `itrader/strategy_handler/base.py:668-675` (and consumer `itrader/strategy_handler/strategies_handler.py:192`)

**Issue:** `to_dict()` now returns `dict(self._to_dict_static_cache)` — a SHALLOW copy. The comment
claims "a caller mutating the result never poisons the cache," but that only holds for the top-level
dict and the two keys reassigned per call (`subscribed_portfolios`, `is_active`). Every OTHER nested
value in the cached snapshot — notably the declared `tickers` `list[str]` and any declared
`dict`/`list` knob produced by `_json_safe` — is the SAME object shared by:
  - the per-instance cache, and
  - every `SignalRecord.config` built from `strategy.to_dict()` (one per signal, per portfolio fan-out).

Before this phase `_build_to_dict_snapshot` ran on every call, so each `SignalRecord` got its OWN
fresh `tickers` list. After caching, all records and the live strategy alias one list. A consumer
that mutates `record.config["tickers"]` (or `strategy.to_dict()["tickers"]`) now poisons every other
record and the strategy's cache. This is a behavioral aliasing regression. It is currently dark (no
in-tree mutator), so WARNING rather than BLOCKER, but it is a real correctness footgun the cache
introduced.

**Fix:** Deep-copy nested mutables when serving from the cache, or freeze them at build time. Minimal:
```python
import copy
snapshot = copy.deepcopy(self._to_dict_static_cache)
snapshot["subscribed_portfolios"] = [str(pid) for pid in self.subscribed_portfolios]
snapshot["is_active"] = self.is_active
return snapshot
```
If `deepcopy` is too costly on the hot path, store list/dict values as immutable (tuple / frozen)
in `_build_to_dict_snapshot` so the shallow copy is genuinely safe.

### WR-02: `itertuples` str-parity is a dataset-specific guarantee, not a structural one

**File:** `itrader/price_handler/feed/bar_feed.py:270-280`

**Issue:** The prebuild was changed from `Bar.from_row(ts, row)` (Series item access) to direct
`Bar(open=Decimal(str(r.open)), ...)` over `frame.itertuples()`. The byte-exactness of the D-14
`Decimal(str(x))` path depends on `str(itertuples_scalar) == str(series_value)` for every OHLCV cell.
I verified this holds for ALL golden-dataset values, and a test pins it — but the guarantee is
*empirical per dataset*, not structural. `iterrows()` and `itertuples()` can both yield numpy
scalars whose `str()` repr is identical today, yet a future data load with a different dtype path
(e.g. an `object`-dtype column, a mixed-block frame, or a non-float64 store) could diverge silently
and shift fills off-oracle without any error. The risk is gated behind "all golden columns are
float64," which is an assumption, not an invariant enforced here.

**Fix:** Add a defensive dtype assertion before the prebuild loop so a non-float64 OHLCV column fails
loud instead of silently drifting the Decimal string:
```python
ohlcv = frame[["open", "high", "low", "close", "volume"]]
if not all(dt == "float64" for dt in ohlcv.dtypes):
    raise MalformedDataError(ticker, f"OHLCV columns must be float64 for str-parity; got {dict(ohlcv.dtypes)}")
```
This keeps the win while making the parity precondition explicit and self-enforcing.

## Info

### IN-01: `current_bars` docstring claims `Bar.from_row` but the prebuild now bypasses it

**File:** `itrader/price_handler/feed/bar_feed.py:463-465, 474`

**Issue:** The `current_bars` docstring still states bars are "built once in `__init__` via the
UNCHANGED `Bar.from_row`, Decimal string path." Phase 8 replaced the `Bar.from_row` prebuild with a
direct `Bar(...)` construction over `itertuples` (lines 270-280). The docstring is now stale — a
future reader auditing the D-14 path will look for `Bar.from_row` and not find it on the hot prebuild.

**Fix:** Update the docstring to "built once in `__init__` via a direct `Decimal(str(...))` Bar
construction over `frame.itertuples` (the same D-14 string path as `Bar.from_row`, inlined for the
prebuild — see Req 3)."

### IN-02: `Bar.from_row` is now dead on the run path — confirm remaining callers

**File:** `itrader/core/bar.py:52-68`

**Issue:** With the `itertuples` prebuild inlining the Decimal construction, `Bar.from_row` is no
longer on the backtest run path. It remains a public classmethod (likely still used by tests). This
is not a defect, but it is now a second, parallel construction path that must be kept byte-identical
to the inlined prebuild by convention only — any future edit to one and not the other risks drift.

**Fix:** Either route the prebuild back through `Bar.from_row` (one source of truth, if the per-row
Series allocation it avoided is not actually the dominant cost), or add a comment on `Bar.from_row`
noting the inlined prebuild in `bar_feed.py` is the authoritative run-path twin that must stay in
sync. No behavioral change required.

### IN-03: `FillEvent.new_fill` / `Transaction.new_transaction` `getattr(..., "leverage", Decimal("1"))` is now redundant for real events

**File:** `itrader/events_handler/events/fill.py:148`, `itrader/portfolio_handler/transaction/transaction.py:153`, `itrader/events_handler/events/order.py:135`

**Issue:** `OrderEvent`, `FillEvent`, and `Transaction` now all carry a real `leverage` field with a
`Decimal("1")` default, so `getattr(order, "leverage", Decimal("1"))` always finds the attribute on a
real event — the default branch is only reachable by hand-built stubs that predate the field. This is
intentional (the comments document the stub-compat rationale), so it is hygiene, not a bug. Flagging
only so the defensive `getattr` is removed when the legacy stubs are retired, to avoid masking a
future genuinely-missing field.

**Fix:** No change required this phase. When the pre-leverage stub fixtures are removed, replace the
three `getattr(x, "leverage", Decimal("1"))` reads with direct `x.leverage` so a missing field fails
loud under the fail-fast seam.

---

_Reviewed: 2026-06-25T18:30:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_

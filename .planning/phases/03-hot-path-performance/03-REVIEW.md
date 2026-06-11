---
phase: 03-hot-path-performance
reviewed: 2026-06-11T00:00:00Z
depth: standard
files_reviewed: 10
files_reviewed_list:
  - itrader/portfolio_handler/storage/in_memory_storage.py
  - itrader/portfolio_handler/base.py
  - itrader/portfolio_handler/metrics/metrics_manager.py
  - itrader/price_handler/feed/bar_feed.py
  - itrader/portfolio_handler/position/position_manager.py
  - itrader/portfolio_handler/portfolio_handler.py
  - itrader/order_handler/order_manager.py
  - itrader/execution_handler/exchanges/simulated.py
  - itrader/price_handler/store/csv_store.py
  - itrader/strategy_handler/strategies/SMA_MACD_strategy.py
findings:
  critical: 0
  warning: 2
  info: 1
  total: 3
status: issues_found
---

# Phase 3: Code Review Report

**Reviewed:** 2026-06-11
**Depth:** standard
**Files Reviewed:** 10
**Status:** issues_found

## Summary

Reviewed the 10 source files changed for the Phase-3 hot-path-performance refactor against
the byte-exact golden-master contract (134 trades / `final_equity 46189.87730727451`), the
Decimal-end-to-end money policy, the determinism seam, and the tab/space indentation hazard.

The phase is a high-quality, well-disciplined behavior-preserving refactor. I traced every
change against its result-altering potential and found **no BLOCKER**:

- **W1-08 Decimal re-wrap drop** — verified `market_value`/`unrealised_pnl`/`realised_pnl`
  are all `-> Decimal` at source (`position.py:70,147,173`); `Decimal(str(Decimal))` was a
  true value/type no-op. Byte-exact.
- **W1-12 MACD-inside-guard reorder** — `MACDhist` is in scope for both the buy-trigger `if`
  and the exit `elif` (both at the same 3-tab level inside the SMA filter). `trend.MACD` is
  pure (no side effects, deterministic), so skipping it on non-firing SMA ticks is observationally
  identical. TAB indentation preserved, no 4-space lines introduced.
- **W1-07 on_fill guard hoist** — `_operation_context` (post-D-19) only allocates a UUIDv7
  correlation id (NOT drawn from the seeded execution RNG, NOT in trade-log/equity output) and
  yields; it publishes nothing on entry/exit. Skipping it for non-EXECUTED fills perturbs neither
  the determinism stream nor any output.
- **W1-14 redundant is_connected drop** — the removed `_admit_order` guard ran only after
  `validate_order()` passed; validation itself fails REFUSED on disconnect, so the guard was
  provably unreachable.
- **W1-09 load-time copy drop** — reproduced the exact load transform under `-W error` with
  CoW disabled (pandas 2.3.3 default `copy_on_write=False`): `data.columns = [...]` on the
  column-select view is warning-free and does not write back to `raw`. Safe under
  `filterwarnings=["error"]`.
- **PERF-01 copy-drop** — `Bar` is `frozen=True, slots=True` (immutable), and every consumer of
  the now-live storage containers reads only (audited `position_manager`, `metrics_manager`,
  `reporting`, `cash_manager`, `transaction_manager`). `close_all_positions` defends with
  `list(...)`. D-19 single-writer holds.

Two latent WARNINGs and one INFO follow. None are triggered by the golden run (so the byte-exact
oracle correctly stays green), but each is a real robustness gap worth recording.

## Warnings

### WR-01: `current_bars()` prebuild silently changes duplicate-timestamp selection semantics

**File:** `itrader/price_handler/feed/bar_feed.py:185-187` (and read site `current_bars` `:320-326`)
**Issue:** The eager prebuild builds the per-ticker map with a dict comprehension:
```python
self._prebuilt[ticker] = {ts: Bar.from_row(ts, row) for ts, row in frame.iterrows()}
```
The replaced per-tick path used `searchsorted(time, side="left")` + `index[pos] == time`, which
selects the **FIRST** row at a given timestamp. A dict comprehension keeps the **LAST** value on
key collision. If `frame.index` ever contains **duplicate timestamps**, the prebuilt map serves a
different `Bar` than the old code did — a silent behavior change, not caught by the oracle.

This is latent, not active: the golden CSV (`data/BTCUSD_1d_ohlcv_2018_2026.csv`) has 3076 rows /
3076 unique dates, and neither the store nor the feed enforces index uniqueness anywhere
(no `drop_duplicates`/`verify_integrity`/`is_unique` guard exists). So byte-exact holds today, but
any future dataset (intraday, vendor-spliced, re-listed symbol) with a duplicate stamp would diverge
invisibly between the two code paths' lifetimes.

**Fix:** Either assert uniqueness once at prebuild (turns a silent divergence into a loud failure),
or document the first-vs-last contract explicitly. Minimal guard at the build site:
```python
if not frame.index.is_unique:
    raise MalformedDataError(ticker, "duplicate timestamps in base frame")
self._prebuilt[ticker] = {ts: Bar.from_row(ts, row) for ts, row in frame.iterrows()}
```
(If first-wins must be preserved to match the old `searchsorted(side="left")` semantics exactly,
build with `frame[~frame.index.duplicated(keep="first")]` instead.)

### WR-02: `get_closed_positions(limit=...)` truthiness bug skips a zero limit

**File:** `itrader/portfolio_handler/position/position_manager.py:261-266`
**Issue:** Not introduced by this phase, but it sits directly on the copy-drop seam this phase
touched (`get_closed_positions()` now returns the live list), so the aliasing interaction is newly
relevant:
```python
def get_closed_positions(self, limit: Optional[int] = None) -> List[Position]:
    closed = self._storage.get_closed_positions()
    if limit:                 # truthiness, not `is not None`
        return closed[-limit:]
    return closed
```
`if limit:` treats `limit=0` as "no limit" and returns the **entire live list** instead of an empty
slice. Worse, with the copy now dropped, the `limit`-falsy branch hands the caller the storage's
**live internal list** (the `[-limit:]` branch returns a safe slice copy). A caller passing
`limit=0` expecting "last zero / empty" instead receives a mutable alias of internal state — a
correctness + aliasing hazard the old defensive `.copy()` previously masked.

**Fix:**
```python
if limit is not None:
    return closed[-limit:]
return list(closed)   # return an owned copy on the no-limit branch, or document read-only
```
(At minimum change `if limit:` → `if limit is not None:`. Returning a copy on the no-limit branch is
the conservative choice now that the storage getter aliases live state.)

## Info

### IN-01: Trailing tab-only line at EOF in a 4-space module

**File:** `itrader/portfolio_handler/base.py:300`
**Issue:** The file body is 4-space indented (per the `config/core/feed` convention), but EOF
carries a stray tab-only line. This is **pre-existing** (present on `main`, not introduced by this
phase's diff — confirmed via `git show main:...`), so it is not a regression and does not break the
mixed-tab/space rule for the changed regions (the new `snapshot_count`/`get_latest_snapshot`
abstractmethods and the rewritten docstrings are correctly 4-space). Flagged only for awareness
since the file is now in scope; safe to strip on the next touch.
**Fix:** Remove the trailing whitespace-only line.

---

_Reviewed: 2026-06-11_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_

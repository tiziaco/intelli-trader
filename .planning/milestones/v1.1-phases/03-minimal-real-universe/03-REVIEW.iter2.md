---
phase: 03-minimal-real-universe
reviewed: 2026-06-09T11:39:47Z
depth: standard
files_reviewed: 8
files_reviewed_list:
  - itrader/price_handler/feed/bar_feed.py
  - itrader/strategy_handler/strategies_handler.py
  - itrader/trading_system/backtest_trading_system.py
  - itrader/universe/__init__.py
  - itrader/universe/membership.py
  - tests/integration/test_universe_spans.py
  - tests/unit/price/test_bar_feed.py
  - tests/unit/universe/test_membership.py
findings:
  critical: 0
  warning: 2
  info: 3
  total: 5
status: issues_found
---

# Phase 3: Code Review Report

**Reviewed:** 2026-06-09T11:39:47Z
**Depth:** standard
**Files Reviewed:** 8
**Status:** issues_found

## Summary

This phase adds a span-model availability primitive (`is_active` /
`active_membership`) to the universe package, wires a `_spans` cache into
`BacktestBarFeed`, gates the feed's absence warning on true mid-life gaps
(D-04), removes the now-duplicate absence warning from `StrategiesHandler`,
and threads a `csv_paths` injection seam through `TradingSystem` so a
multi-ticker store can be constructed. An integration test exercises a
heterogeneous-span universe (early anchor, mid-run lister, early-ender).

**Oracle-dark verification (the phase's primary risk):** I traced every
diff line against the bar/fill path. The only functional change inside
`generate_bar_event` is the warning predicate
(`if ticker not in bars and is_active(...)`). `current_bars`, the `bars`
dict, and `BarEvent` construction are byte-identical to the prior revision
— confirmed by `git diff` line inspection. The new `_spans` cache reads
`frame.index[0]/[-1]` at construction only and never touches the slice
path. The `csv_paths=None` default preserves the single-golden-ticker
store exactly. I judge the oracle-dark guarantee intact. The 31 phase
tests pass.

The remaining findings are robustness/quality concerns, not correctness
defects in the golden path. No blockers.

## Warnings

### WR-01: `is_active` raises `TypeError` on tz-mixed inputs with no defensive guard

**File:** `itrader/universe/membership.py:120-121`
**Issue:** `is_active` does `first <= asof <= last` directly. If `asof` is
tz-aware and the span bounds are tz-naive (or vice versa), Python raises
`TypeError: can't compare offset-naive and offset-aware datetimes`. The
docstring documents the precondition ("Must share tz-ness") but enforces
nothing. The live feed path is currently safe because `_spans` is seeded
from `frame.index[0]/[-1]` (tz-aware) and `time_event.time` is a tz-aware
`pd.Timestamp` (verified: `np.array(DatetimeIndex)` → object dtype yielding
tz-aware Timestamps, preserved through the `reduce(pd.Index.union, ...)`
ping-grid path). But this is an invariant held only by construction
discipline three modules away (store load → feed cache → time generator).
A future store or screener that injects a tz-naive span would convert a
silent contract into a hard crash inside the per-tick warning loop, and
under `filterwarnings=["error"]` even the comparison machinery surfacing a
warning would abort the run. Pure-function primitives that are explicitly
positioned as reusable seams ("the future v1.3 screener consume[s] it")
should fail with an intelligible message rather than a raw `TypeError`.
**Fix:** Either normalize/validate tz-ness at the boundary, e.g.:
```python
def is_active(spans: dict[str, Span], ticker: str, asof: datetime) -> bool:
    span = spans.get(ticker)
    if span is None:
        return False
    first, last = span
    if (first.tzinfo is None) != (asof.tzinfo is None):
        raise ValueError(
            f"is_active tz mismatch for {ticker}: span tz-aware="
            f"{first.tzinfo is not None}, asof tz-aware={asof.tzinfo is not None}")
    return first <= asof <= last
```
or, if the raw `TypeError` is acceptable, downgrade the docstring claim to
make the crash-on-misuse contract explicit rather than implying graceful
handling.

### WR-02: Integration test mutates a private exchange attribute to exercise the path

**File:** `tests/integration/test_universe_spans.py:134-137`
**Issue:** The test reaches into `simulated._supported_symbols` (a private
attribute) and reassigns it to admit the synthetic tickers. This couples
the test to an internal implementation detail of `SimulatedExchange`:
renaming or restructuring `_supported_symbols` (e.g. moving the supported
set behind a config object) silently breaks this test in a way unrelated
to the universe logic it is meant to lock. The whole assertion chain — the
"anchor traded," "no look-ahead," and "differing end date" guarantees —
depends on the strategy's orders actually filling, which depends on this
private mutation succeeding. If the attribute name drifts, the strategy's
orders would be rejected, positions would be empty, and the look-ahead
asserts (`for position in late_positions:`) would vacuously pass over an
empty list while `assert late_positions` fails with a misleading message.
**Fix:** Prefer a public seam if one exists (e.g. an exchange method or a
config field for the supported-symbol set). If none exists, this is a real
gap in the test-support surface worth a small public hook
(`SimulatedExchange.register_symbols(...)` or a constructor arg). At
minimum, assert the mutation took effect before running, so a future rename
fails loudly at the setup line rather than masquerading as a logic failure:
```python
simulated._supported_symbols |= {"EARLYUSD", "LATEUSD", "ENDSEARLYUSD"}
assert {"EARLYUSD", "LATEUSD", "ENDSEARLYUSD"} <= simulated._supported_symbols
```

## Info

### IN-01: `active_membership` is exported and unit-tested but has zero production consumers

**File:** `itrader/universe/membership.py:124-148`
**Issue:** `active_membership` is added, exported in
`itrader/universe/__init__.py`, and covered by two unit tests, but
`grep` across `itrader/` finds no caller — only `is_active` is consumed
(by the feed). The docstring is explicit that it is forward-looking for
"the future v1.3 screener." This is a deliberate seam-now / consume-later
pattern, not accidental dead code, but it is currently an untested-in-anger
public surface: any regression in its set-comprehension behavior would only
be caught by its own unit tests, never by an integration path. Flagging for
the structural-findings substrate (unused export) so it is not mistaken for
a leak later.
**Fix:** Acceptable as a documented forward seam. If the project prefers to
defer the API until it has a consumer, drop `active_membership` from the
public surface until v1.3 and reintroduce it with its first caller.

### IN-02: Removed strategy-handler absence warning relies on an undocumented assumption that the feed always runs first

**File:** `itrader/strategy_handler/strategies_handler.py:74-76`
**Issue:** The diff removes the `self.logger.warning('No last close for %s
...')` line, delegating all absence observability to the feed's
`generate_bar_event` (D-04/D-05). This is correct for the standard route
order (TIME → feed produces the BarEvent and warns → BAR → strategies
consume), but the dependency is now implicit: if a strategy ever consumes
a `BarEvent` produced by a path that does NOT run the feed's span-aware
warning loop (e.g. a hand-built `BarEvent` in a test or an alternate feed),
a genuine mid-life data gap becomes completely silent in the strategy layer.
The `continue` is correctly load-bearing (price is stamped from
`bar.close`), so behavior is safe — only the diagnostic is now centralized
without a code-level link back to the producer.
**Fix:** No code change required; the routing contract is enforced
elsewhere. Optionally reference the feed as the single observability owner
in a one-line comment near the `continue` so a future reader does not
"restore" the warning and reintroduce the duplicate D-05 removed.

### IN-03: `csv_paths` injection widens the public constructor signature without input validation

**File:** `itrader/trading_system/backtest_trading_system.py:52,90-93`
**Issue:** `csv_paths: dict[str, str | Path] | None` passes straight
through to `CsvPriceStore` with no validation at the `TradingSystem`
boundary. An empty dict (`{}`, not `None`) would construct a store with
zero symbols; the failure then surfaces later as the
`ConfigurationError("Backtest store has no symbols ...")` in
`_initialise_backtest_session` (WR-07), which is the correct loud failure —
but only at session init, not at construction. Tickers are upper-cased by
the store but the membership/strategy `tickers` are not normalized here, so
a strategy declaring a lower-case ticker that matches a `csv_paths` key only
by case would silently never match the store's upper-cased keys.
**Fix:** Acceptable for this phase (the loud `ConfigurationError` covers the
empty case and the golden default is `None`). For the Phase-9 multi-ticker
harness this seam is meant to feed, consider normalizing/validating ticker
casing consistently between `csv_paths` keys, strategy `tickers`, and the
derived membership at one boundary to avoid silent case-mismatch misses.

---

_Reviewed: 2026-06-09T11:39:47Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_

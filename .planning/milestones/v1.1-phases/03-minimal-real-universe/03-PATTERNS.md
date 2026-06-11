# Phase 3: Minimal Real Universe - Pattern Map

**Mapped:** 2026-06-09
**Files analyzed:** 7 (5 modify, 2 create — plus added test cases in 2 existing test files)
**Analogs found:** 7 / 7 (all analogs live in the same modules being touched — this is an ADD-ALONGSIDE phase)

## File Classification

| New/Modified File | Action | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|--------|------|-----------|----------------|---------------|
| `itrader/universe/membership.py` | MODIFY (add fns) | utility (pure query) | transform (span -> set/bool) | `derive_membership` in same file | exact (in-file twin) |
| `itrader/universe/__init__.py` | MODIFY (re-export) | barrel | — | existing `derive_membership` export | exact |
| `itrader/price_handler/feed/bar_feed.py` | MODIFY (span cache + warn loop) | feed (read-model) | event-driven (per-tick BarEvent) | `__init__` frame loop + `generate_bar_event` in same file | exact |
| `itrader/strategy_handler/strategies_handler.py` | MODIFY (delete 1 line) | handler (consumer) | event-driven | the WR-12 guard itself (`:69-73`) | exact |
| `itrader/trading_system/backtest_trading_system.py` | MODIFY (optional `csv_paths` passthrough) | composition root | config/wiring | `CsvPriceStore(start_date=..)` ctor call (`:84-86`) | role-match |
| `tests/unit/universe/test_membership.py` | MODIFY (add cases) | test (unit) | transform | existing `derive_membership` tests in same file | exact |
| `tests/unit/price/test_bar_feed.py` | MODIFY (add cases) | test (unit) | event-driven | `write_kline_csv` / `ts` / `duo_feed` / caplog warn tests (`:303-321`) | exact |
| `tests/integration/test_universe_spans.py` | CREATE | test (integration) | end-to-end run | `test_backtest_smoke.py` + `backtest_engine` factory | role-match |

**Key observation:** Every modified-file analog is the SAME module's existing code. This is an ADD-ALONGSIDE / refine-in-place phase, not a new-subsystem phase — copy the twin function's exact shape, do not invent a new style.

## Pattern Assignments

### `itrader/universe/membership.py` (utility, pure transform) — 4 SPACES

**Analog:** `derive_membership` + `SupportsTickers` Protocol, same file (`:27-73`).

**The pure-function shape to mirror** (`membership.py:38-73`):
```python
def derive_membership(
    strategies: Iterable[SupportsTickers],
    screener_tickers: Iterable[str] = (),
) -> list[str]:
    """Derive the tradable symbol membership at wiring time (M5-08, D-20).
    ...NumPy-style Parameters/Returns block, decision tags D-20/D-21...
    """
    tickers: list[str] = []
    for strategy in strategies:
        ...
    return list(set(tickers))
```

**Patterns to copy:**
- **Pure function, no class, no state, no queue, no feed/store import** — exactly like `derive_membership`. Takes an injected shape (here a `dict[str, Span]` span-map), returns a plain value.
- **4-space indentation** (this is a `core`-style spaces module, NOT a tab handler).
- **NumPy-style docstring** with `Parameters` / `Returns` sections; cite decision tags (`D-01`, `D-03`, `UNIV-01`) the way the existing docstring cites `M5-08`/`D-20`.
- **Module docstring (`:1-21`) reserves this as the D-20 growth home** — ADD below `derive_membership`, do NOT touch the docstring's "this stub IS the universe" framing except to note the availability query was added alongside.

**Recommended new code** (from RESEARCH Pattern 1; names are Claude's Discretion per CONTEXT D-03/Discretion):
```python
from datetime import datetime

Span = tuple[datetime, datetime]   # half-inclusive-both-ends [first, last] (D-01)

def is_active(spans: dict[str, Span], ticker: str, asof: datetime) -> bool:
    span = spans.get(ticker)
    if span is None:
        return False            # unknown ticker -> not a member (sparse contract)
    first, last = span
    return first <= asof <= last  # D-01 inclusive both ends

def active_membership(spans: dict[str, Span], asof: datetime) -> set[str]:
    return {t for t in spans if is_active(spans, t, asof)}
```

**Return-type divergence (intentional, Pitfall 4):** `active_membership` returns `set[str]`; `derive_membership` returns `list[str]` ("order unspecified, set-derived" per its docstring `:60-63`). Document the divergence — `set` is honest about unordered availability and composes into `screen(active_membership(T), ranking)`. Tests assert `== {..}` set-equality, never order.

---

### `itrader/universe/__init__.py` (barrel) — 4 SPACES

**Analog:** the existing single-export barrel, same file.

**Exact pattern to extend** (`__init__.py:9-13`):
```python
from .membership import derive_membership

__all__ = [
    'derive_membership',
]
```
**Copy:** add `is_active, active_membership` to the `from .membership import ...` line and to `__all__`. Single-quote strings, 4-space indent, matching the existing entry.

---

### `itrader/price_handler/feed/bar_feed.py` (feed read-model, event-driven) — 4 SPACES

**Analog A — the `__init__` frame loop** (`bar_feed.py:151-153`):
```python
self._frames: dict[tuple[str, str], pd.DataFrame] = {}
for ticker in self._symbols:
    self._frames[(ticker, self._base_alias)] = store.read_bars(ticker)
```
**Span-cache pattern to add IN THIS SAME LOOP** (RESEARCH Pattern 2 — compute-once, M5-03; zero extra frame reads):
```python
self._spans: dict[str, tuple[datetime, datetime]] = {}   # NEW (D-01 span cache)
for ticker in self._symbols:
    frame = store.read_bars(ticker)
    self._frames[(ticker, self._base_alias)] = frame
    self._spans[ticker] = (frame.index[0].to_pydatetime(),
                           frame.index[-1].to_pydatetime())
```
- `frame.index[0]` / `[-1]` = the ticker's `[first_bar, last_bar]` span (already-sorted tz-aware `DatetimeIndex`, O(1) ends).
- **tz note (Pitfall 2):** `.to_pydatetime()` on a tz-aware Timestamp preserves tzinfo. The span operand and the tick (`TimeEvent.time`, tz-aware) MUST both be tz-aware or the comparison raises `TypeError` (a hard failure under `filterwarnings=["error"]`). Safest: keep span bounds as the same tz-aware type the tick carries (consider keeping `pd.Timestamp` rather than `.to_pydatetime()` if it simplifies the comparison; verify against `current_bars`' `searchsorted` which already compares tz-aware `time`).
- **Look-ahead (7-rule contract, `:9-38`):** reading `index[-1]` at wiring time is availability metadata (listing/delisting calendar), NOT a decision-price leak. The slice path stays unchanged.

**Analog B — the warn-all loop** (`generate_bar_event`, `bar_feed.py:244-257`):
```python
bars = self.current_bars(time_event.time)

for ticker in self.membership:
    if ticker not in bars:
        self.logger.warning(
            'Bar feed: no bar for ticker %s at %s in the feed',
            ticker, str(time_event.time))

bar_event = BarEvent(time=time_event.time, bars=bars)

if self.global_queue is not None:
    self.global_queue.put(bar_event)
    return None
return bar_event
```
**Span-aware refinement (D-04 — single owner; the ONLY warning-surface change):**
```python
for ticker in self.membership:
    if ticker not in bars and is_active(self._spans, ticker, time_event.time):
        # Inside the listed span but no bar at T -> a real mid-life data gap.
        self.logger.warning(
            'Bar feed: mid-life gap for %s at %s (active, no bar)',
            ticker, str(time_event.time))
    # else: expected absence (pre-listing / post-end) -> SILENT (D-04).
```
- **Do NOT touch `current_bars` (`:261-276`), `bars`, or `BarEvent` construction** — the sparse dict already makes "absent bar -> no fill" structurally true (Pitfall 1, oracle-darkness). The change is log-only.
- **Oracle-dark:** BTCUSD is dense across its span and always in `bars`, so the new branch never fires on the golden run — byte-identical (134 trades / `final_equity 46132.7668`).
- **Import:** add `from itrader.universe import is_active` (or call a thin `self._spans` forwarder — Open Q1; for Phase 3 direct `is_active(self._spans, ...)` is sufficient).

---

### `itrader/strategy_handler/strategies_handler.py` (handler/consumer, event-driven) — TABS

**Analog:** the WR-12 sparse-ticker guard itself (`strategies_handler.py:69-73`).

**BEFORE** (`:69-73`):
```python
				bar = event.bars.get(ticker)
				if bar is None:
					self.logger.warning('No last close for %s — signal skipped (%s)',
								ticker, strategy.strategy_id)
					continue
```
**AFTER (D-05 — delete ONLY the warning, keep the load-bearing skip):**
```python
				bar = event.bars.get(ticker)
				if bar is None:
					continue
```
- **LOAD-BEARING:** `if bar is None: continue` MUST stay — price is stamped from `bar.close` at `:95` (`price=to_money(bar.close)`). Deleting the skip would NPE the price stamp.
- **TABS, not spaces** — this is a handler module. A spaces diff here breaks the file under `--strict`. The kept lines are tab-indented exactly as shown.
- **Oracle-dark:** BTCUSD is dense; the warning never fires on the golden run. No test asserts the deleted string (verified: `grep "No last close"` matches only the source line) — D-05 Wave-0 gap is clear, no test adjustment needed.

---

### `itrader/trading_system/backtest_trading_system.py` (composition root, config) — TABS — OPTIONAL ENABLING TASK

**Analog:** the existing `CsvPriceStore` construction (`backtest_trading_system.py:84-87`):
```python
		self.store = CsvPriceStore(
			start_date=start_date,
			end_date=end_date or None)
```
**`CsvPriceStore` ALREADY accepts `csv_paths`** (`csv_store.py:52-56`):
```python
def __init__(self, csv_paths: dict[str, str | Path] | None = None,
             start_date: str | None = None,
             end_date: str | None = None) -> None:
    if csv_paths is None:
        csv_paths = {self.CSV_TICKER: self.CSV_DEFAULT_PATH}
```
**Pattern to add (Pitfall 5 / Open Q2 — recommended option b):** add an optional `csv_paths: dict[str, str | Path] | None = None` param to `TradingSystem.__init__` (signature at `:45-51`, default `None`) and pass it straight through to `CsvPriceStore(csv_paths=csv_paths, ...)`. Oracle-dark (default `None` -> identical single-golden-ticker behavior) and exactly the seam the Phase-9 E2E harness reuses.
- **TABS.** Match the existing ctor indentation.
- Constructor already imports `from typing import Optional`; for the `str | Path` annotation add `from pathlib import Path` (Path is not yet imported in this file — verify before use).
- If the planner prefers ZERO production-constructor change, the fallback is direct component wiring in the integration test (Pitfall 5 option c) — but option (b) is the recommended, reusable seam.

---

### `tests/unit/universe/test_membership.py` (unit test, transform) — 4 SPACES

**Analog:** the existing `derive_membership` cases, same file (`:25-57`).

**Style to mirror** (`test_membership.py:13, 25-28`):
```python
pytestmark = pytest.mark.unit            # explicit per house style (also folder-derived)

def test_union_of_strategy_and_screener_tickers_flattens_pairs():
    strategies = [StrategyStub(["BTCUSDT"]), StrategyStub([("A", "B")])]
    result = derive_membership(strategies, screener_tickers=["ETHUSDT"])
    assert set(result) == {"BTCUSDT", "A", "B", "ETHUSDT"}   # SET equality, never order
```
**Patterns to copy:** plain functions (no class), `pytestmark = pytest.mark.unit`, import from the barrel (`from itrader.universe import active_membership, is_active`), `assert ... == {set}` (never order-dependent). Build tz-aware stamps consistently (a naive `datetime(2021,1,1)` is fine for the PURE function unit tests where the span map is also built naive — but keep span and `asof` the same tz-ness; see RESEARCH Code Examples `:313-335`).

**Cases to add (UNIV-01, the three proofs + edges):** inclusive listing day True; inclusive end day True; day-before False; day-after False; mid-life gap day still True (D-01); unknown ticker False; `active_membership` set over differing spans at three T points (only-first-listed / all-listed / some-ended).

---

### `tests/unit/price/test_bar_feed.py` (unit test, event-driven) — 4 SPACES

**Analog A — the fixture/helper toolkit** (`test_bar_feed.py:49-107`):
- `ts(stamp)` (`:49-51`) -> tz-aware `pd.Timestamp(stamp, tz=TIMEZONE)`. **Use this for every stamp** (Pitfall 2 tz-safety).
- `write_kline_csv(path, stamps, base)` (`:54-72`) -> golden-schema kline CSV the real `CsvPriceStore` loads unchanged. **Reuse — do NOT invent a fixture format** (Don't-Hand-Roll).
- `duo_feed` fixture (`:96-107`) -> multi-symbol feed with a late-listing `LATEUSD` (June-only bars). **The exact mid-run-listing shape** — mirror it for a "late lister" and a "ends-early" ticker, and add a gapped-stamps ticker for the mid-life-gap case.

**Analog B — the caplog warn assertions** (`test_bar_feed.py:303-321`):
```python
def test_generate_bar_event_missing_membership_ticker_warns(duo_feed, caplog):
    duo_feed.bind(None, ['BTCUSD', 'LATEUSD'])
    with caplog.at_level(logging.WARNING):
        event = duo_feed.generate_bar_event(TimeEvent(time=ts('2020-01-03')))
    assert 'LATEUSD' in caplog.text
    assert '2020-01-03' in caplog.text

def test_generate_bar_event_no_warning_when_membership_covered(duo_feed, caplog):
    duo_feed.bind(None, ['BTCUSD', 'ETHUSD'])
    with caplog.at_level(logging.WARNING):
        duo_feed.generate_bar_event(TimeEvent(time=ts('2020-01-03')))
    assert caplog.records == []
```
**IMPORTANT — these two EXISTING tests change semantics under D-04** and must be updated, not just appended to:
- The current `..._missing_membership_ticker_warns` test asserts `LATEUSD` (a late-lister, OUTSIDE its span at the January tick) WARNS. Under D-04 that becomes EXPECTED absence -> SILENT. This test must be **inverted** to assert NO warning before listing (`assert caplog.records == []`), and a NEW test added for the mid-life-gap WARN case.

**Cases to add/adjust (UNIV-01/UNIV-02 + D-04):**
- `bind` membership + tick before a late-lister's first bar -> `caplog.records == []` (silent, expected absence).
- `bind` + tick inside a gapped ticker's span with no bar at T -> warns, `'<ticker>' in caplog.text and '<date>' in caplog.text` (mid-life gap).
- `bind` + tick after an ended ticker's last bar -> silent.
- span-cache unit: build feed, assert `feed._spans[ticker] == (first, last)` from the loaded frame (`-k span`).

---

### `tests/integration/test_universe_spans.py` (integration test, end-to-end run) — 4 SPACES — CREATE

**Analog A — `test_backtest_smoke.py`** (whole file): the construct -> add strategy -> add portfolio -> `system.run(print_summary=False)` -> assert-on-positions shape. Module docstring + auto-marker (no hand-added marker — folder-derived `integration`).

**Analog B — the `backtest_engine` factory** (`tests/integration/conftest.py:48-79`): deferred-import callable returning a `TradingSystem`. **The integration test needs multi-ticker synthetic CSVs**, which the current factory cannot inject (it hardcodes the single golden dataset, Pitfall 5). Options:
1. **Recommended:** once the `csv_paths` passthrough lands on `TradingSystem.__init__` (enabling task above), construct `TradingSystem(exchange="csv", csv_paths={..synthetic..}, start_date=.., end_date=..)` directly in the test (write the CSVs with `write_kline_csv` into `tmp_path`).
2. Fallback: build the component graph directly in the test (most isolated, duplicates wiring).

**Assertions to copy/extend (UNIV-02 acceptance lock, RESEARCH OQ3):**
- Engine runs over the UNION window of a mid-run lister + a differing-end-date ticker **without raising** (the union ping grid at `backtest_trading_system.py:169-171` already ticks across the union — no grid change).
- A strategy that WOULD trade the late-lister from day one produces **zero fills/positions for that ticker before its listing date** AND **>=1 after** (no-look-ahead lock — first fill timestamp strictly `>= listing_date`).
- Pull positions via `system.portfolio_handler.get_portfolio(pid)` exactly as the smoke test does (`:61-67`).
- **Pitfall 3:** use whole-day daily stamps (golden schema) so the CSV load doesn't touch the alias-sensitive resample path and trip a `FutureWarning`-as-error.

## Shared Patterns

### Pure-function-over-injected-shape (the membership module's house style)
**Source:** `itrader/universe/membership.py:38-73` (`derive_membership` + `SupportsTickers` Protocol)
**Apply to:** `active_membership` / `is_active` — no class, no state, no queue, no store/feed import inside the function; trivially unit-testable; composes into the future `screen(active_membership(T), ranking)`. 4-space indent, NumPy docstring with decision tags.

### Compute-once-at-init, slice-fast (M5-03)
**Source:** `bar_feed.py:151-153` (the `_frames` build loop) + `:188-206` (memoized resample)
**Apply to:** the `_spans` cache — built in the SAME `__init__` loop, zero extra frame reads. Never recompute per-tick / per-call from the store (Anti-pattern).

### Sparse-universe guard: absent, never None (D-15 / WR-12)
**Source:** `bar_feed.py:261-276` (`current_bars` sparse dict) + `strategies_handler.py:69-73` (`.get(ticker)` + skip)
**Apply to:** `is_active` returns `False` for an unknown ticker (mirrors "absent, not None"); the strategy handler keeps its `if bar is None: continue` skip; the feed's warn loop is the SINGLE observability owner (D-04) — consumers stay silent.

### tz-aware datetime discipline (Pitfall 2)
**Source:** `ts()` helper `test_bar_feed.py:49-51` (`pd.Timestamp(stamp, tz=TIMEZONE)`); `csv_store.py` tz-aware index; `TimeEvent.time` tz-aware
**Apply to:** span bounds and `asof` comparisons in `is_active`; every test stamp built via `ts()`. A naive-vs-aware compare raises `TypeError` = hard failure under `filterwarnings=["error"]`.

### Oracle-darkness (the invariant gate)
**Source:** `tests/integration/test_backtest_oracle.py` (134 trades / `final_equity 46132.7668`)
**Apply to:** EVERY Phase-3 change. All changes are log/query-surface only; none touch `bars`, `BarEvent`, `current_bars`, or the SIGNAL/ORDER/FILL routes. Run `make test-integration` after each change.

### Indentation per file (CLAUDE.md — load-bearing under `--strict`)
- **4 spaces:** `universe/membership.py`, `universe/__init__.py`, `price_handler/feed/bar_feed.py`, all `tests/`.
- **TABS:** `strategy_handler/strategies_handler.py`, `trading_system/backtest_trading_system.py`.
- Match the file being edited. A mixed-indentation diff in a tab file breaks it.

## No Analog Found

None. Every file in scope has a direct in-codebase analog (this is an add-alongside / refine-in-place phase). The planner does NOT need to fall back to RESEARCH-only patterns for any file.

## Metadata

**Analog search scope:** `itrader/universe/`, `itrader/price_handler/feed/`, `itrader/price_handler/store/`, `itrader/strategy_handler/`, `itrader/trading_system/`, `tests/unit/universe/`, `tests/unit/price/`, `tests/integration/`
**Files scanned:** 11 source + test files read; 2 grep sweeps (deleted-warning string, generate_bar_event/caplog sites)
**Pattern extraction date:** 2026-06-09

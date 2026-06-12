# Phase 3: Hot-Path Performance - Pattern Map

**Mapped:** 2026-06-11
**Files analyzed:** 13 (3 NEW symbols/tests homes + 10 in-place edit targets)
**Analogs found:** 13 / 13 (all in-repo, all verified against live source)

> This is a brownfield, **behavior-preserving** performance refactor. MOST work edits
> existing files in place; for those a brief analog pointer + the verified indentation
> suffices. The genuinely NEW artifacts (two storage accessors + four behavioral-assert
> tests) get full code excerpts because they are the only places the planner must
> author a new idiom rather than transform an existing line. Per D-01/D-02 the verification
> law is: **byte-exact oracle proves correctness; deterministic behavioral asserts prove the
> optimization landed; wall-clock benchmarks are REJECTED.**

## Indentation Map (per-FILE — verified with `grep -P '^\t'`, NOT directory shorthand)

CONTEXT/CONVENTIONS describe the hazard by directory; that shorthand is WRONG for the
portfolio targets. Measured this session:

| File | Indent | Tab lines | Space lines | Planner tag |
|------|--------|-----------|-------------|-------------|
| `itrader/portfolio_handler/storage/in_memory_storage.py` | **4-SPACE** | 0 | 55 | 4-space |
| `itrader/portfolio_handler/base.py` | **4-SPACE** | 3 (only top `TYPE_CHECKING` block — DO NOT touch) | 184 | 4-space |
| `itrader/portfolio_handler/metrics/metrics_manager.py` | **4-SPACE** | 0 | 599 | 4-space |
| `itrader/portfolio_handler/position/position_manager.py` | **4-SPACE** | 0 | 389 | 4-space |
| `itrader/portfolio_handler/portfolio_handler.py` | **4-SPACE** | 0 | 426 | 4-space |
| `itrader/order_handler/order_manager.py` | **TAB** | 1143 | 0 | tab |
| `itrader/execution_handler/exchanges/simulated.py` | **TAB** | 559 | 0 | tab |
| `itrader/strategy_handler/strategies/SMA_MACD_strategy.py` | **TAB** | 60 | 0 | tab |
| `itrader/price_handler/feed/bar_feed.py` | **4-SPACE** | 0 | 262 | 4-space |
| `itrader/core/bar.py` | **4-SPACE** | 0 | 34 | 4-space |
| `itrader/price_handler/store/csv_store.py` | **4-SPACE** | 0 | 134 | 4-space |

**Net:** all six PERF-01/PERF-02-portfolio files are 4-space; only `order_manager.py`,
`simulated.py`, `SMA_MACD_strategy.py` are genuine TAB. The single safe rule: match the
file you edit, never normalize.

## File Classification

| New/Modified Symbol | Role | Data Flow | Closest Analog | Match Quality |
|---------------------|------|-----------|----------------|---------------|
| `snapshot_count()` / `get_latest_snapshot()` on `PortfolioStateStorage` ABC + InMemory | storage seam (abstractmethod + impl) | CRUD (read accessor) | sibling accessors in the SAME ABC/impl pair (`get_reserved_cash`/`get_snapshots`) | exact |
| `metrics_manager.py:171-173,189,193` (consume accessors) | manager (consumer) | request-response | self (in-place transform of existing trim/`[-1]` lines) | in-place |
| NEW object-identity tests (5 getters) | unit test | object-identity assert | `tests/unit/portfolio/test_state_storage.py` round-trip tests | exact |
| NEW accessor-behavior tests | unit test | accessor assert | `test_state_storage.py` + `test_metrics_manager.py` | exact |
| NEW no-call `Bar.from_row` sentinel test | unit test | monkeypatch call-presence | `test_bar_feed.py::test_zero_resample_calls_on_per_tick_path` | exact |
| W1-07 non-EXECUTED no-op assert | unit test | behavioral guard | `tests/unit/portfolio/test_on_fill_status_guard.py` (extend/confirm) | exact |
| `in_memory_storage.py:52,61,70,87,95` drop `.copy()` (D-03) | storage seam | CRUD | self (in-place) | in-place |
| `base.py` docstring contract rewrite (D-03) | ABC contract | — | self (in-place docstring) | in-place |
| `bar_feed.py:164-167,281-296` eager prebuild (D-07) | price feed | transform/batch (init) + CRUD (lookup) | the existing `_spans` precompute in the SAME `__init__` loop | exact |
| `position_manager.py:277,287,298,303` re-wrap drop (W1-08) | manager | transform | self (in-place) | in-place |
| `order_manager.py:934,939` local-cache (W1-03) | manager | request-response | self (in-place) | in-place (TAB) |
| `simulated.py:122,127-135,343,400` is_connected (W1-14) | exchange | request-response | self (in-place) | in-place (TAB) |
| `portfolio_handler.py:290,297-305` guard hoist (W1-07) | handler | event-driven | self (in-place) | in-place |
| `csv_store.py:165` load-time copy (W1-09) | price store | file-I/O (load) | self (in-place) | in-place |
| `SMA_MACD_strategy.py:59-61,66` MACD guard (W1-12) | strategy | transform | self (in-place — NO test, D-02) | in-place (TAB) |

---

## Pattern Assignments — NEW ARTIFACTS (full excerpts)

### `snapshot_count()` / `get_latest_snapshot()` — two new accessors (D-06)

**Role:** storage seam (abstractmethod on ABC + concrete impl). **Indent: 4-SPACE both files.**

**Analog 1 — ABC abstractmethod pair** (`itrader/portfolio_handler/base.py`, the snapshot
block lines 209-242). The new abstractmethods go immediately after `set_snapshots`
(after line 242). Copy the NumPy-style docstring + `pass` body shape, e.g. the existing
`get_reserved_cash` (lines 139-152) is the closest "returns a scalar derived from the
container" analog for `snapshot_count`; `get_snapshots` (lines 222-231) is the analog for
`get_latest_snapshot`:

```python
    @abstractmethod
    def get_reserved_cash(self) -> Decimal:
        """Return the total currently reserved cash amount.
        ...
        Returns
        -------
        Decimal
            The sum of all per-reference reservations.
        """
        pass
```

New pair to add (matching that shape — signatures are Claude's discretion per CONTEXT, this
is the project-native form):

```python
    @abstractmethod
    def snapshot_count(self) -> int:
        """Return the number of recorded metrics snapshots (count-only — no copy)."""
        pass

    @abstractmethod
    def get_latest_snapshot(self) -> Optional[Any]:
        """Return the most-recent snapshot, or ``None`` if none recorded (last-only — no copy)."""
        pass
```

**Analog 2 — InMemory impl pair** (`itrader/portfolio_handler/storage/in_memory_storage.py`,
the snapshot block lines 89-98). The existing `get_reserved_cash` (a derived-scalar accessor
reading `self._reservations`) and `get_snapshots` are the direct analogs. The new methods go
in the `# -- Metrics snapshots` section (after `set_snapshots`, line 98), reading `self._snapshots`
directly with NO `.copy()`:

```python
    def add_snapshot(self, snapshot: Any) -> None:
        self._snapshots.append(snapshot)

    def get_snapshots(self) -> List[Any]:
        return self._snapshots.copy()          # ← D-03 drops .copy() here too

    def set_snapshots(self, snapshots: List[Any]) -> None:
        self._snapshots = list(snapshots)
```

New impl (count-only / last-only — the whole point is to avoid the `.copy()` the trim path used):

```python
    def snapshot_count(self) -> int:
        return len(self._snapshots)

    def get_latest_snapshot(self) -> Optional[Any]:
        return self._snapshots[-1] if self._snapshots else None
```

**Consumer rewrite** (`metrics_manager.py:171-173` trim, `:189,193` reads):
```python
# BEFORE (171-173): whole-list copy on the per-tick path
snapshots = self._storage.get_snapshots()
if len(snapshots) > self.max_snapshots:
    self._storage.set_snapshots(snapshots[-self.max_snapshots:])
# AFTER: count-only guard (trim still never fires on the golden run, but no whole-list copy)
if self._storage.snapshot_count() > self.max_snapshots:
    ...trim...
# BEFORE (189,193): get_current_metrics
if not self._storage.get_snapshots(): ...          # → if self._storage.snapshot_count() == 0
latest_snapshot = self._storage.get_snapshots()[-1] # → latest_snapshot = self._storage.get_latest_snapshot()
```

---

### NEW object-identity test for the copy-drop (PERF-01 / D-03)

**Analog:** `tests/unit/portfolio/test_state_storage.py` — uses bare `InMemoryPortfolioStateStorage()`,
`object()` sentinels, and `is`-identity asserts throughout (e.g. line 76 `is sentinel_open`,
line 99 `assert not [...]`). The new identity test extends this file (it has no class — just
top-level `def test_*` functions). The exact project idiom to copy:

```python
def test_positions_round_trip():
    backend = InMemoryPortfolioStateStorage()
    sentinel_open = object()
    backend.set_position("BTCUSDT", sentinel_open)
    assert backend.get_position("BTCUSDT") is sentinel_open    # ← is-identity idiom
```

New test (the claim is "same live dict — would be False with .copy()"):
```python
def test_get_positions_returns_live_container_no_copy():
    backend = InMemoryPortfolioStateStorage()
    backend.set_position("BTCUSD", object())
    assert backend.get_positions() is backend.get_positions()  # D-03: no .copy()
# repeat for get_closed_positions / get_transaction_history / get_cash_operations / get_snapshots
```

**D-05 executor audit (NOT a new test — a grep task):** before dropping copies, grep
`tests/unit/portfolio/` for any test that mutates a getter result (`.append`/`.pop`/`[k]=`)
then asserts storage unchanged — that pattern relied on the copy and must migrate (caller
`copy()`s locally). The existing round-trip tests above only `==`-compare, so they are safe.

---

### NEW accessor-behavior test (PERF-01 / D-06)

**Analog:** same `test_state_storage.py::test_snapshots_round_trip` (line 120-125) and
`test_snapshots_replaceable_for_size_trim` (line 128-134) — `object()` snapshots, `add_snapshot`,
`==` on `get_snapshots()`. `test_metrics_manager.py::test_metrics_manager_initialization`
(line 51-57) shows the `assert len(mm._storage.get_snapshots()) == 0` empty-state idiom — the
new `snapshot_count() == 0` assert mirrors it.

```python
def test_snapshot_count_and_latest():
    backend = InMemoryPortfolioStateStorage()
    assert backend.snapshot_count() == 0
    assert backend.get_latest_snapshot() is None
    s1, s2 = object(), object()
    backend.add_snapshot(s1); backend.add_snapshot(s2)
    assert backend.snapshot_count() == 2
    assert backend.get_latest_snapshot() is s2   # last-only, no whole-list copy
```

---

### NEW no-call `Bar.from_row` sentinel test (PERF-03 / D-07)

**Analog (the gold-standard idiom):** `tests/unit/price/test_bar_feed.py::test_zero_resample_calls_on_per_tick_path`
(lines 186-208) — already proves "ZERO calls on the per-tick path" via `monkeypatch.setattr`
on a method, with a `calls = {'count': 0}` counter. This is the exact call-presence pattern to
replicate; `Bar.from_row` replaces `pd.DataFrame.resample`. The verified existing excerpt:

```python
def test_zero_resample_calls_on_per_tick_path(daily_store, monkeypatch):
    feed = BacktestBarFeed(daily_store, timedelta(days=1))
    calls = {'count': 0}
    original = pd.DataFrame.resample
    def counting_resample(self, *args, **kwargs):
        calls['count'] += 1
        return original(self, *args, **kwargs)
    monkeypatch.setattr(pd.DataFrame, 'resample', counting_resample)
    feed.window(...)
    assert calls['count'] == 0          # ← per-tick path makes zero calls
```

Fixtures already in this file: `daily_feed`, `daily_store`, `duo_feed`, `ts(stamp)` helper
(line 49), and the `current_bars` Decimal-fields test (line 213-226) showing how to call
`current_bars(ts('2020-01-03'))` and assert `isinstance(bar, Bar)` + `Decimal(str(...))` values.
New test (after prebuild, `current_bars` must NOT call `Bar.from_row`; it is a `classmethod`,
so patch it as one):

```python
def test_current_bars_serves_prebuilt_no_from_row_per_tick(duo_feed, monkeypatch):
    import itrader.core.bar as bar_mod
    def _boom(*a, **k):
        raise AssertionError("Bar.from_row called per tick — prebuild not serving")
    monkeypatch.setattr(bar_mod.Bar, "from_row", classmethod(_boom))
    bars = duo_feed.current_bars(ts('2020-01-03'))   # must NOT call from_row
    assert isinstance(bars['BTCUSD'], Bar)
```

**Source of `Bar.from_row`** (`itrader/core/bar.py:52-68`, 4-space) — the 5 `Decimal(str(row[...]))`
that prebuild front-loads; UNCHANGED, just called at `__init__` instead of per tick. The prebuild
loop in `bar_feed.py.__init__` should reuse this exact `Bar.from_row(time, row)` call (warning-clean
per Pitfall 4 — do not introduce a new pandas resample/offset path).

---

### W1-07 non-EXECUTED no-op guard assert (PERF-02 — the one mechanical item with an observable side-effect)

**Analog / home:** `tests/unit/portfolio/test_on_fill_status_guard.py` ALREADY exists and tests
exactly this (lines 45-63): `test_cancelled_fill_creates_no_transaction`,
`test_refused_fill_creates_no_transaction`, `test_executed_fill_is_processed`. The hoist must keep
these green unchanged — a non-EXECUTED fill returns early as a no-op (0 positions, 0 transactions).
The existing idiom to preserve:

```python
def test_cancelled_fill_creates_no_transaction(env):
    assert env.ptf.on_fill(env.fill("CANCELLED")) is None       # ignored
    portfolio = env.ptf.get_portfolio(env.pid)
    assert len(portfolio.positions) == 0
    assert len(portfolio.transactions) == 0
```

The hoist target (`portfolio_handler.py:290` `with self._operation_context("on_fill") as correlation_id`
→ the non-EXECUTED `return` at line 297-304): move the `if fill_event.status != FillStatus.EXECUTED: return`
guard ABOVE the `_operation_context`/correlation-id allocation while keeping the EXECUTED-vs-non-EXECUTED
semantics identical. The existing guard test covers it; extend only if the observable no-op behavior
would change (it must not).

---

## Pattern Assignments — IN-PLACE TRANSFORMS (analog = self; brief pointers)

### `bar_feed.py` eager prebuild (D-07/D-08/D-09) — 4-SPACE

**Analog (in-file):** the existing `_spans` precompute in the SAME `__init__` loop
(`bar_feed.py:163-167`) — it iterates `self._symbols`, reads each frame once, and caches
availability metadata alongside `self._frames`. The module docstring already blesses this as
"availability metadata ... NOT a decision-price look-ahead." The Bar prebuild mirrors it exactly:

```python
for ticker in self._symbols:
    frame = store.read_bars(ticker)
    self._frames[(ticker, self._base_alias)] = frame
    self._spans[ticker] = (frame.index[0], frame.index[-1])
    # NEW: build {time: Bar} per ticker over the SAME rows (Bar.from_row, bit-identical)
```

`current_bars(time)` (lines 281-296) then becomes a dict lookup replacing
`searchsorted` + `iloc` + `Bar.from_row`, keeping the EXACT-stamp existence semantics
(`index[pos] == time` → `time in prebuilt[ticker]`). **Honest rationale (D-09):** "structural
hot-loop de-pandas, bit-identical" — does NOT reduce the Decimal-conversion count, front-loads it.

### `in_memory_storage.py` drop `.copy()` ×5 (D-03) — 4-SPACE

Lines 52, 61, 70, 87, 95 — `return self._X.copy()` → `return self._X`. ABC docstring rewrite
in `base.py` (lines 67-75, 99-108, 126-135, 198-207, 222-231): "Return a shallow copy of ..." →
"Return a read-only view of ... (callers MUST NOT mutate — D-19 single-writer; copy yourself if
you need ownership)."

### `position_manager.py` W1-08 re-wrap drop — 4-SPACE

Lines 277/287/298/303: `Decimal(str(position.market_value))` → `position.market_value` (and
`.unrealised_pnl`/`.realised_pnl`) — all three are verified `-> Decimal` at source. The
accumulators (`Decimal('0.00')`) and the `.values()` iteration are unchanged. **D-05 caller-audit
note:** line 276 iterates `get_positions().values()` read-only; `close_all_positions:425` already
defends with `list(...)` — both safe under the copy-drop.

### `order_manager.py` W1-03 local-cache — **TAB**

Lines 934/939: `self.portfolio_handler.open_position_count(portfolio_id)` is called twice in the
same branch (the `if >=` guard and the f-string message). Cache once into a local before the `if`.

### `simulated.py` W1-14 redundant is_connected — **TAB**

Lines 122/127-135 (`execute_order`), 343, 400 — remove redundant repeat `is_connected()` checks
on a path that already validated connection. Keep the fill path byte-identical (oracle + e2e cover).

### `csv_store.py` W1-09 load-time copy — 4-SPACE

Line 165: `data = raw[expected_cols].copy()` → drop the `.copy()` (the subsequent `.columns =`
and `.set_index` build a fresh frame). Load-path only; oracle + `test_csv_store.py` cover.

### `SMA_MACD_strategy.py` W1-12 MACD guard reorder — **TAB** — **NO NEW TEST (D-02)**

Lines 59-61 compute MACD unconditionally BEFORE the `if short_sma.iloc[-1] >= long_sma.iloc[-1]`
guard at line 66. Move the MACD computation INSIDE that guard. **Verified by code review +
byte-exact oracle ONLY — D-02 forbids any unit test against the strategy module.**

---

## Shared Patterns (cross-cutting)

### Behavioral-assert verification law (D-01/D-02)
**Source idioms:** `tests/unit/price/test_bar_feed.py` (monkeypatch counter, line 186-208),
`tests/unit/portfolio/test_state_storage.py` (`is`-identity, line 76), `tests/integration/test_backtest_oracle.py`
(`assert_frame_equal(check_exact=True)`).
**Apply to:** every PERF-01/PERF-03 optimization gets a paired behavioral assert (identity /
accessor / no-call). PERF-02 mechanical items (W1-08/03/14/09) and W1-12 are **oracle + mypy
only** — no new test. W1-07 is the one PERF-02 item with a behavioral assert (existing
`test_on_fill_status_guard.py`). Wall-clock benchmarks are FORBIDDEN.

### Byte-exact oracle net (cross-cutting correctness)
**Source:** `tests/integration/test_backtest_oracle.py` (DO NOT MODIFY).
**Apply to:** the whole phase. Must stay green unchanged — 134 trades / final_equity
46189.87730727451. Plus `mypy itrader` (strict) clean and full e2e suite green.

### Decimal end-to-end (money policy)
**Source:** `itrader/core/bar.py:61-68` (`Decimal(str(...))`), `core/money.to_money`.
**Apply to:** W1-08 (the dropped re-wraps must leave the value `Decimal` — it already is) and the
prebuild loop (reuse `Bar.from_row`, bit-identical, never `Decimal(float)`).

### `filterwarnings=["error"]` strictness
**Source:** `pyproject.toml [tool.pytest.ini_options]`.
**Apply to:** the prebuild loop must not introduce a new pandas resample/offset path (any
FutureWarning fails the suite — Pitfall 4). Reuse the warning-clean `Bar.from_row`.

## No Analog Found

None. Every NEW symbol and test has a verified in-repo analog (the ABC accessor siblings, the
three existing test files with their idioms). This phase invents no new mechanic — it reuses the
repo's own object-identity, monkeypatch-counter, and round-trip idioms.

## Metadata

**Analog search scope:** `itrader/portfolio_handler/{storage,metrics,position}/`,
`itrader/portfolio_handler/{base,portfolio_handler}.py`, `itrader/price_handler/{feed,store}/`,
`itrader/core/bar.py`, `itrader/order_handler/order_manager.py`,
`itrader/execution_handler/exchanges/simulated.py`,
`itrader/strategy_handler/strategies/SMA_MACD_strategy.py`,
`tests/unit/portfolio/{test_state_storage,test_metrics_manager,test_on_fill_status_guard}.py`,
`tests/unit/price/test_bar_feed.py`.
**Files scanned:** 13 source + 4 test homes.
**Indentation verified:** `grep -P '^\t'` per file (table above — corrects the directory shorthand).
**Pattern extraction date:** 2026-06-11

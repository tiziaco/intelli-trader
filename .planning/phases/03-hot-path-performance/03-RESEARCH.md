# Phase 3: Hot-Path Performance - Research

**Researched:** 2026-06-11
**Domain:** Behavior-preserving performance refactor of an event-driven backtest engine (Python 3.13). No external libraries introduced; all findings verified against the in-repo source.
**Confidence:** HIGH (every claim verified against the codebase at the cited line; no training-data / web claims load-bearing)

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- **D-01:** Prove **and lock** each optimization with **deterministic behavioral regression assertions** — NOT wall-clock benchmarks (environment-flaky) and NOT code-review-only. Concretely: object-**identity** assertion that `get_positions()` returns the same dict object (no `.copy()`); a feed-level assertion that `current_bars()` serves prebuilt `Bar`s (no per-tick `Bar.from_row`). CI-safe, project-style regression-locking, proves the SPECIFIC change landed without timing flakiness.
- **D-02 (owner constraint):** **Do NOT add any new unit test against the `SMA_MACD` strategy.** The W1-12 MACD-guard reorder is verified by **code review + byte-exact oracle only** — no behavioral assert is written against the strategy module.
- **D-03:** Drop the defensive `.copy()` from **ALL** `InMemoryPortfolioStateStorage` getters — `get_positions`, `get_closed_positions`, `get_transaction_history`, `get_cash_operations`, `get_snapshots`. The `PortfolioStateStorage` ABC docstring contract becomes: **"getters return read-only views; callers MUST NOT mutate (D-19 single-writer); copy yourself if you need ownership."**
- **D-04 (gap-discovery delta — owner-flagged):** Do **NOT** add the `*_snapshot()` copy-returning twin the W1-01 finding recommended. Rationale: the hedge exists only for a hypothetical write-through-cache live backend; a query-based live/Postgres backend is copy-safe for free. Adding the seam now is speculative API for deferred work — violates the Phase-1/Phase-2 D-05 "no pre-building for deferred work" discipline. **Log as a bounded gap-discovery delta.**
- **D-05 (caller-mutation audit — DONE during discussion):** Dropping the copies is safe — verified no caller mutates a returned container. (`position_manager.py:241` mutates Position *objects* in place, never the container; `close_all_positions():425` already defends with `list(...)`; reporting only reads.) **Executor MUST still confirm** no *test* mutates a getter result and asserts storage stayed unchanged.
- **D-06:** Replace the never-firing per-tick snapshot-trim `.copy()` in `metrics_manager.py:171` with `snapshot_count()` / `get_latest_snapshot()` accessors on the storage seam (count-only / last-only — no whole-list copy). Add both to the ABC + InMemory.
- **D-07:** **Eager-materialize** all `Bar`s once at `BacktestBarFeed` construction; `current_bars()` becomes a pure dict lookup, removing pandas `iloc` + per-tick Decimal construction from the hot loop. Bit-identical, oracle byte-exact. Feed-level behavioral assert (no `Bar.from_row` per tick) per D-01.
- **D-08:** **Lazy-memoize REJECTED.** Each `(ticker, time)` is queried exactly once over the run — a cache would serve zero hits and add pure overhead.
- **D-09 (gap-discovery delta — owner-flagged):** W1-04's "computed once" rationale **overstates** the saving. Each row is already converted exactly once across the run, so eager prebuild does NOT reduce the total Decimal-conversion count — it **front-loads** it to init. The real win is **structural** (remove pandas `iloc` + per-tick object churn). The planner MUST write the honest rationale ("structural hot-loop de-pandas, bit-identical"), NOT "eliminates per-tick Decimal conversions."
- **D-10 (bounded PERF-02 descope — owner-flagged):** **DEFER** W1-13 (the `get_active_portfolios()` per-tick cache) — no payoff on the single-portfolio golden run, and an oracle-blind invalidation-correctness risk across the `ACTIVE/INACTIVE/ARCHIVED` state machine. Correct PERF-02 / ROADMAP §Phase-3 SC-2 wording to drop "active-portfolio recompute". The other PERF-02 items (W1-08/03/14/07/09) stay in scope.

### Claude's Discretion
- Plan/wave decomposition (grouping PERF-01/02/03 + the mechanical W1-08/03/14/07/09/12 items into plans/waves).
- Exact mechanics of each mechanical transform (W1-08 at `position_manager.py:277,287,298,303`; W1-03 at `order_manager.py:934,939`; W1-14 at `simulated.py:122,127-135,343,400`; W1-07 at `portfolio_handler.py:291,297-305`; W1-09 at `csv_store.py:165`).
- Exact placement/naming of the new behavioral-assertion tests and the `snapshot_count()`/`get_latest_snapshot()` accessor signatures.
- Exact wording/home of the two gap-discovery deltas (D-04, D-09) and the corrected SC-2 wording (D-10).
- Extent of touched-path opportunistic cleanup (Phase-1 D-05 / `CLEANUP-STANDARD.md`).

### Deferred Ideas (OUT OF SCOPE)
- **W1-13 — `get_active_portfolios()` per-tick cache** (PERF-02 descope, D-10). Revisit when multi-portfolio runs are a measured workload — and only then with a multi-portfolio status-transition regression test (active→inactive→active invalidation).
- Any change that moves the oracle; incremental/stateful indicators; the `order_manager.py` split (Phase 6); other cleanup-review batches (Phases 4-5).
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| PERF-01 | Kill the never-firing per-tick snapshot-trim copy via `snapshot_count()`/`get_latest_snapshot()` accessors (D-06); drop the defensive per-call `.copy()` from all 5 in-memory storage getters under the D-19 single-writer contract (D-03). | `in_memory_storage.py:51-52,60-61,69-70,86-87,94-95` (the 5 `.copy()` sites); `base.py:66-108,198-231` (ABC getter contracts + snapshot abstractmethods to amend); `metrics_manager.py:171-173` (the never-firing trim). Validation: object-identity assert + new accessor behavior asserts (D-01). |
| PERF-02 | Drop redundant `Decimal(str(Decimal))` re-wraps (W1-08) and duplicated per-tick work — `open_position_count` ×2 (W1-03), `is_connected` ×2-3 (W1-14), premature `on_fill` guard allocation (W1-07), load-time copy (W1-09). **W1-13 DESCOPED (D-10).** | `position_manager.py:277,287,298,303` (re-wraps — `market_value`/`unrealised_pnl`/`realised_pnl` confirmed `Decimal`-returning); `order_manager.py:934,939`; `simulated.py:122,127-135,343,400`; `portfolio_handler.py:291,297-305`; `csv_store.py:165`. Validation: byte-exact oracle + `mypy --strict`; W1-07 gets a targeted on_fill-guard behavioral assert (see Validation Architecture). |
| PERF-03 | Compute MACD inside the SMA guard (W1-12) — code-review + oracle only, D-02; serve prebuilt `Bar`s from `BacktestBarFeed` (W1-04 / D-07) instead of per-tick `Bar.from_row`. | `SMA_MACD_strategy.py:59-61` (MACD computed unconditionally, BEFORE the `short_sma>=long_sma` guard at line 66 — confirmed); `bar_feed.py:164-167` (prebuild seam in `__init__`), `bar_feed.py:281-296` (per-tick `current_bars` → dict lookup); `bar.py:52-68` (`Bar.from_row`, the 5 `Decimal(str())`). Validation: feed-level no-`Bar.from_row`-per-tick call-presence assert (D-01) + byte-exact oracle. |
</phase_requirements>

## Summary

This is a brownfield, behavior-preserving performance phase. CONTEXT.md is exhaustive: scope, code sites, and ten decisions (D-01..D-10) are locked, and a scout already identified every edit location. **This research deliberately does not re-discover scope.** It verifies each cited site against the live source (all confirmed), corrects one shorthand that would otherwise produce a broken diff (the tab/space mapping is per-FILE, not per-directory — four of the "tab" portfolio modules are actually 4-space), and formalizes the **Validation Architecture** the orchestrator needs to seed `VALIDATION.md` (Nyquist Dimension 8).

The verification philosophy is the load-bearing output (CONTEXT §Specific Ideas): the **byte-exact oracle proves correctness**; **deterministic behavioral asserts prove each optimization actually landed**; **wall-clock benchmarks are rejected as flaky**. Neither the oracle alone (it cannot tell whether a `.copy()` is still there as long as values match) nor the asserts alone (they pin a mechanic but not end-to-end numbers) is sufficient — the two layers are complementary and both are required. The project already runs in exactly this register: `test_backtest_oracle.py` asserts trade/equity/summary identity with `check_exact=True` (no tolerance), and the unit suites use `is`-identity and monkeypatch idioms throughout.

**Primary recommendation:** Plan three validation tracks mapped 1:1 to the optimizations — (1) **object-identity** asserts for the storage copy-drop, (2) **accessor-behavior** asserts for the snapshot accessors, (3) **call-presence/no-call** asserts (monkeypatch-sentinel on `Bar.from_row`) for the prebuilt-Bar feed change — and let the existing byte-exact integration oracle be the cross-cutting correctness net for everything, with W1-12 and the mechanical W1-08/03/14/09 transforms covered by **oracle + `mypy --strict` only** (no new test). W1-07 gets one targeted on_fill-guard assert because it is the only mechanical item with an observable side-effect (correlation-id allocation) that the oracle does not see.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Defensive copy policy (PERF-01) | Storage seam (`PortfolioStateStorage` ABC + `InMemoryPortfolioStateStorage`) | Portfolio managers (callers) | The copy contract is a property of the storage seam; the D-19 single-writer contract is the engine-level precondition that makes dropping it correct. Callers only need the contract docstring. |
| Snapshot count/latest accessors (PERF-01/D-06) | Storage seam (ABC + InMemory) | `MetricsManager` (consumer) | The accessor is a storage capability; the manager's trim logic consumes count-only / last-only instead of a whole-list copy. |
| Decimal re-wrap removal (PERF-02/W1-08) | Position-metrics aggregation (`PositionManager`) | `core.money` (the Decimal domain) | The values are already `Decimal` at source (`Position.market_value` etc.); the re-wrap is a no-op in the aggregation layer only. |
| Duplicated per-tick work (PERF-02/W1-03,14,07,09) | Each owning handler (order / execution / portfolio / price-store) | — | Each is a local micro-redundancy inside one domain; no cross-domain contract changes. |
| Prebuilt Bars (PERF-03/W1-04/D-07) | Price feed (`BacktestBarFeed`) | `core.bar.Bar` (value object) | The feed owns per-tick Bar production; prebuild front-loads `Bar.from_row` from the per-tick `current_bars` path to `__init__`. The Bar value object is unchanged. |
| MACD-guard reorder (PERF-03/W1-12) | Strategy (`SMA_MACD_strategy`) | — | Pure intra-strategy control-flow reorder; D-02 forbids a new test against it. |
| Cross-cutting correctness (all) | Integration oracle (`test_backtest_oracle.py`) | e2e suite | Byte-exact golden master is the single net that proves no optimization perturbed results. |

## Standard Stack

No new packages. This phase is pure in-repo refactoring. The relevant existing toolchain:

### Core (already present — verified in `pyproject.toml` / CLAUDE.md)
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| pytest | ^8.4.2 | Test runner; `monkeypatch` fixture for sentinel/spy asserts | The project's only test framework; `filterwarnings=["error"]`, `--strict-markers`, `--strict-config`. |
| pandas | ^2.3.3 | OHLCV frames in `_frames`; the `iloc`/`searchsorted` the prebuild removes | Already the feed's data structure; `Bar.from_row` reads pandas Series rows. |
| Decimal (stdlib) | — | Money end-to-end; the type the W1-08 re-wraps redundantly re-wrap | Locked project decision. |
| mypy | ^2.1.0 (`--strict`) | Static gate over `itrader` | The only static-analysis gate; every mechanical transform must stay strict-clean. |

**Installation:** None. Do not add dependencies. (Package Legitimacy Audit therefore N/A — no external installs in this phase.)

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| monkeypatch-sentinel call-presence assert | `unittest.mock.patch` / `Mock(wraps=...)` spy | The repo already uses `monkeypatch` in 20+ unit files (e.g. `tests/unit/price/test_bar_feed.py`); a sentinel `monkeypatch.setattr(Bar, "from_row", _boom)` that raises if called matches project style and is timing-free. `Mock` spies are also acceptable but heavier. Pick the lighter project-native form. |
| wall-clock micro-benchmark (`pytest-benchmark`) | — | **REJECTED by D-01** — environment-flaky, artifact-only. Do not introduce. |

## Architecture Patterns

### System Architecture: where each optimization sits on the per-tick hot loop

```
TIME tick T
  │
  ├─► BacktestBarFeed.generate_bar_event(T)
  │      └─ current_bars(T)  ◄── PERF-03 / D-07: today = per-symbol searchsorted + iloc + Bar.from_row (5× Decimal(str))
  │                              after  = pure dict lookup into prebuilt {(ticker): {time: Bar}}  (built once in __init__)
  │      └─ BarEvent(bars) ──► queue
  │
  ├─► PortfolioHandler.update_portfolios_market_value
  │      └─ PositionManager.update_position_market_values
  │            └─ storage.get_positions()  ◄── PERF-01 / D-03: drop .copy() (returns the live dict)
  │            └─ get_total_market_value / _unrealized_pnl / _realized_pnl
  │                  └─ Decimal(str(position.market_value))  ◄── PERF-02 / W1-08: market_value is ALREADY Decimal → drop re-wrap
  │      └─ MetricsManager.record_snapshot
  │            └─ get_snapshots(); if len > max: set_snapshots(...)  ◄── PERF-01 / D-06: never fires; replace with
  │                                                                       snapshot_count() guard + get_latest_snapshot()
  │
  ├─► StrategiesHandler.calculate_signals
  │      └─ SMA_MACD_strategy.generate_signal
  │            MACD computed unconditionally (line 59-61)  ◄── PERF-03 / W1-12: move INSIDE the short_sma>=long_sma guard (line 66)
  │
  ├─► ExecutionHandler.on_order / on_market_data
  │      └─ SimulatedExchange  ◄── PERF-02 / W1-14: redundant is_connected() checks (simulated.py:122,127-135,343,400)
  │
  ├─► OrderManager.on_signal  ◄── PERF-02 / W1-03: open_position_count() called ×2 (order_manager.py:934,939) → local-cache
  │
  └─► PortfolioHandler.on_fill  ◄── PERF-02 / W1-07: non-EXECUTED guard sits INSIDE _operation_context (correlation-id alloc);
                                     hoist guard ABOVE the allocation (portfolio_handler.py:291 vs 297-305)
```

### Pattern 1: Prebuilt-Bar map at feed construction (D-07/D-08/D-09)
**What:** In `BacktestBarFeed.__init__`, after loading each `frame` into `self._frames[(ticker, base_alias)]` (`bar_feed.py:164-167`), iterate the frame once and build `{ticker: {timestamp: Bar}}` (or `{(ticker, time): Bar}`). `current_bars(time)` then becomes a dict lookup per symbol instead of `searchsorted` + `iloc` + `Bar.from_row` (`bar_feed.py:291-296`).
**When to use:** Exactly here. D-08 rejects lazy memoization (each `(ticker,time)` is hit once — zero cache hits).
**Look-ahead safety (verified):** Prebuilding does NOT perturb the bar-timing contract. `current_bars(time)` already returns "only the row stamped exactly `time`" (`bar_feed.py:294` — `base.index[pos] == time` equality guard). Eager-building the full map is the SAME existence-and-equality semantics, just precomputed — it is availability/value materialization, not a visibility-window change. The seven-rule contract is enforced in `window()` (the slice path), which is untouched. This mirrors the existing `_spans` precompute, which the module docstring already declares is "availability metadata ... NOT a decision-price look-ahead" (`bar_feed.py:157-162`). **Bit-identical:** `Bar.from_row` is called on the identical rows, producing the identical `Decimal(str(...))` values — only the *timing* of construction moves (init vs per-tick).
**Honest rationale (D-09):** "structural hot-loop de-pandas, bit-identical" — removes pandas `iloc`/`searchsorted` and per-tick object churn. It does NOT reduce the Decimal-conversion *count* (each row is already converted once across the run). Memory: a second OHLCV copy as Decimal Bars, ~linear in rows×symbols (trivial for the single-symbol golden run).

### Pattern 2: Read-only-view storage contract (D-03/D-05)
**What:** Getters return the internal container directly (no `.copy()`); the ABC docstring states callers must not mutate (D-19 single-writer). The five sites in `in_memory_storage.py` (lines 52, 61, 70, 87, 95) drop `.copy()`; the matching ABC docstrings in `base.py` (lines 67-75, 99-108, 126-135, 198-207, 222-231) change "Return a shallow copy of ..." to "Return a read-only view of ... (callers MUST NOT mutate — D-19)".
**Caller-safety (D-05, verified):** No caller mutates a returned *container*. `position_manager.py:245` mutates Position *objects* in place via `update_current_price_time` — the shallow copy never protected those objects, so behavior is unchanged. `close_all_positions` defends with `list(...)` (the real protection). Reporting only reads. **Executor must still grep tests** for any test that mutates a getter result and asserts the storage was unaffected (that pattern relied on the copy and must migrate).

### Pattern 3: Count-only / last-only accessors (D-06)
**What:** Add `snapshot_count() -> int` and `get_latest_snapshot() -> Optional[Any]` to the ABC (`base.py`, after the snapshot block ~line 231) and `InMemoryPortfolioStateStorage` (`in_memory_storage.py`, after line 98). `metrics_manager.py:171-173` replaces `snapshots = get_snapshots(); if len(snapshots) > max: set_snapshots(snapshots[-max:])` with a count guard, and `get_current_metrics` (`metrics_manager.py:189,193`) replaces `get_snapshots()[-1]` / `if not get_snapshots()` with `get_latest_snapshot()` / `snapshot_count() == 0`. The trim copy is "never-firing" because the golden run never exceeds `max_snapshots`; the accessor avoids the whole-list copy regardless.

### Anti-Patterns to Avoid
- **Adding a `*_snapshot()` copy-returning twin** — explicitly declined by D-04. Speculative API for deferred (write-through-cache) work.
- **Caching `get_active_portfolios()`** — W1-13, descoped by D-10. Oracle-blind invalidation risk.
- **Adding a unit test against `SMA_MACD_strategy`** — forbidden by D-02.
- **Introducing a wall-clock benchmark** — forbidden by D-01.
- **Memoizing prebuilt Bars lazily** — rejected by D-08 (zero cache hits).
- **Normalizing indentation** — a mixed-indent diff breaks a tab file. See Tab/Space Hazard below.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Proving a method was/wasn't called | A timing harness or print-counting | `monkeypatch.setattr(Bar, "from_row", sentinel)` that raises/counts (project-native, 20+ existing uses) | Timing-free, CI-safe, deterministic — matches D-01. |
| Asserting two objects are the same instance | `==` deep-compare or `id()` math | `assert a is b` (already used across `tests/unit/order/`) | Identity is the exact claim ("no copy"); `is` is the project idiom. |
| Byte-exact golden comparison | Hand byte-compare of CSVs | `pandas.testing.assert_frame_equal(..., check_exact=True)` (already in `test_backtest_oracle.py`) | Column-level failure messages; no tolerance masking. |

**Key insight:** This phase's "Don't Hand-Roll" is mostly "don't invent a new validation mechanic — the repo already has the exact idioms."

## Runtime State Inventory

> This is a code-refactor phase, not a rename/migration. No stored data, service config, OS-registered state, secrets, or runtime caches embed a renamed string. The one persistent artifact is the **golden master** (`tests/golden/{trades,equity}.csv`, `summary.json`), which this phase must NOT regenerate (oracle byte-exact — 134 trades / final_equity 46189.87730727451). No data migration; behavior-preserving by definition.

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | None — verified: no DB/datastore keys change. The golden CSVs are frozen oracles, not mutable state. | None (must NOT regenerate golden). |
| Live service config | None — verified: backtest-only path, no external service touched. | None. |
| OS-registered state | None — verified: no scheduler/launchd/pm2 registration involved. | None. |
| Secrets/env vars | None — verified: no key/env-var name referenced by the edited sites. | None. |
| Build artifacts | None — verified: no `pyproject.toml`/package-name change; editable install unaffected. | None (note worktree `.venv` shadowing per MEMORY — `PYTHONPATH="$PWD"` if running pytest/mypy from a worktree). |

## Tab/Space Indentation Hazard (per-FILE — verified, corrects CONTEXT shorthand)

CONTEXT.md and CONVENTIONS.md describe the hazard by *directory* ("portfolio/order/execution/strategy handler modules are tab; core/ and price_handler/feed/ are 4-space"). **That shorthand is wrong for several Phase-3 target files.** Verified by `grep -P '^\t'` per file:

| File | Actual indentation | CONTEXT shorthand would say | Planner must flag |
|------|--------------------|-----------------------------|-------------------|
| `portfolio_handler/storage/in_memory_storage.py` | **4-SPACE** | tab | **4-space** ✅ |
| `portfolio_handler/base.py` | **4-SPACE** (184 space lines vs 3 tab lines — only the top `TYPE_CHECKING` block is tab; class body + all abstractmethods are 4-space) | tab | **4-space** ✅ (but the 3 top-of-file tab lines exist — do not touch them) |
| `portfolio_handler/metrics/metrics_manager.py` | **4-SPACE** | tab | **4-space** ✅ |
| `portfolio_handler/position/position_manager.py` | **4-SPACE** | tab | **4-space** ✅ |
| `portfolio_handler/portfolio_handler.py` | **4-SPACE** | tab | **4-space** ✅ |
| `order_handler/order_manager.py` | **TAB** | tab | **tab** ✅ |
| `execution_handler/exchanges/simulated.py` | **TAB** | tab | **tab** ✅ |
| `strategy_handler/strategies/SMA_MACD_strategy.py` | **TAB** | tab | **tab** ✅ |
| `price_handler/feed/bar_feed.py` | **4-SPACE** | 4-space | **4-space** ✅ |
| `core/bar.py` | **4-SPACE** | 4-space | **4-space** ✅ |
| `price_handler/store/csv_store.py` | **4-SPACE** | 4-space | **4-space** ✅ |

**Net:** All six PERF-01 / PERF-02-portfolio target files are **4-space**. Only `order_manager.py` (W1-03), `simulated.py` (W1-14), and `SMA_MACD_strategy.py` (W1-12) are genuine **tab** files. The planner must tag each task with the *file-verified* indentation, not the directory shorthand — otherwise a portfolio-handler edit would be (incorrectly) tabbed and break the diff. **The single safe rule remains: match the file you edit; never normalize.**

## Common Pitfalls

### Pitfall 1: Treating the oracle as sufficient proof the optimization landed
**What goes wrong:** Byte-exact passes whether or not the `.copy()` is still there (same values either way), so an optimization could be silently reverted/no-op'd and the oracle stays green.
**Why it happens:** The oracle proves *correctness*, not *that the specific mechanic changed*.
**How to avoid:** Pair every behavior-preserving optimization with a deterministic behavioral assert that pins the mechanic (identity / accessor-behavior / call-presence). This IS D-01.
**Warning signs:** A plan task whose only verification is "oracle green" for a PERF-01/PERF-03 item.

### Pitfall 2: A test that mutates a getter result and asserts storage unchanged
**What goes wrong:** Dropping `.copy()` makes the getter return the live container; such a test now mutates internal state and may pass for the wrong reason or fail.
**Why it happens:** The old copy silently protected against this.
**How to avoid:** D-05 mandates the executor grep the test suite for this pattern and migrate it (caller `copy()`s locally if it needs ownership).
**Warning signs:** Tests under `tests/unit/portfolio/` that call `get_positions()/get_snapshots()` then `.append`/`.pop`/`[k]=` on the result.

### Pitfall 3: Prebuild perturbing look-ahead or the oracle
**What goes wrong:** Eager-materializing all bars could be mistaken for changing visibility.
**Why it happens:** Conflating "materialize the value object early" with "widen the decision window."
**How to avoid:** Confirmed safe — `current_bars` is exact-stamp existence (`index[pos] == time`); `window()` (the visibility slice) is untouched; this mirrors the already-blessed `_spans` precompute. Bit-identical because `Bar.from_row` runs on the same rows.
**Warning signs:** Any change to `window()`, `_resampled_frame()`, or the equality guard at `bar_feed.py:294`.

### Pitfall 4: `filterwarnings=["error"]` turning a refactor into a failure
**What goes wrong:** Any new FutureWarning/DeprecationWarning (e.g. a pandas idiom in the prebuild loop) fails the suite.
**Why it happens:** Strict warning config.
**How to avoid:** Reuse the existing `Bar.from_row` per-row construction in the prebuild loop — it is already warning-clean. Don't introduce a new pandas resample/offset path.
**Warning signs:** New `.resample`/offset-alias usage in `__init__`.

## Code Examples

Project-native idioms verified in-repo (use these styles for the new tests).

### Object-identity assert (PERF-01 copy-drop)
```python
# Style verified in tests/unit/order/test_order_manager.py (assert x is Y idiom)
def test_get_positions_returns_live_container_no_copy():
    storage = InMemoryPortfolioStateStorage()
    pos = _make_position("BTCUSD")
    storage.set_position("BTCUSD", pos)
    first = storage.get_positions()
    second = storage.get_positions()
    assert first is second  # same live dict — D-03 (would be False with .copy())
```

### Accessor-behavior assert (PERF-01 D-06)
```python
def test_snapshot_count_and_latest_match_history():
    storage = InMemoryPortfolioStateStorage()
    assert storage.snapshot_count() == 0
    assert storage.get_latest_snapshot() is None
    s1, s2 = _snap(1), _snap(2)
    storage.add_snapshot(s1); storage.add_snapshot(s2)
    assert storage.snapshot_count() == 2
    assert storage.get_latest_snapshot() is s2  # last-only, no whole-list copy
```

### Call-presence / no-call assert (PERF-03 prebuilt Bars)
```python
# monkeypatch-sentinel idiom — matches tests/unit/price/test_bar_feed.py usage of monkeypatch
def test_current_bars_serves_prebuilt_no_from_row_per_tick(monkeypatch):
    feed = BacktestBarFeed(store, base_timeframe=timedelta(days=1))  # prebuild at construction
    import itrader.core.bar as bar_mod
    def _boom(*a, **k):
        raise AssertionError("Bar.from_row called per tick — prebuild not serving")
    monkeypatch.setattr(bar_mod.Bar, "from_row", classmethod(_boom))
    bars = feed.current_bars(some_known_tick_time)  # must NOT call from_row
    assert "BTCUSD" in bars and isinstance(bars["BTCUSD"], Bar)
```
*(Naming/placement is Claude's discretion per CONTEXT; the planner picks the home — likely `tests/unit/price/test_bar_feed.py` and `tests/unit/portfolio/test_state_storage.py`.)*

### W1-07 on_fill-guard hoist assert (PERF-02 — the one mechanical item with an observable side-effect)
```python
# An existing file already targets this: tests/unit/portfolio/test_on_fill_status_guard.py.
# The hoist must keep EXECUTED vs non-EXECUTED semantics identical; a non-EXECUTED fill
# returns early without mutating positions/cash. Assert: non-EXECUTED fill is a no-op on
# portfolio state (extend the existing guard test if the hoist changes observable behavior;
# otherwise oracle + the existing guard test cover it).
```

### Byte-exact oracle (cross-cutting net — already exists, do NOT modify)
```python
# tests/integration/test_backtest_oracle.py — assert_frame_equal(..., check_exact=True)
# on trades/equity, and summary final_cash/final_equity/total_realised_pnl/trade_count.
# Phase 3 must leave this GREEN unchanged (134 trades / final_equity 46189.87730727451).
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Defensive `.copy()` on every getter | Read-only-view contract under D-19 single-writer | This phase (D-03) | Removes per-tick container copies; contract moves to ABC docstring. |
| Per-tick `Bar.from_row` (iloc + 5×`Decimal(str)`) | Prebuilt `{ticker:{time:Bar}}` dict lookup | This phase (D-07) | Structural de-pandas of the hot loop; bit-identical values. |
| `get_snapshots()` whole-list copy for a never-firing trim | `snapshot_count()` / `get_latest_snapshot()` | This phase (D-06) | Eliminates whole-list copy on the per-tick snapshot path. |
| `Decimal(str(some_Decimal))` re-wraps | Use the already-Decimal value directly | This phase (W1-08) | No-op removal; `market_value`/`unrealised_pnl`/`realised_pnl` verified `-> Decimal`. |

**Deprecated/outdated (documentation edit targets — note, do NOT treat as in-scope code work):**
- ROADMAP §Phase-3 **SC-1** still says "live-backend copies stay behind an explicit `*_snapshot()` variant" — **D-04 DECLINES** that variant. Correct the wording.
- ROADMAP §Phase-3 **SC-2** still lists "active-portfolio recompute" — **D-10 DESCOPES** W1-13. Correct the wording.
- REQUIREMENTS **PERF-02**'s `[…W1-13…]` tag is stale — **D-10**. Remove the W1-13 tag.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | "58/58 e2e green" — the e2e tree has 48 `def test_` / 46 `scenario.py` directories; the literal "58" likely counts e2e + integration or parametrized expansion. The exact denominator was not reconciled (not load-bearing). | Validation Architecture | Low — the gate is "the e2e + integration suite stays fully green," not a magic number. Planner should phrase the gate as "full e2e + integration suite green" and let the run report the count. |

**All other claims in this research are VERIFIED against the cited source line in this session.**

## Open Questions

1. **Exact denominator of "58/58 e2e"**
   - What we know: 48 e2e `test_` functions, 46 scenario dirs; integration adds the oracle tests.
   - What's unclear: which collection sums to 58.
   - Recommendation: Planner states the phase gate as "full e2e + integration suite green (no regressions vs Phase-2 baseline)" rather than pinning the literal count; the executor reads the actual count from the run.

2. **Whether any portfolio unit test currently mutates a getter result (D-05 executor task)**
   - What we know: D-05 audited *production* callers (safe). Tests were explicitly left to the executor.
   - What's unclear: whether such a test exists.
   - Recommendation: Make "grep `tests/unit/portfolio/` for mutate-then-assert-storage patterns and migrate" an explicit task line under PERF-01.

## Environment Availability

> Code/config-only changes; no new external dependency. Existing toolchain (pytest, mypy, pandas, Decimal) is already present and green per CLAUDE.md. The only operational note: when running pytest/mypy from a git worktree, prepend `PYTHONPATH="$PWD"` to avoid editable-install shadowing (per user MEMORY: worktree-venv-shadowing).

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| pytest + monkeypatch | new behavioral asserts | ✓ | ^8.4.2 | — |
| mypy --strict | mechanical-transform gate | ✓ | ^2.1.0 | — |
| pandas | feed prebuild loop | ✓ | ^2.3.3 | — |
| committed golden master | oracle byte-exact net | ✓ | `tests/golden/` (frozen) | none — must not regenerate |

## Validation Architecture

> This section seeds `VALIDATION.md` (Nyquist Dimension 8). The phase's verification law (D-01/D-02): **byte-exact oracle proves correctness; deterministic behavioral asserts prove each optimization landed; wall-clock benchmarks are REJECTED (flaky).** Both layers are required — the oracle cannot detect a silently-reverted `.copy()`; the asserts cannot prove end-to-end numbers.

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest ^8.4.2 (`filterwarnings=["error"]`, `--strict-markers`, `--strict-config`) |
| Config file | `pyproject.toml` `[tool.pytest.ini_options]` (`testpaths=["tests"]`) |
| Quick run (per task) | `poetry run pytest tests/unit/portfolio/ tests/unit/price/ -q` (or the specific new test file `-x`) |
| Full suite | `make test` (or `make test-integration` for the oracle, `make test-e2e` for scenarios) |
| Static gate | `poetry run mypy itrader` (strict; runs over `itrader`) |
| Markers auto-applied | `unit`/`integration`/`e2e` from folder via `tests/conftest.py` — do NOT hand-add |

### Phase Requirements → Test Map (each optimization → its proving signal)
| Optimization (Req) | Behavior to prove | Test type | Proving signal / command | File status |
|--------------------|-------------------|-----------|--------------------------|-------------|
| **PERF-01 copy-drop (D-03)** | Getters return the SAME live container (no `.copy()`) | unit / object-identity | `assert storage.get_positions() is storage.get_positions()` (×5 getters). `poetry run pytest tests/unit/portfolio/test_state_storage.py -x` | ❌ Wave 0 — add identity tests; extend `test_state_storage.py` |
| **PERF-01 copy-drop caller audit (D-05)** | No *test* mutates a getter result and asserts storage unchanged | unit / grep-audit | Grep `tests/unit/portfolio/` for mutate-then-assert; migrate any hit (caller `copy()`s locally) | ❌ Wave 0 — executor audit task |
| **PERF-01 snapshot accessors (D-06)** | `snapshot_count()` / `get_latest_snapshot()` replace the never-firing whole-list trim copy | unit / accessor-behavior | `snapshot_count()==N`, `get_latest_snapshot() is last`, `is None` when empty. `poetry run pytest tests/unit/portfolio/test_metrics_manager.py tests/unit/portfolio/test_state_storage.py -x` | ❌ Wave 0 — add accessor tests |
| **PERF-03 prebuilt Bars (D-07/08/09)** | `current_bars()` serves prebuilt `Bar`s with NO per-tick `Bar.from_row` | unit / call-presence (no-call) | monkeypatch sentinel onto `Bar.from_row` that raises if called during a `current_bars()` tick; assert a real `Bar` still returned. Rationale = "structural hot-loop de-pandas, bit-identical" (D-09). `poetry run pytest tests/unit/price/test_bar_feed.py -x` | ❌ Wave 0 — add no-call assert |
| **PERF-03 prebuild look-ahead safety** | Window visibility + bit-identical values unchanged | unit (existing) | Existing `test_bar_feed.py` rules 1-7 stay green; existing `tests/unit/core/test_bar.py` Bar-value tests stay green | ✅ exists — regression coverage |
| **PERF-03 MACD-guard reorder (W1-12 / D-02)** | MACD computed inside the SMA guard, firing tick byte-identical | **code-review + byte-exact oracle ONLY — NO new test** | Reviewer confirms MACD moved inside `if short_sma>=long_sma` (line 66); oracle proves identical trades. **Do not write a test against `SMA_MACD_strategy`.** | ✅ oracle covers — no new test (D-02) |
| **PERF-02 W1-07 on_fill guard hoist** | Non-EXECUTED fill returns early as a no-op; EXECUTED path unchanged; guard now precedes the correlation-id allocation | unit / behavioral | Extend/keep `tests/unit/portfolio/test_on_fill_status_guard.py` — non-EXECUTED fill leaves positions/cash untouched | ✅ file exists — confirm/extend |
| **PERF-02 W1-08 Decimal re-wraps** | `Decimal(str(Decimal))` removed; totals identical (`market_value` etc. already `Decimal`) | oracle + mypy | byte-exact oracle + `mypy --strict`; no targeted test warranted (no observable behavior beyond the number, oracle-covered) | ✅ oracle + mypy |
| **PERF-02 W1-03 open_position_count ×2** | Single call cached locally; identical value | oracle + mypy | byte-exact oracle + `mypy --strict`; oracle-covered-only | ✅ oracle + mypy |
| **PERF-02 W1-14 is_connected ×2-3** | Redundant checks removed; identical fill path | oracle + e2e | byte-exact oracle + full e2e matching/cost scenarios green | ✅ oracle + e2e |
| **PERF-02 W1-09 load-time copy** | `raw[expected_cols].copy()` removed; identical loaded frame | oracle + existing csv-store unit | byte-exact oracle + `tests/unit/price/test_csv_store.py` green | ✅ oracle + existing test |
| **Cross-cutting correctness (ALL)** | 134 trades / final_equity 46189.87730727451; trade/equity/summary identity EXACT | integration / byte-exact oracle | `make test-integration` → `test_backtest_oracle.py` green, no tolerance | ✅ exists — must stay green unchanged |

### Sampling Rate
- **Per task commit:** the new behavioral assert(s) for that optimization + `mypy itrader` (fast) → `poetry run pytest <new test file> -x` and `poetry run mypy itrader`.
- **Per wave merge:** affected unit subtrees → `make test-unit` (or `tests/unit/portfolio/ tests/unit/price/`).
- **Phase gate:** **byte-exact oracle green** (`make test-integration`) + **full e2e suite green** (`make test-e2e`) + **`mypy --strict` clean** (`make test` covers unit/integration; run `mypy itrader` explicitly). The oracle is the non-negotiable correctness net; behavioral asserts are the "it landed" net; both must pass before `/gsd:verify-work`.

### Wave 0 Gaps
- [ ] `tests/unit/portfolio/test_state_storage.py` — add object-identity asserts for the 5 getters (PERF-01/D-03) + accessor-behavior asserts for `snapshot_count`/`get_latest_snapshot` (D-06).
- [ ] `tests/unit/portfolio/test_metrics_manager.py` — assert the trim path uses count/last accessors (D-06) and the never-firing trim still does not fire.
- [ ] `tests/unit/price/test_bar_feed.py` — add the no-call `Bar.from_row` sentinel assert for `current_bars()` (PERF-03/D-07).
- [ ] `tests/unit/portfolio/test_on_fill_status_guard.py` — confirm/extend the non-EXECUTED no-op guard survives the W1-07 hoist.
- [ ] **Audit task (D-05):** grep `tests/unit/portfolio/` for any test that mutates a getter result and asserts storage unchanged; migrate it.
- [ ] No framework install needed — pytest/mypy/pandas all present.

## Security Domain

> Not applicable in the conventional sense. This is a backtest-only, behavior-preserving internal refactor with no auth, no network, no external input, no new dependency. The relevant "integrity" controls are already enforced and must be preserved:
> - **Tampering / silent-corruption guard:** the byte-exact oracle is the integrity net (any unintended state change shows as a number drift). D-19 single-writer is the safety precondition for the copy-drop.
> - **Supply-chain:** zero new packages installed → no slopcheck/registry exposure this phase.
> - **Determinism:** seeded RNG + injected clock unchanged — reproducibility (an integrity property) is preserved.

No ASVS category applies (no V2/V3/V4 surface; V5 input-validation and V6 crypto are out of domain for a backtest hot-path refactor).

## Sources

### Primary (HIGH confidence — in-repo, verified this session)
- `itrader/portfolio_handler/storage/in_memory_storage.py:45-99` — the 5 getter `.copy()` sites + `set_snapshots`.
- `itrader/portfolio_handler/base.py:14-242` — `PortfolioStateStorage` ABC docstrings (the D-03 contract rewrite home) + snapshot abstractmethods (D-06 add point).
- `itrader/portfolio_handler/metrics/metrics_manager.py:171-173,189,193` — never-firing trim + `get_snapshots()[-1]` consumers.
- `itrader/portfolio_handler/position/position_manager.py:241-245,277,287,298,303,425` — caller audit (D-05) + W1-08 re-wraps; `market_value`/`unrealised_pnl`/`realised_pnl` confirmed `-> Decimal` in `position.py:70,147,173`.
- `itrader/portfolio_handler/portfolio_handler.py:291,297-305` — W1-07 guard inside `_operation_context` (correlation-id alloc).
- `itrader/price_handler/feed/bar_feed.py:144-179 (init/_frames/_spans),281-296 (current_bars),300-339 (window — visibility, untouched)` — prebuild seam + look-ahead-safety confirmation.
- `itrader/core/bar.py:52-68` — `Bar.from_row` (the 5 `Decimal(str())`).
- `itrader/strategy_handler/strategies/SMA_MACD_strategy.py:40,59-61,66` — MACD computed unconditionally before the SMA guard (W1-12 confirmed); "byte-identical firing tick" note.
- `tests/integration/test_backtest_oracle.py` — the byte-exact oracle (`check_exact=True`, no tolerance) — the cross-cutting net.
- `tests/unit/portfolio/test_state_storage.py`, `tests/unit/price/test_bar_feed.py`, `tests/unit/portfolio/test_on_fill_status_guard.py` — existing test homes + project idioms (monkeypatch, `is`-identity).
- Indentation: `grep -P '^\t'` per file (Tab/Space Hazard table).

### Secondary
- `CLAUDE.md` (D-19 single-writer, Decimal end-to-end, tab/space convention, filterwarnings strictness) — project constraints.
- `.planning/phases/03-hot-path-performance/03-CONTEXT.md` — locked decisions D-01..D-10.

### Tertiary
- None — no web/training claims load-bearing.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — no new packages; existing toolchain verified in `pyproject.toml`/CLAUDE.md.
- Architecture / code sites: HIGH — every CONTEXT-cited line opened and confirmed against live source.
- Validation Architecture: HIGH — mapped to existing test files and project-native idioms; the one gap (the "58" denominator) is logged as A1 and is not load-bearing.
- Indentation hazard: HIGH — measured per file; corrects the CONTEXT shorthand (material finding).

**Research date:** 2026-06-11
**Valid until:** stable until the source files change (no external/fast-moving dependency); re-verify the line numbers only if Phase-2 follow-up edits land first.

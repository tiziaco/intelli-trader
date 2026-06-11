# Phase 3: Minimal Real Universe - Research

**Researched:** 2026-06-09
**Domain:** Time-parameterized universe membership (availability span model) for an event-driven backtester
**Confidence:** HIGH (entirely codebase-grounded; design precedents [CITED]/[ASSUMED], not load-bearing)

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- **D-01 — Span model.** A ticker is "active at T" iff `first_bar_date <= T <= last_bar_date` — its full listed lifespan, **including internal gap days** (a mid-life missing bar is still "a member, just gapped"). Span boundaries derive from each ticker's own loaded data extent. Chosen over exact-bar-presence (which would conflate a one-day data hole with a delisting).
- **D-02 — Derived read, NOT a gate** (Zipline `can_trade` shape). The primitive is a **pure queryable availability function** that ALSO refines the feed's warning loop. It does **NOT** filter which tickers enter the BarEvent and does **NOT** touch the hot-loop bar path. Gating is the deferred v1.3 screener's job ("screeners propose, membership disposes", D-20).
- **D-03 — Add `active_membership(T)` ALONGSIDE `derive_membership`** — do NOT replace it. `derive_membership` stays as the static "set of interest" / selection-combination seam (strategy ∪ screener union). The new availability query is a separate, composable function over loaded data spans. Future screener composes them: `selected(T) = screen(active_membership(T), ranking)`. No live-path (`live_trading_system.py`) disturbance.
- **D-04 — The feed's `generate_bar_event` loop is the single span-aware owner of absence observability.** SILENT for *expected* absence (T outside a ticker's `[first,last]` span — not-yet-listed / delisted / ended); WARN only on a *true mid-life gap* (T inside the span but no bar — a real data-quality anomaly).
- **D-05 — Strip ONLY the `logger.warning('No last close for %s …')` line from `strategies_handler.py:69-73`.** KEEP the load-bearing `if bar is None: … continue` skip (price is stamped from `event.bars[ticker].close` three lines later). Oracle-dark (BTCUSD is dense, the line never fires on the golden run). CLAR-02 opportunistic cleanup along a Phase-3-touched path.
- **D-06 — Synthetic controlled fixtures ONLY for Phase 3.** Unit tests of `active_membership(T)` plus a small engine integration test driven by hand-pinned tiny datasets with controlled listing / end / mid-life-gap dates (incl. the no-look-ahead "no fill before listing" assertion). The full real-data ETH/SOL/AAVE E2E run is DEFERRED to Phase 9 (it needs the Phase 4 harness; ROBUST-03 scopes it).

### Claude's Discretion
- Exact function name/signature (`active_membership(T) -> set[str]` vs. `is_active(ticker, T) -> bool` vs. both).
- Where span boundaries `[first, last]` are cached (precompute per-ticker at feed init from loaded frames vs. query the store each call) — must be look-ahead-safe and deterministic.
- The precise synthetic-fixture layout/format for the three proof cases.

### Deferred Ideas (OUT OF SCOPE)
- **Full end-to-end run over the real ETH/SOL/AAVE differing spans** → Phase 9 (ROBUST-03), run through the Phase 4 E2E harness.
- **Membership-as-a-gate / dynamic screener selection** (membership filters bar production / engine consideration) → v1.3 / D-screener (LEAN `UniverseSelectionModel` shape). Out of scope per D-02.
- **Auto-subscription** (a strategy ticker automatically causing its data to load) → NOT pursued. The store stays the explicit data-subscription seam.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| UNIV-01 | A real `membership` primitive derives the set of active tickers at time T from data availability (replaces the stub). Screening/ranking explicitly excluded. | New `active_membership(T)` / `is_active(ticker, T)` in `itrader/universe/membership.py`, reading per-ticker `[first_bar, last_bar]` spans from the feed's already-loaded `_frames`. Span model = D-01. Composes with (does not replace) `derive_membership` (D-03). See Architecture Patterns 1-3. |
| UNIV-02 | The engine correctly handles a ticker that lists mid-backtest and assets with differing end dates — no crash, no look-ahead, absent bars produce no fill. | The union ping grid (`backtest_trading_system.py:169-171`, WR-07) ALREADY ticks across the union window; `current_bars` (sparse dict, `bar_feed.py:261-276`) ALREADY drops absent tickers so no fill occurs. Phase 3 adds the *primitive + span-aware observability* (D-04), not new fill-suppression. "No fill before listing" is structurally true today; Phase 3 *proves it* with synthetic fixtures (D-06). See Validation Architecture proof cases. |
</phase_requirements>

## Summary

This is a tightly-scoped, fully behavior-preserving structural addition. Every decision (D-01..D-06) is locked; the only open work is **where to put a pure availability function and how to wire it into one feed loop without disturbing the hot path**. The codebase already does the load-bearing work — the union ping grid produces ticks across the full multi-ticker window (`backtest_trading_system.py:169-171`), and `current_bars`' sparse dict already prevents fills for absent bars (`bar_feed.py:261-276`). Phase 3 adds a *query* (`active_membership(T)`) and refines *one warning loop* (`generate_bar_event`, `bar_feed.py:246-250`) to be span-aware, plus deletes one legacy warning line in the strategy handler (D-05).

The span data lives in the feed already: `BacktestBarFeed._frames[(ticker, base_alias)]` holds each ticker's full base frame, whose `index[0]` / `index[-1]` ARE that ticker's `[first_bar, last_bar]` span. No new store call, no new data source. The cleanest design caches `{ticker: (first, last)}` once at feed `__init__` (the frames are already iterated there at `bar_feed.py:152-153`) and exposes `is_active(ticker, T)` + `active_membership(T)` either as feed methods or as pure functions in `universe/membership.py` that take a span-map argument. The `universe/membership.py` module docstring explicitly reserves this module as the growth home (D-20), and `derive_membership`'s existing `SupportsTickers` Protocol shows the established "pure function over an injected shape" pattern to mirror.

**Primary recommendation:** Add a pure `active_membership(spans, T) -> set[str]` + `is_active(spans, ticker, T) -> bool` pair to `itrader/universe/membership.py` (alongside, never replacing `derive_membership`), backed by a `{ticker: (first_bar, last_bar)}` span-map the feed precomputes once at `__init__`. Refine `generate_bar_event`'s warn-all loop to call `is_active` — warn only when active-but-no-bar (mid-life gap), silent otherwise. Delete the one `logger.warning` line at `strategies_handler.py:71-72`, keep the `if bar is None: continue` skip. Prove with synthetic CSV fixtures (mirror the existing `write_kline_csv` helper in `tests/unit/price/test_bar_feed.py`) covering mid-run listing, differing end dates, and a mid-life gap; lock oracle-darkness with the existing `tests/integration/test_backtest_oracle.py`.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| `active_membership(T)` / `is_active(ticker, T)` query | `universe/` (membership module) | `price_handler/feed/` (owns the span data) | D-20 reserves `membership.py` as the per-tick-membership growth home; the feed owns the loaded frames the spans derive from |
| Per-ticker `[first_bar, last_bar]` span cache | `price_handler/feed/` (`BacktestBarFeed`) | — | Spans = `_frames[(ticker, base_alias)].index[0/-1]`; the feed already holds and iterates these frames at `__init__` |
| Span-aware absence observability (silent vs warn) | `price_handler/feed/` (`generate_bar_event`) | — | D-04: the feed is the SINGLE owner; it already owns the warn-all loop and BarEvent production (D-20) |
| Legacy duplicate warning removal | `strategy_handler/` (consumer) | — | D-05: the strategy handler is a pure consumer; "missing bar = nothing to do," not its job to diagnose data quality |
| Bar production / fills for absent bars | `price_handler/feed/` (`current_bars`) | — | UNCHANGED — the sparse dict already makes "absent bar → no fill" structurally true |

## Standard Stack

**No new dependencies.** This phase is a pure-Python structural addition over the existing stack (pandas 2.3.3 for the frame indices, stdlib `datetime`). No `pip install`, no registry interaction.

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| pandas | 2.3.3 (pinned `^2.3.3`) | `DatetimeIndex[0]` / `[-1]` to read each ticker's span; `searchsorted` already used in `current_bars` | Already the primary OHLCV structure across all handlers [VERIFIED: pyproject.toml + CLAUDE.md] |
| python-stdlib `datetime` | 3.13 | `T` comparison against `[first, last]` (tz-aware `pd.Timestamp` comparisons) | The feed's tick time is already a tz-aware stamp |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Caching spans at feed `__init__` | Querying `store.index(ticker)[0/-1]` on every `is_active` call | Per-call store reads re-touch the frame each tick; precompute once is O(1) per query and matches the M5-03 "compute-once, slice-fast" pattern the feed is built on. Precompute is the recommended path. |
| `set[str]` return for `active_membership` | `list[str]` (to mirror `derive_membership`) | `derive_membership` returns `list` with "order unspecified, set-derived" (membership.py:60-63). A `set` return is more honest about unordered semantics and composes directly into `screen(active_membership(T), ranking)`. **Recommend `set[str]`** — but document the `derive_membership` `list` divergence is intentional. |

## Package Legitimacy Audit

**Not applicable — this phase installs no external packages.** All code is pure-Python additions over the already-vendored pandas/stdlib. No registry interaction, no slopcheck surface.

## Architecture Patterns

### System Architecture Diagram

```
                       wiring time (once)                         per tick T
                       ─────────────────                          ──────────

  store.read_bars(ticker) ──► BacktestBarFeed.__init__
                                 │  builds _frames[(ticker, base_alias)]
                                 │  ── NEW: also build span cache ──►
                                 │     _spans = { ticker: (idx[0], idx[-1]) }
                                 ▼
                            (span cache lives on the feed)
                                 │
                                 │                          TimeEvent(T)
                                 │                                │
                                 ▼                                ▼
   universe.active_membership(_spans, T) ◄── consulted by ── generate_bar_event(T)
   universe.is_active(_spans, ticker, T)                        │
        │  pure: first<=T<=last                                 │ for ticker in membership:
        │                                                       │   bar present?  ── yes ─► (fine)
        ▼                                                       │   no  + is_active(T)? ─► WARN (mid-life gap)  [D-04]
   set[str] / bool                                              │   no  + not active?  ─► SILENT (pre-list/post-end) [D-04]
   (future: screen(active_membership(T), ranking))             │
                                                                ▼
                                                        BarEvent(time=T, bars=current_bars(T))
                                                        bars = SPARSE dict — absent tickers dropped
                                                                │  (UNCHANGED — already "absent → no fill")
                                                                ▼
                                                        SIGNAL ► ORDER ► FILL  (only for present bars)
```

File-to-implementation mapping is in the Component Responsibilities note under each pattern, not the diagram above.

### Recommended Project Structure
```
itrader/universe/
├── membership.py        # ADD active_membership() + is_active() alongside derive_membership()
└── __init__.py          # re-export the new query (barrel pattern, mirror line 9-13)

itrader/price_handler/feed/
└── bar_feed.py          # ADD _spans cache in __init__; refine generate_bar_event warn loop

itrader/strategy_handler/
└── strategies_handler.py # DELETE the logger.warning line at :71-72 (keep the skip)

tests/unit/universe/
└── test_membership.py    # ADD active_membership/is_active unit cases (mirror existing style)

tests/unit/price/
└── test_bar_feed.py      # ADD span-aware generate_bar_event cases (mirror write_kline_csv)

tests/integration/
└── test_universe_spans.py  # NEW: tiny multi-ticker engine run (mid-run listing + differing ends)
```

### Pattern 1: Pure function over an injected shape (mirror `derive_membership` + `SupportsTickers`)
**What:** The existing `derive_membership` is a pure function taking an `Iterable[SupportsTickers]` Protocol — no class, no state, no queue. The new query follows the same shape: a pure function over a span-map.
**When to use:** The availability primitive. Keep it pure (no feed/store imports inside the function) so it is trivially unit-testable and composes into the future `screen(active_membership(T), ranking)`.
**Example:**
```python
# Source: itrader/universe/membership.py (existing pattern, lines 38-73) [VERIFIED: codebase]
# NEW additions (recommended signatures — name is Claude's Discretion per CONTEXT.md):

from datetime import datetime

# A span is a half-inclusive-both-ends [first, last] window (D-01).
Span = tuple[datetime, datetime]

def is_active(spans: dict[str, Span], ticker: str, asof: datetime) -> bool:
    """True iff `first_bar <= asof <= last_bar` for `ticker` (D-01 span model).

    Unknown ticker -> False (not a member; mirrors the sparse-universe
    'absent, never None' contract — a ticker the store never loaded is
    simply not active).
    """
    span = spans.get(ticker)
    if span is None:
        return False
    first, last = span
    return first <= asof <= last

def active_membership(spans: dict[str, Span], asof: datetime) -> set[str]:
    """The set of tickers live at `asof`, derived solely from data spans (UNIV-01).

    Pure availability — no screening/ranking. Composes with the static
    derive_membership() selection seam (D-03): future screener does
    `screen(active_membership(spans, T), ranking)`.
    """
    return {t for t in spans if is_active(spans, t, asof)}
```
**Component responsibility:** `itrader/universe/membership.py` owns these (D-20 growth home). `itrader/universe/__init__.py` re-exports them (barrel pattern).

### Pattern 2: Span cache precomputed once at feed `__init__` (mirror M5-03 compute-once)
**What:** The feed already iterates every ticker's base frame in `__init__` (`bar_feed.py:152-153`). Add a `{ticker: (first, last)}` map in the same loop — zero extra frame reads.
**When to use:** The span data source. The feed is the natural home because it already holds `_frames` and is where look-ahead safety is enforced.
**Example:**
```python
# Source: itrader/price_handler/feed/bar_feed.py __init__ (existing loop, lines 151-153) [VERIFIED: codebase]
self._frames: dict[tuple[str, str], pd.DataFrame] = {}
self._spans: dict[str, tuple[datetime, datetime]] = {}   # NEW (D-01 span cache)
for ticker in self._symbols:
    frame = store.read_bars(ticker)
    self._frames[(ticker, self._base_alias)] = frame
    # NEW: the loaded frame's own index extent IS the ticker's [first, last]
    # availability span. Look-ahead-safe by construction: the span is read from
    # the SAME committed frame the slice path reads — no future leak, deterministic.
    self._spans[ticker] = (frame.index[0].to_pydatetime(),
                           frame.index[-1].to_pydatetime())
```
**Look-ahead note (the 7-rule contract, bar_feed.py:9-38):** Reading `index[-1]` (a ticker's LAST bar date) at wiring time is NOT a look-ahead violation. Look-ahead safety governs the *decision window* a strategy sees at tick T (rules 3-4). The span is *availability metadata* (the listing/delisting calendar), not price data fed into a decision — exactly Zipline's `can_trade` / asset-lifetime shape (D-02). The feed already knows every frame's full extent at `__init__`; the span cache surfaces existing knowledge, it does not leak future *prices*.

### Pattern 3: Span-aware refinement of the warn-all loop (D-04, the single owner)
**What:** Today `generate_bar_event` warns for EVERY membership ticker absent from the produced bars (`bar_feed.py:246-250`) — it cannot distinguish "not yet listed" from "real data gap." Refine it to consult `is_active`.
**When to use:** This is the D-04 observability owner. It is the ONLY behavior change to the warning surface.
**Example:**
```python
# Source: itrader/price_handler/feed/bar_feed.py generate_bar_event (lines 244-257) [VERIFIED: codebase]
# BEFORE (warn-all):
for ticker in self.membership:
    if ticker not in bars:
        self.logger.warning('Bar feed: no bar for ticker %s at %s in the feed',
                             ticker, str(time_event.time))

# AFTER (span-aware, D-04) — warn ONLY on a true mid-life gap:
for ticker in self.membership:
    if ticker not in bars and is_active(self._spans, ticker, time_event.time):
        # Inside the listed span but no bar at T -> a real data-quality gap.
        self.logger.warning('Bar feed: mid-life gap for %s at %s (active, no bar)',
                             ticker, str(time_event.time))
    # else: expected absence (pre-listing / post-end) -> SILENT (D-04).
```
**Oracle-darkness:** On the single-ticker BTCUSD golden run, BTCUSD is dense across `[first, last]` and is always present in `bars`, so this branch never fires — byte-identical to today. The warning is a log side-effect only; it does not touch `bars`, `BarEvent`, or any result-bearing path.

### Pattern 4: Delete-the-warning-keep-the-skip (D-05)
**What:** `strategies_handler.py:69-73` fuses a load-bearing skip with a legacy warning line. Remove ONLY the warning.
**Example:**
```python
# Source: itrader/strategy_handler/strategies_handler.py (lines 69-73) [VERIFIED: codebase]
# BEFORE:
bar = event.bars.get(ticker)
if bar is None:
    self.logger.warning('No last close for %s — signal skipped (%s)',
                ticker, strategy.strategy_id)        # <-- DELETE this line only
    continue
# AFTER (keep the load-bearing skip; price is stamped from bar.close at :95):
bar = event.bars.get(ticker)
if bar is None:
    continue
```
**Indentation note (CLAUDE.md):** `strategies_handler.py` uses **tabs**. `bar_feed.py` and `universe/membership.py` use **4 spaces**. Match the file being edited — a mixed-indentation diff in a tab file breaks the file under the strict suite.

### Anti-Patterns to Avoid
- **Replacing `derive_membership`** — D-03 says ADD ALONGSIDE. The static union seam must stay (it's what the v1.3 screener extends, and the live path calls it untouched at `live_trading_system.py:199-212`).
- **Gating BarEvent production on `active_membership`** — D-02 forbids it. `active_membership` is a query, not a filter. Touching the bar path risks the oracle and pulls v1.3 work forward for zero behavioral gain.
- **Computing spans per-call from the store** — re-touches the frame each tick; violates the M5-03 compute-once design. Precompute at `__init__`.
- **Deleting the `if bar is None: continue` skip** — load-bearing (price stamped from `event.bars[ticker].close` at `:95`). D-05 keeps it.
- **Using exact-bar-presence as "active"** — D-01 chose the span model precisely so a one-day data hole isn't mistaken for a delist-then-relist.
- **Reusing `outils.time_parser` helpers for any pandas offset string** — Pitfall 2 in `bar_feed.py:77-120`; not directly in scope but avoid touching the alias path.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Multi-ticker tick grid over differing spans | A custom union-of-dates loop | The existing `reduce(pd.Index.union, ...)` ping grid (`backtest_trading_system.py:169-171`, WR-07) | Already handles heterogeneous spans; single-symbol case returns the index unchanged (oracle-dark) |
| "Absent bar → no fill" suppression | A new membership filter on bars | The existing sparse `current_bars` dict (`bar_feed.py:261-276`) | Already drops absent tickers — fills structurally cannot occur for them |
| Per-ticker first/last date | Manual `min()/max()` over rows | `frame.index[0]` / `frame.index[-1]` on the already-sorted `DatetimeIndex` | The frame is already a sorted tz-aware index; O(1) ends |
| Tiny CSV fixtures | Bespoke fixture format | The existing `write_kline_csv` helper in `tests/unit/price/test_bar_feed.py:54-72` | Already produces golden-schema klines the real `CsvPriceStore` loads unchanged |
| Membership query over an injected shape | A new class with state | The pure-function-over-Protocol pattern of `derive_membership` | Matches the module's established style; trivially unit-testable |

**Key insight:** Phase 3 is ~90% *already implemented* by existing seams (union grid + sparse dict). The genuine new code is a ~15-line pure function and a one-condition refinement of one log loop. The risk is over-building — adding a gate, a class, or a store re-query where a pure function + a precomputed map suffice.

## Runtime State Inventory

> This is a structural code addition, not a rename/migration. No stored data, services, or registrations carry a renamed string. Included for completeness because the phase modifies a shared seam.

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | None — no datastore stores membership/span state; spans are derived in-memory from CSV frames at each run. Verified: `CsvPriceStore` is read-only, in-memory (`csv_store.py:25-67`). | None |
| Live service config | None — D-03 keeps `live_trading_system.py:199-212` `derive_membership` call site untouched; no new live wiring. | None |
| OS-registered state | None — no scheduled jobs, daemons, or registrations involved. | None |
| Secrets/env vars | None — no new config keys, no env vars; spans come from loaded data. | None |
| Build artifacts | None — pure source addition; no packaging/egg-info change (`universe/` and `feed/` already shipped modules). | None |

## Common Pitfalls

### Pitfall 1: Breaking oracle-darkness by touching a result-bearing path
**What goes wrong:** Adding the membership consult somewhere that changes `bars`, ordering, or a Decimal value flips the frozen BTCUSD oracle (134 trades / `final_equity 46132.7668` per `test_backtest_oracle.py`).
**Why it happens:** Putting `active_membership` into the bar/fill path instead of the log-only warning loop.
**How to avoid:** Keep ALL Phase-3 changes on log/query surfaces. The single behavior change (`generate_bar_event` warn condition) and the deleted warning line are both pure log side-effects. Run `make test-integration` (the oracle) after each change.
**Warning signs:** Any diff touching `bars`, `BarEvent` construction, `current_bars`, or anything inside the SIGNAL/ORDER/FILL routes.

### Pitfall 2: tz-aware vs tz-naive comparison in `is_active`
**What goes wrong:** Comparing a tz-naive `datetime` `T` against tz-aware `pd.Timestamp` span bounds raises `TypeError: can't compare offset-naive and offset-aware datetimes` — which under `filterwarnings=["error"]` and strict typing is a hard failure.
**Why it happens:** The feed's bar index is tz-aware (`tz_convert(TIMEZONE)`, `csv_store.py:172`) and `TimeEvent.time` is the tz-aware stamp; but a hand-built test `datetime(2020,1,1)` is naive.
**How to avoid:** Store span bounds as the same tz-aware type the tick carries. In tests build stamps via the existing `ts()` helper (`pd.Timestamp(stamp, tz=TIMEZONE)`, `test_bar_feed.py:49-51`). If you call `.to_pydatetime()`, it preserves tzinfo from a tz-aware Timestamp — verify the comparison operand is also tz-aware.
**Warning signs:** A `TypeError` comparing datetimes only in the integration test (where real tz-aware stamps flow), not in a naive unit test.

### Pitfall 3: `filterwarnings=["error"]` turns any stray warning into a failure
**What goes wrong:** A new code path that triggers a pandas `FutureWarning` (e.g. a deprecated offset alias) or any `Warning` fails the whole suite.
**Why it happens:** `pyproject.toml:72-76` escalates warnings to errors (only `UserWarning`/`DeprecationWarning` are ignored).
**How to avoid:** The span path does no resampling and no offset-alias derivation, so it is low-risk — but the new integration fixture loads CSVs through the real `CsvPriceStore`, so use whole-day daily stamps (the golden schema) to avoid touching the alias-sensitive resample path. Mirror `write_kline_csv`.
**Warning signs:** A green local run that fails in the strict suite with a `FutureWarning`-as-error.

### Pitfall 4: `derive_membership` returns `list`, the new query returns `set` — don't conflate them
**What goes wrong:** A caller treats `active_membership(T)`'s `set` like the `list` `derive_membership` returns, or a test asserts ordering.
**Why it happens:** Two similarly-named functions in one module with different return types.
**How to avoid:** Document the intentional divergence (a `set` is honest about unordered availability and composes into `screen(...)`). `derive_membership` keeps its `list` (order unspecified) per its docstring. Tests assert on `set(...)` equality, never order — exactly as the existing `test_membership.py` does (`assert set(result) == {...}`).
**Warning signs:** An order-dependent assertion on either function's output.

### Pitfall 5: The integration test can't easily inject custom multi-ticker data
**What goes wrong:** `TradingSystem.__init__` hardcodes `CsvPriceStore(start_date=..., end_date=...)` with the default single-ticker golden path (`backtest_trading_system.py:84-87`); it accepts NO `csv_paths` argument. A naive integration test cannot point the engine at tiny synthetic multi-ticker CSVs through the public constructor.
**Why it happens:** The constructor was built for the single golden dataset; multi-ticker wiring is a Phase-3-era need.
**How to avoid:** Choose one of: (a) construct the `TradingSystem`, then replace `system.store` + rebuild `system.feed` (and re-`bind`) before `run()` — brittle, touches private wiring; (b) **recommended**: add an optional `csv_paths: dict[str,str|Path] | None = None` parameter to `TradingSystem.__init__` that passes through to `CsvPriceStore` (the store already supports it, `csv_store.py:52-56`). This is a minimal, oracle-dark constructor extension (default `None` → identical behavior) and is the clean seam the Phase-9 E2E harness will also want. Flag this for the planner as a small enabling task. (c) Build the component graph directly in the test without `TradingSystem` (most isolated, but duplicates wiring).
**Warning signs:** A test that monkeypatches `CsvPriceStore.CSV_DEFAULT_PATH` or reaches into `system.feed._frames` — a sign the injection seam is missing.

## Code Examples

### Reading a ticker's span from an already-loaded feed frame
```python
# Source: itrader/price_handler/feed/bar_feed.py:151-153 + csv_store.py:170-173 [VERIFIED: codebase]
# The base frame index is a SORTED tz-aware DatetimeIndex named 'date'.
frame = store.read_bars(ticker)          # canonical OHLCV, tz-aware index
first_bar = frame.index[0]               # listing date  (D-01 span lower bound)
last_bar  = frame.index[-1]              # last/end date  (D-01 span upper bound)
# active at T  <=>  first_bar <= T <= last_bar   (inclusive both ends, D-01)
```

### Unit test shape (mirror the existing membership + feed test style)
```python
# Source: tests/unit/universe/test_membership.py + tests/unit/price/test_bar_feed.py [VERIFIED: codebase]
import pytest
from datetime import datetime
from itrader.universe import active_membership, is_active   # NEW barrel exports

pytestmark = pytest.mark.unit   # folder-derived too, but explicit per house style

def test_active_only_within_span():
    spans = {"ETH": (datetime(2021,1,1), datetime(2026,1,8))}
    assert is_active(spans, "ETH", datetime(2021,1,1)) is True    # listing day inclusive
    assert is_active(spans, "ETH", datetime(2026,1,8)) is True    # end day inclusive
    assert is_active(spans, "ETH", datetime(2020,12,31)) is False # before listing
    assert is_active(spans, "ETH", datetime(2026,1,9)) is False   # after end

def test_mid_life_gap_still_active():
    # D-01: an internal gap day is STILL a member (span, not bar-presence).
    spans = {"X": (datetime(2021,1,1), datetime(2021,12,31))}
    assert is_active(spans, "X", datetime(2021,6,15)) is True

def test_active_membership_set_over_differing_spans():
    spans = {"BTC": (datetime(2018,1,1), datetime(2026,6,3)),
             "ETH": (datetime(2021,1,1), datetime(2026,1,8)),
             "AAVE": (datetime(2021,7,15), datetime(2026,1,8))}
    assert active_membership(spans, datetime(2020,1,1)) == {"BTC"}            # only BTC listed
    assert active_membership(spans, datetime(2021,8,1)) == {"BTC","ETH","AAVE"}
    assert active_membership(spans, datetime(2026,3,1)) == {"BTC"}            # ETH/AAVE ended

def test_unknown_ticker_is_not_active():
    assert is_active({}, "NOPE", datetime(2021,1,1)) is False
```

### Span-aware `generate_bar_event` test (mirror the existing `duo_feed` / `caplog` cases)
```python
# Source: tests/unit/price/test_bar_feed.py:303-321 (existing missing-ticker warn tests) [VERIFIED: codebase]
import logging
from itrader.events_handler.events import TimeEvent

def test_no_warn_before_listing(duo_feed_with_late_lister, caplog):
    # LATEUSD lists in June; at a January tick it is OUTSIDE its span -> SILENT (D-04).
    duo_feed_with_late_lister.bind(None, ['BTCUSD', 'LATEUSD'])
    with caplog.at_level(logging.WARNING):
        duo_feed_with_late_lister.generate_bar_event(TimeEvent(time=ts('2020-01-03')))
    assert caplog.records == []                      # expected absence: no noise

def test_warn_on_mid_life_gap(feed_with_gap, caplog):
    # Ticker active across [Jan1, Jan10] but missing the Jan5 bar -> WARN (D-04).
    feed_with_gap.bind(None, ['GAPPY'])
    with caplog.at_level(logging.WARNING):
        feed_with_gap.generate_bar_event(TimeEvent(time=ts('2020-01-05')))
    assert 'GAPPY' in caplog.text and '2020-01-05' in caplog.text
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Static `derive_membership` only (wiring-time union) | Static union + per-tick `active_membership(T)` availability query | This phase (Phase 3, v1.1) | Engine can answer "what's live at T?" from data; gating stays deferred (D-02) |
| Warn-all on any membership ticker absent from bars | Span-aware: silent for expected absence, warn only on mid-life gap | This phase (D-04) | Log noise eliminated for heterogeneous spans; real gaps stay visible |

**Framework precedent (design rationale, NOT a dependency):**
- Zipline's `can_trade` / asset-lifetime is a per-time availability *query* distinct from selection — the D-02/D-03 shape. [ASSUMED — from training knowledge of Zipline's `AssetFinder`/`can_trade`; not verified against current docs this session, and not load-bearing — the codebase's own `membership.py` docstring (D-20) is the authoritative design source.]
- LEAN's `UniverseSelectionModel` is the *selection* gate (the deferred v1.3 screener shape). [ASSUMED — same caveat.]

**Deprecated/outdated:** none introduced or removed in this phase.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | Zipline `can_trade` / LEAN `UniverseSelectionModel` are the cited framework precedents for the availability-vs-selection split | State of the Art | LOW — design rationale only; the locked decisions (D-02/D-03) and the `membership.py` docstring are the authoritative source, not the external framework |
| A2 | `set[str]` is the better return type for `active_membership` (vs `list` to mirror `derive_membership`) | Standard Stack / Pitfall 4 | LOW — Claude's Discretion per CONTEXT.md; planner/user may prefer `list` for symmetry. Either composes into the future screener |
| A3 | Adding an optional `csv_paths` param to `TradingSystem.__init__` is the cleanest multi-ticker injection seam for the integration test | Pitfall 5 / Validation | MEDIUM — alternative is direct component wiring in the test. Both are viable; the constructor extension is reusable for Phase 9 but is a (tiny, oracle-dark) production change the planner should explicitly scope |
| A4 | Reading `frame.index[-1]` (last bar date) at wiring time is not a look-ahead violation | Pattern 2 | LOW — consistent with the 7-rule contract (look-ahead governs the decision *price* window, not availability metadata); but the planner should add an explicit look-ahead assertion ("no fill on a bar before listing") to lock it |

## Open Questions

1. **Where do `active_membership` / `is_active` physically live — `universe/membership.py` (pure, span-map arg) or also as feed convenience methods?**
   - What we know: D-20 reserves `membership.py` as the growth home; the feed owns the span data. The pure function belongs in `membership.py`.
   - What's unclear: whether to ALSO add a thin feed method (`feed.active_membership(T)`) that forwards `self._spans` for ergonomic call sites.
   - Recommendation: pure functions in `membership.py` (the canonical home, unit-testable without a feed); OPTIONALLY a one-line feed forwarder `def active_membership(self, t): return active_membership(self._spans, t)` for the `generate_bar_event` call site. Let the planner decide based on whether other consumers emerge — for Phase 3, `generate_bar_event` calling `is_active(self._spans, ...)` directly is sufficient.

2. **Does the integration test extend `TradingSystem.__init__` (add `csv_paths`) or wire components directly?**
   - What we know: the constructor hardcodes the single golden store (Pitfall 5). The store already supports `csv_paths`.
   - What's unclear: whether the planner wants a (tiny, oracle-dark) production constructor change in Phase 3 or to defer the seam to Phase 4's harness.
   - Recommendation: add the optional `csv_paths=None` passthrough now — it is oracle-dark (default unchanged), unblocks the Phase-3 integration proof cleanly, and is exactly what the Phase-4 E2E harness will reuse. Flag as a small enabling task. If the planner prefers zero production-constructor change, fall back to direct component wiring in the test.

3. **Should the integration test assert the "no fill before listing" property at the FILL level or the bar level?**
   - What we know: `current_bars` already drops absent tickers, so no fill is structurally guaranteed.
   - What's unclear: the strongest assertion for the proof.
   - Recommendation: drive a tiny strategy that WOULD trade the late-lister from day one, run over the union window, and assert (a) zero positions/fills for that ticker before its listing date, AND (b) at least one bar/fill after — proving both "no fill before" and "engine survives the listing." This is the UNIV-02 acceptance lock.

## Environment Availability

> All dependencies are already vendored (pandas, pytest, the engine itself). No new external tools, services, or runtimes. Probing skipped — this is a pure in-repo code addition.

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python | all | ✓ | 3.13 (pinned `>=3.13,<3.14`) | — |
| pandas | span reads, fixtures | ✓ | 2.3.3 | — |
| pytest (+strict markers) | tests | ✓ | 8.4.2 | — |

**Missing dependencies with no fallback:** none.
**Missing dependencies with fallback:** none.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 8.4.2 (+ pytest-cov, pytest-watch) |
| Config file | `pyproject.toml` `[tool.pytest.ini_options]` (`testpaths=["tests"]`, `filterwarnings=["error",...]`, `--strict-markers`, `--strict-config`) |
| Markers | `unit`, `integration`(+`slow`) — folder-derived in `tests/conftest.py`; registered ONLY in `pyproject.toml:62-66`. No new marker needed. |
| Quick run command | `poetry run pytest tests/unit/universe/test_membership.py tests/unit/price/test_bar_feed.py -x` |
| Full suite command | `make test` (or `make test-integration` for the oracle gate) |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| UNIV-01 | `is_active` / `active_membership` return correct sets over a span map (incl. inclusive endpoints, mid-life gap still active, unknown ticker false) | unit | `poetry run pytest tests/unit/universe/test_membership.py -x` | ✅ (file exists; ADD cases — Wave 0 gap below) |
| UNIV-01 | Span cache built correctly at feed `__init__` from loaded frames | unit | `poetry run pytest tests/unit/price/test_bar_feed.py -k span -x` | ✅ (file exists; ADD cases) |
| UNIV-02 | `generate_bar_event` silent before listing / after end; warns only on mid-life gap (D-04) | unit | `poetry run pytest tests/unit/price/test_bar_feed.py -k "warn or gap or listing" -x` | ✅ (file exists; ADD cases) |
| UNIV-02 | Engine runs over a union window with a mid-run lister + differing end dates: no crash, no fill before listing, fills after | integration | `poetry run pytest tests/integration/test_universe_spans.py -x` | ❌ Wave 0 (new file) |
| D-05 | Strategy-handler warning line removed; `if bar is None: continue` skip preserved (still skips, no warning) | unit | `poetry run pytest tests/unit/strategy/ -k "sparse or skip" -x` | ⚠️ check existing strategy tests; ADD/adjust if a test asserts the warning |
| Oracle-dark | Single-ticker BTCUSD golden run stays byte-identical (134 trades / `final_equity 46132.7668`) | integration | `poetry run pytest tests/integration/test_backtest_oracle.py -x` | ✅ (exists — the invariant gate) |

### Sampling Rate
- **Per task commit:** `poetry run pytest tests/unit/universe/test_membership.py tests/unit/price/test_bar_feed.py -x` (sub-second; the three proof-case edges + span cache).
- **Per wave merge:** `make test` (full unit + integration, incl. the oracle invariant).
- **Phase gate:** Full suite green AND `test_backtest_oracle.py` byte-identical before `/gsd:verify-work`.

### Edge / Proof-Case Coverage (Nyquist — the three UNIV-02 proofs + the invariant)
| Proof case | Edge sampled | Assertion |
|------------|--------------|-----------|
| Mid-run listing | Tick exactly at listing date; tick one day before | `is_active` False before listing, True on listing day (inclusive); engine produces no fill for the lister before its first bar, ≥1 after |
| Differing end dates | Tick at a ticker's last bar; tick one day after | `is_active` True on last day (inclusive), False after; the union grid still ticks; ended ticker absent from `bars`, no fill, no crash |
| Mid-life gap | Tick inside `[first,last]` with no bar at T | `is_active` True (still a member, D-01); `generate_bar_event` WARNS (D-04); no fill (sparse dict) |
| No-look-ahead | First fill timestamp for the lister | strictly `>= listing_date` — no fill leaks onto a pre-listing tick |
| Oracle-dark invariant | The full single-ticker golden run | byte-identical trade log / equity / summary vs `tests/golden/` |

### Wave 0 Gaps
- [ ] `tests/integration/test_universe_spans.py` — new tiny multi-ticker engine run (mid-run listing + differing end dates) covering UNIV-02. Needs the `csv_paths` injection decision (Open Q2 / Pitfall 5) resolved first.
- [ ] Synthetic fixtures: 2-3 tiny daily CSVs via the existing `write_kline_csv` helper (mid-run lister starting late; a ticker ending early; a gapped ticker). No new fixture format — reuse `tests/unit/price/test_bar_feed.py:54-72`.
- [ ] Confirm no existing strategy-handler test asserts the deleted `'No last close for %s'` warning (D-05) — grep `tests/unit/strategy/` for the string; adjust if present.
- [ ] (Possible enabling task) optional `csv_paths` param on `TradingSystem.__init__` (oracle-dark passthrough to `CsvPriceStore`).

*Framework already present — no install needed. New files are additive.*

## Security Domain

**Not applicable.** This is an internal backtest-engine code addition with no external attack surface: no network, no untrusted input parsing (CSVs are committed/trusted, validated by `CsvPriceStore`), no auth/session/access-control surface, no secrets, no new serialization boundary. `security_enforcement` is not set in `.planning/config.json`; for an offline deterministic compute path the ASVS categories (V2-V6) do not apply. Input validation of the OHLCV CSV is already owned by `CsvPriceStore._load_csv` (`MalformedDataError`/`MissingPriceDataError`, `csv_store.py:154-188`) and is unchanged by this phase.

## Sources

### Primary (HIGH confidence)
- `itrader/universe/membership.py` — `derive_membership`, `SupportsTickers` Protocol, D-20 growth-target docstring [VERIFIED: codebase]
- `itrader/universe/__init__.py` — barrel re-export pattern [VERIFIED]
- `itrader/price_handler/feed/bar_feed.py` — 7-rule bar-timing contract (`:9-38`), `__init__` frame loop (`:151-153`), `generate_bar_event` warn loop (`:244-257`), sparse `current_bars` (`:261-276`), `bind` (`:210-228`) [VERIFIED]
- `itrader/price_handler/feed/base.py` + `store/base.py` — read-model / store seams [VERIFIED]
- `itrader/price_handler/store/csv_store.py` — `csv_paths` support (`:52-56`), tz-aware index (`:170-173`), `index()`/`read_bars()`/`symbols()` [VERIFIED]
- `itrader/strategy_handler/strategies_handler.py:56-99` — the D-05 warning + load-bearing skip + price stamp [VERIFIED]
- `itrader/trading_system/backtest_trading_system.py` — hardcoded store construction (`:84-87`), membership derivation + `bind` + union ping grid (`:137-175`), run loop (`:177-199`) [VERIFIED]
- `itrader/trading_system/simulation/time_generator.py` — `set_dates` / `TimeEvent` yield [VERIFIED]
- `tests/unit/universe/test_membership.py` — membership test style (`set(...)` assertions) [VERIFIED]
- `tests/unit/price/test_bar_feed.py` — `write_kline_csv` helper, `ts()`, `duo_feed`, `caplog` warn tests, `generate_bar_event` factory tests [VERIFIED]
- `tests/conftest.py` + `tests/integration/conftest.py` — folder-derived markers, `backtest_engine` factory, golden-path fixtures [VERIFIED]
- `tests/integration/test_backtest_oracle.py` / `test_backtest_smoke.py` — oracle invariant + smoke patterns [VERIFIED]
- `pyproject.toml` — markers, `filterwarnings=["error"]`, `--strict-markers` [VERIFIED]
- `.planning/REQUIREMENTS.md` (UNIV-01/02), `ROADMAP.md` §Phase 3, `03-CONTEXT.md` (D-01..D-06), `.planning/config.json` (`nyquist_validation:true`) [VERIFIED]
- `data/{BTCUSD,ETHUSD,SOLUSD,AAVEUSD}_*.csv` spans (BTC 2018-01-01→2026-06-03; ETH/SOL 2021-01-01→2026-01-08; AAVE 2021-07-15→2026-01-08) [VERIFIED via head/tail]

### Secondary (MEDIUM confidence)
- none required — the phase is fully codebase-grounded.

### Tertiary (LOW confidence)
- Zipline `can_trade` / LEAN `UniverseSelectionModel` framework precedents [ASSUMED — training knowledge; design rationale only, not load-bearing; not verified against current docs this session].

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — no new deps; all reads verified in-repo against pinned versions.
- Architecture: HIGH — every seam (union grid, sparse dict, warn loop, span source, module growth home) read directly from source; the locked decisions fully constrain the design.
- Pitfalls: HIGH — tz-comparison, `filterwarnings=["error"]`, oracle-darkness, and the `csv_paths` injection gap are all grounded in concrete file lines.
- Framework precedent: LOW — `[ASSUMED]`, explicitly non-load-bearing.

**Research date:** 2026-06-09
**Valid until:** 2026-07-09 (stable — internal refactor, no fast-moving external surface)

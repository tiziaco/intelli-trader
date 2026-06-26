# Phase 08: Hot-Path Fusion, Bar Prebuild & msgspec Migration - Pattern Map

**Mapped:** 2026-06-25
**Files analyzed:** 18 target edits across 6 requirements (all MODIFY; 0 net-new modules)
**Analogs found:** 18 / 18 (every change has an in-repo precedent)

> This is a **byte-exact** phase. Every change is *less repeated work* / faster construction / faster
> serialization — never a numeric-surface change. The analog for "how to land a perf win safely here"
> is the same every time: **audit-the-invariant + a dedicated equivalence/drift test + same-machine
> A/B, NO hot-path runtime guard** (Phase 3 D-03, Phase 4 D-06/D-07, Phase 6 D-08/D-16). The oracle
> (134 trades / `46189.87730727451`) is the hard lock.

---

## ⚠️ INDENTATION MAP — CORRECTS CONTEXT.md (verified by grep this session)

CONTEXT.md's indentation labels are **wrong for four files**. Verified against the actual bytes
(`grep -cP '^\t'` vs `grep -cP '^    [^ ]'`). The planner MUST hand executors THIS map, not CONTEXT's:

| File | CONTEXT.md says | ACTUAL (verified) | Note |
|------|-----------------|-------------------|------|
| `portfolio_handler/position/position_manager.py` | TABS | **4 SPACES** | 0 tab-lines, 46 space-lines |
| `portfolio_handler/portfolio_handler.py` | TABS | **4 SPACES** | 0 tab-lines, 96 space-lines |
| `execution_handler/matching_engine.py` | TABS | **4 SPACES** | 0 tab-lines, 46 space-lines |
| `strategy_handler/signal_record.py` | "check per file" | **4 SPACES** | its own docstring (L24) says so |
| `portfolio_handler/position/position.py` | TABS | **TABS** ✓ | confirmed |
| `portfolio_handler/transaction/transaction.py` | TABS | **TABS** ✓ | confirmed |
| `strategy_handler/base.py` | TABS | **TABS** ✓ | confirmed |
| `outils/time_parser.py` | TABS | **TABS** ✓ | confirmed |
| `core/bar.py` | 4 SPACES | **4 SPACES** ✓ | confirmed |
| `events_handler/events/*` | 4 SPACES | **4 SPACES** ✓ | confirmed |
| `price_handler/feed/bar_feed.py` | 4 SPACES | **4 SPACES** ✓ | confirmed |

**Rule (CLAUDE.md):** match the file you edit; NEVER normalize — a mixed tab/space diff breaks a tab
file under Python.

---

## File Classification

| Target file | Role | Data Flow | Closest Analog | Match Quality |
|-------------|------|-----------|----------------|---------------|
| `position_manager.py` (Req 1) | manager | transform (per-bar valuation) | `get_total_realized_pnl` accumulator (same file :314) | exact (fused-pass-in-same-file precedent) |
| `portfolio_handler.py` (Req 1) | handler | transform | `position_manager` read-owner delegation (D-04) | role-match |
| `position/position.py` (Req 2) | model (mutable aggregate) | event-driven (fill invalidates) | `Position` `_last_accrual_time` mutable marker (same file :76) | role-match |
| `feed/bar_feed.py` (Req 3) | provider/feed | batch construct | `@functools.cache _offset_alias` + `from_row` factory | role-match |
| `strategy_handler/base.py` (Req 4) | base class | transform (serialize) | `@cache _declared_hints` (same file :106) | exact (layers on top of it) |
| `outils/time_parser.py` (Req 5) | utility | transform | `_aligned` `@lru_cache(maxsize=32)` — **ALREADY DONE** | exact (precedent IS the target) |
| `core/bar.py` (Req 6) | value object | construct | `Event` → `msgspec.Struct` (spike, this phase) | exact |
| `events/base.py` + 5 subclass files (Req 6) | event | construct | spike migration map (8 files converted together) | exact |
| `matching_engine.py` DTOs (Req 6) | value object | construct | `FillDecision`/`CancelDecision` frozen dataclass shape | role-match |
| `transaction/transaction.py` (Req 6) | value object | construct | `Transaction` mutable dataclass + `__post_init__` | role-match |
| `signal_record.py` (Req 6) | value object | construct | `SignalRecord` frozen dataclass | role-match |

---

## Pattern Assignments

### Req 1 — `position_manager.py` + `portfolio_handler.py` (manager + handler, transform)

**File 1:** `itrader/portfolio_handler/position/position_manager.py` — **4 SPACES**
**Target:** `get_total_market_value` **:286-295**, `get_total_unrealized_pnl` **:297-305** (fuse into ONE
pass over `_storage.get_positions()`, D-04).

**Current (two separate full passes — the thing being fused):**
```python
def get_total_market_value(self) -> Decimal:
    """Calculate total market value of all positions."""
    total_value = Decimal('0.00')
    for position in self._storage.get_positions().values():
        # W1-08: position.market_value is already -> Decimal at source ...
        total_value += position.market_value
    return total_value

def get_total_unrealized_pnl(self) -> Decimal:
    """Calculate total unrealized P&L across all positions."""
    total_pnl = Decimal('0.00')
    for position in self._storage.get_positions().values():
        total_pnl += position.unrealised_pnl
    return total_pnl
```

**Analog — the "fused/cached field, public accessor delegates, full precision, do-NOT-revert-to-loop"
pattern already lives in this same file** (`apply_realised_increment` + `get_total_realized_pnl`,
PERF-02 D-01, **:307-328**). Copy this shape exactly — single owner of the iteration, accessors return
byte-identical Decimals, an explicit comment warning the next dev NOT to re-add a per-position loop:

```python
def apply_realised_increment(self, increment: Decimal) -> None:
    """Fold a realised-PnL increment into the running accumulator (D-01/D-02/D-05)."""
    # Full precision — NO quantize, NO mid-sum rounding (D-05): the running
    # sum stays byte-identical to the prior dual-loop re-sum ...
    self._realised_pnl_accumulator += increment

def get_total_realized_pnl(self) -> Decimal:
    # IN-03: ... do not "fix" a suspected desync by re-adding a per-position
    # loop here (that re-pays the O(positions) cost PERF-02 removed). ...
    return self._realised_pnl_accumulator
```

**Pattern to apply (D-04):** add a private fused single-pass valuation that, in ONE
`for position in self._storage.get_positions().values():`, accumulates market-value + unrealised-PnL +
the locked-margin basis (`aggregate_notional`, see below) as three full-precision Decimals; the public
`get_total_market_value` / `get_total_unrealized_pnl` delegate to that fused result. **No `quantize`,
no `Decimal('0.00')` mid-sum rounding change** — keep the `Decimal('0.00')` seed and `+=` order so the
sum stays byte-identical (mirror the PERF-02 "full precision, no mid-sum rounding" note).

**File 2:** `itrader/portfolio_handler/portfolio_handler.py` — **4 SPACES**
**Target:** the locked-margin position basis. ⚠️ CONTEXT.md cites `:638-645`/`:706` but those lines are
the **liquidation breach loop** (`_run_liquidation_pass`) and the `on_fill` Transaction build — NOT a
mark-to-market margin loop. The actual per-bar margin basis is `position.aggregate_notional / leverage`,
sourced in `portfolio.py` (`new_lock = position.aggregate_notional / leverage` **:489/:514**). D-04's
intent: `position_manager` owns the single position-iteration and exposes the locked-margin basis from
the SAME fused pass; `portfolio_handler`/`portfolio` ask for it instead of iterating positions a third
time. **The planner/researcher must re-confirm the exact current third-pass call site** against
`portfolio.py:567 update_market_value` and `:681 update_market_value_of_portfolio` — CONTEXT's line
numbers are stale.

**Cross-component note:** This is the ONLY cross-module change in the phase. It introduces NO event-queue
or cross-domain signature change — `position_manager` is already the position read-owner
(`portfolio.py:226/240` already delegate `get_total_market_value`/`get_total_unrealized_pnl` to it).

**Tests (analog: Phase 6 D-08/D-16 dedicated equivalence test):** fusion-equivalence test — the public
accessors return Decimals byte-identical to the pre-change two-pass build; oracle byte-exact; same-machine
A/B (keep-only-measured).

---

### Req 2 — `position/position.py` (mutable model, fill-invalidated cache)

**File:** `itrader/portfolio_handler/position/position.py` — **TABS**
**Target:** `avg_price` **:109-120**, `net_quantity` **:122-127** (`@property` → explicit fill-invalidated
cache, D-05). `Position` is `class Position(object)` **:21** — **mutable, EXCLUDED from msgspec (D-01)**.

**Current (recompute-on-every-access — the ~7.3% hotspot):**
```python
@property
def avg_price(self) -> Decimal:
    if self.side == PositionSide.LONG:
        return (self.avg_bought * self.buy_quantity + self.buy_commission) / self.buy_quantity
    else: # side = 'SHORT'
        return (self.avg_sold * self.sell_quantity - self.sell_commission) / self.sell_quantity

@property
def net_quantity(self) -> Decimal:
    return abs(self.buy_quantity - self.sell_quantity)
```

**Analog — an explicit, lazily-initialised mutable cache field already lives on `Position`**
(`_last_accrual_time`, CARRY-01 **:76**): a `None`-until-first-read field, mutated in place, set on `self`,
never a dataclass descriptor. Copy this idiom (explicit field, not `functools.cached_property` — D-05
rejected the descriptor route because `Position` is a hand-written class):
```python
# CARRY-01/D-04: ... None until the carry hook first reads it ...
self._last_accrual_time: Optional[datetime] = None
```

**Pattern to apply (D-05):**
- Add explicit cache fields (e.g. `self._net_quantity_cache: Optional[Decimal] = None`,
  `self._avg_price_cache: Optional[Decimal] = None`) in `__init__` (alongside `_last_accrual_time`).
- `net_quantity`/`avg_price` become: compute-and-stash if cache is `None`, else return cache. **Cached
  Decimals stay Decimal** (Decimal end-to-end; never coerce).
- **Reset to `None` at every input-mutating site.** The inputs are `buy_quantity`/`sell_quantity`/
  `buy_commission`/`sell_commission`/`avg_bought`/`avg_sold`. The ONE mutator that touches them is
  `update_position` **:250-263** (the `+= transaction.quantity` / `+= transaction.commission` /
  `avg_bought = …` lines) — set both caches to `None` there. `market_value` (`:83`) and
  `aggregate_notional` (`:95`) consume the cache but still multiply by per-bar `current_price`, so they
  stay live (cache is ONLY on the fill-derived quantities/prices, not on `current_price`).

**Tests (D-05 names this explicitly):** a fill-invalidation unit test — assert the cached `net_quantity`/
`avg_price` after a buy then after a further sell differ correctly (cache invalidated, not stale); oracle
byte-exact; same-machine A/B.

---

### Req 3 — `feed/bar_feed.py` (feed/provider, batch construct)

**File:** `itrader/price_handler/feed/bar_feed.py` — **4 SPACES**
**Target:** the prebuild loop **:255-258** (`frame.iterrows()` → `itertuples`/vectorized, Req 3).

**Current (materializes ~69k throwaway pandas Series — the surviving Series-per-row):**
```python
self._prebuilt[ticker] = {
    ts: Bar.from_row(ts, row)
    for ts, row in frame.iterrows()
}
```

**Analog 1 — the `Bar.from_row` factory + the D-14 Decimal-via-string contract** that must be preserved
byte-for-byte (`itrader/core/bar.py:52-68`):
```python
@classmethod
def from_row(cls, time, row):
    return cls(
        time=time,
        open=Decimal(str(row["open"])),   # D-14 — NEVER Decimal(float)
        high=Decimal(str(row["high"])),
        low=Decimal(str(row["low"])),
        close=Decimal(str(row["close"])),
        volume=Decimal(str(row["volume"])),
    )
```

**Analog 2 — the "memoize/vectorize a per-row hot path, body byte-unchanged" discipline** is the same
`@functools.cache _offset_alias` precedent in THIS file (`bar_feed.py:86`, Phase 6 D-01): module-level,
decision-tag comment, "the function BODY is byte-unchanged".

**Pattern to apply (Claude's-Discretion, mechanical):** replace `frame.iterrows()` with
`frame.itertuples(index=True)` (each row → a NamedTuple; access `r.open`/`r.high`/… by column attr) OR a
column-array zip (`zip(frame.index, frame["open"].to_numpy(), …)`). **Critical byte-exact pin:**
`Bar.from_row` does `Decimal(str(row["open"]))`. `itertuples` yields native Python/numpy scalars, so
`str(np.float64(x))` MUST produce the **same string** as `str(series_value)` did under `iterrows`. The
researcher MUST verify `str()` parity (numpy scalar repr can differ) — if it diverges, build the `Bar`
fields via the same access path `iterrows` exposed, or feed `Bar.from_row` a dict shaped like the Series.
There is **no existing `itertuples` usage in the repo** — this is the one net-new mechanical pattern; the
`from_row` contract is the constraint.

**Tests:** field-for-field equivalence test — the `itertuples`-built `{ts: Bar}` mapping equals the
`iterrows` build for every ticker/ts (every Decimal field byte-identical); oracle byte-exact; same-machine
A/B.

---

### Req 4 — `strategy_handler/base.py` (base class, serialize transform)

**File:** `itrader/strategy_handler/base.py` — **TABS**
**Target:** `to_dict` **:639-705** (per-instance static cache + invalidation hook, D-06).

**Current (re-introspects + re-walks every declared field per signal — the ~3.3% hotspot):**
```python
def to_dict(self) -> dict[str, Any]:
    snapshot: dict[str, Any] = {}
    for nm in _declared_hints(type(self)):          # per-class name memo (Phase 4)
        if nm in ("timeframe", "name"):
            continue
        val = getattr(self, nm, None)
        if isinstance(val, Enum):
            val = val.value
        elif isinstance(val, (SizingPolicy, SLTPPolicy)):
            val = repr(val)
        else:
            val = _json_safe(val)               # recursive container walk
        snapshot[nm] = val
    snapshot.update({ ... "is_active": self.is_active,
                      "subscribed_portfolios": [str(pid) for pid in self.subscribed_portfolios], ... })
    return snapshot
```

**Analog — the per-class name memo this cache LAYERS ON TOP OF** (`@cache _declared_hints`, Phase 4 D-05,
`base.py:106-108`). D-06's per-INSTANCE value cache sits above it:
```python
# D-05 (PERF-04): memoize get_type_hints per concrete Strategy subclass ...
@cache
def _declared_hints(cls: type["Strategy"]) -> dict[str, Any]:
    return get_type_hints(cls)
```

**Pattern to apply (D-06):**
- Cache the serialized **static** portion of the snapshot **PER INSTANCE** (stash on `self`, e.g.
  `self._to_dict_static_cache`). **NOT per-class** — per-class would leak one instance's declared values
  (`short_window=10` vs `20`) into another (a correctness bug).
- Build it **lazily on first `to_dict`** (avoids `__init__`-ordering fragility), then per call **refresh
  ONLY the two genuinely runtime-mutable fields** — `is_active` (set by `activate_strategy`/
  `deactivate_strategy`, **:856/:859**) and `subscribed_portfolios` (mutated by `subscribe_portfolio`/
  `unsubscribe_portfolio`, **:846/:853**). Everything else is set-once in `__init__` with no setter.
- **Byte-identical guarantee:** overwrite those two keys **in place** on the cached dict
  (Python `dict.update`/key-assignment preserves existing-key position), so snapshot key ordering is
  unchanged.
- **Forward-looking seam (D-06):** add a ~2-line `_invalidate_to_dict_cache(self)` that sets the cache
  field to `None`, with a comment *"any setter that mutates a declared param MUST call this."* **No such
  setter exists in Phase 8** → never called → zero backtest cost, byte-exact preserved.

**Tests (analog: Phase 4's `_declared_hints` snapshot-drift test):** snapshot-drift test — `to_dict()`
output byte-identical to the pre-change dict (same keys, same order, same values); oracle byte-exact;
same-machine A/B.

---

### Req 5 — `outils/time_parser.py` (utility, transform) — ⚠️ LARGELY ALREADY LANDED

**File:** `itrader/outils/time_parser.py` — **TABS**
**Target per CONTEXT.md:** `check_aligned` / alignment math `:167-168` (bounded `lru_cache`, Req 5).

**⚠️ STALE REFERENCE — read carefully.** There is **no `check_aligned` function** in the codebase
(`grep -rn check_aligned itrader/` → zero hits). The alignment math is `_aligned(ts, tf)` + its delegator
`check_timeframe`. **`_aligned` ALREADY carries `@functools.lru_cache(maxsize=32)`** — landed by **Phase
7 D-01 (PERF-07)**, which is the exact precedent CONTEXT.md/SPEC point at:

```python
# D-01 (PERF-07): memoize the per-bar alignment math — `_aligned` is called once
# per registered strategy per tick ... Bounded `lru_cache(maxsize=32)` is used
# (NOT bare `functools.cache`): the `ts` key space is unbounded ... The function
# BODY is byte-unchanged — only this decorator was added. lru_cache does NOT cache
# exceptions ... thread-safe (locks internally) for live mode ...
@functools.lru_cache(maxsize=32)          # time_parser.py:139
def _aligned(ts: datetime, tf: timedelta) -> bool:
    utc = ts.astimezone(pytz.utc).replace(second=0, microsecond=0)
    midnight = utc.replace(hour=0, minute=0, second=0, microsecond=0)
    seconds_since_midnight = (utc - midnight).total_seconds()
    return seconds_since_midnight % int(tf.total_seconds()) == 0
```

**Pattern guidance for the planner:** the bounded-`lru_cache` win for per-tick alignment **is already in
place**. The researcher MUST first **re-profile** to confirm whether `_aligned` still shows in the Phase 8
Scalene (`scalene-w1.json`); if it does, the residual cost is the `astimezone/replace/total_seconds` math
on the FIRST distinct `(ts, tf)` (cache miss) — SPEC's "precomputed/cached int64-ns grid (same approach
as the D-10 cursor)" would be the next lever, mirroring the `bar_feed.py` D-10 `frame.index.asi8` int64-ns
cursor. If the re-profile shows `_aligned` is already off the hot path (Phase 7 closed it), Req 5 reduces
to **the equivalence test + an A/B confirming no further work is warranted** (keep-only-measured: do not
add a second cache that lands in noise). The bounded-`lru_cache(maxsize=N)` precedent (Phase 7 D-01) is
the template either way — do NOT use bare `@functools.cache` (unbounded `ts` key).

**Tests:** boolean-equivalence test — `_aligned`/`check_timeframe` returns identical booleans across a
representative tick/timeframe set; oracle byte-exact; same-machine A/B.

---

### Req 6 — msgspec.Struct migration (8 events + Bar together; 5 DTOs standalone)

**De-risked by the spike** (`08-MSGSPEC-SPIKE-FINDINGS.md`): the migration map is proven, mypy-clean,
oracle byte-exact. The spike CODE was discarded (D-03) — re-implement cleanly. msgspec 0.21.1 is already
in `poetry.lock` (dev-only transitive via nautilus-trader); Req 6 **promotes it to a shipped `itrader/`
runtime dependency** (`pyproject.toml` runtime deps change — not yet present).

**Shared migration map (apply to every Struct conversion):**
```python
# 1. base: @dataclass(frozen=True, slots=True, kw_only=True)  →  msgspec.Struct(frozen=True, kw_only=True, gc=False)
# 2. type tag: type: EventType = field(default=EventType.X, init=False)
#              →  type: ClassVar[EventType] = EventType.X    (EventHandler._dispatch reads event.type — works unchanged)
# 3. factory:  field(default_factory=uuid_compat.uuid7)  →  msgspec.field(default_factory=uuid_compat.uuid7)
# 4. frozen __post_init__ object.__setattr__ idiom PORTS VERBATIM (frozen Struct honours it on 0.21.1/Py3.13.1)
# 5. dataclasses.replace  →  msgspec.structs.replace   (matching_engine.py:166)
# 6. gc=False applied PER-DTO, only where reference-cycle-free (researcher confirms per type)
# 7. NEVER msgspec.encode/decode — construction container ONLY → Decimal money fields stay Decimal (no coercion path)
```

#### Req 6a — `core/bar.py` `Bar` — **4 SPACES**
Current `@dataclass(frozen=True, slots=True, kw_only=True)` (`:29`). Convert to `msgspec.Struct`. The
`from_row` classmethod factory and the `Decimal(str(...))` D-14 string path are UNCHANGED. `gc=False`
safe (no cycles). This + events is the **A/B-attributed headline win** (D-02a: +3.82% W1 / +6.72% W2@50).

#### Req 6b — `events_handler/events/` — **4 SPACES** (whole `Event` chain converts TOGETHER)
`base.py::Event` (`:19-47`, incl. the `created_at` `__post_init__` `object.__setattr__` — ports verbatim,
KEEP frozen) + `market.py` (`TimeEvent`/`BarEvent`/`PortfolioUpdateEvent`/`ScreenerEvent`) + `signal.py`
(`SignalEvent`) + `order.py` (`OrderEvent`) + `fill.py` (`FillEvent`) + `error.py` (`ErrorEvent`/
`PortfolioErrorEvent`). msgspec forbids Struct/non-Struct in one inheritance chain → all 8 files convert
in one plan. The `type: EventType = field(default=EventType.X, init=False)` tag (`market.py:23/49`, etc.)
→ `type: ClassVar[EventType] = EventType.X`. `OrderEvent.trail_type: "TrailType | None"` forward-ref needs
no change (msgspec doesn't eagerly evaluate annotations without encode).

#### Req 6c — `execution_handler/matching_engine.py` DTOs — **4 SPACES** (CONTEXT.md says TABS — WRONG)
`TrailState` (`@dataclass(slots=True)`, mutable, **:61-79**), `FillDecision` (frozen, **:81-93**),
`CancelDecision` (frozen, **:96-100**) → `msgspec.Struct`. Convert each STANDALONE (no inheritance chain).
The resting-MODIFY `dataclasses.replace(order, ...)` at **:166** → `msgspec.structs.replace` (the `order`
is an `OrderEvent`, now a Struct). `TrailState` rides in for uniformity (non-frozen Struct, low-frequency);
researcher confirms it relies on no dataclass-specific behavior before converting. ~4% of `Bar` volume →
A/B lands in noise; converted under the SAME oracle gate for a uniform value-object layer, **NOT reverted
for showing no isolated A/B delta** (D-02 carve-out).

#### Req 6d — `portfolio_handler/transaction/transaction.py` `Transaction` — **TABS**
`@dataclass` mutable (`:14-15`). Convert to non-frozen `msgspec.Struct`. **Wrinkle:** it has a
`__post_init__` that re-assigns `self.price/quantity/commission/leverage = to_money(...)` (`:49-61`) — a
plain (non-frozen) Struct supports normal `self.x = ...`, so this ports directly (no `object.__setattr__`
needed). `field(kw_only=True, ...)` + `default_factory` map to `msgspec.field`. Researcher confirms no
dataclass-specific reliance.

#### Req 6e — `strategy_handler/signal_record.py` `SignalRecord` — **4 SPACES** (its docstring L24 confirms)
`@dataclass(frozen=True, slots=True, kw_only=True)` (`:38`). Convert to frozen `msgspec.Struct`.
**Honesty note (D-02):** SignalRecord's profiled 3.3% is its `to_dict` re-introspection — fixed by **Req
4**, not msgspec; converted mainly for uniformity. Standalone (no chain).

**Tests (Req 6, all conversions):** oracle byte-exact + determinism double-run identical + `mypy --strict`
clean (spike cleared all three for Event+Bar). The spike enumerated **~29 mechanical test updates** the
real migration MUST apply — see Shared Patterns below.

---

## Shared Patterns

### Audit-the-invariant + dedicated equivalence/drift test (NO hot-path runtime guard)
**Source:** Phase 3 D-03, Phase 4 D-06/D-07, Phase 6 D-08/D-16 (`06-CONTEXT.md`).
**Apply to:** EVERY committed win (Reqs 1–5) and every msgspec conversion (Req 6).
Each win ships with a dedicated test that proves the invariant the change preserves — fusion-equivalence
(Req 1), fill-invalidation (Req 2), `Bar` field-for-field (Req 3), snapshot-drift byte-identical
`to_dict` (Req 4), `_aligned` boolean equivalence (Req 5), oracle byte-exactness (Req 6) — and **NO
runtime guard is added on the hot path** (the test is the guard).

### `@functools` memoization, body byte-unchanged, decision-tag comment
**Source:** `bar_feed.py:86 _offset_alias` (Phase 6 D-01), `base.py:106 _declared_hints` (Phase 4 D-05),
`time_parser.py:139 _aligned` (Phase 7 D-01) — thrice-used.
**Apply to:** Req 4 (layers a per-instance cache on `_declared_hints`), Req 5 (the precedent IS the
bounded `lru_cache`). Pattern: module-level/instance pure memo + decorator/field + a `D-NN` decision-tag
comment stating "body byte-unchanged, cache does NOT cache exceptions."

### Explicit lazily-initialised mutable cache field (NOT `cached_property`)
**Source:** `Position._last_accrual_time` (`position.py:76`, CARRY-01) — a `None`-until-first-read field
on a hand-written class.
**Apply to:** Req 2 (`_net_quantity_cache`/`_avg_price_cache`, D-05) and Req 4's per-instance static
cache (D-06). D-05 explicitly REJECTED `functools.cached_property` (couples to descriptor internals;
awkward on a non-dataclass).

### Decimal end-to-end / D-14 string path (correctness-critical, CLAUDE.md)
**Source:** `core/money.py::to_money` → `Decimal(str(x))`; `Bar.from_row` (`bar.py:61-68`).
**Apply to:** ALL six requirements. Every change is *less work*, never a float swap. Cached Decimals stay
Decimal (Req 2/4). The `Bar` string-path is preserved byte-for-byte (Req 3). msgspec is a construction
container only — NO encode/decode → Decimal money fields stay Decimal (Req 6).

### Same-machine A/B on a verified-COOL box + keep-only-measured
**Source:** memory `v15-perf-gateb-thermal-drift`; the spike's 8-run position-balanced method
(`08-MSGSPEC-SPIKE-FINDINGS.md` Gate B); Phase 6 keep-only-measured discipline.
**Apply to:** Reqs 1–5 each get an individual A/B (a noise-only change is reverted); Req 6 is the
**measured second layer** on the cool re-frozen baseline (D-03). Never trust the frozen-baseline compare
on a throttled box. **Carve-out (D-02):** Req 6's extra DTOs (FillDecision/CancelDecision/SignalRecord/
Transaction/TrailState) are NOT reverted for landing in A/B noise — they ship for a uniform value-object
layer under the oracle gate.

### The ~29 mechanical test updates (Req 6 only — enumerated in the spike)
**Source:** `08-MSGSPEC-SPIKE-FINDINGS.md` §"Friction worth flagging" + Gate A.
**Apply to:** Req 6. All test-mechanics, zero behavioral:
- frozen tests asserting `pytest.raises(dataclasses.FrozenInstanceError)` → msgspec raises
  `AttributeError` — `tests/unit/core/test_bar.py`, `tests/unit/events/test_event_immutability.py`,
  `tests/unit/events/test_bar_event_ohlc.py`.
- `test_type_is_real_field_with_correct_member` asserts `"type" in Event.__slots__` — `type` is now a
  `ClassVar` by design; update the assertion.
- `tests/unit/order/test_order_manager.py` (×3) helpers call `dataclasses.replace(fill_event, …)` →
  `msgspec.structs.replace`.

### `pyproject.toml` runtime-dependency promotion (Req 6 only)
**Source:** spike override decision (`08-MSGSPEC-SPIKE-FINDINGS.md` TL;DR) + CONTEXT Specifics.
**Apply to:** Req 6. msgspec moves from dev-only transitive (already in `poetry.lock`) to a declared
`itrader/` runtime dependency. Off-hot-path `reporting/frames.py:75 dataclasses.asdict` targets
`PortfolioSnapshot` (NOT a migrated type) — left UNTOUCHED (correctly out of scope).

---

## No Analog Found

| File | Role | Data Flow | Reason / Mitigation |
|------|------|-----------|---------------------|
| `feed/bar_feed.py` `itertuples` build (Req 3) | feed | batch construct | No `itertuples` usage exists anywhere in the repo — this is the one net-new mechanical pattern. Mitigated by the `Bar.from_row` D-14 contract (the constraint) + the `_offset_alias` "body byte-unchanged" discipline. The `str()`-parity risk on numpy scalars is the open item for the researcher. |
| `pyproject.toml` msgspec runtime dep (Req 6) | config | — | No prior runtime-dep promotion in this milestone; standard Poetry add to `[tool.poetry.dependencies]`. |

---

## Metadata

**Analog search scope:** `itrader/portfolio_handler/`, `itrader/price_handler/feed/`,
`itrader/strategy_handler/`, `itrader/outils/`, `itrader/core/`, `itrader/events_handler/events/`,
`itrader/execution_handler/`; Phase 6/7 CONTEXT precedents; `08-MSGSPEC-SPIKE-FINDINGS.md`.
**Files scanned:** 12 source files read + 4 grep sweeps (indentation, `check_aligned`, `itertuples`,
msgspec dep).
**Pattern extraction date:** 2026-06-25

**Two load-bearing corrections to CONTEXT.md the planner MUST carry forward:**
1. **Indentation:** `position_manager.py`, `portfolio_handler.py`, `matching_engine.py`,
   `signal_record.py` are **4 SPACES**, not TABS (verified by byte count).
2. **Req 5 is largely already landed:** there is no `check_aligned`; `_aligned` already has
   `@functools.lru_cache(maxsize=32)` (Phase 7 D-01). Re-profile first; the remaining work is likely
   only the equivalence test + an A/B confirming no further cache is warranted.

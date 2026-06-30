# Cache Classification Map

**Status:** authoritative, committed (CACHE-01 / SC1 — D-01 home #1: the readable map).
**Source inventory:** promoted from `.planning/research/ARCHITECTURE.md` §Q8 (the 14-site source
table), reconciled against a **fresh re-grep of `itrader/` at HEAD** (branch
`v1.6/phase-5-cache-classification`, 2026-06-30) per **D-03** — this is NOT a verbatim copy of the
2026-06-27 Q8 table; new sites were added, removed sites demoted, and line numbers re-verified.
**Companion (D-01 home #2):** a thin one-line `# CACHE-CLASS:` anchor on each live site's definition
line — placed in plan **05-02** (see the machine-readable anchor inventory at the end of this file).
**Drift guard:** `tests/integration/test_cache_classification.py` cross-checks the live grep surface
and the `CACHE-CLASS:` anchors against this document (SC2).

---

## Boundary statement (locked scope)

> **Classify, do not rewrite or unify.**

Phase 5 is a documentation/classification phase whose rule is to **classify, do not rewrite or unify**.
Every construct below is **classified and routed** — none is rewritten or merged. Class **(a)** (hot-path data cache) and class **(c)**
(pure-function / explicitly-invalidated memoization) are **LEFT ALONE**. Class **(b)** (storage-index
lookup) is **documentation-only** — its lookups were already re-expressed by the Phase-3 SQL backends
(`WHERE` + indexes); zero code changes here. The only code edit authorised for this phase is the
**D-02** vestigial-knob removal (deferred to plan 05-03 — see below); this plan (05-01) writes no
`itrader/` source.

## DECISION — no Arrow on the per-tick (hot) path (Q7)

> **The hot-path data cache (class (a)) is NOT to be unified into one Arrow-backed / columnar object,
> and no Arrow/columnar slice may be (re)introduced on the per-tick path.**

This records the **Q7** decision from `.planning/research/ARCHITECTURE.md` §Q7. Cross-references:

- **`.planning/research/FEATURES.md` — anti-features:** "do NOT unify into one Arrow-backed object"
  (Arrow-backed unification of the hot-path cache is **REJECTED, not deferred**).
- **`.planning/research/PITFALLS.md` — Pitfall 3:** Arrow/serialize on the per-tick path reintroduces
  the columnar-slice-per-tick cost v1.5 PERF-05/06 removed, and risks `Decimal` drift off the byte-exact
  oracle. `pyarrow` stays at the once-per-run serialization boundary only.

The v1.5 stateful-indicator + shared recent-bars feed win is what Q7 protects. This phase makes **zero
hot-path edits**, so the recurring two-part DB gate (oracle byte-exact **134 / `46189.87730727451`**,
no W1/W2 regression vs the v1.5 frozen baseline **15.7 s / 152.8 MB**) is satisfied structurally.

## Source citation

The classification scheme and the original site inventory are promoted from **`§Q8`** of
`.planning/research/ARCHITECTURE.md` (the 14-site source table). Per D-03 the inventory below is a fresh
re-grep of HEAD reconciled against that **2026-06-27 §Q8** table — not a verbatim copy. The canonical
re-grep used:

```
grep -rnE "lru_cache|functools\.cache|@cache" itrader/      # applied-decorator surface (exactly 3)
grep -rnE "self\._cache\b|self\._net_quantity_cache|self\._avg_price_cache|self\._to_dict_static_cache" itrader/
```

**Class legend:** **(a)** hot-path data cache [Q7-protected, LEAVE ALONE] · **(a-infra)** wiring-time
derive · **(a-engine)** execution working state · **(b)** storage-index lookup [solved by Phase-3
SQL `WHERE`/indexes — documentation only, zero code] · **(c)** pure-function / explicitly-invalidated
memoization [correct, LEFT ALONE] · **(c-config)** venue config snapshot · **(d) live-retention
working-set cache (built in Phase 4)** · **(—)** removed / superseded (NON-live).

Table columns: **#** · **Site (`file:line`)** · **Construct / what it caches** · **Class** · **Q8 xref**
· **Invalidation / lifecycle**. Each live `file:line` is backticked so the SC2 check can extract it.

---

## (c) — pure-function / explicitly-invalidated memoization  [LEAVE ALONE]

Memoization whose inputs are pure (bounded key space) or whose staleness is handled by an **explicit
invalidation** call on the single input mutator. These are correct as written: `functools.cache` /
`lru_cache` do not cache exceptions, are thread-safe (lock internally), and the hand-rolled ones are
invalidated at the one place their inputs change. **LEFT ALONE — documentation only.**

| # | Site (`file:line`) | Construct / what it caches | Class | Q8 xref | Invalidation / lifecycle |
|---|--------------------|----------------------------|-------|---------|--------------------------|
| 1 | `price_handler/feed/bar_feed.py:91` | `@functools.cache def _offset_alias` — timeframe→pandas alias (pure) | (c) | #1 | None needed; bounded key space; `functools.cache` does not cache exceptions |
| 2 | `outils/time_parser.py:139` | `@functools.lru_cache(maxsize=32) _aligned` — epoch alignment `(ts, tf)` | (c) | #2 | Bounded `maxsize=32`; body byte-unchanged; thread-safe |
| 3 | `strategy_handler/base.py:124` | `@cache def _declared_hints(cls)` — `get_type_hints` per subclass | (c) | #3 | Constant after import; the seed's named correct-memo example |
| 4 | `strategy_handler/base.py:197` | `self._to_dict_static_cache` — static slice of `to_dict` snapshot | (c) | #4 | Explicitly invalidated via `_invalidate_to_dict_cache` (def L782; called from the mutation path) |
| 5 | `portfolio_handler/position/position.py:88` | `_net_quantity_cache` / `_avg_price_cache` (L88-89) — two fill-derived `Decimal`s | (c) | #5 | Fill-invalidated in `update_position` (L288-289); NOT `cached_property` (mutable input) |

## (a) — hot-path data cache  [Q7-PROTECTED — LEAVE ALONE]

The per-tick data caches that the v1.5 PERF-05/06 work introduced. **This IS the hot path.** Q7 forbids
Arrow/columnar unification here; the byte-exact oracle depends on these structures being untouched.

| # | Site (`file:line`) | Construct / what it caches | Class | Q8 xref | Invalidation / lifecycle |
|---|--------------------|----------------------------|-------|---------|--------------------------|
| 6 | `price_handler/feed/bar_feed.py:241` | bar-feed precompute **family** — `_frames:213`, `_spans:224`, `_prebuilt:241`, `_cursor_cut:316`, `_newest_bars:326` (resampled frames + per-ticker span index + prebuilt `Bar`s + monotonic window cursor + newest-bar) | (a) | #6 (`_spans` folded in — NEW within family, no new class) | LEAVE — the hot-path data cache; **Q7 = no Arrow here**. Anchor row is `_prebuilt` (L241); the doc carries the full field list |
| 7 | `strategy_handler/indicators/handle.py:66` | `_buffer: deque(maxlen)` + `indicators/catalog.py` `_SMAState:97` / `_EMAState:143` / `_MACDHistState:184` / `_RSIState:241` — stateful indicator recurrence state | (a) | #7 | LEAVE — hot-path indicator state; the v1.5 Model-B self-buffer win Q7 protects |

## (a-infra) — wiring-time derive  [LEAVE ALONE]

Not a runtime cache: a pure derive-once-at-wiring extension point that sizes the shared bar cache.

| # | Site (`file:line`) | Construct / what it caches | Class | Q8 xref | Invalidation / lifecycle |
|---|--------------------|----------------------------|-------|---------|--------------------------|
| 8 | `price_handler/feed/cache_registration.py:105` | `derive()` (+ `derive_required_depths:65`) — shared-bar-cache capacity, derived once at wiring | (a-infra) | #8 | LEAVE — wiring-time extension point, not a runtime cache |

## (a-engine) — execution working state  [LEAVE ALONE]

The matching engine's resting-order book and parallel trail state. In live mode this working set is what
rehydrates on restart (Q10) — it is execution truth, not a persistence cache.

| # | Site (`file:line`) | Construct / what it caches | Class | Q8 xref | Invalidation / lifecycle |
|---|--------------------|----------------------------|-------|---------|--------------------------|
| 10 | `execution_handler/matching_engine.py:106` | `_resting` (+ `_trails:110`) — resting-order book (truth) + parallel trail state | (a-engine) | #10 | LEAVE — execution working state; in live joins the working set to rehydrate (Q10), not a persistence cache |

## (b) — storage-index lookup  [ALREADY SOLVED — DOCUMENTATION ONLY, ZERO CODE]

Derived secondary indexes over the flat `{id: order}` map (v1.5 PERF-01). The Phase-3 `SqlOrderStorage`
already re-expresses these as SQL `WHERE` + indexes; the in-memory derived index is the backtest
equivalent. **No code change** — routing is documentation only.

| # | Site (`file:line`) | Construct / what it caches | Class | Q8 xref | Invalidation / lifecycle |
|---|--------------------|----------------------------|-------|---------|--------------------------|
| 9 | `order_handler/storage/in_memory_storage.py:62` | `_active_by_portfolio` / `_by_status` / `_last_indexed_status` (L62-64) — derived secondary indexes over flat `{id:order}` | (b) | #9 | ALREADY SOLVED — Phase-3 `SqlOrderStorage` re-expresses as `WHERE`+indexes; no backtest change |

## (c-config) — venue config snapshot  [LEAVE ALONE]

Plain config snapshot fields refreshed through an explicit config seam (`update_config` /
`add_supported_symbol`), not domain state.

| # | Site (`file:line`) | Construct / what it caches | Class | Q8 xref | Invalidation / lifecycle |
|---|--------------------|----------------------------|-------|---------|--------------------------|
| 11 | `execution_handler/exchanges/simulated.py:114` | `_supported_symbols` (+ `_min_order_size:123`, `_max_order_size:124`) — venue config snapshot | (c-config) | #11 | LEAVE — refreshed via `update_config` / `add_supported_symbol` seam, not domain state |

## (d) live-retention working-set cache (built in Phase 4)  [ROUTED — Phase-4 D-04]

The three `CachedSql*Storage._cache = InMemory*Storage()` live working-set caches built in **Phase 4
(D-04)**. The Q8 a/b/c scheme had no slot for these (D-03), so they carry this distinct class. They are
**not a unification** of the caches above — each is a deliberate live-only working set in front of its
SQL store, satisfying **RETAIN-01 / RETAIN-02 / RETAIN-03**: **write-through on mutate**,
**purge-on-terminalize**, **read-through on miss**, **open-only rehydrate** on restart.

| # | Site (`file:line`) | Construct / what it caches | Class | Q8 xref | Invalidation / lifecycle |
|---|--------------------|----------------------------|-------|---------|--------------------------|
| d1 | `order_handler/storage/cached_sql_storage.py:66` | `self._cache = InMemoryOrderStorage()` — live working-set order cache | (d) | not in Q8 (NEW) | Phase-4 D-04 / RETAIN-01/02/03: write-through on mutate; purge-on-terminalize evicts; read-through on miss |
| d2 | `portfolio_handler/storage/cached_sql_storage.py:83` | `self._cache = InMemoryPortfolioStateStorage(max_snapshots=…)` — live working-set portfolio-state cache | (d) | not in Q8 (NEW) | Phase-4 D-04 / RETAIN-01/02/03: rehydrated **open-only** on restart |
| d3 | `strategy_handler/storage/cached_sql_storage.py:60` | `self._cache = InMemorySignalStore()` (rehydrate reset L105) | (d) | not in Q8 (NEW) | Phase-4 D-04 / RETAIN-01/02/03: rebuilt from store on rehydrate |

---

## Removed / superseded (NON-live)

These appeared in the 2026-06-27 §Q8 table but are **not live at HEAD**. They are recorded here as
removed rows (NOT live sites) so the map stays honest and the SC2 grep-match does not carry them forward.

| # | Site (was) | Construct | Status | Note |
|---|------------|-----------|--------|------|
| 12 | `portfolio_handler/metrics/metrics_manager.py:125` | the OLD wall-clock-TTL `_metrics_cache` | **removed (v1.5 D-04)** | Already deleted in v1.5; only the explanatory comment remains. Confirms direction; no action |
| 13 | `price_handler/store/sql_store.py` `inspector.clear_cache()` | SQLAlchemy reflection cache (library) | **gone (Phase-1 FL-06)** | The Phase-1 FL-06 rebuild of `SqlHandler` removed it; `grep -nE "clear_cache|inspector"` on `sql_store.py` now returns nothing |

## D-02 vestigial-knob removal (scheduled for plan 05-03)

Site **#14** — the two dead config knobs in `PerformanceSettings`
(`config/system.py:45` `enable_caching`, L46 `cache_size_mb`) — has **zero consumers**
(`grep -rnE "enable_caching|cache_size_mb|max_cache_size_mb" itrader/ settings/ scripts/ tests/`
returns only the two definitions). **D-02 removes both lines in plan 05-03** (the only authorised code
edit of Phase 5). `rng_seed` (L49) is determinism-critical and MUST stay — remove only L45-46.

**YAML / `max_cache_size_mb` status (re-verified at HEAD):** the `cache:` YAML block the 2026-06-27
research described (with `enable_caching` / `default_ttl_seconds` / `max_cache_size_mb` / `cache_type` /
`enable_persistent_cache`) is **not present** in tracked `settings/` at HEAD —
`settings/domains/system.default.yaml` does not exist and no tracked YAML sets these keys. So the D-02
removal at 05-03 touches only the two Python fields; there is no tracked YAML line to delete.

**Migration note:** prod `settings/*.yaml` is gitignored and Pydantic `extra="ignore"` silently drops
unknown keys, so an existing prod override that still sets `enable_caching` or `max_cache_size_mb` is
**harmless and ignored — no migration required.** The remaining (untracked) `cache:` scaffolding
(`default_ttl_seconds`, `cache_type`, `enable_persistent_cache`) is dead and left in place this phase.

---

## Machine-readable live-site anchor inventory (SC2)

The canonical list of **live anchor sites** that plan **05-02** annotates with a one-line
`# CACHE-CLASS:` comment on each `file:line` below (D-01 home #2). The SC2 check
(`tests/integration/test_cache_classification.py`) treats this block as the single source of truth:
it asserts the live grep surface maps into these files and that the `CACHE-CLASS:` anchor count equals
the number of lines below. This arm is **EXPECTED RED until 05-02 places the anchors** — that is the
intended Wave-0 RED→GREEN sequence, not a failure.

```text
price_handler/feed/bar_feed.py:91            (c)  _offset_alias decorator
outils/time_parser.py:139                    (c)  _aligned lru_cache decorator
strategy_handler/base.py:124                 (c)  _declared_hints decorator
strategy_handler/base.py:197                 (c)  _to_dict_static_cache field
portfolio_handler/position/position.py:88    (c)  _net_quantity_cache / _avg_price_cache fields
price_handler/feed/bar_feed.py:241           (a)  bar-feed precompute family (anchor _prebuilt)
strategy_handler/indicators/handle.py:66     (a)  stateful indicator _buffer
price_handler/feed/cache_registration.py:105 (a-infra)  derive() shared-bar-cache capacity
order_handler/storage/in_memory_storage.py:62 (b)  derived secondary indexes
execution_handler/matching_engine.py:106     (a-engine)  _resting order book (+ _trails)
execution_handler/exchanges/simulated.py:114 (c-config)  venue config snapshot
order_handler/storage/cached_sql_storage.py:66      (d)  live working-set order cache
portfolio_handler/storage/cached_sql_storage.py:83  (d)  live working-set portfolio-state cache
strategy_handler/storage/cached_sql_storage.py:60   (d)  live working-set signal cache
```

# Phase 5: Cache Classification (#3) - Research

**Researched:** 2026-06-30
**Domain:** Static classification + documentation of every cache/memo construct across `itrader/` (no rewrite, one tiny config edit)
**Confidence:** HIGH (the inventory is grounded in a fresh HEAD grep this session; the only MEDIUM item is the (d)-label/annotation-convention recommendation, which is explicitly Claude's-Discretion for the planner to finalize)

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- **D-01 — Dual home.** The canonical inventory lives as a durable shipped doc under `docs/`
  (e.g. `docs/CACHE-CLASSIFICATION.md`) PLUS a thin one-line marker annotation at each inventoried
  site (e.g. `# CACHE-CLASS: (c) …`). Both homes exist; the syntax is Claude's discretion.
- **D-02 — Remove the two dead knobs this phase.** `PerformanceSettings.enable_caching` and
  `cache_size_mb` in `config/system.py`, plus the YAML defaults in `settings/domains/system.default.yaml`
  (including the mis-keyed `max_cache_size_mb`). Zero code consumers (grep-confirmed). **This is the ONLY
  code edit in Phase 5.** Verify post-removal: full suite green, oracle byte-exact, `filterwarnings=["error"]`
  clean, and a final `grep -rn` returns nothing.
- **D-03 — Give the 3 Phase-4 live working-set caches their own classification tag and re-verify the
  whole map against HEAD.** The Q8 a/b/c scheme has no slot for `CachedSql*Storage._cache = InMemory*Storage()`.
  Tag them a distinct class (proposed **(d) deliberate live-retention working-set cache, built in Phase 4** —
  final letter/label is planner's call) with a pointer to Phase-4 D-04 + the RETAIN requirements. The committed
  map MUST be a fresh re-grep of `itrader/` at current HEAD, reconciled against the 2026-06-27 Q8 table — not a
  verbatim copy.
- **Scope guardrail (locked):** "Classify, do not rewrite or unify." Class (a) and (c) are LEFT ALONE;
  class (b) is documentation-only. The only code change is D-02. **No Arrow** anywhere near the per-tick
  path (Q7 / Pitfall 3); record that decision, cross-reference FEATURES anti-features.
- **Two-part DB gate (recurring):** SMA_MACD oracle byte-exact **134 / `46189.87730727451`** with **no
  W1/W2 regression** vs the v1.5 frozen baseline (**15.7 s / 152.8 MB**) — trivially satisfied (no hot-path
  edit) — AND `mypy --strict` clean + `filterwarnings=["error"]` green.

### Claude's Discretion
- Exact `docs/` filename and path, and the precise code-annotation marker convention/format (and whether
  every site is annotated or only the non-obvious ones).
- The final letter/label for the new live-retention class (D-03 proposes **(d)** — finalize it).
- Map layout (flat table vs grouped-by-class); how it cites the Q8 source, the Q7 no-Arrow decision, and
  the FEATURES anti-features.
- Whether the removed knobs warrant a migration note for existing `settings/` YAML overrides (prod YAML is
  gitignored — confirm the default-YAML edit is sufficient).

### Deferred Ideas (OUT OF SCOPE)
- **Arrow-backed unification of the hot-path cache** — explicitly REJECTED, not deferred (Q7 / FEATURES
  anti-features). Record in the map as a decision; never to be attempted on the per-tick path.
- **Async batch write-through for append-heavy live writes** — carried from Phase 4; not a
  cache-classification concern. N+4 / later.
- **`single-pass-portfolio-valuation.md`** — a profile-gated perf BUILD of a cache that does not yet exist;
  not the classification of an existing cache. Stays deferred.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| CACHE-01 | Every ad-hoc cache / `lru_cache` / scattered in-memory lookup across `itrader/` inventoried + classified (a)/(b)/(c) — documented classification + routing, NOT a rewrite/unification. | The fresh-HEAD reconciled inventory table below is the spine; 14 Q8 sites + 3 new (d) sites, all classified with file:line and lifecycle notes. |
| CACHE-02 | v1.5 hot path (stateful indicators / shared recent-bars feed) left unchanged; Arrow rejected unless strictly at the serialization boundary; no W1/W2 regression (Q7). | Class (a) sites (#6/#7/#8/#10) enumerated and tagged LEAVE-ALONE; the "no Arrow on per-tick path" decision sourced to Q7 + Pitfalls 3 + FEATURES anti-features; the phase makes zero hot-path edits so the gate is structurally satisfied. |
</phase_requirements>

## Summary

This is a **documentation/classification phase**, not a feature build. ~90% of the deliverable already
exists as the ARCHITECTURE.md §Q8 14-site inventory; Phase 5 promotes it into a durable committed
`docs/` artifact, anchors it to the code with thin per-site marker annotations (D-01), reconciles it
against current HEAD (D-03), and performs the single authorized code edit (D-02 vestigial-knob removal).

I re-grepped `itrader/` at current HEAD for `lru_cache` / `functools.cache` / `@cache` / ad-hoc `_cache`
fields. **The grep surface is small and fully enumerable — no surprise consumers.** All 14 Q8 sites
reconcile against HEAD (most at stable line numbers; a few drifted by a handful of lines). Two Q8 entries
have changed materially since 2026-06-27: **#13 (`sql_store.py` `inspector.clear_cache()`) is GONE** — the
Phase-1 FL-06 rework removed it — and **the 3 Phase-4 `CachedSql*Storage._cache` working-set caches are NEW**
(the genuinely-new caches D-03 must classify as class (d)). One new structure inside the existing class-(a)
bar-feed family (`_spans`, `bar_feed.py:224`) is not separately enumerated in Q8 and should be folded into
site #6.

**The single most load-bearing correction for the planner:** the blanket CLAUDE.md statement that
`order_handler/` and `portfolio_handler/` use tabs is **WRONG for their `storage/` subpackages.** Every
`storage/*.py` file (in-memory, sql, and the new cached_sql) is **4-space**. The per-site annotation task
must match each file's actual indentation (per-site table below has an explicit indent column) — a
mixed-indent diff in a tab file breaks the file (CONVENTIONS hazard).

**Primary recommendation:** Build `docs/CACHE-CLASSIFICATION.md` from the reconciled HEAD table below
(17 live sites: 5×c, 4×a, 1×b, 1×c-config, 3×d, plus 2 negative/removed and the D-02 cleanup); annotate
each canonical definition line with `# CACHE-CLASS: (x) <label> — see docs/CACHE-CLASSIFICATION.md`; adopt
**(d) live-retention working-set cache** as the new label; do the D-02 removal; gate with the recurring
oracle/mypy/filterwarnings checks (no hot-path edit, so the gate is free).

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Cache inventory + classification | Documentation (`docs/`) | Per-site code annotation | D-01 dual home: durable readable map + drift-proof anchor |
| Hot-path data cache (bar feed, indicators) | Price-feed / strategy-indicator tier | — | Class (a); Q7-protected; LEFT ALONE |
| Storage-index lookup | Storage/persistence tier (SQL `WHERE`/index) | In-memory derived index (backtest) | Class (b); already re-expressed by Phase-3 SQL backends |
| Pure-function / invalidated memoization | Owning domain module | — | Class (c); correct, LEFT ALONE |
| Live working-set cache | Storage/persistence tier (live only) | — | Class (d); built in Phase 4, separate construct (D-03) |
| Vestigial config-knob removal | Config tier (`config/` + `settings/`) | — | D-02; the only code edit |

## Reconciled HEAD Inventory (the spine — CACHE-01)

> Fresh re-grep of `itrader/` at current HEAD (branch `v1.6/phase-5-cache-classification`, 2026-06-30),
> reconciled against the 2026-06-27 Q8 table. **Class:** (a) hot-path data cache · (b) storage-index lookup
> solved by v1.5/SQL indexes · (c) pure-function / explicitly-invalidated memoization · (c-config) config
> snapshot · (d) live-retention working-set cache (NEW) · (—) negative/removed. **Indent** = the file's
> actual indentation (match it for the annotation; never normalize).

| # | Site (file:line @ HEAD) | Construct / what it caches | Class | Q8 xref | Indent | Invalidation / lifecycle |
|---|--------------------------|----------------------------|-------|---------|--------|--------------------------|
| 1 | `price_handler/feed/bar_feed.py:91-92` | `@functools.cache def _offset_alias` — timeframe→pandas alias (pure) | **c** | #1 (was L91) | 4-space | None needed; bounded key space; `functools.cache` does not cache exceptions |
| 2 | `outils/time_parser.py:139` | `@functools.lru_cache(maxsize=32) _aligned` — epoch alignment `(ts,tf)` | **c** | #2 (was L139) | TAB | Bounded `maxsize=32`; body byte-unchanged; thread-safe |
| 3 | `strategy_handler/base.py:124-125` | `@cache def _declared_hints(cls)` — `get_type_hints` per subclass | **c** | #3 (was L124) | TAB | Constant after import; the seed's named correct-memo example |
| 4 | `strategy_handler/base.py:197` | `self._to_dict_static_cache` — static slice of `to_dict` snapshot | **c** | #4 (was L197) | TAB | Explicitly invalidated via `_invalidate_to_dict_cache` (def L782, set-None L790; called L670) |
| 5 | `portfolio_handler/position/position.py:88-89` | `_net_quantity_cache` / `_avg_price_cache` — two fill-derived Decimals | **c** | #5 (was 88-89) | TAB | Fill-invalidated in `update_position` (L288-289); NOT `cached_property` (mutable input) |
| 6 | `price_handler/feed/bar_feed.py` — `_frames:213`, `_spans:224`, `_prebuilt:241`, `_cursor:315`, `_cursor_cut:316`, `_newest_bars:326` | resampled frames + span index + prebuilt Bars + monotonic window cursor + newest-bar (v1.5 PERF-05/06) | **a** | #6 (Q8 listed 241/326/305/213; `_spans` is NEW within this family) | 4-space | LEAVE — this IS the hot-path data cache; Q7 = no Arrow here |
| 7 | `strategy_handler/indicators/handle.py:66` `_buffer: deque(maxlen)` + `indicators/catalog.py` `_SMAState:97` / `_EMAState:143` / `_MACDHistState:184` / `_RSIState:241` | stateful indicator recurrence state (v1.5 PERF-05, Model B self-buffer) | **a** | #7 (was handle.py:66) | TAB | LEAVE — hot-path indicator state; the v1.5 win Q7 protects |
| 8 | `price_handler/feed/cache_registration.py:105` `derive()` (+ `derive_required_depths:65`) | shared-bar-cache capacity (pure derive-once at wiring) | **a-infra** | #8 | 4-space | LEAVE — wiring-time extension point, not a runtime cache |
| 9 | `order_handler/storage/in_memory_storage.py:62-64` `_active_by_portfolio` / `_by_status` / `_last_indexed_status` | derived secondary indexes over flat `{id:order}` (v1.5 PERF-01) | **b** | #9 (was 62-64) | 4-space | ALREADY SOLVED — Phase-3 `SqlOrderStorage` re-expresses as `WHERE`+indexes; no backtest change |
| 10 | `execution_handler/matching_engine.py:106` `_resting` + `:110` `_trails` | resting-order book (truth) + parallel trail state | **a-engine** | #10 (was 106-110) | 4-space | LEAVE — execution working state; in live joins the working set to rehydrate (Q10), not a persistence cache |
| 11 | `execution_handler/exchanges/simulated.py:114` `_supported_symbols` / `:123` `_min_order_size` / `:124` `_max_order_size` | venue config snapshot fields | **c-config** | #11 (was 114-124) | TAB | LEAVE — refreshed via `update_config`/`add_supported_symbol` seam, not domain state |
| 12 | `portfolio_handler/metrics/metrics_manager.py:125-126` | the OLD wall-clock-TTL `_metrics_cache` | **— (removed)** | #12 | TAB | ALREADY DELETED in v1.5 (D-04); only the explanatory comment remains. Confirms direction; no action |
| 13 | `price_handler/store/sql_store.py` — `inspector.clear_cache()` | SQLAlchemy reflection cache (library) | **— (gone)** | #13 | 4-space | **DRIFT: REMOVED.** Phase-1 FL-06 rework rebuilt `SqlHandler`; grep for `clear_cache`/`inspector` now returns nothing. Q8 #13 no longer in code |
| 14 | `config/system.py:45-46` `enable_caching` / `cache_size_mb` | dead config knobs (zero consumers) | **— (vestigial)** | 4-space | **D-02 removal target** — see dedicated section |
| d1 | `order_handler/storage/cached_sql_storage.py:66` `self._cache = InMemoryOrderStorage()` | live working-set order cache (write-through + purge-on-terminalize) | **d (NEW)** | not in Q8 | 4-space | Phase-4 D-04; purge-on-terminalize evicts; read-through on miss |
| d2 | `portfolio_handler/storage/cached_sql_storage.py:83` `self._cache = InMemoryPortfolioStateStorage(max_snapshots=…)` | live working-set portfolio-state cache | **d (NEW)** | not in Q8 | 4-space | Phase-4 D-04; rehydrated open-only on restart |
| d3 | `strategy_handler/storage/cached_sql_storage.py:60` `self._cache = InMemorySignalStore()` (rehydrate reset L105) | live working-set signal cache | **d (NEW)** | not in Q8 | 4-space | Phase-4 D-04; rebuilt from store on rehydrate |

**Grep provenance** [VERIFIED: codebase grep, this session]:
- `grep -rnE "lru_cache|functools\.cache|@cache" itrader/` → exactly sites #1 (bar_feed:91), #2 (time_parser:139), #3 (base.py:124). (Plus explanatory comments.)
- `grep -rnE "cached_property" itrader/` → only a *negative-reference* comment at `position.py:84` ("NOT functools.cached_property"). **No `cached_property` is in use anywhere.**
- `grep -rnE "_cache" itrader/` → the `_to_dict_static_cache` family, `position.py` caches, the three `CachedSql*._cache` (d1–d3, ~70 usages), and the `metrics_manager.py:125` removed-cache comment. No other ad-hoc `_cache`.

## Drift Section (HEAD vs 2026-06-27 Q8)

**NEW sites (in code, not in Q8):**
- **d1 / d2 / d3** — the three `CachedSql*Storage._cache = InMemory*Storage()` live working-set caches
  (`order_handler/`, `portfolio_handler/`, `strategy_handler/` `storage/cached_sql_storage.py`). Built in
  Phase 4 (D-04). These are the "one genuinely new cache" SC2 anticipates — classify as **(d)**.
- **`_spans` (`bar_feed.py:224`)** — a per-ticker `(first, last)` span index used by the look-ahead-safe
  window (`is_active(self._spans, …)` at L469). Part of the class-(a) bar-feed precompute family; Q8 site #6
  did not enumerate it separately. **Action: fold into #6** (no new class, no edit).

**REMOVED / superseded sites (in Q8, no longer in code):**
- **Q8 #13 — `sql_store.py` `inspector.clear_cache()`** — gone after the Phase-1 FL-06 rebuild of
  `SqlHandler`. `grep -nE "clear_cache|inspector"` on `sql_store.py` returns nothing. Record in the map as
  "removed by Phase-1 FL-06" rather than carrying it forward as a live site.

**MOVED / line-drift (same site, shifted lines):**
- `_cursor` / `_cursor_cut` now at **L315/L316** (Q8 said L305).
- `_offset_alias` decorator at L91, `def` at L92 (Q8 cited L91 — still accurate).
- `_declared_hints` decorator L124, `def` L125 (Q8 cited L124 — accurate).
- All other sites (#2, #4, #5, #9, #11) are at stable line numbers vs Q8.

**Negative confirmations (Q8 negatives still negative):**
- **Q8 #12 — `_metrics_cache`** — confirmed still deleted; `metrics_manager.py:125-126` is only the
  decision comment. No action.

**No new `lru_cache`/`functools.cache`/`@cache` decorators appeared** since 2026-06-27 — the decorator
surface is unchanged (still exactly #1/#2/#3). The only growth is the three (d) ad-hoc `_cache` fields.

## D-02 Removal Targets — Grep Confirmation (zero consumers)

[VERIFIED: codebase grep, this session] `grep -rnE "enable_caching|cache_size_mb|max_cache_size_mb"`
across `itrader/`, `settings/`, `scripts/`, `tests/` returns **only the definition sites** — no reader,
no `config.performance.enable_caching` access, no test reference.

**Python fields — `itrader/config/system.py` (4-space, `PerformanceSettings`):**
```
45:    enable_caching: bool = True
46:    cache_size_mb: int = 512
```
(Surrounding context: lines 39-49; `rng_seed: int = 42` at L49 must stay — do not over-delete. Remove
only L45 and L46.)

**YAML defaults — `settings/domains/system.default.yaml`:**
```
31:  enable_caching: true          # under the `cache:` block (L30)
33:  default_ttl_seconds: 3600
34:  max_cache_size_mb: 512        # NOTE the name mismatch: field is `cache_size_mb`, YAML key is `max_cache_size_mb`
```
Confirmed name mismatch — the YAML `max_cache_size_mb` (L34) does not bind to the `cache_size_mb` field
(Pydantic `extra="ignore"` silently drops it). The whole `cache:` block (L30-36: `enable_caching`,
`default_ttl_seconds`, `max_cache_size_mb`, `cache_type`, `enable_persistent_cache`) is unconsumed config
scaffolding. **D-02 scope is the two named knobs** (`enable_caching` L32, `max_cache_size_mb` L34); the
planner should decide whether to delete just those two lines or remove the now-orphaned `cache:` block
wholesale (recommendation: remove the two named lines per the locked D-02 wording; optionally note the rest
as dead scaffolding in the map). *(Line numbers: in the current file the `cache:` header is L30, `enable_caching`
L32, `default_ttl_seconds` L33, `max_cache_size_mb` L34 — verify exact lines at edit time; they are stable
as of this session.)*

**Post-removal verification (per D-02):**
1. `grep -rn -E "enable_caching|cache_size_mb|max_cache_size_mb" itrader/ settings/ scripts/ tests/` → empty.
2. `mypy --strict` clean (removing two unread fields cannot break types).
3. Full suite green under `filterwarnings=["error"]`; oracle byte-exact 134 / `46189.87730727451`.

**Migration note (Claude's-Discretion item):** prod `settings/*.yaml` is gitignored; editing only the tracked
`*.default.yaml` is sufficient. Recommend a one-line note in the map: "an existing prod override that still
sets `enable_caching`/`max_cache_size_mb` is silently ignored (`extra='ignore'`) and harmless — no migration
required."

## Recommendations (Claude's-Discretion — planner finalizes)

### (d)-class label
**Recommend: `(d) live-retention working-set cache (built in Phase 4)`.** Matches the D-03 proposal, the
Phase-4 D-04 naming (`CachedSql…`), and the research framing ("a separate construct, not a unification of
the above"). The map entry for each (d) site should point to Phase-4 D-04 + the RETAIN-01/02/03 requirements
and note: write-through on mutate, purge-on-terminalize, read-through on miss, open-only rehydrate.

### `docs/` filename + path
**Recommend: `docs/CACHE-CLASSIFICATION.md`** (matches D-01's own example and the CONTEXT integration-points
note). Survives `.planning/` archival; discoverable from the code side; consumable by the coming FastAPI app.
Layout: **grouped-by-class** (a / b / c / c-config / d / removed), each group preceded by a one-paragraph
"what this class is and why it's left alone / routed", then a flat per-site table identical in columns to the
spine above. Open with: (1) the Q7 "no Arrow on the per-tick path" decision, cross-referenced to
`FEATURES.md` anti-features and `PITFALLS.md` Pitfall 3; (2) a citation to ARCHITECTURE.md §Q8 as the source;
(3) the "classify, do not rewrite or unify" boundary statement.

### Annotation marker convention
**Recommend a single-line tag on the canonical definition line of each site:**
```
# CACHE-CLASS: (c) pure-function memo — see docs/CACHE-CLASSIFICATION.md
```
- Use **the file's own indentation** (tab files get a tab-then-`#` comment; 4-space files get spaces) — see
  the Indent column. **Never normalize.**
- **Annotate the definition/anchor line only** (e.g. the `@cache` decorator, the `self._cache = …`
  assignment, the `self._prebuilt = …` init), **not** every usage — one drift-proof anchor per site is
  enough for the SC2 grep-matches-inventory check and avoids touching dozens of lines.
- For multi-field sites (#6 bar-feed family, #7 indicators) annotate the **representative anchor**
  (e.g. `_prebuilt` for #6, the `_buffer` def for #7) with a tag naming the family; the doc carries the full
  field list. This keeps the diff minimal and respects the "leave the hot path alone" boundary (a comment is
  inert — but minimize even comment churn on the byte-exact path).
- Consider a stable grep token (`CACHE-CLASS:`) so SC2 can be partially automated:
  `grep -rn "CACHE-CLASS:" itrader/` should enumerate exactly the annotated anchors, cross-checkable against
  the doc's site count.

## Validation Architecture

> nyquist_validation = `true` in `.planning/config.json` — section included.

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest ^8.4.2 (`testpaths=["tests"]`, `--strict-markers`, `--strict-config`, `filterwarnings=["error"]`) |
| Config file | `pyproject.toml [tool.pytest.ini_options]` |
| Quick run command | `poetry run pytest tests/integration/test_backtest_oracle.py -x` (the byte-exact oracle) |
| Full suite command | `make test` (or `poetry run pytest tests` in a worktree — see MEMORY: `.env` abort) |

### Phase Requirements → Test/Check Map
| Req ID | Behavior | Type | Automated command | Exists? |
|--------|----------|------|-------------------|---------|
| CACHE-01 | Committed map covers every cache site; grep matches the inventory exactly (SC1/SC2) | check (script/manual) | `grep -rnE "lru_cache\|functools\.cache\|@cache\|_cache" itrader/` cross-checked against `docs/CACHE-CLASSIFICATION.md` (and `grep -rn "CACHE-CLASS:" itrader/` against the annotated anchors) | ❌ Wave 0 — the doc + annotations are the deliverable; the grep-match check is manual/scripted |
| CACHE-02 | Hot path unchanged; no Arrow on per-tick path; no W1/W2 regression | gate | oracle byte-exact + W1/W2 vs frozen baseline | ✅ `tests/integration/test_backtest_oracle.py` |
| D-02 | Two knobs removed, zero consumers remain | check | `grep -rnE "enable_caching\|cache_size_mb\|max_cache_size_mb" itrader/ settings/ scripts/ tests/` → empty | ✅ greppable |
| Gate (b) | `mypy --strict` clean + `filterwarnings=["error"]` green | gate | `make test` + mypy run | ✅ existing infra |

### How SC2 "grep matches the inventory exactly" is checked
1. Run the canonical grep (`lru_cache`/`functools.cache`/`@cache`/`_cache`) over `itrader/`.
2. Confirm every match maps to a row in `docs/CACHE-CLASSIFICATION.md` (the 17 live sites: #1–#11 minus
   the two negatives, plus d1–d3) and no doc row lacks a code match.
3. Confirm `grep -rn "CACHE-CLASS:" itrader/` enumerates exactly the annotated anchors named in the doc.
4. The two negatives (#12 removed, #13 gone) appear in the doc as "removed" rows, not live sites.

### How SC3 (recurring gate) is satisfied
- The phase makes **no hot-path edit** — only a `docs/` file, inert comment annotations, and the D-02 knob
  removal. Oracle byte-exactness (134 / `46189.87730727451`) and W1/W2 (15.7 s / 152.8 MB) are protected
  structurally. Run the oracle + full suite once after the D-02 edit to confirm no warning regression under
  `filterwarnings=["error"]`.
- **Caveat (from MEMORY):** `make test` exports `ITRADER_DISABLE_LOGS=true` (breaks caplog warn-assertion
  tests like `test_warn_on_mid_life_gap`) and aborts in worktrees on a missing `.env`. Use
  `poetry run pytest tests` as the gate in a worktree; re-run `make test` in the main checkout. Prepend
  `PYTHONPATH="$PWD"` in a worktree (editable-install shadowing).

## Common Pitfalls

### Pitfall 1: Normalizing indentation in a tab file during annotation
**What goes wrong:** Adding a 4-space `# CACHE-CLASS:` comment into a tab-indented file (e.g. `time_parser.py`,
`base.py`, `position.py`, `simulated.py`, `indicators/*`) produces a mixed-indentation diff that breaks the file.
**Why it happens:** The blanket CLAUDE.md statement "`order_handler/`/`portfolio_handler/` use tabs" is
**too coarse** — their `storage/` subpackages are 4-space, but `position/`, `metrics/`, and the indicator
modules are tabs. **How to avoid:** Use the Indent column in the spine table per-site; never assume by domain.
**Warning signs:** a `git diff` showing `^I` vs spaces in the same block.

### Pitfall 2: Treating the `storage/` files as tab-indented
**What goes wrong:** Annotating `cached_sql_storage.py` / `in_memory_storage.py` with tabs (assuming the
domain is tabs) corrupts a 4-space file. **How to avoid:** All `*/storage/*.py` are 4-space (verified
this session); the (d) sites and site #9 are 4-space.

### Pitfall 3: Carrying Q8 #13 forward as a live site
**What goes wrong:** Copying the 2026-06-27 Q8 table verbatim (against D-03) lists `sql_store.py`
`inspector.clear_cache()` as a live site — it was removed by the Phase-1 FL-06 rework. **How to avoid:**
The map is a *fresh* HEAD re-grep; #13 is a "removed" row, not live.

### Pitfall 4: Over-deleting in D-02
**What goes wrong:** Deleting more than `enable_caching`/`cache_size_mb` from `PerformanceSettings`
(e.g. catching `rng_seed` at L49, which is determinism-critical). **How to avoid:** Remove exactly L45-46;
`rng_seed` (L49) stays.

### Pitfall 5: Any Arrow/columnar idea on the per-tick path
**What goes wrong:** Re-introducing the columnar-slice-per-tick cost v1.5 removed, risking Decimal drift off
the oracle. **How to avoid:** The map records the rejection (Q7 / Pitfall 3 / FEATURES anti-features);
pyarrow stays at the once-per-run serialization boundary only. The phase touches no class-(a) code.

## Environment Availability

No external dependencies. The phase writes one `docs/` markdown file, adds inert code comments, and removes
two config lines + two YAML lines. Validation uses the existing pytest/mypy infra already present.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `(d) live-retention working-set cache` is the right label | Recommendations | LOW — explicitly Claude's-Discretion; planner finalizes the letter/label |
| A2 | `docs/CACHE-CLASSIFICATION.md` is the right filename | Recommendations | LOW — Claude's-Discretion; trivially renameable |
| A3 | Annotating only the canonical anchor line (not every usage) satisfies SC2 | Recommendations | LOW — SC2 says "grep matches inventory exactly"; anchor-only keeps the diff minimal and is sufficient if the doc carries full field lists; planner may choose fuller annotation |
| A4 | Deleting just the two named YAML lines (not the whole `cache:` block) satisfies D-02 | D-02 section | LOW — D-02 names the two knobs; the rest is dead scaffolding either way |

## Open Questions

1. **Annotate every site or only the non-obvious ones?**
   - What we know: D-01 fixes that both homes exist; CONTEXT leaves "whether every site is annotated" to the
     planner.
   - What's unclear: whether the class-(c) one-liners (already heavily comment-documented in code) need a
     `CACHE-CLASS:` tag too, or only the less-obvious (a)/(b)/(d) sites.
   - Recommendation: annotate **all 17 live sites** with the anchor-only tag for a clean, fully-automatable
     SC2 grep-match; it is a handful of inert comment lines.

2. **Delete the orphaned `cache:` YAML block wholesale?**
   - What we know: the whole `cache:` block (L30-36) is unconsumed; D-02 names only two of its keys.
   - Recommendation: remove the two named lines per the locked D-02 wording; note the remaining block as dead
     scaffolding in the map (optionally clean it in a follow-up, not this phase).

## Sources

### Primary (HIGH confidence)
- Fresh `grep -rnE` over `itrader/`, `settings/`, `scripts/`, `tests/` at HEAD (branch
  `v1.6/phase-5-cache-classification`, 2026-06-30) — every file:line in the spine table verified this session.
- Per-file indentation probe (`grep -cP "^\t"` vs `^    `) — the Indent column verified this session.
- `.planning/research/ARCHITECTURE.md` §Q8 (the 14-site source inventory) + §Q7 (no-Arrow-on-hot-path).
- `.planning/research/SUMMARY.md` §"Phase 5" + §"Executive Summary".
- `.planning/phases/05-cache-classification-3/05-CONTEXT.md` (D-01/D-02/D-03, canonical_refs).
- `.planning/phases/04-retention-live-write-through-2-live-path/04-CONTEXT.md` (D-04 `CachedSql*` topology).
- `.planning/REQUIREMENTS.md` (CACHE-01/CACHE-02 text), `.planning/STATE.md` (milestone gate).

### Secondary (project)
- `CLAUDE.md` / `.planning/codebase/CONVENTIONS.md` — tab/space hazard (refined this session: `storage/`
  subpackages are 4-space, contradicting the coarse domain-level statement).

## Metadata

**Confidence breakdown:**
- Inventory (the spine): HIGH — every site re-grepped against HEAD this session.
- Drift findings: HIGH — new (d) sites, removed #13, and line-drifts directly observed.
- D-02 zero-consumers: HIGH — grep over all consumer dirs returned only definitions.
- (d)-label / docs-filename / annotation convention: MEDIUM — recommendations on Claude's-Discretion items;
  planner finalizes.

**Research date:** 2026-06-30
**Valid until:** ~2026-07-30 for the classification scheme; the inventory line numbers are valid only against
the current HEAD — re-run the canonical grep at plan/execute time if the branch advances.

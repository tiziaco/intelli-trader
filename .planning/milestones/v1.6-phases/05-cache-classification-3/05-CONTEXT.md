# Phase 5: Cache Classification (#3) - Context

**Gathered:** 2026-06-30
**Status:** Ready for planning

<domain>
## Phase Boundary

Produce the **authoritative, committed cache-classification map** for `itrader/`: every ad-hoc cache /
`lru_cache` / `functools.cache` / scattered in-memory `_cache` lookup is inventoried and tagged
**(a)** hot-path data cache, **(b)** storage-index lookup already solved by the v1.5 secondary indexes,
or **(c)** legitimate pure-function / explicitly-invalidated memoization. The deliverable is a
**documented classification + routing decision, NOT a rewrite or a unification.**

The heavy analysis already exists: research `ARCHITECTURE.md` Q8 carries a **14-site inventory, fully
classified**. This phase **promotes that into a durable committed artifact, reconciles it against current
HEAD** (the 2026-06-27 inventory predates the Phase-3/4 `CachedSql*Storage` working-set caches), records
the **"do NOT unify into one Arrow-backed object"** decision (Q7), and performs the single small code
edit the inventory authorizes (the two vestigial config knobs, #14).

**Requirements (from REQUIREMENTS.md):** CACHE-01, CACHE-02 (+ the recurring two-part DB gate).

**In scope:**
- The authoritative classification map (in-repo `docs/` markdown + light per-site code annotations — D-01).
- Fresh re-grep of `itrader/` against HEAD; map matches current code **exactly** (SC2); the 3 new
  Phase-4 live working-set caches get their own classification (D-03).
- Removal of the two vestigial `PerformanceSettings` config knobs (D-02).
- Recording the Q7 "no Arrow on the hot path" decision, cross-referenced to FEATURES anti-features.

**Out of scope (LEFT ALONE — the whole point of "classify, do not rewrite"):**
- Class **(a)** hot-path caches (bar-feed prebuilt/cursor/frames, stateful indicators) — Q7 protects them;
  no Arrow, no consolidation, no edit (CACHE-02).
- Class **(c)** memoization (`@cache`/`@lru_cache`/derived-value caches) — correct, leave untouched.
- Class **(b)** order-storage indexes — already re-expressed as SQL `WHERE`/indexes by the Phase-3
  backends; **documentation only, zero code**.
- Any cache-consolidation / unification code (there is essentially none to write — Q8 verdict).

</domain>

<decisions>
## Implementation Decisions

### Artifact form & location (CACHE-01 / SC1)
- **D-01:** **Dual home — an in-repo `docs/` markdown map PLUS a small code-level annotation at each
  site.** The canonical inventory (the full classified table, the Q7 no-Arrow record, and the routing
  decisions) lives as a durable shipped doc under `docs/` (e.g. `docs/CACHE-CLASSIFICATION.md`) so it
  survives `.planning/` archival, is discoverable from the code side, and serves the coming FastAPI app.
  Each inventoried site additionally carries a **thin marker annotation** (a one-line comment tag, e.g.
  `# CACHE-CLASS: (c) …`) so the map cannot silently drift from the code and the SC2 grep-matches-inventory
  check is anchored at both ends. Rationale: a planning-only doc gets archived and goes stale; pure
  code annotations are unreadable as one inventory — the owner wants both the readable map and the
  drift-proof anchor.

### Vestigial config-knob cleanup (Q8 #14)
- **D-02:** **Remove the two dead knobs this phase** — `PerformanceSettings.enable_caching` and
  `cache_size_mb` (`config/system.py:45-46`), which have **zero code consumers** (grep-confirmed). This is
  the **only code edit in Phase 5.** Blast radius is small and concrete:
  - `itrader/config/system.py:45-46` — the two Pydantic fields.
  - `settings/domains/system.default.yaml:32,34` — the YAML defaults. **Note the name mismatch:** the YAML
    key is `max_cache_size_mb` (line 34) but the field is `cache_size_mb` — so the YAML line may not even
    bind today; clean **both** YAML lines when removing the fields.
  - Verify post-removal: no remaining reference anywhere (`grep -rn enable_caching|cache_size_mb|max_cache_size_mb`
    returns nothing), full suite green, oracle byte-exact, `filterwarnings=["error"]` clean.

### New-cache classification & map freshness (CACHE-02 / SC2)
- **D-03:** **Give the 3 Phase-4 live working-set caches their own classification tag and re-verify the
  whole map against HEAD.** The Q8 a/b/c scheme has no clean slot for the `CachedSql*Storage._cache =
  InMemory*Storage()` caches (`order_handler/`, `portfolio_handler/`, `strategy_handler/`
  `storage/cached_sql_storage.py`) — research itself called the live working-set cache *"a separate
  construct, not a unification of the above."* Tag them as a distinct class (proposed **(d) deliberate
  live-retention working-set cache, built in Phase 4** — final letter/label is planner's call) with a
  pointer to Phase-4 D-04 and the RETAIN requirements. The committed map must be a **fresh re-grep of
  `itrader/` at current HEAD**, reconciled against the 2026-06-27 Q8 table — **not a verbatim copy** —
  so SC2's "grep matches the inventory exactly" holds against the code as it is now.

### Scope guardrails (locked — restated so the planner cannot drift)
- **"Classify, do not rewrite or unify"** is the hard boundary. Class (a) and (c) are LEFT ALONE; class
  (b) is documentation-only (already solved by v1.5 indexes #9 → Phase-3 SQL `WHERE`/indexes). The **only**
  code change is the D-02 knob removal. **No Arrow** anywhere near the per-tick path (Q7 / Pitfall 3);
  record that decision, cross-reference FEATURES anti-features.
- **Two-part DB gate (recurring):** SMA_MACD oracle byte-exact **134 / `46189.87730727451`** with **no
  W1/W2 regression** vs the v1.5 frozen baseline (15.7 s / 152.8 MB) — trivially satisfied because this
  phase makes **no hot-path edit** — AND `mypy --strict` clean + `filterwarnings=["error"]` green.

### Claude's Discretion (planner/researcher to settle)
- Exact `docs/` filename and path, and the precise code-annotation marker convention/format (and whether
  every site is annotated or only the non-obvious ones). D-01 fixes *both homes exist*, not the syntax.
- The final letter/label for the new live-retention class (D-03 proposes **(d)** — finalize it).
- Map layout: flat table vs grouped-by-class; how it cites the Q8 source, the Q7 no-Arrow decision, and
  the FEATURES anti-features.
- Whether the removed knobs warrant any migration note for existing `settings/` YAML overrides (prod YAML
  is gitignored — confirm the default-YAML edit is sufficient).

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Requirements & scope (read FIRST)
- `.planning/REQUIREMENTS.md` — **CACHE-01** (inventory + a/b/c classification, "documented classification
  + routing, not a rewrite or unification") and **CACHE-02** (v1.5 hot path unchanged; Arrow only at the
  serialization boundary; research Q7).
- `.planning/ROADMAP.md` → **"Phase 5: Cache Classification (#3)"** — the three Success Criteria (SC1
  committed map; SC2 grep-matches-inventory + the one genuinely-new working-set cache; SC3 recurring
  oracle/mypy/filterwarnings gate).
- `.planning/STATE.md` → "Milestone Gate (v1.6 — DB-gated)" — the two-part gate restated.

### THE authoritative inventory source (this IS most of the deliverable — read in full)
- `.planning/research/ARCHITECTURE.md` **§Q8** (the 14-site classification table + "the deliverable is the
  classification, not a rewrite" verdict) and **§Q7** ("LEAVE THE v1.5 HOT PATH ALONE" — no Arrow on the
  per-tick path; what the v1.5 hot-path cache actually is, grounded in code).
- `.planning/research/SUMMARY.md` **§"Phase 5: Cache Classification (#3)"** (deliverables list: map; class
  (a)/(c) left alone, class (b) routes to SQL indexes; "do NOT unify into Arrow" record; optional knob
  removal; one new live working-set cache) + the §"Executive Summary" anti-Arrow framing.
- `.planning/research/FEATURES.md` — the anti-features list ("do NOT unify into one Arrow-backed object")
  and the "Should have: vestigial config knobs removed" item (D-02's source).
- `.planning/research/PITFALLS.md` — **Pitfall 3** (Arrow/serialize on the per-tick path — Phase 5
  structurally confirms it is closed).

### Phase 4 (the new caches D-03 must classify)
- `.planning/phases/04-retention-live-write-through-2-live-path/04-CONTEXT.md` — **D-04** (the
  `CachedSqlOrderStorage` / `CachedSqlPortfolioStateStorage` / `CachedSqlSignalStorage` topology; the live
  working-set cache that is the "one genuinely new cache").

### Conventions
- `.planning/codebase/CONVENTIONS.md` — the tabs/spaces indentation hazard (load-bearing for the per-site
  code annotations across both tab and 4-space modules).

### Code to read (the actual cache sites — verify against HEAD per D-03)
- `itrader/price_handler/feed/bar_feed.py` — `@functools.cache _offset_alias` (L91, class **c**);
  `_prebuilt`/`_newest_bars`/`_cursor`/`_cursor_cut`/`_frames` (class **a**, Q7-protected).
- `itrader/outils/time_parser.py:139` — `@lru_cache(maxsize=32) _aligned` (class **c**).
- `itrader/strategy_handler/base.py` — `@cache _declared_hints` (L124, class **c**);
  `_to_dict_static_cache` (L197, class **c**, invalidated via `_invalidate_to_dict_cache`).
- `itrader/portfolio_handler/position/position.py:88-89` — `_net_quantity_cache` / `_avg_price_cache`
  (class **c**, fill-invalidated L288-289).
- `itrader/strategy_handler/indicators/catalog.py` + `handle.py` — stateful indicator recurrence state
  (class **a**); `itrader/price_handler/feed/cache_registration.py` `derive()` (class **a**-infra).
- `itrader/order_handler/storage/in_memory_storage.py:62-64` — `_active_by_portfolio` / `_by_status` /
  `_last_indexed_status` derived indexes (class **b**, already solved by SQL).
- `itrader/execution_handler/matching_engine.py` `_resting`/`_trails`; `exchanges/simulated.py` config
  snapshot fields — class (a)-engine / (c)-config per Q8.
- `itrader/{order_handler,portfolio_handler,strategy_handler}/storage/cached_sql_storage.py` — the
  `self._cache = InMemory*Storage()` live working-set caches (the **new class (d)** sites, D-03).
- `itrader/config/system.py:34-46` (`PerformanceSettings`) + `settings/domains/system.default.yaml:32,34`
  — the D-02 removal targets.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- **`research/ARCHITECTURE.md` Q8 table** is ~90% of the deliverable: 14 sites already classified with
  routing recommendations. Phase 5 promotes + reconciles it, it does not re-derive it from scratch.
- **The grep surface is small and enumerable** (confirmed this session): `lru_cache`/`functools.cache`/
  `@cache`/ad-hoc `_cache` fields across `itrader/` map to the Q8 sites plus the 3 new Phase-4
  `CachedSql*` caches — no surprise consumers.

### Established Patterns
- **"Classify, do not rewrite"** (this phase's identity) — mirrors the v1.5 keep-only-measured discipline:
  the map is the product; code stays put except the one authorized vestigial-knob deletion.
- **Backtest hot path is sacred** (CACHE-02 / Q7): the v1.5 stateful-indicator + shared-bar-feed design
  is SOTA for single-bar incremental updates; Arrow loses here and risks Decimal drift off the oracle.

### Integration Points
- **New file:** `docs/CACHE-CLASSIFICATION.md` (or similar — D-01, planner names it).
- **Edited (the only code edits):** `itrader/config/system.py` (remove 2 fields) +
  `settings/domains/system.default.yaml` (remove 2 YAML lines, incl. the mis-keyed `max_cache_size_mb`).
- **Per-site annotations** touch handler modules (**tabs**: `order_handler/`, `portfolio_handler/`,
  `strategy_handler/`, `execution_handler/`) and 4-space modules (`price_handler/feed/`, `config/`,
  `outils/`) — **match each file's indentation; never normalize** (a mixed-indent diff breaks a tab file).

### Indentation map (DO NOT normalize)
- Tabs: `order_handler/`, `portfolio_handler/`, `strategy_handler/`, `execution_handler/`.
- 4 spaces: `price_handler/feed/`, `config/`, `outils/`, `itrader/storage/`.

</code_context>

<specifics>
## Specific Ideas

- **Owner wants a durable, discoverable map, not a throwaway** — chose in-repo `docs/` + code annotations
  (D-01) specifically so the inventory survives milestone archival and stays anchored to the code (the
  FastAPI app + future devs consume it).
- **Owner accepts the one authorized code edit** (D-02 knob removal) rather than a strictly zero-edit
  doc phase — but the boundary stays tight: nothing else in code moves.
- **Owner wants the map true to current HEAD** (D-03 fresh re-verify), not a stale copy of the 2026-06-27
  research — the new Phase-4 working-set caches get a first-class classification.

</specifics>

<deferred>
## Deferred Ideas

- **Arrow-backed unification of the hot-path cache** — explicitly **rejected**, not deferred (Q7 /
  FEATURES anti-features). Recorded in the map as a decision; never to be attempted on the per-tick path.
- **Async batch write-through for append-heavy live writes** — carried from Phase 4 (keep-only-measured);
  not a cache-classification concern. N+4 / later, only if profiling justifies it.

### Reviewed Todos (not folded)
- **`single-pass-portfolio-valuation.md`** (matched on `cache`/`deferred`/`phase` keywords) — **not
  folded.** It is a *profile-gated perf build* (a cached per-bar valuation field that does **not yet
  exist**), not the classification of an existing cache. It carries its own byte-exactness landmine + a
  "re-profile W1/W2 before building" gate. Out of scope for Phase 5 (classify existing caches); stays
  deferred as a future perf item.

</deferred>

---

*Phase: 5-Cache Classification (#3)*
*Context gathered: 2026-06-30*

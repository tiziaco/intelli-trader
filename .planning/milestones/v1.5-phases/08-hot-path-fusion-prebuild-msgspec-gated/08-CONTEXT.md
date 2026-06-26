# Phase 8: Hot-Path Fusion, Bar Prebuild & msgspec Migration - Context

**Gathered:** 2026-06-25
**Status:** Ready for planning

<domain>
## Phase Boundary

Cut the post-Phase-7 profiler-confirmed per-bar CPU hotspots (~26% W1 combined) on the backtest hot
path — mark-to-market single-pass fusion, `Position.net_quantity`/`avg_price` caching, `itertuples`
bar prebuild, `Strategy.to_dict` static-snapshot cache, per-tick `check_aligned` precompute — **plus**
the `msgspec.Struct` migration of the value-object/message layer, with **ZERO change to engine
numbers**. The SMA_MACD oracle stays **byte-exact** (134 trades / `final_equity 46189.87730727451`).
This is a byte-exact phase (NOT a re-baseline like Phase 5) — none of the targets touch the money /
position / order / fill numeric surface; they are construction-cost, valuation-iteration, and
serialization surfaces only.

Requirements are LOCKED by `08-SPEC.md` (ambiguity 0.12). This discussion covered the **HOW**
(implementation) decisions only, **plus one owner-directed scope expansion of Req 6** (see D-01).

</domain>

<spec_lock>
## Requirements (locked via SPEC.md)

**6 requirements are locked** (5 committed deterministic wins + 1 previously-gated msgspec decision,
now resolved to INCLUDE). See `08-SPEC.md` for full requirements, boundaries, constraints, and
acceptance criteria. Downstream agents MUST read `08-SPEC.md` before planning or implementing —
requirements are not duplicated here.

**In scope (from SPEC.md):**
- Single-pass fusion of the per-bar portfolio mark-to-market (market value + unrealised PnL + locked
  margin) — `position_manager.py`, `portfolio_handler.py` (Req 1).
- Fill-invalidated caching of `Position.net_quantity` / `avg_price` — `position/position.py` (Req 2).
- `itertuples`/vectorized `Bar` prebuild (drop `iterrows`) — `price_handler/feed/bar_feed.py` (Req 3).
- `Strategy.to_dict` static-snapshot cache — `strategy_handler/base.py` (Req 4).
- Per-tick `check_aligned` precompute/cache — `outils/time_parser.py` (Req 5).
- `msgspec.Struct` migration of `Bar` + per-tick events — RESOLVED to **INCLUDE** (Req 6); see D-01
  for the owner-directed expansion to the full value-object/message layer.
- Equivalence / invalidation / drift tests per committed change; same-machine A/B attribution; cool
  W1 baseline re-freeze.

**Out of scope (from SPEC.md):**
- Coverage-strategy costs (`perf/strategies/*`) — benchmark instruments, not engine code.
- `reporting/` pandas (`metrics.py`, `frames.py`, `plots.py`, `summary.py`) — runs once post-run.
- One-time CSV load (`csv_store.py` `read_csv`/`to_datetime`) — fixed amortizing cost.
- The `bar_feed.window()` `iloc` slice — already tamed by the D-10 cursor; not re-opened.
- Any change to engine numbers — byte-exact phase; re-baselining is Phase-5-only territory.
- `to_money` / `uuid7` discipline — inherent, not optimized here.
- **`Position` → `msgspec.Struct`** — explicitly excluded (D-01): wrong shape (mutable aggregate),
  hotspot is recompute not construction (Req 2 owns it), frozen would collide with Req 2's cache.

</spec_lock>

<decisions>
## Implementation Decisions

> Decision tags are phase-local (`D-01`..`D-06`, PERF-08). Each HOW decision sits on top of the
> locked SPEC requirements and cites the precedent or evidence it derives from.

### Req 6 — msgspec migration scope & recording (owner-directed)

- **D-01 (expand msgspec to the full value-object/message layer; EXCLUDE `Position`):** Convert to
  `msgspec.Struct` — `Bar` (`core/bar.py`) + the **full `Event` hierarchy**
  (`events_handler/events/`) + the standalone DTOs `FillDecision` / `CancelDecision`
  (`execution_handler/matching_engine.py`), `SignalRecord` (`strategy_handler/signal_record.py`),
  `Transaction` (`portfolio_handler/transaction/transaction.py`), and `TrailState`
  (`matching_engine.py`, non-frozen, included for pattern-uniformity). This is an **owner-directed
  expansion** of Req 6's literal "Bar + per-tick events" wording (decided 2026-06-25): "since we're
  already in this layer, end with one uniform Struct value-object pattern."
  **`Position` is EXCLUDED** — three independent reasons established during discussion: (1) it is a
  hand-written **mutable stateful aggregate** (`class Position(object)`), built once per position
  open (a handful per run), NOT a high-frequency immutable DTO — msgspec's construction-speed win has
  almost nothing to act on; (2) its ~7.3% profiled cost is **property recompute on access**, which
  **Req 2's caching** fixes, not construction speed; (3) a frozen `Struct` would actively collide
  with Req 2's mutable invalidated cache. The matching/transaction/signal DTOs ARE genuine value
  objects and are independent of the `Event` chain, so each converts standalone (no forced-chain
  coupling like the `Event` hierarchy had).
  **Reliability is not compromised:** msgspec is used **purely as a fast-construction container — we
  never `msgspec.encode`/`decode` these objects**, so there is no validation/coercion path and
  **Decimal money fields stay Decimal** (the end-to-end Decimal contract is untouched). Every
  conversion is gated by the byte-exact oracle + determinism double-run + `mypy --strict` (the spike
  cleared all three for `Event` + `Bar`). `gc=False` is applied **per-DTO**, only where the struct is
  reference-cycle-free (a per-DTO judgment for the researcher, never a blanket flag).
  **Rejected:** spike-scope-only (events + Bar) — leaves the layer split (Struct events vs dataclass
  DTOs) and re-opens the same files in a later phase; whole-hot-path *including Position* — wrong tool
  for a mutable aggregate, hotspot already owned by Req 2, frozen collision.

- **D-02 (keep-only-measured recording — events+Bar = headline win; extra DTOs = consistency layer):**
  The milestone's keep-only-measured gate (revert noise-only changes) is reconciled with D-01's
  unmeasured DTOs by recording **two distinct justifications**: (a) **events + `Bar` remain the
  A/B-attributed perf win** — the spike's measured **+3.82% W1 / +6.72% W2@50** is the headline
  gate-(b) number; (b) the additional DTOs (`FillDecision`/`CancelDecision`/`SignalRecord`/
  `Transaction`/`TrailState`) fire at ~1,578/run (≈4% of the ~69k `Bar` construction volume), so their
  isolated A/B delta will land in run-to-run noise — they convert under the **same byte-exact oracle
  gate** for a **uniform value-object layer (a consistency refactor, perf-neutral-to-small)**, and are
  **NOT individually reverted** for failing to show an attributable A/B delta. This carve-out is
  explicit so the executor/verifier does not hit a "convert → A/B is noise → discipline says revert"
  contradiction. **Honesty note:** msgspec on `SignalRecord` speeds *construction*, but SignalRecord's
  profiled 3.3% hotspot is its `to_dict` re-introspection — fixed by **Req 4**, not msgspec; Signal is
  converted mainly for uniformity (and signal-heavy strategies beyond the oracle).

### Sequencing & A/B attribution

- **D-03 (5 deterministic wins first → cool re-freeze → msgspec as a measured second layer):** Land
  and **A/B-attribute the 5 deterministic wins (Reqs 1–5) individually**, re-freeze the cool W1
  baseline, **THEN** re-implement msgspec (Req 6) as a measured second layer on the new baseline with
  its **own fresh A/B**. The spike CODE was discarded (only `08-MSGSPEC-SPIKE-FINDINGS.md` kept), so
  the migration is re-implemented cleanly — its A/B is taken fresh, not inherited from the discarded
  spike branch. Cleanest attribution; matches keep-only-measured best.
  **Rejected:** one combined all-six A/B + single re-freeze — fewer benchmark cycles but cannot
  isolate which of Reqs 1–5 is noise vs real, weakening keep-only-measured for the deterministic wins.

### Req 1 — single-pass mark-to-market fusion

- **D-04 (fused valuation method in `position_manager`; public accessors delegate):**
  `position_manager` grows a **private single-pass valuation** that, in ONE iteration over
  `_storage.get_positions()`, produces total market value + total unrealised PnL + the locked-margin
  basis (the three Decimals the per-bar update needs). The per-bar update calls it; the public
  `get_total_market_value` / `get_total_unrealized_pnl` **delegate to the fused result and keep
  returning byte-identical Decimals**. `portfolio_handler` (currently looping positions a 3rd time at
  `:638-645` for locked margin) **asks `position_manager` for the locked-margin basis** instead of
  iterating positions itself — keeping position iteration in one owner.
  **Rejected:** fuse only market-value + unrealised-PnL and leave the margin loop in
  `portfolio_handler` — smaller blast radius but stays 2 passes, only partially satisfying the
  single-pass requirement.

### Req 2 — Position property caching

- **D-05 (explicit cache fields, reset-on-fill, fill-invalidation unit test; Position stays mutable):**
  Cache `net_quantity` / `avg_price` in explicit fields (e.g. `_net_quantity_cache` /
  `_avg_price_cache`), **reset to `None` and recompute lazily whenever a fill mutates the inputs**
  (`buy_quantity` / `sell_quantity` / commissions / avg prices). Explicit, easy to prove correct with
  a **fill-invalidation unit test** (cached value after a buy/sell differs correctly), and `Position`
  **stays a mutable class** (it's excluded from msgspec per D-01). `market_value` still reflects the
  per-bar `current_price` (the cache is only on the fill-derived quantities/prices). Cached Decimals
  stay Decimal.
  **Rejected:** `functools.cached_property` + `__dict__` eviction — couples to descriptor internals
  and is an awkward fit since `Position` is a hand-written class, not a dataclass.

### Req 4 — Strategy.to_dict static-snapshot cache

- **D-06 (per-INSTANCE lazy static cache; refresh only the 2 runtime fields; + documented
  invalidation hook):** Cache the serialized **static** portion of the `to_dict` snapshot **per
  instance** (NOT per class — per-class would leak one instance's declared values, e.g.
  `short_window=10` vs `20`, into another → a correctness bug). Build it **lazily on first `to_dict`**
  (avoids `__init__`-ordering fragility) and stash on `self`. Per call, **refresh only the two
  genuinely runtime-mutable fields — `is_active` (base.py:856/859) and `subscribed_portfolios`
  (846/853)** — verified the exhaustive mutable set; everything else
  (`strategy_id`/`strategy_name`/`timeframe_alias`/`sizing_policy`/`direction`/`allow_increase`/
  `max_positions`/`sltp_policy`/declared windows) is set-once in `__init__` with no setter.
  **Byte-identical** is guaranteed by overwriting those two keys **in place** (Python preserves
  existing-key position on update), so snapshot key ordering is unchanged — gated by a Phase-4-style
  **snapshot-drift test**. The expensive memoized part is the per-field `getattr` + `isinstance` +
  enum/policy `repr` + `_json_safe` recursion (the field *names* are already memoized per-class by
  Phase 4's `@cache _declared_hints`, D-05 PERF-04).
  - **Forward-looking seam (owner concern, 2026-06-25):** add a ~2-line
    `_invalidate_to_dict_cache()` (`self._<cache> = None`) with a comment: *"any setter that mutates
    a declared param MUST call this."* **No such setter exists in Phase 8**, so the hook is never
    called → zero backtest cost, byte-exact preserved — but the future live-trading param-setters
    (and/or Postgres/NoSQL-backed params) have a documented seam to invalidate against, so the cache
    cannot silently desync in live mode. See Deferred Ideas.

### Claude's Discretion
- **Req 3 (itertuples prebuild)** — mechanical swap of `frame.iterrows()` → `itertuples(index=True)`
  / column-array zips, preserving the D-14 Decimal-via-string `Bar` contract byte-for-byte; gated by a
  field-for-field equivalence test vs the `iterrows` build. Standard precedent; planner's shape.
- **Req 5 (`check_aligned` precompute)** — follows Phase 7's D-01 exactly: bounded
  `@functools.lru_cache(maxsize=N)` on the module-level alignment function (unbounded `ts` key → must
  be bounded, not bare `@cache`), body byte-unchanged, equivalence test over a representative
  tick/timeframe set. Researcher pins `N` against the W1 intra-tick fan-out.
- **`gc=False` per-DTO** (D-01) — apply only where the struct is reference-cycle-free; researcher
  confirms per type.
- **`Transaction` / `TrailState` mutability check** (D-01) — both are mutable dataclasses; convert as
  non-frozen Structs only after the researcher confirms they aren't relying on dataclass-specific
  behavior; `TrailState` is low-frequency (rides in for uniformity, not perf).
- **Exact fused-method signature / return shape** (D-04) and **cache-field naming** (D-05/D-06) —
  within "one pass, public accessors byte-identical" and "fill-invalidation proven."

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Locked requirements — read FIRST
- `.planning/phases/08-hot-path-fusion-prebuild-msgspec-gated/08-SPEC.md` — the 6 locked requirements
  (5 deterministic wins + Req 6 msgspec), boundaries, constraints, acceptance criteria. **MUST read
  before planning.**
- `.planning/phases/08-hot-path-fusion-prebuild-msgspec-gated/08-MSGSPEC-SPIKE-FINDINGS.md` — the
  measure-first msgspec spike: the +3.82% W1 / +6.72% W2@50 A/B numbers, the INCLUDE override, the
  migration map (`ClassVar[EventType]` type tag, `msgspec.structs.replace`, frozen-honors-
  `object.__setattr__`, `gc=False`), and the **~29 enumerated mechanical test updates** the real
  migration must apply. **MUST read before the Req 6 re-implementation.**

### Target code — the files this phase edits (⚠ match each file's indentation; see Code Insights)
- `itrader/portfolio_handler/position/position_manager.py` — `get_total_market_value` **:287-298**,
  `get_total_unrealized_pnl` **:300-311** (fuse into one pass, D-04). **TABS.**
- `itrader/portfolio_handler/portfolio_handler.py` — the locked-margin position loop **:638-645**
  (replace with a call to `position_manager`'s fused margin basis, D-04). **TABS.**
- `itrader/portfolio_handler/position/position.py` — `avg_price` **:110-120**, `net_quantity`
  **:127-131** (`@property` → explicit fill-invalidated cache, D-05); `class Position(object)` **:21**
  (mutable, EXCLUDED from msgspec D-01). **TABS.**
- `itrader/price_handler/feed/bar_feed.py` — the prebuild loop **:255-258**
  (`iterrows` → `itertuples`/vectorized, Req 3). **4 SPACES** (feed package).
- `itrader/strategy_handler/base.py` — `to_dict` **:640-704** (per-instance static cache + invalidation
  hook, D-06); `_declared_hints` **:107-108** (the per-class name memo it sits on, Phase 4 D-05).
  **TABS.**
- `itrader/outils/time_parser.py` — `check_aligned` / alignment math **:167-168** (precompute/bounded
  `lru_cache`, Req 5). **TABS.**
- `itrader/core/bar.py` — `Bar` (→ `msgspec.Struct`, D-01). **4 SPACES.**
- `itrader/events_handler/events/` — `base.py` `Event` + `market.py`/`signal.py`/`order.py`/`fill.py`/
  `error.py` (full hierarchy → `msgspec.Struct`, D-01). **4 SPACES** (events package).
- `itrader/execution_handler/matching_engine.py` — `TrailState` **:61-62** (mutable),
  `FillDecision` **:81-82** / `CancelDecision` **:96-97** (frozen) → `msgspec.Struct` (D-01); the
  resting-MODIFY `dataclasses.replace` **:166** → `msgspec.structs.replace`. **TABS.**
- `itrader/portfolio_handler/transaction/transaction.py` — `Transaction` **:14-15** (→ `msgspec.Struct`,
  D-01). **TABS.**
- `itrader/strategy_handler/signal_record.py` — `SignalRecord` **:38-39** (frozen → `msgspec.Struct`,
  D-01). Check indentation per file.

### Pattern precedents — established conventions reused here
- `itrader/strategy_handler/base.py` **:94-108** — `@cache def _declared_hints(cls)` (Phase 4
  D-05/PERF-04): the per-class name memo D-06's per-instance value cache sits on top of.
- `itrader/price_handler/feed/bar_feed.py` **:81-87** — `@functools.cache def _offset_alias(timeframe)`
  (Phase 6 D-01) — the module-level memo template; Req 5 mirrors it as the bounded `lru_cache` variant.
- `.planning/phases/07-per-bar-metrics-timestamp-polish/07-CONTEXT.md` — Phase 7 D-01 bounded-
  `lru_cache` on `_aligned` (the direct precedent for Req 5) + the audit-the-invariant / dedicated-
  equivalence-test discipline.
- `.planning/phases/06-bar-feed-window-copies-optional-slip-able/06-CONTEXT.md` — the audit-the-
  invariant + dedicated equivalence test (D-08/D-16) and the gate-(b) cool-machine same-machine-A/B
  attribution method.

### Gate (a) — correctness lock (byte-exact, held not changed)
- `tests/integration/test_backtest_oracle.py` — byte-exact SMA_MACD oracle (134 /
  `46189.87730727451`) + determinism double-run. (Per memory `oracle-test-location`: this is the
  oracle; `tests/golden` is artifacts, 0 tests collected.)

### Gate (b) — perf harness + baseline (cool re-freeze)
- `Makefile` — `perf-w1` (gated `--check`), `perf-w2`, `perf-profile` (Scalene), `perf-baseline`
  (re-freeze W1).
- `perf/runners/run_w1_benchmark.py`, `perf/runners/run_w2_sweep.py` — the W1/W2 runners.
- `perf/results/W1-BASELINE.json` — the frozen W1 reference (re-frozen on a cool box after the 5
  deterministic wins land, then again after msgspec per D-03). `perf/results/scalene-w1.json` — the
  re-profile that surfaced the Phase 8 hotspots.

### Milestone scope + gate definition
- `.planning/REQUIREMENTS.md` — PERF-08 + the milestone gate (a)/(b) definition.
- `.planning/ROADMAP.md` — Phase 8 entry (line 64) + the byte-exact framing.
- `.planning/STATE.md` — milestone gate (a)/(b) full text + the v1.5-final locked W1 reference.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- **The msgspec migration is already de-risked by the spike** — `08-MSGSPEC-SPIKE-FINDINGS.md` holds
  the working migration map (type-tag → `ClassVar`, `msgspec.structs.replace`, frozen-via-
  `object.__setattr__`, `gc=False`) and the exact ~29 mechanical test updates. The re-implementation
  is mechanical, not exploratory.
- **The `@functools` memoization convention is thrice-used** (`_offset_alias`, `_declared_hints`,
  Phase 7 `_aligned`) — Req 5 mirrors it (bounded `lru_cache`); D-06's per-instance cache layers on
  top of `_declared_hints`.
- **The W1/W2 harness exists** (Phase 1): `perf-w1 --check`, `perf-w2`, Scalene profile, `perf-baseline`
  re-freeze — gate (b) needs no new tooling, only re-profile + cool re-freeze.

### Established Patterns
- **Audit-the-invariant + dedicated equivalence/drift test, NO hot-path runtime guard** (Phase 3
  D-03, Phase 4 D-06/D-07, Phase 6 D-08/D-16). Reuse for each Phase 8 win: fusion-equivalence (public
  accessors byte-identical), fill-invalidation (Req 2), `Bar` field-for-field (Req 3),
  snapshot-drift (Req 4 — byte-identical `to_dict`), `check_aligned` boolean equivalence (Req 5), and
  oracle byte-exactness for every msgspec conversion (Req 6).
- **Gate (a) byte-exact / Gate (b) same-machine A/B on a verified-COOL box** (memory
  `v15-perf-gateb-thermal-drift`) — never trust the frozen-baseline compare on a throttled box; the
  spike's W1/W2 8-run position-balanced method is the template.
- **msgspec as a construction container only (no encode/decode)** — preserves the Decimal-end-to-end
  money contract; the spike confirmed there is no encode path.

### Integration Points
- D-04 is the only **cross-component** change: `portfolio_handler` stops looping positions for margin
  and asks `position_manager` for the fused basis (still no event-queue / cross-domain signature
  change — `position_manager` is the position read-owner). All other changes are internal to their
  module.
- msgspec dispatch verified by the spike: `EventHandler._dispatch` reads `event.type` via a `ClassVar`
  — works unchanged. The `Event` hierarchy converts **together** (msgspec forbids Struct/non-Struct in
  one chain); the standalone DTOs (`FillDecision`/`CancelDecision`/`SignalRecord`/`Transaction`/
  `TrailState`) convert independently.
- ⚠️ **INDENTATION HAZARD — verify per file.** `core/bar.py` and `events_handler/events/` are
  **4 SPACES**; `bar_feed.py` (feed package) is **4 SPACES**; the handler/manager modules
  (`position_manager.py`, `portfolio_handler.py`, `position.py`, `base.py`, `time_parser.py`,
  `matching_engine.py`, `transaction.py`) are **TABS**. Match each file; do NOT normalize (a mixed
  diff breaks a tab file).

</code_context>

<specifics>
## Specific Ideas

- **msgspec runtime-dependency promotion:** Req 6's INCLUDE means `msgspec` is promoted from a
  dev-only transitive dependency (0.21.1, via nautilus-trader) to a **shipped `itrader/` runtime
  dependency** — `pyproject.toml` runtime deps change accordingly (per the spike's override).
- **The win is byte-exact end-to-end** — every target is a construction-cost, valuation-iteration, or
  serialization surface; no stored or reported numeric value (Decimal or float) changes. The oracle
  (134 / `46189.87730727451`) is the hard lock.
- **Position is the canonical "wrong tool for msgspec" example** captured this session: mutable
  stateful aggregate, recompute hotspot (owned by Req 2), frozen-collides-with-cache — useful framing
  for future "should X be a Struct?" calls (the test: high-frequency immutable value object → yes;
  mutable aggregate → no).

</specifics>

<deferred>
## Deferred Ideas

- **Live strategy-param setters / Postgres-NoSQL-backed params must invalidate (or bypass) the
  `to_dict` static cache** — owner concern (2026-06-25): live trading will add setters that mutate
  declared params (e.g. `short_window`) at runtime, and params may move to a Postgres/NoSQL store. The
  per-instance static cache (D-06) ships with a **documented `_invalidate_to_dict_cache()` seam** now
  (never called in backtest), so the live work has a safe place to land. Wire the actual invalidation
  (or a Postgres-repopulate path) when the live param-setters are designed — **N+3b Persistence /
  N+4 Live Trading Readiness**. *(Promote to a todo / roadmap backlog item when convenient.)*
- **msgspec conversion of the residual hot-path dataclasses NOT in this phase** — the spike's
  Scalene check left a residual ~6.31% construction frame in dataclasses outside scope. After D-01,
  the main remaining one is `Position` — but it is the *wrong* shape for msgspec (D-01 rationale);
  revisit only if a future re-profile shows a construction (not recompute) hotspot on a genuinely
  DTO-shaped object that Phase 8 didn't cover.
- **Whole-hot-path A/B re-measurement at larger symbol universes** — the spike showed the msgspec win
  scales with symbol count (3.82% @4 → 6.72% @50). If the optimization-module / target universe grows
  past ~10 symbols, re-confirm the W1-equivalent crosses 5% comfortably (informational; the INCLUDE
  decision already stands).

</deferred>

---

*Phase: 08-hot-path-fusion-prebuild-msgspec-gated*
*Context gathered: 2026-06-25*

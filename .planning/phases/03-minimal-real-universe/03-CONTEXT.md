# Phase 3: Minimal Real Universe - Context

**Gathered:** 2026-06-09
**Status:** Ready for planning

<domain>
## Phase Boundary

Replace the static `derive_membership` stub with a **time-parameterized
`membership`-from-availability primitive** — `active_membership(T)` — that
returns the set of tickers live at time T, derived **solely from each loaded
ticker's data-availability span** (no screening/ranking). Wire it so the engine
survives a ticker that **lists mid-run** and assets with **differing end dates**
with no crash and no look-ahead.

**In scope:**
- A new time-aware availability query (e.g. `active_membership(T)` /
  `is_active(ticker, T)`) in `itrader/universe/`, derived from each loaded
  ticker's `[first_bar, last_bar]` data span (span model).
- Refining the feed's per-tick absence observability to consult it.
- Deleting the legacy duplicate warning in the strategy handler (CLAR-02
  opportunistic cleanup along a touched path).
- Synthetic-fixture tests proving mid-run listing, differing end dates, and the
  mid-life-gap edge.

**Out of scope (own phases / milestones):**
- **Gating** bar production / engine consideration on membership (selection
  layer = the production screener, deferred to **v1.3 / D-screener**).
- Any screening / ranking / rebalance loop.
- The **full end-to-end run over the real ETH/SOL/AAVE differing spans** — that
  belongs to **Phase 9** (ROBUST-03 "heterogeneous date spans … over a union
  window") via the **Phase 4** E2E harness. Forward-pointer recorded below.
- Re-baselining the BTCUSD golden oracle (v1.1 is behavior-preserving — all
  changes here must be **oracle-dark** on the single-ticker run).

</domain>

<decisions>
## Implementation Decisions

### Active-at-T Semantics
- **D-01:** **Span model.** A ticker is "active at T" iff
  `first_bar_date <= T <= last_bar_date` — its full listed lifespan, **including
  any internal gap days** (a mid-life missing bar is still "a member, just
  gapped"). Chosen over exact-bar-presence because it models a real exchange's
  listing concept and is the shape a production screener extends — and because
  exact-bar-presence would conflate a one-day data hole with a delisting
  (silently leaving + re-entering membership). Span boundaries derive from each
  ticker's own loaded data extent (pure availability — roadmap-locked: "derived
  solely from data availability").

### Engine Role / Wiring
- **D-02:** **Derived read, NOT a gate** (Zipline `can_trade` shape). The
  primitive is a **pure queryable availability function** plus it refines the
  feed's warning loop — it does **NOT** filter which tickers enter the BarEvent
  and does **NOT** touch the hot-loop bar path. Rationale: professional
  frameworks separate *availability/tradability* (a query — Zipline
  `can_trade`/asset-lifetime) from *selection* (the gate — LEAN
  `UniverseSelectionModel`). Gating is the **deferred v1.3 screener's** job
  ("screeners propose, membership disposes", D-20). Gating now would conflate
  the layers, pull v1.3 work forward, and rewrite the hot loop — risking the
  byte-identical BTCUSD oracle for **zero behavioral gain** (the existing
  sparse-dict in `current_bars` already prevents fills for absent bars).

### Primitive Shape (relationship to `derive_membership`)
- **D-03:** **Add `active_membership(T)` alongside** `derive_membership` — do
  NOT replace it. `derive_membership` stays as the static **"set of interest" /
  selection-combination seam** (strategy ∪ screener union) — the exact seam the
  v1.3 screener extends ("screeners propose, membership disposes"). The new
  availability query is a **separate, composable** function over loaded data
  spans. Mirrors the framework split (Zipline `AssetFinder` registry vs.
  per-time `can_trade`): the two answer different questions for different
  consumers — "what do we track?" (wiring-time, no meaningful T) vs. "what's
  live at T?" (per-tick). Future screener composes them:
  `selected(T) = screen(active_membership(T), ranking)`. No live-path
  (`live_trading_system.py`) disturbance.

### Absence Observability (single owner)
- **D-04:** The **feed's `generate_bar_event`** loop is the **single
  span-aware owner** of absence observability: **silent** for *expected*
  absence (T outside a ticker's `[first,last]` span — not-yet-listed /
  delisted/ended), **warn only** on a *true mid-life gap* (T inside the span but
  no bar — a real data-quality anomaly worth surfacing in frozen fixtures).
- **D-05:** **Strip the duplicate warning from the strategy handler.** The
  WR-12 sparse guard (`strategies_handler.py:69-73`) has two fused parts: the
  `if bar is None: … continue` skip is **LOAD-BEARING** (price is stamped from
  `event.bars[ticker].close` three lines later — keep it) and the
  `self.logger.warning('No last close for %s …')` line is legacy spam —
  **delete the warning line only**, keep the silent skip. The strategy handler
  is a pure *consumer*: a missing bar means "nothing to do this tick," not its
  job to diagnose data quality. Oracle-dark (BTCUSD is dense, the line never
  fires on the golden run) → no golden-run risk. CLAR-02 opportunistic cleanup
  along a Phase-3-touched path.

### Proof Strategy
- **D-06:** **Synthetic controlled fixture only** for Phase 3. Unit tests of
  `active_membership(T)` plus a small engine integration test driven by
  **hand-pinned tiny datasets** with controlled listing / end / mid-life-gap
  dates — exact, fast, deterministic edge coverage (incl. the no-look-ahead
  "no fill before listing" assertion). The full real-data E2E run over
  ETH/SOL/AAVE differing spans is **deferred to Phase 9** (it needs the Phase 4
  harness; ROBUST-03 already scopes it).

### Claude's Discretion
- Exact function name/signature (`active_membership(T) -> set[str]` vs.
  `is_active(ticker, T) -> bool` vs. both), where span boundaries are cached
  (e.g. precomputed `[first,last]` per ticker at feed init from the loaded
  frames), and the precise synthetic-fixture layout/format — left to research
  and planning, subject to the decisions above.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### The membership primitive (where the new query lands; growth-shape contract)
- `itrader/universe/membership.py` — current static `derive_membership` + the
  `SupportsTickers` Protocol. Its module docstring **pins the growth target**
  (D-20): per-tick membership grows HERE as a LEAN `UniverseSelectionModel`
  shape, driven by the deferred D-screener rebalance loop ("screeners propose,
  membership disposes"); "that milestone touches ONLY this module." Keep the
  seam clean — Phase 3 ADDS alongside, does not gate.
- `itrader/universe/__init__.py` — package barrel (re-export the new query).

### The feed (BarEvent production + the absence-warning site to refine)
- `itrader/price_handler/feed/bar_feed.py` — `generate_bar_event` (the
  warn-all loop to make span-aware, `:244-257`), `current_bars` (the **sparse
  dict** that ALREADY drops absent tickers, `:261-275` — this is why no fill
  occurs on an absent bar), `bind` (`:210-228`), and the seven-rule **bar-timing
  / look-ahead-safety contract** at the top of the file (enforce no look-ahead
  in the window slice, never in the primitive).

### The strategy-handler warning to strip (keep the load-bearing skip)
- `itrader/strategy_handler/strategies_handler.py:69-73` — WR-12 sparse-ticker
  guard. Delete the `logger.warning` line; KEEP `if bar is None: … continue`
  (load-bearing — price stamped from `event.bars[ticker].close` at `:84-88`).

### Engine wiring (membership derivation + union ping grid)
- `itrader/trading_system/backtest_trading_system.py:139-167` —
  `_initialise_backtest_session`: derives membership (`:149`), binds the feed
  (`:153`), and builds the **union** ping grid over every symbol's index (WR-07,
  `:163`) — heterogeneous spans are ALREADY handled at the grid level.
- `itrader/trading_system/live_trading_system.py:199-212` — the live-path
  `derive_membership` call site (D-03 keeps this undisturbed).

### Data layer (where availability spans come from)
- `itrader/price_handler/store/csv_store.py` — `CsvPriceStore`: `csv_paths`
  config = the manual data-subscription seam (`:52`), `symbols()` (`:100`),
  `read_bars`/`index` — each ticker's loaded frame defines its `[first,last]`
  availability span. **Not modified** on the run-path schema.
- `data/ETHUSD_1d_ohlcv.csv`, `data/SOLUSD_1d_ohlcv.csv`,
  `data/AAVEUSD_1d_ohlcv.csv`, `data/BTCUSD_1d_ohlcv_2018_2026.csv` — the
  Phase-2 normalized datasets with real differing spans (the eventual Phase-9
  E2E inputs; informative for synthetic-fixture design).

### Phase / requirements / decisions / prior context
- `.planning/ROADMAP.md` §"Phase 3: Minimal Real Universe" — goal + 3 success
  criteria.
- `.planning/REQUIREMENTS.md` — **UNIV-01** (real availability primitive
  replaces the stub; screening excluded), **UNIV-02** (mid-run listing +
  differing end dates; no crash, no look-ahead, absent bars → no fill).
- `.planning/PROJECT.md` Key Decisions — "minimal real universe … the
  production screener extends, **never a throwaway skip**" (line 164);
  behavior-preserving (BTCUSD oracle not re-baselined).
- `.planning/codebase/FIX-LIST.md` — **no Phase-3-eligible cleanup item** on
  this path (FL-03→Phase 4, FL-04→Phase 5, rest deferred). The only
  opportunistic cleanup here is D-05 (strip the legacy strategy-handler
  warning), captured by CLAR-02.
- `.planning/codebase/CLEANUP-STANDARD.md` — the 4-gate opportunistic-cleanup
  checklist D-05 is executed under.
- `.planning/phases/02-data-ingestion/02-CONTEXT.md` — the upstream datasets
  this phase exercises (D-06 SOLUSD(11)/AAVEUSD(35) zero-volume sentinel note;
  6-column golden schema).

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- **`current_bars` sparse dict** (`bar_feed.py:261-275`) — already returns
  ONLY tickers with a bar stamped exactly at T (absent tickers dropped). This is
  the existing mechanism that makes "absent bar → no fill" structurally true;
  Phase 3 adds the *primitive + observability*, not new fill-suppression.
- **Union ping grid** (`backtest_trading_system.py:163`, WR-07) — the tick grid
  is already the union of every symbol's index, so differing end dates / mid-run
  listings produce ticks across the union window today. No grid change needed.
- **`derive_membership` + `SupportsTickers`** (`membership.py`) — the existing
  union/flatten logic and Protocol; the new query lives beside it in the same
  module.
- **`store.symbols()` / `read_bars()` / `index()`** (`csv_store.py`) — the
  source of each ticker's `[first_bar, last_bar]` availability span.

### Established Patterns
- **Availability vs. selection separation** (frameworks + D-20): keep the
  per-time availability query distinct from the selection/combination seam —
  the explicit design adopted in D-02/D-03.
- **Sparse-universe guards** (WR-12 `strategies_handler.py:69`, D-15 BarEvent
  payload): a no-data ticker is ABSENT from the dict; consumers guard with
  `.get(ticker)` and skip — Phase 3 keeps the skip, drops the noise (D-05).
- **Look-ahead safety lives in the slice** (`bar_feed.py` 7-rule contract):
  the membership primitive must read spans look-ahead-safely; enforcement stays
  in the feed's window/searchsorted path, never pushed into strategies.
- **Behavior-preserving / oracle-dark** — every Phase-3 change must leave the
  single-ticker BTCUSD golden run byte-identical (D-01..D-06 are all designed to
  be dark on that run).

### Integration Points
- New query → consumed by the feed's `generate_bar_event` warning loop (D-04).
- Span data → sourced from `CsvPriceStore` frames via the feed (`_frames` /
  `read_bars`).
- The static `derive_membership` call sites (backtest + live) stay untouched
  (D-03).

</code_context>

<specifics>
## Specific Ideas

- **Framework precedent drove two decisions.** D-02 (derived read) mirrors
  Zipline `can_trade` / asset-lifetime vs. LEAN `UniverseSelectionModel`
  (selection = the deferred screener). D-03 (add alongside) mirrors the
  Zipline `AssetFinder` registry vs. per-time `can_trade` split. The codebase's
  own `membership.py` docstring already prescribes this layering.
- **Two warning sites, one owner.** The discussion surfaced a *second*
  warn-all site (strategy handler) beyond the feed loop; D-04/D-05 consolidate
  observability onto the feed and silence the consumer.

</specifics>

<deferred>
## Deferred Ideas

- **Full end-to-end run over the real ETH/SOL/AAVE differing spans** → **Phase
  9** (ROBUST-03 "heterogeneous date spans … handled over a union window"), run
  through the **Phase 4** E2E harness. Phase 3 proves the edges on synthetic
  fixtures (D-06); Phase 9 proves a real multi-ticker engine run. (User asked to
  "mark the full E2E test for later" — recorded here.)
- **Membership-as-a-gate / dynamic screener selection** (membership filters bar
  production / engine consideration) → **v1.3 / D-screener** (LEAN
  `UniverseSelectionModel` shape; "screeners propose, membership disposes"). Out
  of scope per D-02.
- **Auto-subscription** (a strategy ticker automatically causing its data to
  load) → NOT pursued. The store stays the explicit data-subscription seam
  (matches Zipline/LEAN selecting from a configured bundle); Phase 3 does not
  change this contract.

</deferred>

---

*Phase: 3-Minimal Real Universe*
*Context gathered: 2026-06-09*

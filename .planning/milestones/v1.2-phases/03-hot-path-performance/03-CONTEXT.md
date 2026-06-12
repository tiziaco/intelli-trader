# Phase 3: Hot-Path Performance - Context

**Gathered:** 2026-06-11
**Status:** Ready for planning

<domain>
## Phase Boundary

Eliminate the dominant **per-tick performance costs** on the backtest hot path —
defensive storage copies, redundant `Decimal(str(Decimal))` re-wraps, duplicated
per-tick work, and per-tick `Bar`/MACD churn — **with bit-identical values**.
Behavior-preserving / oracle byte-exact (134 trades / `final_equity
46189.87730727451`); `mypy --strict` clean; 58/58 e2e green.

In scope (locked by ROADMAP §Phase 3 success criteria, REQUIREMENTS PERF-01/02/03):
- **PERF-01** [W1-15, W1-02, W1-01]: kill the never-firing per-tick snapshot-trim
  copy via `snapshot_count()` / `get_latest_snapshot()` accessors; drop the defensive
  per-call `.copy()` from in-memory storage getters under the D-19 single-writer contract.
- **PERF-02** [W1-08, W1-03, W1-14, W1-07, W1-09 — **W1-13 DESCOPED, see D-10**]: drop
  redundant `Decimal(str(Decimal))` re-wraps on the mark-to-market/equity path and the
  duplicated per-tick work (`open_position_count` ×2, `is_connected` ×2–3, premature
  `on_fill` guard allocation, load-time copy).
- **PERF-03** [W1-12, W1-04]: compute MACD **inside** the SMA guard (not unconditionally
  before it); serve **prebuilt** `Bar`s from `BacktestBarFeed` instead of 5
  `Decimal(str(...))` conversions per symbol per tick.

Out of scope: any change that moves the oracle; incremental/stateful indicators (999.5-(c));
the `order_manager.py` split (Phase 6); other cleanup-review batches (Phases 4-5); the
W1-13 active-portfolio cache (descoped — D-10).

</domain>

<decisions>
## Implementation Decisions

### PERF — Verification rigor (cross-cutting)
- **D-01:** Prove **and lock** each optimization with **deterministic behavioral
  regression assertions** — NOT wall-clock benchmarks (environment-flaky) and NOT
  code-review-only. Concretely: object-**identity** assertion that `get_positions()`
  returns the same dict object (no `.copy()`); a feed-level assertion that `current_bars()`
  serves prebuilt `Bar`s (no per-tick `Bar.from_row`). CI-safe, project-style
  regression-locking, proves the SPECIFIC change landed without timing flakiness.
- **D-02 (owner constraint):** **Do NOT add any new unit test against the `SMA_MACD`
  strategy.** The W1-12 MACD-guard reorder is verified by **code review + byte-exact
  oracle only** — no behavioral assert is written against the strategy module.

### PERF-01 — Storage copy contract (W1-15 / W1-02 / W1-01)
- **D-03:** Drop the defensive `.copy()` from **ALL** `InMemoryPortfolioStateStorage`
  getters — `get_positions`, `get_closed_positions`, `get_transaction_history`,
  `get_cash_operations`, `get_snapshots`. The `PortfolioStateStorage` ABC docstring
  contract becomes: **"getters return read-only views; callers MUST NOT mutate
  (D-19 single-writer); copy yourself if you need ownership."**
- **D-04 (gap-discovery delta — owner-flagged, diverges from the finding):** Do **NOT**
  add the `*_snapshot()` copy-returning twin the W1-01 finding recommended. Rationale: the
  `*_snapshot()` hedge exists only for a hypothetical **write-through-cache** live backend; a
  **query-based** live/Postgres backend is copy-safe for free (it builds fresh result objects
  per call, aliasing no internal state). Adding the seam now is speculative API for deferred
  work — violates the Phase-1/Phase-2 D-05 "no pre-building for deferred work" discipline. A
  future write-through-cache backend protects its own internals when it is written. **Log this
  as a bounded gap-discovery delta** per PROJECT.md ("gap discovery is bounded — logged,
  owner-flagged, never silently folded").
- **D-05 (caller-mutation audit — DONE during discussion):** Dropping the copies is safe —
  verified no caller mutates a returned **container**:
  - `position_manager.py:241` (mark-to-market) mutates the **Position objects** in place
    (`update_current_price_time`); the shallow `.copy()` never protected those objects, so
    that path is unchanged.
  - `close_all_positions():425` removes during iteration but already defends with
    `list(self._storage.get_positions().items())` — the `list()` snapshot is the real
    protection, not the `.copy()`.
  - Public getters (`get_all_positions`, `get_closed_positions`, `get_snapshots`) flow up to
    `reporting/` which only **reads** into DataFrames.
  - **Executor MUST still confirm** no *test* mutates a getter result and asserts storage
    stayed unchanged (that pattern would break and must be migrated).
- **D-06:** Replace the never-firing per-tick snapshot-trim `.copy()` in
  `metrics_manager.py:171` with `snapshot_count()` / `get_latest_snapshot()` accessors on the
  storage seam (count-only / last-only — no whole-list copy). Add both to the ABC + InMemory.

### PERF-03 — Bar prebuild (W1-04)
- **D-07:** **Eager-materialize** all `Bar`s once at `BacktestBarFeed` construction
  (a `{(ticker, time): Bar}` or per-ticker map alongside `_frames`); `current_bars()`
  becomes a pure dict lookup, removing pandas `iloc` + per-tick Decimal construction from the
  hot loop. Bit-identical, oracle byte-exact. Feed-level behavioral assert (no `Bar.from_row`
  per tick) per D-01.
- **D-08:** **Lazy-memoize REJECTED.** Each `(ticker, time)` is queried **exactly once**
  over the run (`current_bars(time)` returns only the row stamped at exactly `time`, called
  once per tick with a unique time) — a memoization cache would serve **zero hits** and add
  pure overhead.
- **D-09 (gap-discovery delta — owner-flagged):** W1-04's **"computed once"** rationale
  **overstates** the saving. Each row is **already** converted exactly once across the run, so
  eager prebuild does NOT reduce the total Decimal-conversion **count** — it **front-loads** it
  to init. The real win is **structural**: removing pandas `iloc` (genuinely slow) + per-tick
  object churn from the per-tick loop, replacing with a hash lookup. The planner MUST write the
  honest rationale ("structural hot-loop de-pandas, bit-identical"), NOT "eliminates per-tick
  Decimal conversions." Memory cost: a second copy of OHLCV as Decimal Bars, ~linear in
  rows×symbols (trivial for the golden single-symbol run).

### PERF-02 — W1-13 descope
- **D-10 (bounded PERF-02 descope — owner-flagged):** **DEFER** W1-13 (the
  `get_active_portfolios()` per-tick cache). It is the inverted-risk-reward item of the batch:
  - **No payoff on the verifiable workload** — the golden run is single-portfolio, so the
    list-comp is over one element per tick; W1-13 only helps multi-portfolio runs (which the
    cleanup review rated "low").
  - **Oracle-blind correctness risk** — `get_active_portfolios()` filters by `is_active()`
    over a real state machine (`ACTIVE↔INACTIVE→ARCHIVED`, `set_state`,
    `delete_portfolio`→ARCHIVED). A cache must invalidate on add/delete **and every status
    transition**; miss one and the wrong set of portfolios gets marked-to-market (e.g. a
    suspended portfolio keeps re-pricing, drifting its equity). The single-portfolio,
    never-transitioning golden run **cannot** catch this — byte-exact would pass with the bug
    shipped.
  - **Action:** correct the PERF-02 / ROADMAP §Phase-3 SC-2 wording to drop "active-portfolio
    recompute" from the in-scope list (same Phase-2 D-07 bounded-delta discipline); record as a
    deferred idea (see Deferred). The other PERF-02 items (W1-08/03/14/07/09) stay in scope.

### Claude's Discretion
- Plan/wave decomposition (grouping PERF-01/02/03 + the mechanical W1-08/03/14/07/09/12 items
  into plans/waves).
- Exact mechanics of each mechanical transform: W1-08 drop `Decimal(str(Decimal))` re-wraps
  (`position_manager.py:277,287,298,303`); W1-03 local-cache `open_position_count()`
  (`order_manager.py:934,939`); W1-14 remove redundant `is_connected()` checks
  (`simulated.py:122,127-135,343,400`); W1-07 hoist the `on_fill` non-EXECUTED guard above the
  `_operation_context`/correlation-id allocation (`portfolio_handler.py:291,297-305`); W1-09
  drop the redundant load-time `raw[expected_cols].copy()` (`csv_store.py:165`).
- Exact placement/naming of the new behavioral-assertion tests (storage identity, prebuilt-Bar)
  and the `snapshot_count()`/`get_latest_snapshot()` accessor signatures.
- Exact wording/home of the two gap-discovery deltas (D-04, D-09) and the corrected SC-2 wording
  (D-10).
- Extent of touched-path opportunistic cleanup (Phase-1 D-05 / `CLEANUP-STANDARD.md`).

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase scope & requirements
- `.planning/ROADMAP.md` §Phase 3 (lines ~135-148) — goal + 4 success criteria. **Also an
  edit target:** SC-2's "active-portfolio recompute" in-scope wording must be corrected per
  D-10 (W1-13 descoped).
- `.planning/REQUIREMENTS.md` PERF-01 / PERF-02 / PERF-03 (lines ~49-58) — the three
  requirements with source-finding tags. **PERF-02's `[…W1-13…]` tag is also an edit
  target** per D-10.

### Source findings (cleanup-review rationale + payoff ratings)
- `.planning/codebase/V1.2-CLEANUP-REVIEW.md` — rows: **5** (W1-15+W1-02 snapshot copies),
  **6** (W1-01 storage getter copies), **7** (W1-04 `Bar.from_row` prebuild), **8** (W1-08
  Decimal re-wraps), **9** (W1-12 MACD guard), **24** (W1-13 active-portfolio cache —
  **DESCOPED**), **25** (W1-07 guard hoist), **26** (W1-03 local cache), **27** (W1-14
  is_connected), **28** (W1-09 load-time copy). §6 **Batch 3** + **Batch 4** (lines ~177-197)
  are the batch summaries (Batch 3 ⚠ prudent, Batch 4 ⚠ oracle-re-run gating). **Note:** the
  Batch-3 finding text recommends the `*_snapshot()` variant that D-04 declines.

### Locked decisions & conventions
- `CLAUDE.md` §"Determinism & money" / §"Architectural Constraints" — Decimal end-to-end;
  D-19 single-writer contract (backtest collection lock removed) that makes the copy-drop safe.
- `.planning/codebase/CONVENTIONS.md` — tab/space hazard: `portfolio_handler/`,
  `execution_handler/`, `strategy_handler/`, `order_handler/` are **tab** modules;
  `core/`, `config/`, `price_handler/feed/` are **4-space** — match each file.
- `.planning/codebase/CLEANUP-STANDARD.md` — touched-path opportunistic-cleanup standard
  (Phase-1 D-05 precedent) governing incidental cleanup on edited files.
- `.planning/phases/02-locked-decision-conformance/02-CONTEXT.md` §D-07 — the
  **bounded gap-discovery delta** precedent (owner-flagged, never silently folded) that D-04 /
  D-09 / D-10 follow.

### Code targets (verified during scout)
- `itrader/portfolio_handler/storage/in_memory_storage.py:48-95` — the five getters' `.copy()`
  (D-03) + the snapshot accessors home (D-06).
- `itrader/portfolio_handler/base.py:66-67,99-100,126-127,198-199,222-240` — the
  `PortfolioStateStorage` ABC getter contracts + snapshot abstractmethods (D-03 contract
  rewrite; add `snapshot_count`/`get_latest_snapshot`).
- `itrader/portfolio_handler/metrics/metrics_manager.py:171-173,189,193` — never-firing trim
  copy → accessors (D-06).
- `itrader/portfolio_handler/position/position_manager.py:241,277,287,298,303,425` — caller
  audit sites (D-05) + W1-08 Decimal re-wraps.
- `itrader/price_handler/feed/bar_feed.py:152-166 (init/_frames),258,283-296 (current_bars)`
  — eager-prebuild seam + per-tick lookup (D-07/D-08/D-09).
- `itrader/core/bar.py:53-68` — `Bar.from_row` (the 5 `Decimal(str())` source, D-14 path).
- `itrader/portfolio_handler/portfolio_handler.py:207-209,291,297-305,359` —
  `get_active_portfolios` (W1-13 **descoped**) + W1-07 `on_fill` guard hoist.
- `itrader/order_handler/order_manager.py:934,939` — W1-03 `open_position_count()` ×2.
- `itrader/execution_handler/exchanges/simulated.py:122,127-135,343,400` — W1-14 `is_connected`.
- `itrader/price_handler/store/csv_store.py:165` — W1-09 redundant load-time copy.
- `itrader/strategy_handler/strategies/SMA_MACD_strategy.py:52-61,66` — W1-12 MACD guard
  reorder (**code-review + oracle only — NO new test, D-02**).

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- **D-19 single-writer contract** (backtest collection lock removed) — the precondition that
  makes dropping defensive copies correct; cite it in the ABC contract docstring (D-03).
- **`_frames`** (`bar_feed.py`) — already holds the full per-symbol OHLCV; the eager Bar map
  (D-07) is built once over the same rows at init.
- **`searchsorted`/`_base_alias`** lookup in `current_bars()` — the per-tick cost the prebuilt
  dict replaces.
- **Phase-2 D-07 gap-discovery-delta mechanism** — the established owner-flagged pattern reused
  by D-04, D-09, D-10.

### Established Patterns
- **Storage seam** (`PortfolioStateStorage` ABC ↔ `InMemory*`) — the single place the
  copy-policy contract lives; the future live/Postgres backend implements the same ABC.
- **Indentation hazard:** storage/portfolio/order/execution/strategy handler modules are
  **tab**; `core/bar.py`, `price_handler/feed/bar_feed.py` are **4-space**. Match each file —
  a mixed-indent diff breaks a tab file.
- **Behavioral-assert / regression-lock test style** — the project's preferred way to pin an
  invariant (D-01); object-identity and call-presence assertions, not timing.

### Integration Points
- `current_bars()` Bars flow to 3 readers — `portfolio.py:344` (mark-to-market),
  `matching_engine.py:140`, `strategies_handler.py:87`; the prebuilt-Bar change must keep all
  three bit-identical.
- The copy-drop touches the read seam between the four portfolio managers and the InMemory
  storage; reporting (`frames.py`, `cash_operations.py`) reads the same getters.
- W1-07 hoist sits on the `on_fill` path — adjacent to (but NOT inside) the FRAGILE
  reservation-release zone; keep the EXECUTED-vs-non-EXECUTED semantics identical.

</code_context>

<specifics>
## Specific Ideas

- The phase's verification philosophy: **byte-exact oracle proves correctness; behavioral
  asserts prove the optimization actually landed.** Neither alone is sufficient for a phase
  literally named "Hot-Path Performance" — but wall-clock benchmarks are explicitly rejected as
  flaky (artifact-only at best).
- The two divergences from the cleanup review (D-04 no `*_snapshot()`, D-10 W1-13 descope) and
  the one framing correction (D-09) are all applications of the **same owner value**: don't
  pre-build for deferred/hypothetical work, and don't ship an oracle-blind correctness risk or a
  dishonest rationale into a behavior-preserving phase. Treat them as the load-bearing output of
  this discussion, mirroring Phase-2 where D-07 (the misdiagnosis correction) was "the most
  important finding."

</specifics>

<deferred>
## Deferred Ideas

- **W1-13 — `get_active_portfolios()` per-tick cache** (PERF-02 descope, D-10). Zero payoff on
  the single-portfolio golden run; introduces an oracle-blind invalidation-correctness risk
  across the `ACTIVE/INACTIVE/ARCHIVED` state machine. **Revisit when multi-portfolio runs are a
  measured workload** (N+2 territory) — at which point it ships **with** a multi-portfolio
  status-transition regression test (active→inactive→active invalidation), which is the only way
  to make it safe.

</deferred>

---

*Phase: 3-Hot-Path Performance*
*Context gathered: 2026-06-11*

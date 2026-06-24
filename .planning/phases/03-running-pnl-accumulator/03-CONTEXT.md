# Phase 3: Running PnL Accumulator - Context

**Gathered:** 2026-06-24
**Status:** Ready for planning

<domain>
## Phase Boundary

Phase 3 replaces the per-bar **re-summation** of realised PnL with a **running accumulator**
maintained as realised PnL changes — eliminating the single hotspot at
`position_manager.py::get_total_realized_pnl` (~13% CPU, hotspot #3, PERF-02). Today that method
loops **both** open positions (which carry realised PnL from *partial* closes) **and** the
ever-growing append-only `_closed_positions` list on every call; the per-bar metrics/equity path
pays O(positions) that grows over the run (≈O(n²) overall). The accumulator caches that running
total so the per-bar read becomes O(1).

This is the perf analog of v1.2 Consolidation: **behavior-preserving — it re-baselines NOTHING.**
Decimal stays end-to-end (this is *less re-summation*, never a float swap); the byte-exact SMA_MACD
oracle stays the lock.

**In scope:**
- A running realised-PnL accumulator **owned by `PositionManager`** (D-01); `get_total_realized_pnl`
  returns the accumulator field instead of re-summing (D-01).
- Feeding the accumulator from the **existing close funnel** — the `realised_increment =
  position.realised_pnl - prior_realised` already computed on every closing fill in
  `portfolio.py:~529` (D-02). Captures partial **and** full closes.
- An audit (locked in writing) that `portfolio.py:~529` is the **single** path through which
  `realised_pnl` changes (D-02), plus a dedicated **equivalence regression test** (accumulator ==
  prior full re-sum) as a drift lock (D-03).
- Same `Decimal('0.00')` seed as today so the per-bar value is **byte-identical**, not merely
  `==` (D-05).

**Out of scope (behavior-preserving milestone — changes NO numbers):**
- `get_total_unrealized_pnl` and `get_total_market_value` (position_manager.py:289, :300) — these
  **must** re-sum every bar because market prices move per bar; they are NOT touched this phase
  (D-06).
- Any change to closed-position **retention/eviction** — `_closed_positions`
  (in_memory_storage.py:31) stays append-only for audit/reporting; the accumulator rides alongside
  it, never replaces it (D-07).
- Any money / float / Decimal-precision change; any oracle re-baseline.

**Gate (inherited, every wave):**
- **Gate (a):** byte-exact SMA_MACD oracle green (134 trades / `final_equity 46189.87730727451`);
  `mypy --strict` clean; determinism double-run byte-identical.
- **Gate (b):** clean W1 benchmark shows a measurable wall-clock improvement (≥5%, single timed run
  per Phase 1 D-04) vs the Phase 2 re-frozen baseline; re-freeze as the new locked reference. Peak
  memory tracked alongside.

</domain>

<decisions>
## Implementation Decisions

### Accumulator ownership
- **D-01 (PositionManager owns the accumulator):** The running total is a `Decimal` field on
  `PositionManager`; `get_total_realized_pnl()` simply returns it (no loop). Keeps the read
  co-located with position storage. The increment is fed in from `Portfolio` at the close funnel
  (Portfolio → PositionManager call), respecting the facade→manager layering (manager keeps **no**
  back-reference to the portfolio/handler). **Rejected:** Portfolio owning the field — it computes
  the increment, but `get_total_realized_pnl` lives in `PositionManager` and would have to read back
  from `Portfolio`, inverting the manager→facade dependency.

### Update funnel / capturing partial closes
- **D-02 (reuse the existing close funnel @ portfolio.py:~529):** Feed the accumulator from the
  `realised_increment = position.realised_pnl - prior_realised` already computed on **every closing
  fill** (partial + full) in `Portfolio`'s settle path (portfolio.py:~529; `prior_realised`
  captured pre-mutation at portfolio.py:~406). This is the single proven source of realised-PnL
  change — opening/scale-in fills do not change `realised_pnl`. Planning **must audit** that this is
  the *only* path through which a position's `realised_pnl` changes and lock that invariant in
  writing (mirrors Phase 2 D-04's audit-the-invariant approach). **Rejected:** recomputing the delta
  independently inside `PositionManager` — duplicates Portfolio's increment logic, creating a second
  source of truth with drift risk.

### Equivalence verification (criterion #2 — correctness lock)
- **D-03 (audit + oracle + dedicated equivalence test):** Prove "accumulator == prior re-sum at
  every bar" three ways: (1) audit + lock the D-02 single-funnel invariant in writing; (2) lean on
  the byte-exact oracle + determinism double-run; (3) add a **targeted equivalence regression test**
  asserting the accumulator equals a fresh full re-sum (value-equality `==`), as an explicit drift
  lock — mirrors Phase 2's D-09. **Rejected:** a runtime debug/assert cross-check that re-sums and
  compares on the hot path — it re-introduces exactly the O(positions) cost this phase removes
  (acceptable only if hard-gated off by default; the dedicated test is preferred and cheaper).

### Decimal byte-exactness
- **D-05 (same seed; assert value-equality):** Initialize/keep the accumulator seeded
  `Decimal('0.00')` — matching `get_total_realized_pnl`'s current seed. Because the accumulator sums
  the **same** per-position realised terms incrementally, with **no mid-sum `quantize`**, and Decimal
  addition's result exponent is the min over the same set of terms regardless of order, the per-bar
  value is **byte-identical** (not merely `==`). The equivalence test asserts value-equality (`==`),
  which is criterion #2's contract. **Rejected:** quantizing the running total on each update —
  changes precision vs today's full-precision Decimal sum and risks oracle divergence; today's code
  does **not** quantize here.

### Accumulator lifecycle
- **D-07 (per-portfolio cache; retention unchanged):** The accumulator initializes to
  `Decimal('0.00')` at `PositionManager` construction and is scoped **per-Portfolio** (each
  `Portfolio` owns its own `PositionManager` — there is no global cross-portfolio total). It is a
  **pure perf cache** of the open+closed realised sum: closed positions are **still** moved to and
  retained in `_closed_positions` (in_memory_storage.py:31) for audit/reporting — the accumulator
  does **not** change retention, eviction, or the open→closed move semantics
  (`_close_position`, position_manager.py:207–214). **Rejected:** using the accumulator to justify
  dropping closed-position retention — that is a behavior change beyond PERF-02 and would break other
  readers of `get_closed_positions` (see Deferred).

### Unrealized / market-value scope
- **D-06 (realized only — unrealized/market-value explicitly out of scope):** `get_total_unrealized_pnl`
  (position_manager.py:300) and `get_total_market_value` (position_manager.py:289) also re-sum over
  open positions every bar, but they **must** — unrealised PnL and market value depend on the
  current bar's prices, so they cannot be cached as a running total. Phase 3 touches **realized
  only**; planning must not drift into these adjacent loops.

### Opportunistic CONCERNS cleanups (criterion #3)
- **D-04 (approve-list only — propose, do not auto-apply):** No `CONCERN`/`TODO` markers are
  currently tagged in `position_manager.py` / `portfolio.py`. Any opportunistic zero-behavior in-file
  cleanup must be **proposed during planning for explicit per-item owner sign-off** before it is
  applied — planning does **not** apply cleanups autonomously. Each approved cleanup ships as a
  **separate atomic commit** with the oracle green. **Likely candidate:** collapsing the now-dead
  dual open+closed re-sum loop inside `get_total_realized_pnl` once the accumulator replaces it
  (this is intrinsic to the change, not a separate cleanup). The `float(...)` casts in
  `get_positions_summary` (position_manager.py:420–422) are a **legitimate serialization edge**, not
  a defect — leave them.

### Claude's Discretion
- Exact attribute name/type of the accumulator field and the Portfolio→PositionManager method used
  to apply the increment, within D-01 / D-02.
- Whether the D-02 invariant audit yields any defensive assert in **non-hot** paths (e.g. test-only
  helpers) — planner's call; the contract (audited + tested) is what matters, and nothing defensive
  may land on the per-bar hot path (it would burn the cycles this phase saves).
- Exact placement/shape of the equivalence regression test (D-03), within "asserts accumulator ==
  full re-sum".

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Source of truth (the spike IS the research)
- `perf/results/PERF-BASELINE-RESULTS.md` — §1 (frozen baseline 240.8 s / 167.3 MB), §2 (ranked
  hotspot map — **hotspot #3 is this phase's target**, the `get_total_realized_pnl` re-sum), §6
  (phase breakdown — "P2 — Running PnL accumulator"), §7 (exit criteria). **Authoritative.**

### Milestone scope + requirements + gate
- `.planning/REQUIREMENTS.md` — **PERF-02** (this phase) + the milestone gate (a)/(b) definition.
- `.planning/milestones/v1.5-ROADMAP.md` — Phase 3 goal + success criteria.
- `.planning/ROADMAP.md` — Phase 3 entry + v1.5 framing + the milestone behavior-preserving gate.
- `.planning/phases/01-perf-tooling-baseline/01-CONTEXT.md` — **D-04** (≥5% wall-clock, single-run)
  and the baseline/regression-guard tooling Phase 3's gate (b) uses.
- `.planning/phases/02-order-storage-indexing/02-CONTEXT.md` — precedent for the audit-the-invariant
  (D-04 there) + dedicated equivalence regression test (D-09 there) pattern reused here as D-02/D-03.

### Target code (the seam being optimized)
- `itrader/portfolio_handler/position/position_manager.py` — `get_total_realized_pnl` (line 310, the
  re-sum to replace); `get_total_unrealized_pnl` (line 300) and `get_total_market_value` (line 289)
  are the adjacent loops that stay (D-06); `_close_position` (lines 207–214, the open→closed move);
  the `float(...)` summary edge (lines 420–422). **A file this phase edits (4-space indent).**
- `itrader/portfolio_handler/portfolio.py` — the close/settle funnel where `realised_increment` is
  computed (`prior_realised` captured ~line 406; `realised_increment = position.realised_pnl -
  prior_realised` ~line 529); read-properties `total_realised_pnl` (line 243) / `total_pnl`
  (line 248). **A file this phase edits (tab indent).**

### Storage + position internals (read-only — informs the funnel/lifecycle)
- `itrader/portfolio_handler/storage/in_memory_storage.py` — `_positions` (open dict, line 29),
  `_closed_positions` (append-only list, line 31), `add_closed_position` / `remove_position` /
  `get_closed_positions` (the open→closed move target; retention stays per D-07).
- `itrader/portfolio_handler/position/position.py` — `realised_pnl` computed property (line 175),
  `close_position` (line 265, sets `is_open=False`); confirms a Position is a single record, not a
  collection.
- `itrader/portfolio_handler/base.py` — `PortfolioStateStorage` ABC (`get_closed_positions` at line
  106) — the seam stays unchanged.

### Consumers whose per-bar values must not change
- `itrader/portfolio_handler/metrics/metrics_manager.py` — `_get_realized_pnl` (line 519) reads
  `portfolio.total_realised_pnl`; snapshot fields (lines 153–168) must produce identical values.

### Gate (a) — correctness lock (held, not changed)
- `tests/integration/test_backtest_oracle.py` — byte-exact SMA_MACD oracle
  (134 / `46189.87730727451`). (Per memory `oracle-test-location`: this is the oracle; `tests/golden`
  is artifacts.)
- `tests/unit/portfolio/` — existing portfolio/position tests; the equivalence regression test (D-03)
  lands alongside.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- **The increment already exists** — `realised_increment = position.realised_pnl - prior_realised`
  is computed on every closing fill in `portfolio.py:~529` for the cash-settlement path. The
  accumulator reuses this exact value; no new delta math (D-02).
- `_close_position` (position_manager.py:207–214) is the **single** open→closed move site, and
  `process_position_update` (position_manager.py:95+) is the single per-fill entry — natural hook
  points for confirming the funnel during the D-02 audit.
- `position.realised_pnl` is a computed property (position.py:175); a Position is one record, not a
  collection — confirms there is no double-storage of closed positions to keep consistent.

### Established Patterns
- **Indentation hazard (CLAUDE.md):** `position_manager.py` uses **4 spaces**; `portfolio.py` uses
  **tabs**. Match each file exactly — do not normalize (a mixed-indentation diff breaks a tab file).
- The accumulator field lives inside `PositionManager.__init__` alongside the other Decimal
  config/precision fields (e.g. position_manager.py:80–88), seeded `Decimal('0.00')`.
- Phase 2's "audit the invariant + dedicated equivalence test, no hot-path runtime guard" approach
  (02-CONTEXT D-04/D-09) is the precedent this phase follows for correctness without re-paying the
  cost being removed.

### Integration Points
- Portfolio's settle path already calls into managers (cash_manager release/lock, position updates) —
  applying the increment to `PositionManager` is one more call on that existing path; no
  event-queue, handler, or ABC change.
- `get_total_realized_pnl`'s callers (portfolio.total_realised_pnl → metrics_manager) see the
  identical signature and an identical (byte-equal) Decimal value (D-05).

</code_context>

<specifics>
## Specific Ideas

- Accumulator **owned by PositionManager** (read-side), **fed by Portfolio's existing
  `realised_increment`** (write-side) — the natural split given where the read method and the
  increment already live (D-01 + D-02).
- Seed `Decimal('0.00')` specifically to make the per-bar result **byte-identical**, not just `==`,
  to the current re-sum (D-05) — the byte-exact oracle is the lock.
- Verification is three-layered: invariant audit + oracle/determinism + a dedicated equivalence
  regression test asserting `accumulator == full re-sum` (D-03).
- CONCERNS cleanups are **propose-for-sign-off**, not autonomous (D-04); the only intrinsic cleanup
  is collapsing the dead dual-loop inside `get_total_realized_pnl`.

</specifics>

<deferred>
## Deferred Ideas

- **Trimming closed-position retention** — using the accumulator to stop retaining
  `_closed_positions` would be a behavior change (other readers depend on `get_closed_positions`)
  and belongs in its own phase, not PERF-02 (D-07).
- **Caching `get_total_unrealized_pnl` / `get_total_market_value`** — not cacheable as a simple
  running total (price-dependent per bar); any future optimization here is a separate effort with a
  different technique (D-06). Note: these adjacent loops are the kind of per-bar re-sum a later perf
  pass could revisit, but **not** in this behavior-preserving milestone.

</deferred>

---

*Phase: 3-running-pnl-accumulator*
*Context gathered: 2026-06-24*

# Requirements: iTrader v1.5 — Backtest Performance Optimization

**Defined:** 2026-06-23
**Core Value:** A single backtest run of `SMA_MACD` on `data/BTCUSD_1d_ohlcv_2018_2026.csv`
produces correct, deterministic, cross-validated numbers. v1.5 makes that run **faster** —
profiler-ranked, oracle-gated hot-path optimizations against the frozen W1 baseline, changing the
numbers nowhere.

**Source of truth:** `perf/results/PERF-BASELINE-RESULTS.md` — the v1.5 spike's frozen baseline
(**240.8 s / 167.3 MB**), ranked hotspot map (§2), scaling curve (§3), and proposed phase
breakdown (§6). The spike IS this milestone's research.

## Milestone Gate (applies to EVERY optimization requirement)

Each optimization phase is gated on BOTH, every wave:

1. **Byte-exact oracle stays green** — `tests/integration/test_backtest_oracle.py`: SMA_MACD
   **134 trades / `final_equity 46189.87730727451`**. v1.5 re-baselines **nothing** (it is a
   behavior-preserving milestone — the perf analog of v1.2 Consolidation).
2. **Measurable, locked W1 improvement** — the W1 benchmark shows a real wall-clock and/or peak-memory
   reduction vs the frozen §1 baseline, re-frozen after the phase.

Held throughout: `mypy --strict` clean; Decimal end-to-end (no new float-for-money — every fix is
*less repeated work*, never a float swap); single UUIDv7; determinism double-run byte-identical.

## v1 Requirements

### Tooling & Baseline (TOOL) — Phase 1 prerequisite (spec §13)

- [ ] **TOOL-01**: A `make perf-*` command surface lives in the **root** Makefile (so it inherits
  `include .env` / `.EXPORT_ALL_VARIABLES`): at minimum `perf-w1`, `perf-w2`, `perf-baseline`
  (clean frozen run), `perf-profile` (Scalene).
- [ ] **TOOL-02**: The W1 runner has two modes — a clean **benchmark** mode (the gated, profiler-free
  timing run that produces the frozen number) and a **separate** Scalene `--cpu-only --html
  --program-path` **profile** command that writes a (gitignored) HTML artifact for manual review.
  Profiling NEVER wraps the timed/gated run (it would 2–5× the wall-clock and destroy the gate).
- [ ] **TOOL-04**: The W1 baseline is **re-frozen** (clean run) after TOOL-01..02 land and BEFORE any
  optimization — the locked reference every later phase is judged against. The frozen number is
  written to a committed machine-readable baseline file (`perf/results/W1-BASELINE.json`); `perf-w1`
  prints the delta vs it with a soft regression guard. Gate (b) "measurable" = **≥5% wall-clock
  improvement** (single timed run; peak memory tracked alongside).

> **TOOL-03 (cross-validation) DROPPED from v1.5 — owner decision, 2026-06-23, Phase 1 discussion.**
> v1.5 is behavior-preserving and gated on the byte-exact oracle staying green — correctness is
> proven by *invariance* (oracle), not external *agreement*. Cross-validation against other engines
> was the tool for *result-changing* milestones (v1.0/v1.4) that needed proof the *new* numbers were
> right; v1.5 produces no new numbers, so the v1.0 `tests/golden/CROSS-VALIDATION.md` evidence stays
> valid and the comparison adds no signal. (Comparing a vectorized framework to event-driven iTrader
> on *speed* is also apples-to-oranges; gate (b) is iTrader-vs-its-own-baseline.) No `perf-crossval`
> target. Revive the v1.0 force-match methodology only if a future result-changing milestone
> re-baselines numbers.

### Hot-Path Optimization (PERF) — ordered by payoff × safety (§6)

- [ ] **PERF-01**: Order-storage queries (`get_orders_by_status`, by-portfolio, active) no longer
  linear-scan the full flat `{id: order}` dict — derived secondary indexes are maintained over the
  dict, which stays the source of truth (D-20 keeps all orders for audit). The `OrderStorage`
  interface is designed for extension so a future Postgres backend satisfies the same contract.
  *(Hotspot #1, ~37% CPU.)*
- [ ] **PERF-02**: Realised PnL is maintained as a running accumulator updated on position close —
  no per-bar re-summation over all open+closed positions. *(Hotspot #3, ~13% CPU. Decimal preserved.)*
- [ ] **PERF-03**: Hot-path logging is level-gated; per-bar admission-rejection warnings are
  demoted/sampled; `debug()` calls are removed from the per-bar path. *(Hotspot #4, ~6% W1 / ~22% W2.)*
- [ ] **PERF-04**: `get_type_hints` is memoized per class in `Strategy.to_dict` — resolved once per
  class, not re-resolved on every signal snapshot. *(Hotspot #6, ~2% W1 / ~14% W2.)*
- [ ] **PERF-05**: SMA & MACD indicators compute incrementally (rolling/memoized) instead of a
  full-window `ta` rebuild every bar, reproducing `[BYTE-EXACT]` output. **Oracle-gated, done LAST.**
  *(Hotspots #2+#7, ~24% CPU — highest-care item.)*
- [ ] **PERF-06** *(optional)*: Per-tick bar-feed window `iloc` frame copies are reduced (reusable
  view / cached slice bounds), preserving the look-ahead bar-timing contract (the 7 rules in
  `feed/bar_feed.py`). *(Hotspot #5, ~4% W1 / ~22% W2 — scales with symbol count.)*

## v2 Requirements

Deferred to future milestones. Tracked, not in this roadmap.

### Persistence (the other half of Backlog 999.2 — its own next milestone)

- **PERSIST-01**: Durable PostgreSQL order storage (`PostgreSQLOrderStorage` — currently a
  `NotImplementedError` placeholder) — live-path, DB-gated, not covered by the backtest oracle.
- **PERSIST-02**: Durable PostgreSQL portfolio/signal/fill/equity state.
- **PERSIST-03**: FL-06 — SQL-injection / hardcoded-creds hardening in `SqlHandler`.

### Deferred performance work (not on the W1 hot path)

- **PERF-07**: `EthBtcPairStrategy` `_fit_beta`/`_coint_pvalue` duplicate-log-array dedup (CONCERNS
  §Perf) — strategy-level, fit-once/dormant, not measured by W1.
- **PERF-08**: O(n²)-in-symbol-count guard at n≫50 (add a 100/200-symbol scaling point) — only if
  large universes become a target; symbol axis is clean O(n) through n=50 today.

## Out of Scope

| Feature | Reason |
|---------|--------|
| Persistence / PostgreSQL storage | Split out to its own next milestone — live-path, DB-gated, not oracle-covered (different North Star) |
| General CONCERNS.md tech debt (IN-01..04, dead code, doc gaps, convention fixes) | Its own future sweep; bundling muddies the perf gate. **Exception:** opportunistic zero-behavior in-file cleanups allowed where a perf phase already edits that file (notably P2 in `position_manager.py` / `portfolio.py`), as separate atomic commits, oracle staying green |
| numpy rewrite of the money/PnL path | `Decimal` arrays are `object`-dtype → zero vectorization; money is Decimal end-to-end (LOCKED). Top-2 hotspots aren't pandas anyway |
| Threading / async parallelization of the portfolio/strategy loops | Breaks the single-writer (D-19) + determinism contracts; GIL-bound CPU work; no I/O on the hot path. Run-level multiprocessing (param sweeps) is a separate future concern |
| Re-baselining any golden | v1.5 is behavior-preserving — it changes NO numbers (analog of v1.2) |
| Matching-engine optimization | Not a hotspot at this load (§4 surprise — does not crack the top 10) |

## Traceability

Every v1 requirement maps to exactly one phase (100% coverage). See `ROADMAP.md` Phase Details and
`milestones/v1.5-ROADMAP.md` for phase goals + success criteria.

| Requirement | Phase | Status |
|-------------|-------|--------|
| TOOL-01 | Phase 1 — Perf Tooling & Baseline | Pending |
| TOOL-02 | Phase 1 — Perf Tooling & Baseline | Pending |
| ~~TOOL-03~~ | ~~Phase 1~~ — **DROPPED** (2026-06-23, owner decision; oracle proves correctness by invariance) | Dropped |
| TOOL-04 | Phase 1 — Perf Tooling & Baseline | Pending |
| PERF-01 | Phase 2 — Order-Storage Indexing | Pending |
| PERF-02 | Phase 3 — Running PnL Accumulator | Pending |
| PERF-03 | Phase 4 — Hot-Path Discipline | Pending |
| PERF-04 | Phase 4 — Hot-Path Discipline | Pending |
| PERF-05 | Phase 5 — Incremental Indicators (FRAGILE, LAST) | Pending |
| PERF-06 | Phase 6 — Bar-Feed Window Copies (OPTIONAL) | Pending |

**Coverage:**
- v1 requirements: 9 total (TOOL ×3 + PERF ×6; PERF-06 optional) — TOOL-03 dropped 2026-06-23
- Mapped to phases: 9 ✓
- Unmapped: 0 ✓

---
*Requirements defined: 2026-06-23*
*Last updated: 2026-06-23 — Phase 1 discussion: TOOL-03 (cross-validation) DROPPED (owner decision — byte-exact oracle proves correctness by invariance in a behavior-preserving milestone). 9 v1 requirements mapped to 6 phases (100% coverage). Source: `perf/results/PERF-BASELINE-RESULTS.md` §6.*

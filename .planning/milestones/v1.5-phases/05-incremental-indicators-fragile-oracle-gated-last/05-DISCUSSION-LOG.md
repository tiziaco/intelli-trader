# Phase 5: Stateful Indicators + Shared Bar Cache - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-06-24
**Phase:** 5-Stateful Indicators + Shared Bar Cache (FRAGILE, oracle RE-BASELINED, LAST)
**Areas discussed:** G2 EMA/MACD seeding, G1 update-trigger seam, Re-baseline lock + ROADMAP reconcile, G3/G4/G5 disposition, ta-convergence test oracle, EMA/RSI conversion scope, reset()+causal guard, live-backfill interface, eval/update seam, IndicatorHandle data-access model, shared-cache scope, per-symbol/per-pair fan-out, per-symbol readiness, missing/gap bars, multi-pair keying, handler loop, lazy fan-out init, update() signature

---

## G2 — EMA/MACD seeding (the re-baseline driver, BLOCKER)

| Option | Description | Selected |
|--------|-------------|----------|
| Seed-from-first-value (adjust=False) | y[0]=x[0] seeded once; matches ta + Nautilus + LEAN; keeps §10.H ta-convergence test valid | ✓ |
| SMA-seed | TradingView/StockCharts MACD convention; diverges further, breaks ta-convergence test | |

**User's choice:** Seed-from-first-value (P5-D04).

| Option (SMA) | Description | Selected |
|--------|-------------|----------|
| Fresh windowed-sum from cache (Nautilus) | numerically stable, bounded error, O(period), matches today's approach | |
| Running-sum O(1) (LEAN) | strict O(1), float error accumulates unbounded (negligible on golden) | ✓ |
| Kahan-compensated running-sum | O(1) + bounded error, more code, not framework-default | |

**User's choice:** Running-sum O(1) — LEAN (P5-D05). **Notes:** User initially leaned toward correctness/windowed-sum, then after the full tradeoff (efficiency vs unbounded drift) chose strict O(1)/LEAN idiom; the ~1e-9 drift is negligible on the daily golden path.

| Option (readiness) | Description | Selected |
|--------|-------------|----------|
| Per-indicator is_ready = count >= min_period | Nautilus initialized / LEAN IsReady; warmup=100 preserved; value-drift only | ✓ |
| Re-derive with convergence buffer | shifts firing tick → behavioral re-baseline | |

**User's choice:** Per-indicator is_ready (P5-D06).

---

## G1 — Update-trigger seam scope

| Option | Description | Selected |
|--------|-------------|----------|
| Interface + golden-collapsed impl (defer real consolidator) | seam defined, golden 1d=base=every-tick, full consolidator deferred | ✓ |
| Build the full consolidator now | larger scope, no current consumer needs it | |
| Discuss seam placement first | | |

**User's choice:** Option 1 (P5-D16b). **Notes:** User asked for the deferred consolidator to be captured as a to-do (not buried in roadmap) — created `.planning/todos/multi-timeframe-consolidator.md`.

---

## Re-baseline lock + ROADMAP reconcile

| Option | Description | Selected |
|--------|-------------|----------|
| Reuse cross-val gate; freeze new values; behavioral-set change needs corroboration | backtesting.py+backtrader 1% tol; trade dates expected identical | ✓ |
| Stricter: trade set byte-identical, only numbers move | could block on legit ULP flip | |
| Discuss further | | |

**User's choice:** Reuse cross-val gate (P5-D02).

| Option (docs) | Description | Selected |
|--------|-------------|----------|
| Capture in CONTEXT + update ROADMAP/PROJECT/STATE this session | keeps docs truthful | ✓ |
| Capture in CONTEXT only; defer doc edits | roadmap stays self-contradictory | |

**User's choice:** Update docs this session (P5-D01).

---

## G3 / G4 / G5 disposition

| Option | Description | Selected |
|--------|-------------|----------|
| G3+G4 confirm as settled (record, no further discussion) | spec §10.B fully specifies both | ✓ |
| Discuss one or both further | | |

**User's choice:** Confirm settled (P5-D15 for G4; G3 in P5-D13).

| Option (G5) | Description | Selected |
|--------|-------------|----------|
| Unify — one per-symbol pass feeds both | removes redundant traversal | ✓ |
| Keep two passes | | |
| Defer to plan-phase | | |

**User's choice:** Unify (P5-D16a). **Notes:** User initially unclear on G5 ("create a bar event per symbol?") — clarified it's ONE BarEvent/tick with a dict payload; the issue is a duplicated per-symbol traversal, not duplicated events.

---

## ta-convergence test oracle

| Option | Description | Selected |
|--------|-------------|----------|
| Assert post-warmup, generous abs+rel tol (~1e-9/1e-6) | proves convergence not byte-exactness | ✓ |
| Tight tol from bar 0 | fails on legit seed transient | |

**User's choice:** Generous post-warmup tol (P5-D17). Coverage: **all four indicators** (vs only SMA/MACD).

---

## EMA/RSI oracle-dark conversion scope

| Option | Description | Selected |
|--------|-------------|----------|
| Convert all four; re-baseline EMA/RSI unit tests | uniform stateful surface, live parity | ✓ |
| Convert only SMA/MACD; leave EMA/RSI on ta | mixed catalog | |

**User's choice:** Convert all four (P5-D12); bless EMA/RSI via ta-convergence (ta batch IS their reference), no external cross-val.

---

## reset() + causal-guard surface

| Option | Description | Selected |
|--------|-------------|----------|
| Build reset() now | sweep-readiness seam, cheap | ✓ |
| Defer reset() to optimizer phase | retrofitting error-prone | |

**User's choice:** Build reset() now (P5-D19).

| Option (causal) | Description | Selected |
|--------|-------------|----------|
| Build causal flag + guard now | structural look-ahead fence | ✓ |
| Defer guard | loses fence when ML indicators land | |

**User's choice:** Build causal guard now (P5-D20).

---

## Live-backfill-through-update interface

| Option | Description | Selected |
|--------|-------------|----------|
| No bulk-warmup; backfill through update(bar) | single code path | |
| Allow bulk warmup_from(series) | second divergent path | |
| Defer entirely | | ✓ |

**User's choice:** Defer (P5 Deferred). **Notes:** User asked to track via a to-do AND add a ROADMAP backlog item (N+4). Created `.planning/todos/live-backfill-through-update.md` + N+4 backlog entry.

---

## evaluate/update seam contract

| Option | Description | Selected |
|--------|-------------|----------|
| Push-latest-bar for handle strategies; shared-cache read for frame-needers | keeps a needs-window distinction | |
| Fully remove frame access (Option B) — migrate fixtures + pair off self.bars | uniform contract, no self.bars | ✓ |

**User's choice:** Option B, precisely scoped (P5-D13/D13a). **Notes:** User judged B "more correct architecturally and more efficient." Scoped: B removes the per-tick self.bars SLICE (not multi-bar reads, which become explicit cache reads); pair migrated by G4 regardless; only net-extra = migrate zero-handle count/date fixtures preserving firing.

---

## IndicatorHandle data-access model

| Option | Description | Selected |
|--------|-------------|----------|
| Model B — feed-centric (Nautilus/LEAN), amend spec §10.H | indicators hold own minimal buffers, no cache ref | ✓ |
| Model A — cache-centric (keep spec §10.H) | indicators inject cache, couples to it | |
| Discuss further | | |

**User's choice:** Model B (P5-D07/D08). **Notes:** User asked "what's most correct + what do frameworks do" — both Nautilus + LEAN feed the indicator and let it hold its own buffer; do NOT read shared cache. Also clarified computation stays incremental in BOTH models (axis 1 = incremental vs recompute; axis 2 = where the evicting-value lookup lives). Amends spec §10.H/§10.G (P5-D22).

---

## Shared-cache ownership + scope

| Option | Description | Selected |
|--------|-------------|----------|
| BarFeed owns; newest-bar + interface now, defer deep multi-bar cache | smallest correct Plan A under Model B | ✓ |
| Build full deep capacity-derived cache now | speculative, nothing reads it | |
| Standalone injected read-model | deviates from §4.1 | |

**User's choice:** Option 1 (P5-D16). **Notes:** User confirmed after asking whether multi-instrument still works (it does — orthogonal to cache scope). Asked to track the deferred deep cache as a to-do → `.planning/todos/deep-shared-bar-history.md`.

---

## Per-symbol/per-pair fan-out

| Option | Description | Selected |
|--------|-------------|----------|
| Framework auto-fans-out per symbols (LEAN/Nautilus) | author declares once, framework instantiates per-symbol | ✓ |
| Author declares per-symbol explicitly | more boilerplate | |

**User's choice:** Framework auto-fan-out (P5-D10). **Notes:** Surfaced by the user's question "will I still trade multiple instruments/pairs in one strategy?" — exposed that stateful indicators REQUIRE per-symbol state (the stateless per-tick recompute hid this). Core Plan B/C requirement for the user's multi-instrument benchmark.

---

## Per-symbol readiness gating

| Option | Description | Selected |
|--------|-------------|----------|
| Independent per-symbol warmup | each symbol warms from its own first bar | ✓ |
| Strategy-global warmup | stalls early-ready symbols | |

**User's choice:** Independent per-symbol (P5-D10b).

---

## Missing/gap-bar handling

| Option | Description | Selected |
|--------|-------------|----------|
| No bar → no update; readiness counts real bars only (Nautilus/LEAN) | causality-safe; fill-forward belongs at feed layer | ✓ |
| Forward-fill at the indicator | injects non-real data, bypasses feed look-ahead ownership | |

**User's choice:** No-update-on-missing (P5-D10c). **Notes:** User asked what frameworks do — both Nautilus + LEAN update only on real bars; LEAN's fill-forward is a FEED-level opt-in, never the indicator.

---

## Multi-pair fan-out keying

| Option | Description | Selected |
|--------|-------------|----------|
| Pattern 1 — per-pair state keyed by pair identity; defer Pattern 2 with to-do | dominant framework pattern, no new abstraction | ✓ |
| Pattern 1 only, no to-do | | |
| Pattern 2 — synthetic-spread instrument now | scope creep (§2 non-goal) | |

**User's choice:** Pattern 1 + defer Pattern 2 (P5-D10). **Notes:** User asked what frameworks do — both patterns exist (keyed dict vs synthetic instrument); Pattern 1 dominant + in-scope. Created `.planning/todos/synthetic-spread-instrument.md`.

---

## strategies_handler loop restructure

| Option | Description | Selected |
|--------|-------------|----------|
| Lock the shape; planner fills mechanics | record the contract | ✓ |
| Defer entirely to planner | | |

**User's choice:** Lock the shape (P5-D14).

---

## Per-symbol handle instantiation

| Option | Description | Selected |
|--------|-------------|----------|
| Lazy — instantiate on first bar | dynamic-universe-ready | ✓ |
| Eager — from declared symbols at init | static-universe assumption | |

**User's choice:** Lazy (P5-D10a).

---

## update() signature (multi-input)

| Option | Description | Selected |
|--------|-------------|----------|
| Lock: update(bar) single-input; pair takes both legs | multi-input first-class | ✓ |
| Leave entirely to planner | | |

**User's choice:** Lock the shape (P5-D09).

---

## Claude's Discretion

Left to /gsd:plan-phase (P5-D-discretion): exact IndicatorHandle method signatures, per-symbol handle-storage container type, mypy --strict generics on the adapter Protocol, pair-z running-moments-vs-recompute sub-choice, Plan A/B/C task-boundary breakdown.

## Deferred Ideas

- Full multi-timeframe consolidator → `.planning/todos/multi-timeframe-consolidator.md`
- Deep capacity-derived multi-bar shared cache → `.planning/todos/deep-shared-bar-history.md`
- Live backfill through update(bar) → `.planning/todos/live-backfill-through-update.md` + ROADMAP N+4 backlog item
- Synthetic/spread instrument (multi-pair Pattern 2) → `.planning/todos/synthetic-spread-instrument.md`
- Per-bar logging (~22% W2) — adjacent, out of scope, separate quick task (spec §10.C)

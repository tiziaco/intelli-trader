# Phase 6: Bar-Feed Window Copies (OPTIONAL, slip-able) - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-06-24
**Phase:** 6-bar-feed-window-copies-optional-slip-able
**Areas discussed:** Copy-reduction mechanism, View-aliasing safety, Path scope, Gate (b) verdict (W1 vs W2), W2 record, Empty-window edge, View-construction approach, Drift/equivalence test design, Master-frame immutability

---

## Copy-reduction mechanism (D-01)

| Option | Description | Selected |
|--------|-------------|----------|
| View-primary (+ cheap caching) | Replace `frame.iloc[start:pos]` data copy with a read-only view; memoize `_offset_alias`; `searchsorted` stays | ✓ |
| View + cursor bounds | Also replace `searchsorted` with a monotonic per-(ticker,tf) cursor | |
| Bounds-only (keep copy) | Cache alias + bounds but still copy via `.iloc` | |

**User's choice:** View-primary (+ cheap caching)
**Notes:** Attacks the actual named cost (the per-tick frame copy); `searchsorted` is microsecond-class and left alone. `window()` keeps returning a DataFrame.

---

## View-aliasing safety (D-02)

| Option | Description | Selected |
|--------|-------------|----------|
| Hard read-only + audit + test | Enforce read-only at the feed boundary so mutation raises loudly; + audit + drift test; no global flag | ✓ |
| Global pandas Copy-on-Write | Flip `pd.options.mode.copy_on_write` process-wide | |
| Audit + drift test only | Rely on verified read-only consumers, no runtime guard | |

**User's choice:** Hard read-only + audit + test
**Notes:** Mutation must fail loudly at source, not silently poison future ticks. Implementation consolidated into D-09 (enforce at master-frame build). Researcher verifies `writeable=False` doesn't break `ta` reads; fall back if it does.

---

## Path scope (D-03)

| Option | Description | Selected |
|--------|-------------|----------|
| `window()` only | Oracle-relevant + symbol-count-scaling path; megaframe inherits the view free | ✓ |
| `window()` + `megaframe()` | Also rework megaframe's concat | |

**User's choice:** `window()` only
**Notes:** `megaframe()` is a deferred screener subsystem; `current_bars()` already de-pandas'd.

---

## Gate (b) verdict (W1 vs W2) (D-04)

| Option | Description | Selected |
|--------|-------------|----------|
| W2 shows win + W1 non-regress | Judge gate (b) on the perf-w2 sweep; W1 must not regress; re-freeze W1 | ✓ |
| Hold standard ≥5% W1 bar | Apply the same ≥5% W1 bar; phase slips if it can't pass | |
| Soft: W1 non-regress + any W2 win | No hard % threshold | |

**User's choice:** W2 shows win + W1 non-regress
**Notes:** PERF-06 is ~4% W1 / ~22% W2 — below the W1-only ≥5% bar by design; success criterion says "most visible in W2 sweep."

---

## W2 record (D-05)

| Option | Description | Selected |
|--------|-------------|----------|
| Commit W2 baseline + ≥10% bar | Capture perf-w2 --json before/after, commit W2-BASELINE.json (50-sym), require ≥10% at 50 symbols; seeds Phase 5 | ✓ |
| Record before/after only, no threshold | Evidence in artifacts only, no standing baseline | |
| You decide (planner) | Leave mechanism + threshold to planner | |

**User's choice:** Commit W2 baseline + ≥10% bar
**Notes:** Gives a reproducible, thresholded verdict and seeds a W2 baseline for Phase 5 (incremental indicators, also W2-relevant, runs after this).

---

## Empty-window edge (D-06)

| Option | Description | Selected |
|--------|-------------|----------|
| Short-circuit empty, return as today | Empty slice carries no copy cost / no aliasing risk → bypass view machinery, return `frame.iloc[pos:pos]` unchanged | ✓ |
| Uniform view path | Route empty windows through the same view + writeable path | |

**User's choice:** Short-circuit empty, return as today
**Notes:** Preserves byte-identical empty semantics for the `base.py:347` empty-window guard; sidesteps `writeable=False`-on-empty.

---

## View-construction approach (D-07)

| Option | Description | Selected |
|--------|-------------|----------|
| Set direction, researcher pins API | Direction: slice existing frame + mark read-only, preserve dtype/tz-index/columns (not reconstruct via new DataFrame); researcher pins exact pandas 2.3.3 API + ta compat, byte-identity the constraint | ✓ |
| Pin exact API now | Decide the precise call in discussion | |
| Fully defer | Leave both direction and API to research/planning | |

**User's choice:** Set direction, researcher pins API

---

## Drift/equivalence test design (D-08)

| Option | Description | Selected |
|--------|-------------|----------|
| All three: content + mutation + contract | (a) content equivalence vs old copy; (b) mutation raises + no master leak; (c) 7-rule contract tests green; in tests/unit/price_handler/feed/ | ✓ |
| Content + contract only | Skip the mutation/no-leak assertion | |
| You decide (planner) | Leave assertions + placement to planner | |

**User's choice:** All three: content + mutation + contract

---

## Master-frame immutability (D-09)

| Option | Description | Selected |
|--------|-------------|----------|
| Enforce at source (marks subsume view safety) | Mark master frames read-only at build → views inherit non-writeable buffers AND master mutation fails loudly; one mechanism implements D-02 too | ✓ |
| Audit + test only | Document the invariant, cover via drift test, no marking | |

**User's choice:** Enforce at source
**Notes:** Elegantly unifies the view-safety mechanism (D-02) with the immutability invariant. Researcher confirms it doesn't break resample/ta reads, else fall back to per-view marking.

---

## Claude's Discretion

- Exact pandas 2.3.3 view-construction API and the precise master-frame mark-read-only site (D-07/D-09), within the locked direction + byte-identity + ta/resample compatibility.
- Shape/placement of the `_offset_alias` memoization (D-01).
- Exact placement/shape of the drift/equivalence test within the D-08 three-assertion contract.
- Whether to add a `--check`/`--baseline-out` flag to `perf-w2` to mechanize the D-05 ≥10% verdict.

## Deferred Ideas

- `megaframe()` / screener concat optimization → revisit with the production screener (N+4).
- Monotonic per-(ticker,tf) cursor replacing `searchsorted` → microsecond gain, not worth the state now.
- Removing in-strategy/adapter re-slicing (`catalog.py` `bars[start_dt:]`) → byte-identity risk, future non-byte-exact cleanup.

---

# PIVOT SESSION — 2026-06-24 (post Gate-(b) profile)

**Trigger:** `06-PROFILE-FINDINGS.md` — 06-01's view/alias measured ~0% W2; real hotspot is per-tick
`searchsorted` (13.2%) + `iloc` slice (7.9%). Re-discussed to pivot the mechanism.
**Areas discussed:** Gate (b) realism, Fallback if cursor falls short, Cursor change scope, 06-01
disposition, W1 re-baseline + non-regression, Defensive correctness guard.

## Gate (b) realism / denominator cleanup (D-13/D-14)

| Option | Description | Selected |
|--------|-------------|----------|
| Clean denominator first | Remove per-bar TIME-EVENT debug log + de-time tracemalloc/synth-gen; re-baseline; gate ≥10% on cleaned engine | ✓ |
| Keep ≥10% on raw sweep | Gate on full diluted wall-clock | |
| Lower threshold | Drop to ≥5% on raw sweep | |

**Follow-up:** user confirmed the per-bar log is DEBUG (`full_event_handler.py:116`, eager f-string
discarded at INFO) and chose to **remove it completely** (not just disable during the timed run).
Sub-decision: **remove log → re-baseline → gate the cursor alone** (isolate the cursor's win), not a
combined-win gate.

## Fallback if cursor falls short (D-15)

| Option | Description | Selected |
|--------|-------------|----------|
| Ship as correctness+modest-perf, re-frame gate (b) | Record actual W2 %, re-frame to "measurable W2 win + W1 non-regress" | ✓ |
| Slip the whole phase | Revert/park, defer Phase 6 | |
| Keep iterating | Chase more hotspots until ≥10% | |

## Cursor change scope (D-10/D-11)

| Option | Description | Selected |
|--------|-------------|----------|
| Searchsorted only (slice as stretch) | Cursor replaces searchsorted; iloc slice only if needed | |
| Cursor + slice together | Cursor for bounds AND cheaper slice path for the 7.9% iloc | ✓ |
| Searchsorted only, slice never | Leave iloc exactly as 06-01 | |

## 06-01 disposition (D-12)

| Option | Description | Selected |
|--------|-------------|----------|
| Keep as foundation | Cursor builds on 06-01's read-only master frames + view; D-08 drift test carries | ✓ |
| Revert 06-01 first | Rebuild window path clean from base | |

## W1 re-baseline + non-regression (D-14)

| Option | Description | Selected |
|--------|-------------|----------|
| Re-freeze on cleaned engine, then non-regress | Re-freeze W1 post-cleanup; cursor held to ±5% soft band; cool machine | ✓ |
| Single end re-freeze | One re-freeze after cursor, no intermediate | |
| Require W1 improvement too | Hold cursor to an actual W1 win | |

## Defensive correctness guard (D-16)

| Option | Description | Selected |
|--------|-------------|----------|
| Dedicated test only (extend D-08) | Assert cursor (start,pos) == fresh searchsorted + no-future-bar invariant | ✓ |
| Test + optional debug-flag runtime assert | Add opt-in runtime check off by default | |
| Runtime assert always on | Verify every tick (re-pays searchsorted) | |

**Skipped (folded as carry-forward defaults, not separate decisions):** cursor reset/non-monotonic
semantics (→ safe rebuild via searchsorted, never leak a future bar — D-10); plan split/sequencing
(→ planner's call).

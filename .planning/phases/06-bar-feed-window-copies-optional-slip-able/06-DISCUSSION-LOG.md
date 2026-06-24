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

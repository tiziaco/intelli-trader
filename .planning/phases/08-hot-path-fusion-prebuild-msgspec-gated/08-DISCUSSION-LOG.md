# Phase 8: Hot-Path Fusion, Bar Prebuild & msgspec Migration - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-06-25
**Phase:** 08-hot-path-fusion-prebuild-msgspec-gated
**Areas discussed:** msgspec migration scope, keep-only-measured recording, A/B sequencing, Req 1 fusion shape, Req 2 Position cache, Req 4 to_dict cache granularity, Req 4 live-setter risk

---

## msgspec migration scope (Req 6)

| Option | Description | Selected |
|--------|-------------|----------|
| Spike scope only (8 files) | Bar + Event hierarchy only; Position stays mutable dataclass | |
| Expand to whole hot path | Also Position + matching decision structs | |
| **Owner-refined: events+Bar + genuine DTOs, EXCLUDE Position** | Bar + Event hierarchy + FillDecision/CancelDecision/SignalRecord/Transaction/TrailState; Position excluded as wrong shape | ✓ |

**User's choice:** Started leaning "expand to whole hot path," then asked a clarifying question — "are
we talking DTOs, or stateful classes like Position? Is the improvement substantial? Is this a good
msgspec fit?" After analysis, refined to: convert all genuine DTOs/value objects now ("since we're
already working on this feature, do it all now"), but **exclude Position**.
**Notes:** Position established as the canonical wrong-fit: (1) mutable stateful aggregate built once
per position open, not a high-freq immutable DTO; (2) its ~7.3% cost is property recompute (owned by
Req 2), not construction; (3) frozen Struct would collide with Req 2's mutable cache. User confirmed
including the DTOs after verifying msgspec is a good fit and does not compromise reliability (used as a
construction container only — no encode/decode — so Decimal money discipline is untouched; every
conversion oracle-gated).

## Keep-only-measured recording (Req 6)

| Option | Description | Selected |
|--------|-------------|----------|
| Treat extra DTOs as a perf change | Subject to per-change A/B; revert if noise | |
| **events+Bar = headline measured win; extra DTOs = consistency layer** | events+Bar A/B-attributed (+3.82% W1 / +6.72% W2@50); extra DTOs converted for uniformity under byte-exact gate, NOT reverted for noise-level A/B | ✓ |

**User's choice:** Accepted recording the extra DTOs as a consistency refactor carved out of
keep-only-measured, with events+Bar remaining the headline measured win.
**Notes:** Resolves the executor-facing contradiction ("convert → A/B is noise → discipline says
revert"). The extra DTOs fire at ~1,578/run (≈4% of ~69k Bar volume) so their isolated A/B delta lands
in noise. Honesty note recorded: SignalRecord's profiled hotspot is its to_dict (Req 4), not msgspec.

## A/B sequencing

| Option | Description | Selected |
|--------|-------------|----------|
| **5 wins first, then msgspec layer** | Land + A/B Reqs 1-5, cool re-freeze, then msgspec as measured second layer with fresh A/B | ✓ |
| Combined, single A/B + re-freeze | All six at once, one A/B, one re-freeze | |
| You decide | Delegate to planning | |

**User's choice:** 5 wins first, then msgspec layer.
**Notes:** Spike code was discarded (only findings doc kept), so msgspec is re-implemented cleanly and
gets its own fresh A/B rather than inheriting the spike branch's number.

## Req 1 fusion shape

| Option | Description | Selected |
|--------|-------------|----------|
| **Fused method in position_manager** | Single-pass valuation returns the 3 Decimals; public accessors delegate; portfolio_handler asks for margin basis | ✓ |
| Keep margin loop in portfolio_handler | Fuse only market-value + unrealised-PnL; stays 2 passes | |
| You decide | Delegate to planning | |

**User's choice:** Fused method in position_manager.
**Notes:** Keeps position iteration in one owner; the only cross-component change in the phase.

## Req 2 Position cache

| Option | Description | Selected |
|--------|-------------|----------|
| **Explicit fields + invalidate on fill** | _net_quantity_cache / _avg_price_cache reset-on-fill; fill-invalidation unit test; Position stays mutable | ✓ |
| cached_property + __dict__ eviction | Descriptor-based; awkward for a non-dataclass | |
| You decide | Delegate to planning | |

**User's choice:** Explicit fields + invalidate on fill.

## Req 4 to_dict cache granularity

| Option | Description | Selected |
|--------|-------------|----------|
| Per-class cache | Would leak one instance's declared values into another — correctness bug | |
| **Per-instance lazy static cache** | Cache static portion per instance; refresh only is_active + subscribed_portfolios per call; byte-identical via in-place key overwrite; snapshot-drift test | ✓ |

**User's choice:** Discussed in depth, then locked per-instance.
**Notes:** Verified the exhaustive runtime-mutable set is exactly `is_active` (base.py:856/859) and
`subscribed_portfolios` (846/853); all other snapshot fields are set-once in `__init__` with no setter.
Per-class rejected on correctness grounds (instances differ in declared values).

## Req 4 live-setter risk (forward-looking)

| Option | Description | Selected |
|--------|-------------|----------|
| **Cache + documented invalidation hook** | ~2-line _invalidate_to_dict_cache() seam (never called in backtest), so future live param-setters have a safe place to invalidate | ✓ |
| Cache only, defer the whole concern | Plain cache + documented assumption; build the seam later | |

**User's choice:** Cache + documented invalidation hook.
**Notes:** User raised that live trading will add setters to modify strategy params (possibly
Postgres/NoSQL-backed). The hook is cheap insurance against a silent live-mode desync; captured as a
Deferred Idea for the Live milestone.

---

## Claude's Discretion

- Req 3 (itertuples bar prebuild) — mechanical `iterrows` → `itertuples`/vectorized swap, D-14
  Decimal-via-string contract preserved, field-for-field equivalence test. Planner's shape.
- Req 5 (check_aligned precompute) — bounded `@functools.lru_cache(maxsize=N)` per Phase 7 D-01;
  researcher pins `N`.
- `gc=False` per-DTO (only where reference-cycle-free); `Transaction`/`TrailState` mutability check
  before conversion; exact fused-method signature and cache-field naming.

## Deferred Ideas

- Live strategy-param setters / Postgres-NoSQL-backed params must invalidate (or bypass) the `to_dict`
  static cache — wire the actual invalidation when live param-setters are designed (N+3b / N+4).
- msgspec conversion of any residual hot-path dataclass NOT in this phase — revisit only if a future
  re-profile shows a construction (not recompute) hotspot on a genuinely DTO-shaped object.
- Whole-hot-path A/B re-measurement at larger symbol universes (>10 symbols) — informational; the
  INCLUDE decision already stands.

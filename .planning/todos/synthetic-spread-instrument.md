---
status: open
created: "2026-06-24"
source: surfaced in v1.5 Phase 5 discuss-phase (multi-pair fan-out keying; framework Pattern 2)
tags: [strategy, pairs, spread, synthetic-instrument, fan-out, unification, deferred, §2-non-goal, §6]
resolves_phase: ""
---

# Synthetic / spread instrument as a first-class trading unit (multi-pair unification)

**Origin:** Surfaced in v1.5 Phase 5 (Stateful Indicators + Shared Bar Cache) discuss-phase while
deciding multi-pair fan-out keying. Phase 5 locked **Pattern 1** — per-pair state keyed by a
canonical `(legA, legB)` identity in a `{pair_key: PairState}` dict (the dominant Nautilus/LEAN/
zipline pairs-algo pattern; no new abstraction). This todo captures the deferred **Pattern 2**.

**Design of record:** `docs/superpowers/specs/2026-06-24-stateful-indicator-design.md` §2 (non-goal:
"a first-class Instrument abstraction" beyond what exists), §6 NOTE (Instrument is already
first-class via `core/instrument.py` + `universe/instruments.py::derive_instruments`; further
unifications framed as "possible future, out of scope"). Pattern 2 is one such future unification.

## The idea (Pattern 2)
Model each pair/spread as its OWN first-class synthetic instrument with its own InstrumentId,
bars, and indicators (Nautilus `SyntheticInstrument` / LEAN composite symbols). Then **multi-pair
collapses into multi-instrument** — the per-symbol stateful-indicator fan-out Phase 5 builds
handles it uniformly, with NO separate per-pair keying mechanism. The spread series flows through
the same `update(bar)` indicator path as any single instrument.

## Why deferred
- Requires a new **synthetic-instrument abstraction** (derive a spread instrument, its bar
  synthesis from leg bars, its InstrumentId, look-ahead-safe bucketing) — explicitly a Phase 5
  non-goal (§2). Building it on the oracle-gated FRAGILE phase is scope creep / added risk.
- Pattern 1 already delivers correct multi-pair trading with no new abstraction.

## When to schedule
A future strategy/architecture milestone, ideally alongside any broader Instrument/Cache
unification (§6's "one Nautilus-style Cache over both bars and instruments"). Natural fit once
multi-pair / stat-arb universes grow and the per-pair dict pattern starts to feel like it's
re-implementing per-instrument fan-out.

## Tie-in
- The per-symbol stateful-indicator fan-out (Phase 5) is the mechanism Pattern 2 would reuse.
- Related deferrals: `deep-shared-bar-history.md`, `multi-timeframe-consolidator.md` — a synthetic
  spread instrument would also register lookbacks/timeframes through the same consumer-registration
  path.

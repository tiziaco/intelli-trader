---
status: open
created: "2026-07-06"
source: surfaced in v1.7 Phase 7 discuss-phase (WR-02 readiness-gate state home; LEAN Security model)
tags: [instrument, universe, readiness, mutable-state, refactor, naming, deferred, phase-7-tie-in]
resolves_phase: ""
---

# Refactor `Instrument` split: immutable definition vs mutable runtime state (+ rename `TrackedInstrument`)

**Origin:** Surfaced in v1.7 Phase 7 (Live Dynamic-Universe Hardening) discuss-phase while deciding
where the WR-02 per-symbol **readiness** state (`pending`/`ready`/`failed`) should live. Phase 7
locks the **LEAN `Security` model**: `Universe` stores one `dict[str, TrackedInstrument]` per member,
where `TrackedInstrument` (mutable, NOT frozen) wraps the existing frozen `Instrument` by reference
and adds the runtime `readiness` + `leaving` fields. `Instrument` itself is left **untouched** this
phase (still `@dataclass(frozen=True, slots=True, kw_only=True)`, `core/instrument.py`).

## The deferred refactor
1. **Rename `TrackedInstrument`.** The Phase-7 name is a placeholder. Rename it as part of the
   broader refactor (candidates discussed: `UniverseMember`, `InstrumentEntry`, or fold into an
   explicit immutable-`Instrument` + mutable-`InstrumentState` pair).
2. **Move the *conceptually time-varying* fields off the frozen `Instrument` into a mutable
   per-symbol market-data/state object.** Phase-7 field audit found these are static approximations
   of values that actually change over time on a live venue:
   - `borrow_rate` — its own docstring calls it a *"static-over-time approximation"*; borrow rates
     float continuously on real venues. **Clearest case.**
   - `maintenance_margin_rate` — **tiered by notional** on OKX + venue-revised; modeled as a scalar.
   - `max_leverage` — also tiered by notional + venue-adjustable.
   - `liquidation_fee_rate` — venue-set fee, semi-static/adjustable.
   The genuinely static definition fields stay on the immutable `Instrument`: `symbol`,
   `price_precision`, `quantity_precision`, `quote_currency`, `min_order_size`, `settles_funding`.

## Why deferred (not done in Phase 7)
- Moving the risk/carry params is a **margin/carry-model change** with real consumers (liquidation
  math, short-carry accrual) — a different concern from "universe readiness hardening." Doing it
  under cover of the readiness gate would be scope creep on an oracle-gated milestone.
- Phase 7 only needs the *membership-runtime* fields (`readiness`, `leaving`) in the mutable wrapper;
  the venue risk params stay static-per-run approximations (oracle-dark, `borrow_rate` defaults to 0).

## When to schedule
When live margin trading needs **real venue risk tiers / a live funding-and-borrow feed** — those
fields graduate from `Instrument` into a mutable per-symbol market-data object fed by the venue,
and `TrackedInstrument` gets its permanent name. Natural fit alongside the live-margin / N+5 work.

## Tie-in
- Phase 7 `TrackedInstrument` (`itrader/universe/universe.py`, wrapping `core/instrument.py::Instrument`)
  is the seam this refactor extends — the mutable wrapper already exists; this just moves more fields
  into it and renames.
- Related: `synthetic-spread-instrument.md` (both touch a broader Instrument/Cache unification, §6).

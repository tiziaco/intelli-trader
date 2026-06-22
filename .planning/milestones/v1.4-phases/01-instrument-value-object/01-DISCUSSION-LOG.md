# Phase 1: Instrument Value Object - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-06-15
**Phase:** 1-Instrument Value Object
**Areas discussed:** min_order_size ownership, Behavioral-gate aggressiveness, Registry/Universe seam, Inference guard & defaults

---

## min_order_size ownership

| Option | Description | Selected |
|--------|-------------|----------|
| Instrument owns, EL fallback | Instrument is source of truth; ExchangeLimits demoted to venue fallback for undeclared symbols. BTCUSD leaves it undeclared → falls through to EL(0.001), byte-exact. | ✓ |
| Keep in ExchangeLimits | Instrument carries precision + margin only; min_order_size stays venue-level. Contradicts INST-01/03. | |

**User's choice:** Instrument owns, ExchangeLimits fallback.
**Notes:** Follows authoritative REQUIREMENTS over the older design note. BTCUSD undeclared → EL(0.001) keeps the oracle byte-exact.

---

## Behavioral-gate aggressiveness

| Option | Description | Selected |
|--------|-------------|----------|
| Rewire quantize now | quantize() resolves precision via Instrument; _INSTRUMENT_SCALES deleted; fully meets INST-01. | ✓ |
| Metadata-only, defer rewire | Land Instrument but leave quantize/_INSTRUMENT_SCALES until Phase 2. Leaves a parallel table + value object. | |

**User's choice:** Rewire quantize now.
**Notes:** Surfaced during scout that quantize() is only called from tests today, so the rewire's production blast radius is near-zero; BTCUSD declared-8dp stays byte-identical.

---

## Registry / Universe seam

| Option | Description | Selected |
|--------|-------------|----------|
| Registry seam in core/money | Module-level registry in money.py. | (rejected by user) |
| Global singleton in __init__ | `instruments` registry alongside config/idgen. | |
| Injected read-model | quantize takes an Instrument; injected registry resolves the symbol. | (evolved) |
| **Universe is the home** | No separate registry, no state in money.py. Universe upgraded to symbol→Instrument; Instrument type in core/instrument.py; quantize stays pure taking an Instrument. | ✓ |
| Universe **class** (composition façade) | Introduce a `Universe` class as the injectable read-model, composing the existing pure `derive_membership`/`is_active` (not a rewrite) + a new `derive_instruments` map. | ✓ |

**User's choice:** Universe is the home; introduce a `Universe` class via the composition-façade approach.
**Notes:** User rejected an instrument registry inside money.py ("money.py's job is the rounding mechanism") and rejected a standalone InstrumentRegistry as a parallel source of truth for the symbol set the universe already owns (D-20/D-21). User asked whether to introduce a proper `Universe` class and upgrade `derive_membership`; agreed on composition (keep the pure functions as helpers the class delegates to) so `.members` stays byte-exact and Trap-4 wiring order is untouched. Scope held to façade + instrument map — NOT the full dynamic UniverseSelectionModel.

---

## Inference guard & defaults

| Option | Description | Selected |
|--------|-------------|----------|
| Cap 8dp, string-read, keep default | Infer price precision from the CSV price string, count decimals, cap 8dp (DOGE-safe); keep 0.01 default only when no data. BTCUSD always declared-8dp. | ✓ |
| Defer inference to researcher | Lock only declared→default; let RESEARCH.md propose the algorithm. | |

**User's choice:** Cap 8dp, string-read, keep default.
**Notes:** declared → inferred(guarded) → default ladder, with BTCUSD pinned to the declared-8dp branch so the golden master does not drift.

## Claude's Discretion

- Exact `derive_instruments(...)` signature/placement; whether `is_active`/spans fold into `Universe` now or stay standalone.
- SimulatedExchange Instrument→ExchangeLimits min_order_size resolution plumbing.
- `kind → precision-field` mapping inside `quantize` (cash from `quote_currency`).

## Deferred Ideas

- Full dynamic `UniverseSelectionModel` (D-20 growth target) — future milestone.
- Margin/leverage/shorts/carry/liquidation/trailing stops — Phases 2–5.
- `settles_funding` — inert now, active in deferred Phase B (perp realism).

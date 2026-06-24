# Phase 3: Running PnL Accumulator - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-06-24
**Phase:** 3-running-pnl-accumulator
**Areas discussed:** Accumulator ownership, Update funnel / partial closes, Equivalence verification, CONCERNS cleanup scope, Decimal byte-exactness, Accumulator lifecycle

---

## Accumulator ownership

| Option | Description | Selected |
|--------|-------------|----------|
| PositionManager owns it | Decimal field on PositionManager; get_total_realized_pnl returns it; Portfolio feeds the increment in (facade→manager layering) | ✓ |
| Portfolio owns it | Portfolio holds the field (it computes the increment); but get_total_realized_pnl in PositionManager would read back from Portfolio — inverts dependency | |
| You decide | Leave to planning within layering convention | |

**User's choice:** PositionManager owns it
**Notes:** Keeps the read co-located with position storage; increment fed from Portfolio's close funnel.

---

## Update funnel / partial closes

| Option | Description | Selected |
|--------|-------------|----------|
| Reuse close funnel @529 | Feed from existing realised_increment = position.realised_pnl - prior_realised (portfolio.py:~529); captures partial + full closes; audit no other path | ✓ |
| Recompute in manager | PositionManager independently computes the delta — duplicates logic, drift risk | |
| You decide | Leave wiring to planning | |

**User's choice:** Reuse close funnel @529
**Notes:** Single proven source; planning must audit that ~529 is the only realised-PnL mutation path.

---

## Equivalence verification

| Option | Description | Selected |
|--------|-------------|----------|
| Audit + oracle + equiv test | Audit invariant + oracle/determinism + dedicated equivalence regression test (mirrors Phase 2 D-09) | ✓ |
| Audit + oracle only | Phase-2 D-04 style; no new dedicated test | |
| Keep debug cross-check | Runtime assert re-sums & compares — re-adds hot-path cost unless gated off | |

**User's choice:** Audit + oracle + equiv test
**Notes:** Three-layered proof; the dedicated test is the explicit drift lock for criterion #2.

---

## CONCERNS cleanup scope

| Option | Description | Selected |
|--------|-------------|----------|
| None — minimal diff | Skip opportunistic cleanups; keep diff tight for gate-(b) attribution | |
| Approve-list only | Only specific zero-risk cleanups approved case-by-case during planning, each a separate atomic commit | ✓ |
| You decide | Planning proposes any zero-behavior cleanups it finds | |

**User's choice:** Approve-list only
**Notes:** Planning proposes per-item for owner sign-off, does NOT auto-apply. Likely candidate: collapsing the dead dual open+closed loop. No CONCERN markers currently tagged; float() summary casts are a legit edge, left alone.

---

## Decimal byte-exactness

| Option | Description | Selected |
|--------|-------------|----------|
| Same seed + assert == | Keep Decimal('0.00') seed; same terms, no mid-sum quantize ⇒ byte-identical; equiv test asserts == | ✓ |
| Quantize accumulator | Quantize running total each update — changes precision, risks oracle divergence | |
| You decide | Leave seed/precision to planning | |

**User's choice:** Same seed + assert ==
**Notes:** Byte-identical (not just ==) because resulting Decimal exponent is min over the same term set regardless of order.

---

## Accumulator lifecycle

| Option | Description | Selected |
|--------|-------------|----------|
| Per-portfolio cache, retention unchanged | Init Decimal('0.00') at PositionManager construction; per-Portfolio scope; pure cache; closed positions still retained for audit | ✓ |
| Cache + drop closed retention | Stop retaining closed positions since PnL is cached — out of scope, behavior change | |
| You decide | Leave init/scoping/retention to planning | |

**User's choice:** Per-portfolio cache, retention unchanged
**Notes:** User asked to clarify closed-position storage. Confirmed: closed positions live once in InMemoryPortfolioStateStorage._closed_positions (append-only list); closing MOVES the same Position instance from the open dict to the closed list (no double-storage). The accumulator is a cache riding alongside — does not change retention.

---

## Claude's Discretion

- Exact attribute name/type of the accumulator field and the Portfolio→PositionManager method used to apply the increment (within D-01/D-02).
- Whether the D-02 invariant audit yields any defensive assert in non-hot paths (planner's call; nothing defensive on the per-bar hot path).
- Exact placement/shape of the equivalence regression test (within "asserts accumulator == full re-sum").

## Deferred Ideas

- Trimming closed-position retention (behavior change; own phase).
- Caching get_total_unrealized_pnl / get_total_market_value (price-dependent per bar; different technique; not this behavior-preserving milestone).

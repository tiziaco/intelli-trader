---
status: deferred
created: "2026-06-25"
source: Phase 8 / plan 08-04 D-03 attribution gate — Req 1 fusion reverted as a measured -15% W1 regression
tags: [perf, portfolio, valuation, position_manager, byte-exact, profile-first, D-02, keep-only-measured]
resolves_phase: ""
---

# Proper single-pass per-bar portfolio valuation (the real fix the 08-01 "fusion" missed)

**Origin:** Phase 8 Req 1 shipped a `_fused_valuation()` "fusion" that the 08-04 cool-box
same-machine A/B measured as a **-15% W1 / -5% W2@50 regression** and reverted (keep-only-measured,
D-02). This todo captures the *correct* design so the opportunity is not lost.

## Why the naive fusion regressed (do NOT repeat)

1. It never deduplicated the passes — `get_total_market_value` AND `get_total_unrealized_pnl` both
   still called `_fused_valuation()` independently → **two full iterations per bar**, same as before.
2. It added a per-bar `aggregate_notional` Decimal that **neither caller consumed** → strictly more
   work. "Fusion" in name only.

## The real design (compute-once-per-bar, O(1) accessors)

- There is already a per-bar **write pass**, `PositionManager.update_position_market_values`, that
  iterates every open position to set `current_price`. That is the natural single home.
- In that same loop, *after* setting `current_price`, accumulate `total_market_value` and
  `total_unrealized_pnl` into cached portfolio-level fields.
- `get_total_market_value` / `get_total_unrealized_pnl` become **field reads (O(1))**.
  Net per-bar iterations drop from **3 (write + 2 reads) → 1**.
- Invalidation seam: snapshot valid for the current price tick; fills (open/close/resize) flow
  through the existing mutation path. Same shape already proven twice — the Req-2 Position cache
  (08-02) and the Phase-3 running-PnL accumulator.

## The byte-exactness landmine (what makes this a plan, not a quick edit)

Accumulation order + quantization MUST match the current per-accessor summation exactly or the oracle
drifts off `46189.87730727451`. Seed `Decimal('0.00')`, preserve `+=` order, **no mid-sum quantize** —
the same discipline 08-02 / Phase 3 followed. `maintenance_margin` is on-demand / oracle-dark — keep
it OUT of the hot snapshot.

## Profile-first gate (honest caveat — may not be worth building)

Phase 3 already collapsed the expensive PnL re-summation (`position_manager` ~16% → ~0% CPU). The two
remaining valuation passes are `O(open positions)`, and SMA_MACD holds very few concurrent positions —
so on **W1 this may genuinely not be a measurable hotspot anymore** (part of why even a correct fusion
could land in noise). The symbol axis (**W2**, many concurrent symbols) is the likelier payoff.

**Before building:** re-profile W1 AND W2 and confirm the per-bar valuation iteration shows an
attributable CPU share. If it does not, this stays deferred — keep-only-measured (D-02) would reject it
as churn regardless of how clean the design is.

## Acceptance (if/when promoted to a phase)

- Single per-bar iteration over open positions computes market value + unrealized PnL; accessors O(1).
- SMA_MACD oracle byte-exact (134 / 46189.87730727451); determinism double-run identical; mypy --strict clean.
- Same-machine cool-box A/B shows an **attributable** W1 and/or W2 win (else do not ship).

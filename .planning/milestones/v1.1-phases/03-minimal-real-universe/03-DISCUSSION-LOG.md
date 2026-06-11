# Phase 3: Minimal Real Universe - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-06-09
**Phase:** 3-Minimal Real Universe
**Areas discussed:** Active-at-T semantics, Engine role / wiring, Primitive shape, Absence observability, Proof strategy

---

## Active-at-T Semantics

| Option | Description | Selected |
|--------|-------------|----------|
| Span (listed→delisted) | Active iff first_bar ≤ T ≤ last_bar — full lifespan, gaps still "active" | ✓ |
| Exact-bar presence | Active iff a bar literally exists at T | |

**User's choice:** Span model.
**Notes:** Chosen because it models a real exchange listing concept and is the shape a production screener extends; exact-bar-presence would conflate a one-day data hole with a delisting. Span boundaries derive from each ticker's own loaded data extent (pure availability — roadmap-locked).

---

## Engine Role / Wiring

| Option | Description | Selected |
|--------|-------------|----------|
| Derived read (Zipline-style) | Pure queryable availability primitive + refines warning loop; no hot-loop gating; sparse-dict still prevents fills | ✓ |
| Gate bar production (LEAN-style now) | membership(T) filters which tickers enter each BarEvent; rewrites hot loop; must prove byte-identical | |

**User's choice:** Derived read.
**Notes:** User asked "which future-proofs best, and what do other frameworks do?" Answer: frameworks separate availability/tradability (a query — Zipline `can_trade`/asset-lifetime) from selection (the gate — LEAN `UniverseSelectionModel`). Gating is the deferred v1.3 screener's job ("screeners propose, membership disposes", per the codebase's own D-20 docstring). Derived read is the seam the screener composes onto, keeps the layers separate, and avoids golden-oracle risk for zero behavioral gain.

---

## Primitive Shape (relationship to derive_membership)

| Option | Description | Selected |
|--------|-------------|----------|
| Add active_membership(T) alongside | Keep derive_membership as the static "set of interest" / selection seam; add a separate composable availability query | ✓ |
| Replace derive_membership | Collapse into one time-parameterized primitive, retire derive_membership, update feed + live call sites | |

**User's choice:** Add alongside.
**Notes:** User again asked the future-proofing / framework-precedent question. Answer: frameworks keep a static registry/selection seam distinct from the per-time availability query (Zipline `AssetFinder` vs. `can_trade`); they answer different questions for different consumers ("what do we track?" at wiring time, where T is meaningless, vs. "what's live at T?" per tick). `derive_membership` is precisely the seam the v1.3 screener extends, so it must not be retired.

---

## Absence Observability

| Option | Description | Selected |
|--------|-------------|----------|
| Silent expected, warn on gaps | Silent outside [first,last] span; warn only on true mid-life data hole | ✓ (initial) |
| Fully silent | Drop the warning loop entirely | |
| Keep warn-all | Preserve current warn-for-any-absent behavior | |
| **Refinement →** Feed owns it; strip handler warning | Feed = single span-aware owner; strategy handler keeps load-bearing skip, deletes its logger.warning | ✓ (final) |

**User's choice:** Silent-expected-warn-on-gaps, refined to: the **feed** is the single span-aware owner; the **strategy handler's** duplicate warning is deleted.
**Notes:** Tracing the wiring surfaced a SECOND warn-all site (strategy handler WR-12 guard, `strategies_handler.py:69-73`) beyond the feed loop. User identified the strategy-handler warning as legacy and asked to remove it. Clarified that the `if bar is None: … continue` skip is LOAD-BEARING (price stamped from `event.bars[ticker].close` just after) — only the `logger.warning` line is removable. Result: feed/data layer owns absence observability; strategy handler is a silent consumer. Oracle-dark (BTCUSD dense) → no golden-run risk; counts as CLAR-02 opportunistic cleanup.

---

## Proof Strategy

| Option | Description | Selected |
|--------|-------------|----------|
| Both: synthetic + real spans | Unit tests on synthetic fixture + integration run on real ETH/SOL/AAVE spans | |
| Synthetic fixture only | Hand-pinned tiny datasets with controlled listing/end/gap dates | ✓ |
| Real ETH/SOL/AAVE only | Integration over the actual Phase-2 datasets | |

**User's choice:** Synthetic fixture only.
**Notes:** User added: "Mark full end-to-end test for the next milestone somewhere." Recorded as a forward-pointer — the full real-data E2E run lands in **Phase 9** (ROBUST-03 heterogeneous spans) via the **Phase 4** E2E harness. Phase 3 proves the edges precisely and fast on synthetic fixtures; the real multi-ticker engine run is deferred.

---

## Bonus Discussion: How strategy tickers relate to the universe

User asked whether strategy-declared tickers are "automatically subscribed to the universe." Traced the wiring: strategy tickers ARE auto-folded into `derive_membership` (so yes, auto-members of the set-of-interest), but DATA is NOT auto-loaded — the `CsvPriceStore` `csv_paths` config is the explicit, manual data-subscription seam. It's a two-sided contract (strategy declares interest + store must independently provide data); a declared-but-unloaded ticker crashes at `feed.window()`. Phase 3 does not change this (store stays the subscription seam — matches Zipline/LEAN selecting from a configured bundle). Recorded as a deferred "auto-subscription — NOT pursued" note.

## Claude's Discretion

- Exact function name/signature (`active_membership(T) -> set[str]` vs. `is_active(ticker, T) -> bool` vs. both).
- Where/how span boundaries are cached (e.g. precomputed `[first,last]` per ticker at feed init).
- Precise synthetic-fixture layout/format.

## Deferred Ideas

- Full E2E run over real ETH/SOL/AAVE differing spans → Phase 9 (via Phase 4 harness).
- Membership-as-a-gate / dynamic screener selection → v1.3 / D-screener.
- Auto-subscription (strategy ticker auto-loading its data) → not pursued; store stays the explicit subscription seam.

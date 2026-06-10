# Phase 7: Cost, Sizing & SLTP Scenarios - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-06-10
**Phase:** 7-Cost, Sizing & SLTP Scenarios
**Areas discussed:** Cost-math golden vehicle, Fill substrate, Leaf granularity (COST/SIZE/SLTP), Emitter extension scope, Exchange-config seam validation, Over-cash rejection (SIZE-03), Wave/plan sequencing, Maker/taker fill shapes (COST-02)

---

## Cost-math golden vehicle (COST-06 "to the cent")

| Option | Description | Selected |
|--------|-------------|----------|
| Add explicit fee column to trades | Append a commission column to the trade-log golden so each fill's fee is independently visible/frozen; must be oracle-dark/opt-in | ✓ |
| Rely on final_cash + VERIFY note | Keep existing goldens; per-cent derivation in the leaf VERIFY note. Minimal, zero reporting change | |
| Dedicated cost-ledger artifact | New opt-in golden with per-trade gross/fee/slippage/net breakdown | |

**User's choice:** Add explicit fee column to trades.
**Follow-up — fee column scope:**

| Option | Description | Selected |
|--------|-------------|----------|
| Opt-in, COST leaves only | Freeze commission only in COST goldens that assert on fees | |
| Always-on for all E2E trades | Every E2E trade golden gains the commission column (0.00 for zero-fee leaves); re-freezes Phase 6 goldens | ✓ |

**User's choice:** Always-on for all E2E trades.
**Notes:** Column wired from real `Position.commission` (not recomputed); appended in the E2E path only (D-17 SLIPPAGE_COLUMNS precedent), never the core TRADE_COLUMNS pin the BTCUSD oracle freezes. Phase 6 zero-fee leaves get a one-time additive re-freeze (commission=0.00).

---

## Fill substrate (reuse vs fresh)

| Option | Description | Selected |
|--------|-------------|----------|
| Author fresh per-leaf bars | Each leaf authors minimal bars for ONE cost story; reuse the matching MECHANISM, not Phase 6 bar files | ✓ |
| Clone Phase 6 bar files | Copy Phase 6 matching bars verbatim and layer cost on top | |
| You decide | Per-requirement mix | |

**User's choice:** Author fresh per-leaf bars.
**Notes:** "Reuses matching scenarios" = the scripted-emitter/harness/fill-shape mechanism, not literal bars. Cleaner hand-derivation, isolated, parallel-safe.

---

## Leaf granularity (SLTP matrix)

| Option | Description | Selected |
|--------|-------------|----------|
| Full 2×3 matrix (6 leaves) | One leaf per (policy × outcome) | ✓ |
| Per-policy, multi-outcome bars (2 leaves) | One leaf per policy walking SL/TP/held | |
| Hybrid: 2 policy×outcome + 1 held (3 leaves) | Covers the policy distinction + all outcomes in 3 | |

**User's choice:** Full 2×3 matrix (6 leaves).

## Leaf granularity (COST/SIZE)

| Option | Description | Selected |
|--------|-------------|----------|
| One leaf per requirement (~9) | COST-02 maker+taker in-leaf; COST-05 standalone | ✓ |
| Split the two-legged ones (~11) | Separate maker/taker leaves; pair COST-05 with COST-03/04 | |
| You decide | Split only where a single bars.csv can't carry both legs | |

**User's choice:** One leaf per requirement (~9 → with SLTP's 6 = ~15 total).

---

## Emitter extension scope

| Option | Description | Selected |
|--------|-------------|----------|
| Extend the one ScriptedEmitter | Add sltp_policy (+ declarable stop for RiskPercent) to the single generic emitter | ✓ |
| Bespoke per-policy strategies | Dedicated strategy classes where a policy needs special wiring | |

**User's choice:** Extend the one ScriptedEmitter.
**Notes:** Flagged constraint (not a question): RiskPercent sizes off stop distance, so SIZE-02 must pair with a decision-time stop (explicit level or PercentFromDecision), not PercentFromFill (circular).

---

## Exchange-config seam validation

| Option | Description | Selected |
|--------|-------------|----------|
| Re-init from config object (post-construction) | Set simulated.config = spec.exchange then re-run _init_fee_model()/_init_slippage_model(); replaces the broken update_config(**model_dump()) call | ✓ |
| Thread config through construction | Add exchange_config param down TradingSystem→ExecutionHandler→SimulatedExchange | |
| Fix the flat-kwarg update_config path | Patch the mapping + to_kwargs double-prefix naming | |

**User's choice:** Re-init from config object (post-construction).
**Notes:** Investigation found the pre-wired Phase 6 seam is BROKEN — `update_config(**model_dump())` passes nested keys that the flat config_mapping silently ignores. The chosen fix uses the exchange's own clean config-object re-init path; oracle-dark (only fires for non-None spec.exchange).

---

## Over-cash rejection (SIZE-03)

| Option | Description | Selected |
|--------|-------------|----------|
| Reuse opt-in orders-snapshot (REJECTED) | Freeze the order mirror at REJECTED status — Phase 6's no-trade-outcome vehicle | ✓ |
| Assert on portfolio-error / audit record | Capture the PortfolioErrorEvent / cash-reservation audit trail | |
| Both snapshot + audit record | Most thorough | |

**User's choice:** Reuse opt-in orders-snapshot (REJECTED).

---

## Wave / plan sequencing

| Option | Description | Selected |
|--------|-------------|----------|
| Foundational plan, then 3 parallel waves | Plan 1: commission column + emitter sltp_policy + seam fix + 1 canary; then COST/SIZE/SLTP waves, batched verify per cluster | ✓ |
| Foundational plan, then per-requirement plans | Each requirement its own small plan | |
| You decide | Planner chooses wave grouping | |

**User's choice:** Foundational plan, then 3 parallel waves.

---

## Maker/taker fill shapes (COST-02)

| Option | Description | Selected |
|--------|-------------|----------|
| Two entries in one scenario | Limit rests-then-fills (maker) + market next-bar-open (taker); commission column shows both rates | ✓ |
| Limit maker + same-position market exit | Maker on buy leg, taker on sell leg of one round-trip | |
| You decide | Whichever makes the contrast most hand-derivable | |

**User's choice:** Two entries in one scenario.

---

## Claude's Discretion

- Exact commission column name/position and E2E-serialization append point (oracle-dark, after TRADE_COLUMNS).
- Exact contrived bars.csv authoring per leaf (fresh, hand-derivable, one story per leaf).
- ScriptedEmitter.sltp_policy parameter shape + how the RiskPercent stop is declared.
- Exact tests/e2e/{cost,sizing,sltp}/ sub-directory names/depth.
- Wave composition within clusters + batched-verify sitting boundaries.

## Deferred Ideas

- Faithful construction-time exchange config (thread ExchangeConfig through the production composition root) — deferred; post-construction re-init suffices.
- Dedicated per-trade cost-ledger golden — rejected in favor of the simpler always-on commission column.
- Run-end resting-order disposition / time-in-force (carried from Phase 6) — still unwired.
- Explicit per-intent limit/stop entry price + per-intent order_type (carried from Phase 6) — owner-gated, future milestone.

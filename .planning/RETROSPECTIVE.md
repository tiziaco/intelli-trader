# Project Retrospective

*A living document updated after each milestone. Lessons feed forward into future planning.*

## Milestone: v1.0 — Backtest-Correctness Refactor

**Shipped:** 2026-06-08
**Phases:** 8 (M1→M5c) | **Plans:** 62 | **Tasks:** ~100

### What Was Built
- A backtest engine taken from "does not import" to correct, deterministic, externally cross-validated: `SMA_MACD` on the golden BTCUSD CSV produces 134 trades / `final_equity = 46189.87730727451` / 3076 equity points, frozen as the authoritative numerical oracle.
- Structural foundations: single UUIDv7 ID scheme, Decimal money end-to-end, `mypy --strict` clean with frozen/slots DTOs + real ABCs, deterministic runs (seeded RNG + injected clock), config collapsed 3,380 → ~1,130 lines (Pydantic v2 + pydantic-settings).
- Correctness layers: immutable events + race-free dict-registry dispatch (M3); cash via CashManager + atomic settlement + one-directional order layering + PortfolioReadModel Protocol (M4); look-ahead removal + Bar struct + precomputed frames + next-bar-open fills + Provider/Store/Feed split + engine-side sizing + correct metrics (M5a/b).
- External validation: cross-validated against `backtesting.py`, `backtrader`, and `nautilus-trader` — all reconcile to 134 trades and final_equity ≈ 46189.877; verdict 0 BUG / 4 LEGITIMATE-DIFFERENCE.

### What Worked
- **Two-layer golden-master discipline.** Separating the behavioral oracle (trade timing, law M2–M4) from the numerical oracle (re-baselined at exactly two sanctioned points: M2b and M5c) let aggressive refactors land with byte-exact confidence and made every result change attributable to a milestone boundary.
- **Inert-first sequencing.** Structuring each result-risky phase as "all inert workstreams byte-exact gated, then one owner-gated result-changing wave" (M4 D-22, M5a D-21/22, M5b two re-freezes) isolated numerical risk to a single reviewable commit per phase.
- **Owner checkpoints on every re-freeze.** Result-changing diffs (next-bar-open fills, LONG_ONLY guard, allow_increase, Decimal precision) each carried an attributed expected-diff note + explicit owner sign-off, so no silent drift entered the oracle.
- **Cross-validation as the closing gate.** Forcing three independent engines to consume identical injected indicator arrays (D-03) made indicator divergence zero by construction and turned reconciliation into a pure execution-semantics check.

### What Was Inefficient
- **Planning-metadata drift.** Requirement checkboxes and the traceability table fell out of sync with reality (8 requirements + 30 rows stale at close, fixed during the milestone audit). SUMMARY `requirements_completed` frontmatter was filled sparsely, which weakened the automated 3-source coverage cross-reference and forced manual reconciliation.
- **`nautilus-trader` churn.** Dropped at 08-04 (python-cap conflict), then reinstated at 08-06 via an owner-directed Rule-4 python-constraint narrowing — a re-litigated decision that a tighter upfront dependency-resolution check would have avoided.
- **Repeated oracle re-freezes.** Several phases each needed their own re-freeze cycle; batching the precision-shift work might have reduced the number of owner checkpoints.

### Patterns Established
- Decision-tag anchoring (`D-xx`, `M5-xx`, `WR-xx`, `CR-xx`) in code comments + planning docs as load-bearing cross-references — preserve this.
- Read-model seams (`PortfolioReadModel` Protocol, injected `BacktestBarFeed`) to sidestep the queue-only rule for reads without breaking cross-domain write isolation.
- "Human-blessed deferral" register (DEF-xx) for current-behavior-to-preserve that is known-imperfect but intentionally out of scope.

### Key Lessons
1. **Re-baseline the numerical oracle at the fewest possible sanctioned points and gate each behind an owner checkpoint with an attributed diff.** It made an end-to-end correctness refactor auditable.
2. **Keep planning metadata (checkboxes, traceability, SUMMARY frontmatter) current as you go** — the milestone audit's automated coverage check is only as good as the frontmatter feeding it.
3. **Pin and smoke-gate cross-validation dependencies against the exact interpreter early** — dependency-cap conflicts surfaced late cost a drop-then-reinstate cycle.
4. **"Inert until proven, then one result-changing wave"** is a strong default for refactors guarded by a regression oracle.

### Cost Observations
- Model mix: not instrumented this milestone.
- Notable: most plans landed inert/byte-exact on the first or second attempt; the expensive cycles were the owner-gated re-freezes and the cross-validation engine integration (08-04→08-08).

---

## Cross-Milestone Trends

### Process Evolution

| Milestone | Phases | Plans | Key Change |
|-----------|--------|-------|------------|
| v1.0 | 8 | 62 | Established two-layer golden-master + inert-first + owner-gated re-freeze discipline |

### Cumulative Quality

| Milestone | Tests | mypy | Float money |
|-----------|-------|------|-------------|
| v1.0 | 724 pass | --strict clean | none on result path |

### Top Lessons (Verified Across Milestones)

1. (To be confirmed by v1.1+) Golden-master gating with minimal sanctioned re-baselines keeps refactors trustworthy.

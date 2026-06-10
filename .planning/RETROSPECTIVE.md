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

## Milestone: v1.1 — Backtest Trustworthiness: Breadth

**Shipped:** 2026-06-10
**Phases:** 9 (Phases 1–9) | **Plans:** 28 | **Tasks:** 53

### What Was Built
- A 58-leaf frozen golden E2E matrix exercising the engine's *entire* feature surface — resting-order book, brackets/OCO, fee/slippage variants, sizing, SLTP policies, scale in/out, admission/cash edges, multi-ticker/multi-strategy/multi-portfolio, robustness/degenerate-metrics, determinism — all behavior-preserving (BTCUSD oracle byte-exact: 134 trades / `final_equity 46189.87730727451`).
- New testing apparatus: dedicated `tests/e2e/` tree, registered `e2e` marker + folder-derived auto-marking, `make test-e2e`, and a shared golden-compare harness driving the real `TradingSystem` (no mocks) with a hand-verify-once-then-freeze discipline.
- New production surface: ETH/SOL/AAVE data ingestion (committed normalization script, `CsvPriceStore` unchanged); a real `membership`-from-availability primitive replacing the stub; pydantic `BaseStrategyConfig` + per-strategy validators + `OrderType` enum end-to-end; a typed, queryable `SignalRecord` store.

### What Worked
- **Oracle-dark opt-in instrumentation.** Every new observability artifact (`orders.csv`, `cash_operations.csv`, `portfolios.csv`) is an opt-in serializer gated by file-existence and NEVER added to `TRADE_COLUMNS` — so rich per-scenario state assertions landed without ever touching the byte-exact golden path.
- **Shared-infra-first, then parallel leaves.** Each scenario wave (Phases 6–9) committed shared infra (ScriptedEmitter, ScenarioSpec, serializers, conftest wiring) in Plan 01, then authored independent self-contained leaf folders — parallel-safe, no shared-file merge conflicts, each leaf hand-verified in a VERIFY note before `--freeze`.
- **Behavior-preserving breadth was cheap.** Because new artifacts were additive/oracle-dark, 8 phases of new coverage landed with the v1.0 oracle byte-exact throughout and zero owner-gated re-baselines — the inverse of v1.0's re-freeze-heavy profile.

### What Was Inefficient
- **Planning-metadata drift recurred (the v1.0 lesson repeated).** CLAR-01/02 and MATCH-01..08 traceability + checkboxes were stale at close (showed Pending despite passing verification); `requirements_completed` SUMMARY frontmatter was left empty on phases 1/4/5/7/9. Reconciled during the audit — again — because nothing *enforced* it during execution.
- **Test-harness workarounds accreted as real debt.** `ScenarioSpec`, the post-construction `ExchangeConfig` re-init conftest seam (Phase 7 D-14), and the `csv_paths` passthrough are all test-only stand-ins for a missing engine composition/config interface — now the headline of the v1.2 backlog. Captured, not silently absorbed (good), but they signal a contract gap the scenarios kept hitting.
- **Per-phase code-review warnings deferred wholesale.** Every phase's review (0 blockers, several warnings each) was logged advisory-unfixed rather than addressed inline (e.g. the dormant `ORDER-{n}` lexicographic sort). Cheap individually; an accumulating backlog at scale.

### Patterns Established
- **Opt-in oracle-dark CSV snapshot serializers** (`build_orders_snapshot`, `cash_operations`, per-portfolio snapshot) — file-exists-gated, business-columns-only, no UUIDs/wall-clock, stable `ORDER-{n}` ordinals — as the standard lens for freezing internal state without oracle risk.
- **`ScriptedEmitter` + `ScenarioSpec` as the scenario-authoring substrate** — date-keyed deterministic signal scripting + declarative portfolio/exchange/data wiring, driving the real engine via an oracle-inert `on_tick` hook.
- **Rule-3 conftest seams** — additive, backward-compatible test-infra extensions (commission-merge `pair` key, `spec.data` ticker registration, fee/slippage re-init) that never re-derive/wipe production state.

### Key Lessons
1. **Metadata drift is a process bug, not a discipline bug — it recurred verbatim from v1.0.** Re-reconciling checkboxes/traceability/frontmatter at the milestone audit is the symptom; the fix is *enforcement at execution* (a gate that fails a phase close when SUMMARY `requirements_completed` is empty or traceability lags verification), not another manual reconciliation pass.
2. **When every scenario works around the same missing interface, that's a product requirement surfacing through tests.** The ScenarioSpec/config-reinit workarounds became the v1.2 "Engine Surface Completion" milestone — capture harness workarounds as backlog the moment the second scenario needs the same hack.
3. **Additive, opt-in, oracle-dark is the cheapest way to add breadth under a regression oracle** — it inverted v1.0's expensive re-freeze profile into a zero-re-baseline milestone.
4. **Tooling you depend on can lie at the boundary** — the `gsd-sdk` SDK-port audit reported 4 false-positive "missing" quick tasks (filename bug vs the canonical scanner); verify flags against the canonical source before treating them as real work.

### Cost Observations
- Model mix: not instrumented this milestone.
- Sessions: phases 2–9 each shipped as one PR (#18–#26); Phase 1 + the FL-stragglers committed directly. ~2 calendar days (2026-06-09 → 2026-06-10).
- Notable: near-zero re-work on the golden path — the oracle-dark/opt-in pattern meant leaves landed green against the oracle on the first attempt; the expensive part was hand-verifying each leaf's expected fills/PnL before freezing.

---

## Cross-Milestone Trends

### Process Evolution

| Milestone | Phases | Plans | Key Change |
|-----------|--------|-------|------------|
| v1.0 | 8 | 62 | Established two-layer golden-master + inert-first + owner-gated re-freeze discipline |
| v1.1 | 9 | 28 | Breadth via additive opt-in oracle-dark E2E leaves — zero re-baselines; shared-infra-first then parallel scenario leaves |

### Cumulative Quality

| Milestone | Tests | mypy | Float money |
|-----------|-------|------|-------------|
| v1.0 | 724 pass | --strict clean | none on result path |
| v1.1 | 58 e2e + 12 integration green (full suite ~800+) | --strict clean (161 files) | none on result path |

### Top Lessons (Verified Across Milestones)

1. **Golden-master gating with minimal sanctioned re-baselines keeps refactors trustworthy** — confirmed across v1.0 (two owner-gated re-freezes) and v1.1 (zero re-baselines via additive oracle-dark leaves).
2. **Planning-metadata drift is a recurring process gap** — stale checkboxes/traceability/empty SUMMARY frontmatter required manual reconciliation at close in BOTH v1.0 and v1.1. Enforce frontmatter/traceability at phase close, not at milestone audit.

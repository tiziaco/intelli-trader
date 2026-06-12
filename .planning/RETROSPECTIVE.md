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

## Milestone: v1.2 — Consolidation

**Shipped:** 2026-06-12
**Phases:** 6 (Phases 1–6) | **Plans:** 23 | **Tasks:** ~36

### What Was Built
- The engine put in order — the v1.1 cleanup-review backlog (`V1.2-CLEANUP-REVIEW.md`, 46 findings) + the `CONCERNS.md` dead/fragile/tangled debt cleared **byte-exact against the golden master** (134 trades / `final_equity 46189.87730727451`), re-baselining nothing.
- `order_manager.py` decomposed from a 1279-line god-module into a 210-line thin coordinator + `admission/`/`brackets/`/`lifecycle/`/`reconcile/` collaborators (mirroring `portfolio_handler/`) as pure code-motion — the FRAGILE fill-reconciliation / `should_release`/`finally` path byte-for-byte unchanged, `on_fill` moved as one indivisible unit, cross-bucket seams rewired via coordinator callback + injected `BracketManager` (no sibling edges, no circular import).
- Locked-decision conformance (Decimal money API + Decimal `_min/_max_order_size`; single UUIDv7, `uuid4()` retired); hot-path per-tick copies/re-wraps/Bar-MACD churn eliminated bit-identically; closed vocabularies → class-based enums + frozen decision DTOs + `OrderId`/`PortfolioId` NewTypes; consistent naming (`global_queue`, PascalCase strategies, `*_window`) + public seams (`routes`, `register_symbol()`).

### What Worked
- **Isolating the FRAGILE refactor as a dedicated, sequential, LAST phase.** Phase 6 shipped MOD-01 alone, one D-10 extraction step per plan (BracketBook in-place → brackets → admission → lifecycle → reconcile LAST), each golden-gated. Moving `on_fill` as one intact unit with `should_release`/`finally` byte-for-byte unchanged meant the highest-risk change in the milestone landed byte-exact with zero behavior drift — the isolation rule paid off exactly as designed.
- **Pure code-motion under a regression oracle is nearly free.** Every Phase 6 plan re-ran the golden master + e2e + mypy and landed byte-exact on the first attempt; the decomposition added zero numerical risk because nothing but structure moved.
- **Owner-flagged gap deltas instead of silent folding.** The D-07 re-adjudication (the W2-10 "latent TypeError" was a misdiagnosis — Decimal-vs-float comparison works in Py3) was surfaced as a bounded, owner-visible delta with the REQUIREMENTS/SC wording corrected, not quietly absorbed into a running phase. The established gap-discovery discipline held.
- **Sequencing cleanup so the decomposition came last.** Naming/encapsulation (Phase 5) made the public seams consistent *before* the god-module split, so Phase 6 extracted collaborators against already-clean names.

### What Was Inefficient
- **Planning-metadata drift recurred for the third milestone running.** DEC/PERF/TYPE REQUIREMENTS checkboxes + 11 traceability rows were stale (Pending/`[ ]`) at audit despite passing verification — the phase verifiers deferred these orchestrator-owned edits, and the milestone audit reconciled them *again*. SUMMARY `requirements-completed` frontmatter still omits 6 REQ-IDs. The v1.0/v1.1 lesson ("enforce at phase close, not at audit") remains unimplemented — it is now a verified three-milestone pattern.
- **The same `gsd-sdk` SDK-port false-positive recurred at close.** The 4 completed quick tasks flagged "missing" by the SDK-port filename bug had to be re-adjudicated and re-acknowledged exactly as in v1.1 — a known tooling lie that still costs a manual verification pass each milestone.
- **Nyquist validation was discovery-only again** (not auto-run); the behavioral safety net came entirely from the oracle + 58 e2e + mypy strict. Acceptable for a behavior-preserving milestone, but the formal validation coverage gap persists across milestones.

### Patterns Established
- **God-module decomposition as a sequenced, golden-gated, single-requirement LAST phase** — one collaborator extraction per plan, FRAGILE unit (`on_fill`) moved intact and last, cross-bucket seams via coordinator callback + injection (never sibling references), facade + barrel byte-unchanged. The reusable template for safely splitting any fragile god-module under a regression oracle.
- **Coordinator-owned shared collaborators injected into sub-managers** (the `BracketBook`/`BracketManager` "D-04 star" pattern) — sub-managers hold no queue and no sibling refs; the thin coordinator owns shared state and wires it in, so extraction never introduces a cross-manager edge or circular import.

### Key Lessons
1. **Isolate the fragile change and move it intact, last.** The single most fragile path in the codebase (fill-reconciliation / reservation-release) was refactored with zero drift specifically because Phase 6 carried *only* MOD-01, extracted one step at a time, and moved `on_fill` as one indivisible unit. Bundling it with any behavior fix would have made a regression unattributable.
2. **Pure code-motion under a byte-exact oracle is the cheapest large structural change available** — 1279→210 lines landed byte-exact on first attempt every plan. When the oracle proves "nothing changed," aggressive decomposition is low-risk.
3. **Metadata drift is now a confirmed three-milestone process bug.** It is no longer a discipline lapse to coach away — it needs a *mechanical* phase-close gate (fail the close when `requirements-completed` is empty or traceability lags VERIFICATION.md). Manual reconciliation at audit has been paid three times.
4. **A tool that lied last milestone will lie again** — the `gsd-sdk` SDK-port quick-task false positive recurred verbatim. Either fix/replace the boundary tool or script the canonical-scanner check, rather than re-adjudicating by hand each close.

### Cost Observations
- Model mix: not instrumented this milestone.
- Sessions: phases shipped as PRs (#32–#34 visible in recent git log: type-modeling, naming, order-handler refactor); Phases 1–3 + finalization committed directly. ~1–2 calendar days (2026-06-10 → 2026-06-11, finalized 2026-06-12).
- Notable: near-zero re-work on the golden path — behavior-preserving + pure-code-motion meant plans landed byte-exact on the first attempt; the only real cost was careful sequencing/verification of the FRAGILE Phase 6 extractions.

---

## Cross-Milestone Trends

### Process Evolution

| Milestone | Phases | Plans | Key Change |
|-----------|--------|-------|------------|
| v1.0 | 8 | 62 | Established two-layer golden-master + inert-first + owner-gated re-freeze discipline |
| v1.1 | 9 | 28 | Breadth via additive opt-in oracle-dark E2E leaves — zero re-baselines; shared-infra-first then parallel scenario leaves |
| v1.2 | 6 | 23 | Consolidation via pure code-motion under the oracle — god-module split as a sequenced, isolated, LAST phase; zero re-baselines |

### Cumulative Quality

| Milestone | Tests | mypy | Float money |
|-----------|-------|------|-------------|
| v1.0 | 724 pass | --strict clean | none on result path |
| v1.1 | 58 e2e + 12 integration green (full suite ~800+) | --strict clean (161 files) | none on result path |
| v1.2 | 58 e2e + 3 integration oracle green (full suite 851) | --strict clean (172 files) | none on result path |

### Top Lessons (Verified Across Milestones)

1. **Golden-master gating with minimal sanctioned re-baselines keeps refactors trustworthy** — confirmed across v1.0 (two owner-gated re-freezes), v1.1 (zero re-baselines via additive oracle-dark leaves), and v1.2 (zero re-baselines via pure code-motion). Under a byte-exact oracle, even a 1279-line god-module split lands on first attempt.
2. **Planning-metadata drift is a recurring process gap — now confirmed across THREE milestones** — stale checkboxes/traceability/empty SUMMARY frontmatter required manual reconciliation at close in v1.0, v1.1, AND v1.2. This is no longer a coaching problem; it needs a mechanical phase-close gate that fails when `requirements-completed` is empty or traceability lags VERIFICATION.md.
3. **Isolate the fragile change, move it intact, ship it last and alone** — v1.2 Phase 6 refactored the codebase's most fragile path (fill-reconciliation / reservation-release) with zero drift precisely because it carried only MOD-01, one extraction per plan, `on_fill` moved as one indivisible unit. The template for any future god-module split.
4. **Boundary tooling that lied once will lie again** — the `gsd-sdk` SDK-port quick-task false positive recurred verbatim in v1.1 and v1.2; verify flags against the canonical scanner, don't re-adjudicate by hand each close.

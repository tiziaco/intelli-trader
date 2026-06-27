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

## Milestone: v1.3 — Engine Surface Completion

**Shipped:** 2026-06-14
**Phases:** 6 (Phases 1–6) | **Plans:** 20

### What Was Built
- The engine's authoring + contract surfaces completed ahead of N+2 (margin/shorts): class-attribute strategy authoring (STRAT-01) replacing the frozen-pydantic config + manual field-copy, with a re-runnable idempotent `init()`; a declared-indicator framework (IND-01) with framework-derived `warmup`/`max_window` and look-ahead-safe `crossover`/`crossunder`.
- Engine-level composition API (COMP-01: `SystemSpec`/`build_backtest_system`/`compose_engine` + `OrderConfig` + construction-time `ExchangeConfig` threading replacing the Phase 7 D-14 conftest seam) and a uniform `update_config` on all 7 handlers (COMP-02) for between-cycle live reconfig.
- Signal contract completed (SIG-01/02/03: per-intent entry price + order_type, `Side`-typed action, single snapshot threading) co-phased with the `on_fill`/`should_release` reconcile streamline (RECON-01) so the FRAGILE `reconcile/` path was touched once; and run-end time-in-force expiry (LIFE-01: `EXPIRED` wired through all four arms, dead `create_order` path removed).

### What Worked
- **The two-discipline split (byte-exact 1–4 vs owner-gated 5–6) in SEPARATE phases.** Byte-exact phases produced clean pass/fail golden gates (zero drift on the BTCUSD oracle); each owner-gated phase owned exactly one attributed re-baseline. No ambiguity about whether a number was *allowed* to move.
- **Co-phasing SIG-03 + RECON-01 so `reconcile/` was touched once.** The v1.2 Phase-6 intact-move into `reconcile/` was the designed enabling surface; touching the FRAGILE path under one re-baseline + cross-validation (not twice) is exactly what the v1.2 decomposition was for — the cross-milestone setup paid off.
- **Sequencing STRAT-01 (P2) before COMP-02 (P4).** The re-runnable idempotent `init()` shipped first as a smaller byte-exact slice, then `StrategiesHandler.update_config` consumed it (re-validate → re-run `init()` → re-derive warmup). Building the seam before the consumer kept each phase independently gateable.
- **External cross-validation for the result-changing signal work.** The SIG-01/02 LIMIT-entry golden was validated against backtesting.py + backtrader before the owner froze it; the one legitimate intrabar-SL difference was explicitly adjudicated and accepted, not silently kept.

### What Was Inefficient
- **Planning-metadata drift recurred for the FOURTH milestone running.** HYG-01 and LIFE-01 stayed `[ ]`/Pending in REQUIREMENTS.md traceability despite passing VERIFICATION.md; SUMMARY `requirements-completed` frontmatter was present on only 3 of the phase summaries (inconsistent field naming: `requirements` vs `requirements-completed` vs absent). Both phase verifiers flagged the lag in-line, and a quick-task + the milestone audit reconciled it *again*. The mechanical phase-close gate proposed across v1.0–v1.2 is still unimplemented.
- **The `audit-open` quick-task false-positive recurred for the third close.** 5 completed quick-tasks (`status: complete`) were flagged `missing` by the ledger; the same manual canonical-scan re-adjudication as v1.1/v1.2 was needed.
- **Nyquist Wave-0 discovery-only again** — VALIDATION.md exists on all 6 phases but `nyquist_compliant: false` on 2/3/6. The behavioral net (oracle + 59-leaf e2e + mypy strict) carried correctness, but formal validation coverage still lags.

### Patterns Established
- **Two re-baseline disciplines, declared per-phase, kept in separate phases** — byte-exact (hold the oracle byte-for-byte) vs owner-gated (freeze a new golden only after sign-off + external cross-validation). A byte-exact phase's gate is unambiguous; a result-changing phase owns its attribution. The template for any milestone mixing cleanup with intentional result changes.
- **Build the seam first, consume it later** — ship a re-runnable `init()` as a small byte-exact slice (P2) so a later runtime-reconfig consumer (P4 `update_config`) plugs into an already-proven hook. Decouples a risky integration into two independently gateable steps.
- **Cross-milestone enabling surfaces** — v1.2's FRAGILE-path decomposition into `reconcile/` was explicitly designed as the bounded surface v1.3's RECON-01 would refactor; planning the enabling cleanup one milestone ahead made the fragile change a single bounded touch.

### Key Lessons
1. **Separate "allowed to change the numbers" from "must not" at the phase boundary.** Putting byte-exact and owner-gated requirements in different phases made every golden gate a clean signal and every re-baseline individually attributable — the cleanest result-discipline this project has run.
2. **A fragile refactor is cheapest when the enabling cleanup shipped a milestone earlier.** RECON-01 touched the reconcile path once, safely, because v1.2 had already moved `on_fill` into a bounded collaborator. Plan the enabling surface ahead of the fragile change.
3. **Metadata drift is now a FOUR-milestone confirmed process bug.** Manual reconciliation at close has been paid four times. The fix is mechanical (fail the phase close when `requirements-completed` is empty or traceability lags VERIFICATION.md), not more discipline.
4. **The `audit-open` ledger and the SDK-port flag are both known liars** — script the canonical `status: complete` scan into the close instead of re-adjudicating by hand every milestone.

### Cost Observations
- Model mix: not instrumented this milestone.
- Sessions: phases shipped as PRs (#37–#42: hygiene, authoring surface, indicator framework, composition/config, signal contract, order lifecycle). ~2 calendar days (2026-06-12 → 2026-06-14).
- Notable: byte-exact phases (1–4) landed with zero golden drift; the only sanctioned result changes were the owner-signed LIMIT golden (additive) and 3 equity-neutral `PENDING→EXPIRED` e2e re-baselines.

---

## Milestone: v1.4 — Margin, Leverage, Shorts & Trailing Stops

**Shipped:** 2026-06-22
**Phases:** 7 (Phases 1–6 + inserted 5.1) | **Plans:** 35

### What Was Built
- The matching-engine / risk-execution surface: a frozen per-symbol `Instrument` value object (deletes `_INSTRUMENT_SCALES`) as the single source of price/quantity scales + `max_leverage` + `maintenance_margin_rate` (INST-01/02/03); reserved-margin position opening with effective leverage threaded signal→order→fill→transaction→position for MARKET/LIMIT/STOP, over-margin → audited REJECTED (MARGIN/LEV).
- First-class shorts (the `LONG_ONLY` guard removed via a side-agnostic cover-arm) with short PnL + daily borrow-carry (SHORT/CARRY); bar-close maintenance-margin liquidation with capped loss, cross-validated (LIQ/XVAL); engine-native `TRAILING_STOP` ratcheting favorably-only from closed-bar extremes (TRAIL).
- Short scale-in through the existing side-agnostic SCALE-IN branch with a symmetric admission solvency gate (SCALE, inserted Phase 5.1); a market-neutral ETH/BTC pair flagship running end-to-end both legs (94 round trips) through the unchanged accounting core (PAIR-01).

### What Worked
- **The "reuse the side-agnostic accounting core, zero new correctness branches" constraint.** Shorts, levered entries, short scale-in, and both pair legs all settle through the same lock-and-settle SCALE-IN branch. Holding the line on "no new settlement path" is exactly why the spot oracle stayed byte-exact across all 7 phases while the engine gained margin trading.
- **One owner-gated re-baseline per result-changing subsystem, each cross-validated.** Three separate signed re-baselines (accounting core P4, trailing P5, scale-in P5.1, tiziaco 2026-06-16/06-17) kept every result change attributable and externally checked — the v1.3 discipline carried forward cleanly to a much larger result-changing milestone.
- **The pair flagship framed as additive (NOT the oracle) from the CONTEXT stage.** Declaring up front that a two-leg strategy partially cancels its own sign errors — so the crafted XVAL-01 scenarios are the oracle and the flagship is a stability snapshot — avoided over-trusting a weak signal and kept the capstone genuinely slip-able.
- **Inserting Phase 5.1 as a clean decimal phase.** The short scale-in gap (an unconditional admission rejection) surfaced after Phase 5; inserting 5.1 rather than stretching Phase 5 kept the trailing re-baseline and the scale-in re-baseline independently attributable.

### What Was Inefficient
- **Planning-metadata drift recurred for the FIFTH milestone running.** LIQ-01/02/03, XVAL-01, PAIR-01 stayed `[ ]`/Pending in REQUIREMENTS.md despite passing VERIFICATION.md; Phase 01 used a non-standard `requirements:` frontmatter field (vs `requirements-completed:`) so INST-01/02/03 were tooling-invisible; SHORT-01/SCALE-01/PAIR-01 were absent from their SUMMARY frontmatter. The milestone audit reconciled it *again*. The mechanical phase-close gate proposed since v1.0 is still unbuilt.
- **The `audit-open` quick-task false-positive recurred for the FOURTH close — and this time the root cause was nailed.** The scanner reads `quick/<dir>/SUMMARY.md` but GSD writes `<slug>-SUMMARY.md`, so every quick task always reads `[missing]` regardless of `status: complete`. Resolved at close by adding unprefixed completion-marker files; the real fix is in the SDK scanner (glob `*-SUMMARY.md`), which can't be patched durably from the repo.
- **Nyquist Wave-0 still discovery-only** — VALIDATION.md is `draft`/`planned` on most phases and absent on 5.1; the behavioral net (spot oracle + crafted scenarios + 1193 suite) carried correctness, but formal validation coverage lags for the fifth milestone.

### Patterns Established
- **"No new correctness branch" as an explicit milestone-level constraint.** When adding a large feature family (shorts/leverage/liquidation/scale-in/pairs) that *could* each fork settlement, require every new case to route through the existing side-agnostic core. The oracle byte-exactness becomes the proof that the constraint held.
- **Weak-oracle honesty for multi-leg / self-cancelling strategies.** A strategy whose own structure masks sign errors is declared a stability snapshot, not a correctness oracle, at the CONTEXT stage — the crafted adversarial scenarios remain the oracle.
- **Decimal-phase insertion for a mid-milestone gap with its own re-baseline.** A gap discovered between owner-gated phases gets its own inserted phase so its re-baseline doesn't entangle the neighbour's attribution.

### Key Lessons
1. **A large result-changing milestone stays trustworthy when every new case reuses one validated settlement path.** Seven phases of margin/shorts/leverage/liquidation/trailing/scale-in/pairs landed with the spot oracle byte-exact because nothing forked the accounting core — the single most important discipline of this milestone.
2. **Name the weak oracle before building it.** Declaring the pair flagship "additive, not the oracle" up front kept correctness anchored on the crafted scenarios and made the capstone safely slip-able.
3. **Metadata drift is now a FIVE-milestone confirmed process bug, and the `audit-open` lie is a fully diagnosed tooling bug.** Both were paid again by hand at close. The fixes are mechanical: a phase-close gate on `requirements-completed`, and an SDK scanner that globs `*-SUMMARY.md`.

### Cost Observations
- Model mix: not instrumented this milestone.
- Sessions: ~8 calendar days (2026-06-14 → 2026-06-22); much of the result-changing work executed in isolated worktrees and merged. 16 commits on `v1.3..HEAD`; ~13.9k LOC code added (itrader + tests).
- Notable: the spot oracle held byte-exact (134 / 46189.87730727451) across all 7 phases; the only sanctioned result changes were the 3 owner-signed, externally cross-validated re-baselines.

---

## Milestone: v1.5 — Backtest Performance Optimization

**Shipped:** 2026-06-26
**Phases:** 8 (Phases 1–8, numbering reset; 7–8 added mid-milestone from re-profiles) | **Plans:** 26

### What Was Built
- The profiler-guided hot-path pass over the frozen W1 baseline: a `perf-*` measurement harness (clean benchmark vs separate Scalene profile, committed `W1-BASELINE.json` + soft ≥5% guard); derived secondary order-storage indexes over the flat `{id: order}` dict (killed the #1 ~37% CPU linear scan, D-20 preserved); a running Decimal PnL accumulator (~13%); level-gated logging + memoized `get_type_hints`.
- Hand-written O(1) stateful SMA/EMA/MACD/RSI recurrences on a shared recent-bars feed (~24%, `ta` dropped on the runtime path); a monotonic int64 window cursor replacing per-tick `searchsorted`; `_aligned` memoization + `deque(maxlen)` snapshot retention (killed a latent O(n²)); a `msgspec.Struct` migration of the `Bar` + full event chain (Decimal contract intact).
- Behavior-preserving throughout: the SMA_MACD oracle held byte-exact (134 / `46189.87730727451`) across all 8 phases; final W1 baseline re-frozen at 15.7 s / 152.8 MB.

### What Worked
- **Keep-only-measured discipline.** Every optimization had to show an attributable same-machine-A/B win or be reverted. The Phase-8 naive mark-to-market "fusion" looked clean but A/B-measured at −15% W1 and was reverted with zero residual code — the discipline caught a plausible-but-wrong change that a frozen-baseline diff would have rubber-stamped.
- **Attributing wins by same-machine A/B + Scalene CPU-share, not the frozen-baseline diff.** The box is thermally sensitive and a Phase-1 benchmark-probe quadratic bug shifted the absolute number mid-milestone; A/B attribution made every phase's contribution honest despite an unstable absolute reference.
- **Isolating the FRAGILE stateful-indicator phase LAST, alone, with a pre-authorized re-baseline carve-out.** Dropping `ta` for hand-written recurrences was the one change that *could* break byte-exactness; isolating it made the (as it turned out, byte-identical) result fully attributable, and the carve-out meant a cross-validated re-baseline was ready if needed.
- **The spike WAS the research.** `perf/results/PERF-BASELINE-RESULTS.md` (frozen baseline + ranked hotspot map + phase breakdown) drove the whole milestone — no separate research pass. The profile→fix→re-profile loop then organically surfaced Phases 7 and 8 as the next hotspot tiers.

### What Was Inefficient
- **The benchmark-probe quadratic bug cost real debugging time.** Early W1 baselines were inflated by an O(n²) full-scan in the probe itself; it masqueraded as thermal throttling for a while before being root-caused and re-frozen (153.7 s → 28.3 s). Lesson banked: validate the *measurement* harness as carefully as the code it measures.
- **Planning-metadata drift recurred for the SIXTH milestone running.** Phases 7–8 reused the PERF-07/PERF-08 IDs that REQUIREMENTS.md already defined as deferred-v2 items; Phase 03's verification/UAT stayed `human_needed`/`partial` after the re-freeze that cleared them was done elsewhere (quick task + Phase 8). All reconciled by hand at this close. The mechanical phase-close gate proposed since v1.0 is still unbuilt.
- **The `audit-open` quick-task false-positive recurred for the FIFTH close** — 7 complete quick tasks read `[missing]` because the scanner globs `quick/<dir>/SUMMARY.md` not `<slug>-SUMMARY.md`. Cleared again with completion markers; the durable fix is in the SDK scanner.
- **Nyquist Wave-0 still lags** — VALIDATION.md missing on 03/04/08, partial on 05/06/07. Advisory only here: the byte-exact oracle + same-machine A/B perf gate ARE the regression lock and ran green every phase.

### Patterns Established
- **Keep-only-measured: revert any optimization that lands in A/B noise.** A "clean" change with no attributable win is churn (risk, no payoff). The revert keeps the milestone diff honest and the baseline trustworthy.
- **Attribute perf wins by same-machine A/B + Scalene CPU-share, never the frozen-baseline diff** when the machine is thermally sensitive or the absolute number shifted mid-milestone. Re-freeze the absolute baseline only on a verified-cool box.
- **A behavior-preserving perf milestone gates on the byte-exact oracle exactly like a cleanup milestone** (the v1.2 analog) — speed is the *only* thing allowed to change, so the oracle is the lock that makes every optimization attributable.

### Key Lessons
1. **Measure the measurement.** The biggest time sink wasn't an optimization — it was a quadratic bug in the benchmark probe that corrupted the baseline. A perf milestone's harness needs the same correctness scrutiny as the engine.
2. **Keep-only-measured beats looks-correct.** The reverted Phase-8 fusion was clean, well-typed, byte-exact — and a −15% regression. Only same-machine A/B caught it. Attributable measurement is the real gate, not code review.
3. **Metadata drift is now a SIX-milestone confirmed process bug and the `audit-open` lie a FIVE-close tooling bug.** Both paid again by hand. The fixes remain mechanical: a phase-close gate on `requirements-completed`/traceability, and an SDK scanner that globs `*-SUMMARY.md`.

### Cost Observations
- Model mix: not instrumented this milestone.
- Sessions: ~4 calendar days (2026-06-22 → 2026-06-26); much of the work executed in isolated worktrees and merged via PRs (#54–#61). 18 commits on `v1.4..HEAD`; ~2.5k LOC under `itrader/` (+3.1k tests) — small, surgical, hot-path-focused diffs.
- Notable: the oracle held byte-exact (134 / 46189.87730727451) across all 8 phases — a perf milestone that changed no numbers; the only "result change" attempted (Phase-8 fusion) was reverted.

---

## Cross-Milestone Trends

### Process Evolution

| Milestone | Phases | Plans | Key Change |
|-----------|--------|-------|------------|
| v1.0 | 8 | 62 | Established two-layer golden-master + inert-first + owner-gated re-freeze discipline |
| v1.1 | 9 | 28 | Breadth via additive opt-in oracle-dark E2E leaves — zero re-baselines; shared-infra-first then parallel scenario leaves |
| v1.2 | 6 | 23 | Consolidation via pure code-motion under the oracle — god-module split as a sequenced, isolated, LAST phase; zero re-baselines |
| v1.3 | 6 | 20 | Two re-baseline disciplines (byte-exact vs owner-gated) in SEPARATE phases; cross-milestone enabling surface (v1.2 reconcile/) touched once; result changes attributed + cross-validated |
| v1.4 | 7 | 35 | Large result-changing family (margin/shorts/leverage/liquidation/trailing/scale-in/pairs) reusing one side-agnostic settlement core — zero new correctness branches, spot oracle byte-exact across all 7 phases; 3 owner-signed cross-validated re-baselines; weak-oracle honesty for the pair flagship |
| v1.5 | 8 | 26 | Behavior-preserving perf milestone (the v1.2 analog) — profiler-ranked, oracle-gated hot-path wins under **keep-only-measured** (revert anything that lands in A/B noise); per-phase attribution by same-machine A/B + Scalene CPU-share, not the frozen-baseline diff (thermally sensitive + a probe bug shifted the absolute number); FRAGILE stateful-indicator phase isolated LAST; oracle byte-exact across all 8 phases |

### Cumulative Quality

| Milestone | Tests | mypy | Float money |
|-----------|-------|------|-------------|
| v1.0 | 724 pass | --strict clean | none on result path |
| v1.1 | 58 e2e + 12 integration green (full suite ~800+) | --strict clean (161 files) | none on result path |
| v1.2 | 58 e2e + 3 integration oracle green (full suite 851) | --strict clean (172 files) | none on result path |
| v1.3 | 59 e2e + integration oracle green (full suite 995) | --strict clean (182 files) | none on result path |
| v1.4 | integration oracle byte-exact + pair flagship snapshot green (full suite 1193) | --strict clean (187 files) | none on result path |
| v1.5 | integration oracle byte-exact across all 8 phases (full suite 1340) | --strict clean | none on result path |

### Top Lessons (Verified Across Milestones)

1. **Golden-master gating with minimal sanctioned re-baselines keeps refactors trustworthy** — confirmed across v1.0 (two owner-gated re-freezes), v1.1 (zero re-baselines via additive oracle-dark leaves), and v1.2 (zero re-baselines via pure code-motion). Under a byte-exact oracle, even a 1279-line god-module split lands on first attempt.
2. **Planning-metadata drift is a recurring process gap — now confirmed across SIX milestones** — stale checkboxes/traceability/inconsistent SUMMARY frontmatter required manual reconciliation at close in v1.0, v1.1, v1.2, v1.3, v1.4, AND v1.5 (v1.4 hid INST-01/02/03 behind a non-standard `requirements:` field; v1.5 reused the deferred PERF-07/08 IDs for delivered work and left Phase-03 verification/UAT stale after the re-freeze that cleared it landed elsewhere). This is no longer a coaching problem; it needs a mechanical phase-close gate that fails when `requirements-completed` is empty/misnamed or traceability lags VERIFICATION.md.
3. **Isolate the fragile change, move it intact, ship it last and alone — and plan its enabling surface a milestone ahead** — v1.2 Phase 6 moved `on_fill` into a bounded `reconcile/` collaborator with zero drift; v1.3 RECON-01 then refactored that exact bounded surface in a single touch, co-phased with SIG-03 under one owner-gated re-baseline. The template for any future fragile change.
4. **Boundary tooling that lied once will lie again — now ROOT-CAUSED** — the quick-task false positive recurred verbatim in v1.1, v1.2, v1.3, v1.4, and v1.5. The cause is now pinned: the `audit-open` scanner reads `quick/<dir>/SUMMARY.md` but GSD writes `<slug>-SUMMARY.md`, so completion is never seen. Fix the scanner to glob `*-SUMMARY.md`; until then, completion markers clear it.
5. **Mixing intentional result changes with cleanup is safe only when the two disciplines live in separate phases** — v1.3's byte-exact phases (1–4) and owner-gated phases (5–6) each had an unambiguous gate; v1.4 extended this to 3 owner-gated re-baselines (P4/P5/P5.1), each individually attributed and externally cross-validated.
6. **A large feature family stays trustworthy when every new case reuses ONE validated settlement path** — v1.4 added margin/shorts/leverage/liquidation/trailing/scale-in/pairs with the spot oracle byte-exact across all 7 phases because nothing forked the side-agnostic accounting core. "No new correctness branch" as an explicit milestone constraint is the proof discipline for feature-heavy result-changing work.
7. **For a performance milestone, attributable measurement is the gate — not code review, and not the frozen-baseline diff** — v1.5 reverted a clean, byte-exact, well-typed Phase-8 "fusion" because same-machine A/B measured it at −15% W1. When the machine is thermally sensitive (or the measurement harness itself has a bug, as v1.5's quadratic probe did), attribute every win by same-machine A/B + Scalene CPU-share and re-freeze the absolute baseline only on a verified-cool box. Keep-only-measured: revert anything that lands in A/B noise.

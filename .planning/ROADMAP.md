# Roadmap: iTrader

## Milestones

- ✅ **v1.0 — Backtest-Correctness Refactor** — Phases 1-8 (shipped 2026-06-08)
- 🚧 **v1.1 — Backtest Trustworthiness: Breadth** — Phases 1-9 (in progress)
- 📋 **N+2 — Margin, Leverage, Shorts & Trailing Stops** — Backlog (planned)
- 📋 **N+3 — Persistence & Performance** — Backlog (planned)
- 📋 **N+4 — Live Trading Readiness** — Backlog (planned)

Full v1.0 detail (phase goals, success criteria, per-plan breakdown) is archived in
[`milestones/v1.0-ROADMAP.md`](./milestones/v1.0-ROADMAP.md); requirements in
[`milestones/v1.0-REQUIREMENTS.md`](./milestones/v1.0-REQUIREMENTS.md); audit in
[`milestones/v1.0-MILESTONE-AUDIT.md`](./milestones/v1.0-MILESTONE-AUDIT.md).
v1.0 phase working dirs are archived under `milestones/v1.0-phases/`.

## Phases

> **Active milestone: v1.1 — Backtest Trustworthiness: Breadth.** Phase numbering is RESET
> to start at Phase 1 (v1.0 phase dirs archived). The spine is dependency-ordered: the
> codebase map comes FIRST so every later phase builds on it → data → universe → E2E
> framework → interface hardening → scenario waves. Every E2E scenario phase depends on the
> harness (Phase 4). LONG-ONLY throughout; shorts are gated to N+2. The v1.0 golden numbers
> are NOT re-baselined — v1.1 is behavior-preserving; any result-changing finding is
> owner-gated. Opportunistic cleanup (CLAR-02) is a cross-cutting practice carried through
> every later phase and verified at milestone close — not a standalone phase.

- [x] **Phase 1: Codebase Map & Clarity Baseline** — One read-only `gsd-map-codebase` pass → objective fix-list that informs every later phase; establishes the opportunistic-cleanup standard carried cross-cutting through the milestone. Blocks nothing; pure analysis. (completed 2026-06-09)
- [x] **Phase 2: Data Ingestion** — Committed normalization script produces ETH/SOL/AAVE in the golden Binance-kline schema; `CsvPriceStore` loads all four unchanged. (completed 2026-06-09)
- [x] **Phase 3: Minimal Real Universe** — A `membership`-from-availability primitive replaces the stub; the engine handles mid-run listing / absent bars without crash or look-ahead. (completed 2026-06-09)
- [x] **Phase 4: E2E Harness & Framework** — Dedicated `tests/e2e/` tree, registered `e2e` marker, `make test-e2e`, and a shared golden-compare harness every scenario phase builds on. (completed 2026-06-09)
- [x] **Phase 5: Strategy Interface Hardening & Signal Storage** — Pydantic `BaseStrategyConfig` + per-strategy params validators + `OrderType` enum end-to-end (byte-exact vs the SMA_MACD oracle); typed signal records persisted and queryable. (completed 2026-06-09)
- [ ] **Phase 6: Order Matching Scenarios** — E2E golden-locked coverage of MARKET/LIMIT/STOP fills, bracket OCO lifecycle, same-bar double-trigger priority, gap-through, modify/cancel, and far-from-market no-fill.
- [ ] **Phase 7: Cost, Sizing & SLTP Scenarios** — E2E golden-locked coverage of fee models, slippage models (incl. not-on-limit), combined cash math, `FixedQuantity`/`RiskPercent`/over-cash sizing, and `PercentFromDecision`/`PercentFromFill` SL/TP exit outcomes.
- [ ] **Phase 8: Admission, Position Management & Cash Edges** — E2E golden-locked coverage of scale-in (pyramiding), partial scale-out, `max_positions` rejection, exit-then-re-entry, and the cash reservation/release lifecycle.
- [ ] **Phase 9: Multi-Entity, Robustness & Metrics Edges** — E2E golden-locked coverage of multi-ticker, multi-strategy, multi-portfolio cash isolation, contended cash, heterogeneous date spans, degenerate-run metrics, and cross-scenario determinism.

## Phase Details

### Phase 1: Codebase Map & Clarity Baseline
**Goal**: Produce the objective map of the codebase FIRST — yielding a committed, scoped fix-list (naming, visibility, seams) — so every later phase (harness shape, interface hardening, scenario design) builds on the map; and establish the opportunistic-cleanup standard that the rest of the milestone follows.

> **NOTE — current map already exists (do NOT regenerate); one input is historical.** The `gsd-map-codebase` output — `CONCERNS.md` + the 6 map files (`ARCHITECTURE/STACK/STRUCTURE/CONVENTIONS/TESTING`) — was refreshed at v1.0 close (Analysis Date 2026-06-08), *after* the last `itrader/` commit (`017bf72`); no engine code has changed since, so it is current. CLAR-01 = **harvest the fix-list from `CONCERNS.md`** (it already records only concerns still present post-refactor) plus the fresh map files — NOT a new `gsd-map-codebase` run; spot-check only if a doc looks stale.
> **Do NOT use the architecture review as a fix-list source** — `milestones/v1.0-ARCHITECTURE-REVIEW.md` is a PRE-v1.0 historical snapshot (2026-06-04); most of its 40 findings were fixed in v1.0. Reference only, no finding-by-finding re-audit.
> Also pull forward the residual cleanup items harvested from the archived `milestones/v1.0-COVERAGE-INDEX.md`: #7/#37 (bare `raise ValueError` in `portfolio.py`, off the golden path) and #10 (`portfolio_id: int` annotation carry-over on Signal/Order/Fill events — runtime-correct, annotation-only; may instead land in Phase 5 retype).

**Depends on**: Nothing (first phase — pure analysis, blocks nothing; informs all subsequent phases)
**Requirements**: CLAR-01, CLAR-02
**Success Criteria** (what must be TRUE):
  1. A committed, objective fix-list (naming, visibility, seam issues) is harvested from the existing `.planning/codebase/` map — no redundant regeneration of fresh docs.
  2. The opportunistic naming/visibility cleanup standard is established here as a CROSS-CUTTING practice — cleanup is applied only along paths a later phase already touches (no big-bang refactor) and is VERIFIED at milestone close, not in a standalone phase.
  3. No cleanup is performed in this phase itself (no paths are touched yet); the golden master is therefore unchanged here, and any later cleanup re-runs byte-exact — no oracle re-baseline.
**Plans**: 2 plans
- [x] 01-01-PLAN.md — Harvest the objective FIX-LIST.md (FL-NN schema, eligible-in-phase tags) from the existing codebase map [CLAR-01]
- [x] 01-02-PLAN.md — Establish the opportunistic-cleanup standard (4-gate checklist + milestone-close audit) and record it in PROJECT.md [CLAR-02]

### Phase 2: Data Ingestion
**Goal**: Bring three additional cryptos (ETH/SOL/AAVE) into the repo in the exact golden Binance-kline schema via a committed, re-runnable normalization script — so multi-ticker scenarios have real data — without touching the run-path loader.
**Depends on**: Phase 1 (the codebase map informs where the ingestion script and store boundaries sit)
**Requirements**: INGEST-01, INGEST-02, INGEST-03
**Success Criteria** (what must be TRUE):
  1. Running the committed normalization script converts a provider CSV (split `date`+`time`, lowercase columns) into the golden schema (single tz-aware `Open time` + `Open/High/Low/Close/Volume`) and is re-runnable to byte-identical output.
  2. ETHUSD, SOLUSD, and AAVEUSD datasets are committed in the normalized golden schema alongside BTCUSD.
  3. `CsvPriceStore` loads all four datasets with no code change (no run-path schema-detection branch added).
**Plans**: 1 plan
- [x] 02-01-PLAN.md — Normalize ETH/SOL/AAVE to the golden schema (relocate raw inputs, committed re-runnable script + make target, generate & validate the 3 CSVs, prove CsvPriceStore round-trip) [INGEST-01, INGEST-02, INGEST-03]

### Phase 3: Minimal Real Universe
**Goal**: Replace the membership stub with a real `membership`-from-availability primitive so the engine derives the active ticker set at time T from data, and prove it survives mid-run listings and differing end dates.
**Depends on**: Phase 2 (needs the multi-ticker datasets to exercise heterogeneous spans)
**Requirements**: UNIV-01, UNIV-02
**Success Criteria** (what must be TRUE):
  1. A `membership` primitive returns the set of active tickers at any time T derived solely from data availability (no screening/ranking logic).
  2. A backtest spanning a ticker that lists mid-run runs to completion with no crash and no look-ahead — bars before listing produce no fills.
  3. Assets with differing end dates are handled over the union window — an absent bar at T produces no fill for that ticker.
**Plans**: 3 plans
- [x] 03-01-PLAN.md — Add the `active_membership`/`is_active` span primitive beside `derive_membership` + barrel + UNIV-01 unit tests [UNIV-01]
- [x] 03-02-PLAN.md — Wire the span cache + span-aware warn loop (D-04) into the feed, strip the duplicate strategy-handler warning (D-05), invert the LATEUSD test [UNIV-02]
- [x] 03-03-PLAN.md — Add the oracle-dark `csv_paths` passthrough + the synthetic-fixture engine integration test (mid-run listing, differing ends, no look-ahead) [UNIV-02]

### Phase 4: E2E Harness & Framework
**Goal**: Stand up the whole-system E2E testing apparatus — the dedicated tree, marker, make target, and shared golden-compare harness — that every scenario wave (Phases 6-9) depends on.
**Depends on**: Phase 3 (membership primitive lets scenarios pin real ticker sets)
**Requirements**: E2E-01, E2E-02, E2E-03, E2E-04
**Success Criteria** (what must be TRUE):
  1. A dedicated `tests/e2e/` tree exists, subsystem-grouped, with an `e2e` marker registered in `pyproject.toml`, folder-derived auto-marking, and a working `make test-e2e` target.
  2. A shared harness (`tests/e2e/conftest.py`) runs the full engine on a given `(strategy, data)` pair and diffs trades/equity/summary against that scenario's golden fixtures.
  3. Each scenario is a self-contained leaf folder (purpose-built strategy + frozen golden fixtures) that runs warning-clean under `filterwarnings=["error"]`.
  4. The harness enforces the hand-verify-once-then-freeze discipline: a scenario's oracle is human-verified for correctness before it is committed as a golden fixture.
**Plans**: 3 plans
- [x] 04-01-PLAN.md — D-16 oracle-dark reporting extraction (build_summary/build_metrics_block/attach_slippage → itrader.reporting.summary) + FL-03 dead-skip cleanup [E2E-02]
- [x] 04-02-PLAN.md — Shared framework: e2e marker + folder-derived auto-marking + make test-e2e, and the run_scenario harness + --freeze in tests/e2e/conftest.py [E2E-01, E2E-02, E2E-04]
- [x] 04-03-PLAN.md — The one contrived canary leaf (SingleMarketBuy strategy + scenario.py/test/bars.csv/golden) with hand-verify-once freeze [E2E-02, E2E-03, E2E-04]

### Phase 5: Strategy Interface Hardening & Signal Storage
**Goal**: Put a pydantic config contract on the strategy base class and persist typed signal records — done EARLY, before new scenario strategies are written against the base class, and informed by the Phase 1 codebase map — while staying byte-exact against the SMA_MACD golden master.
**Depends on**: Phase 4 (so the hardened base class and signal store can be regression-checked through the E2E harness); informed by the Phase 1 map
**Requirements**: HARD-01, HARD-02, HARD-03, HARD-04, SIG-01, SIG-02
**Success Criteria** (what must be TRUE):
  1. A pydantic `BaseStrategyConfig` validates engine-facing declarations (timeframe, tickers, order_type, direction, allow_increase, max_positions, sizing_policy, sltp_policy), and a per-strategy params model with validators (e.g. `short_window < long_window`, positivity) replaces loose unvalidated attributes.
  2. `order_type` is the `OrderType` enum end-to-end — the stringly-typed `"market"` is removed.
  3. Re-running the golden master after the refactor is byte-exact (134 trades / `final_equity 46189.87730727451`), proving zero drift; the pure-alpha D-12 contract is intact (pydantic at construction only, `generate_signal` stays pure pandas).
  4. Strategy-generated signals are persisted as typed records (strategy id, ticker, action, time, sizing/sltp declarations, config snapshot) and are queryable for post-run inspection and E2E assertions.
**Plans**: 3 plans
- [x] 05-01-PLAN.md — Foundation primitives: SignalId + generate_signal_id (D-10), Timeframe enum (D-06), BaseStrategyConfig/SMA_MACDConfig/EmptyStrategyConfig + validators [HARD-01, HARD-02]
- [x] 05-02-PLAN.md — Config-constructor refactor (D-01), order_type enum end-to-end + boundary-parse collapse (D-04/FL-04), framework warmup guard (D-15), base __str__/__repr__ (D-14), strategy relocation (D-13), call-site migration [HARD-03, HARD-04]
- [x] 05-03-PLAN.md — SignalRecord entity + pluggable SignalStore seam (D-07/D-08), per-intent capture pre-fan-out (D-09), composition-root injection + post-run accessor (D-11/D-12), golden-run SIG-02 assertion [SIG-01, SIG-02]

### Phase 6: Order Matching Scenarios
**Goal**: Give the resting-order book, bracket/OCO lifecycle, and trigger/gap matching their first end-to-end golden coverage — each a tiny hand-verified scenario then regression-locked.

> **REMINDER — enable `parallelization` HERE (the scenario waves 6–9 benefit; phases 1–5 do not).** Each scenario is an independent leaf folder, ideal for wave-parallel execution in isolated worktrees. Preconditions: (1) Phase 4 shared infra (`tests/e2e/conftest.py`, `pyproject.toml` `e2e` marker, `Makefile` target) MUST be committed first — parallel scenario plans must not edit shared files or they'll merge-conflict; (2) parallelize generation but hand-verify/freeze oracles in deliberate batches, not 12-at-once. Flip via `/gsd:settings` → `parallelization`.

**Depends on**: Phase 4 (E2E harness)
**Requirements**: MATCH-01, MATCH-02, MATCH-03, MATCH-04, MATCH-05, MATCH-06, MATCH-07, MATCH-08
**Success Criteria** (what must be TRUE):
  1. MARKET next-bar-open fills, LIMIT in-bar-touch vs favorable-gap-through fills, and STOP pessimistic gap-down/gap-up fills each have a hand-verified, frozen E2E golden scenario.
  2. A full bracket (entry + SL + TP) OCO lifecycle is covered: children dormant while parent rests, arm on parent fill, sibling OCO-cancel on fill.
  3. Same-bar double trigger resolves by STOP-beats-LIMIT priority, and gap-clean-through (including a gap past both bracket legs) fills as specified.
  4. MODIFY (re-price/re-size) and CANCEL round-trips, plus a far-from-market limit that never fills, are handled and golden-locked.
**Plans**: TBD

### Phase 7: Cost, Sizing & SLTP Scenarios
**Goal**: Give fee models, slippage models, sizing policies, and SL/TP policies their first end-to-end golden coverage with cash math verified to the cent.
**Depends on**: Phase 4 (E2E harness); Phase 6 (reuses matching scenarios as the substrate for cost/SLTP fills)
**Requirements**: COST-01, COST-02, COST-03, COST-04, COST-05, COST-06, SIZE-01, SIZE-02, SIZE-03, SLTP-01, SLTP-02, SLTP-03
**Success Criteria** (what must be TRUE):
  1. percent and maker_taker fee models are covered end-to-end (maker vs taker distinguished on limit vs market), and a combined fee+slippage round-trip's cash math is verified to the cent.
  2. fixed and linear slippage models are covered, and slippage is proven NOT applied to limit fills.
  3. `FixedQuantity` and `RiskPercent` (off stop distance) sizing produce hand-verified fills, and over-cash sizing produces the audited insufficient-funds rejection.
  4. `PercentFromDecision` (priced at assembly) and `PercentFromFill` (anchored to the actual fill) SL/TP are each covered, exercising SL-hit, TP-hit, and held-to-end exit outcomes.
**Plans**: TBD

### Phase 8: Admission, Position Management & Cash Edges
**Goal**: Give the LONG-ONLY position-management directions v1.0 never exercised end-to-end — scale-in, partial scale-out, max-positions rejection, re-entry — plus the cash reservation/release lifecycle, their first golden coverage.
**Depends on**: Phase 4 (E2E harness); Phase 7 (sizing/SLTP scenarios feed multi-fill position management)
**Requirements**: ADMIT-01, ADMIT-02, ADMIT-03, ADMIT-04, CASH-01, CASH-02
**Success Criteria** (what must be TRUE):
  1. `allow_increase=True` scale-in (pyramiding) works end-to-end (v1.0 only validated the reject direction), and partial scale-out via `exit_fraction < 1` across multiple sells is golden-locked.
  2. Reaching `max_positions` produces the audited new-entry rejection, and a full exit followed by re-entry on the same ticker is covered.
  3. Insufficient funds produces the audited `cash_reservation` rejection, and the reservation is released on every terminal state (CANCELLED / REJECTED / REFUSED).
**Plans**: TBD

### Phase 9: Multi-Entity, Robustness & Metrics Edges
**Goal**: Close the breadth matrix with multi-ticker / multi-strategy / multi-portfolio runs and the robustness + degenerate-metrics edges, and prove determinism across every new scenario.
**Depends on**: Phase 2 (multi-ticker data), Phase 3 (membership), Phase 5 (config), Phase 4 (E2E harness); composite — sits at the end of the scenario waves
**Requirements**: MULTI-01, MULTI-02, MULTI-03, MULTI-04, ROBUST-01, ROBUST-02, ROBUST-03, ROBUST-04
**Success Criteria** (what must be TRUE):
  1. One strategy trading two cryptos (multi-ticker) and multiple strategies running simultaneously each have a hand-verified, frozen E2E scenario.
  2. A strategy fanned out to >1 portfolio shows per-portfolio cash isolation, and two strategies competing for the same portfolio's cash resolve correctly.
  3. A sparse/absent bar produces no fill and no crash, and heterogeneous date spans (asset enters mid-run; differing end dates) are handled over a union window.
  4. No-trade / flat / losing runs produce valid metrics (no NaN, no div-by-zero in Sharpe/drawdown/profit-factor), and a double-run is byte-identical across all new scenarios.
**Plans**: TBD

## Progress

| Phase | Milestone | Plans Complete | Status | Completed |
|-------|-----------|----------------|--------|-----------|
| 1. Codebase Map & Clarity Baseline | v1.1 | 2/2 | Complete   | 2026-06-09 |
| 2. Data Ingestion | v1.1 | 1/1 | Complete   | 2026-06-09 |
| 3. Minimal Real Universe | v1.1 | 3/3 | Complete   | 2026-06-09 |
| 4. E2E Harness & Framework | v1.1 | 3/3 | Complete   | 2026-06-09 |
| 5. Strategy Interface Hardening & Signal Storage | v1.1 | 3/3 | Complete   | 2026-06-09 |
| 6. Order Matching Scenarios | v1.1 | 0/0 | Not started | - |
| 7. Cost, Sizing & SLTP Scenarios | v1.1 | 0/0 | Not started | - |
| 8. Admission, Position Management & Cash Edges | v1.1 | 0/0 | Not started | - |
| 9. Multi-Entity, Robustness & Metrics Edges | v1.1 | 0/0 | Not started | - |

## Backlog

> Future **milestone-level** seeds — intent + rationale only, NOT detailed plans.
> **Logical promotion order: N+1 → N+2 → N+3 → N+4** (the `N+x` labels carry the
> dependency order; the `999.x` decimals are just stable IDs and need not match the
> order). Promote one at a time with `/gsd:review-backlog` (or start it via
> `/gsd:new-milestone`); defer detailed planning until promotion so each milestone's
> findings can reshape the next.
>
> **Asset focus: crypto-first** (locked 2026-06-08). Crypto is USD-quoted and 24/7, so
> multi-currency accounting and trading-calendar / corporate-action work are deferred
> indefinitely — see the "Deferred: multi-asset" note at the end.
>
> **N+1 (Backtest Trustworthiness: Breadth) was promoted to active milestone v1.1 on
> 2026-06-09** — see the `## Phases` section above. Its former backlog seed (Phase 999.1)
> is retired.

### Phase 999.4: N+2 — Margin, Leverage, Shorts & Trailing Stops (crypto) (BACKLOG)

**Goal:** The matching-engine / risk-execution milestone. Build the margin/liquidation
model the engine has deliberately deferred (D-08/D-09, DEF-01-C), unblocking shorts and
leverage, AND add engine-native trailing stops — all are stateful resting-order changes to
the same `MatchingEngine` surface, so they're done in one pass and share one golden master +
cross-validation, like M5.
**Requirements:** TBD
**Plans:** 0 plans

Scope (intent only):
- **Margin / liquidation model** in `MatchingEngine` + cash/position accounting — today
  there is NO liquidation model (DEF-01-C): an un-liquidated short can drive equity
  negative. Add maintenance margin + liquidation.
- **Unblock shorts** — remove the `LONG_ONLY`-only guard in `StrategiesHandler.add_strategy`
  AND fix the CR-01 cover-arm hole (`_resolve_signal_quantity` has no BUY-to-cover arm for
  a `SHORT_ONLY` book — a cover would fall through to entry sizing and flip the book long).
- **Leverage** + **levered Kelly** (fraction > 1 becomes expressible once margin exists).
- **Funding/carry** — crypto perp funding-rate accounting (the crypto-first analogue of
  forex swap / equity borrow).
- **Engine-native trailing stop** — new `TRAILING_STOP` `OrderType` + `MatchingEngine`
  ratchet logic (track running extreme, move the resting stop per bar). For the
  risk-management-heavy strategies. Look-ahead-safe per the `bar_feed.py` contract. Levered
  Kelly (>1) also unlocks here once margin exists.
- Config hooks already exist and are currently off: `allow_short_selling`, `enable_margin`
  (`config/portfolio.py`).
- **Real long/short PAIR TRADING** (flagship validation) — market-neutral cointegration/spread
  strategy: long one leg, short the other. Deferred here from v1.1 because it inherently needs
  shorts; it is the natural first real use of the short side once the guard is removed. (v1.1
  validates only a long-only multi-ticker proxy, if any.)

Rationale: shorts are the "short half" of the breadth N+1 wanted, but they are gated on
this accounting work — so it must come right after N+1, before infra/live. Crypto-first
keeps it tractable (no multi-currency, no borrow-locate).

**Design note — trailing stops on venues WITHOUT native support (spans N+2 build → N+4 live):**
Native trailing is NOT universal (Binance spot lacks a clean native trailing; IBKR stocks
DO have `TRAIL`; many smaller venues / DEXs have none; ccxt coverage is spotty and semantics
vary — absolute vs % vs callback-rate, trigger basis last/mark/index). So make trailing a
**declared intent + an exchange capability**, decided in the execution layer (NOT the
strategy):
- Add a capability seam to `AbstractExchange` (e.g. `supports(OrderType.TRAILING_STOP)`).
  **Native-first** (survives client disconnect, lower latency, no rate-limit churn);
  **synthetic-fallback** otherwise.
- **Synthetic = always keep a REAL resting stop server-side; only the *ratchet* is
  client-side.** Place a normal STOP, recompute the trail each bar (ratchet favorable-only),
  and `MODIFY` the resting stop when the move exceeds a step threshold (rides the existing
  `OrderHandler.modify_order` → `OrderEvent(MODIFY)` round-trip). The venue fills the plain
  stop natively — the engine is NOT in the trigger path.
- Safety property: engine downtime ⇒ trail freezes but the last stop still protects. NEVER
  do the naive version (no resting stop; engine watches price and fires a market order on
  trigger) — downtime = zero protection.
- Risks to handle: modify churn vs rate limits (step threshold); cancel-replace gap on
  venues w/o atomic modify (place-new-then-cancel-old); overnight/weekend gaps (stop-limit
  caps fill price but risks no fill); venue min-distance rules.
- Backtest (`MatchingEngine`) models the IDEAL engine-native trail; synthetic-live has
  modify latency / step / gap behavior → backtest is slightly optimistic (a known sim-to-live
  gap to flag at N+4). Backtest and live should SHARE the trail-computation logic; only "how
  the stop rests" differs.

Plans:
- [ ] TBD (promote with /gsd:review-backlog when ready)

### Phase 999.2: N+3 — Persistence & Performance (BACKLOG)

**Goal:** Durable state + acceptable latency — the infra prerequisites for live trading.
Must come AFTER the correctness work (N+1, N+2) so we are not optimizing/persisting
unvalidated behavior.
**Requirements:** TBD
**Plans:** 0 plans

Scope (intent only):
- **#4 permanent PostgreSQL storage** (orders, signals, fills, equity).
  `PostgreSQLOrderStorage` is currently a `NotImplementedError` placeholder.
- **#5 profiler-guided performance pass** (profiler already used to spot hotspots).
- **#1 continued** — structural cleanup that the live-mode transition specifically demands.

Rationale: persistence + performance are cross-cutting infra, cleaner done together than
bolted on during the live push.

Plans:
- [ ] TBD (promote with /gsd:review-backlog when ready)

### Phase 999.3: N+4 — Live Trading Readiness (capstone) (BACKLOG)

**Goal:** Land the new operating mode as one coherent, testable thing. Do last — depends on
validated multi-scenario behavior (N+1), the margin model (N+2), durable storage + latency
(N+3), and a streaming data engine.
**Requirements:** TBD
**Plans:** 0 plans

Scope (intent only):
- **#6 real-time data engine** ready for live.
- **#2 live execution engine.**
- **#7 production-ready universe / screener.**

Plans:
- [ ] TBD (promote with /gsd:review-backlog when ready)

> **Deferred: multi-asset (forex / equities / ETF).** Crypto-first (locked 2026-06-08)
> removes the near-term need. When revisited, this is itself ≥1 milestone and splits into:
> (a) an instrument/contract-spec abstraction (partly folded into N+1 config typing);
> (b) multi-currency accounting (quote→`base_currency` conversion) — needed for forex;
> (c) trading calendars/sessions + corporate actions (splits/dividends) — needed for
> equities/ETF, and a data-engine concern that pairs with N+4's #6.
>
> **Cross-cutting tooling note:** do NOT add third-party graphify / Understand-Anything
> tools — use the native `gsd-map-codebase` + `gsd-graphify`, which write artifacts into
> `.planning/` that integrate with the workflow and that Claude can read directly.

# Milestones

## v1.5 — Backtest Performance Optimization (Shipped: 2026-06-26)

**Scope:** 8 phases (Phases 1–8, numbering reset), 26 plans. Promoted from the **performance half**
of Backlog 999.2 (split out from Persistence, which becomes its own following milestone). The
performance analog of v1.2 Consolidation: a **behavior-preserving** milestone — profiler-ranked,
oracle-gated hot-path optimizations that make the SMA_MACD backtest materially faster while **changing
no numbers**. Phases 7–8 were added 2026-06-25 from post-phase re-profiles. The spike
(`perf/results/PERF-BASELINE-RESULTS.md`) IS the milestone's research.

**Delivered:** The backtest hot path is faster across the board with the engine's numbers untouched.
Every optimization phase was gated on BOTH (a) the byte-exact SMA_MACD oracle staying green AND (b) a
measured **same-machine-A/B** W1 wall-clock improvement, re-frozen after the phase (the milestone
deliberately attributes wins by A/B rather than the frozen-baseline diff, because the absolute W1
number shifted mid-milestone when the Phase-1 benchmark-probe quadratic bug was fixed). The big wins:
the #1 order-storage linear scan (~37% CPU) replaced by derived secondary indexes; the per-bar
realised-PnL re-summation (~13%) collapsed to a running Decimal accumulator; the full-window `ta`
indicator rebuild (~24%) replaced by hand-written O(1) stateful SMA/EMA/MACD/RSI recurrences on a
shared recent-bars feed; per-tick `searchsorted` window slicing replaced by a monotonic int64 cursor;
a latent O(n²) snapshot-retention copy killed via `deque(maxlen)`; and a `msgspec.Struct` migration of
the `Bar` + full event chain (Decimal contract intact). Final W1 baseline re-frozen at **15.7 s /
152.8 MB** on a verified-cool box.

**Definition of done — achieved:** SMA_MACD oracle **byte-exact** (134 trades /
`final_equity 46189.87730727451`) across all 8 phases — Phase 5 carried a deliberate re-baseline
carve-out (cross-validation gated) that proved **unnecessary**, the oracle held byte-exact · full
suite **1340/1340** green, zero warnings · `mypy --strict` clean · Decimal end-to-end (no new
float-for-money — every fix is *less repeated work*) · single UUIDv7 · determinism double-run
byte-identical · gate-(b) cool-machine re-freeze done.

**Key accomplishments:**

- **Perf measurement harness (TOOL-01/02/04, Phase 1)** — a root-Makefile `perf-*` command surface
  (`perf-w1`/`perf-w2`/`perf-baseline`/`perf-profile`) with two cleanly separated modes (a
  profiler-free clean benchmark that produces the gated number, and a separate Scalene
  `--cpu-only --program-path` profile), a committed machine-readable `W1-BASELINE.json` + soft
  regression guard (gate (b) = ≥5% wall-clock). TOOL-03 cross-validation was dropped — a
  behavior-preserving milestone proves correctness by *invariance* (the oracle), not external agreement.
- **Order-storage indexing (PERF-01, Phase 2)** — `get_orders_by_status`/by-portfolio/active queries
  resolve via derived secondary indexes maintained over the flat `{id: order}` dict (which stays the
  D-20 source of truth), eliminating the single largest W1 hotspot (~37% CPU); the `OrderStorage`
  interface is designed so a future Postgres backend satisfies the same contract.
- **Running PnL accumulator (PERF-02, Phase 3)** — realised PnL maintained as a running Decimal
  accumulator updated on position close, removing the per-bar re-summation over all positions (~13% CPU),
  mathematically equal to the prior sum at every bar.
- **Hot-path discipline (PERF-03/04, Phase 4)** — hot-loop logging level-gated + per-bar `debug()`
  removed + by-design admission-rejection spam demoted; `get_type_hints` memoized per class in
  `Strategy.to_dict` — behavior-only, no numeric or log-content surface the oracle/e2e observe.
- **Stateful indicators + shared bar cache (PERF-05, Phase 5, FRAGILE/LAST)** — SMA/EMA/MACD/RSI
  rewritten as hand-written O(1) recurrences (dropping `ta` on the runtime path), feed-centric with
  per-symbol/per-pair state on a shared recent-bars feed, then the per-tick master-frame window slice
  cut; look-ahead-safe and deterministic, oracle held byte-exact under the re-baseline carve-out
  (~24% CPU, the largest single chunk).
- **Bar-feed window copies (PERF-06, Phase 6, optional)** — view-returning `window()` + memoized
  offset alias + a monotonic int64 cursor replacing per-tick `searchsorted`, with all 7 look-ahead
  bar-timing rules preserved (most visible on the W2 symbol sweep).
- **Per-bar metrics & timestamp polish (PERF-07, Phase 7, byte-exact)** — memoized `_aligned`
  (bounded `lru_cache`), dropped the per-bar snapshot debug log's eager arg-eval, snapshot retention →
  `collections.deque(maxlen)` (killing a latent O(n²)), and removed the per-bar metrics-cache churn
  (~24% W1 CPU combined; surfaced by the post-Phase-6 re-profile).
- **Hot-path fusion, bar prebuild & msgspec (PERF-08, Phase 8, byte-exact)** — `Position`
  net-quantity/avg-price fill-invalidated cache (+15% W1), `Strategy.to_dict` static-snapshot cache
  (+2% W1), `itertuples` `Bar` prebuild (dropping `iterrows`' ~69k throwaway Series), and a
  `msgspec.Struct` migration of the `Bar` + full event chain (Decimal contract intact) that cleared a
  measure-first ≥5% W1 A/B. **Keep-only-measured discipline:** the naive mark-to-market "fusion"
  (Req 1) was A/B-measured as a **−15% W1 regression** and **REVERTED** — the correct single-pass
  design is deferred (`.planning/todos/pending/single-pass-portfolio-valuation.md`, profile-first gated).

**Audit:** `tech_debt` status — 11/11 v1 requirements satisfied (3-source cross-referenced; TOOL ×3 +
PERF ×8, TOOL-03 dropped), 8/8 phases verified, integration clean (the 8 independent hot-path
optimizations compose; oracle byte-exact), full suite 1340/1340 green, 0 blockers. The non-`passed`
status reflected only well-tracked, non-blocking tech debt — chiefly the PERF-07/08 traceability
collision, **resolved at this close**. See `milestones/v1.5-MILESTONE-AUDIT.md`.

**Tech-debt resolved at close:** the PERF-07/PERF-08 requirement-ID collision (delivered Phase 7/8
work kept PERF-07/08; the originally-deferred items renumbered PERF-09/PERF-10 — REQUIREMENTS.md
traceability updated) and the stale `human_needed`/`partial` status on Phase 01 verification (manual
profiler inspection, owner-approved-deferred) and Phase 03 verification/UAT (cool-machine re-freeze,
completed via quick task 260625-0qj + Phase 8) were all cleared. **Deferred (carried forward):** the
correct single-pass per-bar portfolio valuation (profile-first gated, future phase); advisory Nyquist
VALIDATION.md gaps on phases 03/04/08 (the byte-exact oracle + same-machine A/B perf gate are the real
regression lock and ran green every phase).

**Archived:** `milestones/v1.5-ROADMAP.md`, `milestones/v1.5-REQUIREMENTS.md`, `milestones/v1.5-MILESTONE-AUDIT.md`.

---

## v1.4 — Margin, Leverage, Shorts & Trailing Stops (Shipped: 2026-06-22)

**Scope:** 7 phases (Phases 1–6 + inserted 05.1), 35 plans, 45 tasks. Promoted from N+2 Backlog
(999.4). Builds the crypto-derivatives surface — per-symbol instruments, reserved-margin leverage,
first-class shorts with borrow carry, isolated-margin liquidation, engine-native trailing stops,
short scale-in, and a market-neutral pair flagship — on top of the v1.3 authoring/contract surfaces.

**Delivered:** The engine now trades on margin. A frozen per-symbol `Instrument` value object is the
single source of price/quantity scales, max-leverage, and maintenance-margin-rate, consumed by all
downstream margin/liquidation/carry code. Positions open on reserved margin
(`initial_margin = notional / leverage`) with effective leverage threaded
signal→order→fill→transaction→position across MARKET/LIMIT/STOP; over-margin admission routes through
the audited REJECTED path. The `LONG_ONLY` guard is gone — shorts are first-class, with short PnL and
daily borrow-carry settling through the accounting core. A maintenance-margin breach is checked on bar
close (the honest daily-OHLCV cadence) and liquidates with capped loss. `TRAILING_STOP` is a
first-class order type whose `MatchingEngine` ratchets favorably-only from closed-bar extremes. A
short can be increased (same-side SELL add) through the side-agnostic SCALE-IN branch with an
admission-side solvency gate symmetric to the long arm. Finally, a market-neutral ETH/BTC pair
strategy runs end-to-end (94 round trips, both legs) through the unchanged Phase 2–4 accounting core —
demonstrating the short side with zero new correctness branches.

**Re-baseline discipline (two disciplines, honored):** the SMA_MACD spot oracle held byte-exact
(134 trades / `final_equity 46189.87730727451`) across all 7 phases — every margin/shorts/leverage
path is oracle-dark on the spot arm. The three result-changing re-baselines (accounting core P4,
trailing P5, short scale-in P5.1) were each frozen ONLY under explicit owner sign-off (tiziaco,
2026-06-16 / 06-17) plus external cross-validation (`backtesting.py` 0.6.5 / `backtrader` 1.9.78.123).
The pair flagship is explicitly additive (a stability snapshot, NOT a correctness oracle) and
re-baselines nothing.

**Definition of done — achieved:** SMA_MACD oracle byte-exact (134 / 46189.87730727451) ·
full suite green (1193) · `mypy --strict` clean (187 source files) · Decimal end-to-end, no new
float-for-money; single UUIDv7 ID scheme · determinism double-run byte-identical · all owner-gated
goldens signed with dated attribution · flagship pair strategy runs both sides end-to-end.

**Key accomplishments:**

- **Instrument value object (INST-01/02/03, Phase 1)** — a frozen per-symbol `Instrument` +
  `derive_instruments` ladder behind a `Universe` facade, the single source of price/quantity scales,
  `max_leverage`, and `maintenance_margin_rate` injected into every margin/liquidation/carry consumer.

- **Margin accounting & leverage (MARGIN-01/02/03, LEV-01/02/03, Phase 2)** — `enable_margin`-branched
  reservation (`notional / L` + commission) with over-margin routed to the audited REJECTED path and
  an `f > 1` admission gate; a position-keyed lock-and-settle model where opening debits only
  commission + locks `aggregate_notional / L` and closing settles realized PnL pro-rata; effective
  leverage threaded end-to-end for MARKET/LIMIT/STOP, with over-close fills failing loud.

- **First-class shorts + borrow carry (SHORT-01/02/03, CARRY-01, Phase 3)** — the `LONG_ONLY` guard
  removed via a side-agnostic cover-arm with clamp-to-flat; short PnL and daily borrow-carry (marked
  against business-time bars through the Universe) settle through the hardened margin/settlement seam.

- **Isolated-margin liquidation + cross-validation re-baseline (LIQ-01/02/03, XVAL-01, Phase 4)** —
  maintenance-margin breach checked on bar close, capped-loss liquidation, deterministic breach
  collection; the owner-gated accounting-core golden (7 scenario leaves) frozen under sign-off
  (tiziaco, 2026-06-16) with the `set_order_storage` seam reconciling the live order mirror.

- **Engine-native trailing stops (TRAIL-01/02/03, Phase 5)** — a first-class `TRAILING_STOP` order
  type ratcheting favorably-only from closed-bar extremes in a leak-free engine-owned side-table,
  declared via `PercentFromFill` (SL leg seeded from entry fill, OCO intact, order handler never
  matches), cross-validated EXACTLY against both gating oracles and frozen under sign-off
  (tiziaco, 2026-06-17); the production path's D-TRAIL-7 viability gate hardened to fail loud.

- **Short scale-in + pair-trading flagship (SCALE-01/02/03, PAIR-01, Phases 05.1 & 6)** — a same-side
  SELL add settles through the existing side-agnostic SCALE-IN branch with an admission-side solvency
  gate symmetric to the long arm (frozen under sign-off, tiziaco, 2026-06-17); a market-neutral ETH/BTC
  pair strategy runs end-to-end (94 round trips, LONG + SHORT) through the unchanged accounting core,
  the flagship demonstration of the short side with zero new engine branches.

---

## v1.3 — Engine Surface Completion (Shipped: 2026-06-14)

**Scope:** 6 phases (Phases 1–6, numbering reset from v1.2), 20 plans. Completes the
signal/order contracts, the composition/config interface, and the declared-indicator +
strategy-authoring surface — the result-changing / new-framework items deferred out of v1.2
Consolidation (promoted Backlog 999.5), BEFORE N+2 builds margin/shorts on these same surfaces.

**Delivered:** The engine's authoring and contract surfaces completed. A strategy is now
authored as class-attribute params (overridable via `**kwargs`, `UnknownParamError` on unknown
kwargs) with a re-runnable idempotent `init()`; indicators are declared in `init()` with
auto-derived `warmup`/`max_window`; the system composes through an engine-level API
(`SystemSpec`/`build_backtest_system`) with construction-time `ExchangeConfig` threading, a new
`OrderConfig`, and a uniform `update_config` on all 7 handlers; the signal contract carries
per-intent entry price + `order_type` with `Side`-typed action and single snapshot threading;
and run-end resting orders now expire (`EXPIRED` wired through all four arms) with the dead
`create_order` second path removed.

**Re-baseline discipline (two disciplines, honored):** byte-exact phases (1–4) held the BTCUSD
oracle (134 trades / `final_equity 46189.87730727451`) byte-for-byte — zero drift; owner-gated
phases (5–6) re-baselined only under explicit owner sign-off (tiziaco, 2026-06-13) + external
cross-validation (`backtesting.py` 0.6.5 / `backtrader` 1.9.78.123). The SMA_MACD oracle itself
stayed byte-exact end-to-end: Phase 5 added an additive owner-signed LIMIT-entry golden; Phase 6
re-baselined exactly 3 e2e leaves' run-end disposition (`PENDING→EXPIRED`), equity-neutral.

**Definition of done — achieved:** `pytest tests/integration` oracle byte-exact (134 /
46189.87730727451) · `pytest tests/e2e -m e2e` green (59 leaves incl. the new LIMIT cross-val leaf) ·
full suite green (995) · `mypy --strict` clean (182 source files) · no new float-for-money; single
UUIDv7 ID scheme · determinism double-run byte-identical.

**Key accomplishments:**

- **Strategy authoring surface (STRAT-01, Phase 2)** — class-attribute params replacing the frozen
  pydantic config + manual field-copy; engine-facing names with defaults on the base, alpha knobs
  on the subclass, all overridable at construction via `**kwargs`; base rejects unknown kwargs
  loudly (`UnknownParamError`); re-runnable idempotent `init()` hook that Phase 4 consumes.

- **Declared-indicator framework (IND-01, Phase 3)** — indicators registered declaration-only in
  `init()`, evaluated lazily per-tick; base auto-derives `warmup`/`max_window` from the recipes
  (hand-set lines gone); look-ahead-safe free-function `crossover`/`crossunder`. Byte-exact by
  construction (derived `warmup == max_window == 100`).

- **Composition & config interface (COMP-01/02, Phase 4)** — engine-level composition API
  (`SystemSpec` + `build_backtest_system` + `compose_engine`) with construction-time `ExchangeConfig`
  threading (replacing the Phase 7 D-14 conftest seam) and a new `OrderConfig`; a uniform
  `update_config` (merge → `model_validate` → atomic-swap) on all 7 handlers/managers, applied
  between event cycles for live runtime reconfig.

- **Signal contract completion + reconcile streamline (SIG-01/02/03 + RECON-01, Phase 5 — FRAGILE,
  owner-gated)** — per-intent limit/stop ENTRY price + per-intent `order_type` threaded
  `SignalIntent → SignalEvent → Order.new_limit/stop_order`; `Order.action`/`_PendingBracket.action`
  typed `Side` with the position snapshot threaded once; `on_fill` reconciliation streamlined into
  named helpers while the idempotent terminal-release invariant held. Proven by an owner-signed,
  externally cross-validated LIMIT-entry golden.

- **Order lifecycle / time-in-force (LIFE-01, Phase 6 — owner-gated)** — run-end resting orders
  transitioned to `EXPIRED` via a non-cascading sweep across all four arms (`expire_all_resting` →
  `OrderCommand.EXPIRE` → exchange EXPIRE arm → `FillEvent(EXPIRED)` → reconcile EXPIRED arm); the
  dead, unvalidated `create_order` second signal→order path removed, collapsing to one validated
  `process_signal` path.

- **Engine hygiene (HYG-01, Phase 1)** — SAFE byte-exact cleanup with no run-path touch: private
  `_storage` test asserts rewritten to public query APIs, stale mypy override removed, dead float
  constants deleted, `validate_transaction_data` retyped off `float` (Decimal-money policy), and
  the three v1.2 Phase-6 review residues resolved.

**Milestone audit:** 10/10 requirements satisfied, 6/6 phases verified passed, 5/5 cross-phase
seams wired, 5/5 E2E flows complete (`milestones/v1.3-MILESTONE-AUDIT.md`). Closed as `tech_debt`
(no blockers); the flagged Phase-6 robustness warnings (WR-01 by-design, WR-02/WR-03 fixed in
PR #42) and doc-tracker lag were reconciled before close.

**Known deferred items at close:** 5 quick-tasks flagged `missing` by the `audit-open` ledger were
verified canonically complete (`status: complete`) and acknowledged; 4 predate v1.3. Nyquist Wave-0
partial on phases 2/3/6 (strong behavioral net via oracle + 59-leaf e2e + `mypy --strict`). See
STATE.md → Deferred Items and `milestones/v1.3-MILESTONE-AUDIT.md`.

---

## v1.2 — Consolidation (Shipped: 2026-06-12)

**Scope:** 6 phases (Phases 1–6, numbering reset from v1.1), 23 plans, ~36 tasks. A
behavior-preserving cleanup milestone — the 999.x backlog phases (Engine Surface Completion + N+2…N+4)
remain future milestones.

**Delivered:** The engine put in order — the v1.1 cleanup-review backlog
(`V1.2-CLEANUP-REVIEW.md`, 46 findings) and the `CONCERNS.md` dead/fragile/tangled debt cleared
**byte-exact against the golden master** (134 trades / `final_equity 46189.87730727451`), so the
next milestone's engine-surface features build on a clean, decomposed foundation. Re-baselined
nothing. The headline: `order_manager.py` decomposed from a 1279-line god-module into a 210-line
coordinator + `admission/`/`brackets/`/`lifecycle/`/`reconcile/` collaborators as pure code-motion,
with the FRAGILE fill-reconciliation / reservation-release path byte-for-byte unchanged.

**Definition of done — achieved:** `pytest tests/integration` byte-exact oracle held (134 /
46189.87730727451) · `pytest tests/e2e -m e2e` 58/58 green (no leaf re-baselined) · full suite
green (851) · `mypy --strict` clean across 172 source files · no new float-for-money; single UUIDv7
ID scheme (zero `uuid4()` on the run path) · `order_manager.py` decomposed with no semantics change ·
determinism double-run byte-identical.

**Key accomplishments:**

- **Golden master held byte-exact through the entire milestone** — 134 trades /
  `final_equity 46189.87730727451`, oracle 3/3, e2e 58/58, `mypy --strict` clean (172 files). The
  behavior-preserving guarantee never broke across 6 phases / 23 plans.

- **`order_manager.py` god-module decomposed (MOD-01, Phase 6 — FRAGILE, isolated, LAST):**
  1279 → 210-line thin coordinator into `admission/`/`brackets/`/`lifecycle/`/`reconcile/`
  collaborators as pure code-motion; `on_fill` moved as one indivisible intact unit; the
  terminal-status / `should_release` / `finally`-release interplay byte-for-byte unchanged; cross-bucket
  seams rewired via coordinator callback + injected `BracketManager` (no sibling edges, no circular import).

- **Locked-decision conformance closed (Phase 2):** `Optional[Decimal]` money API + Decimal
  `_min/_max_order_size` end-to-end (no float-for-money at boundaries); retired the lingering
  `uuid4()` second ID scheme to single UUIDv7 (`CorrelationId` NewType). The W2-10 "latent TypeError"
  was re-adjudicated as a misdiagnosis (D-07) — comparison works in Py3; DEC-02 reframed as
  consistency, not a crash fix.

- **Hot-path performance (Phase 3):** eliminated per-tick storage copies (D-19 single-writer) with
  `snapshot_count()`/`get_latest_snapshot()` accessors, redundant `Decimal(str(Decimal))` re-wraps,
  duplicated per-tick work, and per-tick Bar/MACD churn (prebuilt Bars + MACD-in-guard) — all
  bit-identical.

- **Type modeling hardened (Phase 4):** frozen/slots decision DTOs; class-based string enums
  (`OrderStatus`/`OrderCommand` + `ErrorSeverity`/`OrderOperationType`/`OrderTriggerSource`/`market_execution`)
  with `assert_never` dispatch; `OrderId`/`PortfolioId` NewTypes on public APIs; `BaseStrategyConfig`
  co-located in `config/`.

- **Naming & encapsulation (Phase 5):** `events_queue→global_queue`, PascalCase strategies +
  `*_window` config, public `routes` accessor + `register_symbol()`/`update_config` seam, six tests
  re-asserted through public query APIs (unblocks backend swaps).

**Audit:** `passed` status — 18/18 requirements satisfied (3-source cross-validated), 6/6 phases
verified, 18/18 cross-phase integration seams wired, 1/1 E2E flow complete, 0 blockers. See
`milestones/v1.2-MILESTONE-AUDIT.md`.

**Known deferred items at close: 4** (the 4 completed v1.2 quick tasks — canonically complete,
flagged only by the `gsd-sdk` SDK-port filename bug, same as v1.1; each carries `status: complete`
frontmatter; see STATE.md → Deferred Items). Non-blocking tech debt: DEF-02-02 (raw `Decimal` in
`simulated.py` diagnostic dicts — cosmetic), SUMMARY frontmatter omits 6 REQ-IDs (bookkeeping only),
Nyquist Wave-0 not run (behavioral net = oracle + 58 e2e + mypy strict). Result-changing /
new-framework work (SIG/COMP/IND/LIFE) deferred to Engine Surface Completion (Backlog 999.5).

**Archived:** `milestones/v1.2-ROADMAP.md`, `milestones/v1.2-REQUIREMENTS.md`, `milestones/v1.2-MILESTONE-AUDIT.md`.

---

## v1.1 — Backtest Trustworthiness: Breadth (Shipped: 2026-06-10)

**Scope:** 9 phases (Phases 1–9, numbering reset from v1.0), 28 plans, 53 tasks. The 999.x backlog phases (N+2…N+4, plus the v1.2 Engine Surface Completion seed) are future milestones, not part of v1.1.

**Delivered:** Trustworthy, regression-locked backtest behavior extended across the engine's *entire* feature surface — resting-order book, brackets/OCO, fee/slippage variants, SLTP policies, sizing, scale in/out, and multi-strategy/multi-ticker/multi-portfolio runs — **without re-baselining the v1.0 golden numbers**. The hardening gate before any margin/live work.

**Definition of done — achieved:** full feature surface exercised by a 58-leaf frozen E2E matrix (`tests/e2e/`, `e2e` marker, `make test-e2e`, per-scenario golden fixtures, shared harness) + the BTCUSD oracle (134 trades / `final_equity 46189.87730727451`, byte-exact) · `pytest tests/e2e -m e2e` 58 passed · `pytest tests/integration` 12 passed · `mypy --strict` clean across 161 source files · behavior-preserving guarantee held (no oracle re-baseline). LONG-ONLY throughout; shorts gated to v1.2.

**Key accomplishments:**

- **E2E harness + full coverage matrix (Phases 4, 6–9):** stood up the dedicated `tests/e2e/` apparatus (registered `e2e` marker, folder-derived auto-marking, `make test-e2e`, shared golden-compare harness with hand-verify-once-then-freeze discipline), then filled it to a 58-leaf frozen matrix spanning matching, cost, sizing, SLTP, admission, cash, multi-entity, and robustness — every leaf hand-verified once against the real `TradingSystem` (no mocks) before freezing.
- **Order-matching + cost/sizing/SLTP surface proven (Phases 6–7):** golden-locked the resting-order book end-to-end — MARKET/LIMIT/STOP fill shapes, bracket OCO lifecycle, same-bar STOP-beats-LIMIT priority, gap clean-through/past-both-legs, MODIFY/CANCEL round-trips, far-from-market no-fill (MATCH-01..08); plus percent & maker/taker fees, fixed & linear slippage (not-on-limit), combined cash math to the cent, `FixedQuantity`/`RiskPercent`/over-cash sizing, and `PercentFromDecision`/`PercentFromFill` SL/TP exit outcomes (COST/SIZE/SLTP).
- **Admission, position management & cash edges (Phase 8):** first end-to-end coverage of the LONG-ONLY directions v1.0 never exercised — scale-in (pyramiding via `allow_increase=True`), partial scale-out, `max_positions` rejection, exit-then-re-entry — plus the full cash reservation/release lifecycle across CANCELLED/REJECTED/REFUSED, fronted by a new opt-in oracle-dark cash-ledger snapshot serializer.
- **Strategy interface hardening + signal storage (Phase 5):** collapsed the strategy constructor to a single frozen pydantic `BaseStrategyConfig` + per-strategy params validators (`short_window < long_window`, positivity), made `order_type` the `OrderType` enum end-to-end, and added a typed, queryable `SignalRecord` store (own UUIDv7 `SignalId` + config snapshot, pluggable seam) — all byte-exact vs the SMA_MACD oracle, pure-alpha D-12 contract intact.
- **Data ingestion + minimal real universe (Phases 2–3):** a committed, re-runnable normalization script brings ETH/SOL/AAVE into the byte-identical golden Binance-kline schema (loaded through the UNCHANGED `CsvPriceStore`); a real `membership`-from-availability primitive (`is_active`/`active_membership`) replaces the stub and is proven over mid-run listings and differing end dates with no crash and no look-ahead.
- **Multi-entity breadth + robustness + determinism (Phase 9):** multi-ticker, multi-strategy, multi-portfolio cash isolation, contended-cash contention, sparse-bar and union-window real-data spans, degenerate-run metric finiteness (no NaN/inf), and cross-scenario double-run byte-identity (MULTI-01..04, ROBUST-01..04).
- **Codebase clarity, scoped (Phase 1, cross-cutting):** one `gsd-map-codebase` pass → objective `FIX-LIST.md`; the opportunistic-cleanup standard (4-gate checklist) established and applied along touched paths only — no big-bang refactor, no oracle re-baseline — verified at milestone close (CLAR-01/02).

**Audit:** `passed` status — 51/51 requirements satisfied, 9/9 phases verified, 58/58 e2e + 12/12 integration seams, 58/58 flows, 0 blockers. Phase 9 WR-01 (determinism frame scope) fixed in code; WR-02 (`profit_factor: inf` on genuinely all-win goldens) owner-ratified carve-out. See `milestones/v1.1-MILESTONE-AUDIT.md`.

**Known deferred items at close: 4** (the 4 completed v1.1 quick tasks — canonically complete, flagged only by a `gsd-sdk` v1.42.3 SDK-port filename bug; see STATE.md → Deferred Items). Tracked optional hygiene: formal Nyquist Wave-0 incomplete on 6 phases / absent on 2 (strong behavioral coverage via the 58-leaf matrix + oracle), and empty `requirements_completed` SUMMARY frontmatter on phases 1/4/5/7/9 (cosmetic — traceability + VERIFICATION carry the truth). Substantive behavior deferrals (margin/liquidation, shorts, trailing stops, real pair trading) → v1.2 (ROADMAP backlog).

**Archived:** `milestones/v1.1-ROADMAP.md`, `milestones/v1.1-REQUIREMENTS.md`, `milestones/v1.1-MILESTONE-AUDIT.md`.

---

## v1.0 — Backtest-Correctness Refactor (Shipped: 2026-06-08)

**Scope:** 8 phases (M1 → M5c), 62 plans. The 999.x backlog phases (N+1…N+4) are future milestones, not part of v1.0.

**Delivered:** A single backtest run of `SMA_MACD` on `data/BTCUSD_1d_ohlcv_2018_2026.csv` now produces correct, deterministic, externally cross-validated numbers — the engine's results are trustworthy and regression-locked.

**Definition of done — green on all 8 checks (08-09 owner-signed final-oracle freeze):**
`SMA_MACD` runs end-to-end (134 trades / final_equity 46189.87730727451 / 3076 equity points) · `mypy --strict` clean · no float money (Decimal end-to-end) · single UUIDv7 scheme · deterministic (seeded RNG + injected clock) · 724 tests pass · run-path integration gate byte-exact · cross-validated vs `backtesting.py` + `backtrader` (+ `nautilus-trader`).

**Key accomplishments:**

- **M1 — Ignition + lock the oracle:** Made the backtest path import and run end-to-end (resolved the config-shadow import cascade, `to_timedelta`, `SMA_MACD` `.iloc`/`fillna`, `record_metrics` target, minimal sizing seam); froze the human-blessed behavioral + numerical reference oracle into `tests/golden/`, regression-locked by an exact tolerance-free integration test.
- **M2 — Identity, money, determinism & foundations:** Single UUIDv7 ID scheme via `uuid-utils`; money Decimal end-to-end with centralized quantization; `mypy --strict` clean with frozen/slots DTOs and real ABCs (11 dead Py2 `__metaclass__` bases → Protocols/ABCs); deterministic runs (seeded RNG + injected clock); config collapsed 3,380 → ~1,130 lines of Pydantic v2 + `pydantic-settings`; enums centralized; portfolio storage seam; numerical oracle re-frozen byte-exact after the float→Decimal shift.
- **M3 — Event & dispatch core:** Immutable frozen events with `event_id` + required linkage IDs + enum-typed fields; race-free `dict[EventType, list[Callable]]` dispatch registry (`get_nowait`, `NotImplementedError` on unknown types); unified `ITraderError` hierarchy + structlog — behavior-preserving, oracle byte-exact.
- **M4 — Money & transaction correctness:** Every trade's cash routes through `CashManager` (reservation lifecycle, no setter bypass); atomic validate-first settlement; one-directional facade→manager→storage layering with O(1) `{order_id: order}` lookup + narrow `PortfolioReadModel` Protocol; frozen Decimal execution DTOs — value-preserving, oracle byte-exact.
- **M5a/M5b — Backtest validity, fills, data pipeline, sizing & metrics:** Removed resampling look-ahead, immutable `Bar` struct payload, precomputed frames, correct fee/slippage, Provider/Store/Feed price-handler split with a read-only run path; next-bar-open fills through the unified `MatchingEngine`; full strategy-declared sizing resolved engine-side (`SizingResolver`); correct reporting/metrics; universe stub. Two owner-approved RESULT-CHANGING re-freezes (LONG_ONLY direction guard + `allow_increase=False`) — oracle settled at 134 trades, 0 shorts.
- **M5c — Cross-validation & final oracle:** Cross-validated against `backtesting.py`, `backtrader`, and `nautilus-trader` — all reconcile to 134 trades and final_equity ≈ 46189.877; verdict 0 BUG / 4 LEGITIMATE-DIFFERENCE (owner-approved); final numerical oracle frozen as the new authoritative reference.

**Audit:** `tech_debt` status — all 45/45 requirements satisfied, 8/8 phases verified, 18/18 integration seams wired, 1/1 E2E flow complete, 0 blockers. See `milestones/v1.0-MILESTONE-AUDIT.md`.

**Known deferred items at close: 12** (3 done-but-flagged quick tasks, 5 partial human-UAT gaps, 4 unsigned per-phase verification reports — all advisory, owner-deferred, or out-of-scope live-mode; see STATE.md → Deferred Items). Substantive behavior deferrals (margin/liquidation model, shorts, SHORT_ONLY cover-arm hole) are tracked in the ROADMAP backlog as N+2.

**Archived:** `milestones/v1.0-ROADMAP.md`, `milestones/v1.0-REQUIREMENTS.md`, `milestones/v1.0-MILESTONE-AUDIT.md`.

---

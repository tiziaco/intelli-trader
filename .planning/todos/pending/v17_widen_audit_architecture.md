# v1.7 widened verification + architecture revision

**Source:** systemic patterns from the Phase-5 adversarial review (2026-07-04). Companion to
[`v17_bugs.md`](v17_bugs.md) — that file holds the concrete Phase-5 defects and their fix
waves; THIS file holds (1) the widened audit campaign across earlier phases/milestones and
(2) the three architecture decisions those defects exposed. Line/behavior references are as
of commit `cfaed3f1`.

**Working verdict from the review:** the core architecture is sound (single-queue event flow,
frozen events, handler/manager split, engine-thread/connector-loop threading, Decimal money,
venue-truth + intent-mirror + reconcile). The critical bugs are *seam-completion* failures:
abstractions declared but not enforced, consumers built before producers, invariant systems
half-built. The audits below verify how far each pattern spread; the ARCH items close the
three decision-level roots so the pattern cannot recur.

---

## Part 1 — Widened verification (audit campaign, all read-only)

Each audit is independent, requires no network/credentials, and produces a written artifact
(a census table or conformance matrix) plus, where marked, a pinned test. Priority order.

### AUD-1 — Account-surface conformance census (Phase 1 code) — feeds ARCH-1, blocks V17-01 fix sizing
- **Scope:** `itrader/portfolio_handler/account/` (`base.py`, `simulated.py`, `venue.py`) and
  EVERY `account.<member>` access in `portfolio.py`, `portfolio_handler.py`, and the
  `cash/`, `position/`, `transaction/`, `metrics/` managers.
- **Method:** enumerate all member accesses on `portfolio.account` / injected accounts; build a
  matrix: member × (declared-on-ABC? | SimulatedCash | SimulatedMargin | Venue) ×
  (isinstance-guarded at call site?). V17-01 found three unguarded concretion calls
  (`available_balance`, `assert_funds_invariant`, `apply_fill_cash_flow`) — the census
  determines whether there are more (metrics/serialization paths, `to_dict`, margin surfaces).
- **Deliverable:** conformance matrix + a parametrized conformance test (each Account leaf
  driven through admission-read + BUY settle + SELL settle) that stays as a permanent gate.
- **Effort:** S (mechanical grep + table).

### AUD-2 — Storage producer/consumer census (v1.6 milestone + v1.7 Phases 3/5)
- **Scope:** `order_handler/storage/models.py`, `portfolio_handler/storage/*`
  (`sql_storage.py`, `cached_sql_storage.py`, `storage_factory.py` — is the cached
  PORTFOLIO storage wired anywhere at all?), `strategy_handler/storage/`,
  `itrader/storage/migrations/versions/*`.
- **Method:** for every column/field added in v1.6+v1.7: (a) who writes it in production code,
  (b) is that writer on a WIRED run path (backtest / paper / live), (c) who reads it back.
  Flag every orphan (column with no producer, producer with no wiring, consumer reading a
  never-written field). Known orphans to seed the table: `orders.venue_order_id` (V17-02),
  `transactions.venue_trade_id` (V17-05), the un-wired portfolio SQL storage itself.
- **Deliverable:** census table; each orphan becomes a fix item or an explicit
  "intentionally dormant until phase X" annotation in the schema docstring.
- **Effort:** M.

### AUD-3 — Silent-swallow census on the live path — feeds the circuit-breaker design
- **Scope:** `execution_handler/execution_handler.py` (`on_order`/`on_market_data` boundary
  swallows), `portfolio_handler.py::_operation_context`,
  `live_trading_system._event_processing_loop` (`except Exception: continue`),
  `_publish_and_continue`, `full_event_handler._log_error_event`, and any `except Exception`
  reachable from the FILL/ORDER/SIGNAL routes in live mode.
- **Method:** classify every swallow site: does the swallowed failure leave money state
  wrong/partial (settlement, reservation, mirror) or is it cosmetic (metrics, logging)?
  The money-mutating list is the input spec for the ERROR-route circuit breaker
  (N money-route ErrorEvents in window → halt) proposed in v17_bugs.md.
- **Deliverable:** classified swallow inventory + circuit-breaker spec draft.
- **Effort:** S/M.

### AUD-4 — Connector primitive semantics (Phase 2 code) — feeds V17-07/09 fixes
- **Scope:** `connectors/okx.py` `call()` / `spawn()` / `disconnect()` and ALL their consumers
  (both OKX arms, VenueAccount, VenueReconciler, provider backfill).
- **Method:** audit the two known semantic traps at every consumer: (a) `call()` timeout does
  NOT cancel the in-flight coroutine — which callers treat a timeout as "operation did not
  happen"? (b) `spawn()` never observes task exceptions — which spawned coroutines lack a
  supervisor? (c) disconnect join-timeout path: what state survives an unclean stop?
- **Deliverable:** consumer table + the required semantics written into `LiveConnector`
  Protocol docstrings (so the contract is stated where implementers read it).
- **Effort:** S.

### AUD-5 — LiveBarFeed bar-timing-contract parity (Phase 3 code)
- **Scope:** `price_handler/feed/live_bar_feed.py` vs the seven look-ahead-safety rules in
  `price_handler/feed/bar_feed.py` (the contract's single written home).
- **Method:** rule-by-rule check of the live `window()` slice + monotonic guard + gap
  backfill-and-replay re-entrancy (can a backfilled replay interleave with a live `update()`
  from the socket thread?). Also: `backfill_on_resume` is currently dead code on the run
  path — decide wire-or-delete.
- **Deliverable:** parity checklist; any violated rule is a new bug entry in v17_bugs.md.
- **Effort:** M.

### AUD-6 — Live order-entry validation strength (D-03a re-examination)
- **Scope:** `trading_system/trading_interface.py` → `OkxExchange` path vs the admission path
  (`EnhancedOrderValidator`, sizing, reservation).
- **Method:** the dual-validator decision (D-03a) justified keeping the domain validator
  because the live TradingInterface path bypasses it — but the exchange-side check it leans on
  (`OkxExchange.validate_order`) is only `quantity > 0`. Enumerate what the admission path
  validates that the live entry path does not (funds, direction policy, leverage cap, symbol
  membership) and decide which checks the live path must gain.
- **Deliverable:** validation-gap table + updated D-03a note in
  `.planning/codebase/CONVENTIONS.md`.
- **Effort:** S.

### AUD-7 — Test-double fidelity audit
- **Scope:** `tests/support/fake_venue_connector.py`, `tests/support/fixtures/okx_recon_payloads.json`,
  `test_venue_account_*` payload shapes.
- **Method:** list every behavior where the fake is FRIENDLIER than OKX: complete unpaginated
  trade history (masked V17-10), ids always present, derivative-shaped positions for a spot
  flow (masked V17-04), fixture symbol BTC/USDT vs wired BTC/USDC (old IN-04), instant acks
  (masks V17-09). For each: either make the fake faithful or add a second "hostile" fake
  variant used by the resilience suites.
- **Deliverable:** fidelity gap list + fake hardening plan.
- **Effort:** M.

**Explicitly NOT widened:** Phase 4 paper path (reuses `SimulatedExchange` as-is, fail-fast
error policy — the silent-failure class structurally can't occur there); backtest hot path
(oracle-locked, byte-exact gate already guards it).

---

## Part 2 — Architecture revision (3 decision-level roots + 1 small structural fix)

### ARCH-1 — Enforce the Account contract (root of V17-01)
- **Problem:** Phase 1 extracted the `Account` ABC (`balance/available/reserve/release`) from
  `SimulatedCashAccount` without narrowing the callers — `Portfolio` still calls the concrete
  settlement surface, so the ABC is aspirational and any new leaf (VenueAccount) compiles,
  wires, and then dies at runtime.
- **Decision to make:** where does the settlement contract line sit?
  - **Option A (recommended for v1.7):** widen the ABC to the surface Portfolio actually needs
    (`available_balance`, `assert_funds_invariant`, `apply_fill_cash_flow` — final list comes
    from AUD-1) and implement it on `VenueAccount` (locally-ledgered, reconciled to venue truth
    via snapshot/drift). Smallest diff, keeps all call sites, unblocks v17_bugs Wave 1 now.
  - **Option B (candidate v1.8):** split settlement out of Account into a `SettlementLedger`
    owned by Portfolio; Account narrows to the admission/reservation surface only, and
    VenueAccount becomes genuinely cache-only (its current design intent). Cleaner, but a
    mid-milestone refactor of the hottest money path.
- **Enforcement (either option, non-negotiable):** type `Portfolio.account` as the ABC and
  make mypy see it — remove the relevant modules from the `[[tool.mypy.overrides]]` ignore
  list (or add a dedicated typed conformance module) so ABC-vs-concretion drift becomes a
  compile-time failure, plus the AUD-1 parametrized runtime conformance test.
- **Verification first?** Run AUD-1 BEFORE finalizing the Option-A member list — the census
  sizes the ABC extension; deciding A-vs-B does not need to wait.

### ARCH-2 — Model venue truth per asset class (root of V17-04)
- **Problem:** "the venue owns balances/positions" was implemented through one channel
  (`fetch_positions`/`watch_positions`) that only exists for derivatives; on the wired spot
  pair the venue side of every drift/orphan check is structurally empty.
- **Proposed solution (fairly settled, small):** a per-market-type venue-truth adapter inside
  `VenueAccount`:
  - derivatives → positions channel (current code, unchanged);
  - spot → derive per-symbol position truth from BASE-currency balances
    (`fetch_balance`/`watch_balance` totals keyed by the symbol's base asset);
  - quote currency comes from wiring (the traded pair's quote — USDC today), never a default.
- **Open design point (needs a decision, flag before implementing):** spot balance-derived
  positions cannot distinguish the strategy's position from pre-existing holdings on the same
  account. Requires a session-start BASELINE snapshot (venue baseline vs session deltas) or a
  dedicated sub-account discipline (cleanest: one sub-account per live system, baseline
  asserted ≈ 0 at start, else halt). Recommend the sub-account discipline — it also gives the
  orphan-position halt real teeth on spot.
- **Verification first?** No new audit needed — V17-04 is fully confirmed; CONF-B (sandbox
  run) already pins the empirical side. Decide the baseline question, then implement with the
  v17_bugs Wave-1 fix.

### ARCH-3 — Complete (or change) the durability split (root of V17-05/06)
- **Problem:** the declared model — store owns INTENT (sync-durable), venue owns
  balances/positions/fills, portfolio ledger derivable/volatile — is defensible, but it leans
  on two guarantees that were never built: a drift compare that can actually arbitrate (blind
  on spot until ARCH-2) and a durable settlement/dedup ledger (transactions table never wired).
- **Two coherent postures (do NOT mix):**
  - **Posture (i) — durable engine ledger (leaning recommendation):** wire the existing
    portfolio SQL storage in live (same `SqlBackend` spine), persist transactions with
    `venue_trade_id`, rehydrate positions/cash AND the settled-trade dedup ledger on restart;
    venue truth then serves as the CHECK (drift), not the source. Matches what the codebase
    already built but didn't wire; closest to the Nautilus model.
  - **Posture (ii) — venue-derived ledger:** portfolio state is rebuilt at restart purely from
    venue balances/positions + trade history; only intent stays in the store. Less state to
    keep consistent, but it inherits every venue-API completeness problem found in V17-10
    (trade-history windows, pagination) as a correctness dependency.
- **Verification first? YES — deliberately no final recommendation here.** Decide AFTER
  AUD-2 (what storage actually exists and round-trips) and CONF-B (what the venue APIs
  actually return for this account type). Both postures change the v17_bugs Wave-2 fix shape;
  committing before that evidence risks building the wrong half again.

### ARCH-4 — SystemStatus as a latched state machine (root of V17-03, small)
- **Problem:** engine status is ad-hoc flags mutated from multiple sites; RUNNING clobbered
  HALTED because `_update_status` has no notion of legal transitions.
- **Solution (settled — the pattern already exists in-house):** a `VALID_STATUS_TRANSITIONS`
  table (mirroring `VALID_ORDER_TRANSITIONS` in `core/enums`) enforced at the single mutation
  point; HALTED is terminal except via an explicit operator `reset_halt()`; `start()` checks
  post-reconcile status and refuses to enter RUNNING from HALTED. Fixes V17-03 as a class,
  not a patch.

---

## Part 3 — Roadmap

**Stage 0 — audits (parallelizable, read-only, no gate risk).**
Run AUD-1..AUD-7; AUD-1/AUD-2/AUD-3 first (they feed the architecture decisions and the
Phase-5 fix waves). Each audit's artifact lands in `.planning/` (or this folder) and any new
confirmed defect is appended to `v17_bugs.md` with a V17-NN id.

**Stage 1 — architecture decisions (short, after their inputs land).**
- ARCH-1: decide A vs B immediately; finalize the member list after AUD-1. **Blocks
  v17_bugs Wave 1** (the V17-01 fix implements whichever option is chosen).
- ARCH-2: decide the spot-baseline question (sub-account discipline vs baseline snapshot).
  **Blocks the V17-04 fix in Wave 1.**
- ARCH-4: no dependencies — fold directly into Wave 1 alongside the V17-03 fix.
- ARCH-3: decide posture (i) vs (ii) only after AUD-2 + CONF-B evidence. **Blocks
  v17_bugs Wave 2** (V17-05/06 fix shape depends on it).

**Stage 2 — execution.**
Fold the decided fixes into the existing v17_bugs.md waves (Wave 1 settlement, Wave 2
restart, Wave 3 resilience). The AUD-1 conformance test, the AUD-3 circuit breaker, and the
ARCH-4 transition table become permanent gates alongside the existing ones (SMA_MACD oracle
byte-exact, mypy --strict, full suite via `poetry run pytest tests`, CONF-B sandbox green).

**Sequencing with v17_bugs.md:** CONF-A (offline RED tests) can start immediately and in
parallel with Stage 0 — none of it depends on the architecture decisions; the RED tests
encode observable behavior, not implementation shape.

# v1.7 architecture decision register (ARCH-1..ARCH-4)

**Source:** interactive decision session (2026-07-04) over the Part-1 audit evidence
([`v17_audit_results.md`](v17_audit_results.md), AUD-1..AUD-7 complete) against the Part-2
work order in [`v17_widen_audit_architecture.md`](v17_widen_audit_architecture.md). Code
references are branch `v1.7/phase-5-sandbox-path` at commit `cfaed3f1`. ADR-style, one
section per ARCH item; wave impacts are recorded HERE and applied to
[`v17_bugs.md`](v17_bugs.md) as a separate follow-up (this file does not edit the waves).

---

## ARCH-1 — Account contract enforcement (root of V17-01, V17-14)

### Decision

**Option A — widen the `Account` ABC to the settlement surface Portfolio actually calls,
implemented on `VenueAccount` as a locally-ledgered account (reconciled to venue truth via
snapshot/drift).** Three sub-decisions:

1. **ABC widening (three new members):** `assert_funds_invariant`, `apply_fill_cash_flow`,
   `reserved_balance` — the member list finalized by the AUD-1 census (§1c input 1).
2. **Rename, not re-point:** the ABC's `available` is **renamed to `available_balance`**
   (user variant, superseding the audit's "re-point call sites to `available`" suggestion).
   `SimulatedCashAccount`'s alias pair collapses — the alias `available`
   (`simulated.py:154-162`) is deleted and the real `available_balance` (`simulated.py:139`)
   becomes the ABC implementation; `VenueAccount.available` (`venue.py:237`, overlay-netted)
   is renamed. Final ABC surface (7 members):
   `balance`, `available_balance`, `reserved_balance`, `reserve`, `release`,
   `assert_funds_invariant`, `apply_fill_cash_flow`.
3. **Margin `cast()` sites get a runtime guard now:** the bare
   `cast(SimulatedMarginAccount, self.account)` narrowings (`portfolio.py:438`, `:834`)
   are replaced with an `isinstance` check raising a typed error
   (ConfigurationError/StateError) **before any mutation**. The full margin-conformance
   story (a margin surface on a contract) is explicitly deferred until live-margin wiring
   exists.

**Enforcement (non-negotiable, part of the decision):** `Portfolio.account`
(`portfolio.py:104`) is re-typed from the concretion to the ABC; mypy must see the live
wiring (remove `live_trading_system` from the `[[tool.mypy.overrides]]` ignore list or add
a dedicated typed conformance module); the AUD-1 §1d parametrized conformance test
(`tests/unit/portfolio/test_account_conformance.py`, all three leaves driven through
admission-read + reserve/release + BUY/SELL settle + serialization surface) lands as a
permanent gate.

### Status

**FINAL.**

### Rationale

- AUD-1 (§1b/§1c) proved the unguarded concretion surface is small and concentrated: the
  three V17-01 sites are the ONLY unguarded calls on the wired live run path; the only
  others are the serialization pair (`portfolio.py:888-889`) and the cast-gated margin
  surface (V17-14). Option A closes all of them with an ABC + ~3 `VenueAccount` methods —
  the smallest diff that makes settlement possible, unblocking Wave 1 now.
- Option B refactors `transact_shares` and every settle path — the hottest money path,
  oracle-locked — mid-milestone, and every CONF-A A1 RED test would encode a shape that
  does not exist yet. That is exactly the seam-completion failure class this campaign is
  remediating (consumers built before producers).
- The rename direction is evidence-backed: `.available` has **zero production callers**
  (session grep, 2026-07-04) — production already calls `available_balance` everywhere
  (admission read-model `portfolio_handler.py:300`, `to_dict` `portfolio.py:888`); only 7
  assertions in `tests/unit/portfolio/test_venue_account_cache.py` touch `.available`. The
  rename therefore costs zero production call-site edits, deletes an alias, and yields a
  consistent contract family (`balance` / `available_balance` / `reserved_balance`) instead
  of a mixed one.
- The 1:1 topology makes "locally-ledgered VenueAccount" unambiguous:
  `_link_venue_account_to_portfolios` already fails loud on >1 active portfolio
  (`live_trading_system.py:554-562`), so the per-VenueAccount ledger IS the per-portfolio
  ledger — no sharing hazard.
- Runtime guard on the casts: `cast()` is a mypy-only hint with zero runtime effect, so
  venue-linked + `enable_margin=True` dies **mid-settlement** (same partial-mutation hazard
  class as V17-01's SELL arm). A loud typed error at the guard point converts a silent
  money-state hazard into an immediate wiring failure for a trivial diff.

### Rejected alternatives

- **Option B (SettlementLedger split):** rejected *for v1.7 only* — large refactor of the
  hottest money path mid-milestone, blocks Wave 1, RED tests would encode an unbuilt shape.
  Remains the clean end-state candidate for v1.8 (VenueAccount returns to cache-only, its
  original design intent).
- **Re-point call sites to ABC `available`** (audit §1c input 1): superseded by the rename —
  same three-member widening, but leaves the shorter/vaguer name on the contract and an
  inconsistent naming family; the grep showed the rename is strictly cheaper.
- **Add `available_balance` to the ABC as an alias alongside `available`:** bakes a
  permanent synonym pair into the contract that every future leaf implements twice.
- **Leave margin casts as-is with documentation:** keeps the V17-01 hazard class live
  behind one config flag for zero benefit beyond a saved trivial diff.

### Impact on v17_bugs.md fix waves

- **Wave 1 / V17-01 — unblocked and shaped:** the fix implements Option A: extend the ABC
  (3 members + rename), implement `assert_funds_invariant` / `apply_fill_cash_flow` /
  `reserved_balance` / `available_balance` on `VenueAccount` (ledger-backed locally),
  re-type `portfolio.py:104`, mypy visibility, land the §1d conformance test. CONF-A A1
  RED tests encode this shape.
- **Wave 1 / V17-14 — both arms closed:** the serialization reads (`to_dict`) become
  contract-covered automatically (`available_balance` + `reserved_balance` both on the
  ABC); the cast arm gets the runtime guard in the same wave.
- **Test suite mechanical impact:** 7 assertion renames in `test_venue_account_cache.py`;
  the `SimulatedCashAccount.available` alias deletion is oracle-dark (alias had no
  backtest-path callers) but the SMA_MACD byte-exact gate still applies as usual.

### New follow-ups (not yet V17-NN items)

- **F/U-1:** Record Option B (SettlementLedger) as an explicit v1.8 backlog candidate so
  the "cost later" of Option A is tracked, not forgotten.
- **F/U-2:** `tests/e2e/conftest.py:372` (`get_cash_operations` harness helper) breaks on
  any venue-linked portfolio (AUD-1 site #18) — annotate or guard when the live e2e harness
  next grows a report surface. `get_cash_operations` deliberately stays OFF the ABC.
- **F/U-3:** The admin surface (`deposit`/`withdraw`/`process_transaction_cash_flow`/
  `get_balance_info`/`validate_balance_consistency`) has no production callers (AUD-1 §1a)
  — candidates for pruning or explicit "admin-only, Simulated-only" annotation during the
  Wave-1 touch.
- **F/U-4:** Decide the mypy enforcement mechanism at fix time (remove
  `live_trading_system` from strict-exemption vs a dedicated typed conformance module) —
  either satisfies the decision; pick whichever keeps the strict-clean gate green cheapest.

---

## ARCH-2 — Venue truth per asset class (root of V17-04)

### Decision

1. **Per-market-type venue-truth adapter inside `VenueAccount`** (work-order proposal,
   confirmed): derivatives → positions channel (current code, unchanged); spot →
   per-symbol position truth derived from **BASE-currency balance totals**
   (`fetch_balance`/`watch_balance`); quote currency **always from wiring** (the traded
   pair's quote — USDC today), never a default (kills the `quote_currency="USDT"` default
   at `live_trading_system.py:400` / `venue.py:73`).
2. **Spot baseline: sub-account discipline.** One dedicated venue sub-account per live
   system, in the existing 1:1:1 topology (sub-account ↔ `VenueAccount` ↔ portfolio,
   already enforced fail-loud at `live_trading_system.py:554-562`). Adding another account
   later means a new sub-account + new `VenueAccount` + new portfolio — formalized by the
   planned **account-registry milestone** (user roadmap), which replaces today's hardcoded
   wiring in `live_trading_system.py`. Balance ≡ strategy position **by construction**.
3. **Session-start baseline guard, sequenced AFTER reconciliation.** Startup order:
   (a) venue snapshot → (b) startup reconciliation syncs local state for every
   **explainable** divergence (downtime fills adopted onto known orders, venue-side
   cancels, ledger-rehydrated positions) → (c) the guard compares the base-asset balance
   against the engine's post-reconcile believed position (0 on a fresh session; the
   rehydrated + adopted quantity otherwise) within a per-instrument dust epsilon — any
   **residual (unexplainable) mismatch → HALT before trading**. Quote-side cash is not
   asserted (deposits are legitimate funding). Unexplained divergence is NEVER
   auto-adopted — the engine must not silently start managing exposure of unknown origin.

### Status

**FINAL.**

### Rationale

- V17-04 (confirmed pre-audit): `_extract_positions` (`venue.py:127-148`) parses
  ccxt derivatives channels only; OKX spot returns `[]` there, so venue position truth for
  the wired BTC/USDC pair is permanently empty — drift and orphan checks are structurally
  blind today, and would spuriously halt on every position-opening fill once V17-01 is
  fixed. AUD-7 F3/F4 confirmed the masking mechanism: the fake feeds derivative-shaped
  positions for a spot symbol and agrees with the wrong USDT default.
- Sub-account isolation dissolves the attribution problem instead of solving it in code:
  `fetch_balance` on a dedicated sub-account returns only that system's coins, so no
  baseline artifact, no delta tracking, no corruption-by-manual-trade. The alternative
  (baseline snapshot + session deltas) needs a durable baseline with no storage home until
  ARCH-3, is permanently corrupted by any mid-session external trade, and blinds the
  orphan check to pre-existing holdings forever.
- Ops already match: the OKX demo creds are a dedicated demo sub-account (memory:
  okx-demo-creds-safe), and the code's design intent (`_link_venue_account_to_portfolios`
  docstring) already treats a `VenueAccount` as "one venue sub-account".
- The guard converts the isolation assumption into a **checked invariant** (catches
  wrong-account wiring, leftovers from a crashed session, forgotten deposits) at one
  clear point instead of surfacing later as confusing drift halts. Sequencing it after
  reconciliation keeps the roles clean: **reconcile = sync the explainable; guard = halt
  on the residue**.
- Known operational consequence, accepted: until ARCH-3's durable ledger + V17-02/V17-10
  land, reconciliation can explain almost nothing (adoption is inert per V17-02), so a
  restart while holding a position halts at the guard — correct fail-safe (state was
  lost; a human decides), revisited automatically as Wave 2 restores the sync arm.

### Rejected alternatives

- **Baseline snapshot + session deltas:** durable baseline artifact without a decided home
  (pre-empts ARCH-3), permanent delta corruption on any manual/external trade, orphan
  detection degraded to delta-anomalies-only. More code, weaker guarantees.
- **No start guard (discipline by convention only):** zero diff, but a violated assumption
  surfaces as garbage drift from bar one instead of one clear startup error.
- **Auto-adopting unexplained divergence:** turns the orphan-position halt into silent
  exposure adoption — the exact failure mode the halt exists to prevent.
- **Deferring spot support / trade-history-derived positions:** not seriously entertained;
  the wired pair IS spot, and trade-history derivation inherits V17-10's completeness
  problems as a correctness dependency.

### Impact on v17_bugs.md fix waves

- **Wave 1 / V17-04 — fix shape finalized:** spot arm of the adapter (base-balance-derived
  positions), quote currency from wiring, baseline guard wired into `start()` after
  reconcile. The "just-applied engine fill vs not-yet-refreshed venue snapshot"
  spurious-halt arm stays part of the fix (band policy per the existing Wave-1 text).
  CONF-A A4 encodes these semantics (real empty spot positions payload + one fill → no
  drift halt, divergence still surfaced).
- **Test-side companion:** AUD-7 Tier-1 spot fixture (`BTC/USDC`, USDC balance keys,
  positions channel `[]`) becomes the default for the reconciliation cluster.
- **CONF-B additions:** empirically pin `fetch_positions() == []` for the spot pair,
  USDC balance keys, and snapshot/guard behavior on the demo sub-account.
- **Coupling to ARCH-4:** the guard's halt is only real once HALTED latches (V17-03) —
  same dependency as every other halt; land together in Wave 1.

### New follow-ups (not yet V17-NN items)

- **F/U-5:** Account-registry milestone (user roadmap): per-account
  `VenueAccount`/portfolio linking replacing the hardcoded `live_trading_system.py`
  wiring — the sanctioned multi-account path; sub-account discipline is its per-entry
  invariant.
- **F/U-6:** Dust epsilon for the baseline guard: reuse the per-instrument drift-epsilon
  resolution — note AUD-3 S15 (unknown instrument silently defaults to precision 8);
  acceptable single-symbol, re-check when multi-symbol arms (V17-12).
- **F/U-7:** Document "restart while holding a position halts at the guard until Wave 2
  restores the reconcile sync arm (V17-02/V17-05/V17-10)" as known operational behavior —
  operator runbook note, not a code item.

---

## ARCH-4 — SystemStatus as a latched state machine (root of V17-03)

### Decision

**Two-layer latched status, decided per layer:**

- **Layer 1 — in-process latched state machine (Wave 1):** a `VALID_STATUS_TRANSITIONS`
  table (`dict[SystemStatus, set[SystemStatus]]`, sited next to the existing
  `SystemStatus` enum `core/enums/system.py:14`, mirroring `VALID_ORDER_TRANSITIONS`)
  enforced at the single mutation point — `_update_status`
  (`live_trading_system.py:745`), with `halt()`'s direct write (`:598-601`) routed through
  or sharing the same enforcement so there is genuinely ONE mutation point. `HALTED` has
  **no legal exits** in the table; the only way out is an explicit operator
  `reset_halt()`, deliberately outside the table. `start()` checks post-reconcile status
  and refuses to enter RUNNING from HALTED.
- **Layer 2 — durable halt record (adopted in principle; storage home + wave assigned by
  ARCH-3):** `halt()` persists a record (reason, timestamp); `start()` refuses RUNNING
  while an unresolved halt record exists; `reset_halt()` resolves the record. Purpose: an
  auto-restarting supervisor (systemd/Docker/FastAPI-era service) must never be able to
  silently clear a halt whose cause is not re-detectable at start (circuit-breaker-class
  halts).
- **Out of scope:** persisting general system status (RUNNING/PAUSED/…) — RUNNING is
  re-earned at every start via reconcile + the ARCH-2 baseline guard, so ground truth
  beats a stored flag for money-state halts. DB-backed config / system-wide info storage
  is a FastAPI-milestone feature, not v1.7.

### Status

**Layer 1: FINAL.** **Layer 2: FINAL in principle; storage home and wave land with the
ARCH-3 decision** (on posture (i) it is a small system-state table on the same
`SqlBackend`/Alembic spine, Wave 2).

### Rationale

- V17-03 trace: `_event_processing_loop` unconditionally stamps RUNNING
  (`live_trading_system.py:993`) and `_update_status` (`:745-749`) blindly assigns — no
  notion of legal transitions, so a reconcile-time halt is clobbered within milliseconds
  (`get_status()` shows `status=running, halt_reason=reconciliation-unresolved`). The
  root is "status has multiple writers and no rules", not line 993 — a point patch leaves
  every future status writer free to reintroduce the class.
- The pattern is in-house and proven: `VALID_ORDER_TRANSITIONS` already prevents exactly
  this bug class for orders. The `SystemStatus` enum already exists; only the table and
  its enforcement are missing.
- Hard prerequisite for two other decisions this session: the AUD-3 circuit breaker
  (§3b explicitly notes it is inert until the HALTED latch lands) and the ARCH-2
  session-start baseline guard — every live-path safety mechanism funnels into `halt()`,
  which today is written in pencil.
- Layer 2 (user-raised, argument accepted): "restart = operator intervention" only holds
  for human restarts. Under a supervisor, an auto-restart loop becomes an auto-
  `reset_halt()` loop for any halt whose cause reconcile + guard cannot re-detect
  (breaker trips on transport-level failures) — the system trades straight back into the
  failing condition. Money-state halts do NOT need the record (re-derived from ground
  truth); breaker-class halts DO. Alert egress being log-only today (existing LOW item)
  makes the durable record the only artifact proving a halt ever happened.
- Sequencing: persistence is a strictly additive layer on the latch (an extra check in
  `start()` + a write in `halt()`), so landing Layer 1 first carries zero rework risk,
  and the record's storage home belongs to ARCH-3 — deciding it inside ARCH-4 would
  invert the dependency order.

### Rejected alternatives

- **Point patch at `live_trading_system.py:993` only:** fixes one clobber site, leaves the
  bug class open to every future status writer.
- **Layer 1 only (no durable record):** leaves the auto-restart-clears-the-breaker hole
  open the moment the system runs supervised.
- **Both layers in Wave 1 now:** front-loads a storage commitment one decision before
  ARCH-3 lands the storage posture; risks re-work.
- **Persist full system status / DB-backed config now:** stale-status hazards for
  re-derivable states; config storage is a web-app-milestone feature (v1.6 memory:
  schema is already being steered toward FastAPI queryability — that is its home).

### Impact on v17_bugs.md fix waves

- **Wave 1 / V17-03 — fix shape finalized as Layer 1.** CONF-A A3 pins it (`start()`
  after a reconcile halt → `get_status()` stays `halted`). Must land **before or with**
  the AUD-3 circuit breaker and the ARCH-2 baseline guard.
- **Wave 2 (conditional on ARCH-3 posture (i)):** Layer 2 = one system-state/halt-record
  table on the `SqlBackend` spine + Alembic migration; `start()` gains the
  unresolved-halt-record check; `reset_halt()` resolves it.
- **AUD-3 circuit breaker (Wave 3 resilience):** unblocked by Layer 1; its trip target is
  the now-latching `halt(reason)`.

### New follow-ups (not yet V17-NN items)

- **F/U-8:** The full transition table for the remaining `SystemStatus` members
  (STOPPED/PAUSED/ERROR/RUNNING interplay) and the illegal-transition behavior (typed
  `StateError` vs log-and-refuse-keeping-old-status) are fix-time implementation details —
  decide in the V17-03 plan, not here.
- **F/U-9:** `reset_halt()` should likely re-run reconcile + baseline guard before
  permitting `start()` (verify-then-trust, not blind-trust of the operator) — decide at
  fix time.
- **F/U-10:** Alert egress is log-only (existing LOW item) — once the breaker lands, a
  3am halt still reaches nobody; pair Layer 2 with a minimal alert egress in a later
  wave / FastAPI milestone.

---

## ARCH-3 — Durability split: durable engine ledger (root of V17-05/06)

### Decision

**Posture (i) — durable engine ledger.** Complete the original design rather than change
it: wire the EXISTING cached SQL portfolio storage in live (same `SqlBackend` spine as the
order/signal stores) by threading the environment from the live composition root into the
five call sites that today hardcode `"backtest"` (`portfolio.py:96`,
`position_manager.py:65`, `transaction_manager.py:47`, `metrics_manager.py:112`,
`account/simulated.py:111` — session grep 2026-07-04, matching AUD-2 §2c). Transactions
persist with `venue_trade_id`; on restart, positions/cash AND the settled-trade dedup
ledger rehydrate from Postgres BEFORE the reconciler runs. Role assignment is fixed:
**engine ledger = SOURCE of portfolio truth; venue = CHECK** (drift/auditor + gap-fill
via reconcile adoption). Postures are not mixed — no component rebuilds portfolio state
from venue history.

### Status

**PROVISIONAL — pending CONF-B** (the gated OKX demo sandbox run, not yet executed).
Finalization condition — CONF-B must confirm, with output recorded in `.planning/debug/`:

1. **`fetch_my_trades` empirics for the demo spot sub-account** (V17-10): actual window
   depth, row caps, pagination behavior, and whether `id`/`clientOrderId` are always
   present — this bounds how far reconcile adoption (the venue-as-CHECK arm) can be
   trusted for downtime gap-fill.
2. **`fetch_positions()` returns `[]` for the spot pair** (V17-04 empirical arm — the
   premise of ARCH-2's spot adapter and of "venue positions cannot be the source on spot").
3. **Balance payload shape**: USDC-keyed totals usable as base-asset position truth;
   snapshot timing/coherence vs trade delivery (feeds the drift band policy).
4. **Venue/order id behavior post-fill** (pins V17-02's fix path, which posture (i)'s
   reconcile arm leans on).

Evidence that would flip the leaning to posture (ii): venue trade history proving
complete, paginated, and reliable well beyond restart windows AND a structural obstacle
to the engine-side SQL path — neither is expected. Absent that, flip Status to FINAL
after CONF-B review.

### Rationale

- **AUD-2 is the evidence package the work order gated on:** the entire portfolio SQL
  layer (7 tables — positions, transactions, cash_reservations, locked_margin,
  cash_operations, equity_snapshots, portfolio_account_state) is fully built (writers,
  readers, cache wrapper, factory, Alembic migrations) and **never constructed on any run
  path** (§2b–d); `PortfolioStateStorageFactory`'s `'live'` branch is reachable only from
  tests (factory docstring admits it, `storage_factory.py:95`). Posture (i) is therefore
  wiring + a rehydrate path — not new construction — and restores the design the codebase
  already committed to (order + signal stores are already env-aware and wired live; the
  portfolio arm is the unfinished third).
- **Posture (ii)'s foundation is empirically broken where it matters most:** V17-10 shows
  the venue trade-history fetch is a recent-days window, row-capped, unpaginated; AUD-7 F1
  shows the fake masked exactly this. Rebuilding at restart from venue history makes that
  completeness problem a *correctness dependency* — and entry prices, realized PnL, and
  fee history older than the window are unrecoverable from the venue **by design**.
- **Dedup requires durability:** the settled-trade set (`venue_trade_id` dedup) dies with
  the process under posture (ii) — the V17-06 duplicate-delivery corruption sequence is
  unpreventable without a ledger that survives restart.
- **Convergence of this session's decisions:** ARCH-2's start guard needs a rehydrated
  believed-position to compare against (else every mid-position restart halts forever);
  ARCH-4 Layer 2's durable halt record needs a storage home. Posture (i) gives both the
  same spine; posture (ii) leaves both homeless.
- Closest to the reference model (Nautilus: engine-owned durable state, venue reconciled
  against it).

### Rejected alternatives

- **Posture (ii) — venue-derived ledger:** rejected (provisionally) because it inherits
  V17-10's broken completeness as a correctness dependency, loses cost basis/PnL/fees
  beyond the venue window unrecoverably, kills the durable dedup ledger, and requires new
  rebuild-from-venue code while the alternative's code already exists. Revisit only on
  the CONF-B flip evidence above.
- **Mixing postures** (e.g. persist transactions but rebuild positions from venue):
  categorically rejected — two half-authorities make every divergence ambiguous; the
  work order's "do NOT mix" constraint stands. One source (engine ledger), one check
  (venue), one arbitration path (reconcile adopts the explainable, guard halts on the
  residue).

### Impact on v17_bugs.md fix waves

- **Wave 2 / V17-05 — fix shape finalized (provisionally):** thread env through the five
  sites; construct the portfolio SQL store at the live composition root (same
  `SqlBackend` as `live_trading_system.py:274/:285`); rehydrate positions/cash + settled
  `venue_trade_id` ledger (bounded window) before `reconcile()`.
- **Wave 2 / V17-06:** the per-order dedup check reads the rehydrated durable ledger
  (posture-(i) arm of the existing fix text); dedup keys become `f"{symbol}:{trade_id}"`
  (also closes V17-12).
- **Wave 2 / V17-02:** unchanged in shape (ORDER-ACK event), but its persisted
  `venue_order_id` is what makes posture (i)'s reconcile adoption actually able to match
  downtime fills — same wave, mutually dependent.
- **Wave 2 / ARCH-4 Layer 2:** the durable halt record lands here, one small
  system-state table on the same spine + migration.
- **CONF-B:** extend the sandbox assertions with the four confirmation points above (in
  addition to the existing V17-01/02/04 assertions in the CONF-B spec).
- **Sequencing caveat:** Wave 2's detailed plans should not be *finalized* until CONF-B
  runs (post-Wave-1), but CONF-A RED tests for V17-05/06 can be written now — they encode
  observable behavior (restart remembers state; duplicate delivery is idempotent), not
  storage shape.

### New follow-ups (not yet V17-NN items)

- **F/U-11:** `portfolio_account_state` (`save_account_state`, zero callers — AUD-2's
  strongest orphan): decide wire-on-settlement-path vs drop during the Wave-2
  implementation; do not leave it half-alive.
- **F/U-12:** Until Wave 2 lands, annotate the dormant schema per AUD-2 §2d:
  `transactions.venue_trade_id` + the six unwired baseline tables →
  "dormant until V17-05 wiring (ARCH-3 posture (i))"; `orders.venue_order_id` →
  "restart-relink-only until V17-02".
- **F/U-13:** Rehydrate window policy (how far back the settled-trade ledger loads on
  restart) needs a bound + a loud log when the venue window cannot cover the oldest
  active order (pairs with the V17-10 fix).

---

## Session summary (2026-07-04)

| Item | Decision | Status |
|---|---|---|
| ARCH-1 | Option A: widen ABC (3 members), rename `available`→`available_balance`, runtime-guard margin casts, ABC typing + mypy + conformance test | **FINAL** |
| ARCH-2 | Per-market-type venue-truth adapter; sub-account discipline; post-reconcile session-start baseline guard (reconcile syncs the explainable, guard halts the residue) | **FINAL** |
| ARCH-4 | Two-layer latched status: in-process `VALID_STATUS_TRANSITIONS` (Wave 1) + durable halt record (home via ARCH-3, Wave 2) | **FINAL** (L2 home rides ARCH-3) |
| ARCH-3 | Posture (i): durable engine ledger — wire the existing portfolio SQL layer, venue = check | **PROVISIONAL — pending CONF-B** |

Wave impacts recorded per section above; applying them to `v17_bugs.md` is a follow-up
task for the maintainer (this register does not edit the waves).

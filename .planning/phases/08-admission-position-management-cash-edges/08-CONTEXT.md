# Phase 8: Admission, Position Management & Cash Edges - Context

**Gathered:** 2026-06-10
**Status:** Ready for planning

<domain>
## Phase Boundary

Give the LONG-ONLY position-management directions v1.0 never exercised
end-to-end — **scale-in** (`allow_increase=True` pyramiding), **partial
scale-out** (`exit_fraction < 1` across multiple sells), **`max_positions`
rejection**, and **exit-then-re-entry** — plus the **cash reservation/release
lifecycle**, their **first end-to-end golden coverage**. Hand-verified,
contrived-bar leaf scenarios authored on the Phase 4 E2E harness (and the Phase
6 scripted-emitter / orders-snapshot + Phase 7 commission-column / exchange-seam
infra), then `--freeze` regression-locked. Six requirements:

- **ADMIT-01** — `allow_increase=True` scale-in (pyramiding) **works** end-to-end
  (v1.0 only validated the `False`/reject direction).
- **ADMIT-02** — partial scale-out via `exit_fraction < 1` across multiple sells.
- **ADMIT-03** — reaching `max_positions` produces the audited new-entry
  rejection.
- **ADMIT-04** — full exit followed by re-entry on the same ticker.
- **CASH-01** — insufficient funds → audited `cash_reservation` rejection.
- **CASH-02** — reservation release on every terminal state (CANCELLED /
  REJECTED / REFUSED).

**This is a COVERAGE phase — the engine machinery already ships (scout-confirmed):**
- **Scale-in:** `_enforce_position_admission` (`order_manager.py:860-948`) — when
  an open long exists and `allow_increase=True`, the second BUY falls through to
  entry sizing; the resolver reads **current** `available_cash` as remaining
  cash (`sizing_resolver.py:106-112`). The `False` reject branch
  (`triggered_by="admission_increase"`) is the only side v1.0 froze.
- **Scale-out:** `SignalIntent.exit_fraction` (`sizing.py:230-241`, validated
  `(0,1]`); `resolve_exit` (`sizing_resolver.py:134-173`) — `exit_fraction == 1`
  is a structural no-op (D-07, byte-exact), `< 1` computes `net_quantity *
  exit_fraction` with a dust guard; position stays open
  (`position.py:218-230`). **`ScriptedEmitter` already reads `exit_fraction`
  from the script** (`scripted_emitter.py:126`).
- **`max_positions`:** `config.py:53` (`Field(default=1, gt=0)`); admission gate
  `order_manager.py:934-947` — new-ticker entry when
  `open_position_count >= max_positions` → audited REJECTED
  (`triggered_by="admission_max_positions"`).
- **Re-entry:** clean path — `close_position()` sets `is_open=False`
  (`position.py:233-239`); `get_position()` then returns `None`, so a new entry
  takes the fresh-position admission branch. No special handling.
- **Cash reserve/release:** synchronous check-and-reserve at admission
  (`order_manager.py:384-414`, BUY-only); release on terminal fills + local
  cancel (`order_manager.py:257-273`, `1225-1227`); idempotent
  (`cash_manager.py:418-448`). The `CashOperation` ledger
  (`cash_manager.py:24-42`: RESERVATION / RELEASE_RESERVATION / TRANSACTION_*)
  is live but **has no golden serializer yet**.

We EXERCISE this behavior; we do not BUILD it. The only new code is thin test
scaffolding (cash-ledger snapshot serializer, `ScriptedEmitter` `allow_increase`
+ `max_positions` params) plus the ~7 scenario leaves.

**In scope:**
- ~7 self-contained leaf scenarios under `tests/e2e/admission/` and
  `tests/e2e/cash/` (Hybrid slicing, D-04 below), each with fresh contrived
  `bars.csv` + scripted emitter + VERIFY hand-derivation + frozen golden set.
- A foundational (non-parallel) plan adding the shared scaffolding and proving it
  on ONE canary before the parallel scenario waves (Phase 6 D-13 / Phase 7 D-16).

**Out of scope (own phases / behavior-preserving):**
- Multi-ticker / multi-strategy / multi-portfolio cash isolation, contended cash,
  robustness, degenerate metrics, cross-scenario determinism — **Phase 9**
  (MULTI/ROBUST).
- Shorts, margin, leverage, cover-arm sizing — **gated to N+2** (LONG-ONLY
  throughout v1.1).
- Re-baselining the BTCUSD golden oracle — v1.1 is behavior-preserving. Every
  Phase 8 scenario runs on its OWN contrived bars / configured strategy, so
  oracle-darkness is automatic; `tests/integration/test_backtest_oracle.py` is
  never touched.

</domain>

<decisions>
## Implementation Decisions

### CASH-01 vs Phase-7 SIZE-03 (avoid duplicate coverage)
- **D-01:** **CASH-01 gets a DISTINCT trigger AND a distinct assertion lens.**
  Phase 7's SIZE-03 already hand-verified + froze the exact
  `triggered_by="cash_reservation"` rejection (a single over-cash `FixedQuantity`
  entry asserted via the orders-snapshot REJECTED status). CASH-01 must NOT
  re-prove that. Instead:
  - **Trigger = position-management flavored:** a **scale-in 2nd (or Nth) entry
    that exhausts remaining cash** (rides ADMIT-01's `allow_increase=True`
    pyramiding) — not a single oversized first entry.
  - **Lens = the cash-ledger:** assert from the `CashOperation` ledger angle — a
    RESERVATION that **never commits** / `available_cash` left intact / no orphan
    — where SIZE-03 asserted from the order-mirror angle.
  - Different bars, different lens → genuine coverage, zero overlap. Couples
    CASH-01 to both the scale-in leaf (D-04) and the cash-ledger vehicle (D-02).

### Cash reservation/release golden vehicle (the shared CASH-01 + CASH-02 surface)
- **D-02:** **New opt-in cash-ledger snapshot golden.** Add a `CashOperation`
  ledger serializer (e.g. `golden/cash_operations.csv`) following the Phase 6
  **orders-snapshot opt-in pattern** (only written when the golden file already
  exists — `conftest.py:~460`). It is the single assertion surface for both
  CASH-01 (no-commit) and CASH-02 (release on each terminal state); it shows the
  actual reserve-then-release ops per order with the balance trail.
  - **Determinism-safe columns (constraint):** the snapshot MUST exclude the
    UUIDv7 `operation_id` and the raw `reference_id` (order id) — both
    non-deterministic across runs (mirrors how the orders-snapshot omits the raw
    order id). Assert on the **stable trail**: `operation_type`, `amount`,
    `balance_before`, `balance_after`, business-time, and a **derived stable
    order correlation** (e.g. ticker + a per-order ordinal/role, NOT the raw
    uuid) so a RESERVATION can be matched to its RELEASE without exposing an id.
  - Lives in the foundational plan; proven on the canary; **oracle-dark** (only
    materializes when a leaf opts in via the placeholder golden file).

### CASH-02 terminal-state coverage (honest asymmetric)
- **D-03:** **Honest asymmetric coverage** — the three terminal states are NOT
  symmetric, because **REJECTED never holds a reservation** (every REJECTED path
  fires at/before `reserve()`: max_positions/allow_increase reject *before*
  reserve; cash_reservation reject *is* the reserve failing atomically,
  `order_manager.py:399-411`).
  - **CANCELLED** → reserve → operator-cancel a **resting limit BUY** → assert a
    POSITIVE `RELEASE_RESERVATION` op in the ledger snapshot. (Reuses Phase 6
    operator/cancel infra.)
  - **REFUSED** → reserve → exchange `validate_order` failure → `FillEvent
    (REFUSED)` → assert a POSITIVE `RELEASE_RESERVATION` op. **Trigger = a BUY
    exceeding a tiny `max_order_size`** set via `spec.exchange`
    (`simulated.py:_admit_order` validation branch, `~L122-127`) — deterministic,
    no RNG `simulate_failures` path.
  - **REJECTED** → rejection at/before reserve → assert the **NEGATIVE**: no
    orphan RESERVATION in the ledger, `available_cash` intact. (This is the
    truthful semantics, not a contrivance.)
  - Do NOT attempt to force a reserve-then-REJECTED path — none exists today;
    fabricating one would require engine changes, violating behavior-preserving /
    coverage-only.

### Leaf granularity / requirement→scenario mapping (Hybrid, ~7 leaves)
- **D-04:** **Hybrid slicing** — strict one-shape-per-leaf (Phase 6 D-11 / Phase
  7 D-10) EXCEPT one deliberate two-outcome fold where the contrast is the point
  (Phase 7 D-11 maker/taker precedent):
  1. **`admission/scale_in`** — ADMIT-01 **+** CASH-01. One coherent "pyramid
     until cash runs out" story: `allow_increase=True`, an initial entry, a
     successful scale-in add (ADMIT-01 ✓), then a further add that **exhausts
     remaining cash** → `cash_reservation` rejection asserted on the cash-ledger
     no-commit (CASH-01). Trade golden + cash-ledger snapshot.
  2. **`admission/scale_out`** — ADMIT-02. `exit_fraction < 1` across **multiple
     partial sells**, position staying open between them, final close. Trade
     golden (multiple SELL rows).
  3. **`admission/max_positions`** — ADMIT-03. `max_positions` reached → new-ticker
     entry audited REJECTED (orders-snapshot).
  4. **`admission/re_entry`** — ADMIT-04. Full exit → re-entry on the same ticker.
  5. **`cash/release_cancelled`** — CASH-02 CANCELLED (positive release).
  6. **`cash/release_refused`** — CASH-02 REFUSED (positive release).
  7. **`cash/release_rejected`** — CASH-02 REJECTED (negative no-orphan).
  - CASH-02 stays as **3 isolated leaves** (not one combined) — honest asymmetric
    coverage reads clearest when each terminal state is its own hand-verified
    leaf.

### Plan / wave sequencing (carried forward, Phase 6 D-13 / Phase 7 D-16)
- **D-05:** **Foundational plan first, then parallel waves.**
  - **Plan 1 (non-parallel):** the cash-ledger snapshot serializer + opt-in
    wiring (D-02), the `ScriptedEmitter` `allow_increase` + `max_positions`
    params (D-06), and ONE canary leaf proving the wiring end-to-end. **Re-runs
    the BTCUSD oracle gate byte-exact** (new serializer must stay out of the core
    `frames.py::TRADE_COLUMNS` pin; only fires opt-in).
  - **Then parallel waves** grouped ADMISSION / CASH; generate in isolated
    worktrees (Phase 6 D-11 leaf isolation), hand-verify + freeze **batched per
    cluster** (roadmap "not 12-at-once" + "shared infra committed first"
    preconditions). Wave composition within the clusters is discretion.

### Claude's Discretion
- **D-06 (emitter extension shape):** thread `allow_increase` and `max_positions`
  into `ScriptedEmitter` as **constructor params** (Phase 7 D-12 precedent for
  `sltp_policy`/`sizing_policy`), flowing `BaseStrategyConfig` →
  `SignalEvent.allow_increase`/`.max_positions` (both already exist:
  `signal.py:90-91`). Per-instance (not per-bar). Exact param names/defaults are
  discretion (subject to: defaults preserve existing leaves' behavior —
  `allow_increase=False`, `max_positions=1`).
- Exact cash-ledger snapshot column set, file name, and append/opt-in point
  (subject to D-02: determinism-safe, no UUIDs, orders-snapshot opt-in pattern).
- Exact contrived `bars.csv` authoring per leaf (subject to D-04: fresh,
  hand-derivable, one story per leaf except the deliberate scale_in fold).
- Exact `tests/e2e/{admission,cash}/` sub-directory names/depth (subject to Phase
  4 subsystem grouping).
- Canary choice for the foundational plan and wave composition within the
  ADMISSION / CASH clusters (subject to D-05).

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### The harness + scenario infra this phase builds on (read FIRST)
- `.planning/phases/07-cost-sizing-sltp-scenarios/07-CONTEXT.md` — the directly
  preceding sibling coverage phase: commission-column append (D-07/D-08), the
  exchange-config seam fix (D-14, the `spec.exchange` path Phase 8's REFUSED leaf
  reuses for `max_order_size`), `ScriptedEmitter` extension precedent (D-12),
  foundational-plan-first + batched verify (D-16), SIZE-03 over-cash REJECTED
  (the vehicle CASH-01 must NOT duplicate).
- `.planning/phases/06-order-matching-scenarios/06-CONTEXT.md` — scripted-emitter
  (D-01), one-shape-per-leaf (D-11), the **opt-in orders-snapshot for no-trade /
  REJECTED outcomes** (D-08/D-09, the pattern D-02's cash-ledger snapshot mirrors),
  operator/cancel infra (the CANCELLED trigger), foundational-plan-first (D-13).
- `.planning/phases/04-e2e-harness-framework/04-CONTEXT.md` — base harness
  contract: per-folder one-line test → `run_scenario`; `ScenarioSpec` reuses real
  config; diff-what's-frozen; exact no-tolerance diff; CONTRIVED bars; `--freeze`
  + per-scenario VERIFY note; subsystem grouping.
- `tests/e2e/conftest.py` — the `run_scenario` harness + `--freeze` + exact-diff
  machinery; the **orders-snapshot opt-in gate** (`~L460`, the `exists()` check
  D-02's cash-ledger snapshot copies); the `spec.exchange` re-init seam (Phase 7
  D-14, `~L237-254`).
- `tests/e2e/scenario_spec.py` — `ScenarioSpec` (carries `exchange`, `actions`,
  `strategies`, `portfolios`) + `Action`/`PortfolioSpec`. Field names are a
  consuming contract — do not rename.
- `tests/e2e/strategies/scripted_emitter.py` — the generic emitter to extend with
  `allow_increase` + `max_positions` (D-06); already supports `sizing_policy`,
  `sltp_policy`, per-bar `side`/`sl`/`tp`/`exit_fraction` (`~L81-131`).
- `tests/e2e/smoke/single_market_buy/scenario.py` — the `scenario.py` + VERIFY-
  note copy-template each leaf clones.
- `tests/e2e/sizing/over_cash_reject/scenario.py` — Phase 7 SIZE-03; the
  over-cash REJECTED leaf CASH-01 (D-01) must diverge from (distinct trigger +
  ledger lens).
- `tests/integration/test_backtest_oracle.py` — the byte-exact BTCUSD oracle gate
  the cash-ledger serializer (D-02) must stay DARK against (must NOT enter core
  `TRADE_COLUMNS`; opt-in only).

### System under test — admission & position management (already implemented)
- `itrader/order_handler/order_manager.py` — `_enforce_position_admission`
  (`~L860-948`): `allow_increase` increase-reject vs fall-through (`~L916-926`),
  `max_positions` new-entry reject (`~L934-947`); the **cash reserve gate**
  (`~L384-414`, BUY-only, `InsufficientFundsError` → REJECTED
  `triggered_by="cash_reservation"`); the **terminal release** finalizer
  (`~L257-273`, `should_release` on EXECUTED/CANCELLED/REFUSED) and local-cancel
  release (`~L1225-1227`); `_reject_unsized_signal` (`~L1070-1079`).
- `itrader/order_handler/sizing_resolver.py` — `resolve_entry` (scale-in reads
  current `available_cash`, `~L106-112`); `resolve_exit` (`~L134-173`):
  `exit_fraction == 1` structural no-op (`~L161-164`), `< 1` partial + dust guard
  (`~L165-172`).
- `itrader/core/sizing.py` — `SignalIntent.exit_fraction` (`~L230-241`, validated
  `(0,1]`); `FractionOfCash`/`FixedQuantity` (scale-in sizing).
- `itrader/strategy_handler/config.py` — `BaseStrategyConfig.allow_increase`
  (`:52`, default `False`) and `.max_positions` (`:53`, `Field(default=1, gt=0)`)
  — the knobs D-06 threads through the emitter.
- `itrader/events_handler/events/signal.py` — `SignalEvent.allow_increase`
  (`:90`) and `.max_positions` (`:91`) already exist (the propagation target).
- `itrader/portfolio_handler/position/position.py` — `update_position`
  (`~L218-230`, partial-sell keeps `is_open`), `close_position` (`~L233-239`),
  `open_position` (`~L192-216`, re-entry).
- `itrader/core/portfolio_read_model.py` — `open_position_count` (`~L179-194`,
  max_positions gate) and `get_position` (`~L107-125`, returns `None` for closed
  → re-entry).

### System under test — cash reservation/release (already implemented)
- `itrader/portfolio_handler/cash/cash_manager.py` — `CashOperation` dataclass
  (`~L24-42`: `operation_type`/`amount`/`reference_id`/`balance_before`/`_after`/
  `timestamp`), `reserve_cash` (`~L365-416`, `InsufficientFundsError` on
  `available_balance < amount`, records RESERVATION), `release_reservation`
  (`~L418-448`, idempotent `pop_reservation`, records RELEASE_RESERVATION),
  `get_cash_operations` (`~L460-470`) — **the ledger D-02 serializes**.
- `itrader/portfolio_handler/portfolio_handler.py` — `reserve`/`release`
  Protocol surface the order manager calls.
- `itrader/execution_handler/exchanges/simulated.py` — `_admit_order`
  (`~L105-164`): `validate_order` failure → `_emit_rejection` (`~L122-127`); the
  RNG `simulate_failures` path (`~L138-151`, AVOID for determinism);
  `_emit_rejection` → `FillEvent(REFUSED)` (`~L166-173`). The **REFUSED trigger**
  (D-03) is a `validate_order` failure via `spec.exchange` `max_order_size`.
- `itrader/config/exchange.py` — `ExchangeConfig` (carries `limits.max_order_size`,
  the REFUSED lever) + the Phase 7 D-14 re-init seam.

### Reporting / golden serialization
- `itrader/reporting/orders.py` — `ORDER_SNAPSHOT_COLUMNS` (`~L39-49`) + the
  orders-snapshot builder; the **template D-02's cash-ledger serializer follows**
  (determinism-safe column selection, opt-in).
- `itrader/reporting/frames.py` — `TRADE_COLUMNS` (the oracle-pinned core list,
  D-02/D-05 must NOT touch), `build_trade_log`.
- `itrader/reporting/summary.py` — `SLIPPAGE_COLUMNS`/`COMMISSION` append-after-
  `TRADE_COLUMNS` precedent; `build_summary` (`final_cash`/`starting_cash`).

### Phase / requirements / roadmap
- `.planning/ROADMAP.md` §"Phase 8: Admission, Position Management & Cash Edges" —
  goal + 3 success criteria + the Phase 6 parallelization REMINDER (shared infra
  committed first; hand-verify in deliberate batches; LONG-ONLY).
- `.planning/REQUIREMENTS.md` — ADMIT-01..04 (`~L71-74`), CASH-01..02 (`~L83-84`).
- `itrader/price_handler/store/csv_store.py` — `CsvPriceStore` + `csv_paths`
  passthrough (the contrived-CSV data seam).

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- **`run_scenario` harness + `--freeze`** (`tests/e2e/conftest.py`) — full
  build-run-diff machinery; Phase 8 adds the cash-ledger snapshot to its
  serialization (opt-in) and extends the emitter.
- **Orders-snapshot opt-in golden** (Phase 6 D-08) — the exact pattern D-02's
  cash-ledger snapshot mirrors; reused verbatim for ADMIT-03 max_positions
  REJECTED.
- **Operator/cancel infra** (Phase 6) — the CANCELLED trigger for CASH-02.
- **`spec.exchange` re-init seam** (Phase 7 D-14) — the `max_order_size` lever for
  the REFUSED trigger.
- **`ScriptedEmitter` + `ScenarioSpec` + leaf copy-template** — clone per leaf;
  extend the emitter with `allow_increase`/`max_positions` (D-06); `exit_fraction`
  already supported.
- **All admission / position-mgmt / cash engine logic already exists** — scale-in
  fall-through, `exit_fraction` partial close, `max_positions` gate, re-entry path,
  reserve/release + `CashOperation` ledger. Phase 8 COVERS these, does not build
  them.

### Established Patterns
- **Self-contained, parallel-safe leaf folders** — basis for D-04 slicing + the
  parallel waves.
- **Diff-what's-frozen / presence=assertion / exact no-tolerance diff** — the
  cash-ledger snapshot + max_positions orders-snapshot follow this.
- **Behavior-preserving / oracle-dark** — own bars / configured strategy; the
  BTCUSD oracle is never touched; the cash-ledger serializer stays out of core
  `TRADE_COLUMNS` and only fires opt-in.
- **Foundational-plan-first** (Phase 6 D-13 / Phase 7 D-16) — shared scaffolding +
  one canary + oracle re-run byte-exact before the parallel wave.
- **Deliberate two-outcome leaf when the contrast is the point** (Phase 7 D-11) —
  the basis for the scale_in + CASH-01 fold (D-04 leaf 1).

### Integration Points
- Cash-ledger snapshot: `cash_manager.get_cash_operations()` → determinism-safe
  serializer → opt-in golden in `run_scenario` (orders-snapshot pattern).
- `ScriptedEmitter.allow_increase`/`.max_positions` → `BaseStrategyConfig` →
  `SignalEvent.allow_increase`/`.max_positions` → `_enforce_position_admission`.
- `spec.exchange.limits.max_order_size` → `simulated._admit_order` `validate_order`
  → `FillEvent(REFUSED)` → on_fill release (CASH-02 REFUSED).
- ADMIT-03 / CASH-02-rejected REJECTED → opt-in orders-snapshot + cash-ledger
  (no-orphan) diff.
- `tests/e2e/{admission,cash}/` leaves ← built on all the above in the parallel
  waves.

</code_context>

<specifics>
## Specific Ideas

- **Non-duplication drove the CASH-01 framing (D-01).** The user explicitly did
  not want CASH-01 to re-prove Phase 7's SIZE-03 — it must carry its own weight
  via a position-management trigger (scale-in exhaustion) AND a new assertion lens
  (the cash-ledger, not the order mirror).
- **Faithfulness over symmetry (D-03).** Rather than force all three CASH-02
  terminal states into an identical "positive release" shape, the coverage tells
  the truth: CANCELLED/REFUSED hold-then-release; REJECTED structurally cannot
  hold a reservation, so it asserts the absence of an orphan. The honest model is
  the spec.
- **The cash-ledger snapshot is the phase's one new artifact (D-02).** The user
  chose a real per-operation ledger view (RESERVATION/RELEASE rows + balance
  trail) over the cheaper "available_cash returns to full" assertion — because the
  latter can't distinguish a never-reserved order from a reserved-then-released
  one, and proving the release actually FIRED is the point of CASH-02.

</specifics>

<deferred>
## Deferred Ideas

- **RNG-driven REFUSED (`simulate_failures`)** — the simulated exchange can refuse
  via a seeded random-failure path (`simulated.py:~L138-151`). Deliberately NOT
  used for CASH-02 REFUSED (D-03) in favor of the deterministic `max_order_size`
  validation failure. Revisit only if a future phase needs to cover the
  random-failure path itself.
- **Multi-portfolio / contended cash reservation** — cash isolation across
  portfolios and two strategies competing for one portfolio's cash — **Phase 9**
  (MULTI-03/MULTI-04). Phase 8 stays single-portfolio.
- **Explicit reserve-then-REJECTED engine path** — considered for CASH-02
  symmetry and rejected (D-03): no such path exists, and adding one violates
  behavior-preserving / coverage-only. Owner-gated if ever needed.
- **Per-bar `order_type` override in the emitter** (carried from Phase 7
  deferred) — still unwired; Phase 8 uses per-instance `order_type` + contrived
  bars (the resting-limit-buy CANCELLED leaf uses a LIMIT-construction emitter).

None of these block Phase 8 — discussion stayed within scope.

</deferred>

---

*Phase: 8-Admission, Position Management & Cash Edges*
*Context gathered: 2026-06-10*

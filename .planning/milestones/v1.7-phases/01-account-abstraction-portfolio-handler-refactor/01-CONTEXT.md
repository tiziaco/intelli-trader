# Phase 1: Account Abstraction + Portfolio/Handler Refactor - Context

**Gathered:** 2026-06-30
**Status:** Ready for planning

<domain>
## Phase Boundary

Behavior-preserving, **oracle-gated** extraction of an `Account` abstraction that owns
balance/margin **truth**, pulled out of `Portfolio` (cash) and `PortfolioHandler` (margin/liquidation
math). Phase 1 builds the **`Simulated*` side only** (verbatim today's spot/margin math); `Venue*`
leaves and the `LiveConnector` are **interface-only**. Plus three cleanups: strip `Portfolio.user_id`,
**delete** `TradingInterface`, and shape the `LiveConnector` interface so Phases 2–5 build against a
stable contract.

**The universal gate:** the backtest oracle stays **byte-exact (134 / `46189.87730727451`)** after
the extraction — this is pure code-motion behind the existing `PortfolioReadModel` seam and must not
ripple into the order domain. No live code may merge against `Account` until the backtest is
re-confirmed byte-exact. (ACCT-01..06; gates all of v1.7.)

</domain>

<decisions>
## Implementation Decisions

### Account ABC leaf shape (gray area 1)
- **D-01:** The `Account` family uses **inheritance on the cash-vs-margin axis** and **sibling leaves
  on the simulated-vs-venue axis**:
  ```
  Account (ABC)            # balance / available / reserve / release contract
   ├─ SimulatedCashAccount         (spot: deposit/withdraw/fill cash-flow — CashManager code-motion)
   │    └─ SimulatedMarginAccount(SimulatedCashAccount)   (adds lock_margin, maintenance_margin,
   │                                                        liq price/penalty, run_liquidation_pass)
   └─ Venue* leaves (interface-only this phase)
  ```
- **D-02:** Rationale — margin is a strict **superset** of cash (it needs balance/available/reserve
  *and* adds locks + liquidation math), so inheritance models it honestly with zero duplication. The
  simulated-vs-venue axis is genuinely two implementations of one contract → it reuses the established
  ABC + sibling-leaf pattern (`fee_model`, `slippage_model`, `exchanges`). "Single unified class" was
  rejected because **ACCT-01 literally commits to two leaves** (`SimulatedCashAccount` +
  `SimulatedMarginAccount`); "siblings (no inheritance)" was rejected because it duplicates shared
  balance logic or over-fattens the ABC.
- **D-03:** The existing `enable_margin` config flag
  (`config.trading_rules.enable_margin`, today branching `_process_transaction_spot` vs
  `_process_transaction_margin`) **graduates from a runtime branch to leaf selection at wiring time** —
  same decision input, cleaner expression (which leaf class to construct).
- **D-04 (plan must pin):** Determine whether the **SMA_MACD oracle runs spot or margin** — that
  decides which leaf the byte-exact gate actually exercises (v1.4 means it likely trades on margin, so
  `SimulatedMarginAccount` is on the hot path and must be verbatim code-motion).

### reserve/release home (gray area 2)
- **D-05:** `reserve`/`release` **mechanics move onto the `Account`** (they are `CashManager` methods —
  `reserve_cash`/`release_reservation`, and the margin analogues `lock_margin`/`release_margin` — and
  ride along with the `CashManager → SimulatedCashAccount` code-motion). The Account-level signature
  **drops `portfolio_id`** (it *is* the single account under LX-04 1:1):
  `account.reserve(order_id, amount)` / `account.release(order_id)`.
- **D-06:** The **`PortfolioReadModel.reserve(portfolio_id, order_id, amount)` seam stays on
  `PortfolioHandler` unchanged** — it must, because it is keyed by `portfolio_id`, which `Account` has
  no notion of. It simply re-points its delegation: `get_portfolio(portfolio_id).account.reserve(...)`
  instead of `...cash_manager.reserve_cash(...)`.
- **D-07:** Net effect — **zero ripple into the order domain.** The seam signature and every
  order-domain caller (`admission_manager`, `lifecycle_manager`, `reconcile_manager`) are untouched.
  Pushing the `portfolio_id`-keyed method *down* onto `Account` is explicitly rejected (would leak
  portfolio identity into the account layer).

### TradingInterface fate — LX-14 (gray area 3)
- **D-08:** **Delete `TradingInterface`.** It is effectively dead code (referenced only by the
  `trading_system/__init__.py` barrel export + a test *docstring* mention; not instantiated or wired
  into `LiveTradingSystem` composition), and it carries a live-path **float-money leak** (D-09 in the
  oracle notes; `quantity: float`). Deleting it *helps* the `mypy --strict` / no-float-money gate.
  Scope of deletion: the class, the barrel export, and fixing the test-docstring reference in
  `tests/unit/order/test_admission_rules.py`.
- **D-09:** **Lock only the *principle* for the surviving engine command surface** — FastAPI calls a
  **thin, explicit engine command surface** and the web layer **never reaches into `LiveTradingSystem`
  internals**. The **actual command method set is deferred to Phase 4**, when the live path first has a
  real consumer (`LiveTradingSystem` wired end-to-end). Designing it now would be speculative — there
  is no live consumer in Phase 1. This satisfies ACCT-05 as a *decided direction* and scopes FL-13
  (test the surface that survives).

### LiveConnector interface scope (gray area 4)
- **D-10:** `LiveConnector` is a **thin `runtime_checkable Protocol` marker** (D-07 structural-seam
  consistency with `AbstractExchange`) that **names the arm boundaries** — data arm, order arm,
  lifecycle — so Phase 2 knows the slots to fill, but the **real signatures are shaped against OKX in
  Phase 2** (async submit→ack→fill, `confirm`-flag, balances/positions). The spec's own "Open items"
  (native-vs-ccxt gap list, rate-limit accounting) confirm these are Phase-2 concerns.
- **D-11:** `VenueAccount` is an **interface-only stub leaf of the `Account` ABC** this phase. Its
  *stable contract comes from the `Account` ABC* (D-01) — **not** from the connector — so it does not
  need a rich `LiveConnector` to be shaped. The connector→`VenueAccount` data flow (push-stream vs
  pull-getter, sync vs async, OKX payloads) is explicitly **Phase 2 (CONN-*) / Phase 5 (RECON-01)**.
  This avoids the premature-interface trap of freezing connector signatures before the integration
  exists.

### File placement (gray area 5)
- **D-12:** The `Account` family lives in a **new `itrader/portfolio_handler/account/` subdir — a peer
  to the four managers (`cash/ position/ transaction/ metrics/`)**, NOT a top-level `account_handler/`.
  Reason: `*_handler` in this codebase means a thin **queue-facing** interface layer; `Account` has
  **no queue and emits no events** (the liquidation `global_queue.put` *emission* stays in
  `PortfolioHandler` by design), so `account_handler/` would misrepresent it. The spec frames `Account`
  as "the same pattern as its four managers," and under LX-04 1:1 `Account`/`Portfolio` share scope —
  not an independent domain. Layout:
  ```
  portfolio_handler/account/
    __init__.py
    base.py        # Account ABC
    simulated.py   # SimulatedCashAccount, SimulatedMarginAccount(SimulatedCashAccount)
    venue.py       # VenueAccount (interface-only stub leaf)
  ```
  (`cash/` is likely **absorbed** here since `CashManager` *becomes* `SimulatedCashAccount` — a planner
  detail, not a folder decision.)
- **D-13:** The `LiveConnector` interface lives in a **new top-level `itrader/connectors/` package**
  (`connectors/base.py` for the Protocol now). It is NOT a portfolio concern — it spans data + order
  arms, broader than execution. Anticipates Phase 2 `connectors/okx.py` (`OkxConnector`) and Phase 4
  `connectors/paper.py` (`PaperConnector`). `VenueAccount` stays in `account/venue.py` (it is an
  `Account` leaf, not a connector).

### Claude's Discretion
- The mechanical code-motion itself, constructor-signature-ripple resolution (`add_portfolio(user_id,
  ...)` → user_id strip), the `Portfolio.cash → Portfolio.account.balance` delegation wiring,
  `mypy --strict` cleanliness, and oracle re-confirmation are implementation details handled at plan/
  execute time (Research flag: SKIP — code-motion only; v1.2 MOD-01 OrderManager-decomposition playbook
  applies).

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase scope & requirements
- `.planning/ROADMAP.md` §"Phase 1: Account Abstraction + Portfolio/Handler Refactor" — goal, success
  criteria, dependencies, Research flag (SKIP).
- `.planning/REQUIREMENTS.md` — **ACCT-01..ACCT-06** (the six requirements this phase satisfies).
- `.planning/STATE.md` §"Milestone Gate (v1.7)" — the recurring oracle/perf gate applied every phase.

### Locked design (the sketch)
- `docs/superpowers/specs/2026-06-30-live-trading-milestone-design.md` §"Phase 1 — Account abstraction
  + Portfolio/PortfolioHandler refactor" (lines ~89–127) — the locked source: leaf diagram, LX-03,
  the `user_id` strip, the `TradingInterface` LX-14 evaluation, and the three "Open items" this
  discussion resolved (leaf split / reserve-release home / TradingInterface). Also the LX-01..LX-15
  decision table and the symmetry table (sim computes / venue caches).

### App-layer context (informs TradingInterface deletion + user_id strip)
- `.planning/milestones/v1.6-phases/03-operational-sql-backends-2-store-layer/03-CONTEXT.md` — the
  FastAPI application-layer plan (D-01/D-02/D-09): FastAPI owns the app layer and the
  `user_id → portfolio/account` mapping, which is *why* `TradingInterface` is redundant and
  `Portfolio.user_id` is app-layer (must NOT relocate onto `Account`).

### Code touch-points (the extraction targets)
- `itrader/portfolio_handler/portfolio.py` — `cash` property, `_process_transaction_spot`/`_margin`,
  `_accrue_short_carry`, `available_cash`, `user_id` (lines 46/52/850); the `enable_margin` branch
  (line 303).
- `itrader/portfolio_handler/cash/cash_manager.py` — **becomes `SimulatedCashAccount`** (balance,
  available, reserve_cash/release_reservation, lock_margin/release_margin, accrue_borrow_interest).
- `itrader/portfolio_handler/portfolio_handler.py` — margin/liq math to move into `Account`:
  `maintenance_margin`, `margin_ratio`, `_isolated_liq_price`, `_liquidation_penalty`,
  `_liquidate_position`, `_run_liquidation_pass`; `reserve`/`release` seam (276–284); `add_portfolio`
  signature (152). **Liquidation `global_queue.put` emission STAYS here.**
- `itrader/core/portfolio_read_model.py` — the `PortfolioReadModel` Protocol (`reserve`/`release` at
  127/146) the seam must continue to satisfy unchanged.
- `itrader/execution_handler/exchanges/base.py` — `AbstractExchange` `runtime_checkable Protocol` (the
  D-07 pattern `LiveConnector` mirrors).
- `itrader/trading_system/trading_interface.py` — the file to **delete**;
  `itrader/trading_system/__init__.py` barrel export to remove;
  `tests/unit/order/test_admission_rules.py:267` docstring reference to fix.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- **`PortfolioReadModel` seam** (`core/portfolio_read_model.py`): already the read boundary between the
  order domain and portfolios — the refactor hides entirely behind it, which is what keeps the
  order-domain ripple at zero.
- **ABC + sibling-leaf pattern** (`fee_model/`, `slippage_model/`, `exchanges/`): the precedent the
  simulated-vs-venue axis reuses.
- **The four manager subdirs** (`cash/ position/ transaction/ metrics/`): the structural precedent
  `account/` joins as the fifth peer delegate.
- **v1.2 MOD-01 OrderManager-decomposition playbook**: the prior behavior-preserving extraction this
  phase mirrors.

### Established Patterns
- **`*_handler` = queue-facing thin layer only.** Managers/delegates have no queue access — confirmed
  for `cash/`, `position/`. `Account` follows the manager (queue-free) pattern, NOT the handler one.
- **Decimal end-to-end**; tabs in handler/manager modules (match the file); UUIDv7; seeded RNG +
  injected clock.
- **Liquidation emission stays in the handler** — math moves to `Account`, the `global_queue.put`
  does not (queue-only rule preserved, ACCT-02).

### Integration Points
- `Portfolio.__init__` constructs its `account` (leaf chosen by `enable_margin`) the same way it
  constructs its four managers; `Portfolio.cash` → `Portfolio.account.balance`.
- `add_portfolio(...)` constructor ripple from the `user_id` strip — touches golden-master wiring
  (`backtest_trading_system.py:466`, `system_spec.py`, `validators.py`); do deliberately, re-confirm
  byte-exact.

</code_context>

<specifics>
## Specific Ideas

- The oracle byte-exact gate is the hard ceiling on every choice: `134 / 46189.87730727451`,
  determinism double-run identical, `mypy --strict` clean, no float-for-money, `filterwarnings=["error"]`
  green, no W1/W2 perf regression vs the v1.5 baseline (15.7 s / 152.8 MB).
- The user values the refactor reading consistently with the existing codebase patterns over literal
  fidelity to the spec's diagram (drove the inheritance + folder-placement calls).

</specifics>

<deferred>
## Deferred Ideas

- **Engine command surface (concrete method set)** → **Phase 4** — defined when `LiveTradingSystem` is
  wired end-to-end and FastAPI/FL-13 have a real target. Principle locked here (D-09).
- **`LiveConnector` real signatures** (async submit→ack→fill, `watch_ohlcv`, balances/positions, OKX
  `confirm`-flag, rate-limit accounting) → **Phase 2** (CONN-*); shaped against OKX reality.
- **`VenueAccount` connector-coupled implementation** (caching venue balance/margin/position streams,
  per-symbol drift reconciliation) → **Phase 5** (RECON-01). Phase 1 ships the stub leaf only.
- **`Venue*` cash/margin leaf bodies** (the computed-vs-cached split) → Phase 5.

</deferred>

---

*Phase: 1-account-abstraction-portfolio-handler-refactor*
*Context gathered: 2026-06-30*

# Account Addressability & Liquidation Ownership — Design Spec

- **Date:** 2026-07-31
- **Status:** DRAFT (brainstorm output; ready for user review, then planning)
- **Branch context:** `v1.81/phase-11.3-refactor-venues`
- **Path posture:** margin-only / **oracle-dark** — the SMA_MACD golden (`final_equity 46189.87730727451`)
  is liquidation-dark and must stay byte-exact.
- **Deliverable of this doc:** a design the planner can decompose; scope is deliberately larger than
  the defect that surfaced it, because the defect is a symptom.

> Decision tags are written `AL-NN` (Account/Liquidation). They are citable by downstream plans.
> Per the repo convention, `D-NN` tags are per-phase counters and do **not** form a global namespace —
> cite `AL-NN` or state the claim outright.

---

## 1. North Star & scope posture

**Core value:** a forced liquidation should be produced by the component that actually owns the
account it liquidates. Today it is produced by the portfolio, which reaches across a domain boundary
to write another domain's storage — and it does so because there is no way to reach an account
except through a portfolio.

### The defect that surfaced this

`PortfolioHandler._liquidate_position` (`itrader/portfolio_handler/portfolio_handler.py:610-673`)
force-closes a breached margin position by:

1. minting a real opposite-side `Order` tagged `OrderTriggerSource.LIQUIDATION`,
2. **writing it into the order mirror** — `self._order_storage.add_order(order)` (line 673),
3. putting a `FillEvent(EXECUTED)` on the queue at `time=bar_time`.

Line 673 is the **only** `add_order` call outside `order_handler/`. Every other writer is
`AdmissionManager` (`admission_manager.py:247, 286, 841`) or `BracketManager`
(`bracket_manager.py:183, 185, 187, 318, 319`). The handle it writes through is injected by
`set_order_storage` (`portfolio_handler.py:553-558`, wired at `trading_system/graph.py:223`), with a
`StateError` guard at `:630-636` and a silent `return` gate at `:717`.

This was a **known, accepted** contract violation, not drift: v1.4 phase 04-03 logged it as threat
`T-04-03-SEAM`, categorised *"Tampering (cross-domain WRITE-contract violation)"*, disposition
*mitigate*, with the mitigation being "make the seam narrow and injected rather than a raw handler
call." The stated justification for not using the queue was that an ORDER-route enqueue *"would fill
next-bar-open"* — correct (`exchanges/simulated.py:341`), but it rules out only the **execution**
route, not every queue-based handoff.

### The real problem (AL-01)

The storage handle is a symptom. Two things are fused inside one method:

- **decide what to close** (breach detection, liq price, penalty), and
- **admit the order into the system** (`add_order`).

Both mature frameworks split exactly there (§3). And the reason iTrader *couldn't* split them is
structural: **an `Account` is reachable only through a `Portfolio` instance.** `Portfolio.__init__`
receives the built leaf and stores it; per its own comment (`portfolio_handler/portfolio.py:124`),
`account_id` / `venue_name` *"are not stored here — they are read-only properties over
`self.account`, the ONE storage site for the pair."*

So the account is **venue-scoped in its data** (it carries `(venue_name, account_id)`) but
**portfolio-owned in its access**. There is no way to ask the system for "account X at venue Y".
That single fact is what makes every candidate seam feel wrong (§4).

### In scope

- Making `Account` addressable by `(venue, account_id)` independently of `Portfolio`.
- Moving liquidation production out of `portfolio_handler` to the component that owns the account.
- Deleting `set_order_storage`, `PortfolioHandler._order_storage`, and the `StateError` guard.
- Deciding how a venue-originated fill enters the order mirror (AL-05 — the crux).

### Explicitly out of scope

- **The `ForceCloseEvent` primitive** — designed in
  `docs/superpowers/specs/2026-07-13-force-close-event-design.md` (DRAFT, unimplemented). See §6.
- **Operator emergency shutdown / targeted operator close** — `.planning/todos/pending/`.
- **The margin-equity double-count defect** (`.planning/todos/pending/margin-equity-double-counts-notional-wr01.md`,
  auto-memory `wr01-margin-equity-frozen-golden-gap`). Independent, but it shares the same goldens,
  so sequencing matters (§7).
- Any change to the spot/cash path. Liquidation is margin-only and oracle-dark.

---

## 2. Evidence gathered this session

### 2.1 The reorder spike (executed, then reverted)

A full working implementation of the queued-event option (option A, §4) was built and run, to replace
speculation with measurement:

| Result | Detail |
|---|---|
| Full suite | **2951 passed, 7 failed** |
| Liquidation e2e | **3/3 pass** — `forced_liq_long`, `forced_liq_short`, `levered_long_into_liquidation` |
| Backtest oracle | **passes** — byte-exact, as predicted (liquidation-dark) |
| The 7 failures | **all harness-contract, zero behavioural** |

The failures decompose as: 6 unit tests that call `_liquidate_position` /
`update_portfolios_market_value` directly with **no `EventHandler`**, then drain the queue expecting a
`FillEvent` (the new event sits unconsumed); plus
`test_live_bar_feed_route_order.py::test_direct_emission_preserves_bar_route_order`, whose
`SimpleNamespace` spies lack the new method the route literal names.

**Two findings the green run does not license as "safe":**

- **The settlement order changes.** Today the liquidation `FillEvent` is queued *at detection*, so it
  settles **first** among the bar's events. Under a queued handoff the consumer only emits the fill
  when it processes the event, so it settles **last** — behind `execution_handler.on_market_data` and
  the signal→order chain. Same `bar_time`, different sequence.
- **The suite does not exercise the interaction.** `forced_liq_long` asserts exactly 2 orders (the
  open + the liquidation); no resting bracket competes on the breach bar. So the 3/3 pass means
  *"unexercised"*, not *"proven equivalent"*. A resting stop on a breaching position would diverge
  between the two designs and nothing would catch it.

**Judgement (AL-02):** liquidation-first is the more defensible semantic — a venue force-closes
immediately rather than waiting for your resting orders to fill. The current behaviour is right and
the suite does not encode it. **Any design that reorders it must add a test asserting
liquidation-first before changing it.**

### 2.2 Prior-art research

**Nautilus** (read from installed source, `nautilus-trader 1.227.0`):

- Margin math lives on the **account**, delegating to a pluggable model:
  `MarginAccount.calculate_margin_init/calculate_margin_maint`
  (`accounting/accounts/margin.pxd`) → `MarginModel` / `StandardMarginModel` / `LeveragedMarginModel`
  (`accounting/margin_models.pxd`).
- `Portfolio` is a **pass-through reader**: `margins_maint()` resolves
  `account = self._get_account(venue, account_id)` and returns `account.margins_maint()`
  (`portfolio/portfolio.pyx:846-866`). Its constructor takes `cache: CacheFacade` — *"The read-only
  cache for the portfolio."*
- `Portfolio` **never mints orders**: `grep OrderFactory|submit_order|MarketOrder(` over
  `portfolio/*.pyx` returns nothing.
- Accounts are mutated by `AccountsManager` (`update_balances(account, instrument, fill)`,
  `update_orders`, `update_positions` — `accounting/manager.pxd`), driven by `OrderFilled` and venue
  `AccountState` events.
- **Nautilus does not simulate liquidation at all.** Every `margin_call` / `liquidat` mention in the
  package is in venue adapters (Binance futures, OKX, Bybit, Kraken) — ingesting venue reports. The
  only core concept is an exception, `AccountMarginExceeded`, whose docstring says *"In this scenario
  some form of liquidation event will occur."* Their position: the venue liquidates.
- *Verification limit:* the matching engine is compiled Rust; the Python/Cython surface and the
  adapter distribution were verified, the Rust internals were not.

**LEAN** (source + docs):

- `GetMarginCallOrders(...)` returns `List<SubmitOrderRequest>` — it **decides** and returns data,
  writing nothing.
- `ExecuteMarginCall(...)` submits via the transaction handler:
  `tickets.Add(Portfolio.Transactions.AddOrder(request));`
- The margin-call **trigger** reads portfolio-level aggregates (`Portfolio.TotalMarginUsed`,
  `TotalPortfolioValue`, `GetMarginRemaining`); per-position margin comes from
  `positionGroup.BuyingPowerModel`.

**Synthesis (AL-03):** neither framework lets the portfolio write the order store. LEAN splits
*decide* from *admit*; nautilus doesn't let the portfolio near either. **iTrader already places the
margin math correctly** — it lives on `SimulatedMarginAccount` (`_liq_inputs`,
`_isolated_liq_price`, `_liquidation_penalty`), and `PortfolioHandler.maintenance_margin` is
documented as *"A pass-through to `SimulatedMarginAccount`."* That is nautilus's shape. The
divergence is **account reachability**, not math placement.

---

## 3. Decisions locked this session

| Tag | Decision | Rationale |
|-----|----------|-----------|
| AL-01 | **The root cause is account addressability, not the storage handle.** `Account` is venue-scoped in data but portfolio-owned in access. | Every candidate seam (§4) is awkward in a way traceable to this one fact. Fixing a seam without fixing reachability relocates the problem. |
| AL-02 | **Liquidation-first settlement is the correct semantic and must be pinned by a test before any reorder.** | A venue force-closes immediately. The current engine relies on this implicitly and no test encodes it; the spike proved the suite cannot detect a change. |
| AL-03 | **Margin math stays on the account leaf.** No relocation of `_liq_inputs` / `_isolated_liq_price` / `_liquidation_penalty`. | Matches nautilus (`MarginAccount` + `MarginModel`) and LEAN (`BuyingPowerModel`). iTrader is already correct here; touching it would be churn. |
| AL-04 | **The exchange must not take a `PortfolioReadModel`.** | The venue does not need the *portfolio*; it needs the *account*. Injecting the portfolio read-model is passing the wrong object because the right one is unaddressable — it would encode AL-01 rather than fix it. |
| AL-05 | **Venue-originated fill provenance is the crux and must be designed explicitly.** | A venue liquidation is a fill for an order the system never submitted; `ReconcileManager.on_fill` early-returns on unknown orders. This is *why* `add_order` was called from the portfolio. It is the same problem the live path already faces. |
| AL-06 | **Simulated and live liquidation should converge on one path.** | On OKX the venue force-closes and you learn from an unsolicited fill. Modelling sim as "we chose to close" while live is "we were closed" guarantees two mechanisms that drift. |
| AL-07 | **Oracle-dark by construction; the three liquidation e2e goldens are the real gate.** | `liquidation_fee_rate=0` and margin off on the SMA_MACD path → zero breaches. The margin goldens, however, were never externally cross-validated (see §7). |

---

## 4. Options considered

| Option | Shape | Verdict |
|---|---|---|
| **A — `LiquidationEvent` on the queue** | Portfolio detects + emits; order domain mints, registers, emits the fill. | **Viable, measured** (§2.1): 2951 pass, harness-only failures. Rejected as the *target* because it reorders settlement (AL-02) and still models liquidation as a system-chosen close (AL-06). |
| **B — Typed `LiquidationSink` Protocol** | Order domain exposes a narrow write-seam mirroring `PortfolioReadModel.reserve/release/drop_pending`; portfolio calls it, gets a registered `Order`, emits the fill in place. | This is **LEAN's exact shape** (`Transactions.AddOrder(request)`). Preserves ordering, zero behaviour change, cheap. Rejected as the target because it keeps the portfolio as the decider and leaves AL-01 untouched. **Retained as the interim option** (§5). |
| **C — Breach scan on the BAR route, order-side** | `OrderHandler` gains a BAR-route entry after the portfolio mark. | Rejected: drags `SimulatedMarginAccount` internals across the boundary — worse coupling than the defect. |
| **D — The venue owns liquidation** | The exchange reads the account it owns, evaluates the maintenance breach like a trigger, produces the fill. | **The target.** Matches nautilus and iTrader's own stated principle (*"the exchange … is the source of truth for fills"*). `MatchingEngine` already fills same-bar on intrabar trigger evaluation, so the next-bar-open objection that killed the ORDER route does not apply. Blocked on AL-01 + AL-05. |

**Why B is not a stepping stone to D.** B moves the mint portfolio → order-domain; D moves the
concern portfolio → execution-domain. Different axes. If D ships, B's Protocol is discarded. B is
justified only as a cheap interim that closes the defect without making D harder — not as phase 1 of D.

---

## 5. Target design (D)

### 5.1 Account addressability (AL-01)

Introduce a lookup keyed on `(venue, account_id)` — nautilus's `_get_account(venue, account_id)`
shape — so any component can resolve an account without traversing a `Portfolio`.

iTrader already holds **half** of this. `venues/accounts.py` owns `AccountSpec` (one durable
`venue_accounts` row) and `VenueAccountManager`, and the order path already routes on
`(venue, account_id)`. The compute leaf under `portfolio_handler/account/` holds the same pair as
read-only properties. **The two were never unified** — CLAUDE.md states the split as deliberate:
*"Venue truth is deliberately not an account leaf."*

The design question this spec hands to planning: **do the venue-account record and the compute leaf
become one object, or does the registry index the existing leaves?** The second is far cheaper and
probably sufficient — it needs no change to how accounts are built or to `AccountSnapshot`.

### 5.2 Liquidation moves to the venue

With addressability in place, `SimulatedExchange` resolves the account for the pair it is already
serving and evaluates the maintenance breach where it already evaluates stop/limit triggers against
intrabar high/low. `SimulatedMarginAccount` keeps every formula (AL-03). No `PortfolioReadModel`
appears anywhere (AL-04).

`PortfolioHandler` loses `_liquidate_position`, `_run_liquidation_pass`, `set_order_storage`,
`_order_storage`, and the `StateError` guard. It keeps breach *reporting* surfaces
(`maintenance_margin`, `margin_ratio`) as pass-throughs.

### 5.3 Fill provenance (AL-05 — must be concluded before implementation)

The venue emits a fill for an order that was never admitted. Options, in rough preference order:

1. **Venue emits an `OrderEvent` first**, the order domain registers it, then the fill — keeps the
   mirror's "every fill has an order" invariant, costs one extra hop, and risks reordering (AL-02).
2. **Extend `ReconcileManager` to admit venue-originated fills** by minting the mirror row on
   arrival — converges sim with the live unsolicited-fill path (AL-06) and reuses `VenueReconciler` /
   `seed_applied_trades` vocabulary. Larger, but the one that actually unifies.
3. Keep a narrow order-domain registration call from the venue — smallest, but re-creates a
   cross-domain write one layer down.

**This is the single largest open question in the spec** and should be resolved before any plan is
written.

---

## 6. Relationship to the ForceCloseEvent spec

`docs/superpowers/specs/2026-07-13-force-close-event-design.md` (DRAFT, **verified unimplemented** as
of this date: no `EventType.FORCE_CLOSE`, no `ForceCloseEvent`, no `on_force_close` in `itrader/`;
`Order.strategy_id` still non-optional at `order_handler/order.py:54`; `universe_handler.py:83` still
holds the module-level `_idgen`, line 653 still fabricates a `StrategyId`).

**They are complementary, not competing.**

- That spec covers a **venue market exit** (universe force-remove, operator close): build a MARKET
  order, route it through execution, let the venue fill it. Its §3.3 step 6 already puts `add_order`
  **in the order domain** — so it independently establishes the principle this spec's defect violates.
- This spec covers a **venue-computed forced fill**: settled at a computed maintenance price on the
  breach bar, never routed through execution.
- That spec explicitly scoped margin liquidation out, calling it *"a synthetic-fill-at-a-computed-price
  path — a genuinely different animal from a venue market exit."* **That observation is correct and
  nautilus agrees with it.** What this spec revises is only the conclusion drawn from it: being
  venue-computed is an argument for the work living *in the venue*, not for it staying in
  `portfolio_handler`.

**Shared dependency:** FC-02 makes `strategy_id` optional, which deletes the fresh-`StrategyId` mint
inside `_liquidate_position` (that spec's §3.6 lists the one-liner). Whichever lands first should
carry it. *Note:* that spec's line citations have drifted (it cites `portfolio_handler.py:536` /
`:548-549`; the code now sits at `610-673`).

---

## 7. Risks & sequencing

- **The margin goldens are not oracle-backed.** Per auto-memory `wr01-margin-equity-frozen-golden-gap`,
  the frozen margin goldens were never externally cross-validated. So a diff in the three liquidation
  e2e scenarios cannot adjudicate which version is correct — only that something moved. **Mitigation:**
  land AL-02's liquidation-first test *before* any behavioural change, so at least the ordering
  invariant is pinned by intent rather than by accident.
- **Overlap with WR-01.** `margin-equity-double-counts-notional-wr01` touches the same goldens. Doing
  both concurrently makes attribution impossible. Sequence them.
- **Scope discipline.** The originating defect is one line (`:673`) and is fully closed by option B in
  a fraction of the effort. This spec deliberately targets the larger fix; if the account redesign is
  deferred, **B remains available and does not make D harder** — but it is disposable work, and that
  should be a conscious trade, not a default.
- **v1.81 adjacency.** Account addressability reaches into the venue/account substrate refactored in
  v1.81. Planning should confirm nothing here contradicts decisions locked there.

---

## 8. Verification strategy

- **Oracle:** `tests/integration/test_backtest_oracle.py` byte-exact at `46189.87730727451`.
  Guaranteed by construction (liquidation-dark), proven by the run.
- **Ordering invariant (new, AL-02):** a test asserting the liquidation fill settles before any
  competing resting-order fill on the breach bar. **This does not exist today and must be written
  first.**
- **The three liquidation e2e scenarios:** every hand-computed literal unchanged — realised PnL,
  equity floor (`equity >= -WB`), cash balance, LIQUIDATION order FILLED at the quantized liq price.
- **The unexercised interaction:** a new scenario placing a resting stop on a position that breaches
  on the same bar — the case the current suite cannot see (§2.1).
- **Structural gate:** `grep -rn "add_order(" itrader/ | grep -v order_handler/` returns empty.
- `mypy --strict` clean; `filterwarnings=["error"]` / `--strict-markers` respected.

---

## 9. Decision log (citable)

`AL-01` root cause is account addressability · `AL-02` liquidation-first is correct, pin it with a
test first · `AL-03` margin math stays on the account leaf · `AL-04` no `PortfolioReadModel` in the
exchange · `AL-05` venue-fill provenance is the crux, unresolved · `AL-06` converge sim and live
liquidation · `AL-07` oracle-dark, margin e2e goldens are the gate.

---

## 10. Open questions for planning

1. **AL-05** — how does a venue-originated fill enter the order mirror? (§5.3, three options.)
2. **§5.1** — unify the venue-account record with the compute leaf, or index the existing leaves?
3. **Sequencing vs WR-01** — which of the two margin workstreams goes first?
4. **Interim B** — ship the cheap fix now and accept it as disposable, or leave `:673` in place until
   the redesign lands?

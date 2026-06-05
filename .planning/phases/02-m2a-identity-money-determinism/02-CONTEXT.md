# Phase 2: M2a — Identity, Money & Determinism - Context

**Gathered:** 2026-06-04
**Status:** Ready for planning

<domain>
## Phase Boundary

Lay the **structural foundations** the rest of the program builds on, across four axes:

1. **Identity** — replace the overflow-prone, type-encoding integer `id_generator` with a single
   **UUIDv7** scheme (`uuid-utils`), stored as native UUID (M2-01, #10 Critical).
2. **Money** — make money **Decimal end-to-end** (prices-as-money, quantities, cash, commissions,
   PnL) with no float round-trips and a centralized quantization policy (M2-02, #17).
3. **Typing** — `mypy --strict` clean across the in-scope package; hot-path DTOs/events
   `frozen=True`/`slots=True`; `NewType` ID aliases; the eight Py2 `__metaclass__` "abstract" bases
   become real ABCs/Protocols with non-conforming subclasses fixed (M2-03, M2-04, #8, #20).
4. **Determinism** — seeded RNG behind an injected `Random`; an injected clock (no local
   `datetime.now()` on the engine path); flat global O(1) order index by id (M2-05, #5, PERF2).

The WHAT is **fully locked** by `REQUIREMENTS.md` (M2-01…M2-05) and ROADMAP Phase 2's four success
criteria. This discussion resolved only the **HOW** — the decisions that move the oracle numbers
and set the scope/effort boundaries.

**Golden-master position:** M2a is **behavior-preserving** against the M1 behavioral oracle (trade
timing + sides + sequence are LAW). The **numerical** oracle is allowed to drift this phase from
the float→Decimal shift; it is **not** re-frozen until **M2b (Phase 3)** — one of PROJECT.md's two
sanctioned re-baseline points (after M2, after M5). UUIDv7 + injected clock are **oracle-safe by
construction** because M1's D-12 deliberately excluded integer-ID *values* and wall-clock/audit
timestamps from the captured oracle.

**Boundary with adjacent milestones (do NOT pull forward):**
- **M2b (Phase 3)** owns: config→Pydantic collapse, type centralization, portfolio storage seam,
  `time_parser` final, dead-code purge, bulk pytest conversion, **order-audit & transaction-timestamp
  determinism (SC2)**, and the **numerical-oracle re-freeze**.
- **M3 (Phase 4)** owns: event immutability + `event_id` + linkage IDs + dispatch registry (#11).
  M2a touches only the **six entity IDs**, not event ids.
- **M4 (Phase 5)** owns: cash-through-`CashManager` (#22) + the **DEF-01-A** commission-coercion
  final reconciliation + atomic transactions.
- **M5b (Phase 7)** owns: `calculate_signal` contract enforcement (#24), universe collapse (#33),
  reporting computation/presentation split + `print_summary` (#38), full sizing policy.

</domain>

<decisions>
## Implementation Decisions

### Money: Decimal precision & quantization (M2-02, #17)
- **D-01:** **Hybrid precision policy.** Carry a **28-digit default Decimal context** (Python's
  standard working precision) through all intermediate money math; **quantize only at money
  boundaries** (cash ledger, reported PnL, persistence/serialization) to **per-instrument scale**.
  This keeps the smallest possible numeric drift vs the M1 float oracle (lowest behavioral-oracle
  risk) while still producing exchange-realistic quantized money at the edges.
- **D-02:** **Quantization scale = per-instrument, via a lookup with a default + override.**
  BTC price/quantity → **8 dp**; USD cash/PnL/commission → **2 dp**. Only **BTCUSD** is traded in
  this program, so the lookup ships a sensible default and a single BTCUSD entry; a general
  per-cryptocurrency precision registry (e.g. 18-dp tokens) is **deferred** (see Deferred Ideas).
- **D-03:** **Rounding mode = `ROUND_HALF_UP`** at the quantization boundaries (matches #17's
  explicit suggestion; conventional, predictable financial rounding).
- **D-04:** **float→Decimal boundary = the money-path entry only.** A price value becomes `Decimal`
  via **`Decimal(str(x))`** (avoids float-repr artifacts) at the point it enters the money path —
  fill/execution price, position mark-to-market, and the `OrderManager` sizing seam (M1's D-09).
  The **indicator/analytics path stays float by design**: SMA/MACD on `ta`/`pandas-ta`, plots, and
  statistics operate on float64 arrays (#17 carve-out: "float acceptable for derived analytics where
  precision is not contractual" — a crossover is a crossover regardless of the 12th decimal). The
  defect being fixed is the **same-value float↔Decimal round-trip** (`portfolio.cash += float(...)`),
  not "a float exists somewhere." No money value round-trips back to float.

### Typing: mypy --strict scope (M2-03, #8)
- **D-05:** **In-scope strict + documented excludes.** Strict-clean everything on/around the
  backtest path + shared core (events, enums, exceptions, config, portfolio, order, execution,
  strategy, csv price feed, reporting). **Deferred subsystems get explicit
  `[[tool.mypy.overrides]]` excludes**, each commented with its deferral tag: `live_trading_system`,
  `trading_interface` (D-live); `sql_handler` (D-sql); `CCXT`/OANDA/`BINANCE_Live` (D-oanda/D-live);
  `screeners_handler` (D-screener). The exclude list shrinks only if a later milestone reworks that
  module. The program DoD's "mypy --strict clean" is interpreted as **clean over the in-scope
  package** (backtest-correctness-first; live/SQL are separate risk surfaces that may never run here).
- **D-06:** **Add a `make typecheck` gate now.** Add a `make typecheck` target + mypy config in
  `pyproject.toml`, wired into the test/make workflow, so M3/M4/M5 cannot silently regress strictness
  (program DoD calls for "mypy --strict in CI"). Stand the gate up at M2a where the cleanup happens.

### Typing: ABC vs Protocol for the 8 dead `__metaclass__` bases (M2-04, #20)
- **D-07:** **Per-#20 mix, not uniform.**
  - **Protocol** (pluggable swap-a-fake structural seams, no shared impl):
    `AbstractExchange` (exchanges/base — also the base whose dead enforcement let `SimulatedExchange`
    skip `configure()`), `AbstractPositionSizer` (position_sizer/base), `AbstractPriceHandler`
    (price/base — eases the M5 Provider/Store/Feed split #30).
  - **ABC** (subclasses inherit real shared code/lifecycle):
    `AbstractExecutionHandler` (holds queue + exchange registry + routing), `AbstractStatistics`,
    `Strategy` base (`strategy_id`/queue/`_generate_signal`), `Universe`, `Screener`.
- **D-08:** **Convert all 8 now (SC3) + minimal conformance; defer deep rework.** M2a makes each
  base a real ABC/Protocol and fixes the missing/mismatched method signatures **just enough** to
  conform + pass mypy (e.g. `SimulatedExchange.configure`, the `PriceHandler` `get_last_date`/
  `get_last_bar`/signature drift). The deeper module rework stays in its owning milestone:
  `calculate_signal` contract → M5b #24; universe collapse → M5b #33; reporting split +
  `print_summary` → M5b #38; screener wiring → deferred D-screener. The **screener base is converted
  (cheap)** despite the module being mypy-excluded (D-05).
- **D-08b (scope expansion, user-approved 2026-06-04):** Phase-2 research found the dead Py2
  `__metaclass__` pattern in **11 classes across 9 files** — two beyond D-08's named 8:
  `trading_system/simulation/base.py::SimulationEngine` and the two classes in
  `portfolio_handler/base.py`. The owner **approved converting all 11 now** (not flagging the 2 as a
  deferred delta). M2a therefore converts all 11 dead-metaclass bases to real ABCs/Protocols with
  minimal conformance fixes; log the 2-class expansion as a COVERAGE-INDEX §E gap-discovery delta.
  Per-base ABC-vs-Protocol classification for the 2 extras follows the D-07 policy (ABC when
  subclasses inherit shared impl/lifecycle; Protocol when it's a swap-a-fake structural seam).

### Determinism: clock & RNG (M2-05, #5, PERF2)
- **D-09:** **Injected clock returns simulation (bar/event) time** in backtest; live returns wall
  clock. Domain timestamps become deterministic & bar-derived. **Perf-telemetry `datetime.now()`
  legitimately stays wall-clock** (e.g. backtest run-duration in `backtest_trading_system.py` — it
  measures how long the run took, not a domain fact). Oracle-safe (D-12 excludes these).
- **D-10:** **M2a builds the mechanism + replaces engine-path sites only.** Build the injected
  `Clock` + seeded `Random` and replace `datetime.now()`/`random.*` on the **backtest engine path**.
  **Defer** the specific **order-audit (`order.py`) & transaction-timestamp determinism to M2b**
  (its SC2) to avoid double-ownership. Leave **live-mode** (`D-live`) status/uptime `datetime.now()`
  sites alone.
- **D-11:** **RNG = config seed behind an injected `random.Random`** (documented default seed),
  injected into the components that use `random` (`SimulatedExchange` failure-sim,
  fixed/linear slippage models). **Forbid module-level `random.*` in the engine.** No oracle impact
  (M1 oracle runs failure-sim off, zero slippage) — this future-proofs determinism per #5/PERF2.

### Identity: UUIDv7 migration (M2-01, #10)
- **D-12:** **Distinct `NewType` alias per entity:** `OrderId`, `PortfolioId`, `PositionId`,
  `TransactionId`, `StrategyId`, `ScreenerId` — each `NewType` over `uuid.UUID`. `mypy --strict`
  then flags any cross-entity id mix-up (the typing payoff of #10/#8; M2-03 "NewType ID aliases").
- **D-13:** **Drop the type-in-id encoding.** Type was encoded in the integer prefix (1=Transaction
  …6=Screener); **nothing decodes it today** (verified by scout — no `// 10**19`/prefix-decode
  sites). Type is now implicit in the entity class / field name / single-entity store; when Postgres
  lands (deferred D-sql) the **table IS the type**. No discriminator field added (#10 "stop encoding
  type into the key").
- **D-14:** **Native UUID end-to-end.** `id` fields typed `UUID` (not `str`/`int`), the flat order
  index is `Dict[UUID, Order]`, storage keys are native `UUID`; tighten the existing loose
  `Union[str, int]` keying (in `in_memory_storage.py`) to `UUID` (serves mypy --strict). #10 "store
  as native UUID, not string." Oracle-safe (D-12: trades identified by time/side, not id value).

### Claude's Discretion
- **idgen facade shape:** keep a thin `idgen` facade whose methods return `uuid_utils.uuid7()` to
  minimize churn at the ~7 call sites; the per-type generator methods collapse to a single `uuid7()`
  implementation. (Entity `event_id` redesign stays M3 #11 — M2a touches only the six entity IDs.)
- **Flat O(1) order index (PERF2):** the `Dict[UUID, Order]` index design/placement in storage.
- **`frozen=True`/`slots=True` rollout:** which hot-path DTOs/events get frozen+slots this phase
  (per #8 — hot-path internal events; note `SignalEvent.verified` mutation at `event.py:235` is a
  known immutability blocker — coordinate with M3's event redesign so M2a doesn't pre-judge #11).
- **Transitional numerical-tolerance magnitude:** set empirically from observed M2a drift (tight
  enough to catch dollar-level money bugs, loose enough for sub-cent/quantization drift).
- Exact `[[tool.mypy.overrides]]` module list and `make typecheck` invocation details.
- Per-base Protocol-vs-ABC edge calls within the D-07 policy if a base turns out to carry/omit
  shared behavior contrary to the table above.

### Golden-master / oracle handling this phase
- **D-15:** **Behavioral-exact + bounded transitional numerical tolerance.** The behavioral oracle
  (trade timing + sides + sequence) stays asserted **EXACTLY** throughout M2a. The run-path
  integration test's **numerical** assertion gets a **documented bounded tolerance** for the duration
  of M2a (permits expected Decimal-precision drift, still catches gross/dollar-level money bugs). The
  tolerance is **removed and the numerical oracle re-frozen EXACT at M2b** (Phase 3 SC4). This honors
  PROJECT.md's two-point exact-baseline rule; D-13's (M1) "no float tolerance" is the *end-state*,
  and this is an explicitly sanctioned transition window — NOT a third re-baseline point.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Authoritative analysis (source of truth — do NOT re-derive requirements)
- `.planning/REFACTOR-BRIEF.md` — program goal/scope, locked decisions (Decimal money, UUIDv7),
  golden-master discipline, definition-of-done
- `.planning/COVERAGE-INDEX.md` — all 105 items → milestone (the coverage contract); §E logs
  gap-discovery deltas (the doc-filename delta from M1 is logged here)
- `.planning/PROJECT.md` — milestone breakdown, Key Decisions table, constraints, two-point
  numerical-oracle re-baseline rule, Out-of-Scope tags (D-live/D-sql/D-screener/D-oanda)
- `.planning/REQUIREMENTS.md` — **M2-01…M2-05** (the locked WHAT for this phase)
- `.planning/ROADMAP.md` — Phase 2 goal + 4 success criteria; **Phase 3 SC2** (order/txn timestamp
  determinism boundary) + **Phase 3 SC4** (numerical-oracle re-freeze)

### Architecture findings driving this phase
- `.planning/codebase/ARCHITECTURE-REVIEW.md` **#10** (UUIDv7, Critical), **#17** (Decimal money),
  **#8** (typing: mypy-strict + frozen/slots DTOs + NewType), **#20** (dead ABC enforcement — the
  8 bases), **#5** (seed RNG + flat order index). Also **#11** (event schema — M3 boundary, do NOT
  pull forward), **#22** (CashManager bypass — M4 boundary), **#30** (price Provider/Store/Feed — M5).
- `.planning/codebase/CONCERNS.md` — **PERF2** (flat order index / unseeded RNG); DEF-01-A overlap
  with #22 (M4).

### Phase 1 carry-forward (constrains M2a)
- `.planning/phases/01-m1-ignition-lock-the-oracle/01-CONTEXT.md` — **D-12** (oracle excludes
  integer-ID values + wall-clock/audit timestamps → UUIDv7/clock are oracle-safe), **D-13**
  (behavioral-exact + numerical-exact, re-baselined only after M2 & M5), **D-09** (sizing seam in
  `OrderManager` — the money-path Decimal entry point), **D-07** (csv branch in `PriceHandler`).
- `.planning/phases/01-m1-ignition-lock-the-oracle/deferred-items.md` — **DEF-01-A** (commission
  Decimal→float coercion, reconcile at M4), **DEF-01-C** (no margin/liquidation, M5).

### Codebase maps
- `.planning/codebase/ARCHITECTURE.md`, `STRUCTURE.md`, `CONVENTIONS.md` (tabs vs spaces, naming,
  logging, error handling), `TESTING.md` (strictness: `filterwarnings=["error"]`, strict markers),
  `STACK.md`, `INTEGRATIONS.md`

### Golden dataset & oracle
- `data/BTCUSD_1d_ohlcv_2018_2026.csv` — THE golden dataset (Binance-klines; per M1 D-01)
- `test/golden/{trades,equity}.csv` + `summary.json` — the frozen M1 oracle (behavioral law;
  numerical baseline drifts this phase, re-frozen at M2b)

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `itrader/outils/id_generator.py` — the `IDGenerator` singleton + its ~7 call sites
  (`order.py:50`, `screeners/base.py:24`, `transaction.py:90`, `position.py:38`,
  `portfolio.py:44`, `portfolio_handler.py:269`, `strategy_handler/base.py:19`). Replace internals
  with `uuid_utils.uuid7()`; keep the facade to minimize call-site churn.
- `itrader/order_handler/storage/in_memory_storage.py` — already keys by `str(order_id)` with loose
  `Union[str, int]` typing; tighten to native `UUID` keys + add the flat `Dict[UUID, Order]` index.
- `itrader/core/exceptions/{base,portfolio}.py` — `entity_id: int`/`portfolio_id: int`/
  `transaction_id: int` signatures need retyping to the UUID aliases.
- Existing exception hierarchy + `ConfigProvider` (config seed source for the injected `Random`).
- `itrader/execution_handler/exchanges/simulated.py`, `slippage_model/{fixed,linear}_slippage_model.py`
  — the `random.*` sites to route behind the injected `Random`.

### Established Patterns
- Queue-only cross-domain communication; handler/manager split; `on_<event>` callbacks.
- **Tab indentation** in handler modules; **spaces** in `config/` and newer modules — match the file.
- `pyproject.toml` is the single source of truth for deps + test config + (new) mypy config.
- `uuid` is already partially present (`event.py:6` `from uuid import uuid4` for event-level concerns
  — that's M3's domain; `portfolio_handler.py:5 import uuid`).

### Integration Points
- `itrader/outils/id_generator.py` + the 7 call sites — UUIDv7 swap (D-12/D-13/D-14).
- The money path: `transaction.py`, `transaction_manager.py` (the `Decimal(str(...))` churn at
  `:246-255` then `float()` cast at `:229`), `portfolio.py` (`cash: float` at `:37`),
  `cash_manager.py` (`_reserved_cash: Decimal` at `:65`), `order_manager.py` sizing seam (D-09),
  execution fill construction — retype to `Decimal` end-to-end with quantization at boundaries
  (D-01…D-04). NB: the `portfolio.cash += float(...)` setter bypass is #22/**M4** — M2a types the
  fields Decimal; M4 routes cash through `CashManager`.
- The 8 ABC/Protocol bases: `execution_handler/exchanges/base.py`, `execution_handler/base.py`,
  `price_handler/base.py`, `strategy_handler/position_sizer/base.py`, `strategy_handler/base.py`,
  `reporting/base.py`, `universe/universe.py`, `screeners_handler/screeners/base.py` (D-07/D-08).
- Clock injection: `order.py` (many `datetime.now()` — but **audit-timestamp determinism is M2b**),
  `metrics_manager.py:131`, `backtest_trading_system.py:97,105` (perf-timing — stays wall-clock).
  `order_validator.py:287` already uses `signal.time.time()` (good pattern to mirror).
- `pyproject.toml` — add mypy config + `[[tool.mypy.overrides]]` excludes; `Makefile` — add
  `make typecheck` (D-05/D-06).
- `uuid-utils` dependency — add to `pyproject.toml`/`poetry.lock`.

</code_context>

<specifics>
## Specific Ideas

- User confirmed the **money/non-money split** explicitly: "Decimal end-to-end" means money is
  Decimal with no round-trips, while the **indicator/analytics path stays float** (TA libs require
  float; precision there is not contractual). This was a deliberate clarification, not an oversight.
- User favored **real per-instrument quantization** (instinct toward "option 2") but accepted the
  **hybrid** once the 28-digit *context precision* (significant figures) was distinguished from the
  *quantization scale* (decimal places) — they are two separate knobs.
- User explicitly **blessed the numerical oracle drifting** this phase (behavioral stays exact),
  consistent with the M2b re-freeze.
- User wanted the **idiomatic Python** choice on ABC vs Protocol (confirmed mixing both is standard
  in mature frameworks) and locked the per-#20 mix.

</specifics>

<deferred>
## Deferred Ideas

- **General per-cryptocurrency precision registry** (small-value tokens, e.g. 18-dp) — deferred;
  only BTCUSD is traded in this program. The D-02 policy is a default+override lookup, so it is
  trivially extensible later.
- **Order-audit & transaction-timestamp determinism** → **M2b (Phase 3) SC2**. M2a builds the
  injected clock mechanism; M2b applies it to make order/transaction timestamps event-derived.
- **`calculate_signal` contract enforcement** (richer than the bare abstract method) → **M5b #24**.
- **Universe collapse to a documented stub** → **M5b #33**. M2a only converts the `Universe` base
  to a real ABC + minimal conformance.
- **Reporting computation/presentation split + `print_summary` fix** → **M5b #38**. M2a only converts
  `AbstractStatistics` to a real ABC.
- **Screener wiring** → deferred **D-screener**. M2a converts the base (cheap, for SC3) but the
  module stays mypy-excluded and otherwise dormant.
- **Cash-through-`CashManager` (no `portfolio.cash += float(...)` bypass) + DEF-01-A commission
  reconciliation + atomic transactions** → **M4 (#22, #16, #23)**. M2a types money fields Decimal;
  M4 fixes the cash-flow routing.
- **Event immutability + `event_id` + linkage IDs + dispatch registry** → **M3 (#11, #1, #2)**.
  M2a touches only the six entity IDs and may freeze hot-path DTOs at discretion without pre-judging
  the M3 event schema (mind `SignalEvent.verified` mutation).
- **mypy --strict over deferred subsystems** (live/SQL/screener/OANDA) — excluded now; revisited only
  if a later milestone reworks them.

</deferred>

---

*Phase: 2-m2a-identity-money-determinism*
*Context gathered: 2026-06-04*

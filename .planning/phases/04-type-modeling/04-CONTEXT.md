# Phase 4: Type Modeling - Context

**Gathered:** 2026-06-11
**Status:** Ready for planning

<domain>
## Phase Boundary

Make closed string vocabularies into canonical `core/enums/` enums, freeze the engine's
decision/result DTOs into immutable facts, harden config-boundary validation, retype the
public-API ids onto the UUIDv7 `core/ids.py` NewTypes, and co-locate the strategy config base —
all **behavior-preserving**. Oracle byte-exact (134 trades / `final_equity 46189.87730727451`),
`mypy --strict` clean, 58/58 e2e green.

In scope (locked by ROADMAP §Phase 4 success criteria, REQUIREMENTS TYPE-01..05):
- **TYPE-01** [W2-03, W2-04, W2-12]: freeze `FillDecision`/`CancelDecision`,
  `OperationResult`/`SignalProcessingResult`, and `_PendingBracket` as
  `frozen=True, slots=True, kw_only=True` facts.
- **TYPE-02** [W2-08, W2-09, W2-11, DEF-02-03]: fee/slippage dispatch on enum members with
  `assert_never`; `rebalance_frequency` validated at the Pydantic boundary;
  `PortfolioConfig.portfolio_id` false affordance **removed**; public-API id annotations retyped
  to the `core/ids.py` NewTypes (scope widened — see D-12).
- **TYPE-03** [W2-07, W2-05, W2-06, SYN-05-enum]: `ErrorSeverity`, `OrderOperationType`,
  `OrderTriggerSource`, and `market_execution` become class-based `core/enums/` enums.
- **TYPE-04** [W2-01]: `OrderStatus`/`OrderCommand` converted to canonical class-based
  string-valued enums (⚠ BEHAVIOR-SENSITIVE int→string value change).
- **TYPE-05** [SYN-02]: `BaseStrategyConfig` relocated to `itrader/config/strategy.py`; concrete
  configs co-located into their strategy files.

Out of scope: any change that moves the oracle; building `OrderConfig` / threading it (999.5-(b));
`Order.action: str → Side` retype (W2-02 → 999.5-(a)); the `order_manager.py` god-module SPLIT
(Phase 6 — only the enum-carrier annotation swaps land here, not structural code-motion); other
cleanup-review batches; deferred/off-path subsystems (live `TradingInterface`, screeners).

</domain>

<decisions>
## Implementation Decisions

### Cross-cutting — verification & behavior-preservation
- **D-00 (milestone gate, inherited):** Every change is behavior-preserving — the SMA_MACD
  golden master re-runs **byte-exact** (134 trades / `final_equity 46189.87730727451`) and
  `pytest tests/e2e -m e2e` stays 58/58. `mypy --strict` clean across all source files. No new
  float-for-money; single UUIDv7 scheme. This phase re-baselines nothing.

### TYPE-04 — OrderStatus / OrderCommand canonical form (W2-01, ⚠ behavior-sensitive)
- **D-01:** Convert `OrderStatus` and `OrderCommand` from the functional `Enum("X", "...")`
  auto-int form to the **full house pattern**, matching `OrderType`/`FillStatus`:
  - Class-based with **explicit UPPERCASE string values equal to the member name**
    (`PENDING = "PENDING"`, `FILLED = "FILLED"`, `NEW = "NEW"`, `CANCEL = "CANCEL"`,
    `MODIFY = "MODIFY"`, etc.).
  - Add a **case-insensitive `_missing_`** classmethod (raise a clear f-string `ValueError` on
    unknown strings), exactly like `OrderType._missing_`.
  - **Retain** `order_status_map` / `order_command_map` (string → member). With string values,
    `.value` lookups become reachable (the finding's "unreachable" defect is closed).
  - `VALID_ORDER_TRANSITIONS` and all member references carry over unchanged (member identity is
    unaffected; only `.value` flips int → string).
- **D-02 (the load-bearing audit — done in discussion):** The int→string value change is
  **inert on the golden path** because order status serializes via `.name`, never `.value`:
  - `itrader/reporting/orders.py:91` → `"status": o.status.name` (writes `"PENDING"`).
  - `itrader/order_handler/order.py:133` → `f"{self.status.name}"`.
  - `.name` is invariant under this change (`"PENDING"` whether `.value` is `1` or `"PENDING"`).
  - No `status.value == <int>` assertions exist in the test suite (grep-confirmed).
  - Therefore golden CSV/summary output is byte-identical by construction; the oracle gate
    confirms it. The risk the ⚠ flag guards (a hidden int-`.value` consumer) is **absent**.
- **D-03 (verification — owner choice: lean tests):** Gate on grep-audit (D-02) + byte-exact
  oracle, **and add lean targeted unit tests on the enums themselves** where useful — assert the
  string values, the `_missing_` case-insensitive parse, the `*_map` round-trip, and the
  `.name`-serialization invariant. **Keep it lean** — no broad `SMA_MACD` strategy test (Phase 3
  D-02 owner constraint still applies to strategy modules).

### TYPE-03 — new enums in `core/enums/` (W2-07, W2-05, W2-06, SYN-05-enum)
- **D-04 (FRAGILE-zone gating — owner choice: full convert):** `OrderOperationType` (11-value,
  `operation_type`) and `OrderTriggerSource` (10-value, `OrderStateChange.triggered_by`) are
  defined in `core/enums/order.py` **and** all call-sites are converted **this phase** — including
  the 20+/8+ sites **inside `order_manager.py`** (the FRAGILE file Phase 6 splits).
  - **Hard constraint:** each enum member's `.value` MUST equal the **exact current string**
    (value-equal swap — e.g. `operation_type="create_market_order"` → an enum member whose
    `.value` is `"create_market_order"`). The carrier **type** changes; the **value** does not,
    so `OrderStateChange` audit records, logs, comparisons, and any string emission stay
    byte-identical.
  - **The reconciliation / reservation-release LOGIC is untouched** — this is a pure
    annotation + value-equal literal swap, NOT structural code-motion. The terminal-status /
    `should_release` / `finally`-release interplay must not change. Golden re-run mandatory.
  - **Payoff:** Phase 6 inherits a string-literal-free `order_manager.py` — a cleaner pure
    code-motion split with no vocabulary strings to chase.
- **D-05:** `ErrorSeverity` (W2-07) — class-based `core/enums/` enum replacing the
  `ErrorEvent.severity: str = "ERROR"  # ERROR, CRITICAL, WARNING` comment-as-enum; update
  `_log_error_event`'s string compare to enum members. (Claude's discretion on exact home/parse.)
- **D-06 (`market_execution` — SYN-05 split):** Convert the `"immediate"`/`"next_bar"` string to
  a class-based `core/enums/` enum (value-equal), coerced at the **`OrderManager` ctor boundary**.
  Per SYN-05 the **enum alone is cleanup-eligible now**; building an `OrderConfig` model and
  threading it through `TradingSystem` is **NEW CONTRACT WORK → deferred to 999.5-(b)** and is
  NOT in this phase. The ctor keeps taking the (now enum-coerced) param; no config model is added.

### TYPE-01 — freeze decision/result DTOs (W2-03, W2-04, W2-12) — mostly mechanical
- **D-07:** `FillDecision`/`CancelDecision` (`matching_engine.py`),
  `OperationResult`/`SignalProcessingResult` (`order_handler/operation_result.py`), and
  `_PendingBracket` (`order_manager.py`) become `frozen=True, slots=True, kw_only=True`. For
  `OperationResult`/`SignalProcessingResult`, prefer `tuple[OrderEvent, ...]` over the mutable
  `List` field per W2-04. Construction must remain kw-only-compatible; audit constructors/factory
  classmethods for positional calls and any in-place mutation of these objects (freezing surfaces
  them as errors — migrate the call, do not unfreeze). Oracle byte-exact.

### TYPE-02 — config-boundary hardening & id NewTypes (W2-08, W2-09, W2-11, DEF-02-03)
- **D-08:** Fee/slippage dispatch in `simulated.py::_init_*_model` compares **enum members**
  (`config.model_type is FeeModelType.X`) instead of `.value` strings, with `assert_never` on the
  exhaustive branch (mypy proves completeness). (W2-08.)
- **D-09:** `PortfolioConfig.rebalance_frequency` validated at the Pydantic boundary against its
  closed vocabulary (field unread on the backtest path — `auto_rebalance=False` — so oracle-dark;
  this hardens the boundary without changing run behavior). (W2-09.)
- **D-10 (W2-11 — owner choice: REMOVE):** Delete `PortfolioConfig.portfolio_id`
  (`config/portfolio.py:108`, `Optional[int]`) entirely — it is never read at construction (the
  entity always mints a fresh UUIDv7), a false affordance AND a stray int-typed id. **Verified in
  discussion:** no construction site passes `portfolio_id=` (grep of `itrader/`/`tests/`/`scripts/`
  found none; executor double-checks `tests/unit/portfolio/test_portfolio_handler.py:107`).
- **D-11 (the W2-11 decision is also part of D-12's "no int ids" goal).**

### TYPE-02 (cont.) — eliminate non-NewType id annotations (DEF-02-03, owner-widened)
- **D-12 (owner directive — "no `int` type for any id"; scope widened beyond TYPE-02 literal):**
  Retype **every entity-id annotation — `int` AND `Any` — across the backtest run-path order +
  portfolio + events domains** to its `core/ids.py` NewType. Annotation-only, runtime-identical
  (the values are already UUIDs at runtime), `mypy --strict` is the gate. Concretely:
  - `order_manager.py` / `order_handler.py` public methods: `order_id: int → OrderId`,
    `portfolio_id: Optional[int]|Optional[Any] → Optional[PortfolioId]` (`modify_order`,
    `cancel_order`, `get_order_by_id`, `get_order_history`, `get_orders_by_status`,
    `get_active_orders`, `get_orders_by_ticker`, `search_orders`, `get_orders_summary`).
  - `order_handler/order.py:199,232` factory params: `strategy_id: Any → StrategyId`,
    `portfolio_id: Any → PortfolioId`.
  - `portfolio_handler.py`: `get_portfolio`/`delete_portfolio`/`update_portfolio_config`/
    `get_portfolio_config` `portfolio_id: Any → PortfolioId`.
  - `events/error.py:78`: `portfolio_id: Any | None → PortfolioId | None`.
  - `portfolio_handler/validators.py:83`: `transaction_id: Optional[int] → Optional[TransactionId]`.
  - **`config/portfolio.py:108` portfolio_id** — removed entirely (D-10), not retyped.
- **D-13 (carve-outs — NOT retyped):**
  - **`user_id: int` stays `int`** (`portfolio.py:46`, `portfolio_handler.py:123`,
    `validators.py:56`) — a user account id is a genuine integer; there is no `UserId` in
    `core/ids.py` and inventing one would be a new id scheme (forbidden).
  - **Deferred / off-path subsystems untouched** — `trading_system/trading_interface.py` (live
    path, `strategy_id/portfolio_id: int = 0`) and `screeners_handler/screeners/base.py`
    (`strategy_id: int`) are under `[[tool.mypy.overrides]] ignore_errors`, off the backtest path,
    and PROJECT.md-deferred. Owner noted the live/strategy wiring is refactored next milestone
    anyway. No scope creep into deferred code.

### TYPE-05 — BaseStrategyConfig relocation (SYN-02, owner choice)
- **D-14 (placement — owner choice):** Move the **base contract only** —
  `BaseStrategyConfig` → `itrader/config/strategy.py`, re-exported via `config/__init__.py`
  (consistent with `ExchangeConfig`/`PortfolioConfig`/`SystemConfig`). Move the **concrete**
  configs **into their respective strategy files**:
  - `SMA_MACDConfig` → `itrader/strategy_handler/strategies/SMA_MACD_strategy.py`
  - `EmptyStrategyConfig` → `itrader/strategy_handler/strategies/empty_strategy.py`
  - `itrader/strategy_handler/config.py` is **emptied / removed**.
  Each concrete config subclasses `BaseStrategyConfig` imported from `config/`. Pure code-motion +
  import updates, oracle-dark. (`config/` already imports `core/` legally, so the
  `core.sizing`/`core.enums` imports carry over unchanged.)
  - **Owner note:** the strategy-setting system gets refactored next milestone — do NOT
    over-engineer placement now; this is minimal co-location, not a config-system redesign.
- **D-15 (⚠ INDENTATION HAZARD — must flag to executor):** the destination strategy files
  (`strategies/SMA_MACD_strategy.py`, `strategies/empty_strategy.py`) are **TAB-indented**
  (grep-confirmed), but the pydantic config classes are written in the **4-space** config house
  style. The moved config class MUST be **re-indented to tabs** to match its destination file — a
  mixed-indentation diff breaks a tab file. (`config/strategy.py` itself is a 4-space module.)
- **D-16 (import-churn list — verified in discussion):** importers of the old
  `strategy_handler.config` that need updating: `strategy_handler/base.py:12`,
  `strategy_handler/signal_record.py:35`, the two strategy files, plus
  `tests/unit/strategy/test_strategy_config.py`, `test_strategy.py`, `test_signal_store.py`,
  `tests/integration/test_universe_spans.py`, `test_backtest_oracle.py:255`,
  `test_backtest_smoke.py`, `test_reservation_inertness.py`, `tests/e2e/strategies/
  single_market_buy.py`, `scripted_emitter.py`, and `scripts/run_backtest.py:48`. The base-config
  import resolves to `itrader.config.strategy` (or `itrader.config`); the concrete-config imports
  (`SMA_MACDConfig`/`EmptyStrategyConfig`) resolve to the strategy modules that now hold them.

### Claude's Discretion
- Plan/wave decomposition across TYPE-01..05 (likely: SAFE enum/freeze batch → ⚠ W2-01
  string-value batch → relocation batch, mirroring the cleanup-review Batch 5/6 split).
- Exact `_missing_` bodies, enum member ordering, and `<domain>_<type>_map` shapes for the new
  enums (follow the `OrderType`/`FillStatus` house pattern).
- Exact placement/naming of the lean enum unit tests (D-03).
- Whether `OperationResult`/`SignalProcessingResult` order-event fields become
  `tuple[OrderEvent, ...]` vs frozen-list (W2-04 suggests tuple; pick the byte-exact-safe form).
- Extent of touched-path opportunistic cleanup (Phase-1 D-05 / `CLEANUP-STANDARD.md`).
- Exact wording/home of the D-02 audit note and the D-06 SYN-05-split rationale.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase scope & requirements
- `.planning/ROADMAP.md` §Phase 4 — goal + 5 success criteria.
- `.planning/REQUIREMENTS.md` TYPE-01..05 (lines ~62-80) — the five requirements with source
  cleanup-review finding tags.

### Source findings (cleanup-review rationale + payoff/risk ratings)
- `.planning/codebase/V1.2-CLEANUP-REVIEW.md` — rows: **2** (W2-01 ⚠ class-based
  OrderStatus/OrderCommand), **11** (W2-03 freeze FillDecision/CancelDecision), **12** (W2-04
  freeze OperationResult), **13** (W2-05 OrderOperationType), **14** (W2-06 OrderTriggerSource),
  **15** (W2-07 ErrorSeverity), **16** (W2-08 enum-member dispatch), **29** (W2-12 _PendingBracket
  slots), **30** (W2-09 rebalance_frequency), **31** (W2-11 portfolio_id false affordance), **38**
  (W2-13 config-enum exception — documented in Phase 1, context only); §6 **Batch 5** + **Batch 6**
  (lines ~199-207; Batch 6 ⚠ W2-01 oracle-re-run gating); §7 Addendum rows **49** (SYN-02
  BaseStrategyConfig), **52** (SYN-05 — the market_execution-enum-vs-OrderConfig split).
- **Deferred (do NOT execute here — record only):** W2-02 `Order.action: Side` → 999.5-(a);
  OrderConfig threading → 999.5-(b). (Cleanup-review §6 "Deferred to 999.5".)

### Locked decisions & conventions
- `CLAUDE.md` §"Determinism & money" / §"IDs & Determinism" — single UUIDv7 scheme; the basis for
  D-12's "no int ids".
- `.planning/codebase/CONVENTIONS.md` — the four documented conventions incl. the tab/space
  indentation hazard (D-15) and the config-enum-in-`config/` exception (W2-13, Phase 1).
- `.planning/codebase/CLEANUP-STANDARD.md` — touched-path opportunistic-cleanup standard.
- `.planning/phases/02-locked-decision-conformance/02-CONTEXT.md` §D-12 — the nine→ten NewType
  pattern in `core/ids.py` that D-12 retypes onto; §D-07 — the bounded gap-discovery-delta
  precedent.
- `.planning/phases/03-hot-path-performance/03-CONTEXT.md` §D-01/D-02 — the verification-rigor
  precedent (behavioral-assert vs oracle-only) that D-03 follows; D-02's "no new SMA_MACD strategy
  test" owner constraint carries forward.

### Code targets (verified during scout)
- `itrader/core/enums/order.py:33,64` — `OrderStatus`/`OrderCommand` functional form + the maps +
  `VALID_ORDER_TRANSITIONS` (D-01); home for `OrderOperationType`/`OrderTriggerSource` (D-04).
- `itrader/core/enums/order.py:11-31` — `OrderType` (the `_missing_` house-pattern template).
- `itrader/core/ids.py:18-27` — the ten NewType aliases (D-12 retype target).
- `itrader/order_handler/operation_result.py:13,56` — `OperationResult`/`SignalProcessingResult`
  (D-07 freeze).
- `itrader/execution_handler/matching_engine.py:60,75` — `FillDecision`/`CancelDecision` (D-07).
- `itrader/order_handler/order_manager.py:34` — `_PendingBracket` slots (D-07); `:70,105`
  `market_execution` ctor param (D-06); 20+ `operation_type` + 8+ `triggered_by` sites (D-04);
  `:1089,1177,1255,1267` public-API id params (D-12).
- `itrader/order_handler/order_handler.py:40,121,158,222,274` + the `get_orders_*` block —
  `market_execution` (D-06) + public-API id params (D-12).
- `itrader/order_handler/order.py:23-24,27 (OrderStateChange.triggered_by),199,232` — triggered_by
  (D-04) + factory id params (D-12).
- `itrader/events_handler/events/error.py:52 (severity),78 (portfolio_id)` — D-05 + D-12.
- `itrader/execution_handler/exchanges/simulated.py:493-533` — fee/slippage dispatch (D-08).
- `itrader/config/portfolio.py:108 (portfolio_id),124 (rebalance_frequency)` — D-10 + D-09.
- `itrader/portfolio_handler/portfolio_handler.py:167,173,495,507` + `validators.py:83` — D-12.
- `itrader/reporting/orders.py:91`, `itrader/order_handler/order.py:133` — the `.name`
  serialization that makes W2-01 inert (D-02).
- `itrader/strategy_handler/config.py` — `BaseStrategyConfig`/`SMA_MACDConfig`/
  `EmptyStrategyConfig` (D-14 source); `itrader/config/__init__.py` (re-export target);
  `strategies/SMA_MACD_strategy.py` / `empty_strategy.py` (TAB modules — D-14 dest + D-15 hazard).

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- **`OrderType` / `FillStatus` house pattern** (`core/enums/`) — class-based, explicit UPPERCASE
  string values, case-insensitive `_missing_` raising an f-string `ValueError`. The exact template
  for D-01 (OrderStatus/OrderCommand) and the four new D-03/D-04/D-05/D-06 enums.
- **`core/ids.py` ten NewType aliases** — `OrderId`/`PortfolioId`/`StrategyId`/`TransactionId`
  already exist; D-12 is pure annotation reuse, no new types minted.
- **Phase-2 D-07 gap-discovery-delta mechanism** + **Phase-3 D-01/D-02 verification rigor** — the
  established owner-flagged patterns D-02/D-03 reuse.

### Established Patterns
- **`.name`-based serialization** (`reporting/orders.py`, `order.py.__str__`) — the load-bearing
  invariant that makes the W2-01 int→string value change byte-inert; do NOT switch any serializer
  to `.value`.
- **Indentation hazard:** `order_handler/`, `execution_handler/`, `portfolio_handler/`,
  `strategy_handler/` (incl. `strategies/`) are **TAB** modules; `core/`, `config/` (incl. the new
  `config/strategy.py`), and `events_handler/events/` are **4-space**. Match each file. D-15 is the
  acute case (moving a 4-space config class into a tab strategy file).
- **mypy `--strict` as the id-type gate** — D-12 is verified entirely by mypy (NewType nominal
  distinctness), no runtime change.

### Integration Points
- **W2-01 value change** touches order-status identity used in `VALID_ORDER_TRANSITIONS`, order
  lifecycle (`order.py`), reconciliation (`order_manager.on_fill`), and reporting — all via member
  identity / `.name`, none via `.value`; keep it that way.
- **D-04 enum swap** sits ON the FRAGILE reconciliation/reservation-release path (operation_type /
  triggered_by are recorded there) — value-equal swap only, logic frozen, golden re-run mandatory.
- **D-14 relocation** touches the strategy-config import graph: `base.py`, `signal_record.py`, two
  strategy files, 9 test files, 1 script (D-16 list).

</code_context>

<specifics>
## Specific Ideas

- **Owner stance — "no `int` type for any id" (D-12):** the strongest signal of this discussion.
  It widened TYPE-02 beyond its literal OrderHandler/OrderManager scope to *every* entity-id
  annotation on the run path (int AND Any → NewType), while explicitly carving out the legitimate
  `user_id: int` and the deferred off-path subsystems. The principle: ids are nominally typed
  UUIDv7 NewTypes everywhere they actually flow; `int`/`Any` on an entity id is a defect.
- **Verification philosophy carried from Phase 3:** byte-exact oracle proves correctness; lean
  targeted enum unit tests prove the canonical-form change landed (D-03). No broad strategy test.
- **The W2-01 ⚠ flag is mostly a false alarm here** — the `.name` serialization audit (D-02) is
  the load-bearing finding that downgrades it from "behavior-sensitive" to "byte-inert, oracle-
  confirmed". Treat the audit, not the conversion, as the important output.

</specifics>

<deferred>
## Deferred Ideas

- **W2-02 — `Order.action: str → Side` / `_PendingBracket.action: str → Side`** (→ 999.5-(a),
  FRAGILE bracket/reconcile path). NOT in this phase; coordinate with the signal-contract work.
- **`OrderConfig` domain model + construction-time threading** (SYN-05 config arm → 999.5-(b)).
  Only the `market_execution` enum lands now (D-06); the config model that would naturally own it
  is new contract work.
- **Strategy-setting-system refactor** (owner-noted, next milestone) — the reason D-14 stays
  minimal co-location rather than a config-system redesign.
- **Deferred/off-path id retyping** — `trading_interface.py` and `screeners/base.py` int-typed ids
  (D-13 carve-out); revisit when the live/screener subsystems are de-deferred.

</deferred>

---

*Phase: 4-Type Modeling*
*Context gathered: 2026-06-11*

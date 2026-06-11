# Phase 4: Type Modeling - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-06-11
**Phase:** 4-Type Modeling
**Areas discussed:** OrderStatus/Command form, FRAGILE enum sites, StrategyConfig move, NewType retyping

---

## OrderStatus/OrderCommand canonical form (W2-01)

### Q1 — How far to take the conversion?

| Option | Description | Selected |
|--------|-------------|----------|
| Full house pattern | Class-based, UPPERCASE string values = member name, case-insensitive `_missing_`, keep `order_status_map`/`order_command_map`. Fully consistent with OrderType/FillStatus; `.value` lookups become reachable. | ✓ |
| Class-based, no `_missing_` | Convert to class-based string values but skip the parser. Leaner, inconsistent with house pattern. | |
| You decide | Match surrounding enums. | |

**User's choice:** Full house pattern

### Q2 — Verification approach for the ⚠ int→string value change

| Option | Description | Selected |
|--------|-------------|----------|
| Audit + oracle + .name assert | Grep-audit + oracle gate + one regression assert pinning `.name` serialization. | |
| Audit + oracle only | Grep-audit + oracle gate, no new test (Phase 3 D-02 style). | |
| You decide | — | |

**User's choice (clarified):** Add lean unit tests on the enum itself where useful, but keep it lean.
**Notes:** User first asked "what's the problem here?" — clarified that W2-01 is flagged
behavior-sensitive only because *if* anything consumed the integer `.value` it would break;
the scout proved the golden path serializes via `.name` (invariant) with no int-value
assertions, so the change is byte-inert and oracle-confirmed. User opted for lean targeted
enum unit tests over either extreme.

---

## FRAGILE enum sites (W2-05 / W2-06)

| Option | Description | Selected |
|--------|-------------|----------|
| Full convert, oracle-gated | Define both enums AND convert all 20+/8+ order_manager.py sites this phase; pure value-equal type swap, reconciliation logic untouched; leaves Phase 6 a clean string-literal-free split. | ✓ |
| Define enums, defer FRAGILE sites | Add enums + convert SAFE boundary sites only; leave in-FRAGILE-zone order_manager.py sites as strings until Phase 6. | |
| You decide | — | |

**User's choice:** Full convert, oracle-gated
**Notes:** Hard constraint captured — enum `.value` must equal the exact current strings so
audit records/logs/comparisons stay byte-identical; only the carrier type changes, the
reconciliation/reservation-release logic is frozen.

---

## StrategyConfig relocation (TYPE-05 / SYN-02)

| Option | Description | Selected |
|--------|-------------|----------|
| Base only; concretes stay | Move only BaseStrategyConfig to config/strategy.py; concrete configs stay co-located with strategies. | ✓ (modified) |
| Move everything | Move base + concrete configs to config/strategy.py. | |
| You decide | — | |

**User's choice:** Base only — AND move the concrete `SMA_MACDConfig`/`EmptyStrategyConfig`
into their respective strategy definition files under `strategies/`.
**Notes:** User: "i'll refactor the strategy setting system in the next milestone anyway" —
so keep this minimal co-location, not a config-system redesign. `strategy_handler/config.py`
is emptied/removed. ⚠ Indentation hazard surfaced: strategy files are tab-indented, the
pydantic configs are 4-space — the moved class must be re-indented to tabs.

---

## NewType retyping + PortfolioConfig.portfolio_id (TYPE-02 / W2-11)

### Q1 — Scope of eliminating non-NewType id annotations

| Option | Description | Selected |
|--------|-------------|----------|
| Whole run path | Retype all entity-id annotations (int AND Any) across order + portfolio + events run-path domains to NewTypes; user_id stays int; deferred subsystems untouched. | ✓ |
| Run path + deferred too | Above plus trading_interface.py and screeners/base.py. | |
| TYPE-02 literal only | Just OrderHandler/OrderManager public order_id/portfolio_id params. | |

**User's choice:** Whole run path
**Notes:** User stated "i do not want any type int for all ids." Clarified that the original
option 1 was narrower than this ask; presented the full int/Any id inventory. Agreed to widen
to all run-path entity ids (int AND Any → NewType), carve out the legitimate `user_id: int`
(no UserId scheme exists) and the deferred off-path live/screener subsystems.

### Q2 — PortfolioConfig.portfolio_id: remove or document?

| Option | Description | Selected |
|--------|-------------|----------|
| Remove the field | Delete it — never read, kills false affordance + stray int-id. Grep construction sites first. | ✓ |
| Document it | Keep but mark as ignored/reserved. | |
| You decide | — | |

**User's choice:** Remove the field
**Notes:** Verified in discussion — no construction site passes `portfolio_id=` to
PortfolioConfig (grep of itrader/tests/scripts found none).

---

## Claude's Discretion

- TYPE-01 freezing of `FillDecision`/`CancelDecision`/`OperationResult`/`SignalProcessingResult`/
  `_PendingBracket` (mechanical; tuple-vs-frozen-list field choice per W2-04).
- TYPE-03 `ErrorSeverity` enum (W2-07); `assert_never` fee/slippage dispatch (W2-08);
  `rebalance_frequency` Pydantic validation (W2-09).
- `market_execution` enum landing at the ctor boundary without building OrderConfig (SYN-05 split;
  OrderConfig threading deferred to 999.5-(b)) — user may redirect to leave it as a string.
- Plan/wave decomposition; exact `_missing_`/map shapes; lean enum-test placement; touched-path
  opportunistic cleanup extent.

## Deferred Ideas

- W2-02 `Order.action: str → Side` retype → 999.5-(a).
- `OrderConfig` model + construction-time threading → 999.5-(b) (only the `market_execution`
  enum lands now).
- Strategy-setting-system refactor → next milestone (owner-noted).
- Deferred/off-path id retyping (live `TradingInterface`, screeners) → when those subsystems are
  de-deferred.

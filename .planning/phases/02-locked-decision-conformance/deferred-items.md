# Phase 02 — Deferred / Out-of-Scope Items

Out-of-scope discoveries logged during plan execution (per the SCOPE BOUNDARY rule:
only auto-fix issues DIRECTLY caused by the current plan's changes).

## DEF-02-01 — stale `test_correlation_id_generation` assertion (owned by plan 02-03)

- **Discovered during:** plan 02-01 Task 3 (full-suite roll-up verification).
- **Test:** `tests/unit/portfolio/test_portfolio_handler.py::test_correlation_id_generation` (line ~433).
- **Symptom:** `AttributeError: 'UUID' object has no attribute 'startswith'` — the test asserts
  `id1.startswith("ph_")`, but `PortfolioHandler._generate_correlation_id()` now returns a
  `CorrelationId(UUID)` from `idgen.generate_correlation_id()`.
- **Root cause / owner:** commit `eacc0a0` "feat(02-03): mint correlation id from idgen, retype
  event field, drop dead uuid import" (plan **02-03**, DEC-03 — single UUIDv7 scheme). The impl
  was retyped from `f"ph_{uuid.uuid4().hex[:12]}"` to the idgen UUID, but this assertion was not
  updated.
- **NOT plan 02-01's domain:** plan 02-01 (DEC-01) touched only `order_handler.py`,
  `order_manager.py`, and `tests/unit/order/test_order_manager.py` — none in the
  portfolio/ids/events surface. Left untouched per the scope boundary; plan 02-03's own
  verification owns this fix.
- **Status:** RESOLVED (2026-06-11) by plan 02-03 commit `57ad3df` "test(02-03): assert
  correlation id is a uuid.UUID instead of ph_ prefix" — the assertion at
  `test_portfolio_handler.py:433` was swapped from `.startswith("ph_")` to
  `isinstance(id1, uuid.UUID)`. Test passes; full suite 811 green at phase close. No action
  required.

## DEF-02-02 — residual Decimal/float serialization inconsistency in exchange diagnostic dicts

- **Discovered during:** `/gsd:code-review 02 --fix --auto` iteration-2 re-review (Info finding IN-01).
- **Files:** `itrader/execution_handler/exchanges/simulated.py:480` (`get_exchange_info()['statistics']['total_volume']` emits raw `Decimal`) and `:627-632` (`get_config_dict()` `fee_rate`/`maker_rate`/`taker_rate`/`base_slippage_pct` emit raw `Decimal`).
- **Symptom:** After the IN-01/IN-02 fix (`fd688cf`) normalized `get_exchange_info()['limits']` to `float()` at the serialization edge, sibling fields in the same diagnostic dicts still emit raw `Decimal` — a serialization-type inconsistency.
- **Why deferred (NOT fixed in Phase 2):** Cosmetic/latent only. `get_config_dict` is consumed solely by `portfolio.to_dict` (diagnostic/reporting), with no production consumer that breaks on `Decimal`. Not a correctness/determinism/money-policy/oracle issue. Fixing it now is out of DEC-01/02/03 scope and unnecessary for phase goal.
- **Status:** Open — opportunistic cleanup. No dedicated requirement; fold into any future touch of the exchange serialization helpers, or sweep alongside Phase 3 hot-path work if `simulated.py` is already open. Low priority.

## DEF-02-03 — stale `order_id: int` / `portfolio_id: int` public-API annotations vs. single-UUIDv7 scheme

- **Discovered during:** `/gsd:code-review 02 --fix --auto` iteration-2 re-review (Info finding IN-02).
- **Files:** `itrader/order_handler/order_handler.py:121,131,158,167,222,228,240,274,290,308,326` and `itrader/order_handler/order_manager.py:1087,1094,1100,1175,1182`.
- **Symptom:** The order public API still annotates `order_id: int` / `portfolio_id: int`, but UUIDs flow through these methods at runtime (e.g. `tests/e2e/conftest.py:267-273` calls `cancel_order(order.id, portfolio_id)` with UUIDs). The annotations contradict the locked single-UUIDv7 scheme (DEC-03); the mismatch is silent because the params are unused-as-int.
- **Why deferred (NOT fixed in Phase 2):** Out of Phase 2 scope. DEC-01 covered only the **money** params of `modify_order`/`cancel_order` (`Optional[Decimal]`); the **id** params are a separate, broader retype across ~16 call sites that belongs to the **Type Modeling** milestone (Phase 4). Pulling it forward would be scope creep into a later phase and widen the behavior-preserving blast radius.
- **Cross-ref accuracy note:** This is **adjacent to but NOT covered by** the existing **TYPE-01** (Phase 4), which as currently written names only `PortfolioConfig.portfolio_id` (W2-08) — i.e. the *config* affordance, not the `OrderHandler`/`OrderManager` *method-parameter* annotations. To actually close DEF-02-03, TYPE-01 should be **extended** (or a new Phase-4 sub-item added) to name the order-API `order_id`/`portfolio_id` parameter retype to `OrderId`/`PortfolioId`. Suggested target type: the existing `OrderId`/`PortfolioId` NewType aliases in `core/ids.py`.
- **Status:** Open — proposed for **Phase 4 (Type Modeling)**; requires an explicit TYPE-01 scope extension or new sub-requirement (it is not implicitly in scope today).

---
phase: 02-m2a-identity-money-determinism
plan: 03
subsystem: identity-storage-exceptions
tags: [uuidv7, identity, storage, exceptions, mypy-strict, determinism]
requires:
  - "02-01: uuid-utils installed + mypy --strict gate"
  - "02-02: core/ids.py NewType aliases (OrderId/PortfolioId/TransactionId/...)"
provides:
  - "idgen.generate_*_id() returns stdlib uuid.UUID (UUIDv7) — single id scheme"
  - "InMemoryOrderStorage native-UUID keyed + flat Dict[uuid.UUID, Order] index (PERF2)"
  - "core exceptions typed to uuid.UUID / PortfolioId / TransactionId; mypy --strict Optional fixes"
affects:
  - "Plan 04 (entity-typing): entities now receive UUID ids from idgen at runtime"
  - "portfolio_handler.on_fill id handling (no int coercion)"
tech-stack:
  added: []
  patterns:
    - "uuid_utils.compat.uuid7() (NOT top-level uuid_utils.uuid7) — returns native uuid.UUID"
    - "flat global order index alongside retained nested per-portfolio dicts (D-14)"
key-files:
  created: []
  modified:
    - itrader/outils/id_generator.py
    - itrader/order_handler/storage/in_memory_storage.py
    - itrader/core/exceptions/base.py
    - itrader/core/exceptions/portfolio.py
    - itrader/portfolio_handler/portfolio_handler.py
    - test/test_order_handler/test_order_storage.py
    - test/test_order_handler/test_on_signal.py
    - test/test_portfolio_handler/test_portfolio_handler.py
    - test/test_positions/test_open_position.py
    - test/test_positions/test_multiple_buy.py
    - test/test_positions/test_multiple_sell.py
decisions:
  - "D-12/D-13/D-14: single UUIDv7 scheme; type no longer encoded in the id value; native uuid.UUID storage keys"
  - "portfolio_handler.py int(portfolio_id) coercion removed as a Rule 1/3 deviation (file unowned by any phase-02 plan; fix required to keep the suite green after the UUID migration)"
metrics:
  duration_min: 13
  completed: "2026-06-04"
  tasks: 3
  files: 11
  commits: 4
---

# Phase 2 Plan 03: Identity Infrastructure → UUIDv7 Summary

Migrated the identity infrastructure to a single UUIDv7 scheme: the `IDGenerator`
facade now returns stdlib `uuid.UUID` values via `uuid_utils.compat.uuid7()` (the
overflow-prone integer type-prefix+timestamp+counter scheme is fully deleted),
`InMemoryOrderStorage` keys natively by `uuid.UUID` with a new flat
`Dict[uuid.UUID, Order]` index for O(1) cross-portfolio lookup, and the core
exceptions are retyped to the `uuid.UUID` / `PortfolioId` / `TransactionId`
aliases with `mypy --strict` Optional-default fixes.

## What Was Built

### Task 1 — UUIDv7 idgen facade (D-12/D-13/D-14) — `572c4a4`
- Deleted the integer body of `IDGenerator`: per-type counters, `threading.Lock`,
  `_last_timestamp` cache, `_generate_unique_id`, and the `type_prefix * 10**19 + …`
  formula (the only `10**19` site in the tree — D-13 verified no decode site).
- All six `generate_*_id` methods now `return self._uuid7()` where
  `_uuid7()` calls `uuid_utils.compat.uuid7()` — the **compat** module that returns
  a native `uuid.UUID` (Pitfall 1: top-level `uuid_utils.uuid7()` returns the custom
  `uuid_utils.UUID` and would break D-14).
- Method names and the `itrader/__init__.py` singleton contract are unchanged, so the
  ~7 call sites stay byte-identical.
- Wave 0 scaffold `test/test_outils/test_id_generator.py` (3 tests: stdlib-UUID type,
  uniqueness, time-ordering) now green.

### Task 2 — Native UUID keying + flat order index (D-14, PERF2) — `115f897`
- `InMemoryOrderStorage` nested dicts now key by native `order.id`/`order.portfolio_id`
  (dropped every `str(...)` coercion); typed `Dict[uuid.UUID, Dict[uuid.UUID, Order]]`.
- Added `self._by_id: Dict[uuid.UUID, "Order"]` flat global index; populated in
  `add_order`/`update_order`, read in `get_order_by_id` (replaces the O(n)
  cross-portfolio scan), pruned in `remove_order`/`_remove_order_search_all`/`archive_orders`.
- Retyped all ~14 `Union[str, int]` params to `uuid.UUID` / `Optional[uuid.UUID]`
  (the `Union` import is now gone). Nested dicts retained for portfolio-scoped queries;
  the deeper nested-scan elimination remains M4-06 (PERF3), not pulled forward.
- Storage tests updated to native UUID ids/keys; added
  `test_get_order_by_id_uses_flat_index`.

### Task 3 — Exception signatures → UUID/NewType (M2-03) — `0c4a4de`
- `core/exceptions/base.py`: `entity_id: int` → `uuid.UUID`
  (`StateError`) / `Optional[uuid.UUID]` (`ConcurrencyError`, `NotFoundError`); fixed
  non-Optional `= None` defaults (`ValidationError`, `ConfigurationError`, plus the
  retyped params) to `Optional[...] = None` for `mypy --strict`.
- `core/exceptions/portfolio.py`: `portfolio_id: int` → `PortfolioId`,
  `transaction_id: int` → `Optional[TransactionId]`, plus the same Optional-default
  fixes; imports the aliases from `itrader.core.ids`. Type-only — messages and raise
  sites unchanged.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1/Rule 3 — Bug/Blocking] Integer-id coercion broke after the UUIDv7 migration — `e0244d8`**
- **Found during:** post-Task-1 full-suite run (the plan's Task 3 verification expected
  `test_portfolio_handler` to "stay green — no behavioral change", but Task 1's UUID
  change turned 11 portfolio tests and 6 position tests red).
- **Root cause:** `itrader/portfolio_handler/portfolio_handler.py` `on_fill` did
  `int(fill_event.portfolio_id)` (lines 241, 286). With ids now native `uuid.UUID`,
  `int(uuid)` either raised `ValueError` (string-id fills) or produced a giant int that
  no longer matched the UUID-keyed `_portfolios` dict → spurious `PortfolioNotFoundError`.
  Numerous tests also hard-asserted `isinstance(id, int)` / `assertGreater(id, 0)`.
- **Fix:** removed the `int()` coercion (the `_portfolios` dict is already keyed directly
  by `portfolio.portfolio_id`); the `on_fill` error path now passes the id as-supplied via
  `getattr(fill_event, "portfolio_id", None)`. Updated portfolio/position test assertions
  to `uuid.UUID`, to pass native-UUID `portfolio_id` on fills, and to expect the
  error-event id as-supplied (no int coercion).
- **Scope note:** `portfolio_handler.py` is **not** in any phase-02 plan's `files_modified`
  (Plan 04 owns `portfolio.py` the entity, not the handler). This fix is the minimal
  change needed to keep the suite green after the in-scope UUID migration; it does not
  touch entity-field typing (Plan 04's domain). No architectural change (Rule 4 not
  triggered) — pure removal of dead integer-scheme coercion.
- **Files modified:** `itrader/portfolio_handler/portfolio_handler.py`,
  `test/test_portfolio_handler/test_portfolio_handler.py`,
  `test/test_positions/{test_open_position,test_multiple_buy,test_multiple_sell}.py`
- **Commit:** `e0244d8`

**2. [Rule 1 — Bug] `test_on_signal.py` string-key portfolio lookup — folded into `115f897`**
- **Found during:** Task 2 full order-handler run.
- **Issue:** `pending_orders.get(str(primary_event.portfolio_id), {})` used a string key
  against the now native-UUID-keyed storage → empty result (`0 != 3`).
- **Fix:** use the native UUID key `pending_orders.get(primary_event.portfolio_id, {})`.

## Verification

- `test/test_outils/test_id_generator.py test/test_order_handler/test_order_storage.py` — 20 passed
- `test/test_portfolio_handler` — 120 passed
- `itrader/outils/id_generator.py` contains `uuid_utils.compat`, no `10**19`
- `in_memory_storage.py` has `self._by_id: Dict[uuid.UUID, "Order"]`; no `Union[str, int]` remains
- **Full suite: 288 passed** (incl. `test_integration/test_backtest_oracle.py` green —
  the UUIDv7 migration is behavior-preserving against the M1 golden-master oracle; ids are
  excluded from the committed oracle per D-12).

## Known Stubs

None — no placeholder/empty-value stubs introduced.

## Threat Flags

None — internal identity/storage-keying refactor; no new trust boundary or untrusted-input
deserialization (UUIDs are generated, not parsed from external input on the engine path).
Matches the plan `<threat_model>` (T-02-03 / T-02-03b both `accept`).

## Follow-ups for Later Plans

- **Plan 04 (entity-typing):** retype entity `id`/`*_id` fields (`order.py`,
  `transaction.py`, `position.py`, `portfolio.py`) to `uuid.UUID` / NewType aliases and
  money fields to `Decimal`. The entities already receive UUID ids from `idgen` at runtime
  after this plan; Plan 04 makes the field annotations match.
- **Plan 04 / residual typing (Plan 07):** the `portfolio_handler.py` id-handling now uses
  native UUIDs; if a later plan formally types the handler's `portfolio_id` params, the
  `Dict[int, Portfolio]` annotation on `_portfolios` should move to `Dict[uuid.UUID, Portfolio]`
  (left as-is here to stay within this plan's file scope).
- **M4-06 (PERF3):** full nested-scan elimination in `InMemoryOrderStorage` — the flat
  index added here is the foundation; the nested dicts are intentionally retained for now.

## Self-Check: PASSED

- SUMMARY.md created at `.planning/phases/02-m2a-identity-money-determinism/02-03-SUMMARY.md`
- All four commits present in git history: `572c4a4`, `115f897`, `0c4a4de`, `e0244d8`
- Full suite 288 green; plan acceptance/verification criteria confirmed.

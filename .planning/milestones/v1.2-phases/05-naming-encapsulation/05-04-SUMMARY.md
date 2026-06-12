---
phase: 05-naming-encapsulation
plan: 04
subsystem: tests
tags: [naming, encapsulation, test-hygiene, public-api, D-09, golden-master, behavior-preserving]

# Dependency graph
requires:
  - phase: 05-naming-encapsulation
    provides: "05-01 count_orders_by_status; 05-02 EventHandler.routes + SimulatedExchange.register_symbol/get_supported_symbols"
provides:
  - "All NAME-04 test consumers assert through public query APIs (routes, get_order_by_id, count_orders_by_status, emitted correlation_id, register_symbol/get_supported_symbols)"
  - "Zero remaining private-internal access (_routes/_by_id/_generate_correlation_id/raw _supported_symbols mutation) in the migrated test files"
  - "Phase 05 (plans 01-04) composes end-to-end: golden byte-exact, e2e 58/58, mypy strict clean"
affects: [order-manager-decomposition, future-backend-swaps]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Test-hygiene rewrite: swap private-internal read/mutation for an EXISTING public query/seam — no new production API, no test-only backdoor (D-09 guardrail)"
    - "Assert the OBSERVABLE EFFECT (emitted PortfolioErrorEvent.correlation_id) instead of calling the private id-generation helper"

key-files:
  created:
    - .planning/phases/05-naming-encapsulation/05-04-SUMMARY.md
  modified:
    - tests/unit/events/test_dispatch_registry.py
    - tests/unit/order/test_order_storage.py
    - tests/unit/portfolio/test_portfolio_handler.py
    - tests/unit/execution/exchanges/test_simulated_exchange.py
    - tests/integration/test_universe_spans.py
    - tests/e2e/conftest.py

key-decisions:
  - "Correlation-id test adjudicated to the OBSERVABLE-EFFECT rewrite (PREFERRED branch): drive on_fill twice with an unknown portfolio, capture two emitted PortfolioErrorEvent.correlation_id values, assert distinct UUIDs — NOT kept as white-box. The public error-emission path makes correlation-id uniqueness observable cleanly, so the D-09 white-box fallback was not needed."
  - "test_flat_dict_is_sole_container: kept the hasattr-absence checks for the deleted nested containers (public negative introspection, no private read) and replaced the _by_id == {...} private-shape assertion with public get_order_by_id resolution of the single added order."
  - "cash_manager.py:266/271 white-box reservation writes left UNCHANGED per the plan's D-09 adjudication — routing them through a setter would violate the no-internal-setter guardrail."

requirements-completed: [NAME-04]

# Metrics
duration: ~10min
completed: 2026-06-11
---

# Phase 05 Plan 04: Test-Hygiene Rewrites (NAME-04) Summary

**Rewrote the 6 test consumers that reached private internals (`_routes`, `_by_id`, `_generate_correlation_id`, raw `_supported_symbols` mutation) to assert through the public query APIs introduced in Wave 1 (`routes`, `get_order_by_id`, `count_orders_by_status`, the emitted `correlation_id`, `register_symbol`/`get_supported_symbols`) — no test-only backdoor or internal setter added; golden master byte-exact (134 / 46189.87730727451), e2e 58/58, mypy --strict clean.**

## Performance

- **Duration:** ~10 min
- **Completed:** 2026-06-11
- **Tasks:** 3 (2 implementation, 1 verification gate)
- **Files modified:** 6

## Accomplishments

- **Task 1 — `_routes` + `_by_id` consumers (D-06 / D-09 / D-01):**
  - `test_dispatch_registry.py`: all 8 `wiring.handler._routes[...]` attribute accesses → `wiring.handler.routes[...]` (the 05-02 public plain-field attr), plus the `:4` module-docstring `EventHandler._routes` → `EventHandler.routes`.
  - `test_order_storage.py`: all 6 `._by_id` attribute accesses → the public order query API — set-equality `:82` → public `get_order_by_id` resolution of the added order (+ negative checks); `:155/156` index/membership → `get_order_by_id(oid) is not None` / `== order`; `:170/174` non-membership → `get_order_by_id(oid) is None`; `:227` `_by_id[oid].price` → `get_order_by_id(oid).price`; and `:366` `handler.get_orders_summary(pid)` → `handler.count_orders_by_status(pid)` (the 05-01 canonical name). Stale `_by_id` comment prose updated to describe the public-query assertion.
- **Task 2 — `_generate_correlation_id` + raw `_supported_symbols` consumers (D-09 / D-07):**
  - `test_portfolio_handler.py` `test_correlation_id_generation`: rewritten to the **observable-effect** branch — drives the public `on_fill` path twice with an unknown portfolio (each runs its own `_operation_context`), captures the two emitted `PortfolioErrorEvent.correlation_id` values, and asserts they are distinct `uuid.UUID`s. The private `_generate_correlation_id` helper is no longer referenced.
  - `test_simulated_exchange.py:148`: `_supported_symbols == new_symbols` → `get_supported_symbols() == new_symbols` (the `:710-713` public-copy test left untouched).
  - `test_universe_spans.py:141/149`: raw `_supported_symbols = set(...) | {...}` mutation → a `register_symbol(...)` call per added ticker; the `<= _supported_symbols` read → `<= get_supported_symbols()`.
  - `e2e/conftest.py:348`: raw `_supported_symbols = set(...) | {...}` mutation → `register_symbol(...)` per ticker. The `:311/:328` PATTERNS-A2 comments documenting the deliberately-untouched set on the OTHER (config-re-derivation) path were left intact.
- **Task 3 — milestone gate:** full suite 844 green, integration 12 (oracle byte-exact 3/3), e2e 58/58, `mypy --strict` clean — proving the rewrites are behavior-preserving and the whole phase (01-04) composes.

## Correlation-ID Adjudication (plan-mandated)

The plan asked to PREFER the emitted-event assertion and document the choice. **Chosen: the observable-effect rewrite, NOT the D-09 white-box fallback.** Rationale: `PortfolioHandler._publish_error_event` carries the per-operation `correlation_id` onto every emitted `PortfolioErrorEvent`, and the existing `test_error_event_publishing` test already demonstrates that `on_fill` with an unknown portfolio emits exactly one such event. Two `on_fill` calls therefore run two `_operation_context` scopes and emit two events whose `correlation_id` fields are the public observable — uniqueness is assertable through the public surface with no contortion, so the white-box fallback was unnecessary.

## Verification Evidence

| Gate | Result |
|------|--------|
| `grep -c 'handler._routes' tests/unit/events/test_dispatch_registry.py` | 0 |
| `grep -c '.routes\[' tests/unit/events/test_dispatch_registry.py` | 7 |
| `grep -c '\._by_id' tests/unit/order/test_order_storage.py` | 0 |
| `grep -c 'get_orders_summary' tests/unit/order/test_order_storage.py` | 0 |
| `grep -c '_generate_correlation_id' tests/unit/portfolio/test_portfolio_handler.py` | 0 |
| `grep -c '_supported_symbols *=' tests/integration/test_universe_spans.py` | 0 |
| `grep -c 'register_symbol' tests/integration/test_universe_spans.py` | 2 |
| `grep -c '_supported_symbols *=' tests/e2e/conftest.py` | 0 |
| `grep -c '_supported_symbols ==' tests/unit/execution/exchanges/test_simulated_exchange.py` | 0 |
| `pytest` (full suite) | 844 passed |
| `pytest tests/integration` (oracle byte-exact 134 / 46189.87730727451) | 12 passed (oracle 3/3) |
| `pytest tests/e2e -m e2e` | 58 passed |
| `mypy --strict itrader` | Success: no issues found in 162 source files |
| `git diff --check` | clean — 4-space indentation preserved |
| Excluded files (test_error_flow / test_event_wiring / test_order_manager / test_on_signal / test_sltp_policy / test_cash_manager) | UNTOUCHED |
| oracle / golden baseline files | none edited (no re-baseline) |

## Deviations from Plan

None - plan executed exactly as written. (No Rule 1-4 deviations triggered. The only judgment call was the plan-mandated correlation-id adjudication, resolved to the PREFERRED observable-effect branch and documented above.)

## Commits

- `d9ec6a8` refactor(05-04): assert routes/_by_id consumers via public query APIs (NAME-04)
- `ad8242b` refactor(05-04): assert correlation-id + _supported_symbols via public surfaces (NAME-04)

(Task 3 was a verification-only gate — no files changed, no commit.)

## Known Stubs

None introduced.

## Self-Check: PASSED

- tests/unit/events/test_dispatch_registry.py — modified, present
- tests/unit/order/test_order_storage.py — modified, present
- tests/unit/portfolio/test_portfolio_handler.py — modified, present
- tests/unit/execution/exchanges/test_simulated_exchange.py — modified, present
- tests/integration/test_universe_spans.py — modified, present
- tests/e2e/conftest.py — modified, present
- Commit d9ec6a8 — present in git log
- Commit ad8242b — present in git log

---
*Phase: 05-naming-encapsulation*
*Completed: 2026-06-11*

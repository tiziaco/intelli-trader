# Phase 02 — Deferred Items

Out-of-scope discoveries logged during execution (not fixed in the discovering plan).

| ID | Item | Discovered | Owner | Status |
|----|------|------------|-------|--------|
| DEF-02-03-A | `tests/unit/core/test_sizing.py::test_sizing_policy_union_members` asserts the OLD 3-member `SizingPolicy` union (`FractionOfCash \| FixedQuantity \| RiskPercent`) but Plan 02-02 (`e2afb00`) grew the union with `LeveredFraction`. The stale assertion now fails. Pre-existing failure in an unrelated file — out of Plan 02-03's scope (admission/order-domain wiring). | Plan 02-03 execution (2026-06-15) | Plan 02-02 / a follow-up quick-task | Open — update the test to include `LeveredFraction` in the expected union. |

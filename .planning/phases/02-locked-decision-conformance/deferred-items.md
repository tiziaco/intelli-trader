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
- **Status:** Open — expected to clear when plan 02-03 completes its verification task. If it
  remains red at phase close, plan 02-03 must update the assertion (e.g. to validate the
  CorrelationId/UUID shape, dropping the obsolete `ph_` prefix expectation).

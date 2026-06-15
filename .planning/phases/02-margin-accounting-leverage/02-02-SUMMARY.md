---
phase: 02-margin-accounting-leverage
plan: 02
subsystem: sizing (typed policy vocabulary + resolver arm)
tags: [leverage, sizing, levered-kelly, oracle-dark, D-07, D-03, D-12, LEV-02]
requires:
  - "02-00 (Wave 0 collectible test stub: test_levered_fraction_wave0_stub)"
  - "02-01 (SignalEvent.leverage / TradingRules.max_leverage contract fields, D-03/D-14)"
provides:
  - "LeveredFraction sizing kind in core/sizing.py — notional = f x total_equity, f>0 guard (NOT (0,1]) (D-07/LEV-02)"
  - "SizingPolicy union grown with LeveredFraction (forces resolver exhaustiveness, D-02 growth rule)"
  - "SignalIntent.leverage: Decimal field (default Decimal('1')) — strategy-return mirror (D-03)"
  - "resolve_entry LeveredFraction arm reading total_equity() (D-12 mark-to-market, LEV-02)"
affects:
  - "Plan 03 AdmissionManager — owns the f>1-only-under-enable_margin gate (RESEARCH A3); resolver stays config-free"
  - "Strategy authoring — LeveredFraction makes a Kelly fraction f>1 structurally expressible"
tech-stack:
  added: []
  patterns:
    - "New sizing-policy kind: frozen-slots dataclass mirroring RiskPercent + __post_init__ guard"
    - "Union member addition forcing the resolver's typing.assert_never arm (D-02 fail-loud growth gate)"
    - "Resolver reads portfolio state ONLY through the injected PortfolioReadModel Protocol (total_equity)"
key-files:
  created: []
  modified:
    - "itrader/core/sizing.py (LeveredFraction dataclass + union member + __all__ + SignalIntent.leverage)"
    - "itrader/order_handler/sizing_resolver.py (import + resolve_entry LeveredFraction case arm)"
    - "tests/unit/order/test_sizing_resolver.py (replaced Wave 0 stub with 4 real LeveredFraction tests)"
decisions:
  - "fraction guarded > 0 via _require_positive, NOT (0,1] — f>1 is structurally allowed at the policy level (the gate lives in AdmissionManager, Plan 03)"
  - "FractionOfCash (0,1] guard left untouched — the golden oracle-dark byte-exact path is preserved (D-02 growth, never relax)"
  - "fraction (exposure: notional = f x equity) and leverage (margin backing, D-03) are complementary not redundant (D-07a); the resolver never conflates them"
  - "resolver arm reads total_equity() (D-12 mark-to-market) through the read-model Protocol — never cash, never the concrete handler"
  - "to_money(price) string-path Decimal entry (Pitfall 1) — never Decimal(float)"
metrics:
  duration: ~8 min
  completed: 2026-06-15
  tasks: 2
  files: 3
---

# Phase 2 Plan 02: Equity-Based Levered Sizing Kind Summary

Added the equity-based `LeveredFraction` sizing kind (D-07/LEV-02): a Kelly fraction `f > 1` is now structurally expressible as `notional = f x total_equity()`. The new dataclass mirrors `RiskPercent` but guards `f > 0` (NOT `(0,1]`), grows the `SizingPolicy` union forcing the resolver's `assert_never` arm to be satisfied in the same change, reads mark-to-market `total_equity()` (D-12) through the injected read-model, and lands the `SignalIntent.leverage` strategy-return mirror (D-03). Oracle-dark — the golden `FractionOfCash` run never constructs `LeveredFraction`.

## What Was Built

- **`LeveredFraction` frozen-slots dataclass** (`core/sizing.py`) — mirrors `RiskPercent`'s shape (`fraction: Decimal`, optional `step_size`), validated in `__post_init__` via `_require_positive("LeveredFraction", "fraction", ...)` (f > 0) + `_validate_step_size`. CRITICAL: uses `_require_positive`, NOT `_require_unit_interval` — `f > 1` is allowed at the policy level; the `f>1 only when enable_margin` gate is enforced downstream in `AdmissionManager` (Plan 03, RESEARCH A3), keeping this policy config-agnostic. Docstring records D-07 (notional = f x equity), D-07a (fraction = exposure vs leverage = margin backing, complementary), and oracle-dark intent.
- **`SizingPolicy` union grown** to `FractionOfCash | FixedQuantity | RiskPercent | LeveredFraction` (+ `LeveredFraction` added to `__all__`). Adding the union member without the resolver arm fails `mypy --strict` at `assert_never` — both landed in this one change (D-02 growth rule, intended fail-loud gate).
- **`SignalIntent.leverage: Decimal = Decimal("1")`** — the D-03 strategy-return mirror, a defaulted `kw_only` field placed after the other defaulted fields, with a docstring entry noting it is complementary to a `LeveredFraction` policy's `fraction` (D-07a). Inert default keeps the golden path byte-exact.
- **`resolve_entry` `LeveredFraction` case arm** (`sizing_resolver.py`) — reads `equity = self._read_model.total_equity(portfolio_id)` (D-12 mark-to-market) and computes `qty = (policy.fraction * equity) / to_money(price)`. Reads `total_equity`, NEVER cash. Config-free (no `enable_margin` knowledge — resolver purity). `to_money(price)` is the string-path Decimal entry. The `case _: assert_never(policy)` is preserved (now exhaustive). The existing `step_size` quantize path applies uniformly.

## Verification

- Task 1 automated check: `LeveredFraction(fraction=Decimal("2"))` constructs; `LeveredFraction(fraction=Decimal("0"))` raises (f>0 guard); `FractionOfCash(fraction=Decimal("1.5"))` still raises ((0,1] guard intact); `SignalIntent` has `leverage` defaulting to `Decimal("1")` → OK.
- Task 2 (TDD): RED — 4 new `levered_fraction` tests failed at `assert_never` (union grew, arm absent). GREEN — all 4 pass after the arm landed.
  - `test_levered_fraction_sizes_notional_off_equity`: f=2, equity=50000, price=100 → qty=1000 (reads total_equity, tiny cash basis proves cash is NOT read).
  - `test_levered_fraction_above_one_sizes_larger_than_unit`: f=3 resolves 3x the f=1 qty (no clamp here).
  - `test_levered_fraction_ignores_stop`: stop=None is fine (stop-independent).
  - `test_levered_fraction_step_size_quantizes_round_down`: (2 x 50000)/30 → step 0.01 → 3333.33.
- `poetry run pytest tests/unit/order/test_sizing_resolver.py` → 23 passed (4 new + 19 prior; FractionOfCash byte-exact arm tests still green).
- `poetry run mypy itrader` → Success: no issues found in 185 source files (the `assert_never` arm proves union + arm landed together).

## TDD Gate Compliance

- RED gate: `test(02-02)` commit `cfd4bef` — 4 failing `levered_fraction` tests.
- GREEN gate: `feat(02-02)` commit `9760fba` — resolver arm makes them pass; mypy clean.
- REFACTOR: none needed — the arm is minimal and mirrors the existing `RiskPercent` arm.

## Deviations from Plan

None - plan executed exactly as written.

## Known Stubs

None - the only stub touched (`test_levered_fraction_wave0_stub`) was the Wave 0 placeholder this plan was scheduled to implement; it is now 4 real tests.

## Self-Check: PASSED

- `itrader/core/sizing.py` — FOUND (LeveredFraction, union member, SignalIntent.leverage)
- `itrader/order_handler/sizing_resolver.py` — FOUND (LeveredFraction resolver arm)
- `tests/unit/order/test_sizing_resolver.py` — FOUND (4 real levered_fraction tests)
- Commit e2afb00 (Task 1 feat) — FOUND
- Commit cfd4bef (Task 2 RED test) — FOUND
- Commit 9760fba (Task 2 GREEN feat) — FOUND

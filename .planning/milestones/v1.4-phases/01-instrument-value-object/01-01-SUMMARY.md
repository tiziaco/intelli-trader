---
phase: 01-instrument-value-object
plan: 01
subsystem: core
tags: [instrument, money, quantize, decimal, frozen-value-object, byte-exact]
requires: []
provides:
  - "itrader.core.instrument.Instrument (frozen per-symbol value object)"
  - "itrader.core.money.quantize(value, Instrument, kind) — Instrument-driven scale read"
affects:
  - "itrader/core/money.py (quantize signature + _INSTRUMENT_SCALES deletion)"
  - "tests/unit/core/test_money.py (three quantize call sites)"
tech-stack:
  added: []
  patterns:
    - "Frozen value object: @dataclass(frozen=True, slots=True, kw_only=True) mirroring core/bar.py::Bar"
    - "Decimal scale stored directly (not int place-count) for byte-exact rounding (D-10/Pitfall 3)"
    - "Pure/stateless rounding mechanism reading domain state off an injected value object (D-05)"
key-files:
  created:
    - itrader/core/instrument.py
    - tests/unit/core/test_instrument.py
  modified:
    - itrader/core/money.py
    - tests/unit/core/test_money.py
decisions:
  - "Stored the Decimal SCALE on Instrument (price_precision=Decimal('0.00000001')) rather than an int place-count — byte-identical to the deleted table, keeps quantize a one-line value.quantize(scale)"
  - "Ordered required dataclass fields before defaulted ones (kw_only relaxes this, but defensive ordering reads cleanly and is construction-equivalent)"
  - "cash scale derives from _DEFAULT_SCALES['cash'] (quote_currency USD -> 2dp) rather than a per-Instrument cash field — YAGNI, crypto-first all USD-quoted"
metrics:
  duration_minutes: 4
  tasks_completed: 2
  completed_date: 2026-06-15
requirements-completed: [INST-01, INST-03]
---

# Phase 1 Plan 01: Instrument Value Object & quantize() Rewire Summary

Landed a frozen `Instrument` value object as the per-symbol source of precision +
`min_order_size` + inert margin params, and rewired `core/money.py::quantize()` to
read its rounding scale off a handed-in `Instrument` — deleting the hard-coded
`_INSTRUMENT_SCALES` table with the SMA_MACD oracle held byte-exact by construction.

## What Was Built

**Task 1 — `Instrument` frozen value object (TDD: RED → GREEN).**
`itrader/core/instrument.py` mirrors `core/bar.py::Bar` exactly:
`@dataclass(frozen=True, slots=True, kw_only=True)`, 4-space indented (core
convention), module docstring citing D-04/D-05/D-01a/D-10/INST-01/03. Eight fields:
`symbol`, `price_precision` (Decimal scale), `quantity_precision` (Decimal scale),
`maintenance_margin_rate`, `max_leverage` (required); `quote_currency="USD"`,
`min_order_size: Decimal | None = None` (D-01a undeclared fallback),
`settles_funding=False` (defaulted). The INST-03 margin fields land inert for
Phase 2 (leverage) / Phase 4 (liquidation) / Phase B (funding, deferred).
`tests/unit/core/test_instrument.py` — 8 tests: frozen-ness (`FrozenInstanceError`),
8dp scale byte-exactness, the scale-vs-int guard (`Decimal(1).scaleb(-8)` /
`str == "1E-8"`), `min_order_size` None default + declared round-trip, margin-field
presence, and `settles_funding`/`quote_currency` defaults.

**Task 2 — `quantize()` rewire + `_INSTRUMENT_SCALES` deletion.**
`quantize(value: Decimal, instrument: Instrument, kind: str)` now resolves the
scale via a `kind → field` map: `"price" → instrument.price_precision`,
`"quantity" → instrument.quantity_precision`, `"cash" → _DEFAULT_SCALES["cash"]`
(USD 2dp); `ROUND_HALF_UP` unchanged. The entire `_INSTRUMENT_SCALES` table was
deleted (including the docstring mention — `grep -c` returns 0). `_DEFAULT_SCALES`,
`ONE`, `to_money`, and `__all__` are unchanged. The three `test_money.py` call
sites (`:45/:50/:57`) now pass `Instrument` objects (a BTCUSD 8dp instrument and a
default-precision instrument replacing the former `"UNKNOWN"` string case),
preserving byte-identical expected outputs.

## Verification

- `poetry run pytest tests/unit/core/test_instrument.py tests/unit/core/test_money.py` — 13 passed.
- `poetry run mypy itrader` — Success: no issues found in 183 source files (strict-clean).
- `grep -c '_INSTRUMENT_SCALES' itrader/core/money.py` — `0` (table fully deleted).
- `grep -nP '\t'` on `instrument.py` / `money.py` — no tabs (4-space core convention held).
- **D-02a proven:** `test_money.py` remains the ONLY importer of the module `quantize()`
  (grep over `itrader/` + `tests/`); every production `.quantize(` is the stdlib method.
- **Byte-exact oracle gate held** (run as a guard, though the plan defers it to 01-03):
  `poetry run pytest tests/integration/test_backtest_oracle.py` — 3 passed
  (134 trades / `final_equity 46189.87730727451`).

## Deviations from Plan

None — plan executed as written. One acceptance-criterion nuance handled inline
(not a behavior deviation): the first docstring rewrite still contained the literal
token `_INSTRUMENT_SCALES` (in a "the table is gone" sentence), which would have
failed `grep -c == 0`; reworded to "per-instrument scale table" so the token count
is exactly 0 per the acceptance criterion.

## Threat Flags

None. This plan adds a pure in-process value object and rewires a pure rounding
function — no new external input, auth, secret, network, or endpoint surface. The
T-01-01 precision-drift mitigation (store the Decimal scale directly) is implemented
and covered by the scale-equivalence test; the oracle byte-exact gate (the second
mitigation, owned by 01-03) was run here and holds.

## Known Stubs

None. The INST-03 margin fields (`maintenance_margin_rate`, `max_leverage`,
`settles_funding`) are intentionally **inert** — declared-but-unconsumed value-object
fields landed for downstream phases (Phase 2 leverage, Phase 4 liquidation, Phase B
funding). This is by design per INST-03, not a stub: they carry real data on every
constructed `Instrument`; no consumer reads them yet.

## Commits

- `dd23df6` test(01-01): add failing tests for frozen Instrument value object (RED)
- `4edb0a1` feat(01-01): add frozen Instrument value object (INST-01/INST-03) (GREEN)
- `77cf135` feat(01-01): rewire quantize() to read scale off an Instrument; delete _INSTRUMENT_SCALES

## Self-Check: PASSED

All created/modified files present on disk; all three task commits present in git
history. No missing artifacts.

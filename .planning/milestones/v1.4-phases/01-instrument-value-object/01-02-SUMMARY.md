---
phase: 01-instrument-value-object
plan: 02
subsystem: universe
tags: [instrument, universe, min-order-size, precision-ladder, inference, byte-exact, decimal]
requires:
  - "itrader.core.instrument.Instrument (frozen per-symbol value object, plan 01-01)"
provides:
  - "itrader.universe.derive_instruments(...) -> dict[str, Instrument] — declared->inferred(8dp cap)->default ladder"
  - "itrader.universe.Universe — read-model facade (.members byte-exact, .instrument(symbol))"
  - "SimulatedExchange.resolve_min_order_size(ticker) + set_universe(universe) — Instrument-first -> venue fallback"
  - "Engine.universe field (DI seam for the symbol->Instrument read-model)"
affects:
  - "itrader/config/exchange.py (ExchangeLimits demoted to venue fallback — docstring/value unchanged)"
  - "itrader/execution_handler/exchanges/simulated.py (admission gate min_order_size resolution)"
  - "itrader/trading_system/backtest_runner.py (Universe constructed/injected at Trap-4 point)"
  - "itrader/trading_system/live_trading_system.py (mirrors Universe wiring, mypy-deferred)"
  - "itrader/trading_system/compose.py (Engine.universe field)"
tech-stack:
  added: []
  patterns:
    - "Pure derive-once-at-wiring sibling of derive_membership (no class/state/queue/feed import)"
    - "Precision ladder: declared(wins) -> inferred(raw-string read, 8dp cap) -> default (D-09)"
    - "Raw-CSV-string decimal-count inference (Pitfall 1 — never off the float64 frame)"
    - "Injected read-model facade composing pure fns (Universe over membership + instrument map)"
    - "Instrument-first -> venue-fallback resolution with byte-exact None default (no universe -> venue min)"
key-files:
  created:
    - itrader/universe/instruments.py
    - itrader/universe/universe.py
    - tests/unit/universe/test_derive_instruments.py
    - tests/unit/universe/test_universe.py
    - tests/unit/execution/test_min_order_size_resolution.py
  modified:
    - itrader/universe/__init__.py
    - itrader/config/exchange.py
    - itrader/execution_handler/exchanges/simulated.py
    - itrader/trading_system/compose.py
    - itrader/trading_system/backtest_runner.py
    - itrader/trading_system/live_trading_system.py
decisions:
  - "Declared-config home (OQ1) = a small in-code _DECLARED table in instruments.py for Phase 1; BTCUSD reproduces _INSTRUMENT_SCALES['BTCUSD'] 8dp exactly, min_order_size omitted (D-01a)"
  - "price_data inference input shaped as Mapping[str, Sequence[str]] (symbol -> raw price strings) — pure/testable without files; wiring passes price_data={} on the golden path (BTCUSD declared, no inference)"
  - "Universe.instrument(unknown) raises KeyError; the exchange catches KeyError and falls through to the venue min (a non-member resolves to the venue fallback, byte-exact)"
  - "SimulatedExchange gains a set_universe injection (None default) rather than a constructor arg — keeps every pre-existing no-universe exchange construction byte-exact"
  - "Engine.universe is Optional[Universe]=None populated by the runner at the Trap-4 point, not by compose_engine — wiring order (membership derive -> feed.bind) preserved byte-exact"
metrics:
  duration_minutes: 5
  tasks_completed: 2
  completed_date: 2026-06-15
requirements-completed: [INST-02, INST-03]
---

# Phase 1 Plan 02: Universe Instrument Resolution & ExchangeLimits Demotion Summary

Built the symbol->`Instrument` resolution layer in `universe/` (the declared ->
inferred(raw-string, 8dp-cap) -> default precision ladder, with BTCUSD always on
the declared branch) and wired the `Universe` read-model through the backtest +
live composition roots, demoting `ExchangeLimits.min_order_size` to the
venue-level fallback that `SimulatedExchange` now resolves Instrument-first —
with the SMA_MACD oracle held byte-exact (134 trades / `final_equity 46189.87730727451`).

## What Was Built

**Task 1 — `derive_instruments` ladder + `Universe` facade (TDD: RED -> GREEN).**
`itrader/universe/instruments.py` (4-space) adds the pure
`derive_instruments(strategies, screener_tickers, *, price_data) -> dict[str, Instrument]`,
the derive-once sibling of `derive_membership` (composes it for the member set,
never reimplements it). The D-09 ladder per member symbol: `price_precision =
declared -> inferred(guarded) -> default(0.01)`; `quantity_precision = declared ->
default(8dp)` (NOT inferable, D-10); `min_order_size = declared -> None` (D-01a);
margin params = declared -> default (inert). The in-code `_DECLARED` table
reproduces `_INSTRUMENT_SCALES["BTCUSD"]` exactly (8dp price + 8dp quantity,
`min_order_size` OMITTED). `_infer_price_scale` reads the **raw CSV strings**
(Pitfall 1 — counts decimal places off the string, caps at 8dp, enters via the
`Decimal("1e-<n>")` string path). `itrader/universe/universe.py` (4-space) is a
thin `Universe` facade: `.members` returns the constructed list by identity
(byte-exact, Pitfall 4), `.instrument(symbol)` looks up the injected map
(`KeyError` for non-members). The barrel re-exports both (single-quote `__all__`).
`tests/unit/universe/test_derive_instruments.py` (11 tests) + `test_universe.py`
(4 tests) cover declared-wins, inferred(3dp/5dp/8dp-cap/max-across-cells),
string-not-float inference, default fallback, quantity-never-inferred,
BTCUSD-min-None, and the `.members` byte-exact / identity guarantees.

**Task 2 — `ExchangeLimits` demotion + Instrument-first `min_order_size` + wiring.**
`config/exchange.py`: `ExchangeLimits.min_order_size` reframed in its docstring as
the venue-level fallback for undeclared symbols — **value unchanged**
(`Decimal("0.001")`, byte-exact). `simulated.py` (TABS): added a `_universe`
attribute (None default), `set_universe(universe)`, and `resolve_min_order_size(ticker)`
(Instrument-first when an injected universe declares a min; otherwise the venue
fallback; a non-member or absent universe also falls through — byte-exact). The
admission gate at `validate_order` now resolves the per-order minimum via
`resolve_min_order_size(event.ticker)`. `compose.py` (TABS): added
`Engine.universe: Optional[Universe] = None`. `backtest_runner.py` (TABS):
constructs the `derive_instruments` map + `Universe` at the Trap-4 point, sets it
onto the engine, injects it into the simulated exchange, and passes
`universe.members` (the SAME list) to `feed.bind` — wiring order preserved
exactly. `live_trading_system.py` (4-space, mypy-deferred): mirrors the same
construction/injection at its `derive_membership` site (D-08).
`tests/unit/execution/test_min_order_size_resolution.py` (5 tests):
Instrument(None) -> 0.001, declared -> declared value, BTCUSD -> 0.001, no-universe
-> venue fallback, non-member -> venue fallback.

## Verification

- `poetry run pytest tests/unit/universe/test_derive_instruments.py tests/unit/universe/test_universe.py -v` — 15 passed.
- `poetry run pytest tests/unit/execution/test_min_order_size_resolution.py -v` — 5 passed.
- `poetry run pytest tests/unit/universe/ tests/unit/execution/ -q` — 179 passed (no execution regression).
- `poetry run mypy itrader` — Success: no issues found in 185 source files (strict-clean; `derive_instruments -> dict[str, Instrument]`, `Universe.members -> list[str]`, `Universe.instrument -> Instrument`).
- **Byte-exact oracle gate HELD:** `poetry run pytest tests/integration -q` — 16 passed (oracle 3/3: 134 trades / `final_equity 46189.87730727451`).
- **E2E gate HELD (no leaf re-baselined):** `poetry run pytest tests/e2e -m e2e -q` — 59 passed.
- Acceptance greps: `grep -c 'def derive_membership' universe.py` == 0 (composes, not reimplements); `grep -nP '\t'` on the two new universe files == nothing (4-space); `grep -c 'Decimal("0.001")' config/exchange.py` == 6 (>= 1); Trap-4 order preserved (`derive_membership` precedes `feed.bind` in `backtest_runner.py`); `grep -q "Universe(" live_trading_system.py` exits 0; tabs preserved in `simulated.py`/`compose.py`/`backtest_runner.py` new lines.

## Deviations from Plan

None — plan executed as written. One wiring-shape choice within the plan's
"Claude's-Discretion on plumbing" latitude: the exchange receives the `Universe`
via a `set_universe()` injection (None default) rather than a constructor
argument, so every pre-existing no-universe exchange construction (unit tests,
the conftest seam) stays byte-exact and no signature changes ripple through
`ExecutionHandler.init_exchanges`. The `price_data` inference input is shaped as
`Mapping[str, Sequence[str]]` (symbol -> raw price strings) — pure and testable
without re-reading CSV files; the golden path passes `price_data={}` because
BTCUSD is declared (D-10), so inference is never consulted on the run path.

## Threat Flags

None. This plan adds a derived-once read-model and rewires an in-process
admission check — no new external input, auth, secret, network, or endpoint
surface (threat register T-01-02 / T-01-03 mitigations confirmed: BTCUSD always
on the declared branch, inference 8dp-capped + synthetic-only, undeclared
min_order_size -> ExchangeLimits(0.001) byte-identical; the byte-exact oracle +
e2e gates both held).

## Known Stubs

None. The inferred-price-scale path is fully implemented and unit-covered on
synthetic non-oracle symbols; it is simply not exercised on the golden run path
(BTCUSD is declared, D-10). The INST-03 margin fields on each derived
`Instrument` remain intentionally inert (Phase 2 leverage / Phase 4 liquidation
consumers), consistent with plan 01-01.

## Commits

- `f34e1ec` test(01-02): add failing tests for derive_instruments ladder + Universe facade (RED)
- `5827c8e` feat(01-02): add derive_instruments ladder + Universe facade (INST-02, GREEN)
- `a4590d7` feat(01-02): demote ExchangeLimits to venue fallback + Instrument-first min_order_size (INST-03)

## Self-Check: PASSED

All created/modified files present on disk; all three task commits present in git
history. mypy strict-clean, oracle byte-exact, e2e 59/59. No missing artifacts.

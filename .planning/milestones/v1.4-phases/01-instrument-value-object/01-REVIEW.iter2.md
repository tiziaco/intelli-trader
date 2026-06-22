---
phase: 01-instrument-value-object
reviewed: 2026-06-15T00:00:00Z
depth: standard
files_reviewed: 15
files_reviewed_list:
  - itrader/config/exchange.py
  - itrader/core/instrument.py
  - itrader/core/money.py
  - itrader/execution_handler/exchanges/simulated.py
  - itrader/trading_system/backtest_runner.py
  - itrader/trading_system/compose.py
  - itrader/trading_system/live_trading_system.py
  - itrader/universe/__init__.py
  - itrader/universe/instruments.py
  - itrader/universe/universe.py
  - tests/unit/core/test_instrument.py
  - tests/unit/core/test_money.py
  - tests/unit/execution/test_min_order_size_resolution.py
  - tests/unit/universe/test_derive_instruments.py
  - tests/unit/universe/test_universe.py
findings:
  critical: 0
  warning: 5
  info: 5
  total: 10
status: issues_found
---

# Phase 01: Code Review Report

**Reviewed:** 2026-06-15
**Depth:** standard
**Files Reviewed:** 15
**Status:** issues_found

## Summary

This phase introduces the frozen `Instrument` value object, the `derive_instruments` precision
ladder, the `Universe` read-model facade, and rewires `money.quantize` to read its scale off an
`Instrument` instead of a hard-coded `_INSTRUMENT_SCALES` table. The byte-exact golden discipline
holds on the oracle path: BTCUSD is DECLARED (8dp price/quantity, `min_order_size` undeclared), so
inference is never consulted and `resolve_min_order_size("BTCUSD")` falls through to the venue
`Decimal("0.001")` byte-identically. Money stays Decimal end-to-end in the new core/universe code —
no `Decimal(float)` and no float-for-money introduced; the precision-inference path enters Decimal
via the `Decimal("1e-<n>")` string path correctly.

No BLOCKER-class correctness or security defects were proven. The findings below are
robustness/maintainability gaps and a small set of doc-vs-implementation mismatches that should be
fixed before the contract is consumed by later phases (Phase 2 leverage, Phase 4 liquidation), plus
latent bugs in the not-yet-exercised inference path. The most material is the `quantize` cash-scale
contract: the docstring promises `quote_currency`-derived cash precision but the implementation
hard-codes 2dp — inert today (only USD), but a real defect the moment a non-USD instrument is added.

## Warnings

### WR-01: `quantize` cash scale ignores `quote_currency` — doc/impl mismatch, latent for non-USD

**File:** `itrader/core/money.py:62-79`
**Issue:** The docstring (lines 17-18, 70-72) states the `"cash"` scale "derives from `quote_currency`
(default USD -> 2dp)". The implementation hard-codes `_DEFAULT_SCALES["cash"]` (always `Decimal("0.01")`)
and never reads `instrument.quote_currency`. `Instrument.quote_currency` exists and is documented as
"the source of the `kind="cash"` scale", but `quantize` ignores it entirely. This is inert this phase
(every instrument is USD) but becomes a correctness defect the moment a non-2dp quote currency (e.g. a
JPY-quoted or 8dp-stable instrument) is derived: cash will silently quantize to the wrong scale, and
the ledger write will be wrong. Either the code or the contract is lying.
**Fix:** Make the contract honest. Either implement the promised derivation:
```python
_CASH_SCALES: dict[str, Decimal] = {"USD": Decimal("0.01")}
...
scale = {
    "price": instrument.price_precision,
    "quantity": instrument.quantity_precision,
    "cash": _CASH_SCALES.get(instrument.quote_currency, _DEFAULT_SCALES["cash"]),
}.get(kind, _DEFAULT_SCALES[kind])
```
or downgrade the docstring to state explicitly that cash is fixed at 2dp this phase and
`quote_currency` is currently unconsumed (carried inert for a later phase).

### WR-02: `_infer_price_scale` miscounts scientific-notation and trailing-garbage cells

**File:** `itrader/universe/instruments.py:108-143`
**Issue:** `_infer_price_scale` counts characters after the first `.` with no validation that they are
digits. A raw cell in scientific notation (e.g. `"1.0e-5"`) yields `text.split(".",1)[1] == "0e-5"`
→ `len == 4` → inferred 4dp, which is simply wrong. A cell with a trailing currency/sign artifact
(e.g. `"12.34 "` after strip is fine, but `"12.34%"` → 3) is likewise mis-measured. This path is
oracle-dark today (golden run passes `price_data={}`, BTCUSD is declared so inference never runs), so
it does not threaten the byte-exact gate — but it is a real bug the first time INST-02 inference is
wired against a non-declared symbol whose feed emits non-plain-decimal strings.
**Fix:** Validate the fractional part is all digits before counting, and skip the cell otherwise:
```python
frac = text.split(".", 1)[1]
if not frac.isdigit():
    continue  # scientific notation / trailing garbage — not a plain decimal count
decimals = len(frac)
```

### WR-03: Redundant double `derive_membership` derivation in the runner

**File:** `itrader/trading_system/backtest_runner.py:61-74`
**Issue:** `_initialise_backtest_session` calls `derive_membership(...)` to build `membership`, then
calls `derive_instruments(...)` which internally calls `derive_membership(...)` **again** over the
same inputs (`itrader/universe/instruments.py:186`). The two derivations each return `list(set(...))`.
Within one interpreter they agree, so `universe.members` (first call) and `instruments`' key set
(second call) are consistent — no bug today. But it is wasteful and, more importantly, fragile: any
future change that makes `derive_membership` non-idempotent (e.g. consuming a generator strategy
input, or time-dependent membership) would silently desync `universe.members` from `instruments`,
producing a `Universe` whose `members` list contains a symbol absent from `instrument_map` (then
`instrument(symbol)` → `KeyError` at runtime).
**Fix:** Derive membership once and thread it in, or have `derive_instruments` accept a precomputed
membership list. Minimal change: pass the already-derived `membership` to a `derive_instruments`
overload, or assert `set(instruments) == set(membership)` immediately after construction so a future
desync fails loudly at wiring rather than mid-run.

### WR-04: `LiveTradingSystem.universe` is set only in `_initialize_live_session`, never in `__init__`

**File:** `itrader/trading_system/live_trading_system.py:274`
**Issue:** `self.universe` is assigned only inside `_initialize_live_session` (invoked from `start()`).
Any access to `self.universe` before `start()` is called raises `AttributeError` rather than returning
a defined "not yet wired" sentinel. The backtest path declares `Engine.universe: Optional[Universe] = None`
(`compose.py:106`) so a pre-wiring read is a clean `None`; the live path has no such declaration and is
asymmetric. This module is mypy-deferred so it escapes the strict gate, and no current consumer reads
`self.universe`, but the asymmetry is an attribute-existence trap for the D-live consumer.
**Fix:** Initialise `self.universe: Optional[Universe] = None` in `__init__` alongside the other
component attributes, mirroring `Engine.universe`.

### WR-05: `derive_membership` set-ordered output threads into `feed.bind` / ping-grid ordering

**File:** `itrader/universe/membership.py:79`, consumed at `itrader/trading_system/backtest_runner.py:84`
**Issue:** `derive_membership` returns `list(set(tickers))`; the docstring correctly warns order is
unspecified. `Universe.members` holds this list by identity and feeds it directly to
`engine.feed.bind(engine.global_queue, universe.members)`. With `PYTHONHASHSEED` randomized (the
CPython default), the iteration order of a `set[str]` varies run-to-run, so for any MULTI-symbol
universe `members` order is non-deterministic. This is behavior-preserving against the legacy code
(which also used `list(set(...))`), so the single-symbol golden run stays byte-exact and this is NOT a
phase regression — but it is a determinism hazard the project's own "runs must be reproducible"
constraint cares about, and it is newly surfaced through the `Universe` seam this phase formalizes.
The ping grid is order-insensitive (`reduce(pd.Index.union, ...)` then sorted by index), but feed-bind
ordering or any downstream order-sensitive consumer would drift.
**Fix:** Out of strict phase scope (pre-existing), but recommend sorting at the membership boundary —
`return sorted(set(tickers))` in `derive_membership` — to make multi-symbol runs reproducible without
touching the single-symbol oracle (a 1-element list is its own sort). Confirm against the byte-exact
oracle before merging.

## Info

### IN-01: `money.quantize` has no production caller — new `Instrument` signature is unexercised on the run path

**File:** `itrader/core/money.py:62`
**Issue:** A grep of `itrader/` finds no production call site for `money.quantize` (only the two
test modules import it). The signature changed from `quantize(value, instrument: str, kind)` to
`quantize(value, instrument: Instrument, kind)` this phase. The new contract is therefore validated
only by unit tests, not by any run-path consumer — the byte-exact oracle does not exercise it. Not a
defect (the prior `quantize` was likewise effectively a boundary helper), but flagged so reviewers do
not assume the golden run covers the new `Instrument`-keyed rounding path.
**Fix:** None required; note for the consuming phase (Phase 2/4) to add an integration assertion when
`quantize(..., instrument, ...)` lands on a real ledger-write path.

### IN-02: `Universe.members` returns the live internal list by reference (mutable)

**File:** `itrader/universe/universe.py:51-54`
**Issue:** The `.members` property returns `self._members` directly (intentional, Pitfall 4 — identity
must be preserved for byte-exact `feed.bind`). A caller that mutates the returned list mutates the
universe's internal membership. The identity requirement is real and documented, so a defensive copy
is not the fix — but the surface is mutate-through with no guard.
**Fix:** Document the read-only contract on the property (`# returned by identity — DO NOT mutate`),
or expose as a `tuple` if the byte-exact `feed.bind` consumer accepts a tuple. Lowest-risk: a comment;
do not change the return type without re-checking the oracle.

### IN-03: `derive_instruments` margin/`settles_funding` ladder is verbose, repeated `declared is not None` guards

**File:** `itrader/universe/instruments.py:192-220`
**Issue:** The per-field `if declared is not None and declared.X is not None: ... else: ...` ladder is
repeated five times with identical structure. Correct, but high-ceremony and easy to get subtly wrong
on the next field added. A small helper (`_pick(declared_value, default)`) would collapse each rung to
one line and remove the repeated `declared is not None` short-circuit.
**Fix:** Optional refactor:
```python
def _pick(value, default):
    return value if value is not None else default
...
maintenance_margin_rate = _pick(
    declared.maintenance_margin_rate if declared else None, _DEFAULT_MAINTENANCE_MARGIN_RATE)
```

### IN-04: `Instrument.quote_currency` documented as the cash-scale source but currently unconsumed

**File:** `itrader/core/instrument.py:47-48,77`
**Issue:** The field docstring says `quote_currency` is "source of the `kind="cash"` scale (USD -> 2dp)",
but no code reads it (see WR-01). It is carried inert. This is acceptable as a forward-declaration but
the docstring overstates current behavior.
**Fix:** Append "(inert this phase — `quantize` currently fixes cash at 2dp; consumed when non-USD
quote currencies land)" to the field doc, consistent with the explicit inert-marking on the margin
fields.

### IN-05: `_DECLARED` price/quantity scales duplicate the deleted `_INSTRUMENT_SCALES` literal with no shared assertion

**File:** `itrader/universe/instruments.py:99-105`
**Issue:** The byte-exact guarantee rests on `_DECLARED["BTCUSD"]` reproducing the deleted
`_INSTRUMENT_SCALES["BTCUSD"]` 8dp scales exactly. This is asserted only by tests
(`test_btcusd_takes_declared_8dp`), and the duplicated literal `Decimal("0.00000001")` appears in
four places across `instruments.py`, `money.py:48`, and the test modules. A future edit to one and not
the others would silently drift the oracle. Tests catch it, but the magic literal is unanchored.
**Fix:** Reference a single shared module constant (e.g. reuse `_DEFAULT_QUANTITY_SCALE` /
introduce `_BTC_8DP = Decimal("0.00000001")`) so the 8dp scale has one definition site.

---

_Reviewed: 2026-06-15_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_

---
phase: 01-instrument-value-object
fixed_at: 2026-06-15T00:00:00Z
review_path: .planning/phases/01-instrument-value-object/01-REVIEW.md
iteration: 1
findings_in_scope: 10
fixed: 9
skipped: 1
status: partial
---

# Phase 01: Code Review Fix Report

**Fixed at:** 2026-06-15
**Source review:** .planning/phases/01-instrument-value-object/01-REVIEW.md
**Iteration:** 1

**Summary:**
- Findings in scope: 10 (fix_scope=all — includes Info)
- Fixed: 9
- Skipped: 1 (IN-01 — no code change required by design)

**Gate verification (post-fix, run in the isolated worktree):**
- Byte-exact oracle (`tests/integration/test_backtest_oracle.py`): **3 passed** — 134 trades / final_equity `46189.87730727451` byte-identical (check_exact=True holds).
- `poetry run mypy itrader`: **Success, no issues in 163 source files** (`--strict` clean).
- Full suite `poetry run pytest -q`: **1023 passed** (no regressions; baseline was 1023).

## Fixed Issues

### WR-01: `quantize` cash scale ignores `quote_currency` — doc/impl mismatch

**Files modified:** `itrader/core/money.py`
**Commit:** 1498048
**Applied fix:** Made the contract honest by implementing the promised derivation.
Added `_CASH_SCALES = {"USD": Decimal("0.01")}` and changed `quantize`'s `"cash"`
branch to `_CASH_SCALES.get(instrument.quote_currency, _DEFAULT_SCALES["cash"])`.
USD still resolves to `Decimal("0.01")` byte-identically (the only quote currency
this phase), so cash quantization is unchanged on the oracle path; non-USD quote
currencies now fall back cleanly to 2dp instead of silently mis-scaling. Money
stays Decimal end-to-end (string-literal scales only; no `Decimal(float)`).
**Requires human verification:** logic change to the cash-scale lookup — confirmed
byte-exact via the oracle, but flagged because it alters the rounding-scale
resolution path.

### WR-02: `_infer_price_scale` miscounts scientific-notation / trailing-garbage cells

**Files modified:** `itrader/universe/instruments.py`
**Commit:** 5bf5821 (bundled with IN-03, IN-05 — same file, interleaved edits)
**Applied fix:** Validate the fractional part is all digits before counting.
`frac = text.split(".", 1)[1]; if not frac.isdigit(): continue`. A cell like
`"1.0e-5"` (`frac == "0e-5"`) or `"12.34%"` is now skipped rather than mis-measured.
Oracle-dark path (BTCUSD is declared so inference never runs), so no oracle impact.

### WR-03: Redundant double `derive_membership` derivation in the runner

**Files modified:** `itrader/trading_system/backtest_runner.py`
**Commit:** fba186c
**Applied fix:** Added a fail-loud invariant immediately after deriving instruments
and before constructing the `Universe`: `if set(membership) != set(instruments):
raise ConfigurationError(...)`. This makes any future `derive_membership`
non-idempotency desync fail at wiring (with both symbol sets in the message) rather
than as a mid-run `KeyError` in `instrument(symbol)`. `ConfigurationError` was already
imported. Tabs preserved. No behavior change on the single-symbol oracle (sets agree).

### WR-04: `LiveTradingSystem.universe` never initialised in `__init__`

**Files modified:** `itrader/trading_system/live_trading_system.py`
**Commit:** 0f94e22
**Applied fix:** Added `self.universe: Optional[Universe] = None` alongside the other
component attributes in `__init__`, mirroring `Engine.universe: Optional[Universe] = None`
on the backtest path. A pre-`start()` read now returns a clean `None` sentinel instead
of raising `AttributeError`. `Universe` and `Optional` were already imported. Module is
mypy-deferred (`ignore_errors`); the annotation does not break the deferral (full
`mypy itrader` still clean).

### WR-05: `derive_membership` set-ordered output threads into feed.bind ordering

**Files modified:** `itrader/universe/membership.py`
**Commit:** 7f6b887
**Applied fix:** Changed `return list(set(tickers))` to `return sorted(set(tickers))`.
Makes multi-symbol `members` order deterministic regardless of `PYTHONHASHSEED`; a
single-symbol universe is its own sort (`sorted({"BTCUSD"}) == ["BTCUSD"]`), so the
byte-exact single-symbol oracle is unaffected — proven by the oracle (3 passed,
final_equity byte-identical). Docstring updated to reflect the sorted contract.

### IN-02: `Universe.members` returns the live internal list by reference

**Files modified:** `itrader/universe/universe.py`
**Commit:** 074c526
**Applied fix:** Documented the read-only-by-identity contract on the `.members`
property docstring (`returned BY IDENTITY ... READ-ONLY by contract — DO NOT mutate`).
Lowest-risk fix per the review — return type unchanged (identity required for byte-exact
`feed.bind`), so no oracle re-check risk.

### IN-03: `derive_instruments` margin/`settles_funding` ladder verbose

**Files modified:** `itrader/universe/instruments.py`
**Commit:** 5bf5821 (bundled with WR-02, IN-05)
**Applied fix:** Added a `_pick[T](value: T | None, default: T) -> T` helper (PEP 695
generic, Python 3.13) and collapsed the three repeated
`if declared is not None and declared.X is not None: ... else: ...` rungs
(`maintenance_margin_rate`, `max_leverage`, `settles_funding`) to one `_pick(...)`
call each. Identical semantics. mypy `--strict` clean on the file.

### IN-04: `Instrument.quote_currency` documented as cash-scale source but unconsumed

**Files modified:** `itrader/core/instrument.py`
**Commit:** 0c0508f
**Applied fix:** Appended a clarifying note to the `quote_currency` field docstring
describing that it is now consumed by `quantize(kind="cash")` via `_CASH_SCALES`
(WR-01), with USD -> 2dp and non-USD quote currencies not yet derived this phase.
Doc-only.

### IN-05: `_DECLARED` 8dp scales duplicate the deleted `_INSTRUMENT_SCALES` literal

**Files modified:** `itrader/universe/instruments.py`
**Commit:** 5bf5821 (bundled with WR-02, IN-03)
**Applied fix:** Introduced a single shared constant `_BTC_8DP = Decimal("0.00000001")`
and referenced it for both `price_precision` and `quantity_precision` in
`_DECLARED["BTCUSD"]`, removing two of the four magic-literal sites in this module so
the BTCUSD 8dp scale has one definition site. Value byte-identical — oracle passes.

## Skipped Issues

### IN-01: `money.quantize` has no production caller

**File:** `itrader/core/money.py:62`
**Reason:** skipped — no code change required. The review's Fix section states
"None required; note for the consuming phase (Phase 2/4) to add an integration
assertion when `quantize(..., instrument, ...)` lands on a real ledger-write path."
This is an informational forward-note, not an actionable defect. Recorded here so the
consuming phase wires the integration assertion; no source edit was made.
**Original issue:** A grep of `itrader/` finds no production call site for
`money.quantize` (only the two test modules import it); the new `Instrument`-keyed
signature is validated only by unit tests, not by the byte-exact oracle run path.

---

_Fixed: 2026-06-15_
_Fixer: Claude (gsd-code-fixer)_
_Iteration: 1_

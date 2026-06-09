---
phase: 03-minimal-real-universe
fixed_at: 2026-06-09T11:39:47Z
review_path: .planning/phases/03-minimal-real-universe/03-REVIEW.md
iteration: 1
findings_in_scope: 5
fixed: 2
skipped: 3
status: partial
---

# Phase 3: Code Review Fix Report

**Fixed at:** 2026-06-09
**Source review:** .planning/phases/03-minimal-real-universe/03-REVIEW.md
**Iteration:** 1

**Summary:**
- Findings in scope: 5 (fix_scope=all → Warning + Info)
- Fixed: 2
- Skipped: 3

All 31 phase tests remain green after the fixes
(`tests/unit/universe/`, `tests/unit/price/test_bar_feed.py`,
`tests/integration/test_universe_spans.py`), and `mypy itrader/universe`
is clean. No functional behavior on the golden single-ticker path was
changed — both fixes are defensive guard / test-robustness only, in line
with the oracle-dark / behavior-preserving phase guarantee.

## Fixed Issues

### WR-01: `is_active` raises `TypeError` on tz-mixed inputs with no defensive guard

**Files modified:** `itrader/universe/membership.py`
**Commit:** 2fc6809
**Applied fix:** Added a tz-ness boundary guard inside `is_active`: if
`asof` and the span bounds disagree on tz-ness (one naive, one tz-aware),
it now raises `ValueError` with an intelligible per-ticker message instead
of letting a raw `TypeError` surface deep inside the `first <= asof <= last`
comparison. Updated the docstring (`asof` precondition + a `Raises` section)
to document the new contract. The guard propagates automatically to
`active_membership` (it delegates to `is_active`). The golden feed path is
unaffected — spans are tz-aware by construction and `asof` is a tz-aware
`pd.Timestamp`, so the new branch is never taken on the golden path.
Verified: Python `ast.parse` OK, `mypy itrader/universe` clean, 11 universe
unit tests pass.

### WR-02: Integration test mutates a private exchange attribute to exercise the path

**Files modified:** `tests/integration/test_universe_spans.py`
**Commit:** b9fa443
**Applied fix:** Added an assertion immediately after the
`simulated._supported_symbols` mutation confirming the three synthetic
tickers are now present in the supported set. If the private attribute
drifts (e.g. the supported-symbol set moves behind a config object), the
test now fails loudly at the setup line rather than silently rejecting
orders and producing a misleading downstream failure in the look-ahead
assertions. No public seam (`register_symbols(...)`/constructor arg) was
introduced — that is a larger test-support-surface change the review flags
as a "real gap... worth a small public hook" and is better deferred to the
Phase-9 E2E harness that will own a richer symbol setup; the
assert-it-took-effect option is the minimum the review explicitly endorses
for this phase. Verified: Python `ast.parse` OK, integration test passes.

## Skipped Issues

### IN-01: `active_membership` is exported and unit-tested but has zero production consumers

**File:** `itrader/universe/membership.py:124-148`
**Reason:** Skipped — accepted as a documented forward seam, exactly as the
review's own Fix note endorses ("Acceptable as a documented forward seam").
The function is already explicitly documented in its docstring as
forward-looking for the v1.3 screener (`screen(active_membership(spans, T),
ranking)`), so the lightweight-documentation outcome is already satisfied.
The only alternative the review offers is dropping `active_membership` from
the public surface until v1.3 — that would remove tested public API and is
out of scope per the task constraint (prefer documentation over removing
public API / changing behavior).
**Original issue:** `active_membership` is added, exported, and unit-tested,
but no production caller exists yet (only `is_active` is consumed by the
feed). Flagged as an intentional seam-now / consume-later pattern so it is
not mistaken for dead code.

### IN-02: Removed strategy-handler absence warning relies on an undocumented assumption that the feed always runs first

**File:** `itrader/strategy_handler/strategies_handler.py:74-76`
**Reason:** Skipped — no code change required (per the review's own Fix
note), and the optional one-line comment it suggests already exists. The
guard at `strategies_handler.py:62-73` already carries the exact link the
review asks for: "D-05: the duplicate absence warning was removed — the
feed's generate_bar_event is the single span-aware observability owner
(D-04); the strategy handler is a pure consumer." Adding another comment
would be redundant and risk the "future reader restores the warning"
confusion the note warns against. The `continue` is correctly load-bearing
and behavior is safe.
**Original issue:** Delegating absence observability entirely to the feed
makes the dependency on route ordering (TIME → feed warns → BAR →
strategies) implicit; a hand-built `BarEvent` bypassing the feed would make
a genuine mid-life gap silent in the strategy layer.

### IN-03: `csv_paths` injection widens the public constructor signature without input validation

**File:** `itrader/trading_system/backtest_trading_system.py:52,90-93`
**Reason:** Skipped — accepted for this phase, exactly as the review's Fix
note states ("Acceptable for this phase... the golden default is `None`").
The empty-dict case is already caught loudly by the
`ConfigurationError("Backtest store has no symbols ...")` at session init.
The proposed remedy — normalizing/validating ticker casing consistently
across `csv_paths` keys, strategy `tickers`, and derived membership — is an
explicit Phase-9 multi-ticker-harness concern and would change normalization
behavior, which violates the oracle-dark / behavior-preserving guarantee for
this phase. Deferred forward seam.
**Original issue:** `csv_paths` passes straight through to `CsvPriceStore`
with no `TradingSystem`-boundary validation; a strategy declaring a
lower-case ticker matching a `csv_paths` key only by case would silently
never match the store's upper-cased keys.

---

_Fixed: 2026-06-09_
_Fixer: Claude (gsd-code-fixer)_
_Iteration: 1_

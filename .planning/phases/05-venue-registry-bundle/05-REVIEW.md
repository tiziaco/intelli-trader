---
phase: 05-venue-registry-bundle
reviewed: 2026-07-12T23:27:12Z
depth: standard
files_reviewed: 34
files_reviewed_list:
  - itrader/connectors/base.py
  - itrader/connectors/provider.py
  - itrader/connectors/stream_supervisor.py
  - itrader/core/money.py
  - itrader/execution_handler/exchanges/base.py
  - itrader/execution_handler/exchanges/okx.py
  - itrader/execution_handler/exchanges/simulated.py
  - itrader/portfolio_handler/account/venue.py
  - itrader/price_handler/providers/live_provider.py
  - itrader/price_handler/providers/okx_provider.py
  - itrader/price_handler/providers/replay_provider.py
  - itrader/trading_system/live_trading_system.py
  - itrader/trading_system/system_spec.py
  - itrader/universe/universe_handler.py
  - itrader/venues/__init__.py
  - itrader/venues/assemble.py
  - itrader/venues/bundle.py
  - itrader/venues/lifecycle.py
  - itrader/venues/okx_plugin.py
  - itrader/venues/paper_plugin.py
  - itrader/venues/registry.py
  - tests/integration/test_okx_inertness.py
  - tests/unit/connectors/test_provider.py
  - tests/unit/connectors/test_stream_supervisor.py
  - tests/unit/core/test_money.py
  - tests/unit/execution/test_precision.py
  - tests/unit/price_handler/test_live_provider.py
  - tests/unit/price/test_replay_provider.py
  - tests/unit/universe/test_universe_poll.py
  - tests/unit/venues/test_assemble.py
  - tests/unit/venues/test_lifecycle.py
  - tests/unit/venues/test_okx_plugin.py
  - tests/unit/venues/test_paper_plugin.py
  - tests/unit/venues/test_registry.py
findings:
  critical: 0
  warning: 2
  info: 4
  total: 6
status: issues_found
---

# Phase 5: Code Review Report

**Reviewed:** 2026-07-12T23:27:12Z
**Depth:** standard
**Files Reviewed:** 34
**Status:** issues_found

## Summary

Phase 5 landed the venue-registry + bundle refactor: two independent registries
(`ExecutionVenueRegistry` / `DataProviderRegistry`), a shared `(venue, account_id)`
`ConnectorProvider` memo, a `VenueBundle` value object, concrete OKX + paper plugins,
a `VenueLifecycle` orchestrator, an `assemble_venue` delegation seam, the uniform
`LiveDataProvider` surface, and the extraction of the reconnect ladder into one shared
`StreamSupervisor`. It also relocated `precision_to_scale` into `core/money.py` and
added the `AbstractExchange.resolve_precision` capability.

Against the locked project invariants the code is strong. I verified all four:

- **Money-Decimal:** no `Decimal(<float>)` and no float-money arithmetic in any changed
  file; every venue edge crosses via `to_money(str(x))`; the only `Decimal(...)` literals
  are string/int-literal forms (`Decimal("0")`, `Decimal(1).scaleb(...)`).
- **OKX import-inertness:** the `venues/` barrel re-exports only Protocols/value objects;
  both plugin modules keep every ccxt/OKX/SQL import inside `build*` bodies; the LTS venue
  wiring lazy-imports the plugins inside `__init__`. `test_okx_inertness.py` extends the
  `_FORBIDDEN` set with `venues.okx_plugin` / `venues.paper_plugin` and the register-vs-build
  probe, and the plugin unit tests AST-assert module-scope import purity.
- **Determinism:** no wall-clock money/time on the deterministic path; the single
  `datetime.now(UTC)` in `okx_provider` is the documented live-only control-plane
  `BarsLoadFailed` stamp (oracle-inert).
- **Indentation:** per-file matches — `venues/` and `connectors/` new modules are 4-space,
  `execution_handler/exchanges/okx.py` stays tabs; no mixed-indent diff observed.

The `StreamSupervisor` extraction is especially well-covered: the donor-diff matrix,
classification ladder, ceiling-halt, clean-return policy, and the secret-scrub invariant
are all tested. No BLOCKER-class defect was found. The findings below are two robustness /
maintainability WARNINGs and four INFO notes.

## Warnings

### WR-01: Duplicated paper-parity anchor reintroduces the drift risk D-18 removed

**File:** `itrader/venues/paper_plugin.py:36-39` (and `itrader/trading_system/live_trading_system.py:86-93`)
**Issue:** The four parity-anchor constants are now defined as **independent literals in
two modules**:

- `venues/paper_plugin.py:36-39` — `ReplayDataPlugin.build_provider` builds the **actual**
  replay store (`CsvPriceStore(start_date=..., end_date=...)`) from *this* copy.
- `live_trading_system.py:86-93` — the `run_paper_replay()` window/timeframe guard
  (`live_trading_system.py:1455-1481`) validates against *this* copy, and
  `tests/integration/test_paper_parity.py:49-62` imports the comparand from *this* copy.

D-18 was explicitly "SINGLE SOURCE OF TRUTH … so paper/backtest parity can never silently
desync," and the paper_plugin header even calls the LTS constants "their canonical home"
— then re-declares the literals instead of importing them. The result: a change to the
plugin's values (the store actually replayed) that is not mirrored into the LTS values
desyncs the parity comparand from the store. The `run_paper_replay()` guard would catch a
store-vs-LTS mismatch *only when that entry point is run*; the parity test itself asserts
against the LTS copy, so a plugin-only edit makes the test compare against a window the
replay store no longer uses. This is precisely the WR-02 "coincidental parity" failure
mode D-18 was created to eliminate.
**Fix:** Collapse to one definition. Either have `paper_plugin` import the four constants
from a single shared home, or extract them into a tiny constants module both `paper_plugin`
and `live_trading_system` import:
```python
# itrader/venues/paper_plugin.py
from itrader.trading_system.parity_anchor import (   # single source
    PAPER_PARITY_START_DATE, PAPER_PARITY_END_DATE,
    PAPER_PARITY_SYMBOL, PAPER_PARITY_TIMEFRAME,
)
```
(A dedicated `parity_anchor` module avoids the paper_plugin→live_trading_system circular
import and keeps the anchor inertness-free.)

### WR-02: `ConnectorProvider.close_all` strands remaining connectors if one `disconnect()` raises

**File:** `itrader/connectors/provider.py:79-83`
**Issue:**
```python
def close_all(self) -> None:
    for connector in self._memo.values():
        connector.disconnect()   # raises -> loop aborts
    self._memo.clear()           # never reached
```
If any memoized `connector.disconnect()` raises, the loop propagates, the remaining
connectors are never disconnected, and `self._memo.clear()` never runs — leaking
authenticated venue sockets / asyncio loops (a `ResourceWarning` under the strict suite,
a dangling venue session in production). The exception does surface into
`LiveTradingSystem.stop()`'s `finally` (`live_trading_system.py:1938-1942`, log-and-swallow),
but by then the fan-out is already half-torn-down. Impact is bounded today (single
`('okx','default')` connector), but this class's entire justification is multi-builder /
future per-account (`account_id`) sharing of *many* connectors, where the gap becomes real.
**Fix:** Isolate each disconnect and always clear the memo:
```python
def close_all(self) -> None:
    try:
        for connector in self._memo.values():
            try:
                connector.disconnect()
            except Exception:
                self._logger.error("connector disconnect failed", exc_info=True)
    finally:
        self._memo.clear()
```
(A per-connector try/except mirrors the per-symbol isolation already used in
`OkxExchange.catch_up_missed_fills` and the universe add-loop.)

## Info

### IN-01: `VenueLifecycle.stop()` bundle-connector fallback branch never runs in production

**File:** `itrader/venues/lifecycle.py:87-90`
**Issue:** `assemble_venue` (`assemble.py:78`) always constructs the lifecycle with
`connectors=connectors`, so `stop()` always takes the `self._connectors.close_all()`
branch. The `elif self._bundle.connector is not None: self._bundle.connector.disconnect()`
fallback is reachable only when `connectors=None`, which the production seam never passes —
it is exercised solely by `test_lifecycle.py::test_stop_disconnects_bundle_connector_without_provider`.
Not a bug (defensive API completeness), but the fallback is dead on every real run.
**Fix:** Either document it as test-only defensive code, or drop the `connectors` optionality
if no production caller will ever omit it.

### IN-02: `VenueBundle.account_factory` signatures diverge; the documented "uniform call" never occurs

**File:** `itrader/venues/okx_plugin.py:101` and `itrader/venues/paper_plugin.py:72`
**Issue:** OKX's factory is `(*args, **kwargs) -> VenueAccount`; paper's is
`(portfolio, initial_cash=0.0) -> Account`. The bundle/OKX comments claim args are absorbed
"so the 05-06 `assemble_venue` can call this uniformly with the paper factory," but
`assemble_venue` never invokes `account_factory` — only `LiveTradingSystem` does, and only
on the OKX branch as `bundle.account_factory()` (`live_trading_system.py:566`). The paper
factory is therefore built but never called in the live flow, and the "uniform" contract is
unenforced: a future uniform caller invoking `account_factory()` on a paper bundle would
raise `TypeError` (missing `portfolio`).
**Fix:** Align the two factory signatures (paper also absorbing `*args, **kwargs` with
internal keyword extraction), or drop the "uniform call" claim from the comments.

### IN-03: `money.quantize` unknown-`kind` fallback is dead and misleading

**File:** `itrader/core/money.py:89-93`
**Issue:**
```python
scale = {
    "price": instrument.price_precision,
    "quantity": instrument.quantity_precision,
    "cash": _CASH_SCALES.get(instrument.quote_currency, _DEFAULT_SCALES["cash"]),
}.get(kind, _DEFAULT_SCALES[kind])
```
The `.get(kind, _DEFAULT_SCALES[kind])` reads as "fall back to the default scale for an
unknown `kind`," but Python evaluates the default argument eagerly: for an unknown `kind`,
`_DEFAULT_SCALES[kind]` raises `KeyError` *before* `.get()` runs, so the graceful fallback
can never return. For the three valid kinds the primary dict always has the key, so the
default is never consulted anyway. No runtime impact (all callers pass valid kinds), but the
fallback is dead and its intent is not achieved.
**Fix:** Drop the misleading default and fail loud explicitly, e.g.
`if kind not in {"price","quantity","cash"}: raise ValueError(kind)` then a plain lookup.

### IN-04: `precision_to_scale` treats a tick size of exactly `1` as a decimal-place count

**File:** `itrader/core/money.py:118-121`
**Issue:** A ccxt TICK_SIZE-mode entry of exactly `1` (integral and `>= 1`) is interpreted
as a DECIMAL_PLACES count → `Decimal(1).scaleb(-1)` = `Decimal("0.1")`, when a tick size of
`1` should mean integer rounding (`Decimal("1")`). The docstring acknowledges the
TICK_SIZE-vs-DECIMAL_PLACES ambiguity, and OKX crypto instruments realistically never carry a
`1` tick, so this is a benign documented edge. Noted for completeness.
**Fix:** If any venue could emit a `1` tick, disambiguate on the venue's declared precision
mode rather than the value's integrality; otherwise leave as documented.

---

_Reviewed: 2026-07-12T23:27:12Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_

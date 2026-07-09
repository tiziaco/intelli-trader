---
phase: 01-config-centralization
reviewed: 2026-07-09T10:51:16Z
depth: standard
files_reviewed: 20
files_reviewed_list:
  - itrader/config/__init__.py
  - itrader/config/models.py
  - itrader/config/stream.py
  - itrader/config/system.py
  - itrader/core/enums/__init__.py
  - itrader/core/enums/system.py
  - itrader/execution_handler/exchanges/okx.py
  - itrader/execution_handler/exchanges/venue_correlation.py
  - itrader/portfolio_handler/account/venue.py
  - itrader/price_handler/feed/live_bar_feed.py
  - itrader/price_handler/providers/okx_provider.py
  - itrader/price_handler/providers/replay_provider.py
  - itrader/trading_system/live_trading_system.py
  - itrader/universe/universe_handler.py
  - tests/e2e/test_okx_sandbox_recon.py
  - tests/integration/test_okx_inertness.py
  - tests/unit/config/test_stream_settings.py
  - tests/unit/config/test_system_config.py
  - tests/unit/core/test_halt_reason.py
  - tests/unit/universe/test_universe_warmup_consumers.py
findings:
  critical: 1
  warning: 1
  info: 1
  total: 3
status: resolved
resolution: fixed_during_execution
resolved_findings: 2
resolution_note: "CR-01 (blocker) fixed in b2e88d29 (fix 01-02): DRIFT added to HaltReason. WR-01 (warning) fixed in 2c4aaac1 (fix 01-04): paper-parity timeframe decoupled from live config + WR-02 guard extended. IN-01 (info) is the documented P1 default-construct seam — no action (P5 injection)."
---

# Phase 1: Code Review Report

**Reviewed:** 2026-07-09T10:51:16Z
**Depth:** standard
**Files Reviewed:** 20
**Status:** resolved — CR-01 fixed in `b2e88d29`, WR-01 fixed in `2c4aaac1` (both verified during execution); IN-01 informational (no action)

> **Resolution (orchestrator, during phase-01 execution):** Both actionable findings were
> verified against the code and fixed before phase close. **CR-01** — `DRIFT` added to
> `HaltReason` (`halt("drift")` is a live path: `portfolio_handler.py:839` →
> `set_halt_signal(self.halt)` at `:678`); docstrings + tests corrected. **WR-01** — the
> paper-parity replay timeframe was decoupled from the live-tunable `okx_stream_timeframe`
> back to a `PAPER_PARITY_TIMEFRAME` anchor, and the `run_paper_replay` WR-02 guard was
> extended to catch timeframe drift. **IN-01** is the documented P1 default-construct seam
> (P5 injection replaces it) — no action. Gates re-verified: oracle byte-exact
> `134 / 46189.87730727451`, inertness green, full unit suite 1769 passed, mypy --strict clean.

## Summary

Reviewed the config-centralization phase: the two new Pydantic models (`StreamSettings`
/ `FeedProviderSettings`), the constant-fold rewiring that repoints the live-supervisor /
warmup / backfill / paper-parity read sites at default-constructed config instances, the
`SystemConfig` eager-`runtime` / lazy-`sql` split, the new `HaltReason` enum, and the
accompanying tests.

**Constant-fold verification (the primary risk).** I diffed every retired module constant
against its new config default. All values match byte-for-byte:
`reconnect_debounce_s=0.25`, `reconnect_backoff_base_s=1.0`, `reconnect_backoff_cap_s=30.0`,
`reconnect_retry_ceiling=6`, `okx_stream_symbol="BTC/USDC"`, `okx_stream_timeframe="1d"`,
`warmup_margin=5`, `backfill_page=1000`. Each read site (`okx.py`, `venue.py`,
`okx_provider.py`, `replay_provider.py`, `universe_handler.py`, `live_trading_system.py`,
`live_bar_feed.py`) was correctly repointed with no renamed/mis-mapped field. The
`halt('baseline-residual')` → `halt(HaltReason.BASELINE_RESIDUAL.value)` rewrite preserves
the wire string. The inertness gate stays green (`config/stream.py` imports pydantic +
stdlib only, so pulling it onto the backtest-transitive `VenueAccount` path is inert). All
15 new tests pass.

**Key concern:** the `HaltReason` enum is presented as the exhaustive typed vocabulary for
"every reachable engine halt reason," but it omits `"drift"`, which is a live, wired halt
call on the venue drift money-safety path — and the characterization test actively pins the
false invariant that `DRIFT` must NOT be a member.

## Critical Issues

### CR-01: `HaltReason` enum omits the reachable `"drift"` halt reason; docstring and test pin a false "no-drift" invariant

**File:** `itrader/core/enums/system.py:72-89` (enum); `tests/unit/core/test_halt_reason.py:48-51` (test)

**Issue:**
The enum docstring claims it is "exactly the four reasons that reach `halt()` … today. No
more, no fewer" and explicitly justifies excluding drift: *"`drift` is comment-only (no live
`halt('drift')` call)."* That premise is factually wrong.

- `itrader/portfolio_handler/portfolio_handler.py:839` calls `self._halt_signal("drift")` on
  the unexplained-beyond-band drift path (a money-safety halt).
- `itrader/trading_system/live_trading_system.py:678` wires that signal directly to the
  engine halt: `self.portfolio_handler.set_halt_signal(self.halt)`.

So `halt("drift")` is a genuinely reachable runtime call in live mode. `"drift"` is a fifth
reachable halt reason that the enum does not contain, and the enum's stated contract ("typed
vocabulary for **every reachable** engine halt reason") is violated.

Impact / why this is a BLOCKER (latent, not yet firing only because the enum is not consumed
at call sites yet — the docstring defers that to P8):
1. When P8 migrates `halt(reason: str)` to validate/construct `HaltReason(reason)`, a drift
   halt executes `HaltReason("drift")` → `ValueError: 'drift' is not a valid HaltReason`,
   crashing (or corrupting) the exact drift-detection money-safety halt it must perform.
2. The enum's T-02-01 durable-record claim ("records persisted as strings still resolve — no
   data migration") is already false for any persisted `"drift"` halt record — restart
   rehydration would fail to resolve it.
3. `test_halt_reason_excludes_drift_and_paused_on_disconnect` (line 48-51) passes today and
   cements the wrong invariant: the correct fix (adding `DRIFT`) would look like a test
   regression, so the test actively guards the bug.

Note the same drift confusion is duplicated in the `SystemStatus.HALTED` comment
(`system.py:20-22`), which lists `{drift, reconciliation-unresolved, connector-fatal,
paused-on-disconnect}` as halt reasons — inconsistent with the `HaltReason` members it sits
next to.

**Fix:** Add the reachable member and correct the docstring/test to match the true reachable
set (`drift` is a halt; `paused-on-disconnect` remains correctly excluded as a
`pause_submission` reason):

```python
class HaltReason(Enum):
    BASELINE_RESIDUAL = "baseline-residual"
    CONNECTOR_FATAL = "connector-fatal"
    RECONCILIATION_UNRESOLVED = "reconciliation-unresolved"
    DURABLE_HALT = "durable-halt"
    DRIFT = "drift"  # portfolio_handler.py:839 self._halt_signal("drift") -> LiveTradingSystem.halt
```

```python
# tests/unit/core/test_halt_reason.py
def test_halt_reason_has_exactly_the_reachable_members():
    assert set(HaltReason.__members__) == {
        "BASELINE_RESIDUAL", "CONNECTOR_FATAL",
        "RECONCILIATION_UNRESOLVED", "DURABLE_HALT", "DRIFT",
    }

def test_halt_reason_excludes_paused_on_disconnect():
    # paused-on-disconnect is a pause_submission reason, NOT a halt.
    assert "PAUSED_ON_DISCONNECT" not in HaltReason.__members__
```

If the intent really is a deferred/minimal set, the docstring must stop asserting
completeness ("every reachable halt reason") and the test must not assert `DRIFT` is
absent — otherwise the artifact encodes a claim its own codebase contradicts.

## Warnings

### WR-01: Paper-parity replay timeframe is now coupled to the live-tunable `okx_stream_timeframe`, and the parity-drift guard does not check timeframe

**File:** `itrader/trading_system/live_trading_system.py:645-648` (paper wiring); `:1514-1524` (parity guard)

**Issue:**
The rewiring retired the independent `_PAPER_STREAM_TIMEFRAME = "1d"` constant and now sources
the paper replay timeframe from the live-venue field:

```python
self._replay_provider = ReplayDataProvider(
    store=CsvPriceStore(start_date=PAPER_PARITY_START_DATE, end_date=PAPER_PARITY_END_DATE),
    symbol=PAPER_PARITY_SYMBOL,
    timeframe=_STREAM_SETTINGS.okx_stream_timeframe)   # was _PAPER_STREAM_TIMEFRAME
```

`okx_stream_timeframe` is documented (config/stream.py:48-51) as the **live OKX stream
target** — a supervisor tunable meant to become injectable at the P5 composition root. The
paper-parity replay grid is a **byte-exact golden anchor** ("1d") that must never drift from
the backtest. These are two independent concerns now folded onto one field: once P5 injects a
tuned `StreamSettings` (e.g. `okx_stream_timeframe="1h"` for a live run), the paper-parity
replay silently changes its bar grid.

Worse, the `run_paper_replay` window-drift `ConfigurationError` guard (`:1514-1524`) compares
only `start_date`, `end_date`, and `_symbol` — it does **not** check timeframe. So a timeframe
drift introduced through this coupling slips past the very guard designed to catch
parity-window drift, and would surface only as a downstream parity-count mismatch (the failure
mode the guard exists to pre-empt).

Today the value is always `"1d"` (everything default-constructs the same `StreamSettings`), so
this is latent, not live — hence WARNING not BLOCKER. But the coupling is a correctness trap
seeded by this phase.

**Fix:** Keep the paper-parity timeframe anchored to a parity-owned constant (co-located with
`PAPER_PARITY_SYMBOL` / `PAPER_PARITY_START_DATE`), not the live stream field:

```python
PAPER_PARITY_TIMEFRAME = "1d"   # golden grid — independent of the live stream tunable
...
    timeframe=PAPER_PARITY_TIMEFRAME)
```

and add the timeframe to the parity-drift guard so any future drift fails loud there.

## Info

### IN-01: Config models are default-constructed at each read site rather than shared

**File:** `itrader/price_handler/feed/live_bar_feed.py:283`; `itrader/price_handler/providers/okx_provider.py:640,681`; `itrader/universe/universe_handler.py:460`; `itrader/price_handler/providers/replay_provider.py:162`

**Issue:** `FeedProviderSettings()` / `StreamSettings()` are freshly instantiated on each call
(e.g. `self.cache_capacity() + FeedProviderSettings().warmup_margin` inside `warmup`, and per
`fetch_ohlcv_backfill` call). This is the documented "P1 seam" (a default-constructed instance
until P5 injects a shared instance at the composition root), so it is intentional and
low-impact — noted only so the P5 injection work replaces every per-call construction with the
injected instance and does not leave a mix of injected-vs-default readers (which would re-open
the value-drift risk the phase closed).

**Fix:** At P5, inject one shared `StreamSettings` / `FeedProviderSettings` through the
composition root and hold it on the instance (`self._feed_cfg`), replacing the per-call
`FeedProviderSettings()` / `StreamSettings()` constructions.

---

_Reviewed: 2026-07-09T10:51:16Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_

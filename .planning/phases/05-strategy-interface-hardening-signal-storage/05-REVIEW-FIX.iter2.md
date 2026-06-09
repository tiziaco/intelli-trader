---
phase: 05-strategy-interface-hardening-signal-storage
fixed_at: 2026-06-09T19:19:04Z
review_path: .planning/phases/05-strategy-interface-hardening-signal-storage/05-REVIEW.md
iteration: 1
findings_in_scope: 11
fixed: 10
skipped: 1
status: partial
---

# Phase 05: Code Review Fix Report

**Fixed at:** 2026-06-09T19:19:04Z
**Source review:** .planning/phases/05-strategy-interface-hardening-signal-storage/05-REVIEW.md
**Iteration:** 1

**Summary:**
- Findings in scope: 11 (fix_scope: all — 5 warnings + 6 info)
- Fixed: 10
- Skipped: 1

All 10 fixed findings verified by re-read + AST parse. Behavioral changes were
additionally validated by running the strategy unit suite (21 passed) and the
oracle/smoke integration tests (4 passed) — the golden `SMA_MACD` backtest path
is byte-unchanged.

## Fixed Issues

### WR-01: `unsubscribe_portfolio` raises on already-unsubscribed id; `subscribe_portfolio` allows duplicate fan-out

**Files modified:** `itrader/strategy_handler/base.py`
**Commit:** 26934fd
**Applied fix:** Made both operations idempotent. `subscribe_portfolio` now
guards the append with an `in` check (preventing double fan-out → two
SignalEvents / two orders for one decision); `unsubscribe_portfolio` guards the
remove (no more `ValueError` on a benign double-unsubscribe). Verified against
the existing subscribe/unsubscribe tests (test_strategy.py) — all green.

### WR-02: `InMemorySignalStore.add` silently overwrites on `signal_id` collision

**Files modified:** `itrader/strategy_handler/storage/in_memory_storage.py`
**Commit:** 1f65987
**Applied fix:** `add` now raises `ValueError(f"duplicate signal_id: ...")`
before writing if the id already exists, honoring the documented "insertion
order / one record per intent" (D-09) contract instead of a silent upsert that
would corrupt count and ordering. Signal-store unit tests still pass.

### WR-03: Live system constructs a `SignalStore` but neither retains nor exposes it

**Files modified:** `itrader/trading_system/live_trading_system.py`
**Commit:** e585c77
**Applied fix:** Promoted the local `signal_store` to `self._signal_store` and
added `get_signal_records()` / `get_signal_store()` accessors, mirroring the
backtest system (`backtest_trading_system.py:234-257`). Captured signals are now
reachable for post-run inspection in live mode.

### WR-04: `get_strategies_universe` shadows builtin `tuple`

**Files modified:** `itrader/strategy_handler/strategies_handler.py`
**Commit:** a5226f0
**Applied fix:** Renamed the comprehension loop variable from `tuple` (which
shadowed the builtin) to `pair`/`sym`. The pair-branch logic is preserved
verbatim (the declared `list[str]` config contract means it never legitimately
fires for a config-built strategy); a comment documents that it remains only for
legacy callers. (Committed together with IN-06 since both edit this file.)

### WR-05: Live event loop calls private `_dispatch` and swallows handler exceptions, bypassing the publish-and-continue seam

**Files modified:** `itrader/trading_system/live_trading_system.py`
**Commit:** bfed5df
**Applied fix:** Installed the documented live error policy by overriding the
event handler's `_on_handler_error` with a new `_publish_and_continue` method at
construction time. `EventHandler._dispatch` already routes handler exceptions
through `_on_handler_error`; the base implementation re-raises (backtest
fail-fast), so overriding it makes a failed handler emit an `ErrorEvent` onto the
queue (consumed by the ERROR route / status consumers) and keep draining —
exactly the publish-and-continue contract described in CLAUDE.md. The override
records the failure (`errors_count`), logs it, and enqueues an `ErrorEvent`
carrying the active exception (read via `sys.exc_info()`).
**STATUS: requires human verification** — this introduces a new live-mode
error-handling path with no direct automated test coverage. The logic is
syntactically sound and respects the documented seam, but a developer should
confirm the publish-and-continue behavior end-to-end (e.g. that a raising
handler produces exactly one `ErrorEvent` and the loop continues) before relying
on it.

### IN-01: `_update_status` / `_update_stats` annotate `str = None` defaults

**Files modified:** `itrader/trading_system/live_trading_system.py`
**Commit:** 0aeb72c
**Applied fix:** Changed `error_msg: str = None` → `error_msg: Optional[str] =
None` and `event_type: str = None` → `event_type: Optional[str] = None`.
`Optional` was already imported.

### IN-02: `SignalStorageFactory` rejects deferred `'live'` with `ConfigurationError` while order storage uses `NotImplementedError`

**Files modified:** `itrader/strategy_handler/storage/storage_factory.py`
**Commit:** 092930b
**Applied fix:** Aligned the deferred-backend exception type with
`OrderStorageFactory` — `create('live')` now raises `NotImplementedError`
(formerly `ConfigurationError`). `ConfigurationError` is retained for the
unknown-environment branch. No tests asserted the live-path exception type
(verified by grep), so the change is safe.

### IN-03: `to_dict()` serializes `strategy_id` (a UUID) without stringifying

**Files modified:** `itrader/strategy_handler/base.py`
**Commit:** e889893
**Applied fix:** `"strategy_id": self.strategy_id` → `"strategy_id":
str(self.strategy_id)`, making `json.dumps(strategy.to_dict())` JSON-safe and
consistent with the `.value`-serialized `order_type`/`direction` fields. No test
asserts the raw-UUID type. (Committed together with IN-04 since both edit
base.py.)

### IN-04: `subscribed_portfolios` typed `list[int]` but portfolio identity is `PortfolioId` (UUID)

**Files modified:** `itrader/strategy_handler/base.py`
**Commit:** e889893
**Applied fix:** Took the review's documented-divergence alternative rather than
flipping the type. The entire backtest path (unit tests, integration tests, the
oracle, e2e conftest) addresses portfolios by plain `int`, and the fan-out only
needs an opaque hashable handle — never a portfolio object. Flipping the
annotation to `PortfolioId` (UUID) while every caller passes `int` would create
a misleading contract in the opposite direction and risk `mypy --strict`
failures. Added a comment documenting the deliberate integer-handle choice and a
forward pointer to switch to `list[PortfolioId]` (with the subscribe/unsubscribe
signatures) when the strategy layer is wired to real UUID portfolio ids.

### IN-06: `min_timeframe` seeded with a `timedelta(weeks=100)` magic sentinel

**Files modified:** `itrader/strategy_handler/strategies_handler.py`
**Commit:** a5226f0
**Applied fix:** Initialized `self.min_timeframe` to `None` (annotated
`timedelta | None`) instead of the 100-week sentinel; `add_strategy` now sets the
baseline from the first registered strategy and `min()`s thereafter. A consumer
reading `min_timeframe` before any strategy is registered gets a clear `None`
("no strategies") instead of silent garbage. (Committed together with WR-04.)

## Skipped Issues

### IN-05: Relocated SMA_MACD exit branch gated by the bullish trend filter

**File:** `itrader/strategy_handler/strategies/SMA_MACD_strategy.py:66-72`
**Reason:** skipped: explicitly oracle-locked — the review states "No change now
(oracle-locked). Revisit at a future re-baseline." The exit-branch structure is
carried verbatim from the deleted strategy and is locked by
`test_backtest_oracle.py`; changing it would break the golden numerical
reference. The review flags it for awareness only, not for a phase-5 fix.
**Original issue:** The long EXIT (`self.sell`) is nested under the bullish entry
filter (`if short_sma >= long_sma`), so a position can only exit while the short
SMA is still above the long SMA — a latent logic smell, but behavior-preserving
and intentionally out of scope for this phase.

---

_Fixed: 2026-06-09T19:19:04Z_
_Fixer: Claude (gsd-code-fixer)_
_Iteration: 1_

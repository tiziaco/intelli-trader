---
phase: 06-liverunner-factory-facade-shrink
reviewed: 2026-07-13T13:54:40Z
depth: standard
files_reviewed: 16
files_reviewed_list:
  - itrader/trading_system/universe_wiring.py
  - itrader/trading_system/backtest_runner.py
  - itrader/trading_system/worker_supervisor.py
  - itrader/trading_system/error_policy.py
  - itrader/trading_system/live_runner.py
  - itrader/trading_system/route_registrar.py
  - itrader/trading_system/session_initializer.py
  - itrader/trading_system/live_trading_system.py
  - itrader/trading_system/__init__.py
  - itrader/universe/universe_handler.py
  - itrader/price_handler/feed/cache_registration.py
  - itrader/price_handler/feed/live_bar_feed.py
  - itrader/price_handler/providers/live_provider.py
  - itrader/price_handler/providers/replay_provider.py
  - itrader/venues/paper_plugin.py
  - scripts/run_live_paper.py
findings:
  critical: 0
  warning: 2
  info: 2
  total: 4
status: partially_resolved
resolution:
  resolved: 3   # WR-01, WR-02, IN-02
  deferred: 1   # IN-01 — folded into a design brainstorm on synthetic-signal attribution
  updated: 2026-07-13
  notes:
    - "WR-01 — resolved 2026-07-13, fast task 260713-wr1 (commit dc1f5cb8): vacuous guard deleted, replaced with a TODO for the real future-feature condition."
    - "WR-02 — resolved 2026-07-13, quick task 260713-phm (commit fe38b501): typed StateError guard added above the start() try-block."
    - "IN-02 — resolved 2026-07-13, quick task 260713-phm (commit a9f3b5ac): LiveRunner.stop() now warns when the drain thread outlives the join timeout."
    - "IN-01 — DEFERRED: not the one-line singleton swap; the fresh IDGenerator surfaced a deeper attribution concern (synthetic control-plane force-close signals get random, unattributable strategy_ids). Moved to a dedicated design brainstorm rather than a mechanical fix."
    - "Related (owner-flagged, out of original review scope) — settings-centralization anti-pattern resolved 2026-07-13, quick task 260713-ncq (commits 1c2ff039..b602f28f): StreamSettings/FeedProviderSettings + DB gate centralized under SystemConfig."
---

# Phase 06: Code Review Report

**Reviewed:** 2026-07-13T13:54:40Z
**Depth:** standard
**Files Reviewed:** 16
**Status:** issues_found

## Summary

Reviewed the Phase 06 God-object decomposition of `LiveTradingSystem` into standalone
collaborators (`LiveRunner`, `WorkerSupervisor`, `ErrorPolicy`, `SessionInitializer`,
`LiveRouteRegistrar`), the `build_live_system` factory, the shared `wire_universe`
extraction, the `UniverseHandler` promotion, and the replay-harness relocation
(`replay_provider.py` was deleted — relocated to `tests/support/`).

The prioritized risk areas came out clean:

- **Threading/concurrency** (`live_runner.py`, `worker_supervisor.py`, `error_policy.py`):
  the shared `stop_event` is cleared once in `LiveRunner.start()` and honoured by both
  the drain daemon and the poll worker; `stop_event.wait(cadence)` is a correct
  interruptible sleep; the per-thread `threading.local` replay guard in `LiveBarFeed`
  (WR-04) correctly scopes the in-replay gap classification so an engine-thread gap can
  no longer spuriously halt the connector. Single-writer engine-thread contract is
  respected (blocking venue I/O stays on the engine thread; the poll worker only does a
  thread-safe `queue.put`).
- **WR-06 error→error livelock**: `ErrorPolicy.on_handler_error` has the terminal-route
  source guard (`if getattr(event, 'type', None) is EventType.ERROR: return`) BEFORE the
  republish, so a failing `ErrorEvent` consumer cannot re-emit a fresh `ErrorEvent`. The
  guard is correct and the class is not self-referential.
- **Import-inertness**: all live/venue/SQL imports in `build_live_system`,
  `_initialize_live_session`, and `LiveRunner`/`WorkerSupervisor`/`ErrorPolicy`/
  `SessionInitializer` stay lazy inside function bodies or under `TYPE_CHECKING`. Module
  scope of `live_trading_system.py` (imported by the `trading_system` barrel) pulls no
  ccxt.pro/async/SQL. This is additionally locked by `tests/integration/test_okx_inertness.py`
  lines 195-215, which import the new surface and assert the OKX/ccxt/SQL stack is absent.
- **Oracle path** (`universe_wiring.py`, `backtest_runner.py`): the shared unit is a
  verbatim transplant; the one added call (`strategies_handler.set_universe`) is inert by
  construction; the WR-03 desync assert is a fail-loud invariant.
- **Money/determinism**: Decimal end-to-end preserved (float only at the analytics edge in
  `LiveBarFeed._base_frame`, documented convention); the poll timer's `datetime.now(UTC)`
  is the sole control-plane wall-clock stamp (never a business `time`).

Findings below are quality/robustness defects, not correctness or security failures on the
live or backtest hot path.

## Warnings

### WR-01: Subscription/membership mismatch guard is vacuous — it can never fire

> **✅ RESOLVED** 2026-07-13 — fast task `260713-wr1`, commit `dc1f5cb8`. Deleted the tautological guard (and its now-unused `ConfigurationError` import); replaced it with a TODO documenting the real condition that would warrant a genuine `subscribed ⊆ members` guard (an independent subscription source being reintroduced). Membership is the sole subscription source since 06-02/D-05, so nothing to validate today.

**File:** `itrader/trading_system/session_initializer.py:122-135`
**Issue:** The transplanted "subscription vs membership" guard derives the subscribed set
directly from `members` and then checks that subscribed set against `members`:

```python
if self._data_provider is not None and universe.members:
    members = universe.members
    subscribed = list(members)                       # copy of members
    mismatched = [s for s in subscribed if s not in members]  # ALWAYS []
    if mismatched:
        raise ConfigurationError(config_key="okx_stream_symbols", ...)
```

Because `subscribed` is literally `list(members)`, `mismatched` is unconditionally empty
and the `raise` is unreachable. The guard cannot detect the very desync it documents
(`config_key="okx_stream_symbols"` implies it once compared an independent stream-symbol
config against membership). It provides false safety assurance: a reviewer or future editor
reading the fail-loud `ConfigurationError` will believe subscription/membership divergence
is caught at wiring time, when in fact nothing is validated. The in-line comment even
mis-describes the behaviour ("fails loudly at wiring if a future edit subscribes a symbol
whose form diverges") — but a divergence can only be introduced by editing this same line.

**Fix:** Either source `subscribed` from the ACTUAL subscription input the guard claims to
protect (e.g. the real stream-symbol config / the set `start()` iterates at
`live_trading_system.py:1068`), so the comparison is meaningful:

```python
# example: compare the real subscription source against membership
subscribed = self._subscription_symbols()   # the independent stream-symbol set
mismatched = [s for s in subscribed if s not in members]
```

…or delete the guard entirely and drop the misleading comment, rather than shipping a
tautological check that reads as a live invariant.

### WR-02: `start()` dereferences `_error_policy` / `_live_runner` that are `None` unless the factory wired them — failure is masked as a generic ERROR

> **✅ RESOLVED** 2026-07-13 — quick task `260713-phm`, commit `fe38b501`. Added a typed `StateError` guard clause at the top of `start()`, placed ABOVE the `try:` block and the `STARTING` status stamp so it propagates unhandled (a hard programming-error signal) rather than being swallowed by the broad `except Exception` and masked as `SystemStatus.ERROR + return False`.

**File:** `itrader/trading_system/live_trading_system.py:1036,1196` (attrs default at `246-247`)
**Issue:** The facade uses two-phase construction: `__init__` sets
`self._live_runner = None` and `self._error_policy = None` (lines 246-247), and
`build_live_system` attaches the real objects post-construction (lines 1711-1712). But
`start()` unconditionally dereferences them:

```python
self.event_handler._on_handler_error = self._error_policy.on_handler_error   # line 1036
...
self._live_runner.start()                                                    # line 1196
```

If a `LiveTradingSystem` is ever constructed outside `build_live_system` (the class is
documented as factory-only, but nothing enforces it), both attributes are `None` and
`start()` raises `AttributeError: 'NoneType' object has no attribute 'on_handler_error'`.
That exception is swallowed by the broad `except Exception` at line 1201 and reported as a
generic `Failed to start... 'NoneType' object has no attribute ...` with
`SystemStatus.ERROR` — masking the real root cause (an un-wired runtime) behind an opaque
message and a silent `return False`.

**Fix:** Guard the runtime wiring explicitly at the top of `start()` with a typed,
descriptive error so the misuse is diagnosable rather than surfacing as a cryptic caught
`AttributeError`:

```python
if self._live_runner is None or self._error_policy is None:
    raise StateError(
        "LiveTradingSystem",
        "unwired",
        required_state="built via build_live_system() (LiveRunner/ErrorPolicy attached)",
        operation="start",
    )
```

## Info

### IN-01: `UniverseHandler` constructs a second `IDGenerator` instead of the `idgen` singleton

> **⏸️ DEFERRED** 2026-07-13 — NOT taken as the one-line singleton swap. The fresh `IDGenerator()` exists only to mint a `strategy_id` for the synthetic force-close exit `SignalEvent` (`_emit_force_close_exit`, line 728) — a control-plane-originated signal with no owning strategy. That surfaced a deeper concern beyond the convention nit: each force-close gets a **random, unattributable** `strategy_id`, which may be the wrong identity model for system-originated signals. Moved to a dedicated design brainstorm (synthetic-signal attribution / reserved sentinel identity) rather than a mechanical fix, so the singleton swap is intentionally NOT applied yet — it would be resolved together with the identity decision.

**File:** `itrader/universe/universe_handler.py:93`
**Issue:** `_idgen = IDGenerator()` constructs a fresh generator at module import for the
force-close exit signal's `strategy_id`. Project convention (CLAUDE.md — "IDs &
Determinism") is to use the process-wide `idgen` singleton (`from itrader import idgen`) and
not to stand up a second generator. This is the same UUIDv7 scheme (no determinism or
correctness impact, and this path is live-only / oracle-dark), so it is a convention nit
rather than the "second ID scheme" the constraint forbids — but it needlessly diverges from
the single-singleton idiom used elsewhere.

**Fix:** Import and use the shared singleton:

```python
from itrader import idgen
...
strategy_id=cast(StrategyId, idgen.generate_strategy_id()),
```

and drop the module-level `_idgen = IDGenerator()`.

### IN-02: `LiveRunner.stop()` reports success without verifying the drain thread actually joined

> **✅ RESOLVED** 2026-07-13 — quick task `260713-phm`, commit `a9f3b5ac`. `stop()` now checks `self._thread.is_alive()` after `join(timeout)` and emits a `logger.warning` when the daemon drain thread survives the join, so a non-joining thread is observable rather than silently advertised as STOPPED.

**File:** `itrader/trading_system/live_runner.py:214-219`
**Issue:** `stop()` sets the latch and calls `self._thread.join(timeout=timeout)` but never
checks `self._thread.is_alive()` afterward. If a handler is stuck in blocking work and the
join times out, `stop()` returns normally and the facade proceeds to `_update_status(STOPPED)`
(`live_trading_system.py:1247`) while the daemon drain thread is still alive. The lifecycle
then advertises STOPPED with a live worker — a latent shutdown-correctness gap (benign for
daemon threads at process exit, but misleading for restart/status logic).

**Fix:** Check the join result and surface a warning (and optionally propagate it) so a
non-joining thread is observable:

```python
if self._thread is not None:
    self._thread.join(timeout=timeout)
    if self._thread.is_alive():
        self.logger.warning(
            "Drain thread did not stop within %.1fs — still alive after join", timeout)
```

---

_Reviewed: 2026-07-13T13:54:40Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_

---
phase: 10-strategies-registry
reviewed: 2026-07-18T00:00:00Z
depth: standard
files_reviewed: 40
files_reviewed_list:
  - itrader/core/policy_codec.py
  - itrader/events_handler/events/universe.py
  - itrader/price_handler/feed/cache_registration.py
  - itrader/price_handler/feed/live_bar_feed.py
  - itrader/storage/strategy_registry_store.py
  - itrader/strategy_handler/base.py
  - itrader/strategy_handler/pair_base.py
  - itrader/strategy_handler/registry/__init__.py
  - itrader/strategy_handler/registry/catalog.py
  - itrader/strategy_handler/registry/config_codec.py
  - itrader/strategy_handler/registry/rehydrate.py
  - itrader/strategy_handler/strategies_handler.py
  - itrader/trading_system/live_trading_system.py
  - itrader/trading_system/route_registrar.py
  - itrader/trading_system/session_initializer.py
  - migrations/versions/p10_strategy_portfolio_subs.py
  - tests/integration/storage/test_migrations.py
  - tests/integration/test_okx_inertness.py
  - tests/integration/test_reconfigure_positions.py
  - tests/integration/test_strategy_add_warmup.py
  - tests/integration/test_strategy_external_add_lifecycle.py
  - tests/integration/test_strategy_registry_restart.py
  - tests/integration/test_strategy_remove_flat.py
  - tests/support/strategy_catalog.py
  - tests/unit/core/test_policy_codec.py
  - tests/unit/events/test_strategy_command_vocabulary.py
  - tests/unit/price_handler/test_cache_registration.py
  - tests/unit/storage/test_strategy_registry_store.py
  - tests/unit/strategy/test_config_roundtrip.py
  - tests/unit/strategy/test_is_active_gate.py
  - tests/unit/strategy/test_mark_unwarm.py
  - tests/unit/strategy/test_pair_dispatch.py
  - tests/unit/strategy/test_reconfigure_allowlist.py
  - tests/unit/strategy/test_reconfigure_atomic.py
  - tests/unit/strategy/test_rehydrate.py
  - tests/unit/strategy/test_signal_store.py
  - tests/unit/strategy/test_strategies_live_membership.py
  - tests/unit/strategy/test_strategy_command_verbs.py
findings:
  critical: 0
  warning: 2
  info: 1
  total: 3
status: issues_found
---

# Phase 10: Code Review Report (Round-2 Re-Review)

**Reviewed:** 2026-07-18
**Depth:** standard
**Files Reviewed:** 40
**Status:** issues_found

## Summary

This is the second re-review after two remediation rounds. The five round-2 fix
points were verified in detail and are **mechanically correct for their stated
goals**:

1. **Rehydrate quarantine matches the D-19 shape.** `UnwarmableTimeframeError` is in
   `_QUARANTINABLE`; a raise appends the name, fires ONE CRITICAL `alert_sink.alert`,
   logs, and `continue`s. The row is never mutated (the `deactivate_strategy()` /
   `enabled`-honoring block runs only in the success path AFTER `add_strategy`), healthy
   siblings keep loading, and `read_all()`/`strategy_name ASC` order is preserved
   (`rehydrate.py:345-354`, `:357-365`).
2. **`required_base_depth` argument order is correct.** Signature is
   `(warmup, strategy_timeframe, base_timeframe)`; the call is
   `required_base_depth(strategy.warmup, strategy.timeframe, base_timeframe)`
   (`rehydrate.py:344`), and the return is discarded (called only for its raise).
3. **The base-cadence accessor is crash-safe when the feed has no `base_timeframe`.**
   `getattr(getattr(strategies_handler, "feed", None), "base_timeframe", None)` yields
   `None` for the backtest/in-memory `BacktestBarFeed`, so the check is skipped
   cleanly — no crash, no over-quarantine (`rehydrate.py:341-344`). It is active only on
   the live `LiveBarFeed`, which exposes the `base_timeframe` property.
4. **The floor is preserved and the Protocol change is mypy-clean.**
   `max(NEWEST_BAR_ONLY, max((... for s if s.is_active), default=1))` returns `1` for
   an empty/all-deactivated/all-zero-warmup roster in both branches
   (`cache_registration.py:378-387`); pinned by
   `test_derive_warmup_depth_all_deactivated_roster_floors_at_newest_bar`. The
   `_SupportsWarmup.is_active` read-only `@property` is satisfied structurally by
   `Strategy.is_active` (a plain attribute set in `base.py:193`) under strict mypy.
5. **The new `cache_registration` module-top import in `rehydrate.py` does not break
   inertness.** `cache_registration` imports only stdlib (`collections.abc`,
   `dataclasses`, `datetime`, `typing`) — no sqlalchemy/ccxt/pandas — and `rehydrate` is
   itself lazy-imported only inside the `build_live_system` gate and never barrel-exported.

However, the round-2 **deactivated-skip** in `derive_warmup_depth` — while correct for
the floor — introduced a live-path robustness regression (WR-01) and an internal
inconsistency with the rehydrate warmability gate (WR-02). Both are below. Nothing else
new surfaced; the codec, catalog, store, migration, pair, route-registrar, and event
surfaces are clean.

## Structural Findings (fallow)

No `<structural_findings>` block was provided with this review.

## Narrative Findings (AI reviewer)

### WR-01: `derive_warmup_depth` excludes disabled strategies from live ring sizing, but `enable` has no capacity guard — re-enabling a deep disabled strategy under-provisions its warmup

**File:** `itrader/price_handler/feed/cache_registration.py:378-387` (the `is_active`
filter); `itrader/strategy_handler/strategies_handler.py:1351-1372` (the `enable` verb)

**Issue:**
The round-2 change added an `is_active` filter to `derive_warmup_depth` so
`register_strategy_warmup` sizes the `LiveBarFeed` ring from **active strategies only**.
This is pinned deliberately by `test_register_strategy_warmup_skips_deactivated_strategies`
("The deactivated 4h strategy would size the ring to 400 if counted; skipped, the single
registered consumer sizes only to the active 1h's 50").

Two problems compound:

1. **The filter is not needed for its stated purposes.** The `NEWEST_BAR_ONLY` floor is
   already guaranteed by `default=1` + the outer `max(NEWEST_BAR_ONLY, ...)` **without**
   the `is_active` filter. The other stated purpose — "a DEACTIVATED finer-than-base
   strategy can no longer raise from the ladder" (`cache_registration.py:367-370`) —
   defends an **unreachable** case: `register_strategy_warmup` (scaled branch) runs only
   from `SessionInitializer` (live-only) over the just-rehydrated roster, and
   `rehydrate_strategies` already quarantines every finer-than-base row (enabled OR
   disabled) before it can enter the roster (`rehydrate.py:341-354`). So no
   finer-than-base strategy — active or not — ever reaches the ladder, and the filter buys
   nothing.

2. **It reintroduces the silent under-provisioning that F-1 exists to prevent, on a path
   with no guard.** The ring is a `deque(maxlen=cache_capacity())` fixed at creation and
   cannot resize (`live_bar_feed.py:689`). Pre-round-2, disabled strategies inflated the
   ring, so a disabled strategy was always fully provisioned. Post-round-2, a strategy
   stored `enabled=False` at boot whose base-scaled warmup exceeds every active strategy's
   is excluded from ring sizing. When an operator later issues `enable`
   (`strategies_handler.py:1351`), the verb only `activate_strategy()` + `mark_unwarm()` +
   `_request_rewarm()` — it does **not** re-check capacity and cannot resize the ring
   (contrast the `add` gate at `:759-788` and the `reconfigure` gate at `:987-1026`, both
   of which reject `depth > capacity` loudly). The warmup fetch depth is
   `cache_capacity() + warmup_margin` (`live_bar_feed.py:308`), now sized without the
   re-enabled strategy, so its warmup is under-provisioned — a regression from the
   pre-round-2 guarantee and inconsistent with the sibling capacity gates that treat this
   under-provisioning as a correctness defect.

**Fix:** Drop the `is_active` filter from `derive_warmup_depth` so the ring is sized to the
deepest *possible* active strategy (including currently-disabled, re-enable-able ones),
restoring the pre-round-2 provisioning guarantee. The floor is already safe via
`default=1` + the outer `max`:

```python
# cache_registration.py — size to the whole roster, not active-only:
if base_timeframe is None:
    return max(NEWEST_BAR_ONLY, max((s.warmup for s in strategies), default=1))
return max(
    NEWEST_BAR_ONLY,
    max((required_base_depth(s.warmup, s.timeframe, base_timeframe)
         for s in strategies), default=1))
```

The finer-than-base concern the filter was added for is already handled by the rehydrate
quarantine (nothing unwarmable reaches the roster). Alternatively, if excluding disabled
strategies from ring sizing is intentional for memory reasons, add an explicit
`depth > capacity` reject to the `enable` verb mirroring the `add`/`reconfigure` gates so
the failure is loud, never silent. Update
`test_register_strategy_warmup_skips_deactivated_strategies` and
`test_derive_warmup_depth_skips_deactivated_unwarmable_strategy` to match the chosen
contract.

### WR-02: rehydrate quarantines a *disabled* unwarmable row instead of loading it present-but-dark — orphaning its open positions (CR-01 tension) and inconsistent with the ladder's own disabled-skip

**File:** `itrader/strategy_handler/registry/rehydrate.py:341-354`

**Issue:**
The per-instance warmability check runs `required_base_depth(...)` for **every** row
regardless of `rec["enabled"]`, inside the `_QUARANTINABLE` try. A row stored
`enabled=False` whose timeframe is unwarmable against the current base cadence (reachable
when the operator changes the subscribed stream's base cadence between restarts, or via a
seeded/legacy row) is therefore **quarantined** — skipped, alerted, and NOT registered.

This contradicts CR-01, the explicit round-1 guarantee that a disabled row loads
"present-but-dark" precisely so it retains ownership of its open positions
(`rehydrate.py:12-18`, `strategies_handler.py:1235-1239`). A quarantined disabled
strategy is never added to `self.strategies`, so its open positions become **orphaned**
(no strategy owns them out) — the exact harm CR-01 was written to prevent. A disabled
strategy cannot trade anyway (the D-07 gate stops new entries), so an unwarmable timeframe
has no trading consequence for it; quarantining it trades a loud alert for lost position
ownership.

This is also internally inconsistent with the round-2 ladder change: `derive_warmup_depth`
now *skips* `is_active == False` strategies "so a DEACTIVATED finer-than-base strategy can
no longer raise from the ladder," yet rehydrate does the opposite — it *quarantines* a
disabled unwarmable row rather than skipping the check for it.

**Fix:** Gate the per-instance warmability check on the row's enabled state so a disabled
row loads present-but-dark (retaining positions) and is only re-checked if/when it is
re-enabled (which, combined with WR-01, should carry the loud capacity reject):

```python
# rehydrate.py — only gate warmability for rows that will actually trade:
base_timeframe = getattr(
    getattr(strategies_handler, "feed", None), "base_timeframe", None)
if base_timeframe is not None and rec["enabled"]:
    required_base_depth(strategy.warmup, strategy.timeframe, base_timeframe)
```

If quarantining an unwarmable disabled row is the intended D-19 behavior, document the
position-orphaning consequence explicitly at the check site and reconcile it with CR-01's
present-but-dark contract, since the two currently read as contradictory.

## Info

### IN-01: `derive_warmup_depth` comment/docstring cites a filter benefit the rehydrate quarantine already provides

**File:** `itrader/price_handler/feed/cache_registration.py:342-359`, `:367-370`

**Issue:** The comment and docstring justify the `is_active` filter partly as preventing "a
DEACTIVATED finer-than-base strategy [from raising] from the ladder." As established in
WR-01, the scaled ladder only runs over the rehydrated roster, and rehydrate already
quarantines every finer-than-base row, so no such strategy can reach the ladder. The
justification is stale even if WR-01's filter removal is not adopted. This is documentation
drift, not a runtime defect.

**Fix:** If the filter is retained, trim the finer-than-base justification to the actual
retained behavior (excluding dark rows from ring depth); if removed per WR-01, delete the
paragraph. Keep the floor rationale (`default=1` + outer `max`), which is accurate.

---

_Reviewed: 2026-07-18_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_

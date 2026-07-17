---
phase: 10-strategies-registry
reviewed: 2026-07-17T00:00:00Z
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
  critical: 1
  warning: 2
  info: 2
  total: 5
status: issues_found
---

# Phase 10: Code Review Report

**Reviewed:** 2026-07-17T00:00:00Z
**Depth:** standard
**Files Reviewed:** 40
**Status:** issues_found

## Summary

Phase 10 adds the durable strategy-instance registry (two-table SQL schema + migration),
the `catalog x row x codec -> Strategy` rehydrate seam, the tagged-union policy/config
codecs, and the live `STRATEGY_COMMAND` verb surface (`add`/`remove`/`enable`/`disable`/
`reconfigure`/`subscribe`/`unsubscribe`/`add_ticker`/`remove_ticker`). The codecs are
carefully written (no eval/import-by-name; allowlist-gated class resolution; Decimal money
boundary via string wire form; parameterized SQL Core) and the security posture of the
external ingress (`add_event` fail-closed default-deny) is sound. Test coverage is broad,
including a full external-ingress lifecycle and restart test.

The dominant defect is a **rehydrate/persistence contract mismatch**: `enabled=False` rows
are written by two verbs on the assumption that the row survives and is reconstructed at
restart, but rehydrate loads only `enabled=True` rows (`list_active()`), so those rows are
never reconstructed. This breaks `disable`-across-restart entirely and defeats the
documented `remove` crash-safety guarantee. Two lower-severity robustness gaps and two
observations round out the review.

## Critical Issues

### CR-01: `enabled=False` strategies are persisted for restart-recovery but rehydrate never loads them

**File:** `itrader/strategy_handler/registry/rehydrate.py:272`, `itrader/storage/strategy_registry_store.py:325`, `itrader/strategy_handler/strategies_handler.py:1346-1352` and `807-858`

**Issue:**
`rehydrate_strategies` reconstructs the roster from `store.list_active()`, which is a
`WHERE enabled=True` query (`strategy_registry_store.py:340`). `read_all()` (the only query
that returns disabled rows) has **no production caller** — rehydrate is the sole boot path
and it uses `list_active`. Two verbs, however, persist `enabled=False` and explicitly rely
on the row being reconstructed at restart:

1. **`disable`** (`strategies_handler.py:1346-1352`, `1429` persist with
   `enabled=strategy.is_active` == False): the object "STAYS in `self.strategies`" for the
   current session, and the row is persisted `enabled=False` so the state survives "even if
   the process dies." But at the next boot `list_active` skips the row, so the disabled
   strategy is **not rehydrated at all**. A subsequent `enable` command then hits the
   by-name lookup in `on_strategy_command` (`:1253-1260`), finds nothing, and is a loud
   no-op — the strategy is permanently unreachable and can never be re-enabled, while its
   `enabled=False` row lingers orphaned forever. This is a normal, non-edge operation.

2. **`remove`** (`_remove_strategy_verb`, `:807-858`): the docstring (`:831-834`, `:849-853`)
   states the row is kept `enabled=False` until flat specifically so that "a crash
   mid-force-close then rehydrates the strategy and it resumes managing its own positions
   rather than orphaning them." Because rehydrate skips `enabled=False` rows, a crash during
   the pending-removal window (open positions still flattening) restarts with the position
   restored from the portfolio/order store but **no strategy object owning its exits** — the
   exact orphaned-position outcome the design claims to prevent. Any position without a
   resting exchange bracket is then unmanaged.

**Fix:**
Rehydrate must reconstruct rows that carry runtime obligations regardless of the `enabled`
flag, then apply the flag to `is_active`. For example, load all rows and set activation from
the column rather than filtering them out:

```python
# rehydrate.py — load the full roster, honor `enabled` as is_active, not as a load filter
rows = store.read_all()            # instead of store.list_active()
...
strategies_handler.add_strategy(strategy)
if not rec["enabled"]:
    strategy.deactivate_strategy()  # disabled: registered but dark, re-enable-able + owns exits
```

(Or, if only enabled strategies should trade but disabled/removing ones must still manage
open positions, add a dedicated "reconstruct-for-position-ownership" pass over the non-active
rows.) Whichever path is chosen, the `disable`/`remove` docstrings' restart-recovery
guarantees and the actual rehydrate query must be made consistent — today they contradict
each other.

## Warnings

### WR-01: `derive_warmup_depth` returns 0 for an all-zero-warmup roster, crashing `cache_capacity()`

**File:** `itrader/price_handler/feed/cache_registration.py:350-355` and `358-388`; consumer at `itrader/trading_system/session_initializer.py:133`

**Issue:**
`derive_warmup_depth` uses `max((required_base_depth(s.warmup, ...) for s in strategies),
default=1)`. The `default=1` only applies to an **empty** iterable. For a non-empty roster
whose strategies all have `warmup == 0` — a handle-free `EthBtcPairStrategy`
(`pair_base.py`, warmup derives to 0) or an `EmptyStrategy` (warmup stays 0) — every term is
`required_base_depth(0, tf, base) == 0`, so `max` returns **0**, not 1.
`register_strategy_warmup` then registers `StrategyWarmupConsumer(required_history_depth=0)`
unconditionally (`:386-388`). The next `cache_capacity()` call routes through
`derive_required_depths`, whose WR-06 guard raises `ValueError` on any depth `< 1`
(`:109-112`). Result: the live feed raises on the first bar delivery / warmup for a
handle-free-only live roster.

**Fix:** Floor the derived depth at the newest-bar minimum:

```python
# cache_registration.py::derive_warmup_depth
if base_timeframe is None:
    return max(NEWEST_BAR_ONLY, max((s.warmup for s in strategies), default=1))
return max(
    NEWEST_BAR_ONLY,
    max((required_base_depth(s.warmup, s.timeframe, base_timeframe)
         for s in strategies), default=1),
)
```

### WR-02: A live `PairStrategy` is not warmed by the `BarsLoaded` bulk-warmup path

**File:** `itrader/strategy_handler/strategies_handler.py:506-533` (`on_bars_loaded`), `itrader/strategy_handler/pair_base.py:169-222`

**Issue:**
`on_bars_loaded` warms each concerned strategy by replaying the single-symbol payload
through `strategy.update(event.symbol, bar)`. A `PairStrategy`'s spread warmth lives in
`_buf_A`/`_buf_B` and `_pair_bar_count`, which are filled ONLY by `update_pair(bar_A, bar_B)`
(both legs together) — never by the inherited single-leg `update()`. So a pair that is
rehydrated or `add`ed live (D-16 permits both) receives base bookkeeping churn from the bulk
warmup but its `is_pair_ready()` stays False; it must instead accumulate `beta_warmup +
z_lookback` (280 for the reference) **live** bars via `_dispatch_pair` before it can trade.
The `on_bars_loaded`/`is_warm` docstrings imply pairs warm through the same pipeline, so this
is a silent divergence. Because `is_warm` reports a handle-free pair as ready
(`is_ready == True`), the symbol is flipped READY and subscribed while the spread is still
cold — no wrong trade results (the `_dispatch_pair` `is_pair_ready` gate holds), but the pair
trades nothing for ~280 live bars after being added.

**Fix:** Either (a) explicitly document that live pairs warm from live bars only (not from
`BarsLoaded`) and confirm this is the accepted P10 deferral, or (b) give the bulk-warmup path
a pair-aware branch that feeds paired history through `update_pair` once both legs' warmup
windows are available. Given the two-leg-simultaneity requirement, option (a) with an explicit
note in `on_bars_loaded` is the pragmatic P10 fix; do not leave the current implied-but-unmet
"pairs use the same pipeline" contract.

## Info

### IN-01: `StrategyRegistryStore.read_all()` has no production caller

**File:** `itrader/storage/strategy_registry_store.py:356-406`

**Issue:** The FK-join `read_all()` (the only query that returns disabled rows with their
portfolio fan-out) is never called on the run path — rehydrate uses `list_active()` plus
per-strategy `portfolio_subscriptions()`. It is currently dead outside tests. If CR-01 is
fixed by switching rehydrate to `read_all()`, this becomes live; otherwise consider removing
it or documenting it as a query-only/inspection surface.

### IN-02: `add` verb requires the external payload to carry `config_version`

**File:** `itrader/strategy_handler/registry/config_codec.py:383-393`, `itrader/strategy_handler/strategies_handler.py:730-735`

**Issue:** `_add_strategy_verb` forwards the raw command `config` (minus `portfolio_id`) as
the `config_json` blob, and `decode_strategy_config` hard-requires an `int config_version`
key, rejecting the blob otherwise. This is correct for store-sourced blobs (written by
`encode_strategy_config`, which stamps the version) and the P10 tests build the `add` payload
via `encode_strategy_config`, so they pass. But a future FastAPI client that POSTs a
hand-built authoring-param dict without `config_version` will get a silent loud-no-op `add`.
Worth documenting on the `StrategyCommandEvent.add` factory that its `config` argument must
be a full `config_json`-shaped blob (version-stamped), not a bare kwargs dict — the current
factory docstring implies the latter.

---

_Reviewed: 2026-07-17T00:00:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_

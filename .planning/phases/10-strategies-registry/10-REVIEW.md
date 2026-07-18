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
  warning: 1
  info: 1
  total: 2
status: issues_found
---

# Phase 10: Code Review Report (RE-REVIEW after remediation)

**Reviewed:** 2026-07-18T00:00:00Z
**Depth:** standard
**Files Reviewed:** 40
**Status:** issues_found (prior blockers resolved; 1 new WARNING, 1 INFO)

## Summary

This is a re-review of the strategies-registry phase after remediation of the prior
review's findings (CR-01, WR-01, WR-02, IN-01, IN-02). I verified each prior finding is
resolved and did not introduce a regression, then reviewed the full scope fresh.

**All four prior findings are RESOLVED and correctly fixed — see the verification section.**
The remediation is clean: the rehydrate seam now loads the full roster via `read_all()`,
disabled rows are reconstructed present-but-deactivated (and provably do NOT trade), the
deterministic `strategy_name` ASC ordering is preserved, the WR-01 warmup-depth floor is
correct in both branches, and the inline portfolio-id consumption in rehydrate is atomic.

The fresh pass surfaced **one new WARNING** — a D-19 quarantine gap where a rehydrated
strategy with a timeframe finer than the feed base cadence crashes the boot at
`register_strategy_warmup` instead of being quarantined — and **one INFO** documenting a
benign behavioral coupling that the CR-01 fix introduces (disabled strategies now
participate in `is_warm()` aggregation and ring sizing).

## Verification of prior findings

**CR-01 (BLOCKER) — RESOLVED.** `rehydrate_strategies` now calls `store.read_all()`
(rehydrate.py:291), which returns the FULL FK-joined roster (enabled AND disabled). A
disabled row is reconstructed, subscribed, then `deactivate_strategy()`'d
(rehydrate.py:344-345). Verified no regression to trading: `calculate_signals` gates on
`if not strategy.is_active: continue` FIRST (strategies_handler.py:254), placed before both
the single-leg loop and the `_dispatch_pair` branch, so a rehydrated disabled strategy's
`update()` never runs and it emits no signals. Pinned by
`test_rehydrate_reconstructs_disabled_rows_present_but_dark` and `test_is_active_gate.py`.

**Deterministic order — PRESERVED.** `read_all()` orders by `strategy_name ASC, portfolio_id
ASC` (strategy_registry_store.py:381-384) and builds the record dict in row order, so
`list(records.values())` is name-ASC. Pinned by
`test_registration_order_follows_read_all_name_ordering` and
`test_read_all_is_deterministically_ordered`.

**Portfolio-ids inline consumption — ATOMIC (no new bug).** `build_strategy` and the
`portfolio_ids = [_resolve_portfolio_id(raw) ...]` comprehension both run inside the same
`try/except _QUARANTINABLE` block BEFORE `add_strategy` (rehydrate.py:320-334). A malformed
id raises `StrategyConfigError` (a quarantinable type) so the instance is quarantined and
never half-registered. Pinned by `test_malformed_portfolio_subscription_quarantines_the_instance`
(asserts `handler.strategies == []`).

**WR-01 (WARNING) — RESOLVED and correct.** `derive_warmup_depth` floors at
`NEWEST_BAR_ONLY` (1) in BOTH the unscaled branch (`max(NEWEST_BAR_ONLY, max(..., default=1))`,
cache_registration.py:358) and the scaled branch (:359-364). An all-zero-warmup roster
returns 1, so no `StrategyWarmupConsumer(required_history_depth=0)` can be registered to
crash `derive_required_depths`' `< 1` guard. The floor does not inflate a genuine depth
(`max(1, 100) == 100`). Pinned by
`test_derive_warmup_depth_non_empty_all_zero_warmup_floors_at_newest_bar`.

**WR-02 (doc gap) — RESOLVED.** `on_bars_loaded` carries the explicit ⚠ docstring block
(strategies_handler.py:521-527) documenting that a live `PairStrategy` is NOT warmed by the
`BarsLoaded` bulk path (its `_buf_A/_buf_B` fill only via `update_pair`), and warms instead
from live bars via `_dispatch_pair`, gated by `is_pair_ready`.

**IN-01 (dead `read_all`) — RESOLVED.** `read_all()` is now the live rehydrate path
(rehydrate.py:291); `list_active()` remains a distinct queryable surface. Not dead.

**IN-02 (add-factory config_version) — RESOLVED.** `StrategyCommandEvent.add` carries the
⚠ IN-02 docstring (universe.py:163-168) requiring a full version-stamped `config_json` blob.

## Warnings

### WR-01: Rehydrate does not quarantine a finer-than-base timeframe strategy — it crashes the boot

**File:** `itrader/trading_system/session_initializer.py:133-135`, `itrader/strategy_handler/registry/rehydrate.py:313-345`, `itrader/price_handler/feed/cache_registration.py:359-364`
**Issue:** `rehydrate_strategies` reconstructs every stored instance without any
timeframe-vs-base-cadence check — `build_strategy` has no knowledge of the feed base
cadence. After rehydrate (construction time), `SessionInitializer.initialize()` (invoked by
`start()`) calls `register_strategy_warmup(engine.feed, engine.strategies_handler.strategies,
base_timeframe=...)`, which ladders `required_base_depth(s.warmup, s.timeframe, base)` over
ALL registered strategies. If any rehydrated strategy declares a timeframe FINER than the
base cadence (or a non-whole-multiple), `required_base_depth` raises
`UnwarmableTimeframeError`, which propagates out of `register_strategy_warmup` and crashes
the entire live boot.

This defeats D-19's core promise for this one class of bad row: one unloadable strategy must
not become a self-inflicted outage. The runtime `add` and `reconfigure` verbs BOTH guard this
per-strategy with a loud no-op (`_add_strategy_verb` cache_registration gate at
strategies_handler.py:770-788; `_reconfigure_warmability_check` at :1005-1026), but rehydrate
— the one place a stored row becomes a live instance at boot — has no equivalent gate, so a
single finer-than-base row takes down every healthy sibling instead of being quarantined.

Reachability is narrow: the reference strategies are all `1d == base`, and the add/reconfigure
gates prevent a finer-than-base instance from ever being written through the normal path. The
vector is a legacy row (written by an older code version) or a hand-inserted DB row — exactly
the class of drift D-19 exists to survive.

**Fix:** Wrap the finer-than-base / non-multiple case at rehydrate in the same D-19
quarantine the codec/param failures already get. Either (a) add `UnwarmableTimeframeError` to
the `_QUARANTINABLE` tuple and perform the `required_base_depth` check inside the per-instance
`try` when a base cadence is available, or (b) make `register_strategy_warmup` skip-and-alert
an individual unwarmable strategy rather than raising for the whole roster. Concretely, in
`rehydrate_strategies`, after `build_strategy`, when the feed exposes `base_timeframe`:
```python
base_tf = getattr(getattr(strategies_handler, "feed", None), "base_timeframe", None)
if base_tf is not None:
    required_base_depth(strategy.warmup, strategy.timeframe, base_tf)  # raises -> quarantine
```
with `UnwarmableTimeframeError` added to `_QUARANTINABLE`.

## Info

### IN-01: CR-01 makes disabled strategies participate in `is_warm()` aggregation and ring sizing

**File:** `itrader/strategy_handler/strategies_handler.py:208-212` (`is_warm`), `:535-541` (`on_bars_loaded`)
**Issue:** Before CR-01, disabled rows were dropped at rehydrate, so a disabled strategy
could not influence readiness. After CR-01 a disabled strategy stays in `self.strategies`, so
it now (a) contributes its `warmup` to `register_strategy_warmup`'s max ladder, and (b) is
counted by `is_warm(symbol) = all(s.is_ready(symbol) for s in strategies if symbol in
s.tickers)`. If a disabled strategy shares a symbol with an enabled one and is not yet warm,
`is_warm(symbol)` returns False, which can gate the ENABLED sibling's readiness through
`UniverseHandler` and `calculate_signals`' `_universe.is_ready(ticker)` check.

This appears self-consistent and self-healing rather than a defect: `on_bars_loaded`
deliberately has NO `is_active` guard (strategies_handler.py:535), so it warms disabled
strategies too, and `register_strategy_warmup` sizes the ring to the max warmup over all
registered strategies (disabled included) — so the disabled sibling gets enough bars to warm
and `is_warm` resolves True. I could not construct a concrete failing path. Flagging as INFO
because it is a genuine behavioral change introduced by the CR-01 fix with no dedicated test
of the shared-symbol disabled+enabled interaction; a regression test pinning "a disabled
strategy sharing a symbol does not permanently block an enabled sibling's readiness" would
lock the invariant this now depends on.
**Fix:** Add an integration test covering an enabled strategy and a disabled strategy sharing
one symbol, asserting the enabled strategy reaches READY after warmup. No code change
required unless the test surfaces a block.

---

_Reviewed: 2026-07-18T00:00:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_

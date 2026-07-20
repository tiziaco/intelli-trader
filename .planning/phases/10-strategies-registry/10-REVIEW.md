---
phase: 10-strategies-registry
reviewed: 2026-07-18T00:00:00Z
depth: standard
files_reviewed: 39
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
  warning: 0
  info: 0
  total: 0
status: clean
---

# Phase 10: Code Review Report

**Reviewed:** 2026-07-18T00:00:00Z
**Depth:** standard
**Files Reviewed:** 39
**Status:** clean

## Summary

This is the third and final confirmation re-review of phase 10 (strategies registry)
after three rounds of remediation. The full scope was re-read at standard depth, the
round-3 end state was verified against all five acceptance criteria, and the code was
re-scanned adversarially for new defects.

**All reviewed files meet quality standards. No issues found.** The round-3 revert of the
"deactivated-skip" and the retention of the ungated rehydrate quarantine are internally
consistent, regression-free, and correctly leave the warmup ladder unable to raise at boot.

No structural pre-pass (`<structural_findings>`) was provided.

## Narrative Findings (AI reviewer)

No BLOCKER or WARNING findings. The verification of the round-3 end state follows; each
point was confirmed against the source and, where applicable, against a pinning test and a
live test run.

### Round-3 verification (all five criteria CONFIRMED)

**(1) `derive_warmup_depth` sizes from ALL strategies in both branches; no `is_active`
filter; `NEWEST_BAR_ONLY` floor preserved.**
`itrader/price_handler/feed/cache_registration.py:357-364` — both the unscaled branch
(`max(NEWEST_BAR_ONLY, max((s.warmup for s in strategies), default=1))`) and the scaled
branch (`max(NEWEST_BAR_ONLY, max((required_base_depth(s.warmup, s.timeframe, base_timeframe)
for s in strategies), default=1))`) iterate the full `strategies` iterable with no
`s.is_active` predicate and both floor at `NEWEST_BAR_ONLY` (1). The regression test
`test_derive_warmup_depth_includes_disabled_deep_strategy_provisions_ring`
(`tests/unit/price_handler/test_cache_registration.py:163-182`) pins this: a disabled deep
`100 @ 4h` strategy still sizes the ring to 400 base bars, and the stub deliberately no
longer defines `is_active`, so any re-introduced `if s.is_active` filter drops the assertion
to 50 and fails loudly.

**(2) `_SupportsWarmup` no longer carries `is_active`; mypy-strict clean.**
The Protocol (`cache_registration.py:162-183`) declares only `warmup: int` and
`timeframe: timedelta`. `mypy` run over both central modules reports
`Success: no issues found in 2 source files`.

**(3) The rehydrate quarantine catches every unwarmable row (enabled AND disabled) BEFORE
the warmup ladder runs.**
`itrader/strategy_handler/registry/rehydrate.py:363-366` resolves `base_timeframe` via
`getattr(getattr(strategies_handler, "feed", None), "base_timeframe", None)` and calls
`required_base_depth(...)` for its raise-only side effect — gated ONLY on
`base_timeframe is not None`, never on `rec["enabled"]`. This runs inside the per-instance
`try` at lines 322-366, i.e. BEFORE `add_strategy` (line 379) and BEFORE the
present-but-dark `deactivate_strategy()` (lines 386-387). Because an unwarmable row is
quarantined before registration, it never enters `self.strategies`, so the ladder — which
iterates the surviving registered roster — cannot re-encounter it. The load-bearing WR-02
comment block (lines 343-362) documents exactly why the check must stay ungated. Pinned by
`test_finer_than_base_timeframe_row_is_quarantined_at_rehydrate_not_crash_boot`
(`tests/unit/strategy/test_rehydrate.py:372-409`).

**(4) CR-01 present-but-dark loading, the D-19 quarantine shape, and backtest inertness are
intact.**
- Present-but-dark: `rehydrate.py:386-387` honors `enabled` as `is_active` via
  `deactivate_strategy()` (never as a load filter); `read_all()`
  (`strategy_registry_store.py:356-406`) LEFT-OUTER-JOINs the full roster. Pinned by
  `test_rehydrate_reconstructs_disabled_rows_present_but_dark`.
- D-19 shape: the quarantine appends the name, fires ONE CRITICAL `ErrorEvent` via
  `alert_sink.alert`, `continue`s, and never mutates the row (`rehydrate.py:367-376`).
  Deterministic order comes from `read_all()`'s `strategy_name ASC` / `portfolio_id ASC`
  (`strategy_registry_store.py:381-384`). The `_QUARANTINABLE` tuple is narrow and explicit
  (lines 105-112) so a store/driver fault still propagates loud. Pinned by
  `test_quarantine_skips_bad_rows_keeps_healthy_and_never_mutates_the_row` and
  `test_unreadable_store_propagates_and_is_not_degrade_cleaned`.
- Backtest inertness: the registry/store/rehydrate imports are lazy inside the
  `system_store is not None` gate in `build_live_system`
  (`live_trading_system.py:1600-1648`) and the registry subpackage is not barrel-exported
  (`registry/__init__.py:9-12`). `tests/integration/test_okx_inertness.py` passes.

**(5) No contradiction between the rehydrate quarantine and the warmup ladder.**
Both use the same shared `required_base_depth` boundary keyed on the same feed
`base_timeframe`. Every strategy that survives rehydrate is provably warmable (the quarantine
already raised on the unwarmable ones), so when `register_strategy_warmup` →
`derive_warmup_depth` (`session_initializer.py:133-135`) later ladders `required_base_depth`
over the surviving-and-registered roster, none can raise `UnwarmableTimeframeError`. The
rehydrate-vs-`add`/`reconfigure` asymmetry (rehydrate does raise-only, no `depth > capacity`
gate) is correct and documented: at rehydrate the ring is sized AFTER from the full survivor
set, whereas the runtime verbs face an already-fixed-`maxlen` ring.

### Fresh adversarial scan — no new defects

- Money boundary held end-to-end: `config_codec.py` and `policy_codec.py` refuse JSON floats
  for `Decimal` params and re-enter the Decimal domain only via `to_money` (string path);
  non-finite Decimals are refused on both encode and decode.
- Access control: both `resolve_strategy_class` (`catalog.py`) and `decode_policy`
  (`policy_codec.py`) resolve untrusted `strategy_type` / `kind` strings by plain dict lookup
  in an injected allowlist only — never via the import system and never by interpreting a
  blob field as source text. No injection surface introduced.
- SQL surface is parameterized Core throughout (`strategy_registry_store.py`); FK ordering
  (child-before-parent delete) is correct and enforced on both dialects; the migration's A1
  guard refuses a destructive drop of a non-empty `strategy_subscriptions` (loud over silent).
- Atomicity: `_apply_params` resolves into locals and commits only after all checks
  (`base.py:243-299`); `reconfigure` trial-constructs a throwaway before touching the live
  instance (`strategies_handler.py:1119-1163`), with the SHORT-01 direction re-gate that
  `validate()` cannot cover. The persist-then-apply asymmetry is deliberate and documented.
- No unhandled null/edge cases found in the per-tick `calculate_signals` / `_dispatch_pair`
  gap and readiness gates, the `LiveBarFeed` monotonic guard, or the `_portfolio_id_from` /
  `_resolve_portfolio_id` parse-or-reject seams.

### Test evidence (this run)

- `tests/unit/price_handler/test_cache_registration.py`, `test_rehydrate.py`,
  `test_mark_unwarm.py`, `test_is_active_gate.py`: 45 passed.
- Full `tests/unit/strategy/`, `test_strategy_registry_store.py`, `test_policy_codec.py`,
  `test_strategy_command_vocabulary.py`, `test_okx_inertness.py`: 367 passed.
- Phase-10 integration suite (`test_reconfigure_positions`, `test_strategy_add_warmup`,
  `test_strategy_external_add_lifecycle`, `test_strategy_registry_restart`,
  `test_strategy_remove_flat`, `storage/test_migrations`): 19 passed, 10 skipped (all skips
  are "PostgreSQL container unavailable" environment gates, not code defects).
- `mypy` over `cache_registration.py` + `rehydrate.py`: clean.

---

_Reviewed: 2026-07-18T00:00:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_

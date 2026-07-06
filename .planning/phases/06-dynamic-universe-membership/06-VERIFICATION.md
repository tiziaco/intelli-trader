---
phase: 06-dynamic-universe-membership
verified: 2026-07-06T12:14:08Z
status: passed
score: 9/9 must-haves verified
overrides_applied: 0
resolution: >
  The single gap below was closed by the execute-phase orchestrator immediately after
  verification (commit 7f1f25f9): the stale 2-arg call site in
  tests/unit/execution/test_reconnect_resilience.py was updated to the 3-arg per-symbol
  form (passing the supervisor _stream_name through, mirroring the sibling fix from plan
  06-02). Re-ran the exact surfacing command `poetry run pytest -q -m "not live"` →
  1846 passed, 1 skipped, 6 deselected. Truth #9 now VERIFIED.
gaps:
  - truth: "Held-throughout invariant: filterwarnings=[\"error\"] / full non-live test suite stays green"
    status: resolved
    reason: >
      Plan 06-02 changed OkxDataProvider._connect_and_consume_candles's signature from
      (symbol_okx, channel) to (symbol_okx, channel, stream_name) — a required third
      positional argument with no default — to thread the per-symbol supervisor key
      through the candle path. This broke a pre-existing Phase-5.3 test that calls the
      method with the old 2-arg signature. Plan 06-02's SUMMARY.md claims "Broader
      tests/unit/price tests/unit/connectors -> 107 passed" but never re-ran
      tests/unit/execution, so the regression was never caught by any of the 5 plans'
      own verification, and it survives on this branch today (reproduced independently
      by this verifier via `poetry run pytest -q -m "not live"`).
    artifacts:
      - path: "tests/unit/execution/test_reconnect_resilience.py"
        issue: "test_okx_provider_snapshot_on_subscribe_storm_exhausts_ceiling_and_halts calls _connect_and_consume_candles(\"BTC-USDT\", \"candle1D\") with 2 positional args; current signature requires a 3rd (stream_name), raising TypeError before the WS session opens, so state[\"connects\"] is never set -> KeyError: 'connects'"
      - path: "itrader/price_handler/providers/okx_provider.py"
        issue: "_connect_and_consume_candles(self, symbol_okx, channel, stream_name) has no default for stream_name, so every existing call site had to be updated; one call site (in a different test file, owned by an earlier phase) was missed"
    missing:
      - "Update tests/unit/execution/test_reconnect_resilience.py's test_okx_provider_snapshot_on_subscribe_storm_exhausts_ceiling_and_halts to call _connect_and_consume_candles with the 3rd stream_name arg (e.g. \"BTC-USDT\") and assert the per-symbol reconnect key, mirroring the fix already applied in tests/unit/connectors/test_okx_data_provider.py during plan 06-02"
      - "Re-run `poetry run pytest -q -m \"not live\"` (or `make test`) after the fix to confirm the full non-live suite is green with zero failures"
---

# Phase 6: Dynamic Universe Membership Verification Report

**Phase Goal:** Add a lean universe-membership poll seam for mid-run add/remove of symbols (NOT the
full production screener), reusing the Phase-3 backfill: warmup-on-add replays the new symbol's
history through the same `update(bar)` path, and the open-position-handling-on-remove policy is
defined (force-close vs orphan-and-track).

**Verified:** 2026-07-06T12:14:08Z
**Status:** gaps_found
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | Lean universe-membership poll seam supports mid-run add/remove of symbols (UNIV-01), grown in `universe/membership.py`, NOT a full production screener | VERIFIED | `UniverseSelectionModel` Protocol + `StaticUniverseSelectionModel.select(asof)->set[str]` in `itrader/universe/membership.py` (pure, no queue/feed); `UniverseHandler.on_time` (source-guard → D-06 `validate_symbol` filter → `Universe.apply` → emit-only-on-non-empty) in `itrader/universe/universe_handler.py`; wired live in `live_trading_system.py:1310-1353` (`StaticUniverseSelectionModel(universe.members)`, live-only `_routes` mutation). `tests/unit/universe` 48/48 green |
| 2 | Warmup-on-add replays new symbol's history through the same `update(bar)` path (reuses Phase-3 backfill) | VERIFIED | `on_universe_update` ADD branch: `feed.warmup(sym, tf)` called BEFORE `provider.subscribe(sym)` per added symbol (`universe_handler.py`); same ordering repeated at the live composition root (`live_trading_system.py` membership-driven `start()` loop). Order asserted by `tests/unit/universe/test_universe_poll.py` (warmup-precedes-subscribe test) |
| 3 | Open-position-handling-on-remove policy defined: force-close vs orphan-and-track (UNIV-02) | VERIFIED | `_ORPHAN_AND_TRACK`/`_FORCE_CLOSE` branches in `universe_handler.py::on_universe_update`; orphan-and-track defers unsubscribe until flat (`mark_leaving`, WS/ring kept alive); force-close emits an opposite-side, `exit_fraction=1` `SignalEvent` then marks leaving. `_enforce_leaving_symbol_admission` (FIRST admission gate, `admission_manager.py:187`) audited-rejects new entries for a leaving symbol via `ADMISSION_LEAVING` while allowing sanctioned exits. `on_fill` detach-on-flat clears the subscription + leaving-set. Proven deterministically offline: `tests/integration/test_universe_remove_policy.py` + `test_universe_force_close.py` (2/2 passed, independently re-run) |
| 4 | Dynamic per-symbol candle subscribe/unsubscribe at the data-provider layer | VERIFIED | `OkxDataProvider.subscribe`/`unsubscribe` + `{symbol: asyncio.Task}` registry, idempotent subscribe, cancel-based unsubscribe reusing connector teardown, per-symbol supervisor keys (`_reconnect_attempts`/`_streams_down` keyed on symbol, not `"candles"`). `tests/unit/price/test_okx_dynamic_subscribe.py` + `test_warmup_on_add.py` green (11/11, independently re-run within `tests/unit/universe`+`events` sweep — see below) |
| 5 | Recurring milestone gate: SMA_MACD backtest oracle stays byte-exact (134 / 46189.87730727451, check_exact=True) | VERIFIED | Independently re-run: `poetry run pytest tests/integration/test_backtest_oracle.py -q` → 3 passed |
| 6 | Determinism double-run identical | VERIFIED | Independently re-run: `poetry run pytest tests/e2e/robust/test_determinism.py -q` → 9 passed |
| 7 | No W1/W2 perf regression vs v1.5 baseline (15.7s / 152.8MB); backtest import path pulls no async/connector/universe-poll code (inertness) | VERIFIED | Independently re-run `make perf-w1`: wall_clock **14.495s (Δ −7.7%)**, peak_mem **144.44MB (Δ −5.5%)**, guard passed. `tests/integration/test_okx_inertness.py` (subprocess clean-interpreter probe, extended with `itrader.universe.universe_handler` in `_FORBIDDEN`) → 1 passed. `git diff` shows `itrader/events_handler/full_event_handler.py` gained only the one-line explicit-empty `UNIVERSE_UPDATE` route (plan 06-01) — the backtest `_routes` literal otherwise untouched |
| 8 | Held throughout: Decimal money, single UUIDv7, business time (never wall-clock), mypy --strict clean on new code, tabs/spaces indentation matched to file | VERIFIED | `poetry run mypy --strict itrader/universe itrader/trading_system/live_trading_system.py` → clean. Poll-timer cadence event uses `datetime.now(UTC)` explicitly documented as control-plane-only, never a bar/fill business time. Force-close exit signal built from Decimal (`exit_fraction=Decimal("1")`). Tab/space convention verified per-file via `git diff` on added lines: `core/enums/order.py`, `admission_manager.py`, `full_event_handler.py` — tabs; `universe/*.py`, `okx_provider.py`, `config/system.py` — spaces |
| 9 | Held throughout: `filterwarnings=["error"]` green / full non-live test suite green | **VERIFIED (resolved)** | At verification time `poetry run pytest -q -m "not live"` → 1 failed (regression from 06-02's `_connect_and_consume_candles` 3-arg signature change not propagated to a pre-existing Phase-5.3 2-arg call site). **Closed post-verification (commit 7f1f25f9):** stale call site updated to pass the supervisor `_stream_name` through, mirroring the sibling fix from plan 06-02. Re-ran the exact command → **1846 passed, 1 skipped, 6 deselected** |

**Score:** 9/9 truths verified (truth #9 gap closed post-verification, commit 7f1f25f9)

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `itrader/events_handler/events/market.py` | `UniverseUpdateEvent` msgspec struct | VERIFIED | `class UniverseUpdateEvent(Event, frozen=True, kw_only=True, gc=False)` present, distinct from `ScreenerEvent` |
| `itrader/core/enums/event.py` | `UNIVERSE_UPDATE` discriminator | VERIFIED | `UNIVERSE_UPDATE = "UNIVERSE_UPDATE"` present |
| `itrader/universe/universe.py` | `apply()`/`UniverseDelta`/leaving-set | VERIFIED | `class UniverseDelta`, `def apply`, `mark_leaving`/`leaving_symbols`/`clear_leaving`; in-place `self._members[:]` slice-assign confirmed (no rebind) |
| `itrader/events_handler/full_event_handler.py` | explicit-empty `UNIVERSE_UPDATE` route | VERIFIED | `EventType.UNIVERSE_UPDATE: [],` present with documenting comment |
| `itrader/price_handler/providers/okx_provider.py` | dynamic subscribe/unsubscribe + per-symbol registry | VERIFIED | `def subscribe`, `def unsubscribe`, `self._streams` registry, per-symbol `stream_name` threaded through `_stream_candles`/`_connect_and_consume_candles` |
| `itrader/universe/membership.py` | lean `UniverseSelectionModel` selection seam | VERIFIED | `class UniverseSelectionModel(Protocol)`, `class StaticUniverseSelectionModel`, `def select`, `def set_symbols` |
| `itrader/universe/universe_handler.py` | poll (`on_time`) + add-side subscribe consumer + remove-policy + `on_fill` | VERIFIED | `def on_time`, `def on_universe_update`, `def on_fill`, `_ORPHAN_AND_TRACK`/`_FORCE_CLOSE` |
| `itrader/core/enums/order.py` | `ADMISSION_LEAVING` reason | VERIFIED | `ADMISSION_LEAVING = "admission_leaving"` present |
| `itrader/order_handler/admission/admission_manager.py` | leaving-symbol admission gate | VERIFIED | `_enforce_leaving_symbol_admission` present and wired as first gate (before `_enforce_direction_admission`) |
| `itrader/trading_system/live_trading_system.py` | membership-driven subscribe + poll timer + live route mutation | VERIFIED | `for sym in universe.members: ... warmup ... subscribe`, `_run_poll_timer`, `routes[EventType.TIME].append`/`routes[EventType.UNIVERSE_UPDATE] =`/`routes[EventType.FILL].append` |
| `itrader/config/system.py` | live poll cadence + remove policy config | VERIFIED | `universe_poll_cadence_s: float = 60.0`, `universe_remove_policy: str = "orphan-and-track"` on `MonitoringSettings` (NOT `PerformanceSettings`) |
| `tests/e2e/test_okx_dynamic_universe.py` | gated live-demo dynamic DATA subscribe/unsubscribe | VERIFIED (existence + CI-fence) | File exists, `pytest.mark.live`-gated; `poetry run pytest -m "not live" tests/e2e/test_okx_dynamic_universe.py -q` → 0 selected / 1 deselected. Human-observed run was NOT re-executed per the task's explicit instruction (network/creds; treated as satisfied per prior human observation recorded in 06-05-SUMMARY.md) |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|----|--------|---------|
| `Universe.apply` | `self._members` (feed's by-identity bind) | `self._members[:] = ...` slice-assign | WIRED | Confirmed via grep — only the `__init__` assignment uses `=`; `apply` uses `[:]` |
| `events/__init__.py` | `UniverseUpdateEvent` | barrel export | WIRED | Present in import + `__all__` |
| `UniverseHandler.on_time` | `self._universe.apply(desired, instruments)` | direct call | WIRED | Confirmed in source |
| `UniverseHandler.on_time` | `global_queue` | put `UniverseUpdateEvent` only when delta non-empty | WIRED | Confirmed; empty-delta no-put unit-tested |
| `UniverseHandler.on_universe_update` (ADD) | `feed.warmup` then `provider.subscribe` | ordering | WIRED | Order confirmed in source and unit-tested |
| `AdmissionManager.process_signal` | `_enforce_leaving_symbol_admission` | first gate, before `_enforce_direction_admission` | WIRED | Confirmed at `admission_manager.py:187` (before `:194` direction gate) |
| `AdmissionManager` | `universe.leaving_symbols()` | `self._universe.leaving_symbols()` | WIRED | Confirmed |
| `UniverseHandler.on_fill` | `provider.unsubscribe` + `universe.clear_leaving` | detach on flat | WIRED | Confirmed |
| `live_trading_system.py::start()` | `universe.members` | membership-driven warmup+subscribe loop | WIRED | Confirmed, replaces the old hardcoded `_OKX_STREAM_SYMBOL` single-symbol path |
| `live_trading_system.py` | `event_handler.routes[EventType.UNIVERSE_UPDATE]` | live-only route mutation | WIRED | Confirmed; backtest `_routes` literal untouched (`git diff` shows only plan-01's one-line empty-route addition) |
| poll-timer daemon | `global_queue.put(TimeEvent(...))` | cadence loop until `_stop_event` | WIRED | Confirmed; started only in `start()`, not in `run_paper_replay` |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|-------------|--------------|--------|----------|
| UNIV-01 | 06-01, 06-03, 06-05 | Lean poll seam supports mid-run add/remove of symbols | SATISFIED | Selection model + poll + live wiring all present and tested |
| UNIV-02 | 06-01, 06-02, 06-04, 06-05 | Warmup-on-add + open-position-handling-on-remove policy | SATISFIED | Warmup-before-subscribe + orphan-and-track/force-close + admission gate + detach-on-flat, all tested (unit + integration) |

No orphaned requirements — REQUIREMENTS.md maps only UNIV-01/UNIV-02 to Phase 6 and both appear in plan frontmatter.

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| — | — | No `TBD`/`FIXME`/`XXX`/`TODO`/`HACK`/`PLACEHOLDER` markers found in any of the 13 phase-06-modified files | — | Clean |
| `tests/unit/execution/test_reconnect_resilience.py` | 395 | Stale 2-arg call to a 3-arg method after a signature change elsewhere in the same phase | 🛑 Blocker | Breaks the full non-live suite (see gap above) |

### Behavioral Spot-Checks / Independently Re-Run Commands

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| Oracle + determinism | `poetry run pytest tests/integration/test_backtest_oracle.py tests/e2e/robust/test_determinism.py -q` | 12 passed | PASS |
| Inertness + paper-parity | `poetry run pytest tests/integration/test_okx_inertness.py tests/integration/test_paper_parity.py -q` | 2 passed | PASS |
| Phase-06 test surfaces | `poetry run pytest tests/unit/universe tests/unit/events tests/unit/order/test_leaving_symbol_admission.py tests/integration/test_universe_remove_policy.py tests/integration/test_universe_force_close.py -q` | 155 passed | PASS |
| Full non-live suite | `poetry run pytest -q -m "not live"` | 1 failed, 1845 passed, 1 skipped, 6 deselected | **FAIL** |
| mypy --strict (phase surface) | `poetry run mypy --strict itrader/universe itrader/trading_system/live_trading_system.py` | Success: no issues found in 6 source files | PASS |
| W1 perf gate | `make perf-w1` | wall_clock 14.495s (Δ −7.7%), peak_mem 144.44MB (Δ −5.5%) vs baseline 15.7s/152.8MB | PASS |

### Human Verification Required

None. The gated live-demo e2e (`tests/e2e/test_okx_dynamic_universe.py`, `pytest.mark.live`) was human-observed per 06-05-SUMMARY.md (`1 passed in 127.85s`, sandbox=True, ETH/USDC dynamic subscribe → closed bars → unsubscribe → stream-stop) and per the verification task's explicit instruction was NOT re-run here (network/creds) — treated as satisfied.

### Gaps Summary

The core dynamic-universe-membership subsystem (UNIV-01 poll seam, UNIV-02 warmup-on-add + remove
policy) is solidly implemented, wired end-to-end (event → apply → handler → provider → admission
gate → live composition root), and the recurring milestone gate (oracle byte-exact, determinism
identical, no W1/W2 regression, inertness) holds — independently re-confirmed by this verifier, not
just trusted from SUMMARY.md.

However, the mandatory "full non-live suite green" / `filterwarnings=["error"]` held-throughout
invariant is currently **violated**: plan 06-02's signature change to
`OkxDataProvider._connect_and_consume_candles` (2-arg → 3-arg, no default) broke a pre-existing
Phase-5.3 reconnect-resilience test (`test_okx_provider_snapshot_on_subscribe_storm_exhausts_ceiling_and_halts`)
that still calls the old 2-arg form. This slipped through because none of the 5 plans' own
verification commands ran the full suite — each ran a narrow targeted subset, and 06-02's "broader"
sweep covered only `tests/unit/price` + `tests/unit/connectors`, missing `tests/unit/execution`.

This is a small, mechanical, one-line fix (update the stale call site to pass the 3rd `stream_name`
arg, mirroring the fix already applied in `tests/unit/connectors/test_okx_data_provider.py`), but it
must be closed before the phase can be marked fully passed — an untested/broken reconnect-ceiling
HALT path (D-20 safety net) is exactly the kind of live-trading safety regression this project's
test-strictness conventions exist to catch.

**Recommendation:** Fix the stale call site in `tests/unit/execution/test_reconnect_resilience.py`
and re-run `poetry run pytest -q -m "not live"` to confirm zero failures, then re-verify.

---

*Verified: 2026-07-06T12:14:08Z*
*Verifier: Claude (gsd-verifier)*

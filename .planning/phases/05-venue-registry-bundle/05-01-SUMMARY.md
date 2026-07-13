---
phase: 05-venue-registry-bundle
plan: 01
subsystem: connectors / live-stream supervision
status: complete
tags: [venue-07, cf-3, cf-4, cf-9, d-08, d-11, stream-supervisor, inertness, scrub]
requirements: [VENUE-07]
requires:
  - "itrader/config/stream.py::StreamSettings (reconnect tuning home, CFG-03/D-08)"
  - "itrader/connectors/base.py::LiveConnector (Protocol the CF-3 docstrings extend)"
provides:
  - "itrader/connectors/stream_supervisor.py::StreamSupervisor (the ONE shared reconnect ladder)"
  - "CF-9 fail-closed OkxExchange.validate_symbol (cold-cache -> False)"
affects:
  - "itrader/price_handler/providers/okx_provider.py (delegates)"
  - "itrader/portfolio_handler/account/venue.py (delegates)"
  - "itrader/execution_handler/exchanges/okx.py (delegates + CF-9)"
tech-stack:
  added: []
  patterns:
    - "Composition (has-a StreamSupervisor), not inheritance — matches MatchingEngine/Portfolio-manager ethos"
    - "Parameterized behavior-preservation (transient/fatal tuples + reconnect_on_clean_return) over 3 donor configs"
    - "Lazy ccxt + supervisor import inside __init__ keeps the module inert-by-construction"
key-files:
  created:
    - "itrader/connectors/stream_supervisor.py"
    - "tests/unit/connectors/test_stream_supervisor.py"
  modified:
    - "itrader/connectors/base.py"
    - "itrader/price_handler/providers/okx_provider.py"
    - "itrader/portfolio_handler/account/venue.py"
    - "itrader/execution_handler/exchanges/okx.py"
decisions:
  - "Kept peripheral surface DELETED (not shimmed): the arms delete _run_stream_supervisor/_escalate_connector_halt/_mark_stream_down/_on_stream_healthy/_reset_reconnect_budget + state; ~9 coupled test files were mechanically retargeted to arm._supervisor rather than kept back-compat via property shims (faithful to the plan's slimming intent)"
  - "Unified ceiling-escalation uses the transient exc when available, else RuntimeError(drop_label) — matches okx.py/venue exactly; a cosmetic okx_provider log-type divergence on the transient-ceiling path is documented below (scrub invariant preserved either way)"
metrics:
  duration_min: 29
  tasks: 3
  files_created: 2
  files_modified: 15
  completed: 2026-07-13
---

# Phase 5 Plan 01: Shared StreamSupervisor + CF-3/CF-9 Summary

One parameterized `StreamSupervisor` (`itrader/connectors/stream_supervisor.py`) now owns the
bounded-retry reconnect ladder + `_reconnect_attempts`/`_streams_down` that had been hand-copied
three times; the OKX data provider, OKX exchange, and venue-cached account arms each HAS-A
supervisor and delegate to it — with each donor's exact behavior preserved via constructor
parameters. CF-3 connector-contract docstrings were added to `LiveConnector`, and CF-9
fail-closes `OkxExchange.validate_symbol` on a cold markets cache. VENUE-07 in full.

## What shipped

- **StreamSupervisor (Task 1):** a new 4-space, ccxt-free composition class. The reconnect ladder
  is parameterized over the three donor-diff axes — `transient_exceptions` (6-type provider set vs
  ccxt-only 3-type), `fatal_exceptions`, and `reconnect_on_clean_return` (provider=True → a server
  socket-close reconnects; exec/account=False → a clean return stops). It owns the reconnect state
  and exposes `run` / `mark_down` / `mark_up` / `reset_budget` / `is_healthy` / `forget` /
  `_escalate_halt`. Exception families are constructor params, so the module imports NO ccxt and is
  inert-by-construction. Behavior preserved exactly: `CancelledError` re-raise, fatal → one
  `halt_signal("connector-fatal")`, **unclassified → fail-safe halt that NEVER falls through to the
  reconnect ladder** (T-05-03), retry-ceiling → halt (D-20), debounce + capped exponential backoff,
  and the T-05-27 scrub (`type(exc).__name__` + fixed label, never `str(exc)`; fixed halt reason).
- **CF-3 docstrings (Task 1):** additive connector-contract docstrings on `connectors/base.py::LiveConnector`
  (auth ownership, single client/loop, the call/spawn thread seam, sandbox/ws_hostname routing,
  lifecycle). No signature change — the 7 Protocol method stubs are untouched.
- **okx_provider + venue delegation (Task 2):** both 4-space arms build `self._supervisor` in
  `__init__` (lazy ccxt + supervisor import) and delegate. okx_provider keeps its WR-03 `payload_seen`
  post-snapshot gate exactly (`self._supervisor.reset_budget` only there) and its `unsubscribe`
  per-symbol teardown now calls `self._supervisor.forget`. venue's REDUCED surface is PRESERVED
  (no mark_up/reset_budget calls added; `on_up=None`) per RESEARCH Open Q1 / A2.
- **okx exchange delegation + CF-9 (Task 3):** the TABS arm delegates; the D-12 `_disconnect_ts_ms`
  catch-up floor stays ARM state, snapshotted via a new `_on_stream_down_with_floor` wrapper passed
  as the supervisor's `on_down` (the supervisor's mark_down dedup keeps it once-per-transition). CF-9:
  `validate_symbol` returns **False** when `markets` is not a loaded dict (fail-closed cold cache,
  threat T-05-04), reusing the single `validate_symbol → delta.removed` removal path — no parallel drop.

## Deviations from Plan

### Auto-fixed / blocking (Rule 3 — forced test migration the plan under-scoped)

**1. [Rule 3 - Blocking] ~9 test files coupled to the deleted arm internals were migrated.**
- **Found during:** Tasks 2 + 3.
- **Issue:** The plan's `<action>` deletes `arm._run_stream_supervisor` and the supervisor state
  fields, and its acceptance requires `grep -c "_run_stream_supervisor" == 0` in the source — but 7
  unit test files + 1 integration test + `okx_provider.unsubscribe` itself read/mutate
  `arm._run_stream_supervisor` / `_streams_down` / `_reconnect_attempts` / `_reconnect_ceiling` /
  `_on_stream_healthy` / `_mark_stream_down` / `_reset_reconnect_budget` / `_escalate_connector_halt`
  directly. "Existing tests pass unchanged" is unsatisfiable as written once those methods are deleted.
- **Fix:** Deleted the arm bodies/state (faithful to the plan's slimming intent) and mechanically
  retargeted every coupled reference to `arm._supervisor.<member>`; added a `StreamSupervisor.forget`
  method so `unsubscribe`'s per-symbol teardown had a clean encapsulated home.
- **Files modified:** tests/unit/price/test_warmup_on_add.py, tests/unit/price/test_okx_unsubscribe_marshal.py,
  tests/unit/connectors/test_okx_data_provider.py, tests/unit/execution/test_reconnect_resilience.py,
  tests/unit/execution/test_supervisor_catchall.py, tests/unit/execution/test_off_loop_halt_write.py,
  tests/integration/test_resume_gated_on_all_streams.py.
- **Commits:** 5bfe9842 (provider/venue-scope), f8e82580 (exec/cross-arm-scope).

**2. [Rule 3 - Blocking] CF-9 fail-close flipped 12 order-submit tests; seeded loaded markets.**
- **Found during:** Task 3.
- **Issue:** The submit-path preflight calls `validate_symbol`; the existing OkxExchange submit/fill
  tests use a MagicMock client whose `.markets` is not a dict, so they relied on the old fail-OPEN
  `True`. CF-9's fail-CLOSED flip rejected all of them ("unknown symbol BTC-USDT — not submitted").
- **Fix:** Seeded `client.markets = {"BTC-USDT": {}}` in the four order-submit fixtures (the two
  existing validation tests already override `.markets`, so they still assert reject/accept) and added
  a new `test_validate_symbol_fail_closed_on_cold_cache` unit case (Task 3 acceptance) proving
  cold-cache → False and warm-cache membership.
- **Files modified:** tests/unit/execution/test_okx_exchange.py, test_okx_fill_idempotency.py,
  test_missed_fill_catchup.py, test_submit_timeout_inflight.py.
- **Commit:** f8e82580.

### Documented micro-divergence (behavior-preserving, log-only)

- **Ceiling-halt log exception type, okx_provider transient path.** The three donors escalated the
  retry-ceiling with different exception objects (okx_provider used `RuntimeError(drop_label)` for
  both transient and clean paths; okx/venue used the transient `exc`). The unified ladder uses the
  transient `exc` when available, else `RuntimeError(drop_label)` — reproducing okx/venue exactly and
  okx_provider's clean-return path exactly, differing only in the exception TYPE NAME shown in the
  provider's transient-ceiling `_escalate_halt` log line (e.g. `NetworkError` vs `RuntimeError`).
  The scrub invariant (type name only, never `str(exc)`) and the halt outcome
  (`halt_signal("connector-fatal")` once, then return) are identical. No test asserts this log type;
  it is not one of the enumerated donor-diff behavioral axes.
- **mark_down / mark_up / escalate log wording is now `label`-prefixed and unified** (e.g. venue's
  "disconnected past debounce" is now "disconnected — pausing new order submission" under label
  "OKX venue"). Log wording is not a donor-diff behavioral axis; scrub + dedup + fire-once semantics
  are preserved.

## Threat mitigations applied (from `<threat_model>`)

- **T-05-01 (info disclosure):** scrub asserted by `test_scrub_no_secret_in_logs` /
  `test_scrub_reconnect_log_carries_type_not_str` — no `str(exc)` payload reaches the logs.
- **T-05-02 (DoS, reconnect ladder):** retry ceiling → halt; WR-03 payload-only budget reset preserved
  (subscribe-then-close storm still trips the ceiling).
- **T-05-03 (unclassified stream exception):** `except Exception` → fail-safe halt + return, NEVER the
  reconnect ladder — asserted per-donor by `test_unclassified_error_halts_and_never_reconnects`.
- **T-05-04 (cold markets cache):** CF-9 fail-closed `validate_symbol`, asserted by
  `test_validate_symbol_fail_closed_on_cold_cache`.
- **T-05-SC:** zero new dependencies / no poetry change; supervisor imports no ccxt.

## Verification (all green)

- `tests/unit/connectors/test_stream_supervisor.py` — 19-case parameterized 3-donor matrix.
- `tests/unit/execution tests/unit/connectors` — 303 passed.
- `tests/unit/connectors tests/unit/portfolio tests/unit/price_handler` + migrated price/ tests — green.
- Full sweep `tests/unit tests/integration` — **1997 passed, 2 skipped** (OKX demo creds absent).
- **Standing gates:** `test_backtest_oracle.py` byte-exact `46189.87730727451`; `test_okx_inertness.py`
  + `tests/unit/storage/test_import_quarantine.py` green (supervisor imports no ccxt).
- `mypy --strict` clean on all 5 touched source files.
- Source greps: `_run_stream_supervisor` == 0 across all three arms; supervisor 0 tab lines, 0 `import ccxt`;
  okx.py 0 space-indented lines (TABS preserved); base.py `def ` count unchanged.

## Follow-ups / notes

- venue's reduced stream surface (pauses-down, never resumes-up nor resets the budget) is preserved,
  not normalized — the latent question of whether it SHOULD resume-up remains RESEARCH Open Q1 (a
  separate todo, deliberately not folded into this extraction).

## Self-Check: PASSED

- Created files exist: itrader/connectors/stream_supervisor.py, tests/unit/connectors/test_stream_supervisor.py, 05-01-SUMMARY.md.
- Commits exist: 3b87666a (Task 1), 5bfe9842 (Task 2), f8e82580 (Task 3).

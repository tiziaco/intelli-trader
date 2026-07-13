---
phase: 06-liverunner-factory-facade-shrink
plan: 02
subsystem: trading_system
status: complete
tags: [RUN-02, live-runner, composition-over-inheritance, D-05, D-06, D-07, D-08, refactor]
requires:
  - "trading_system/live_trading_system.py::LiveTradingSystem (donor: _event_processing_loop, _run_poll_timer, _publish_and_continue)"
  - "events_handler/bus.py::EventBus seam"
  - "events_handler/events (UniversePollEvent, ErrorEvent, EventType)"
provides:
  - "LiveRunner — owns the live daemon-thread drain loop; composes WorkerSupervisor; injected ErrorPolicy + dispatch-gate + per-tick callbacks"
  - "WorkerSupervisor — the standalone poll-timer worker collaborator (D-05)"
  - "ErrorPolicy — the minimal live publish-and-continue seam (D-07, WR-06 guard)"
  - "itrader/trading_system/live_runner.py, worker_supervisor.py, error_policy.py"
affects:
  - "build_live_system (plan 06-05 — future consumer that wires these three and removes the old facade loop/worker/policy methods)"
  - "SafetyController (P7 — repoints the dispatch_gate callback; D-04 bodies stay in the facade until then)"
tech-stack:
  added: []
  patterns:
    - "Composition-over-inheritance runtime (D-05) — LiveRunner has-a WorkerSupervisor; the live analog of compose_engine -> Engine -> BacktestRunner"
    - "D-08 injected dispatch-gate + D-04 injected per-tick callbacks — the facade method BODIES stay put; the runner reaches them via callables"
    - "Verbatim code-motion of an inert-until-wired seam (new modules authored, old facade methods left dead-until-wired for 06-05)"
key-files:
  created:
    - itrader/trading_system/worker_supervisor.py
    - itrader/trading_system/error_policy.py
    - itrader/trading_system/live_runner.py
  modified: []
decisions:
  - "D-05: WorkerSupervisor is its OWN class (poll-timer worker); LiveRunner COMPOSES it (has-a), not inherits"
  - "D-06: LiveRunner owns the drain loop; queue_timeout/max_idle_time are injected config/spec values, not __init__ knobs the caller re-derives"
  - "D-07: ErrorPolicy is MINIMAL — _publish_and_continue moved VERBATIM (WR-06 source guard preserved); full formalization (EventHandler-construction injection, fail-fast/live split, CF-1 breaker) stays P8"
  - "D-08: LiveRunner takes an injected dispatch-gate CALLBACK (06-05 wires it to the facade's _dispatch_live; P7 repoints to SafetyController)"
  - "D-04: this plan does NOT touch the facade's safety/reconcile/stream method BODIES — live_trading_system.py is byte-untouched; the runner reaches those bodies via injected callbacks"
metrics:
  duration: "~12 min"
  completed: "2026-07-13"
  tasks: 3
  files: 3
---

# Phase 6 Plan 02: LiveRunner Runtime Engine Extraction (RUN-02) Summary

Extracted the live runtime engine — the daemon-thread drain loop, the poll-timer worker, and the handler-failure policy — out of the `LiveTradingSystem` God object into three standalone, composition-friendly collaborators authored as NEW 4-SPACE import-inert modules. `LiveRunner` owns the drain loop (ex `_event_processing_loop`), COMPOSES `WorkerSupervisor` (the ex `_run_poll_timer` worker), and takes an injected `ErrorPolicy` (the verbatim ex `_publish_and_continue`, WR-06 guard intact) plus a D-08 dispatch-gate callback and the D-04 per-tick hook callables. The classes are built but UNWIRED here — the old facade methods stay live (dead-until-wired) until `build_live_system` wires `LiveRunner` in plan 06-05. Per D-04 the facade `live_trading_system.py` is **byte-untouched** this plan (empty diff since the wave base), so P7 extracts the safety/reconcile bodies from an unchurned baseline.

## What Was Built

- **`itrader/trading_system/worker_supervisor.py`** (new, 4-SPACE) — `class WorkerSupervisor` owning the dynamic-universe poll-timer daemon (D-05). Constructor injects the `bus` (EventBus), the shared `stop_event`, and the poll `cadence` seconds (read from `monitoring.universe_poll_cadence_s` by the caller — NOT a module literal). `_run_poll_timer` is the VERBATIM donor body (`live_trading_system.py:1852-1873`): `bus.put(UniversePollEvent(time=datetime.now(UTC)))` every cadence, `stop_event.wait(cadence)` as the interruptible sleep. `start()`/`stop()` manage the daemon thread (the thread-creation ex `:1836-1841`). The control-plane-only wall-clock / Pitfall 3 determinism comments are preserved.
- **`itrader/trading_system/error_policy.py`** (new, 4-SPACE) — `class ErrorPolicy` exposing `on_handler_error(self, event, handler) -> None` (the signature `EventHandler._on_handler_error` expects). The `_publish_and_continue` body (`:622`) is transplanted VERBATIM: read the active exception via `sys.exc_info()`, log, construct the `ErrorEvent` (same fields/severity), `bus.put(...)`, return so draining continues. **The WR-06 source guard is preserved exactly** — an `ErrorEvent` whose own consumer failed is NOT republished (`if getattr(event, 'type', None) is EventType.ERROR: return`). The publish target `bus` is an injected constructor dependency; an optional `error_counter` callback preserves the facade's `_stats['errors_count']` bookkeeping when wired. Docstring cites D-07 (minimal seam; full formalization is P8).
- **`itrader/trading_system/live_runner.py`** (new, 4-SPACE) — `class LiveRunner` that OWNS the daemon-thread drain loop transplanted from `_event_processing_loop` (`:1526-1608`). Pure-injection constructor (no facade back-reference): `bus`, `stop_event`, `error_policy: ErrorPolicy` (HELD for the 06-05 wiring layer that installs it on the EventHandler — the loop itself does NOT install the monkeypatch), `worker_supervisor: WorkerSupervisor` (composed, D-05), `dispatch_gate: Callable` (D-08), the D-04 per-tick hooks (`update_stats`, `record_bar_metrics`, `resume_after_reconnect`, `halt_after_connector_fatal`), `queue_timeout`/`max_idle_time` (injected config values, D-06), and two optional lifecycle hooks (`on_loop_start`, `on_loop_error`). `_run_loop` mirrors the donor verbatim (get→dispatch_gate→hooks; queue.Empty branch: resume/halt drains + idle-time warn; loop catch-all). `start()` clears the shared `stop_event` once, spawns the drain daemon, and starts the supervisor; `stop()` sets the latch, joins the thread, and stops the supervisor.

## Oracle / Gate Results (the per-PLAN gate on the milestone's highest oracle risk)

- **OKX import-inertness: PASS** — `tests/integration/test_okx_inertness.py` 3 passed. The three new modules pull no `ccxt.pro` / async / SQL onto the backtest import path (they import only stdlib `threading`/`queue`/`datetime` + the events package + the `EventBus` seam + the two siblings). `trading_system/__init__.py` was NOT touched — no eager barrel re-export of the new modules.
- **Backtest oracle byte-exact: PASS** — `tests/integration/test_backtest_oracle.py` 3 passed → 134 trades / final equity `46189.87730727451` (frozen `tests/golden/summary.json`). This plan is live-only / backtest-dark, so the oracle is unchanged by construction.
- **Paper-parity: PASS** — `tests/integration/test_paper_parity.py` 1 passed.
- **mypy --strict: clean** — `Success: no issues found in 248 source files` (245 → 248, +3 new modules).
- **Full suite: green** — `poetry run pytest tests` → 2125 passed, 6 skipped (all OKX-credential-gated opt-in live suites; no credentials in this env). `filterwarnings=["error"]` held — zero new warnings.
- **Zero new dependencies** — no `poetry`/`pyproject.toml` change.

## Grep / Structural Acceptance

- `WorkerSupervisor`: `grep -c "UniversePollEvent"` → 5 (>=1); cadence is a constructor arg (no module literal); 0 tab-indented body lines (4-SPACE).
- `ErrorPolicy`: importable; `grep -ci "wr-06|source guard|ErrorEvent"` → 12 (>=1) and the emit path is guarded by `event.type is EventType.ERROR`; bus injected; 0 tab-indented lines.
- `LiveRunner`: importable; `grep -c "WorkerSupervisor|worker_supervisor"` → 10 (composes, has-a; does not subclass a runner base); `grep -c "def _dispatch_live|def _maybe_resume_after_reconnect|def _record_bar_metrics"` → **0** (D-04 bodies NOT duplicated); `queue_timeout`/`max_idle_time` injected (not module literals); 0 tab-indented lines.
- **Facade untouched (D-04):** `git diff <wave-base> -- itrader/trading_system/live_trading_system.py` → empty (byte-untouched).

## Deviations from Plan

None material — plan executed as written. One structural design choice worth recording: LiveRunner's constructor adds two **optional** lifecycle callbacks (`on_loop_start`, `on_loop_error`) beyond the four per-tick hooks the plan enumerated. These carry the donor loop's loop-entry facade bookkeeping (`_update_status(RUNNING)` + `_stats['uptime_start']` stamp) and the loop catch-all (`_stats['errors_count'] += 1`) as injected callbacks — the same D-04 injected-callback discipline the plan mandates for the per-tick hooks, applied to the two non-per-tick facade side-effects the drain loop also performs. This keeps the facade the source of truth for status/stats (no LiveRunner import of `SystemStatus`) and keeps the constructor stable for 06-05. Similarly, `ErrorPolicy` takes an optional `error_counter` callback to preserve the facade's `errors_count` increment when wired; both default to no-op so the modules stay standalone here.

## Known Stubs

None. The three modules are complete and self-contained; they are intentionally UNWIRED (dead-until-wired) — `build_live_system` (plan 06-05) is the designated consumer that composes and wires them and removes the superseded facade methods. This is not a stub: the old `_event_processing_loop`/`_run_poll_timer`/`_publish_and_continue` remain the live path until 06-05, so behavior is unchanged this plan.

## Threat Flags

None new. The plan threat register is satisfied: T-06-03 (WR-06 guard loss → error→error livelock) mitigated by the verbatim move + the guard grep + the full suite (WR-06 terminal-safety tests) green; T-06-04 (import DoS) mitigated by inertness green; T-06-05 (LiveRunner re-implementing a D-04-frozen body) mitigated by the `grep → 0` on the forbidden method defs + the byte-untouched facade; T-06-SC zero new dependencies.

## Notes for Downstream

- **06-05 (`build_live_system`) is the wiring consumer.** It constructs `WorkerSupervisor(bus, stop_event, cadence)`, `ErrorPolicy(bus, error_counter=...)`, and `LiveRunner(...)` with the facade's `_dispatch_live` as `dispatch_gate`, the `_maybe_*`/`_record_bar_metrics`/`_update_stats` methods as the per-tick hooks, `_update_status(RUNNING)`+uptime stamp as `on_loop_start`, and the `errors_count` increment as `on_loop_error`/`error_counter`. It then installs `error_policy.on_handler_error` on the EventHandler (replacing the `_publish_and_continue` monkeypatch) and removes the three superseded facade methods.
- **P7 (SafetyController)** repoints the `dispatch_gate` callback to the SafetyController; the D-04 method bodies stay in the facade until then, so P7 works from an unchurned baseline.
- **P8** formalizes ErrorPolicy: EventHandler-construction injection (removing the monkeypatch), the backtest fail-fast / live publish-and-continue split behind one interface, and the CF-1 aggregate error-rate breaker.

## Self-Check: PASSED

- FOUND: `itrader/trading_system/worker_supervisor.py`
- FOUND: `itrader/trading_system/error_policy.py`
- FOUND: `itrader/trading_system/live_runner.py`
- FOUND commit `1478a1f7` (Task 1 — WorkerSupervisor)
- FOUND commit `870854c4` (Task 2 — ErrorPolicy)
- FOUND commit `6a8b914b` (Task 3 — LiveRunner)

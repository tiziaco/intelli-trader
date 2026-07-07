---
phase: 02-okx-connector
plan: 02
subsystem: connectors
tags: [asyncio, ccxt-pro, okx, sandbox-routing, daemon-thread, protocol, transport]

# Dependency graph
requires:
  - phase: 02-okx-connector
    plan: 01
    provides: "LiveConnector session/transport Protocol (call/spawn/client/sandbox/connect/disconnect) + OkxSettings SecretStr credential layer + async mocked-ccxt conftest"
provides:
  - "OkxConnector — the shared authenticated session/transport primitive: one asyncio loop on a daemon thread, one ccxt.pro client built inside the loop, one sandbox bool, call/spawn scheduling bridge, connect/disconnect lifecycle with stream-task tracking + cancel"
  - "Single-bool sandbox routing: set_sandbox_mode(True) (REST header + ccxt WS host swap to wspap) AND the exposed sandbox flag for the native data socket — no split-brain (CONN-03)"
  - "OkxConnector exported from the connectors barrel (D-04); satisfies LiveConnector structurally"
affects: [02-03-order-arm, 02-04-data-arm, 02-05-native-candle, 03-livebarfeed, 05-real-sandbox-recon]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "loop-on-a-daemon-thread + ccxt.pro client built INSIDE the loop (Pitfall 3: ccxt.pro binds sockets to its creating loop); every venue op bridged via run_coroutine_threadsafe"
    - "single sandbox: bool drives ccxt routing (set_sandbox_mode) AND is exposed for the native socket — one knob, no header-for-WS split-brain (CONN-03 / D-02 correction)"
    - "nautilus-mirrored stream-task set: spawn tracks watch_* tasks, disconnect cancels-all + awaits gather before tearing down the loop"

key-files:
  created:
    - itrader/connectors/okx.py
    - tests/unit/connectors/test_okx_connector.py
  modified:
    - itrader/connectors/__init__.py

key-decisions:
  - "Sandbox routing asserted against a REAL offline ccxt.pro.okx client (construction opens no socket; only load_markets stubbed) rather than a fake — the wspap host swap is genuine ccxt behavior, the strongest possible CONN-03 misroute gate"
  - "load_markets() is called unconditionally in _build_client (the order arm's amount/price precision helpers need it in BOTH live and sandbox); set_sandbox_mode(True) is the only sandbox-conditional call"
  - "Connector docstring reworded to avoid the literal tokens FillEvent / events_handler.events so the Task-1 grep-guard (which scans the FULL source incl. docstrings) reads grep-zero"

requirements-completed: [CONN-03, CONN-04]

# Metrics
duration: 12min
completed: 2026-07-01
---

# Phase 2 Plan 02: OKX Connector (session/transport primitive) Summary

**`OkxConnector` — the thin authenticated session/transport primitive the three OKX arms share: one asyncio loop on a daemon thread, one ccxt.pro client built inside that loop, one `sandbox: bool` that drives both `set_sandbox_mode` (REST header + ccxt WS host swap to `wspap`) and the exposed flag the native data socket keys off, a `call`/`spawn` async→sync bridge, and lifecycle — owning no venue operations and emitting no domain events (D-02).**

## Performance

- **Duration:** ~12 min
- **Tasks:** 2 (both `type=auto`)
- **Files modified:** 3 (2 created, 1 modified)

## Accomplishments
- Built `itrader/connectors/okx.py::OkxConnector` — the genuinely-new async-containment code of the phase: `connect()` spins `asyncio.new_event_loop()` on a `threading.Thread(daemon=True, name="okx-connector")` and builds the `ccxt.pro.okx` client *inside* the loop via `run_coroutine_threadsafe(_build_client()).result(30)` (Pitfall 3 — ccxt.pro binds sockets to its creating loop). `enableRateLimit=True` left ON (RES-01).
- Encoded the single-bool sandbox routing (CONN-03 / D-02 correction): `sandbox=True` → `set_sandbox_mode(True)` (REST `x-simulated-trading` header + ccxt WS host swap to `wspap.okx.com`) AND the read-only `sandbox` property the native business-candle socket (Plan 02-04) keys its own host off — no split-brain, the header never routes WS.
- Implemented the scheduling seam: `call(coro)` synchronous RPC (bridge + `.result(30)`); `spawn(coro)` schedules a tracked `watch_*` stream task in `self._stream_tasks` (never `.result()`-awaited); `disconnect()` cancels-all + `gather`s, closes the client, stops the loop, joins the thread.
- Kept the connector domain-free (D-02, grep-guarded): no `events_handler.events` import, no fill/order/bar event construction; credentials only via `SecretStr.get_secret_value()` at client construction, never logged.
- Exported `OkxConnector` from the connectors barrel (D-04); `mypy --strict` clean.
- Proved the three properties offline: `-k sandbox` asserts the real ccxt `urls['api']` swaps to `wspap` (and stays `ws.okx.com` when live); `-k loop` asserts `call` returns via the daemon-thread loop and `spawn`+`disconnect` track/cancel the task and close the client; a grep-guard test asserts no domain-event reference in the source.

## Task Commits

Each task was committed atomically:

1. **Task 1: OkxConnector session/transport primitive** — `26a56067` (feat)
2. **Task 2: sandbox routing + loop/bridge + no-domain-import tests** — `6de02e2b` (test)

**Plan metadata:** committed separately (docs: complete plan).

## Files Created/Modified
- `itrader/connectors/okx.py` (created) — `OkxConnector` (loop-on-daemon-thread, ccxt.pro client built inside the loop, single sandbox bool, `call`/`spawn`/`connect`/`disconnect`, stream-task tracking + cancel).
- `itrader/connectors/__init__.py` (modified) — added `from .okx import OkxConnector`, added to `__all__`, docstring moved to past tense.
- `tests/unit/connectors/test_okx_connector.py` (created) — 5 tests: 2 `sandbox` (CONN-03), 3 `loop` (CONN-04, incl. the no-domain-import guard).

## Decisions Made
- **Real offline ccxt client for the CONN-03 assertion:** `ccxt.pro.okx` construction opens no socket (`session=None` until first request), so the sandbox tests build a *real* client (only `load_markets` stubbed, `set_sandbox_mode` wrapped to spy) and assert the genuine `urls['api']` → `wspap` swap. This proves the actual ccxt routing rather than a fake's echo — the strongest gate for the phase's highest-severity threat (a live misroute).
- **`load_markets()` unconditional:** the order arm's `amount_to_precision`/`price_to_precision` helpers need loaded markets in both live and sandbox, so `load_markets()` runs regardless; only `set_sandbox_mode(True)` is sandbox-gated.
- **Docstring token hygiene:** the Task-1 verify grep-guard scans the full module source (docstrings included), so the D-02 discipline paragraph was worded to avoid the literal `FillEvent` / `events_handler.events` tokens.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Reworded the D-02 docstring to avoid literal domain-event tokens**
- **Found during:** Task 1 (first verify run)
- **Issue:** The connector docstring described the D-02 discipline using the literal strings `FillEvent`, `OrderEvent`, `BarEvent`, and `events_handler.events`. The Task-1 automated verify greps the *entire* module source (including docstrings) for those tokens, so it failed with `AssertionError: connector imports domain events` despite the code being clean.
- **Fix:** Reworded to "imports NO domain-event module and constructs NO fill/order/bar event objects" — same meaning, no literal tokens. No behavior change.
- **Files modified:** itrader/connectors/okx.py
- **Verification:** verify command reads `ok`; `grep -qE "OrderEvent|BarEvent"` grep-zero; the `test_loop_connector_imports_no_domain_events` test passes.
- **Committed in:** 26a56067 (Task 1)

**2. [Rule 3 - Blocking] mypy --strict annotations for the env-sourced settings + threadsafe bridge**
- **Found during:** Task 1 (mypy run)
- **Issue:** `mypy --strict` flagged `OkxSettings()` (env-sourced fields look "missing" to mypy), and could not infer types through `run_coroutine_threadsafe(coro, ...)` given the `Awaitable[_T]` Protocol signature (the `# type: ignore[arg-type]` masks the arg but leaves the `future`/`task` vars unannotated → `no-any-return`/`var-annotated`).
- **Fix:** Added `# type: ignore[call-arg]` on the env-sourced `OkxSettings()` (correct at runtime — pydantic-settings sources every field from the environment), and explicit `future: Future[_T]` / `task: asyncio.Task[Any]` annotations. No behavior change.
- **Files modified:** itrader/connectors/okx.py
- **Verification:** `mypy --strict itrader/connectors/okx.py` → `Success: no issues found`.
- **Committed in:** 26a56067 (Task 1)

---

**Total deviations:** 2 auto-fixed (both blocking, Rule 3). No architectural changes, no scope creep.
**Impact on plan:** Both fixes are mechanical (docstring wording + type annotations) and required to clear the plan's own automated verify/mypy gates. Every must-have and acceptance criterion is honored.

## Milestone Gate
- **Oracle byte-exact:** `tests/integration/test_backtest_oracle.py` passes within the full suite — the backtest hot path imports no async/connector code (the connector is additive, off the run path).
- **No W1/W2 regression:** no change to any backtest-path module; the connector is imported only by the (future) live arms.
- **Held constraints:** `mypy --strict` clean on the new file; full suite green under `filterwarnings=["error"]` (1475 passed / 1 skipped, no ResourceWarning/RuntimeWarning escalation — Pitfall 4); credentials stay `SecretStr` to the client edge; no float money introduced (connector constructs no money values); 4-space indentation matched to the `connectors/` package.

## Known Stubs
None. The connector is a complete session/transport primitive; venue operations are intentionally absent (D-02 — they belong to the arms in Plans 02-03/04/05, which type against this seam).

## Verification Evidence
- `poetry run pytest tests/unit/connectors/test_okx_connector.py -k sandbox -x` → 2 passed (CONN-03).
- `poetry run pytest tests/unit/connectors/test_okx_connector.py -k loop -x` → 3 passed (CONN-04).
- `poetry run pytest tests/unit/connectors` → 5 passed.
- `poetry run pytest tests` → 1475 passed, 1 skipped (no warning escalation).
- `poetry run mypy --strict itrader/connectors/okx.py` → Success.
- `grep -c "set_sandbox_mode"` = 2; `grep -c "enableRateLimit"` = 3; `grep -qE "OrderEvent|BarEvent"` → grep-zero.

## Next Phase Readiness
- The order arm (02-03) and data arm (02-04/02-05) receive `OkxConnector` injected: `call()` for `create_order_ws`/`cancel_order_ws`, `spawn()` for `watch_orders`/`watch_my_trades` and the native business-candle loop, `client` for the ccxt precision helpers, and `sandbox` for the native socket's `wspap` host selection.
- Async containment (CONN-04) and single-bool routing (CONN-03) are locked and tested — the arms build on a proven seam.

## Self-Check: PASSED

- FOUND: itrader/connectors/okx.py
- FOUND: itrader/connectors/__init__.py (OkxConnector exported)
- FOUND: tests/unit/connectors/test_okx_connector.py
- FOUND commit: 26a56067 (feat, Task 1)
- FOUND commit: 6de02e2b (test, Task 2)

---
*Phase: 02-okx-connector*
*Completed: 2026-07-01*

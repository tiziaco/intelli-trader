---
status: resolved
trigger: "WR-03 (Phase 5 review) — reconnect retry ceiling can never trip on a subscribe-then-close storm, defeating the D-20 never-spin-forever→HALT guarantee. Oracle-dark (live/sandbox only); the frozen SMA_MACD backtest MUST stay byte-exact."
created: 2026-07-03
updated: 2026-07-03
---

# Debug Session: WR-03 reconnect ceiling storm

## Symptoms

DATA_START

**Expected behavior:** When an OKX websocket subscribes then closes immediately in a
repeating storm (server-side churn), the reconnect supervisor's retry budget should be
exhausted and the stream should HALT (D-20 "never spin forever → HALT" guarantee,
RES-01/D-19/D-20).

**Actual behavior:** The loop reconnects forever at `backoff_base` and NEVER halts. Each
cycle `_on_stream_healthy` fires on mere subscribe (before any payload) and resets
`_reconnect_attempts[stream] = 0`, so the supervisor's `attempt = get(stream,0)+1` is
always 1 and never exceeds `_reconnect_ceiling`.

**Error messages:** None — silent defeat of the HALT guarantee (this is the danger).

**Timeline:** Introduced with the reconnect-supervisor design; line numbers in okx.py
rotted after recent WR-01/WR-04 edits (LOCATE BY SYMBOL, not line).

**Reproduction:** Script many `"ok"` steps in `tests/unit/execution/test_reconnect_resilience.py`
via `_ScriptedConsume` (`"ok"` = signal healthy then return cleanly = subscribe-then-close).
Assert the retry ceiling IS reached and `_halt_signal` fires (reason 'connector-fatal' on
the order arm; provider ceiling-exhausted halt on the data arm). Must currently FAIL.

**Affected symbols (both venue arms):**
- Data arm — `itrader/price_handler/providers/okx_provider.py`: `_connect_and_consume_candles`,
  `_on_stream_healthy`, `_run_stream_supervisor`.
- Order arm — `itrader/execution_handler/exchanges/okx.py`: `_consume_fills`, `_consume_orders`,
  `_on_stream_healthy`, `_run_stream_supervisor`, `_halt_signal`.

**Root-fix direction (prefilled by reporter):** A subscribe is not "healthy" — only a
connection that proves itself should reset the retry budget.
- (A) PAYLOAD-GATED reset (preferred, deterministic, no clock): do NOT reset in
  `_on_stream_healthy` on subscribe; reset only after the consume loop delivered ≥1 payload.
- (B) HEALTHY-DWELL timer: reset only after connection stayed up ≥ a per-instance tunable
  dwell (module default, mirror `_reconnect_backoff_base_s`/`_reconnect_ceiling`), monotonic clock.
- Hybrid (reset on first payload OR dwell) acceptable. Same fix to both arms; shared helper
  if it reads cleanly.

**Constraints:**
- okx.py + okx_provider.py use TABS. Never normalize.
- No money in this path; no Decimal changes.
- filterwarnings=["error"], --strict-markers — no new markers.
- Backtest byte-exact: `tests/integration/test_backtest_oracle.py` (oracle 134 / 46189.87730727451).

**Verification (report ACTUAL output, use `poetry run pytest` NOT `make test`):**
- New storm-exhausts-ceiling-and-halts test (red before, green after).
- `tests/unit/execution/test_reconnect_resilience.py` full (transient-survives + fatal-halts unchanged).
- `tests/integration/test_backtest_oracle.py` (byte-exact).
- `poetry run mypy itrader` (strict-clean).

DATA_END

## Current Focus

reasoning_checkpoint:
  hypothesis: "`_on_stream_healthy` resets `_reconnect_attempts[stream]=0` on a mere subscribe (before any payload). In a subscribe-then-close storm the supervisor re-enters each cycle with attempt=get(stream,0)+1=1, which is never > `_reconnect_ceiling`, so the D-20 never-spin-forever HALT can never trip."
  confirming_evidence:
    - "okx.py:630 and okx_provider.py:379 are the ONLY reset-to-0 sites (grep repo-wide); both live inside `_on_stream_healthy`."
    - "okx_provider.py:260 calls `_on_stream_healthy('candles')` right after `ws.send_json(subscribe)` and BEFORE the `async for msg` read loop — i.e. on subscribe, before any payload."
    - "okx.py `_consume_fills`/`_consume_orders` call `_on_stream_healthy` after every `watch_*()` return regardless of whether the batch is empty (subscribe-ack level)."
    - "The supervisor increment sites (okx.py:578, okx_provider.py:331) compute attempt = get(stream,0)+1; a reset to 0 immediately before pins attempt at 1."
  falsification_test: "A subscribe-then-close storm (many iterations that signal healthy-on-subscribe then drop) that STILL halts once the reset is removed from `_on_stream_healthy` would disprove that the subscribe reset is the cause. Conversely, if removing the reset does NOT make the storm halt, the hypothesis is wrong."
  fix_rationale: "Fix (A) payload-gated reset: `_on_stream_healthy` (the subscribe hook the test harness drives) stops resetting the budget — it retains only the D-19 resume/up transition. The budget reset moves to a new `_reset_reconnect_budget` helper called from the real consume loops ONLY when >=1 payload was delivered (non-empty trades/orders batch; a processed candle row). A subscribe is no longer proof of health, so the storm's attempts climb monotonically until the ceiling trips -> HALT. Addresses the root cause (subscribe != healthy), not a symptom."
  blind_spots: "The payload-gated reset in the real consume loops (_consume_fills/_consume_orders/_connect_and_consume_candles) is not directly unit-covered by the harness (which drives `_run_stream_supervisor` with a scripted consume, not the real methods). Covered indirectly by mypy strict + the oracle for regression, and the storm test proves the subscribe path no longer resets. Resume-on-subscribe (on_stream_up) is intentionally left as-is (pre-existing D-19 behavior, out of WR-03 scope)."
  next_action: "Write red storm test (both arms) in test_reconnect_resilience.py; confirm RED; apply fix (A) to both files; confirm GREEN + full suite + oracle + mypy."

## Evidence

- timestamp: 2026-07-03
  checked: "grep repo-wide for `_reconnect_attempts[...] = 0` and all `_on_stream_healthy` references."
  found: "Exactly two reset-to-0 sites, both inside `_on_stream_healthy` (okx.py:630, okx_provider.py:379). No other resets. `_on_stream_healthy` is referenced by the two real consume paths and by the test harness `on_healthy` hook."
  implication: "Removing the reset from `_on_stream_healthy` fully controls where the budget resets; the fix surface is exactly these two methods plus the payload-gated reset sites."

- timestamp: 2026-07-03
  checked: "okx_provider.py `_connect_and_consume_candles` (subscribe -> _on_stream_healthy -> async-for read) and okx.py `_consume_fills`/`_consume_orders` (watch -> _on_stream_healthy -> iterate)."
  found: "Provider signals healthy immediately after subscribe, before reading any message. Order arm signals healthy after every watch return, including empty batches. Both equate subscribe/ack with 'healthy'."
  implication: "Subscribe-then-close (no payload) resets the budget in both arms -> ceiling never trips. Payload-gating the reset is the correct, minimal fix and applies identically to both arms."

- timestamp: 2026-07-03
  checked: "Supervisor divergence between arms: okx.py `_run_stream_supervisor` does `await consume; return` (clean return STOPS); okx_provider.py treats a clean return as a server-closed socket and reconnects."
  found: "Order arm's real consume never returns cleanly (it raises on drop); provider's returns cleanly on server close. Storm must be modeled per-arm: order arm = healthy-then-transient-raise; provider arm = healthy-then-clean-return."
  implication: "Two paired storm tests needed (mirrors existing paired tests). A single storm double parameterized by drop mode ('transient' vs 'clean') serves both."

- timestamp: 2026-07-03
  checked: "ONLINE probe against OKX demo (host wseeapap.okx.com, eea region, sandbox routing asserted). Read-only public candle1D BTC-USDC subscribe, mirroring `_connect_and_consume_candles` exactly (raw aiohttp, `rows = payload.get('data', [])`, reset `if rows:`). Ran 3 subscribe-then-close cycles."
  found: "OKX pushes a `data` payload (rows=1, confirm='0' — the in-progress candle SNAPSHOT) within ~27-34ms of EVERY subscribe, before any real streaming. `_reset_reconnect_budget('candles')` fired in 3/3 cycles."
  implication: "SURVIVING BUG (data arm). The WR-03 payload-gate does NOT close the candle arm: OKX's snapshot-on-subscribe means a delivered payload == a subscribe, so a subscribe-then-close storm resets the budget every cycle and the D-20 ceiling never trips. Order arm IS fixed (ccxt.pro watch_my_trades/watch_orders emit only on real activity, no subscribe snapshot). The offline unit harness scripts the consume loop and never models snapshot-on-subscribe, so it passed green while the online hole remained."

- timestamp: 2026-07-03
  checked: "ONLINE fix-verification probe against OKX demo (same host/sandbox routing), driving the FIXED skip-snapshot logic (`payload_seen` gate): (1) 3 subscribe-then-close storm cycles; (2) one healthy cycle held open for a post-snapshot streaming update."
  found: "Storm: snapshot skipped, budget reset 0/3 cycles (was 3/3 pre-fix). Healthy: the subscribe snapshot (confirm='0', +30ms) was skipped, and a genuine post-snapshot candle update arrived at +6908ms and reset the budget (1/1). FIX CONFIRMED ONLINE."
  implication: "Data arm now behaves as required against the real venue: a subscribe-then-close storm no longer resets the retry budget -> the D-20 ceiling trips -> HALT; a genuine streaming reconnect still clears the budget within seconds -> survives. Closes the online hole the offline suite could not see."

## Eliminated

- hypothesis: "Fix (A) pure payload-gated reset closes BOTH arms."
  why_wrong: "Empirically false on the data arm — OKX delivers a candle snapshot (confirm='0') on every subscribe (~30ms), so 'first delivered payload' is indistinguishable from 'subscribed'. Payload-gating is sufficient ONLY for channels that never snapshot-on-subscribe (the order arm). The data arm needs a stronger 'proved itself' signal: a healthy DWELL (fix B) or skipping the subscribe snapshot (reset on the 2nd payload)."

## Resolution

root_cause: "`_on_stream_healthy` resets the reconnect retry budget (`_reconnect_attempts[stream]=0`) on a mere subscribe/ack, before any payload is delivered. In a subscribe-then-close storm the supervisor's `attempt = get(stream,0)+1` is pinned at 1 and never exceeds `_reconnect_ceiling`, so the D-20 never-spin-forever HALT guarantee is silently defeated in both the data (okx_provider) and order (okx) arms."
fix: |
  Two layers (the second found only by the ONLINE sandbox test the reporter asked for):

  Layer 1 — payload-gated reset (both arms):
  - `_on_stream_healthy` no longer resets `_reconnect_attempts` — it now performs ONLY the
    D-19 resume/up transition. A subscribe/ack is no longer treated as proof of health.
  - Added `_reset_reconnect_budget(stream)` to each class; the real consume loops call it
    ONLY when >=1 payload is delivered: okx.py `_consume_fills` (non-empty `trades`) and
    `_consume_orders` (non-empty `orders`); okx_provider.py `_connect_and_consume_candles`.

  Layer 2 — skip-the-subscribe-snapshot (DATA arm only; the surviving bug):
  - ONLINE evidence: OKX pushes an in-progress-candle SNAPSHOT (confirm='0', ~30ms) on EVERY
    candle subscribe, so plain payload-gating still reset the budget every storm cycle.
  - `_connect_and_consume_candles` now carries a per-connection `payload_seen` flag and resets
    the budget ONLY on a payload delivered AFTER the subscribe snapshot (real streaming). The
    snapshot sets the flag but does not reset. Order arm needs no such guard (ccxt.pro
    watch_my_trades/watch_orders never emit on bare subscribe).
  Result: a subscribe-then-close storm's `attempt` climbs monotonically (snapshot no longer
  resets it) until it exceeds `_reconnect_ceiling` -> `_escalate_connector_halt('connector-fatal')`
  (D-20 restored) on BOTH arms; a genuine streaming reconnect still clears the budget.
verification: |
  All ACTUAL output (poetry run pytest / mypy, NOT make test):
  OFFLINE:
  - New order+data storm tests + new snapshot-on-subscribe test (drives the REAL
    `_connect_and_consume_candles` via a fake WS reproducing the demo snapshot-then-close):
    RED before each fix (`assert [] == ['connector-fatal']`; logs showed the "attempt 1/3"
    forever-loop), GREEN after (halt fires).
  - tests/unit/execution/test_reconnect_resilience.py: 17 passed (transient-survives +
    fatal-halts + blip-debounce + WR-01/WR-04 unchanged).
  - tests/integration/test_backtest_oracle.py: 3 passed, byte-exact (oracle unchanged).
  - poetry run mypy itrader: Success, no issues in 226 source files (strict-clean).
  ONLINE (OKX demo, sandbox routing asserted, read-only public candle channel):
  - Subscribe-then-close storm: snapshot skipped, budget reset 0/3 cycles (was 3/3 pre-fix)
    -> ceiling can trip -> HALT.
  - Healthy stream: post-snapshot streaming update at +6908ms reset the budget 1/1 -> survives.
files_changed:
  - itrader/execution_handler/exchanges/okx.py            # Layer 1 (order arm) — prior session
  - itrader/price_handler/providers/okx_provider.py       # Layer 1 + Layer 2 (data arm)
  - tests/unit/execution/test_reconnect_resilience.py     # storm tests + snapshot-on-subscribe test

---
phase: quick-260722-hpz
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - itrader/trading_system/live_trading_system.py
  - tests/unit/trading_system/test_stop_tears_down_every_lifecycle.py
autonomous: true
requirements: [WR-08]

must_haves:
  truths:
    - "WR-08: LiveTradingSystem.stop() drives VenueLifecycle.stop() on EVERY entry of _venue_lifecycles, not just the first — symmetric with the start() loop at :762-763"
    - "WR-08: a lifecycle built WITHOUT a shared ConnectorProvider (the elif bundle.connector.disconnect() fallback branch of VenueLifecycle.stop) is disconnected even when it is not the primary — no leaked authenticated socket, no ResourceWarning under filterwarnings=['error']"
    - "WR-08: one lifecycle raising during teardown does NOT prevent the remaining lifecycles from being torn down (per-lifecycle isolation, guard at the call site)"
    - "WR-08: a teardown failure never masks an exception already propagating out of the stop() try body"
    - "PRESERVED: the teardown still runs from the finally block, so it happens on the early 'not running' return, on a normal return, and on a raising body"
    - "PRESERVED: stop() still survives a partially-constructed facade (defensive read of _venue_lifecycles) and still raises nothing on a facade with no lifecycles at all"
    - "PRESERVED: the SQL-spine backend.dispose() that follows the teardown in the same finally block still runs on every path, including after a raising lifecycle"
    - "A regression test drives stop() with 2+ recording fakes and FAILS against the pre-fix code"
    - "Backtest path untouched — the SMA_MACD oracle stays 134 trades / 46189.87730727451 and test_okx_inertness stays green"
  artifacts:
    - itrader/trading_system/live_trading_system.py
    - tests/unit/trading_system/test_stop_tears_down_every_lifecycle.py
  key_links:
    - "stop()'s finally block iterates the snapshot taken from _venue_lifecycles before the try, so every return path sees the full map"
    - "the per-lifecycle try/except sits INSIDE the teardown loop, so isolation is per venue rather than per teardown block"
    - "ConnectorProvider.close_all() clears its memo in a finally (connectors/provider.py:82-91), which is what makes the extra shared-provider calls safe no-ops"
---

<objective>
Close code-review finding **WR-08**: `LiveTradingSystem.stop()` tears down only the FIRST
venue lifecycle while `start()` starts every one of them.

Purpose: in any configuration where the lifecycles were built WITHOUT a shared
`ConnectorProvider`, `VenueLifecycle.stop()` takes its `elif self._bundle.connector is not
None: self._bundle.connector.disconnect()` fallback branch — which covers only that one
bundle. Stopping just the primary therefore leaks every non-primary connector: a dangling
authenticated venue socket in production, and a `ResourceWarning` (i.e. a hard failure)
under `pyproject.toml`'s `filterwarnings = ["error"]`. The comment in `stop()` justifies
the shortcut with `ConnectorProvider.close_all()` being shared across accounts, which is
true for only ONE of that method's two branches.

Output: an iterating, per-lifecycle-isolated teardown in `stop()`, plus a unit regression
test that fails against the current code and proves every lifecycle is stopped.
</objective>

<execution_context>
@$HOME/.claude/gsd-core/workflows/execute-plan.md
@$HOME/.claude/gsd-core/templates/summary.md
</execution_context>

<context>
@.planning/PROJECT.md
@CLAUDE.md

@itrader/trading_system/live_trading_system.py
@itrader/venues/lifecycle.py
@tests/unit/trading_system/test_live_runner_stats.py
@tests/unit/venues/test_lifecycle.py
</context>

<interface_context>
Verified against the real code before planning — do NOT re-derive, but DO re-read the
lines before editing (code wins over any claim below):

- `itrader/trading_system/live_trading_system.py` is **4-SPACE indented** (0 tab-indented
  lines in the whole file, measured). Siblings `compose.py` / `backtest_trading_system.py`
  are TABS — this file is not. Match 4 spaces.
- `stop()` is a **method** and uses `self.logger` (`self.logger.warning` at :901,
  `self.logger.error` at :928). The function-local `logger` idiom used elsewhere in this
  module does NOT apply at this site.
- Current shape (`:897-898`, pre-try):
  `lifecycles = getattr(self, '_venue_lifecycles', None) or {}`
  `lifecycle = next(iter(lifecycles.values()), None)`
  and (`:919-938`, the `finally`): `if lifecycle is not None:` → `try: lifecycle.stop()` →
  `except Exception as e: self.logger.error(f'Error disconnecting venue connector: {e}')`,
  then the `_system_db_backend` dispose block.
- `start()`'s symmetric loop is `:762-763`:
  `for lifecycle in self._venue_lifecycles.values(): lifecycle.start()`.
- `self._venue_lifecycles: Dict[str, Any]` (`:206`) is keyed by `account_id`; insertion
  order is a documented primary contract (`_primary_lifecycle`, `:301`, is the first entry).
- `ConnectorProvider.close_all()` (`itrader/connectors/provider.py:82-91`) iterates the
  memo, swallows per-connector failures, and `self._memo.clear()`s in a `finally` — so a
  second call iterates an empty memo. Idempotency confirmed; the extra calls in the
  shared-provider case are true no-ops.
- No test anywhere asserts the `'Error disconnecting venue connector'` log string
  (grep: 1 hit, the source line itself). No test asserts a `close_all` call count driven
  through the facade `stop()` — `tests/unit/venues/test_lifecycle.py:73-87` drives
  `VenueLifecycle.stop()` directly with ONE lifecycle and is unaffected.
- `tests/unit/trading_system/` is **package-less** (no `__init__.py`) — keep it that way;
  the folder supplies the `unit` marker via `tests/conftest.py`.
- Established in-repo pattern for driving a facade method without building the facade:
  `tests/unit/trading_system/test_live_runner_stats.py:35-46` re-binds the REAL method onto
  a minimal host (`class _StatsHost: _update_stats = LiveTradingSystem._update_stats`).
  Reuse that pattern — it exercises the actual logic, not a re-implementation.
</interface_context>

<tasks>

<task type="auto" tdd="true">
  <name>Task 1: Failing regression test — stop() must tear down EVERY lifecycle</name>
  <files>tests/unit/trading_system/test_stop_tears_down_every_lifecycle.py</files>
  <behavior>
    Four tests. The first three MUST FAIL against the current (pre-fix) code — that RED
    result is the deliverable of this task. The fourth is a preservation test and is
    expected to pass both before and after (say so in its docstring so nobody reads its
    green as evidence of the fix).

    Host pattern: a `_TeardownHost` class that re-binds the REAL method —
    `stop = LiveTradingSystem.stop` — onto a minimal object carrying only what `stop()`
    touches: `_venue_lifecycles` (dict of account_id -> fake), `_running`,
    `_system_db_backend`, `_live_runner`, `_safety`, `logger`. No daemon thread, no venue
    arm, no credentials, no network. Fakes are hand-written recorders (a shared ordered
    `calls: list[str]` each fake appends its own account id to on `stop()`), NOT MagicMocks
    with only a call-count — the assertions must name WHICH lifecycles were stopped.

    - Test 1 `test_stop_tears_down_every_lifecycle`: 3 fakes keyed acct-a/acct-b/acct-c,
      `_running=False` (the early "not running" return — proves the finally still runs).
      Assert the recorded call log equals `["acct-a", "acct-b", "acct-c"]` (fan-out AND the
      deterministic insertion order the module documents), and that `stop()` returned True.
      RED today: the log is `["acct-a"]`.
    - Test 2 `test_a_raising_lifecycle_does_not_strand_the_others`: same 3 fakes, the MIDDLE
      one (acct-b) raises `RuntimeError` from its `stop()` after recording. Assert all three
      are in the recorded log (isolation is per lifecycle), that `stop()` did NOT propagate
      the RuntimeError, that the recording SQL backend's `dispose()` still ran exactly once,
      and that an error was logged. RED today: only acct-a is in the log.
    - Test 3 `test_teardown_runs_and_does_not_mask_a_raising_stop_body`: `_running=True`
      with a `_live_runner` whose `stop()` raises `RuntimeError("boom")`. Assert under
      `pytest.raises(RuntimeError, match="boom")` — the ORIGINAL exception must still
      propagate through the finally, unmasked — and, after the raises block, that all three
      lifecycles were stopped and the backend was disposed. RED today: only acct-a stopped.
    - Test 4 `test_partially_constructed_facade_stop_does_not_raise`: a host with NO
      `_venue_lifecycles` and NO `_system_db_backend` attributes at all, `_running=False`.
      Assert `stop()` returns True and raises nothing — locks the defensive `getattr` reads
      that must survive the fix. Passes before AND after; it is a preservation guard.

    Module docstring: state that this is the WR-08 regression gate, what the pre-fix defect
    was (only the first lifecycle torn down; the non-shared-provider fallback branch of
    `VenueLifecycle.stop` leaks every other connector), and that the directory is
    package-less on purpose.
  </behavior>
  <action>
Create `tests/unit/trading_system/test_stop_tears_down_every_lifecycle.py` implementing the
four tests in `<behavior>`. Import `LiveTradingSystem` from
`itrader.trading_system.live_trading_system` at module scope (the sibling unit tests in this
directory already do — no inertness concern, this is not the backtest import path).

Follow the host-rebinding pattern from `tests/unit/trading_system/test_live_runner_stats.py`
(`class _StatsHost: _update_stats = LiveTradingSystem._update_stats`): the point is to drive
the REAL `stop()` body, not a paraphrase of it. `MagicMock` is fine for `logger`, `_safety`
and (in tests 1/2/4) `_live_runner`; the lifecycles and the SQL backend must be hand-written
recorders so the assertions can name them.

Do NOT add `@pytest.mark.unit` — `tests/conftest.py` derives the marker from the folder, and
`--strict-markers` is on. Do NOT create an `__init__.py` in this directory. 4-space
indentation (test tree convention). No new fixtures in `conftest.py`.

Run the file and CONFIRM it is RED for the three defect tests before finishing this task.
Do not touch `itrader/` in this task — the fix is Task 2.
  </action>
  <verify>
    <automated>cd /Users/tizianoiacovelli/Desktop/projects/intelli-trader &amp;&amp; if poetry run pytest tests/unit/trading_system/test_stop_tears_down_every_lifecycle.py -q 2>&amp;1 | tee /tmp/wr08-red.txt | tail -5; then echo "UNEXPECTED GREEN — the test does not reproduce WR-08"; exit 1; fi; grep -qE "3 failed, 1 passed" /tmp/wr08-red.txt || { echo "expected exactly 3 failed / 1 passed"; exit 1; }</automated>
  </verify>
  <done>`poetry run pytest tests/unit/trading_system/test_stop_tears_down_every_lifecycle.py` reports exactly 3 failed, 1 passed against the unmodified `live_trading_system.py`; the three failures are the fan-out/isolation/unmasked-raise tests, and each failure message shows the recorded call log containing only `acct-a`. `itrader/` is unchanged.</done>
</task>

<task type="auto">
  <name>Task 2: Iterate the teardown in stop(), with per-lifecycle isolation</name>
  <files>itrader/trading_system/live_trading_system.py</files>
  <action>
Edit `LiveTradingSystem.stop()` (currently `:869-938`). Two edits, no other change to the
method, and nothing else in the file.

(1) Replace the pre-`try` pair at `:897-898`

    lifecycles = getattr(self, '_venue_lifecycles', None) or {}
    lifecycle = next(iter(lifecycles.values()), None)

with a single snapshot of the full map:

    lifecycles = list((getattr(self, '_venue_lifecycles', None) or {}).items())

Keep it BEFORE the `try` (deliberate: the `finally` then holds the map on every return
path) and keep the defensive `getattr` (deliberate: `stop()` must survive a
partially-constructed facade). Snapshot into a `list` rather than holding a live view, so a
teardown that mutates the map cannot raise "dictionary changed size during iteration".
Iterate `.items()` so the failure log can name the account — that is a READ of the existing
key for diagnostics; do NOT change how `_venue_lifecycles` is keyed or built (out of scope,
owned by Phase 11.1).

(2) Replace the single-lifecycle teardown in the `finally` (`:924-928`)

    if lifecycle is not None:
        try:
            lifecycle.stop()
        except Exception as e:
            self.logger.error(f'Error disconnecting venue connector: {e}')

with the loop, keeping the `try/except Exception` INSIDE it:

    for account_id, lifecycle in lifecycles:
        try:
            lifecycle.stop()
        except Exception as e:
            self.logger.error(
                f'Error disconnecting venue connector for account {account_id}: {e}')

The `if lifecycle is not None:` guard is dropped because the loop is self-guarding on an
empty map — that is the guard-clause/early-exit shape the owner prefers, not a lost check.
The guard placement is a DECISION, state it in the comment: it lives at this call site,
per iteration, NOT inside `VenueLifecycle.stop()` — that method must stay honest and keep
raising for its own single-lifecycle callers and its unit contract
(`tests/unit/venues/test_lifecycle.py`). Swallowing here also stops a teardown failure from
masking an exception already propagating out of the `try` body.

Leave the `_system_db_backend` dispose block that follows COMPLETELY untouched — it must
still run after the loop, including after a raising lifecycle.

Rewrite the stale block comment at `:892-896` ("11-09: ONE stop() is enough for every
account ... so calling it on the primary tears down all of them"). It is now factually
wrong and is the exact reasoning that produced the defect. Replace it with: every account's
lifecycle is torn down, symmetric with the `start()` loop above; the old shortcut held only
for the `self._connectors is not None` branch of `VenueLifecycle.stop()`, while the
documented `elif self._bundle.connector is not None: disconnect()` fallback exists for
lifecycles built WITHOUT a shared provider and there every non-primary connector leaked
(dangling authenticated socket in production, `ResourceWarning` under
`filterwarnings=["error"]`); `ConnectorProvider.close_all()` clears its memo in a `finally`
(`connectors/provider.py:82-91`) so it is idempotent and the shared-provider case is
unaffected by the extra calls. Tag it `WR-08`. Keep the surrounding CR-01 comment block.

INDENTATION: this file is 4-SPACE (verified: zero tab-indented lines). Never introduce a
tab. Do not reformat or re-wrap any line you are not changing.

SCOPE LOCK: do not touch `_primary_lifecycle`, `_streaming_lifecycles`, the `start()` loop,
`_venue_lifecycles` keying/construction, `_attach_venue_accounts`, any `or DEFAULT_ACCOUNT_ID`,
or `ExecutionHandler.on_order`. Every other 11-REVIEW finding belongs to Phase 11.1. If you
notice something else worth fixing, write it in the SUMMARY's follow-ups instead of fixing it.
  </action>
  <verify>
    <automated>cd /Users/tizianoiacovelli/Desktop/projects/intelli-trader &amp;&amp; test "$(git diff -U0 -- itrader/trading_system/live_trading_system.py | grep -cP '^\+\t')" = "0" &amp;&amp; poetry run pytest tests/unit/trading_system/test_stop_tears_down_every_lifecycle.py tests/unit/venues/test_lifecycle.py tests/unit/connectors/test_provider.py -q 2>&amp;1 | tail -3</automated>
    <automated>cd /Users/tizianoiacovelli/Desktop/projects/intelli-trader &amp;&amp; poetry run pytest tests/integration/test_live_system_okx_wiring.py tests/integration/test_multi_account_composition.py tests/integration/test_live_paper_lifecycle.py tests/integration/test_multi_portfolio_lifecycle.py tests/integration/test_okx_inertness.py -q 2>&amp;1 | tail -3</automated>
    <automated>cd /Users/tizianoiacovelli/Desktop/projects/intelli-trader &amp;&amp; poetry run pytest tests/integration/test_backtest_oracle.py -q 2>&amp;1 | tail -3</automated>
  </verify>
  <done>The three RED tests from Task 1 are GREEN; the fourth still passes. `tests/unit/venues/test_lifecycle.py` and `tests/unit/connectors/test_provider.py` are unchanged and green. The live-wiring, multi-account-composition, paper-lifecycle and multi-portfolio integration suites are green (each of them calls `system.stop()`, several with 2 lifecycles — they now exercise the fan-out). `test_okx_inertness.py` is green. The SMA_MACD oracle is byte-exact (134 trades / 46189.87730727451). The diff adds zero tab-indented lines to a 4-space file and touches nothing outside `stop()`.</done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| engine process → venue (OKX) socket | authenticated WS/REST sessions held open by each account's connector; teardown is the only thing that closes them |

## STRIDE Threat Register

| Threat ID | Category | Component | Severity | Disposition | Mitigation Plan |
|-----------|----------|-----------|----------|-------------|-----------------|
| T-hpz-01 | Information Disclosure | `LiveTradingSystem.stop()` teardown of non-primary `VenueLifecycle`s | high | mitigate | Iterate every lifecycle so each account's authenticated venue socket is closed at shutdown; a leaked session outlives the process's intent to trade and stays credentialed. Proven by the Task 1 fan-out test. |
| T-hpz-02 | Denial of Service | teardown loop when one venue's `disconnect()` hangs or raises | medium | mitigate | Per-lifecycle `try/except Exception` INSIDE the loop, so one bad venue cannot strand the remaining venues' sockets or block the SQL-spine dispose. Proven by the Task 1 isolation test. |
| T-hpz-03 | Tampering | dependency surface | low | accept | No package installs in this change — no `npm`/`pip`/`cargo` task, no new import. Package Legitimacy Gate not applicable. |
</threat_model>

<verification>
1. `poetry run pytest tests/unit/trading_system/test_stop_tears_down_every_lifecycle.py -q` — 4 passed.
2. `poetry run pytest tests` — full suite green (the mandated gate; NEVER `make test`, it exports
   `ITRADER_DISABLE_LOGS=true` and breaks caplog assertions).
3. `poetry run pytest tests/integration/test_backtest_oracle.py -q` — oracle byte-exact
   (134 trades / `46189.87730727451`). Any movement here means something went wrong: this
   change touches only the live teardown path.
4. `poetry run pytest tests/integration/test_okx_inertness.py -q` — GATE-01 holds (no new
   eager async/ccxt/SQL import reached the backtest import path).
5. `git diff -U0 -- itrader/trading_system/live_trading_system.py | grep -P '^\+\t'` — empty
   (no tab added to a 4-space file). Scanned on ADDED lines only, per the tab-gate
   false-failure hazard.
6. `git diff --stat` — exactly two files: `itrader/trading_system/live_trading_system.py`
   and the new test. Nothing from the Phase 11.1 scope-locked list is touched.
</verification>

<success_criteria>
- `LiveTradingSystem.stop()` calls `VenueLifecycle.stop()` once per entry in
  `_venue_lifecycles`, from the `finally` block, on every return path.
- A raising lifecycle is isolated: the others are still stopped, the SQL-spine
  `dispose()` still runs, and an exception propagating out of the `try` body is not masked.
- `stop()` on a partially-constructed facade (no `_venue_lifecycles`) still returns True
  without raising.
- The new regression test failed against the pre-fix code (RED evidence captured in the
  SUMMARY) and passes after.
- Full suite green via `poetry run pytest tests`; oracle byte-exact; inertness gate green.
- Two atomic commits: `test(quick-260722-hpz): ...` (RED) then `fix(quick-260722-hpz): ...`.
</success_criteria>

<output>
Create `.planning/quick/260722-hpz-fix-code-review-wr-08-stop-tears-down-ev/260722-hpz-SUMMARY.md` when done.
Record in it: the RED pytest output from Task 1 (proof the test reproduces WR-08), the
guard-placement decision (call site, per iteration — NOT inside `VenueLifecycle.stop()`) and
why, and any out-of-scope observation noticed but deliberately NOT fixed.
</output>

---
phase: quick-260713-phm
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - itrader/trading_system/live_trading_system.py
  - itrader/trading_system/live_runner.py
autonomous: true
requirements: [WR-02, IN-02]

must_haves:
  truths:
    - "LiveTradingSystem.start() raises StateError (unhandled) when constructed outside build_live_system() with _live_runner/_error_policy unwired"
    - "LiveRunner.stop() logs a warning when the drain thread is still alive after join timeout"
  artifacts:
    - itrader/trading_system/live_trading_system.py
    - itrader/trading_system/live_runner.py
  key_links:
    - "start() guard sits ABOVE the try: and above _update_status(STARTING) so the broad except cannot swallow it"
    - "StateError added to the existing `from itrader.core.exceptions import ...` line (no duplicate import)"
---

<objective>
Batch-fix two Phase 06 code-review findings in the live trading system: WR-02 (unwired-start masking) and IN-02 (stop() ignores join timeout). Both are live-only, oracle-dark, mechanical. Owner has LOCKED the exact edits — implement exactly as specified, do not re-litigate.

Purpose: Turn two silent failure modes into loud, correct signals — a hard programming-error raise for an unwired start, and an operator warning when a drain thread outlives its join.
Output: Two edited 4-space-indented files; guardrail gates green.
</objective>

<execution_context>
@$HOME/.claude/gsd-core/workflows/execute-plan.md
@$HOME/.claude/gsd-core/templates/summary.md
</execution_context>

<context>
@.planning/STATE.md
@CLAUDE.md

# Both target files are 4-SPACE indented (0 tabs, verified). Preserve 4-space.
@itrader/trading_system/live_trading_system.py
@itrader/trading_system/live_runner.py
@itrader/core/exceptions/base.py
</context>

<tasks>

<task type="auto">
  <name>Task 1: WR-02 — typed guard clause in LiveTradingSystem.start()</name>
  <files>itrader/trading_system/live_trading_system.py</files>
  <action>
    Add StateError to the existing exceptions import on line 19. That line currently reads exactly `from itrader.core.exceptions import ConfigurationError` — change it to import both ConfigurationError and StateError on that single line (do NOT add a second import line; verified StateError is not yet imported).

    In start() (~line 982): insert a typed guard clause AFTER the existing `if self._running:` early-return block (ends ~line 989) and ABOVE both `self._update_status(SystemStatus.STARTING)` (~line 992) and the `try:` (~line 994). Placement is CRITICAL — inside the try the broad `except Exception` (~1205) would swallow it and mask it as SystemStatus.ERROR + return False, defeating the fix. Use 4-space indentation matching start()'s body (8 spaces for the `if`, 12 for the raise args). The guard:

    if self._live_runner is None or self._error_policy is None: raise StateError with positional args "LiveTradingSystem" and "unwired", plus keyword args required_state="built via build_live_system() (LiveRunner/ErrorPolicy attached)" and operation="start". These fields match the StateError signature in core/exceptions/base.py (entity_id, current_state, required_state=None, operation=None). The raise MUST propagate unhandled (hard programming-error signal for construction outside build_live_system()); it must NOT be caught-and-returned-False.
  </action>
  <verify>
    <automated>poetry run python -c "import itrader.trading_system.live_trading_system as m; from itrader.core.exceptions import StateError; import inspect; src=inspect.getsource(m.LiveTradingSystem.start); g=src.index('self._live_runner is None'); t=src.index('try:'); s=src.index('_update_status(SystemStatus.STARTING)'); assert g < s < t, 'guard must precede STARTING and try:'"</automated>
  </verify>
  <done>StateError imported on the single existing import line; guard clause present in start() above _update_status(STARTING) and above try:; raises StateError with the four fields; propagates unhandled.</done>
</task>

<task type="auto">
  <name>Task 2: IN-02 — warn on non-joining drain thread in LiveRunner.stop()</name>
  <files>itrader/trading_system/live_runner.py</files>
  <action>
    In LiveRunner.stop() (lines 214-219): the inner block currently joins the drain thread without checking is_alive() after the join, so on a join timeout stop() returns normally while the daemon drain thread is still alive → the facade advertises STOPPED with a live worker.

    Keep `self._stop_event.set()` and the trailing `self._worker_supervisor.stop(timeout=timeout)` unchanged. Modify the `if self._thread is not None:` block so that after `self._thread.join(timeout=timeout)` it checks `self._thread.is_alive()` and, when still alive, logs via `self.logger.warning` a lazy %-formatted message noting the drain thread did not stop within the timeout and is still alive after join (pass `timeout` as the format arg with a `%.1fs` specifier). self.logger is the bound LiveRunner logger (live_runner.py:102). Use 4-space indentation (8 spaces for the join/is-alive lines, matching the method body). Do NOT change any other lines.
  </action>
  <verify>
    <automated>poetry run python -c "import inspect, itrader.trading_system.live_runner as m; s=inspect.getsource(m.LiveRunner.stop); assert 'is_alive()' in s and 'logger.warning' in s and 'join(timeout=timeout)' in s and '_worker_supervisor.stop(timeout=timeout)' in s, s"</automated>
  </verify>
  <done>stop() joins the drain thread then warns via self.logger.warning when is_alive() is still True after the join; stop_event.set() and worker_supervisor.stop() unchanged.</done>
</task>

</tasks>

<verification>
Run all guardrail gates (non-isolated, current feature branch, `poetry run pytest` NOT `make test`):

1. Imports clean: `poetry run python -c "import itrader.trading_system.live_trading_system, itrader.trading_system.live_runner"`
2. Types clean: `poetry run mypy itrader`
3. Inertness gate green (proves backtest path stays live-stack-free): `poetry run pytest tests/integration/test_okx_inertness.py`
4. Backtest oracle byte-exact (134 / 46189.87730727451; trivially unaffected — live-only edits): `poetry run pytest tests/integration/test_backtest_oracle.py`
5. Existing LiveRunner / LiveTradingSystem start/stop unit tests: `poetry run pytest -k "live_runner or live_trading_system or (start or stop)" tests/unit`
</verification>

<success_criteria>
- WR-02: start() raises unhandled StateError when _live_runner or _error_policy is None, positioned above the try/STARTING so the broad except cannot swallow it.
- IN-02: stop() warns when the drain thread outlives its join timeout.
- Both files remain 4-space indented (no tab introduced).
- mypy clean; imports clean; inertness + oracle gates green; live start/stop unit tests pass.
</success_criteria>

<output>
Create `.planning/quick/260713-phm-fix-phase-06-review-findings-wr-02-typed/260713-phm-SUMMARY.md` when done.
</output>

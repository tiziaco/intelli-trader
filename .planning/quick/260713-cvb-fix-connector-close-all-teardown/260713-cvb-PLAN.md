---
phase: quick-260713-cvb
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - itrader/connectors/provider.py
  - tests/unit/connectors/test_provider.py
autonomous: true
requirements: [WR-02]
must_haves:
  truths:
    - "close_all() never propagates a disconnect() exception (WR-02)"
    - "close_all() disconnects every remaining memoized connector even when one raises"
    - "close_all() always empties the memo (finally-clear), so a partial teardown never strands connectors"
    - "ConnectorProvider owns a bound logger and logs each disconnect failure with a stack trace"
    - "test_okx_inertness.py stays green — provider.py pulls nothing heavy"
  artifacts:
    - itrader/connectors/provider.py
    - tests/unit/connectors/test_provider.py
  key_links:
    - "provider.__init__ binds self.logger = get_itrader_logger().bind(component=\"ConnectorProvider\") (NOT self._logger)"
    - "close_all() try/finally: memo.clear() in finally, per-connector try/except in the loop"
    - "from itrader.logger import get_itrader_logger stays inert (already loaded at itrader import)"
---

<objective>
Fix WR-02 from `.planning/phases/05-venue-registry-bundle/05-REVIEW.md`: `ConnectorProvider.close_all`
propagates the first `disconnect()` exception, so the remaining memoized connectors are never
disconnected and `self._memo.clear()` never runs — leaking authenticated venue sockets / asyncio loops.

Isolate each `disconnect()` in a per-connector try/except, always clear the memo in a `finally`, and
log each failure through a bound logger. Add a unit test proving a raising `disconnect()` no longer
strands the rest of the fan-out.

Purpose: Make live-teardown robust to a single misbehaving connector — the whole justification for this
class is multi-builder / future per-`account_id` sharing of MANY connectors, where a mid-loop raise
currently orphans every connector after it.
Output: Hardened `close_all()` + a bound logger on `ConnectorProvider`, plus a regression test.
</objective>

<execution_context>
@$HOME/.claude/gsd-core/workflows/execute-plan.md
@$HOME/.claude/gsd-core/templates/summary.md
</execution_context>

<context>
@.planning/STATE.md
@.planning/phases/05-venue-registry-bundle/05-REVIEW.md
@itrader/connectors/provider.py
@tests/unit/connectors/test_provider.py

# Logger convention reference — provider.py must mirror this exact call
@itrader/connectors/okx.py
</context>

<tasks>

<task type="auto">
  <name>Task 1: Harden ConnectorProvider.close_all and give the class a bound logger</name>
  <files>itrader/connectors/provider.py</files>
  <action>
Edit `itrader/connectors/provider.py` (4-SPACE indentation — this file is space-indented per its
module docstring line 28; do NOT introduce tabs).

Add a module-level runtime import: `from itrader.logger import get_itrader_logger`. Place it after the
existing `from typing import ...` line (line 33), as a plain runtime import (NOT under `TYPE_CHECKING`).
This import is inertness-safe: `itrader.logger` is already initialized at `itrader` package import time
and pulls no ccxt/async/sql, and it is not in the `test_okx_inertness.py` `_FORBIDDEN` set. Keep every
other import unchanged.

In `ConnectorProvider.__init__` (currently sets `self._plugins` and `self._memo`), bind a component
logger as the LAST statement of the body:
`self.logger = get_itrader_logger().bind(component="ConnectorProvider")`.
TRAP: the review's suggested snippet references `self._logger`, but this class has NO logger attribute
today — bind it as `self.logger` (public, matching the codebase convention shown at
`itrader/connectors/okx.py:77` `self.logger = get_itrader_logger().bind(component="OkxConnector")`).
`get_itrader_logger()` returns `ITraderStructLogger` and `.bind(**kw)` returns `ITraderStructLogger`, so
`self.logger` type-checks under `mypy --strict` with no explicit annotation.

Rewrite `close_all` (currently the bare for-loop over `self._memo.values()` followed by
`self._memo.clear()`) to: wrap the whole for-loop in `try:` / `finally:`, put `self._memo.clear()` in the
`finally` so the memo is ALWAYS emptied; inside the loop wrap `connector.disconnect()` in its own
`try: ... except Exception: ...` that calls `self.logger.error("connector disconnect failed",
exc_info=True)` and continues to the next connector. Preserve the existing docstring
("Disconnect every memoized connector exactly once, then drop the memo."). Do NOT catch
`BaseException` — catch `Exception` only (a per-connector try/except mirroring the per-symbol isolation
already used in `OkxExchange.catch_up_missed_fills`).

Do NOT change `get`, the `ConnectorPlugin` Protocol, the memo key shape, or `connectors/__init__.py`
(the barrel stays untouched to preserve the inertness surface).
  </action>
  <verify>
    <automated>PYTHONPATH="$PWD" poetry run mypy itrader/connectors/provider.py</automated>
  </verify>
  <done>
provider.py imports `get_itrader_logger` at module scope; `__init__` binds `self.logger` with
`component="ConnectorProvider"`; `close_all` uses try/finally with `self._memo.clear()` in the finally
and a per-connector try/except-Exception logging `exc_info=True`; `mypy --strict` is clean on the file.
  </done>
</task>

<task type="auto">
  <name>Task 2: Add a regression test — a raising disconnect() still clears the memo and disconnects the rest</name>
  <files>tests/unit/connectors/test_provider.py</files>
  <action>
Append to the EXISTING `tests/unit/connectors/test_provider.py` (do NOT rewrite the file, do NOT add an
`__init__.py` — this directory is deliberately package-less per the connectors conftest; adding one
recreates the tests/unit vs tests/integration package-collision hazard). Match the existing file's style:
plain module-level `def test_...()` functions, simple hand-rolled fakes (the file already defines
`_FakeConnector` / `_FakeConnectorPlugin`), no mock library, no real ccxt. The `unit` marker is
auto-applied by folder location — do NOT add a marker by hand.

Add two small doubles near the existing fakes:
- `_RaisingConnector`: a `LiveConnector`-shaped double with `disconnect_calls` counter whose
  `disconnect()` increments the counter THEN raises (e.g. `RuntimeError`).
- `_RaisingConnectorPlugin`: a structural `ConnectorPlugin` whose `build(self, spec)` returns a fresh
  `_RaisingConnector` (mirror the `# noqa: ANN001, ANN201` annotations on the existing
  `_FakeConnectorPlugin.build`).

Add one test, e.g. `test_close_all_isolates_a_raising_disconnect_and_clears_the_memo`:
- Construct `ConnectorProvider` registering the raising plugin under a DIFFERENT venue key than the good
  plugin, e.g. `ConnectorProvider({"boom": _RaisingConnectorPlugin(), "okx": _FakeConnectorPlugin()})`.
- `get` the raising connector FIRST (so it is memoized ahead of the survivor — a naive loop would abort
  before reaching the survivor), then `get` a good `_FakeConnector` survivor under the "okx" key.
- Call `provider.close_all()` — assert it does NOT raise (call it directly; no `pytest.raises`).
- Assert the raising connector's `disconnect_calls == 1` (it WAS attempted), the survivor's
  `disconnect_calls == 1` (the loop CONTINUED past the raise), and `provider._memo == {}` (the memo was
  cleared in the `finally`).

Keep the four existing tests unchanged.
  </action>
  <verify>
    <automated>PYTHONPATH="$PWD" poetry run pytest tests/unit/connectors/test_provider.py -q</automated>
  </verify>
  <done>
The new test passes alongside the existing four; it proves close_all does not propagate, still disconnects
the survivor after a mid-loop raise, and empties `_memo`. No `__init__.py` added to the test dir.
  </done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| engine thread → venue connectors (teardown) | A single connector's `disconnect()` failure must not abort the fan-out |

## STRIDE Threat Register

| Threat ID | Category | Component | Severity | Disposition | Mitigation Plan |
|-----------|----------|-----------|----------|-------------|-----------------|
| T-QUICK-01 | Denial of Service | `ConnectorProvider.close_all` | medium | mitigate | Per-connector try/except + finally-clear so a raising `disconnect()` cannot strand remaining authenticated sockets / asyncio loops (resource-exhaustion leak). Regression test asserts survivor disconnect + memo clear. |
| T-QUICK-02 | Information disclosure | failure logging | low | accept | `self.logger.error(..., exc_info=True)` logs a stack trace on disconnect failure; connectors own their own secret-scrub, no credentials are logged here. No new package installs. |
</threat_model>

<verification>
Run all three gates (prepend `PYTHONPATH="$PWD"` to defend against editable-install worktree shadowing;
use `poetry run pytest` directly — NOT `make test`, which aborts on a missing `.env` in worktrees and
disables logs):

- `PYTHONPATH="$PWD" poetry run pytest tests/integration/test_okx_inertness.py -q` — inertness gate stays
  green (provider.py's new logger import pulls nothing heavy; provider.py is not on the backtest graph).
- `PYTHONPATH="$PWD" poetry run pytest tests/unit/connectors/test_provider.py -q` — all five tests pass.
- `PYTHONPATH="$PWD" poetry run mypy itrader/connectors/provider.py` — strict-clean (`self.logger`
  type-checks as `ITraderStructLogger`).
</verification>

<success_criteria>
- `close_all()` isolates each `disconnect()` and always clears `self._memo` (WR-02 closed).
- `ConnectorProvider` binds `self.logger` (component="ConnectorProvider") in `__init__` and logs each
  disconnect failure with `exc_info=True`.
- New regression test proves a raising `disconnect()` neither propagates nor strands the survivor, and
  the memo ends empty.
- `test_okx_inertness.py` green; `mypy --strict` clean on `itrader/connectors/provider.py`.
- 4-space indentation preserved; barrel `connectors/__init__.py` untouched; test dir stays package-less.
</success_criteria>

<output>
Create `.planning/quick/260713-cvb-fix-connector-close-all-teardown/260713-cvb-SUMMARY.md` when done
</output>

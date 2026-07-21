---
phase: quick/260720-qfs
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - itrader/strategy_handler/lifecycle/manager.py
  - tests/unit/strategy/test_strategy_command_verbs.py
autonomous: true
requirements: [WR2-01]

must_haves:
  truths:
    - "An `add` whose config supplies a MALFORMED portfolio_id is rejected outright: nothing constructed, nothing in the roster, no strategy_registry row, no strategy_portfolio_subscriptions row, no UniversePollEvent, exactly one WARNING."
    - "An `add` with an ABSENT portfolio_id (key missing OR explicit null) is unchanged and SILENT: registered, persisted, subscribed_portfolios == [], poll emitted, zero warnings (D-09 legal no-subscription state)."
    - "An `add` with a valid UUID portfolio_id is unchanged: registered, persisted, one subscription row, zero warnings."
    - "`subscribe_portfolio` / `unsubscribe_portfolio` on a malformed portfolio_id are byte-unchanged: warn + ignore, strategy STAYS registered."
    - "`_add_strategy_verb` still never raises into the queue (D-10); the new arm warns and returns."
  artifacts:
    - itrader/strategy_handler/lifecycle/manager.py
    - tests/unit/strategy/test_strategy_command_verbs.py
  key_links:
    - "The malformed check sits BEFORE `build_strategy` and before every state mutation, so the reject path never unwinds a completed `add_strategy` roster insert."
    - "The check sits OUTSIDE both tiers of the CR-01 zone-1 guard, which stays scoped to the single `build_strategy` call — the guard is not widened or restructured."
    - "`_portfolio_id_supplied` is the SOLE presence probe and owns the `\"portfolio_id\"` key name + the `isinstance(config, dict)` guard, adjacent to `_portfolio_id_from`; no call site re-reads `event.config`."
---

<objective>
Close Phase 10.1 re-review finding **WR2-01**: `StrategyLifecycleManager._add_strategy_verb`
treats a MALFORMED `config["portfolio_id"]` as the legal "no subscription requested" state and
proceeds silently, producing a registered, persisted, warming strategy with zero subscriptions
that emits no SignalEvent forever.

Make a malformed portfolio_id **reject the whole add** (warn + return, nothing constructed or
persisted) while an **absent** portfolio_id stays a clean legal no-op (D-09), and pin the two
light verbs so this fix cannot drift them.

Purpose: eliminate a healthy-looking-engine-that-trades-nothing failure mode that D-19 rates as
worse than failing loudly.
Output: one new manager helper + one relocated/gated parse in `_add_strategy_verb`, plus six
tests in the existing verb suite.
</objective>

<execution_context>
@$HOME/.claude/gsd-core/workflows/execute-plan.md
@$HOME/.claude/gsd-core/templates/summary.md
</execution_context>

<context>
@.planning/STATE.md
@CLAUDE.md
@itrader/strategy_handler/lifecycle/manager.py
@tests/unit/strategy/test_strategy_command_verbs.py
</context>

<verified_findings>
**The review was audited against the current tree before this plan was written. CODE WINS.**

CONFIRMED (the defect is real, exactly as described):

- `_portfolio_id_from` collapses four outcomes into one `None`: config-not-a-dict, key absent,
  value not a non-empty `str`, UUID parse failure.
- `_add_strategy_verb` reads that `None` as the legal absent state and proceeds silently.
  `subscribe_portfolio` / `unsubscribe_portfolio` warn unconditionally on `None`. So the
  diagnosis genuinely depends on which verb the operator used.
- The blast-radius claim holds: `owe` removed the `int` fallback, so `{"portfolio_id": "7"}`
  now lands in the silent arm. There is an existing test
  (`test_a_bare_numeric_portfolio_id_is_a_loud_no_op`) pinning that for `subscribe_portfolio`
  and **none at all** for `add`.
- The downstream consequence is real: `strategies_handler.py` fans intents with
  `for portfolio_id in strategy.subscribed_portfolios:` wrapping the `SignalEvent(...)`
  construction, so an empty list means literally zero SignalEvents.
- The ordering hazard described in the task brief is REAL and confirmed by reading the method:
  `self._managed.add_strategy(strategy)` runs FIRST, then `self._portfolio_id_from(event)`,
  then `_persist_strategy`. A rejection at the current call site would have to undo a completed
  roster insert. **This is why the new check goes early.**
- The CR-01 two-tier zone-1 guard wraps exactly the single `build_strategy(...)` call
  (tier 1 `except (StrategyAdmissionError, ValueError)`, tier 2 `except Exception`). An
  insertion above the blob construction sits outside both tiers.
- `itrader/strategy_handler/lifecycle/manager.py` is **pure TABS** (measured: 969 tab-indented
  lines, 0 space-indented lines). `tests/unit/strategy/test_strategy_command_verbs.py` is
  **pure 4-space** (697 space-indented, 0 tab-indented).
- `itrader.strategy_handler.lifecycle.*` is NOT under any `ignore_errors` mypy override (only
  `my_strategies.*` is), so the `mypy --strict` gate is real for this file.

WRONG IN THE REVIEW (line numbers had drifted before this plan was written — cite by SYMBOL):

- Review cites the add call site as `manager.py:485-491`. **Actual: 501-508.** (+16)
- Review cites `_portfolio_id_from` as `:282-314`. **Actual: 294-326.** (+12)

CORRECTION TO THE TASK BRIEF (a better mechanism already exists in the repo):

- The brief assumes these tests depend on `caplog` and warns about `ITRADER_DISABLE_LOGS`.
  The target test file **bans caplog outright** (its module docstring: "Assertions read STATE
  and the STORE, never log capture") and already ships `_LogSpy` — a collaborator spy injected
  via `monkeypatch.setattr(handler._lifecycle, "logger", spy)`, used by three existing add
  tests. **Use `_LogSpy`, not caplog.** The warning-tier assertions are then independent of
  logging configuration entirely. The "do not use `make test`" constraint still stands as a
  gate-command rule, but no test written here is log-config sensitive.
</verified_findings>

<tasks>

<task type="auto" tdd="true">
  <name>Task 1: Write the WR2-01 tests, malformed-reject FAILING FIRST</name>
  <files>tests/unit/strategy/test_strategy_command_verbs.py</files>
  <behavior>
    - Malformed portfolio_id on `add` (parametrized over `"7"`, `"not-a-uuid"`, `""`, `7`):
      roster empty, `store.get(name) is None`, `store.portfolio_subscriptions(name) == []`,
      queue empty (no `UniversePollEvent`), exactly 1 spy warning, 0 spy errors.
    - Absent portfolio_id on `add` (key omitted): registered, row present,
      `subscribed_portfolios == []`, no subscription rows, `UniversePollEvent` emitted,
      **0 warnings**.
    - Explicit-null portfolio_id on `add` (`config["portfolio_id"] = None`): identical to
      absent — registered, persisted, 0 warnings. Pins the FastAPI/Pydantic
      `str | None = None` shape as the legal unsubscribed payload.
    - Valid UUID portfolio_id on `add`: registered, row present,
      `subscribed_portfolios == [UUID(_P1)]`, `portfolio_subscriptions(name) == [_P1]`,
      0 warnings.
    - Drift pin, parametrized over `subscribe_portfolio` / `unsubscribe_portfolio` with
      `config={"portfolio_id": "7"}`: exactly 1 warning, no subscription written, and the
      strategy STAYS in the roster — proving only `add` gained the reject.
  </behavior>
  <action>
Append the new tests to the `add`-verb section of
`tests/unit/strategy/test_strategy_command_verbs.py`, after the existing
`test_add_of_a_finer_than_base_timeframe_is_a_loud_reject` / `test_add_of_a_pair_strategy_succeeds`
family. Keep them in this file — do NOT create a new file. Reuse the existing helpers verbatim:
`_add_handler`, `_handler`, `_sma_add_config`, `_LogSpy`, `_drain`, the `store` fixture, and the
`_P1` / `_NAME` constants.

Build each add payload as `config = _sma_add_config(["ETHUSD"])` then set `config["portfolio_id"]`
for the case under test (omit the assignment entirely for the absent case). Dispatch through
`StrategyCommandEvent.add(strategy_name=..., strategy_type="SMAMACDStrategy", config=config,
time=_T)` — that factory folds `strategy_type` into a copy of the config, so `portfolio_id`
rides inside the payload where `_add_strategy_verb` reads it.

Inject the log spy the way the three existing add tests do:
`spy = _LogSpy()` then `monkeypatch.setattr(handler._lifecycle, "logger", spy)`. Do NOT use
`caplog` — the module docstring bans it and `_LogSpy` is the sanctioned mechanism.

Write a docstring on each test naming WR2-01 and stating WHY, per the file's established style:
the malformed test should record that a registered-but-unsubscribed strategy computes signals
and fans them to nobody, and that the identical payload sent as `subscribe_portfolio` already
warns. The absent/null tests should record that D-09 makes no-subscription a LEGAL state that
`subscribe_portfolio` can wire later, so it must stay silent. The drift-pin test should record
that the two light verbs must keep warn-and-ignore semantics and must NOT gain the reject.

Cite by symbol (`_add_strategy_verb`, `_portfolio_id_from`, `_portfolio_id_supplied`), never by
line number — line numbers in this area have already drifted twice.

THEN RUN THE MALFORMED TEST AND CONFIRM IT FAILS FOR THE RIGHT REASON before touching any
production code. The correct RED signal is the assertion on the roster or the registry row:
the strategy IS currently registered and IS persisted, so you should see the roster assertion
report a non-empty list (e.g. `['malformed_pid'] == []`) or the row assertion report a
non-`None` row. A collection error, an import error, a fixture error, a `TypeError`, or a
failure on the warning-count assertion instead is the WRONG reason — fix the test, do not
proceed. Record the observed failure text in the summary.

The other five tests should PASS against current code (they pin existing behavior); if any of
them fails now, stop and report — that would mean current behavior differs from what this plan
assumes.
  </action>
  <verify>
    <automated>PYTHONPATH="$PWD" poetry run pytest tests/unit/strategy/test_strategy_command_verbs.py -k "portfolio_id" -v; test "$(git diff -U0 -- tests/unit/strategy/test_strategy_command_verbs.py | awk '/^\+[^+]/ && /^\+\t/' | wc -l | tr -d ' ')" = "0"</automated>
  </verify>
  <done>The malformed-reject test(s) FAIL with a roster/registry-row assertion (the documented RED reason, quoted in the summary); the absent, explicit-null, valid-UUID and light-verb-drift tests PASS; zero tab-indented lines were added to the 4-space test file.</done>
</task>

<task type="auto" tdd="true">
  <name>Task 2: Add the presence probe and the early malformed-reject gate</name>
  <files>itrader/strategy_handler/lifecycle/manager.py</files>
  <behavior>
    - `_portfolio_id_supplied(event)` returns False when config is not a dict, when the key is
      absent, and when the value is exactly `None`; True for every other supplied value.
    - `_add_strategy_verb` rejects (warn + return) when the parse yields `None` AND the probe
      reports supplied; proceeds unchanged otherwise.
    - The subscribe call later in the method reuses the already-parsed handle rather than
      re-parsing.
  </behavior>
  <action>
`itrader/strategy_handler/lifecycle/manager.py` is a **pure TABS file** (verified: 0
space-indented lines). Indent every added line with TABS, matching the surrounding bodies
byte-for-byte. Never normalize; do not reflow untouched lines.

**(a) New sibling helper `_portfolio_id_supplied`.** Place it immediately AFTER
`_portfolio_id_from`, before `_add_strategy_verb`, so the parser and its presence probe read as
one pair. Signature: takes the `StrategyCommandEvent`, returns `bool`. Body: read `event.config`;
return False if it is not a `dict`; otherwise return whether `config.get("portfolio_id")` is not
`None`.

Keep the `"portfolio_id"` key name and the `isinstance(config, dict)` guard INSIDE this helper —
do NOT re-read `event.config` at the call site, which would duplicate the parsing
`_portfolio_id_from` centralizes and let the two drift.

Docstring must state, per this file's decision-anchored style and tagged **WR2-01**:
  - it is the presence probe that makes ABSENT and MALFORMED distinguishable, because
    `_portfolio_id_from` deliberately collapses config-not-a-dict / key-absent / wrong-type /
    unparseable-UUID into one `None` — right for the two light verbs (which warn on every
    `None`) and wrong for `add`, where absence is legal (D-09) and malformation is operator
    error;
  - why the key name and dict guard live here rather than at the call site;
  - why an explicit `None` VALUE counts as NOT supplied: a FastAPI/Pydantic model declaring
    `portfolio_id: str | None = None` serializes the unsubscribed case as a null on EVERY add,
    so a bare key-presence probe would reject the most likely shape of the legal
    no-subscription payload. Every other value — non-`str`, empty `str`, non-UUID `str` — is
    supplied-and-malformed.

**(b) Early reject gate in `_add_strategy_verb`.** Insert AFTER the D-02 duplicate-name check
and BEFORE the blob construction / `rec` dict that feeds `build_strategy`. Assign
`portfolio_id = self._portfolio_id_from(event)` there, then reject when it is `None` AND
`self._portfolio_id_supplied(event)` is True: `self.logger.warning(...)` followed by `return`.

Placement is load-bearing and the comment must say so: this is a pure payload check with no
dependency on the constructed object, so it belongs ahead of every state mutation — rejecting at
the old call site would have to UNDO a completed `add_strategy` roster insert. It is also
deliberately OUTSIDE the CR-01 two-tier zone-1 guard, which stays scoped to the single
`build_strategy` call. **Do NOT widen, move, or restructure that guard** — its own point 3
forbids exactly that. The new arm raises nothing, so it needs no guard.

The warning message must name the strategy by `event.strategy_name`, state that
`config["portfolio_id"]` is present but unparseable, state that nothing was registered or
persisted, explain the consequence being prevented (a registered strategy with no subscription
computes signals and fans them to nobody), and tell the operator both remedies: re-issue with a
UUID, or omit the key to add it unsubscribed. Follow the tier-1 convention already in this
method — name the KIND/condition, never echo payload values.

Comment block above the gate, tagged **WR2-01**, must record: that reject-without-registering is
this method's established idiom (the catalog gate, the D-02 duplicate gate, the SHORT-01 arm),
not a new policy; that ABSENT stays a clean legal no-op per D-09 and `subscribe_portfolio` can
wire it later; and that the identical payload sent as `subscribe_portfolio` already warns, so
the diagnosis must not depend on which verb the operator used.

**(c) Reuse the parse at the old call site.** Where `_add_strategy_verb` currently does
`portfolio_id = self._portfolio_id_from(event)` followed by the `if portfolio_id is not None:`
subscribe, DELETE the re-parse line and keep the `if`, now reading the handle bound in (b).
`_portfolio_id_from` must end up called exactly ONCE in this method. Update the existing comment
above that subscribe block so it no longer claims the parse happens there — point it at the
early gate by symbol and keep the D-09 absent-is-legal sentence, which is still true.

Do NOT touch the `subscribe_portfolio` / `unsubscribe_portfolio` arms in
`on_strategy_command`. They keep calling `_portfolio_id_from` and warning unconditionally on
`None` — that is correct for them and is pinned by Task 1's drift test.

Do NOT change `_portfolio_id_from` itself: its four-outcomes-to-one-`None` collapse stays, and
the two light verbs keep behaving exactly as they do today.
  </action>
  <verify>
    <automated>PYTHONPATH="$PWD" poetry run pytest tests/unit/strategy/test_strategy_command_verbs.py -v && test "$(grep -c '_portfolio_id_supplied' itrader/strategy_handler/lifecycle/manager.py)" = "2" && test "$(grep -c '_portfolio_id_from' itrader/strategy_handler/lifecycle/manager.py)" = "4" && test "$(git diff -U0 -- itrader/strategy_handler/lifecycle/manager.py | awk '/^\+[^+]/ && /^\+ /' | wc -l | tr -d ' ')" = "0"</automated>
  </verify>
  <done>All tests in the verb suite pass including the six new ones; `_portfolio_id_supplied` occurs exactly twice (definition + one call); `_portfolio_id_from` occurs exactly four times (definition + one call in `_add_strategy_verb` + two in the light verbs); zero space-indented lines were added to the TABS file.</done>
</task>

<task type="auto">
  <name>Task 3: Full gates — mypy, strategy suite, byte-exact oracle</name>
  <files>itrader/strategy_handler/lifecycle/manager.py, tests/unit/strategy/test_strategy_command_verbs.py</files>
  <action>
Run the full gate set. In a worktree, prepend `PYTHONPATH="$PWD"` to EVERY pytest/mypy
invocation — the editable `.venv` install otherwise resolves to the main checkout and yields a
false green.

Do NOT use `make test` for any gate: it exports `ITRADER_DISABLE_LOGS=true` and aborts on a
missing `.env` in worktrees. Use `poetry run pytest` directly.

1. `mypy --strict` clean over `itrader` (this module is in scope — no `ignore_errors` override
   covers `strategy_handler.lifecycle`).
2. The strategy unit suite plus the exceptions suite green.
3. The byte-exact oracle: `tests/integration/test_backtest_oracle.py` must still report
   **134 / 46189.87730727451**. This change is live-control-plane-only and backtest-dark (no
   backtest path emits a STRATEGY_COMMAND verb), so any oracle movement means something
   unintended was touched — stop and report rather than re-baselining.

If any gate fails, fix forward within the scope of this plan; do not weaken a test or a gate to
make it pass.
  </action>
  <verify>
    <automated>PYTHONPATH="$PWD" poetry run mypy && PYTHONPATH="$PWD" poetry run pytest tests/unit/strategy tests/unit/core/test_exceptions.py -q && PYTHONPATH="$PWD" poetry run pytest tests/integration/test_backtest_oracle.py -q</automated>
  </verify>
  <done>mypy reports no issues; the strategy + exceptions suites are green; the oracle test passes byte-exact at 134 / 46189.87730727451, with the trade count and equity value quoted in the summary.</done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| operator/FastAPI → `LiveTradingSystem.add_event` → `STRATEGY_COMMAND` → `_add_strategy_verb` | Untrusted external payload (`event.config`, including `portfolio_id`) crosses into live strategy state and SQL |

## STRIDE Threat Register

| Threat ID | Category | Component | Severity | Disposition | Mitigation Plan |
|-----------|----------|-----------|----------|-------------|-----------------|
| T-qfs-01 | Denial of Service (silent) | `_add_strategy_verb` portfolio subscription | high | mitigate | A malformed `portfolio_id` currently yields a registered, persisted, warming strategy that emits zero SignalEvents forever — a self-inflicted trading outage that looks healthy. Task 2's early gate rejects the add outright and warns, so the failure is loud and no bad state is created. |
| T-qfs-02 | Information Disclosure | WR2-01 warning message | low | mitigate | The new warning names `event.strategy_name` and the CONDITION only; it never echoes the operator-supplied `portfolio_id` value into the log sink, following the P8 declared-fields-only precedent already used by this method's tier-1 arm. |
| T-qfs-03 | Denial of Service (halt latch) | `_add_strategy_verb` never-raise contract (D-10) | high | accept | The new arm warns and returns; it raises nothing and sits outside the CR-01 two-tier zone-1 guard, which is left byte-unchanged. Routine bad operator input therefore still cannot reach `ErrorPolicy.record_failure` → tripwire → `halt()`. Pinned by the existing zone-1 tests plus Task 1's malformed tests, which assert a clean return. |
| T-qfs-04 | Tampering | dependency surface | low | accept | No package-manager install: zero new dependencies, no `poetry` change (the v1.8 milestone gate forbids it — a new lib regresses import inertness). No Package Legitimacy Audit is required because no install task exists. |
</threat_model>

<verification>
- `_add_strategy_verb` rejects a supplied-but-unparseable `portfolio_id` before constructing,
  registering or persisting anything, and warns exactly once.
- An absent or explicitly-null `portfolio_id` still produces a registered, persisted,
  unsubscribed strategy with a `UniversePollEvent` and NO warning.
- A valid UUID `portfolio_id` still produces one live subscription and one child row.
- `subscribe_portfolio` / `unsubscribe_portfolio` are behaviorally unchanged on malformed input.
- The CR-01 two-tier zone-1 guard is untouched (no diff hunk inside the
  `try:` / `except (StrategyAdmissionError, ValueError):` / `except Exception:` block around
  `build_strategy`).
- Indentation: zero space-indented lines added to the TABS module; zero tab-indented lines added
  to the 4-space test file. Checked on ADDED DIFF LINES ONLY — never as a whole-file scan, which
  false-fails on untouched tab files carrying space-aligned docstring prose.
- `mypy --strict` clean; strategy + exceptions suites green; oracle byte-exact
  (134 / 46189.87730727451).
</verification>

<success_criteria>
- WR2-01 is closed: malformed rejects the whole add, absent stays legal and silent, the two
  light verbs are unmoved.
- The malformed-reject test was written and confirmed FAILING FOR THE RIGHT REASON before the
  fix, with the observed failure text recorded in the summary.
- New code is tagged WR2-01 and cites collaborators by SYMBOL, never by line number.
- All three gates green; no new dependency; no `make test` used as a gate.
</success_criteria>

<output>
Create `.planning/quick/260720-qfs-close-10-1-re-review-wr2-01-reject-the-a/260720-qfs-SUMMARY.md` when done
</output>
</content>
</invoke>

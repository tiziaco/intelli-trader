---
phase: quick-260610-sjp
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - itrader/portfolio_handler/portfolio.py
  - itrader/events_handler/events/signal.py
  - itrader/events_handler/events/order.py
  - itrader/events_handler/events/fill.py
  - itrader/order_handler/order.py
  - .planning/codebase/FIX-LIST.md
autonomous: true
requirements: [FL-01, FL-02]

must_haves:
  truths:
    - "Portfolio.py raises typed domain exceptions (not bare ValueError) at all 7 former sites"
    - "Signal/Order/Fill event facts annotate portfolio_id as PortfolioId (UUIDv7-backed), not int"
    - "mypy --strict over itrader/ stays clean after the annotation retype (FL-02 gate)"
    - "BTCUSD golden master oracle test still passes byte-exact (behavior preserved)"
    - "FIX-LIST.md Status column reconciled: FL-01/FL-02 done, FL-03/FL-04 marked already-shipped"
  artifacts:
    - path: "itrader/portfolio_handler/portfolio.py"
      provides: "Typed exceptions at the 7 former ValueError sites (FL-01)"
      contains: "PortfolioError"
    - path: "itrader/events_handler/events/signal.py"
      provides: "portfolio_id PortfolioId annotation (FL-02)"
      contains: "PortfolioId"
    - path: "itrader/events_handler/events/order.py"
      provides: "portfolio_id PortfolioId annotation (FL-02)"
      contains: "PortfolioId"
    - path: "itrader/events_handler/events/fill.py"
      provides: "portfolio_id PortfolioId annotation (FL-02)"
      contains: "PortfolioId"
  key_links:
    - from: "itrader/order_handler/order.py"
      to: "itrader/events_handler/events/order.py"
      via: "Order.portfolio_id flows into OrderEvent/FillEvent construction"
      pattern: "portfolio_id"
---

<objective>
Close two fix-list residuals left undone by phases already marked complete, then reconcile
the FIX-LIST.md ledger.

- FL-01 (exception migration): replace 7 bare raise ValueError sites in portfolio.py with the
  MOST APPROPRIATE typed domain exception per site.
- FL-02 (annotation retype): retype portfolio_id int to portfolio_id PortfolioId (UUIDv7-backed,
  already defined in core/ids.py) on the Signal/Order/Fill event facts, matching the sibling
  strategy_id to StrategyId treatment from Phase 5.
- Reconcile FIX-LIST.md Status column for FL-01..FL-04.

Purpose: Discharge the two true carry-forward residuals (#7/#37, #10) and bring the ledger
honest. v1.1 is BEHAVIOR-PRESERVING — FL-01 is Golden-path?=no, FL-02 is annotation-only
(runtime already carries a UUID), so neither changes runtime numbers.

Output: source files edited (portfolio.py + 3 event files, plus order.py only if mypy demands),
FIX-LIST.md reconciled, golden master confirmed byte-exact, mypy --strict clean.
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/execute-plan.md
</execution_context>

<context>
@./CLAUDE.md

<interfaces>
Typed exception constructor signatures (from itrader/core/exceptions/). Use directly.

From itrader/core/exceptions/base.py:
- ValidationError(field: str, value: Optional[str] = None, message: Optional[str] = None)
- StateError(entity_id: uuid.UUID | int | str, current_state: str, required_state: Optional[str] = None, operation: Optional[str] = None)
- ConfigurationError(config_key: Optional[str] = None, config_value: Optional[object] = None, reason: Optional[str] = None)

From itrader/core/exceptions/portfolio.py:
- PortfolioError(ITraderError)  # base — message-only via super().__init__(msg)
- InsufficientFundsError(required_cash: float, available_cash: float, transaction_id=None)
- PortfolioStateError(StateError)(portfolio_id, current_state, required_state=None, operation=None)

From itrader/core/ids.py:
- PortfolioId = NewType("PortfolioId", uuid.UUID)   # already defined; runtime-identity over UUID
- StrategyId  = NewType("StrategyId", uuid.UUID)    # sibling pattern already applied to events

Note: itrader/order_handler/order.py:55 already declares portfolio_id: "PortfolioId | int" with a
transitional "02-05 carry-over" comment — the Order entity tolerates both today, so retyping the
EVENTS to PortfolioId is upstream-compatible.
</interfaces>
</context>

<tasks>

<task type="auto">
  <name>Task 1: FL-01 — replace 7 bare ValueError sites with typed exceptions</name>
  <files>itrader/portfolio_handler/portfolio.py</files>
  <action>
File uses TAB indentation — match it exactly; do not normalize.

Add imports near the existing imports (after the `from itrader.core.ids import PortfolioId` line):
`from itrader.core.exceptions.base import ValidationError, StateError, ConfigurationError`
`from itrader.core.exceptions.portfolio import PortfolioError`
Import only names actually used by the mappings below.

Replace each bare raise ValueError with the mapped typed exception, preserving the original
message intent. PortfolioState enums expose `.value` for the string form.

- :101 negative starting cash in _validate_initial_state ->
  raise ValidationError("cash", str(self.cash_manager.balance), "Portfolio cannot start with negative cash").
  Rationale: input validation on the cash field at construction, not a transaction funds-shortfall;
  InsufficientFundsError's (required, available) shape does not fit "negative starting balance".

- :103 empty name in _validate_initial_state ->
  raise ValidationError("name", message="Portfolio name cannot be empty").

- :124 invalid state transition in set_state ->
  raise StateError(self.portfolio_id, self._state.value, required_state=new_state.value, operation="set_state").
  Rationale: state-machine transition violation. self.portfolio_id is a PortfolioId (uuid.UUID)
  satisfying StateError's entity_id: uuid.UUID | int | str.

- :183 unknown configuration key in update_config ->
  raise ConfigurationError(config_key=key, reason="Unknown configuration key").

- :410 cannot trade in current state in transact_shares ->
  raise StateError(self.portfolio_id, self.state.value, required_state=PortfolioState.ACTIVE.value, operation="transact_shares").

- :431 max positions limit reached in _validate_transaction ->
  raise PortfolioError(f"Maximum positions limit reached: {self.config.limits.max_positions}").
  Rationale: a domain limit breach, not a state-machine or field-validation error; PortfolioError
  (base, message-only) is the appropriate domain-typed parent.

- :436 transaction value exceeds limit in _validate_transaction ->
  raise PortfolioError(f"Transaction value {transaction_value} exceeds limit {self.config.limits.max_position_value}").

Do NOT change any control flow, conditions, or message informational content — only the exception
TYPE and constructor shape. Money stays Decimal; do not introduce float (the str(...) at :101 builds
a diagnostic message, not money math — allowed). Optionally add a one-line `# FL-01:` decision-tag
comment above each changed raise, matching portfolio.py's existing `# D-19` / `# M2-08` anchor style.
  </action>
  <verify>
    <automated>cd /Users/tizianoiacovelli/Desktop/projects/intelli-trader && test "$(grep -c 'raise ValueError' itrader/portfolio_handler/portfolio.py)" = "0" && PYTHONPATH="$PWD" poetry run python -c "import ast; ast.parse(open('itrader/portfolio_handler/portfolio.py').read()); print('parses OK')"</automated>
  </verify>
  <done>All 7 bare raise ValueError sites replaced with typed domain exceptions; file parses; zero raise ValueError remains in portfolio.py; original message intent preserved.</done>
</task>

<task type="auto">
  <name>Task 2: FL-02 — retype portfolio_id int to PortfolioId on event facts</name>
  <files>itrader/events_handler/events/signal.py, itrader/events_handler/events/order.py, itrader/events_handler/events/fill.py, itrader/order_handler/order.py</files>
  <action>
The three event files use 4-SPACE indentation — match it. order.py (entity) uses TABS if edited.

For each of signal.py, order.py (event), fill.py:
1. Add PortfolioId to the `from itrader.core.ids import ...` line:
   - signal.py:11 `import StrategyId` -> `import PortfolioId, StrategyId`.
   - order.py:11 `import OrderId, StrategyId` -> `import OrderId, PortfolioId, StrategyId`.
   - fill.py:14 `import OrderId, StrategyId` -> `import OrderId, PortfolioId, StrategyId`.

2. Retype the field annotation:
   - signal.py:84 `portfolio_id: int` -> `portfolio_id: PortfolioId`.
   - order.py:52 `portfolio_id: int` -> `portfolio_id: PortfolioId`.
   - fill.py:64 `portfolio_id: int` -> `portfolio_id: PortfolioId`.

3. Update the docstring entry for portfolio_id to mirror the sibling strategy_id style: change each
   `portfolio_id: int` docstring line to `portfolio_id: PortfolioId` and note it is the UUIDv7-backed
   portfolio identity. Affected lines: signal.py:49-50, the corresponding entry in order.py's class
   docstring, fill.py:44. Keep wording minimal and consistent with strategy_id's docstring.

4. Add a one-line provenance comment above each retyped field, mirroring the existing
   `# 02-05 carry-over: strategy_id carries a UUIDv7-backed StrategyId...` comment at signal.py:82:
   `# FL-02: portfolio_id carries a UUIDv7-backed PortfolioId (#10 carry-forward).`

5. Do NOT touch the construction sites (order.py:94, fill.py:137 `portfolio_id=order.portfolio_id`).
   The Order ENTITY field at itrader/order_handler/order.py:55 is currently
   `portfolio_id: "PortfolioId | int"`. After the event retype, run mypy --strict (the verify
   command). ONLY IF mypy reports an incompatible-assignment at the construction sites, apply the
   minimal fix: tighten order.py:55 from "PortfolioId | int" to PortfolioId and delete its stale
   "02-05 carry-over: accept both ... not mandated by Task 2" comment (lines 53-54) — the migration
   it waited on is now complete. Annotation-only and behavior-preserving (runtime value is already a
   UUID). order.py is TAB-indented — match it. Do not make this edit pre-emptively.

Runtime is unchanged: PortfolioId = NewType("PortfolioId", uuid.UUID) — identity at runtime.
No float, no money changes.
  </action>
  <verify>
    <automated>cd /Users/tizianoiacovelli/Desktop/projects/intelli-trader && grep -q "portfolio_id: PortfolioId" itrader/events_handler/events/signal.py && grep -q "portfolio_id: PortfolioId" itrader/events_handler/events/order.py && grep -q "portfolio_id: PortfolioId" itrader/events_handler/events/fill.py && PYTHONPATH="$PWD" poetry run mypy --strict itrader/</automated>
  </verify>
  <done>All 3 event facts annotate portfolio_id as PortfolioId with updated import and docstring; mypy --strict over itrader/ reports zero errors (FL-02 gate); order.py:55 tightened only if mypy required it.</done>
</task>

<task type="auto">
  <name>Task 3: Reconcile FIX-LIST.md ledger and confirm behavior preserved</name>
  <files>.planning/codebase/FIX-LIST.md</files>
  <action>
Update the Status column in the Fix-List table (lines 54-57). Leave FL-05..FL-14 untouched
(deferred by design — do not edit their rows).

- FL-01 (row line 54): Status `open` -> `done (quick 260610-sjp)`.
- FL-02 (row line 55): Status `open` -> `done (quick 260610-sjp)`.
- FL-03 (row line 56): Status `open` -> `done (phase 4)`. Already shipped — FillStatus was added in
  Phase 3 / the e2e harness work in Phase 4 covers the test tree; the ledger row was just stale.
- FL-04 (row line 57): Status `open` -> `done (phase 5)`. Already shipped — HARD-03 in Phase 5
  removed the stringly-typed order_type; the ledger row was just stale.

Edit ONLY the Status cell of each of these 4 rows; preserve every other cell verbatim (Category,
Description, File(s):line, Golden-path?, Eligible-in-phase, Origin). Do not touch the surrounding
prose sections.

Behavior-preservation gate (run as verify): the golden-master oracle and full unit suite must pass.
FL-01 is Golden-path?=no and FL-02 is annotation-only, so the BTCUSD oracle (134-trade behavioral
identity + frozen numeric values) must stay byte-exact. The canonical assertions live in
tests/integration/test_backtest_oracle.py.
  </action>
  <verify>
    <automated>cd /Users/tizianoiacovelli/Desktop/projects/intelli-trader && grep -q "FL-01 | exception .*done (quick 260610-sjp)" .planning/codebase/FIX-LIST.md && grep -q "FL-02 | annotation .*done (quick 260610-sjp)" .planning/codebase/FIX-LIST.md && PYTHONPATH="$PWD" poetry run pytest tests/integration/test_backtest_oracle.py tests/unit -q</automated>
  </verify>
  <done>FIX-LIST.md FL-01/FL-02 = done (quick 260610-sjp), FL-03 = done (phase 4), FL-04 = done (phase 5); FL-05..FL-14 unchanged. Oracle behavioral-identity + numeric tests pass byte-exact; full unit suite green.</done>
</task>

</tasks>

<verification>
Run from repo root (/Users/tizianoiacovelli/Desktop/projects/intelli-trader):

1. No bare ValueError remains in portfolio.py:
   `grep -c 'raise ValueError' itrader/portfolio_handler/portfolio.py`  -> must print 0
2. mypy --strict clean (the FL-02 gate that matters most):
   `PYTHONPATH="$PWD" poetry run mypy --strict itrader/`  -> Success: no issues
3. Golden master byte-exact + full unit suite:
   `PYTHONPATH="$PWD" poetry run pytest tests/integration/test_backtest_oracle.py tests/unit -q`
4. FIX-LIST.md Status reconciled for FL-01..FL-04; FL-05..FL-14 untouched.

PYTHONPATH="$PWD" prefix guards against the worktree .venv editable-install shadowing noted in
project memory (pytest/mypy must see worktree edits, not the installed package).
</verification>

<success_criteria>
- All 7 portfolio.py ValueError sites raise typed domain exceptions mapped per-condition.
- portfolio_id annotated PortfolioId on signal/order/fill events (import + field + docstring + comment).
- mypy --strict over itrader/ reports zero errors.
- BTCUSD oracle test passes byte-exact (134 trades, frozen numeric values) — behavior preserved.
- Full unit suite green; no new warnings (filterwarnings=["error"] stays satisfied).
- FIX-LIST.md FL-01/FL-02 done (quick 260610-sjp), FL-03 (phase 4), FL-04 (phase 5); rest untouched.
- No float introduced anywhere (money stays Decimal); indentation matched per file (tabs vs 4 spaces).
</success_criteria>

<output>
Create `.planning/quick/260610-sjp-close-fl01-fl02/260610-sjp-SUMMARY.md` when done.
</output>

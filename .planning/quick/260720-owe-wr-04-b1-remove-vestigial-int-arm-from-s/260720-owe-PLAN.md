---
phase: quick-260720-owe
plan: 01
type: execute
wave: 1
depends_on: []
autonomous: true
requirements: [WR-04-B1]
files_modified:
  - tests/unit/strategy/test_rehydrate.py
  - tests/integration/test_strategy_registry_restart.py
  - tests/unit/strategy/test_to_dict_snapshot.py
  - tests/unit/strategy/test_is_active_gate.py
  - tests/unit/strategy/test_strategies_handler_remediation.py
  - tests/unit/strategy/test_pair_dispatch.py
  - itrader/strategy_handler/base.py
  - itrader/strategy_handler/registry/rehydrate.py
  - itrader/strategy_handler/lifecycle/manager.py
  - itrader/strategy_handler/strategies_handler.py
  - tests/unit/strategy/test_strategy_command_verbs.py
  - itrader/storage/strategy_registry_store.py
  - tests/unit/storage/test_strategy_registry_store.py
  - tests/support/strategy_catalog.py
  - migrations/versions/p10_strategy_portfolio_subs.py

must_haves:
  truths:
    - "Strategy.subscribed_portfolios is declared as a homogeneous list of PortfolioId; the vestigial second arm is gone from every strategy-domain source file."
    - "StrategyLifecycleManager.portfolio_read_model is declared as the real PortfolioReadModel protocol, so mypy --strict actually checks the get_position call in _strategy_is_flat."
    - "A non-UUID portfolio subscription id reaches each resolver's pre-existing loud-failure arm: rehydrate raises StrategyConfigError (D-19 quarantine), the manager returns None (loud no-op). Neither failure semantic changes."
    - "The fan-out in strategies_handler constructs SignalEvent.portfolio_id with no bridging cast, because the iterated element type already matches the field type."
    - "Every surviving justification for the String portfolio_id column rests on serialization (to_dict writes str(pid), rehydrate parses it back), never on the removed arm."
    - "mypy --strict is clean over 273 source files with zero new type-ignore comments and zero widened annotations."
    - "Full gates hold: 2299 unit passed, 204 integration passed + 2 skipped, oracle byte-exact at 134 / 46189.87730727451."
  artifacts:
    - itrader/strategy_handler/base.py
    - itrader/strategy_handler/registry/rehydrate.py
    - itrader/strategy_handler/lifecycle/manager.py
    - itrader/strategy_handler/strategies_handler.py
    - itrader/storage/strategy_registry_store.py
  key_links:
    - "base.py subscribed_portfolios element type -> strategies_handler.py SignalEvent.portfolio_id field type (must match with no cast)"
    - "base.py subscribed_portfolios element type -> manager.py _strategy_is_flat -> PortfolioReadModel.get_position(portfolio_id: PortfolioId, ...) (the original defect seam)"
    - "base.py to_dict str(pid) serialization -> strategy_portfolio_subscriptions.portfolio_id String column -> rehydrate._resolve_portfolio_id parse (the round trip that justifies String)"
    - "rehydrate._resolve_portfolio_id failure arm -> StrategyConfigError -> D-19 quarantine (must stay reachable, semantics unchanged)"
---

<objective>
Close WR-04 (the last open finding in 10.1-REVIEW.md) by removing the vestigial second
arm from the `subscribed_portfolios` portfolio-id handle across the strategy domain, and
restore the type honesty that the arm's presence was suppressing.

Purpose: `StrategyLifecycleManager._strategy_is_flat` passes each element of
`strategy.subscribed_portfolios` into `PortfolioReadModel.get_position`, whose first
parameter is declared `PortfolioId`. The element type is a two-arm union. The mismatch is
invisible only because the manager declares its read-model attribute as `Optional[Any]`,
which erases the call site from `mypy --strict`. Both resolvers already parse to a real
`PortfolioId` first and only fall back to the second arm; the FL-02 invariant states the
runtime value is ALWAYS a UUIDv7-backed `PortfolioId`. The arm is dead weight that costs a
real type check.

Output: a homogeneous handle type, an honestly-typed read-model attribute, two resolvers
whose accepted-input set narrows while their failure semantics stay byte-identical, and
four dead justification comments rewritten to cite the reason that actually survives.
</objective>

<context>
@.planning/STATE.md
@CLAUDE.md
</context>

<planner_findings>
Read this before touching code. I re-measured every claim in the task brief; three are
wrong in ways that change the work.

**CORRECTION 1 — the brief materially under-scoped the test surface.**
The brief disclosed one test file passing bare-int portfolio ids (`test_to_dict_snapshot.py`).
There are **14 such call sites across 6 test files**, and **3 of them are hard breakages**,
not cosmetic incoherence, because they round-trip through `rehydrate`:

| Site | Round-trips rehydrate? | Effect of deleting the arm |
|------|------------------------|----------------------------|
| `test_rehydrate.py:207,208,210` | YES | resolver raises -> D-19 quarantine claims the instance -> `assert quarantined == []` and the roster assertion both FAIL |
| `test_rehydrate.py:551` | YES | pair quarantined -> `handler.strategies[0]` raises IndexError |
| `test_strategy_registry_restart.py:135` | YES | roster empty after rebuild -> subscription assertion FAILS |
| `test_to_dict_snapshot.py:64,77,78` | no | still passes (`str(3) == "3"`), but documents removed usage as legal |
| `test_is_active_gate.py:164` | no | still passes; incoherent |
| `test_strategies_handler_remediation.py:178,193,270,285` | no | still passes; incoherent |
| `test_pair_dispatch.py:138` | no | still passes; incoherent |

Consequence: the brief's "2299 unit / 204 integration stay green" baseline is **not
reachable** without migrating these fixtures. That migration is required work, and it is
why Task 1 exists and runs FIRST.

**CORRECTION 2 — the brief's stated reason for deferring B2 is factually false.**
The brief says "there is NO Alembic chain in this repo (verified: no
`itrader/storage/migrations/` directory exists)". The directory it names does not exist
because the chain was **relocated to the repo root** in Phase 04-01 (`git mv`, STATE.md
line 211). `migrations/versions/` is present and live, and
`migrations/versions/p10_strategy_portfolio_subs.py:106` carries the same dead
justification comment as the other sites.

B2 (changing the column type) **stays out of scope** — that is the user's settled decision
and it is independently correct. But the deferral must not be recorded against a false
premise, and the migration's *comment* is the same rot being removed elsewhere. A
comment-only edit to a shipped migration changes no DDL and no revision identifier, so it
is safe; it is folded into Task 3. Flag this correction in the summary.

**CORRECTION 3 — the mutator signatures are not a judgment call.**
The brief asks whether to narrow `subscribe_portfolio` / `unsubscribe_portfolio` "unless
you find a concrete reason not to". There is no choice: once the list is homogeneous,
appending a value of the removed arm to it is a `mypy --strict` error. Narrowing the
mutators is forced by the list narrowing, not discretionary. Narrow them.

**Two decisions this plan makes, stated explicitly (the brief asked for both):**

- **Resolver handling — option (a), delete outright.** Both resolvers already own a
  loud-failure arm that is the correct destination for a malformed id. A "parse then
  reject" fallback would be dead code reconstructing the same outcome one branch later.
  Deleting leaves each resolver's failure semantics *unchanged*: `rehydrate` still raises
  `StrategyConfigError` (so D-19 quarantine still claims the instance), the manager still
  returns `None` (so the caller still makes it a loud no-op). Only the set of ACCEPTED
  inputs narrows. Return types narrow to match.

- **Read-model import — module-top, NOT `TYPE_CHECKING`.** The brief suggested
  `TYPE_CHECKING`. Prefer module top: `manager.py`'s own module docstring states "Every
  import is at MODULE TOP (DECOMP-02)" and records that the GATE-01 lazy-import rationale
  was re-tested and found FALSE for this module. `itrader/core/portfolio_read_model.py`
  imports only stdlib plus `core.enums` and `core.ids` — **both already on manager.py's
  module-top import graph** (line 58 imports `PortfolioId` from `core.ids`). The import is
  therefore free and carries zero inertness risk; a `TYPE_CHECKING` guard would contradict
  the file's documented convention for no benefit.

**Indentation — measured per file, byte-counted just now. Never infer from the directory;
this repo splits indentation WITHIN packages.**

| File | Indentation | Note |
|------|-------------|------|
| `itrader/strategy_handler/base.py` | **TABS** (867 tab / 0 space) | |
| `itrader/strategy_handler/lifecycle/manager.py` | **TABS** (959 / 0) | |
| `itrader/strategy_handler/strategies_handler.py` | **TABS** (720 / 0) | |
| `itrader/strategy_handler/registry/rehydrate.py` | **TABS** (241 tab / **7 space**) | The 7 space lines are the MODULE docstring at lines 23-30, far from every edit site. Do NOT write a gate forbidding space-leading lines here. |
| `itrader/storage/strategy_registry_store.py` | **4-SPACE** (0 tab / 332 space) | Note the path: `itrader/storage/`, NOT `itrader/strategy_handler/storage/` (which does not exist). |
| `migrations/versions/p10_strategy_portfolio_subs.py` | 4-SPACE | |
| all `tests/` files in scope | 4-SPACE | |

**Observed but deliberately untouched** (report in the summary, do not edit):
`itrader/portfolio_handler/transaction/transaction.py:36` and
`itrader/portfolio_handler/position/position.py:44` carry the same two-arm union on a
different domain's field. Out of scope. Every negative grep below excludes them by path.
</planner_findings>

<tasks>

<task type="auto">
  <name>Task 1: Migrate bare-int portfolio-id test fixtures to real PortfolioId values</name>
  <files>tests/unit/strategy/test_rehydrate.py, tests/integration/test_strategy_registry_restart.py, tests/unit/strategy/test_to_dict_snapshot.py, tests/unit/strategy/test_is_active_gate.py, tests/unit/strategy/test_strategies_handler_remediation.py, tests/unit/strategy/test_pair_dispatch.py</files>
  <action>
Replace all 14 bare-integer-literal `subscribe_portfolio` arguments across these six files
with genuine `PortfolioId`-wrapped UUIDv7 values. All six files are 4-SPACE indented.

This task runs FIRST and is deliberately behavior-neutral: real UUID values are already the
primary arm of both resolvers, so every touched test passes BEFORE the source change (Task
2) and AFTER it. There is no red window at any point in this plan.

Per file:

- `test_rehydrate.py` — three call sites in the roster test (currently seeding literals
  11, 22 and 33 across an sma and an empty strategy) and one in the pair test (literal 9).
  These are the round-trip breakages: they seed the store, then rehydrate. Introduce
  module-level `PortfolioId(uuid7())` constants (the file already imports `PortfolioId` and
  `uuid7` — confirm before adding an import; the id-parse test around line 324 already uses
  exactly this idiom, so mirror it). Preserve each test's existing intent and assertions;
  if an assertion compares against the stringified id, update it to compare against
  `str(<the new constant>)` so it still asserts the round trip rather than a literal.
- `test_strategy_registry_restart.py` — one call site (literal 4242) plus the assertion
  a few lines below that compares the rebuilt subscription list against that literal
  stringified. Update both together so the test still proves store-driven roster survival
  across a rebuild.
- `test_to_dict_snapshot.py` — three call sites (literals 7, 3, 9). One is in the
  key-order test; two are in the runtime-refresh test, whose assertion compares the
  serialized subscription list against the stringified literals. Update the assertion to
  compare against the stringified new constants. This test is the direct evidence that
  `to_dict` serializes via `str(pid)` — which is the justification Task 3 promotes to sole
  survivor — so it is strictly better with real ids.
- `test_is_active_gate.py`, `test_strategies_handler_remediation.py` (four sites),
  `test_pair_dispatch.py` — single-value fixtures where the id is opaque to the assertion.
  A single module-level constant per file is sufficient.

Do not change any test's name, intent, or assertion strength. This is a fixture-value
migration only. Do not touch `test_strategy_command_verbs.py` here — its int-arm test is
repurposed in Task 2, where the behavior it asserts actually changes.
  </action>
  <verify>
    <automated>test $(grep -rEn 'subscribe_portfolio\([0-9]' tests/ | wc -l) -eq 0 && PYTHONPATH="$PWD" poetry run pytest tests/unit -q 2>&1 | tail -3 && PYTHONPATH="$PWD" poetry run pytest tests/integration -q 2>&1 | tail -3</automated>
  </verify>
  <done>
Zero bare-integer `subscribe_portfolio` arguments remain anywhere under `tests/`.
Unit suite 2299 passed; integration 204 passed + 2 skipped (the 2 skips are absent OKX
credentials — pre-existing and expected).

GATE FALSIFICATION: the grep returns **14** on the untouched tree (3 in
`test_to_dict_snapshot.py`, 4 in `test_strategies_handler_remediation.py`, 4 in
`test_rehydrate.py`, 1 each in `test_is_active_gate.py`, `test_pair_dispatch.py` and
`test_strategy_registry_restart.py`), so `-eq 0` FAILS pre-change and passes only once the
migration is complete. Verified by running it before writing this plan.
  </done>
</task>

<task type="auto">
  <name>Task 2: Narrow the handle type, delete both legacy resolver arms, and restore the read-model annotation</name>
  <files>itrader/strategy_handler/base.py, itrader/strategy_handler/registry/rehydrate.py, itrader/strategy_handler/lifecycle/manager.py, itrader/strategy_handler/strategies_handler.py, tests/unit/strategy/test_strategy_command_verbs.py</files>
  <action>
The four source files are ALL TAB-indented — match them exactly, and note that
`rehydrate.py` legitimately contains 7 space-indented module-docstring lines at 23-30 that
must survive untouched. `test_strategy_command_verbs.py` is 4-SPACE.

`base.py` (TABS) — declare `subscribed_portfolios` as a homogeneous list of `PortfolioId`
(around line 194). Narrow the `subscribe_portfolio` and `unsubscribe_portfolio` parameter
annotations to match (around lines 1009 and 1016); this is forced, not optional — see
Correction 3. Rewrite the WR-01 comment above the attribute (around line 189) so it no
longer describes the handle as opaque or dual-shaped; it now carries exactly one shape.
Leave both `str(pid)` serialization expressions (around lines 790 and 850) UNCHANGED — they
are the surviving justification for the String column and Task 3 promotes them to sole
reason. Their surrounding comment currently claims `str()` is safe "for both int and UUID
handles"; trim that to the UUID case only.

`rehydrate.py` (TABS) — narrow `_resolve_portfolio_id`'s return annotation to `PortfolioId`
(around line 178). Delete the second parse attempt and the comment introducing it (around
lines 199-201) so a value that is not a UUID falls directly to the existing
`StrategyConfigError` raise. Keep that raise, its message intent, and its `from exc`
chaining EXACTLY as they are — the D-19 quarantine depends on it and its semantics do not
change. Rewrite the docstring paragraph (around lines 180-193) that justifies the String
column via the removed arm: the column is String because `to_dict` serializes via
`str(pid)` and this function is the parsing inverse. Keep the rest of the docstring —
the "trade into the void" hazard explanation is still exactly right and is why this
function must parse rather than pass the raw string through.

`manager.py` (TABS) — three coordinated changes:
  1. Add a module-top import of `PortfolioReadModel` from `itrader.core.portfolio_read_model`,
     placed in alphabetical position among the existing `itrader.core.*` imports (around
     lines 56-59). Module top, not `TYPE_CHECKING` — see Correction 3's second decision.
  2. Change the `portfolio_read_model` constructor parameter (around line 156) and the
     attribute assignment (around line 190) from the erased `Optional[Any]` to the real
     `Optional[PortfolioReadModel]`. Leave `registry_store` and `strategy_catalog` as they
     are — those legitimately stay erased because the SQL stack must stay off this module's
     annotations. Update the class docstring (around lines 136-141) which currently states
     that all three live deps keep erased values for that reason: it must now say the
     read-model is the exception, because `core/` pulls no SQL so its protocol costs
     nothing to name. The parameter's own docstring entry (around line 177) already names
     the protocol correctly and needs no change.
  3. Narrow `_portfolio_id_from`'s return annotation to `Optional[PortfolioId]` (around
     line 277) and delete its second parse attempt (around lines 310-313) so a non-UUID
     value returns `None` via the existing miss path. The "returns None instead of raising,
     so the caller makes it a loud no-op" contract is unchanged. Rewrite the docstring
     sentences that describe the handle as a two-arm union (around lines 286-287) and that
     describe this function as mirroring rehydrate's fallback ordering (around lines
     295-296) — it still mirrors rehydrate, just without that second step.

`strategies_handler.py` (TABS) — at the `SignalEvent` construction in the fan-out (around
line 536) the bridging `cast` is now provably unnecessary: the iterated element type and
the target field type are identical. Remove the call, passing the loop variable directly,
and delete the now-obsolete FL-02 comment block above it (around lines 531-535) that
explains why the bridge was needed. `cast` is imported on line 1 and this is its ONLY use
in the file (verified) — drop it from the import, keeping `Any`, `Optional` and
`TYPE_CHECKING`. Leave the `for` loop itself (around line 521) unchanged.

`test_strategy_command_verbs.py` (4-SPACE) — repurpose, do not delete, the test around line
311 that currently asserts the removed arm is accepted (it sends a numeric-string portfolio
id and asserts it lands in the roster as a number plus persists a row). Its behavior is
now inverted, so rewrite it into a rejection test: same command, but assert the roster
stays empty AND no subscription row is written — i.e. the same shape as the
unparseable-id test directly above it around line 300. Rename it to describe rejection
rather than acceptance, and rewrite its docstring to state that a bare numeric id is no
longer a valid portfolio handle and must reach the loud no-op path. Repurposing preserves
coverage of this input class rather than dropping it. Also rewrite the module-level comment
around line 61 that describes the handle as a two-arm union; the surrounding point it makes
— that ids arrive as untrusted strings and MUST be parsed, or signals fan at a portfolio
matching nothing — is still correct and must survive.

If `mypy --strict` surfaces any error not enumerated above, it is a REAL latent defect that
the erased annotation was hiding. Fix it properly and report it in the summary. Do NOT add
a type-ignore comment. Do NOT re-widen any annotation to silence it. If a correct fix would
exceed this task's scope, STOP and escalate rather than papering over it.
  </action>
  <verify>
    <automated>test $(grep -rn 'PortfolioId | int' itrader/strategy_handler/ tests/unit/strategy/test_strategy_command_verbs.py | wc -l) -eq 0 && test $(grep -rn 'return int(raw)' itrader/ | wc -l) -eq 0 && test $(grep -c 'cast' itrader/strategy_handler/strategies_handler.py) -eq 0 && test $(grep -c '^ ' itrader/strategy_handler/registry/rehydrate.py) -eq 7 && test $(grep -c $'^\t' itrader/storage/strategy_registry_store.py) -eq 0 && poetry run mypy 2>&1 | tail -2 && PYTHONPATH="$PWD" poetry run pytest tests/unit -q 2>&1 | tail -3</automated>
  </verify>
  <done>
The two-arm union is absent from every strategy-domain source file and from the verbs test.
Neither resolver retains a secondary integer parse. `strategies_handler.py` contains no
`cast` token at all. `mypy --strict` reports success over 273 source files with zero new
ignores. Unit suite still 2299 passed.

GATE FALSIFICATION (each clause measured on the untouched tree before writing this plan):
- union grep returns **11** pre-change (4 in `base.py`, 2 in `manager.py`, 2 in
  `rehydrate.py`, 1 in `strategies_handler.py`, 2 in the verbs test) -> `-eq 0` FAILS pre-change.
- secondary-parse grep returns **2** pre-change (`rehydrate.py:201`, `manager.py:311`) ->
  FAILS pre-change.
- `cast` count in `strategies_handler.py` returns **3** pre-change (the import on line 1,
  the comment on 535, the call on 536) -> FAILS pre-change.
- The two indentation clauses are REGRESSION guards, not change detectors — they hold both
  before and after by design, and exist to catch normalization of the 7 legitimate
  space-indented docstring lines in the tab-indented `rehydrate.py` and of the 4-space
  `strategy_registry_store.py`. The composite command as a whole still FAILS on the
  untouched tree via the three clauses above, satisfying the fail-first requirement.
  </done>
</task>

<task type="auto">
  <name>Task 3: Rewrite the four dead String-column justifications onto the surviving reason</name>
  <files>itrader/storage/strategy_registry_store.py, tests/unit/storage/test_strategy_registry_store.py, tests/support/strategy_catalog.py, migrations/versions/p10_strategy_portfolio_subs.py</files>
  <action>
Four comments across the storage layer justify the `strategy_portfolio_subscriptions.portfolio_id`
String column by appealing to the arm that Task 2 removed. Each must be rewritten to cite
the reason that actually survives, so no future reader re-derives a dead premise or
concludes the column is now unjustified.

The surviving justification, in one sentence: the column is String because
`Strategy.to_dict` serializes each handle via `str(pid)` and `rehydrate._resolve_portfolio_id`
parses it back, so the stored form is a string by the round trip's own construction.
Whether the column *should instead* become a UUID-typed column is a separate open question
(filed as B2) and is explicitly NOT decided here — say so where a reader would otherwise
assume the String choice is now settled.

- `itrader/storage/strategy_registry_store.py` (**4-SPACE**, at `itrader/storage/`, not
  under `strategy_handler/`) — the module docstring paragraph around lines 22-25 and the
  inline comment above the column definition around line 121. The docstring paragraph
  currently contrasts this column against the portfolio-owned tables whose key is strictly
  a portfolio id; that contrast is still meaningful and worth keeping, but its conclusion
  must change from "a typed column would reject the other arm" to the serialization
  rationale.
- `tests/unit/storage/test_strategy_registry_store.py` (4-space) — the two-line comment
  around lines 91-92 above the String type assertion. It already mentions the `str(pid)`
  serialization in its second line; drop the first line's dead clause and promote the
  serialization reason. Leave the assertion itself untouched.
- `tests/support/strategy_catalog.py` (4-space) — the docstring bullet around line 99
  describing the subscriptions table's column. Same substitution.
- `migrations/versions/p10_strategy_portfolio_subs.py` (4-space) — the comment around lines
  105-106 above the table creation. See Correction 2: this file exists at the repo ROOT
  `migrations/` tree (relocated in Phase 04-01), contradicting the task brief's claim that
  no Alembic chain exists. Edit the COMMENT ONLY. Do not touch the column type, any DDL,
  the revision identifier, or the down-revision — a comment-only edit is safe precisely
  because it changes none of those. B2 remains out of scope.

Comments only in this task. No code, no schema, no assertion changes.
  </action>
  <verify>
    <automated>test $(grep -rn 'PortfolioId | int' --include='*.py' . | grep -v 'portfolio_handler/transaction/transaction.py' | grep -v 'portfolio_handler/position/position.py' | wc -l) -eq 0 && test $(git diff --stat migrations/ | grep -c 'p10_strategy_portfolio_subs') -eq 1 && test $(git diff -U0 migrations/ | grep -E '^[+-]' | grep -v '^[+-][+-]' | grep -cE 'sa\.Column|op\.create_table|revision|down_revision') -eq 0 && poetry run mypy 2>&1 | tail -2 && PYTHONPATH="$PWD" poetry run pytest tests/unit -q 2>&1 | tail -3 && PYTHONPATH="$PWD" poetry run pytest tests/integration -q 2>&1 | tail -3</automated>
  </verify>
  <done>
The two-arm union appears nowhere in the repository outside the two deliberately-untouched
portfolio-domain files. The migration diff touches exactly one file and contains no
added/removed line matching a column definition, table creation, or revision identifier —
proving the edit was comment-only. mypy clean over 273 files; unit 2299 passed; integration
204 passed + 2 skipped.

GATE FALSIFICATION:
- The repo-wide union grep returns **5** at the start of this task (2 in
  `strategy_registry_store.py`, 1 in `test_strategy_registry_store.py`, 1 in
  `strategy_catalog.py`, 1 in the migration) and **16** on the fully untouched tree, so
  `-eq 0` FAILS in both states and passes only once all four sites are rewritten. The
  `grep -v` exclusions are path-scoped to the two out-of-scope portfolio-domain files and
  cannot mask an in-scope site.
- The migration-diff clauses return 0 files and 0 DDL lines on the untouched tree, so the
  first of them (`-eq 1`) FAILS pre-change; together they pin the edit to comments only.
  </done>
</task>

</tasks>

<verification>
Run in the main checkout, never in a worktree, and never via `make test` (it exports a
log-disabling variable that breaks caplog assertions elsewhere in the suite).

1. `PYTHONPATH="$PWD" poetry run pytest tests/unit -q` -> 2299 passed
2. `PYTHONPATH="$PWD" poetry run pytest tests/integration -q` -> 204 passed, 2 skipped
   (the 2 skips are absent OKX credentials — pre-existing and expected)
3. `poetry run mypy` -> Success, 273 source files, zero new ignores, zero widened annotations
4. Oracle byte-exact: `tests/integration/test_backtest_oracle.py` -> trade_count 134,
   final_equity 46189.87730727451. This change is backtest-relevant (`base.py` and
   `strategies_handler.py` are on the hot path) even though it is type-level only, so the
   oracle is a required gate rather than a formality.
5. Repo-wide: the two-arm union survives ONLY in
   `itrader/portfolio_handler/transaction/transaction.py` and
   `itrader/portfolio_handler/position/position.py` (deliberately untouched, different domain).

If `mypy --strict` surfaces an error anywhere outside the sites enumerated in Task 2, treat
it as a real defect the erased annotation was concealing. Fix it properly, report it in the
summary, and never suppress it with an ignore comment or a re-widened annotation.
</verification>

<success_criteria>
- `subscribed_portfolios` and both its mutators carry a single homogeneous handle type.
- Neither resolver retains a secondary integer parse; both failure semantics are unchanged
  (rehydrate raises `StrategyConfigError` into the D-19 quarantine; the manager returns
  `None` for a loud no-op).
- `StrategyLifecycleManager.portfolio_read_model` names the real protocol, so the
  `get_position` call in `_strategy_is_flat` — the original WR-04 defect seam — is now
  genuinely type-checked. This is the finding's actual closure condition.
- The fan-out constructs its signal with no bridging cast; `cast` is gone from
  `strategies_handler.py` entirely.
- All four String-column justifications cite serialization; none cites the removed arm.
- All 14 bare-integer test fixtures use real portfolio ids; the acceptance test for the
  removed arm is repurposed into a rejection test rather than deleted.
- Every gate in `<verification>` passes, including the byte-exact oracle.
</success_criteria>

<summary_requirements>
The summary MUST report:
- Every `mypy --strict` error surfaced by the narrowing, and how each was fixed. If none
  appeared, say so explicitly — that is itself the finding that the arm was purely
  vestigial.
- The two decisions taken (resolvers deleted outright rather than converted to rejecting
  parsers; read-model imported at module top rather than under `TYPE_CHECKING`) with the
  rationale recorded above.
- **Correction 2** — that the repo DOES have a live Alembic chain at the root `migrations/`
  tree, contradicting the task brief. B2's deferral stands on its own merits, but was
  justified to the planner on a false premise and should be re-recorded.
- **Correction 1** — that the int-fixture surface was 14 sites across 6 test files, 3 of
  them hard breakages via the rehydrate round trip, not the single cosmetic file the brief
  disclosed.
- Observed-but-untouched: the same two-arm union on
  `portfolio_handler/transaction/transaction.py:36` and
  `portfolio_handler/position/position.py:44` (different domain, different fields, out of
  scope by decision).
</summary_requirements>

<output>
Create `.planning/quick/260720-owe-wr-04-b1-remove-vestigial-int-arm-from-s/260720-owe-SUMMARY.md` when done.
</output>

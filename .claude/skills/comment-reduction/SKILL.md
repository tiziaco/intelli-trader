---
name: comment-reduction
description: Use when reducing comment/docstring volume in iTrader source files - strips decision-tag narration and decayed citations while provably changing zero code, keeping design counterfactuals and public-surface Parameters/Returns
---

# Comment reduction

Cut prose volume in a source file while **provably** changing no code.

The codebase runs ~1.23 prose lines per code line, because GSD phase executors write a
justification comment at every code site citing the plan decision they implemented
(~3,832 `D-NN`/`WR-NN`/`CR-NN` citations across 226 of 285 files). Those comments were
addressed to a verification gate, not to a reader. **12 of 19** external references
audited so far were wrong — dead paths, line numbers off by 200, a named caller that
does not exist, an invented constant. Broken cross-references survive only in text
nobody reads.

Target after a pass: **0.3-0.7** prose/code for handler modules. ABCs and Protocols
legitimately run higher — there the contract IS the deliverable.

## The four categories

Apply per comment, in order:

1. **Restates the code or the types** → delete. `"""Update internal statistics."""` on
   `_update_stats`. A numpy `Returns: int` block on `-> int`.
2. **Narrates a change** → delete. Anything whose subject is a *change* rather than a
   *constraint*: "X was moved here", "the old Y is deleted", "this replaces Z",
   "before this plan the id was minted fresh", "renamed from".
3. **A behavioral claim** → it belongs in a test. Check whether one exists
   (`grep -rhoE 'def test_[a-z_]+' tests | grep -i <topic>`). If yes, delete the comment
   — the test is executable and fails when it stops being true. If no, keep the comment
   and say so in the report; that gap is a finding.
4. **A design counterfactual** → keep, one sentence, present tense.

Category 4 is the only thing code genuinely cannot express: code shows the path taken,
never why the obvious alternative is wrong, because that alternative is not in the file.
Real examples worth keeping:

- "`assert` is stripped under `python -O`, so a `None` queue would reach `.put`"
- "a synchronous fetch here would self-deadlock the loop"
- "releasing first pops the very lock the assertion credits back"
- "two `OkxExchange` objects per account would double-spawn that account's streams"

## Always keep

- **`Parameters` / `Returns` on `__init__` and every public method.** Reference material
  for a human reader at the call site. `Returns` should enumerate *why* a falsy value
  comes back when there are several paths — that is the part not derivable from the body.
  A `Returns` block that only echoes the annotation (`Returns: Decimal` on `-> Decimal`)
  is category 1: delete it. Keep `Raises`, which is never in the signature.
- The failure mode a guard exists to prevent, especially when fail-fast does NOT trip.
- Ordering constraints ("assert BEFORE release", "warmup BEFORE subscribe").
- Thread-affinity rules and what breaks if violated.

## Always cut

- `D-NN` / `WR-NN` / `CR-NN` / `FEED-NN` / plan-id tags in comments. `D-NN` is a
  **per-phase counter that restarts every phase** — a bare `D-04` has ~60 unrelated
  definitions and resolves to none. (`FL-NN` is a real global registry: keep.)
- Line-number coordinates (`foo.py:334-335`). Replace with the **symbol name** — line
  numbers decay silently. Do this even when the coordinate is currently correct.
- Test-suite census counts ("~100 call sites", "274 tests"). Use a structural claim.
- The same fact stated more than once. Deduplicate to the site that owns it.

## Out of scope

**Tags inside runtime string literals** — log messages, exception fields. They are
behavior-visible. Leave them. Roughly 50 occurrences across 21 files.

## Workflow

```bash
S=.claude/skills/comment-reduction/tools
python3 $S/measure.py itrader/<file>.py          # 1. baseline
```

2. **Read the whole file.** No partial passes.
3. **Verify every external citation against real code** before rewriting it. Expect
   most to be wrong. Report what you find; it is the most useful output of the pass.
4. **Batch edits** through `sub.py` (assert-exactly-one, atomic rollback on any miss).
   Write one script per batch under a scratch dir, never edit ad hoc.
5. `python3 $S/verify.py itrader/<file>.py` after **every** batch.
6. Residual scan:
   `grep -nE '\b(D-[0-9]+|WR-[0-9]+|CR-[0-9]+|Pitfall|[0-9]{2}-[0-9]{2}\b)' <file>`
   Remaining hits must all be inside string literals.
7. Gates: `poetry run pytest tests -q` (expect 3021 passed, 6 skipped — the 6 are
   OKX-credential-gated), `poetry run mypy`, and
   `poetry run pytest tests/integration/test_backtest_oracle.py tests/integration/test_okx_inertness.py -q`.
8. `measure.py` again; report before/after.

## Landmines

- **`fee_model/` docstrings are runtime data.**
  `execution_handler/fee_model/base.py` does `self.__doc__.split('\n')[1].strip()`.
  Those class docstrings are indexed **by line**. Never delete or reflow them.
  `verify.py` tolerates docstring removal by design and will NOT catch this.
- **Indentation is per-file, not per-package.** Handler modules use tabs; `config/`,
  `core/`, `price_handler/feed/`, `events_handler/events/` use 4 spaces — and
  `trading_system/` is split (`live_trading_system.py` is spaces,
  `compose.py`/`engine_context.py`/`backtest_trading_system.py` are tabs). Measure the
  bytes of the file you are editing. Never normalize.
- **Trailing whitespace on blank lines** inside legacy numpy docstrings. A separator
  line is often `    `, not empty. `sub.py` fails loud with MATCH 0 rather than
  corrupting — read the exact bytes with a delimiter dump, do not guess.
- **cwd trap.** `sub.py` scripts live outside the repo, so a chained
  `cd <scratch> && python3 batch.py && poetry run ...` makes `poetry`/`git` run from the
  scratch dir and fail. Always run gates and `verify.py` as a separate call from the
  repo root.
- **`ignore_errors` blindspot.** Several live modules are excluded from
  `mypy --strict` per-module. A dead import or unreachable code there passes both mypy
  and the full suite silently.
- **Concurrent edits.** If `verify.py` reports a difference you cannot attribute to your
  own batches, replay your batch scripts against a clean `git show HEAD:<file>` copy and
  diff. An editor with organize-imports-on-save will strip dead imports mid-pass. Never
  silently absorb a change you did not make — report it.

## Reporting

State: before/after ratio and prose-line delta, the `verify.py` result, gate results,
every wrong citation found (cited vs actual), duplicated facts collapsed, and any
behavioral claim kept **because no test covers it**.

# Quick Task 260720-owe — Audit Marker

**WR-04, the last open finding from `10.1-REVIEW.md`. Phase 10.1's review is now fully closed.**

Option **B1** only — the type narrowing. "B2" (the `String`→`Uuid` column change) was deliberately
NOT taken; a todo is filed.

## The defect

`StrategyLifecycleManager._strategy_is_flat` iterated `strategy.subscribed_portfolios` and passed
each element into `read_model.get_position(portfolio_id, ticker)`. But `subscribed_portfolios` was
`list[PortfolioId | int]` while `PortfolioReadModel.get_position` accepts only `PortfolioId`. The
mismatch was invisible **solely** because the manager declared `portfolio_read_model:
"Optional[Any]"` — an erased annotation hiding a real type error.

## What changed

- **`base.py`** — `list[PortfolioId | int]` → `list[PortfolioId]`. `subscribe_portfolio` /
  `unsubscribe_portfolio` narrowed too — **forced, not discretionary**: once the list is homogeneous,
  appending the other arm is a `mypy --strict` error.
- **Both resolver int-arms deleted outright** (`registry/rehydrate.py::_resolve_portfolio_id`,
  `lifecycle/manager.py::_portfolio_id_from`). Chosen over a "rejecting parse fallback" because each
  resolver **already owns** the correct loud-failure arm — rehydrate raises `StrategyConfigError`
  (D-19 quarantine claims the instance), the manager returns `None` (loud no-op). A rejecting
  fallback would be dead code reaching the same outcome one branch later. Failure semantics are
  byte-identical; only the accepted-input set narrows.
- **`manager.py`** — `"Optional[Any]"` → `"Optional[PortfolioReadModel]"` on both the constructor
  param and the attribute. Imported at **module top, not under `TYPE_CHECKING`**, diverging from the
  brief: the file's own docstring states "Every import is at MODULE TOP (DECOMP-02)" and records the
  GATE-01 lazy rationale as re-tested **false** for this module. `core/portfolio_read_model.py`
  imports only stdlib + `core.enums` + `core.ids`, both already on manager.py's import graph — free,
  zero inertness risk. Class docstring updated: `registry_store`/`strategy_catalog` legitimately stay
  `Any` (SQL stack), `portfolio_read_model` is now the documented exception.
- **`strategies_handler.py`** — removed the now-unnecessary `cast(PortfolioId, ...)`, its obsolete
  FL-02 comment, and the newly-unused `cast` import.
- **Four dead justifications rewritten** (`storage/strategy_registry_store.py` docstring + inline
  comment, `rehydrate.py` docstring, `migrations/versions/p10_strategy_portfolio_subs.py:106`, plus
  the mirrored test comment). All had claimed the column is `String` *because a `Uuid` column would
  reject the legal int arm*. That reason died with the arm. They now cite the surviving one: `to_dict`
  serializes via `str(pid)` and rehydrate parses it back — the stored form is a string by the round
  trip's own construction. The migration edit is **comment-only** — verified no `sa.Column` /
  `op.create_table` / `revision` / `down_revision` line changed.

## The mypy answer

**The narrowing surfaced ZERO mypy errors.** That absence *is* the finding: nothing in the codebase
relied on the int arm — it was purely vestigial, exactly as the comments claimed.

Because "mypy passed" is weak evidence when the defect *was* an erased annotation, enforcement was
**falsified**: a `get_position` call was deliberately broken, mypy caught it
(`Argument 2 ... has incompatible type "int"; expected "str"`), then reverted. Also confirmed
`strategy_handler.lifecycle.manager` sits in **neither** `ignore_errors` override block — worth
checking given this repo's known mypy blindspot on the live facade. The check is genuinely enforced.

No `# type: ignore` added anywhere. Union never re-widened.

## Under-scoped surface found during planning

The original finding named the test impact as one file. Reality: **14 bare-int call sites across 6
test files**, and **3 were hard breakages, not cosmetic** — `test_rehydrate.py:207/208/210` and
`:551`, plus `test_strategy_registry_restart.py:135` round-trip through `rehydrate`, so deleting the
int arm makes the resolver raise → D-19 quarantine claims the instance → roster assertions fail.
The stated "2299 unit stays green" baseline was **unreachable** without migrating them first. That
became task `owe-01`, sequenced ahead of the source change so every intermediate commit is green.

## Disclosed deviation

The plan said keep the rehydrate raise message "EXACTLY as is". The executor changed
`"is neither a UUID nor an int"` → `"is not a UUID"`, reading the instruction as preserving
*semantics*, not stale prose describing a removed input set. Judged correct on review: no test
anywhere asserts that string, and exception type / `from exc` chaining / D-19 quarantine path are
byte-identical.

## Survivors deliberately kept

`PortfolioId | int` now survives at exactly **two** sites repo-wide —
`itrader/portfolio_handler/transaction/transaction.py:36` and
`itrader/portfolio_handler/position/position.py:44`. Different domain, different fields, explicitly
out of scope; untouched. Whether the same vestigiality argument applies there is an **open question,
not investigated**.

## Correction to the task brief (recorded so it doesn't recur)

The brief deferred B2 partly on *"there is NO Alembic chain in this repo."* **False.** The chain
exists at the **repo root** — `migrations/versions/` (9 revisions), driven by `alembic.ini`
(`script_location = migrations`); relocated there in Phase 04-01. What's absent is
`itrader/storage/migrations/`, the path `CLAUDE.md:114` wrongly claims. B2's deferral is
independently correct on other grounds (zero correctness benefit + needs a schema-policy decision),
but it was nearly recorded against a fabricated constraint. Todo filed for the doc rot.

## Gates (all observed, independently re-run by the verifier)

unit **2299 passed** · integration **204 passed / 2 skipped** (pre-existing OKX-cred skips) ·
mypy **clean, 273 source files** · oracle **byte-exact** `trade_count 134` /
`final_equity 46189.87730727451` (read from `output/summary.json` directly, not inferred from a green
diff test) · indentation regression **none** (tab files held space-counts 0/0/0/7, including
rehydrate.py's 7 legitimate docstring-prose lines; the space-indented store file held tab-count 0).

**Verification: 7/7 must-haves, status `passed`.**

**Commits:** `7adfcfa5` (test fixture migration) · `d2b96089` (narrowing + resolver arms + read-model
annotation) · `c29ea3c2` (justification rewrites).

**Todos filed:** `b2-strategy-subscription-portfolio-id-uuid-column.md` ·
`claude-md-alembic-migration-chain-path-wrong.md`.

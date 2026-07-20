---
phase: quick-260720-m0c
plan: 01
subsystem: strategy_handler
tags: [code-review-followup, observability, typing, encapsulation, docs]
requires: [phase-10.1]
provides: [WR-02, WR-03, WR-05, IN-01, IN-02, IN-03, IN-04, IN-06, DOC-CLAUDEMD]
affects:
  - itrader/strategy_handler/storage/registry_storage_factory.py
  - itrader/strategy_handler/managed_strategies.py
  - itrader/strategy_handler/lifecycle/manager.py
  - itrader/strategy_handler/lifecycle/__init__.py
  - itrader/strategy_handler/registry/__init__.py
  - itrader/strategy_handler/strategies_handler.py
  - itrader/trading_system/universe_wiring.py
  - CLAUDE.md
tech-stack:
  added: []
  patterns: [read-through-property, symbol-citation, fail-loud-observability]
key-files:
  created:
    - .planning/quick/260720-m0c-clear-10-1-review-cheap-tier-wr-02-wr-03/SUMMARY.md
  modified:
    - itrader/strategy_handler/storage/registry_storage_factory.py
    - itrader/strategy_handler/managed_strategies.py
    - itrader/strategy_handler/lifecycle/manager.py
    - itrader/strategy_handler/lifecycle/__init__.py
    - itrader/strategy_handler/registry/__init__.py
    - itrader/strategy_handler/strategies_handler.py
    - itrader/trading_system/universe_wiring.py
    - CLAUDE.md
decisions:
  - "IN-01 _pending_removals: added a PUBLIC same-object read accessor on ManagedStrategies rather than leaving the private reach with a comment — the handler now reaches ZERO privates of its collaborator."
  - "IN-04 shipped: the perf gate was decided by an interleaved A/B, not a single sample, because the naive measurement was thermal-drift dominated."
  - "WR-03 surfaced no defects: mypy clean on the first run after tightening. Reported as the expected-but-uninteresting outcome."
metrics:
  duration: ~35min
  completed: 2026-07-20
status: complete
---

# Quick Task 260720-m0c: Clear the 10.1 review cheap tier Summary

Cleared all eight cheap-tier findings from the Phase 10.1 code review plus a CLAUDE.md
factual correction — one silent-degradation seam made loud, one erased type restored,
two rotted source pointers re-anchored to symbols, and four documentation/encapsulation
gaps closed. Nothing was dropped; the oracle stayed byte-exact throughout.

## What Shipped

### Task 1 — documentation truth pass (commit `831dd660`)

- **WR-05** — `universe_wiring.py` cited `strategies_handler.py:214` at two sites as the
  home of the readiness gate. That line had rotted onto the unrelated `_enable_margin`
  delegating property; the real gate is the `_universe.is_ready` short-circuit in
  `StrategiesHandler.on_bar`'s per-ticker loop. Both citations now reference the SYMBOL,
  so they cannot rot again. No code line in this oracle-sensitive file changed.
- **IN-02** — deleted the commented-out `#self.portfolios: dict = {}` line from `__init__`.
- **IN-03** — documented the four previously-undocumented `__init__` parameters
  (`environment`, `sql_engine`, `strategy_catalog`, `portfolio_read_model`) in signature
  order, naming the D-10 allowlist and D-11 read-model roles.
- **IN-06** — see the empirical measurement below.
- **CLAUDE.md** — both exceptions inventories now list `strategy.py` and `results.py`, and
  the Error Handling entry names `StrategyAdmissionError` and `ResultsNotFound`.

### Task 2 — observability, typing, encapsulation (commit `03dd4ece`)

- **WR-02** — the `environment='live'` + `sql_engine is None` arm returned `None` silently
  while its sibling D-21 has-table arm logged a WARNING. Both produce the same outcome: a
  `None` registry makes every control-plane persist arm a clean no-op, so every
  `enable` / `disable` / `subscribe` / `add` / `reconfigure` applies in memory and vanishes
  on restart with no audit trail. Now emits a matching WARNING naming the registry DISABLED
  and the lost-on-restart consequence. Logs the CONDITION only — no credentials, no
  connection string, no `sql_engine` repr (T-m0c-01).
- **WR-03** — see the mypy outcome below.
- **IN-01** — see the `_pending_removals` decision below.

### Task 3 — IN-04, the duplicated `_universe` field (commit `e2be29a7`)

Shipped. The handler's `_universe` field was a second copy kept consistent with the
lifecycle manager's only by `set_universe` writing both. It is now a READ-ONLY
read-through property over the manager's single copy, matching the three live-dep
properties above it. No setter — the sole write path is `set_universe` -> the manager,
which makes the desync (silently short-circuiting `_request_rewarm` so it never re-warms)
unrepresentable rather than merely unlikely. `on_bar` and the pairs gate were NOT
restructured.

## Required Reporting

### WR-03 mypy outcome: CLEAN — no findings

Tightening `logger: Any` -> `logger: ITraderStructLogger` on both `ManagedStrategies.__init__`
and `StrategyLifecycleManager.__init__` restored `mypy --strict` coverage over the ~30
`self.logger.warning/.error/.info` call sites in those two modules. The first mypy run after
the change was clean: **no issues found in 273 source files**. Zero `type: ignore` added,
zero call sites needed fixing, annotation never widened back.

This matches the planner's pre-assessment (only `.warning` / `.error` / `.info` / `.bind` are
called, all present on `ITraderStructLogger` with permissive signatures). Recorded explicitly
because a NON-clean run was the interesting outcome and did not occur.

Both imports are normal module-top runtime imports, not `TYPE_CHECKING`-guarded — `itrader.logger`
pulls no SQL and both modules are on the backtest import graph by design, so there was no
GATE-01 justification for keeping the `Any`. `manager.py` had no `itrader.logger` import at all
and gained one; `managed_strategies.py`'s `from typing import Any` became dead (logger was its
only consumer) and was removed. The three `Optional[Any]` live-dep annotations were NOT touched
(that is WR-04, out of scope).

### IN-06 clean-interpreter measurement

Run before editing anything, exactly as 10.1-03 did:

```
PYTHONPATH="$PWD" poetry run python -c "
import sys
import itrader.strategy_handler.registry
leaked = sorted(m for m in sys.modules if m.split('.')[0] in ('sqlalchemy','psycopg2','alembic'))
print('leaked:', leaked)"
```

Observed: **`leaked: []`** — zero, agreeing with the planner's 2026-07-20 measurement, so
editing proceeded.

Exactly ONE clause was corrected. `registry/__init__.py` gave TWO reasons for keeping the
package out of the top barrel:

- The LAYERING/D-05 reason (reconstruction implementation detail reaching the store through
  an injected handle) — **still true, PRESERVED and expanded** with the `order_handler`
  collaborator-subdir precedent.
- The SQL-leak reason ("would pull SQL onto the backtest import graph") — **FALSE on today's
  tree** and removed, since barrel-exporting performs exactly the import measured above. The
  inline evidence (10.1-03 + the 2026-07-20 re-measurement) is now recorded in the docstring
  so the next reader need not re-derive it.

The surrounding GATE-01 inertness discipline was explicitly NOT deleted — only this module's
own SQL-leak assertion was wrong (T-m0c-03). The `**D-05 — why the reconstruction logic lives
HERE**` bullet block is byte-identical, including both 2-space continuation lines (verified:
the file still has exactly 2 space-prefixed lines). In `lifecycle/__init__.py` only the
cross-module "the other file's claim is (now-stale)" framing was removed; its own positive
statement is intact.

### IN-04 performance measurement — SHIPPED, gate passed

`self._universe` is read TWICE per (strategy, ticker, bar) on the oracle hot path and is
non-`None` in backtest, so the `is None` short-circuit never fires there — a property turns
each direct attribute load into a Python-level call. Measured before deciding.

**Plan's specified instrument** (oracle test wall clock, 5 runs, minimum):

| | before_min | after_min | threshold (before x 1.02) | verdict |
|---|---|---|---|---|
| pytest wall clock | 2.09s | 2.12s | 2.1318s | PASS (marginal) |

That instrument is startup-dominated — its own run-to-run spread (2.09–2.18s, ~4%) exceeds
the 2% threshold, so it cannot resolve a 2% effect. A cleaner in-process instrument
(7 backtest runs per process, logs disabled) initially showed `after` MIN 0.296s vs `before`
MIN 0.2955s (pass) but a MEDIAN 6.7% worse (0.3167 vs 0.2969) — ambiguous.

Resolved with an **interleaved A/B** (4 rounds, alternating before/after, 5 in-process runs
each) to control for thermal drift:

| round | BEFORE min | AFTER min | BEFORE median | AFTER median |
|-------|-----------|-----------|---------------|--------------|
| 1 | 0.2942 | 0.2989 | 0.3232 | 0.3196 |
| 2 | 0.2984 | 0.2963 | 0.3115 | 0.3059 |
| 3 | 0.2917 | 0.2904 | 0.2977 | 0.2972 |
| 4 | 0.2915 | 0.2918 | 0.2958 | 0.2986 |

**before_min 0.2915s, after_min 0.2904s** — ratio 0.996, comfortably inside the 1.02
threshold. The medians converge as the box settles (rounds 3–4 are within noise of each
other), identifying the earlier 6.7% median gap as thermal drift rather than a property
cost. Both instruments pass, so IN-04 shipped.

Correctness: the oracle was byte-exact after the edit, as expected by construction (same
object, same value, same order).

### IN-01 `_pending_removals` decision: PUBLIC accessor added

The plan allowed either a public read accessor or leaving the site with an explanatory
comment. **Chose the public accessor.** The five existing public methods
(`is_pending` / `mark_pending` / `discard_pending` / `has_pending` / `pending_names`) do not
cover the handler's need: `pending_names` returns a `list` COPY, so none of them can serve a
caller that must hand back the live set. Added a `pending_removals` `@property` on
`ManagedStrategies` returning the SAME `set` object (never a copy — the module's SAME-OBJECT
INVARIANT; a copy would silently turn in-place test mutations into no-ops).

Result: `grep -c 'self\._managed\._'` in `strategies_handler.py` is now **0** — the handler
reaches no underscore-prefixed attribute of its collaborator at all, which makes the plan's
IN-01 truth literally rather than approximately true.

The two gate flags went public on the collaborator (`allow_short_selling` / `enable_margin`)
with the handler's `_`-prefixed property NAMES unchanged, so the 15 test files that flip
`handler._allow_short_selling` / `handler._enable_margin` after construction keep working.
**Zero test files modified.** The unrelated `_enable_margin` field in
`order_handler/admission/admission_manager.py` was correctly left alone.

## Gate Results (ACTUAL observed)

| Gate | Baseline | Observed | Status |
|------|----------|----------|--------|
| `tests/unit` | 2302 passed | **2302 passed** in 11.99s | match |
| `tests/integration` | 204 passed, 2 skipped | **204 passed, 2 skipped** in 29.08s | match |
| Oracle | 134 / 46189.87730727451 | **3 passed** against unmodified `tests/golden/summary.json` (`trade_count: 134`, `final_equity: 46189.87730727451`) | byte-exact |
| `mypy` | no issues, 273 files | **Success: no issues found in 273 source files** | clean |
| `test_okx_inertness.py` | green | **4 passed** | green |
| registry+lifecycle SQL leak | `[]` | **`inertness OK`** (zero leaked) | clean |

The 2 integration skips are the pre-existing OKX-credentials-absent skips
(`test_okx_connectivity.py`, `test_okx_smoke.py`), not a regression.

### Indentation audit — every count matches its measured baseline

| File | Metric | Baseline | Observed |
|------|--------|----------|----------|
| `strategies_handler.py` | space-lines | 0 | 0 |
| `managed_strategies.py` | space-lines | 4 | 4 |
| `lifecycle/manager.py` | space-lines | 0 | 0 |
| `lifecycle/__init__.py` | space-lines | 0 | 0 |
| `registry/__init__.py` | space-lines | 2 | 2 |
| `universe_wiring.py` | space-lines | 0 | 0 |
| `registry_storage_factory.py` | TAB-lines | 0 | 0 |

`git diff --check` silent. No file under `tests/` modified. Zero `type: ignore` added.
`pyproject.toml` / `poetry.lock` untouched.

## Deviations from Plan

**1. [Plan-gate correction, pre-execution] Tightened a self-passing verify clause**

The plan-checker flagged Task 1's `grep -q 'D-10' itrader/strategy_handler/strategies_handler.py`
as self-passing — `D-10` already appeared 3 times in that file on the untouched tree, so it
proved nothing about the new docstring entries. Replaced it with two entry-anchored gates:

```
test "$(grep -A2 '^\t\tstrategy_catalog: ' ...  | grep -c 'D-10')" = "1"
test "$(grep -A2 '^\t\tportfolio_read_model: ' ... | grep -c 'D-11')" = "1"
```

Both return 0 on the untouched tree (the docstring entries did not exist), so they are
genuinely falsifying. My first replacement attempt was itself broken — a
`sed -n '/def __init__/,/^\t\t"""$/p'` range terminated at the OPENING docstring quote and
so never saw the body, reporting 0 against real content. Caught by running it; replaced with
the entry-anchored form above.

**2. [Rule 1 - Bug] Self-inflicted gate failures from quoting the forbidden strings**

Two Task 1 gates failed on my first run because my own new prose quoted the exact strings the
gates forbid: I wrote "The former ``strategies_handler.py:214`` citation had already rotted"
(tripping the `:214`-must-be-absent gate) and quoted the removed claim verbatim as
`"would pull SQL onto the backtest import graph"` (tripping its zero-count gate). Both
reworded to describe the corrections without reproducing the forbidden text. This is why the
gates exist — they caught prose that would have left the stale citation greppable.

**3. [Accuracy fix] Mis-cited decision tag**

The `registry/__init__.py` correction initially cited `(WR-05/IN-06)`; WR-05 is the
`universe_wiring.py` item, not this one. Corrected to `(IN-06)`.

**4. [Instrument change, in-spirit] IN-04 perf gate measured with an interleaved A/B**

The plan specified 5 oracle-test runs before and after, comparing minimums. I ran that
(it passed: 2.09 -> 2.12 against a 2.1318 threshold) but it passed only marginally and its
noise floor exceeds the effect size it was meant to detect. Rather than accept a
noise-dominated pass or weaken the gate, I added the stricter interleaved in-process A/B
reported above. The plan's gate was not weakened — it was met AND corroborated by a better
instrument. Both are reported.

## Out-of-Scope Items — untouched, as required

WR-01, WR-04 (the three `Optional[Any]` live-dep annotations stay exactly as they were),
WR-06 (`min_timeframe` prose and `recompute_min_timeframe` untouched), IN-05 (already resolved
by `260720-ljn`, not re-fixed), the km2 zone-1/zone-2 guard in `_add_strategy_verb`, and the
`StrategyAdmissionError` hierarchy. Verified mechanically: the `manager.py` diff adds no line
matching `StrategyAdmissionError|except \(`.

## Commits

| Task | Commit | Description |
|------|--------|-------------|
| 1 | `831dd660` | docs — WR-05, IN-02, IN-03, IN-06, CLAUDE.md |
| 2 | `03dd4ece` | feat — WR-02, WR-03, IN-01 |
| 3 | `e2be29a7` | refactor — IN-04 `_universe` collapse |

## Remaining After This Task

The 10.1 review's three genuinely owner-gated items are all that is left: **WR-01**
(`ManagedStrategies.remove` leaves derived state stale, blocked on WR-06), **WR-04**
(`portfolio_read_model: Optional[Any]` hiding a `PortfolioId | int` mismatch — investigation
shaped, unknown blast radius), and **WR-06** (`min_timeframe` delete-vs-document, needs an
owner decision).

## Self-Check: PASSED

All 8 claimed artifacts exist on disk; all 3 claimed commits (`831dd660`, `03dd4ece`, `e2be29a7`) exist in git history. Verified 2026-07-20.

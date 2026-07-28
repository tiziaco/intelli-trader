---
status: completed
created: "2026-07-28"
source: comment-reduction campaign (45 files, 2026-07-28) — dead cross-references found in files the campaign has NOT yet passed over
tags: [documentation, stale-citations, claude-md, planning-docs, test-docstrings, gsd-plan-quality]
resolves_phase: ""
---

# Dead symbol citations in files the comment campaign has not reached

**Origin:** The 2026-07-28 comment-reduction campaign audits every external reference in the file
it is cleaning. **103 of ~290** citations checked so far were wrong. The ones below live in files
that have **not** had a pass yet, so they are still in the tree — including in `CLAUDE.md` and
`.planning/codebase/`, which brief every future planner and executor.

All verified by grep at HEAD.

## Why this matters more than ordinary doc rot

These are not stale prose in a corner. `CLAUDE.md` and `.planning/codebase/` are loaded into
context at session start; a GSD planner reading them inherits the error and writes it into a
plan. The campaign's evidence is that this already happened — the same dead symbol appears in
source comments, in planning docs, **and** in test docstrings, which is the signature of a name
that changed once and was never chased down.

## 1. `EventHandler._log_error_event` — deleted symbol, cited in three docs

`grep -rn "_log_error_event" itrader/` finds **one** hit: a docstring in
`events_handler/error_handler.py` narrating that it lifted the old body. The symbol is gone.
The real ERROR-route consumer is `ErrorHandler.on_error`.

Still cited as live:
- `CLAUDE.md` — *"Contains: `EventHandler.process_events()`, `_dispatch()`, `_on_handler_error()`, `_log_error_event()`"*
- `CLAUDE.md` — *"`EventHandler._log_error_event` is the real `ERROR`-route consumer (structured log sink, severity-mapped)"*
- `.planning/codebase/CONVENTIONS.md` — the broad-`except` policy entry, *"consumer swallow in `_log_error_event`"*
- `.planning/codebase/INTEGRATIONS.md` — *"Error route consumer: `…full_event_handler.py::EventHandler._log_error_event`"*, with a file path that no longer hosts it

## 2. `LiveTradingSystem._maybe_resume_after_reconnect` — deleted symbol, cited in four test files

`grep -rn "_maybe_resume_after_reconnect" itrader/` returns **nothing**. The method was folded
into `StreamRecoveryHandler`. Still cited in:

- `tests/unit/trading_system/test_stream_recovery_handler.py` — module docstring, carrying **two**
  dead line coordinates, `(607-666)` and `(668-684)`
- `tests/integration/test_resume_gated_on_all_streams.py` — module docstring
- `tests/integration/test_resume_missed_fill_catchup.py` — module docstring
- `tests/unit/execution/test_reconnect_resilience.py` — a test docstring claiming *"Proves the
  honest resume path: `_maybe_resume_after_reconnect` refreshes venue…"*

That last one is a test asserting it proves the behaviour of a method that does not exist. The
test passes, so nothing surfaces it.

## 3. `LiveTradingSystem._update_status` — never existed under that name

`grep -rn "def _update_status" itrader/` returns nothing. The mutation seam is
`SafetyController.update_status` — public, no leading underscore. Cited as the enforcement point
in:

- `core/enums/system.py` — **three times**, including in the comment that introduces
  `VALID_STATUS_TRANSITIONS` (*"Enforced at the ONE mutation seam `LiveTradingSystem._update_status`"*),
  the same-state-no-op note, and the `HaltReason` docstring (*"`_update_status(halt_reason=)`"*)
- `trading_system/live_runner.py` — the loop-entry hook description

A transition table whose comment names a non-existent enforcer is exactly the kind of thing a
planner trusts.

## 4. `core/enums/system.py` also carries the stale 4-reason halt vocabulary

The `HALTED` member's inline comment describes a four-reason halt vocabulary. `HaltReason` has
**nine** members. This is the same stale list that
[[comment-campaign-code-defects]] item 2 found in `SafetyController.halt()`'s docstring — where
it additionally named `paused-on-disconnect`, which `HaltReason`'s own docstring explicitly
excludes as *"a `pause_submission()` reason, not a halt"*.

## 5. `stream_recovery_handler.py` line coordinates — FIXED 2026-07-28

Recorded for the pattern, not as open work. That file cited `_all_venue_streams_healthy`
**(668-684)** in a ~230-line file where the method sits at ~204, and
`_maybe_resume_after_reconnect` **(607-666)** for a method that does not exist. Both were
replaced with symbol names in commit `306fe4ad`. The test-tree copies (item 2) survive.

## 6. Two live dead-symbol citations in files still outside the campaign

Found by sweep agents while verifying their own files, in files they did not own and correctly
left untouched:

- **`itrader/trading_system/backtest_trading_system.py`** cites
  `ExecutionHandler._resolve_rng_seed` **twice** (`:179` and again in a Notes block). That method
  does not exist anywhere in `itrader/` — the determinism seam moved to `EngineContext.rng`.
  This is on the **backtest determinism path**, the one thing the whole project is anchored on,
  so a planner reading it is pointed at a method that cannot be inspected.
- **`tests/integration/test_compose_wiring.py:107`** says *"Registry lookup: read
  `ExecutionHandler.init_exchanges` before changing this key."* `init_exchanges` has zero
  occurrences in `itrader/`; the real seam is the module-level `seed_exchange_registry`. The
  comment instructs a future reader to consult a symbol that cannot be found — the failure mode
  is wasted search, then a guess.

Both are one-line fixes (swap in the live symbol name). Neither file has had a pass.

## Running tally after the 29-file sweep

**103 wrong of ~290 citations checked**, across 45 source files plus `CLAUDE.md` and
`.planning/codebase/`. The 29-file sweep alone contributed 52 wrong out of ~130.

The category split from the sweep, which is the useful part — it says what *kind* of rot to
expect and therefore what a fix should target:

| category | n | what it looks like |
|---|---:|---|
| `stale-behavior` | 21 | the claim was true when written; the code moved underneath it |
| `dead-symbol` | 8 | names a symbol that no longer exists anywhere |
| `invented` | 7 | names a symbol that **never** existed (`plugin.venue_uid`, `ExecutionTimeoutError`, a "mirror" site with no matching code) |
| `moved-symbol` | 4 | right symbol, wrong home |
| `stale-line-number` | 4 | coordinate decayed, including one off-by-one that was *already* wrong when authored |
| `wrong-count` | 1 | "the four safety collaborators" — there are three |
| `other` | 7 | mostly correct facts carrying an unresolvable plan-id tag |

**`stale-behavior` dominating at 40% is the finding.** These are not typos; they are claims that
were accurate at authoring and were never revisited when the code moved. Several now assert the
*opposite* of current behaviour — `venue_spec.py` documents an `account_id` fallback that
`assemble_venue` now **raises** on, and `order_manager.py` advertises "stop/limit trigger
evaluation" in two separate docstrings when nothing in `order_handler/` evaluates a trigger at all
(matching lives in the execution layer). A planner trusting either would design against inverted
behaviour.

The `invented` bucket (7) deserves separate weight: those citations were **wrong on the day they
were written**. No amount of keeping docs in sync with code would have prevented them — only
verifying the reference at authoring time.

## RESOLVED 2026-07-28

All five dead symbols are now at **zero** occurrences across `itrader/`, `tests/`,
`.planning/codebase/` and `CLAUDE.md`:

| symbol | live owner it was replaced with | sites |
|---|---|---:|
| `_log_error_event` | `ErrorHandler.on_error` | already closed by the doc audit before this pass |
| `_maybe_resume_after_reconnect` | `StreamRecoveryHandler.on_reconnect` | 4 |
| `_update_status` | `SafetyController.update_status` | 8 |
| `_is_halted` | `is_halted` (public on both facade and controller) | 1 |
| `_resolve_rng_seed` | *(no replacement — `EngineContext.rng` is the seam)* | 3 |
| `init_exchanges` | `seed_exchange_registry` | 2 |

Three decayed line coordinates went with them: `catch_up_missed_fills (okx.py:626)` — the real
line is 518 — plus `live_trading_system.py:993` twice. All replaced with symbol names.

Also corrected: `test_halt_reason.py`'s module docstring claimed *"Exactly the FIVE reasons"*
while `HaltReason` carries **nine** members — and the file's own first test asserts all nine.
The docstring had been describing the P1 state and was never revisited when D-16 added the four
tripwire reasons.

**Scope note.** 17 of the 19 sites were in `tests/` — a tree the comment campaign has never
passed over. The dead symbols survived longest exactly where nobody was looking, which is the
argument for extending a citation sweep to `tests/` even though the campaign proper stops at
`itrader/`.

**One deliberate AST change.** `test_early_durable_halt_refusal.py`'s `_UnresolvedHaltStore`
raises `AssertionError("… the gate re-latches via _update_status …")`. Runtime string literals
are normally out of scope for the campaign, but this is a test-failure message read only by a
human, nothing greps for its text, and leaving a dead symbol in the one line a developer sees
when the test breaks defeats the point. `verify.py` reports that single `Constant` delta for
that file and nothing else.

Gates at resolution: 3021 passed / 6 skipped, mypy clean on 285 files, oracle + inertness
7 passed. Every other touched file is AST-identical to HEAD.

Do `CLAUDE.md` and `.planning/codebase/` **first** and separately — they are the highest-leverage
two files in the repo for plan quality, and fixing them is independent of everything else.

Note the recurring shape across all of items 1–3: **a method moved, and its old address survived
in files that did not move.** Worth a grep-for-dead-symbols check at phase close, since the
mechanism is not going to stop on its own.

**Related:** [[comment-campaign-code-defects]], [[comment-campaign-untested-safety-claims]],
[[claude-md-alembic-migration-chain-path-wrong]] (an earlier instance of CLAUDE.md drift).

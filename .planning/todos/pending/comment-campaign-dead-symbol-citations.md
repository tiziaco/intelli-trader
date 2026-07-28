---
status: open
created: "2026-07-28"
source: comment-reduction campaign (13 files, 2026-07-28) — dead cross-references found in files the campaign has NOT yet passed over
tags: [documentation, stale-citations, claude-md, planning-docs, test-docstrings, gsd-plan-quality]
resolves_phase: ""
---

# Dead symbol citations in files the comment campaign has not reached

**Origin:** The 2026-07-28 comment-reduction campaign audits every external reference in the file
it is cleaning. **42 of 136** citations checked so far were wrong. The ones below live in files
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

## Suggested handling

A mechanical sweep, no design decisions: replace each dead symbol with its real owner and drop
every line coordinate in favour of the symbol name (line coordinates decay silently — this is
why the campaign cuts them unconditionally, even when currently correct).

Do `CLAUDE.md` and `.planning/codebase/` **first** and separately — they are the highest-leverage
two files in the repo for plan quality, and fixing them is independent of everything else.

Note the recurring shape across all of items 1–3: **a method moved, and its old address survived
in files that did not move.** Worth a grep-for-dead-symbols check at phase close, since the
mechanism is not going to stop on its own.

**Related:** [[comment-campaign-code-defects]], [[comment-campaign-untested-safety-claims]],
[[claude-md-alembic-migration-chain-path-wrong]] (an earlier instance of CLAUDE.md drift).

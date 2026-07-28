---
status: open
created: "2026-07-28"
source: comment-reduction campaign (13 files, 2026-07-28) — category-3 claims KEPT because no test covers them
tags: [test-coverage, live, safety, okx, halt, thread-affinity, category-3]
resolves_phase: ""
---

# Behavioral claims kept in comments because no test covers them

**Origin:** The 2026-07-28 comment-reduction campaign. Its category-3 rule: a comment making a
*behavioral* claim belongs in a test — if a test exists, delete the comment (the test is
executable and fails when the claim stops being true); if none exists, **keep the comment and
report the gap**. The gaps are below.

Each is a claim currently defended by nothing but prose. The comment is still in the file, so
nothing is lost today; the point is that a refactor can break any of these and every gate stays
green.

Ordered by what a silent regression would cost.

## High — a regression is silent and live-path

- **`SafetyController._persist_state` swallow-and-log.** *"A write failure (e.g. an un-migrated
  schema) is swallowed-and-logged so a status transition — a halt above all — is never aborted
  by the read-model write."* No test injects a raising `system_store`
  (`test_system_stats_store.py` only round-trips the store itself). **A regression converts
  every halt into an exception on the live loop** — the failure mode the swallow exists to
  prevent, on the one path that must not fail.

- **`SafetyController._notify_status_change`** — exception swallow, and the requirement that the
  callback runs **outside** the lock. No test passes a raising callback; nothing asserts the
  unlocked call. Grep for `notify_status_change` in `tests/` finds only an unrelated passthrough
  in `tests/support/replay_harness.py`. Ordering-under-lock is exactly the class of constraint
  that a later "tidy up" reverses without noticing.

- **`OkxDataProvider._okx_interval` — the `1M` case-fold collision.** *"The month token `1M`
  collides with the minute intent of a naive `.lower()`, so the map is looked up verbatim."*
  **No test touches `_okx_interval` or `_OKX_INTERVALS` at all.** A `.lower()` "cleanup" would
  silently route the month channel to the 1-minute channel — wrong data, no error, no gate.

## Medium — real hazards, louder failure or narrower blast radius

- **`OkxDataProvider.unsubscribe`'s `coro.close()` on spawn failure.** *"An un-awaited coroutine
  raises a `RuntimeWarning` that is test-fatal under `filterwarnings=["error"]`."*
  `test_okx_unsubscribe_marshal.py` has no `coro.close` / `RuntimeWarning` assertion. Self-
  announcing if broken (the suite goes red), which is why it is not High — but it would go red
  somewhere unrelated.

- **`OkxExchange.set_halt_signal`** — *"`halt()`'s blocking durable `record_halt` SQL write would
  stall every stream sharing the loop."* `test_fatal_alert_carries_no_secret_substring` covers
  the secret-leak concern on this path, not the loop-stall hazard.

- **`OkxExchange._on_stream_down_with_floor`** — *"Runs on the connector loop thread — flag-only,
  no blocking venue I/O."* `test_reconnect_resilience` covers debounce/pause behaviour; nothing
  asserts the callback performs no blocking I/O. Thread-affinity rules are an always-keep for the
  campaign precisely because they are invisible in the code.

- **`OkxExchange.connect()`** — the stream spawn handles are *"never `.result()`-awaited — they
  loop forever."* No test asserts they are left un-awaited.

- **`OkxExchange.disconnect()`** — *"Stream-task cancellation is owned by the connector's
  disconnect."* Cross-object cancellation ownership is untested.

## Low — architectural invariants, no runtime failure mode

- **`OkxExchange.is_streaming_healthy`** — the GIL-atomic lock-free-read justification.
- **`OkxExchange.resolve_precision`** — *"`Universe` stays connector-free: every connector read
  happens HERE."* An architectural invariant with no enforcing test; the natural guard is an
  import-boundary assertion, not a unit test.
- **`OkxDataProvider._hand_closed_bar`** — the drop-and-log branch when no sink is registered.
  Every test calls `set_bar_sink` first.

## What the campaign found about coverage generally

Coverage in this codebase is good where it was written deliberately and absent where a comment
stood in for it. `stream_recovery_handler.py` was the clean case: **all ten** of its behavioral
claims mapped to a test, which is why its prose could be cut by 43% with nothing kept for lack
of coverage. The OKX arm is also well covered (dedup, fast-fill race, clOrdId length raise,
fail-closed `validate_symbol`, ambiguous-timeout non-terminalization, negative-fee `abs()`).

The gaps cluster in **error/degradation paths** — the swallow, the raising callback, the
unregistered sink, the un-awaited coroutine. Happy paths get tests; the guard that exists so a
failure does not cascade gets a comment.

## Suggested handling

The three High items are small, self-contained unit tests (inject a raising double, assert the
transition still completes / the lock is not held / the map is read verbatim) and are worth doing
as one batch. Medium items suit whichever phase next touches the OKX connector arm. Low items may
be better served by an architectural assertion or simply left as documented invariants — not
every claim needs a test, but each should be a decision rather than an oversight.

**Related:** [[comment-campaign-code-defects]], [[comment-campaign-dead-symbol-citations]].

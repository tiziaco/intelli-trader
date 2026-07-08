---
status: scheduled
created: "2026-07-07"
source: v1.7 milestone-close disposition sweep of the Phase-5 remediation roadmap (v17_bugs / v17_audit_results / v17_arch_decisions / v17_widen_audit_architecture)
tags: [live, carry-forward, v1.8, circuit-breaker, resilience, observability, docs, refactor]
resolves_phase: ""
folded_into: "v1.8 spec §18 — CF-1…CF-7 (§1→P9, §2→P8, §3→P6, §4→P6/§8f, §5→P9, §6→P1, §7→P8)"
---

# v1.7 residual carry-forward — 7 open deliverable/refactor/doc gaps

**Origin:** the v1.7 Phase-5 adversarial-review roadmap (four docs, archived at close to
`.planning/milestones/v1.7-review/`). A read-only disposition sweep at milestone close
(2026-07-07) verified every enumerated item against HEAD: **32 FIXED-IN-HEAD, 7 genuinely-open,
0 regressions.** Every CRITICAL/WARNING V17 defect (V17-01…16) and the entire 05-13 WR family is
fixed in HEAD — consistent with `.planning/v1.7-MILESTONE-AUDIT.md`. **None of the 7 below is a
money-correctness bug or a v1.7-blocker** — they are deliverables/refactors/docs that were scoped
in the roadmap but not built. Carried here as one unit for triage at v1.8 kickoff
(`gsd-review-backlog`).

Separately-tracked v1.7 deferrals (NOT part of this set): margin-equity WR-01
(`margin-equity-double-counts-notional-wr01.md`), off-vocabulary halt reason WR-04
(`off-vocabulary-halt-reason-baseline-residual-wr04.md`).

---

## 1. AUD-3 — ERROR-route circuit breaker  **[Priority: HIGH — unblocked, real safety gap]**

The single most consequential open item. This is the "V17-01 ran an entire e2e suite green with
zero settlements" guard.

- **Gap:** `LiveTradingSystem._publish_and_continue` (`live_trading_system.py:686`) increments
  `errors_count` and emits one `ErrorEvent` per failure, then continues **forever** — there is no
  aggregate tripwire. A money route that fails on every event produces an infinite green-looking run.
  (The "breaker halt" references at `:436/:870/:1679` are the ARCH-4 *durable-halt record*, not
  this error-rate breaker.)
- **Spec already drafted:** `v17_audit_results.md` §3b — route-classified ring on the
  `_publish_and_continue` seam: SETTLEMENT (FILL → portfolio/order handler) halts on **first**
  failure; ORDER-IO N=3 in 60s; ADMISSION (SIGNAL) N=3 in 300s; FILL-TRANSLATION (`okx.py` per-trade
  swallow S8) must first emit a counted `ErrorEvent` then treat as SETTLEMENT; LOOP-BACKSTOP N=5/60s.
  Guard with `_stats_lock`; trip via the existing idempotent `halt(reason)`; surface counters +
  last-trip reason in `get_status()`.
- **Now unblocked:** its hard dependency — the ARCH-4 HALTED latch (V17-03) — has landed, so the
  breaker's `halt()` will no longer be clobbered back to RUNNING.
- **Preserve:** WR-06 terminal ERROR-route swallow; backtest fail-fast untouched (breaker is an
  aggregate tripwire *on top of* the documented publish-and-continue policy, not a per-event change).

## 2. `LiveBarFeed.backfill_on_resume` still unwired

- **Gap:** `live_bar_feed.py:395` (`backfill_on_resume`) is called only by
  `tests/integration/test_live_bar_feed_warmup.py`; no production resume path invokes it. A reconnect
  straddling a bar close recovers only at the next delivered bar — up to one bar-period stall (1d).
- **Now unblockable:** AUD-5 §5d prescribed wiring it **loop-natively** (on the connector loop, via
  the reconnect callback — not the engine thread) only *after* the V17-15 loop-native gap-backfill
  redesign landed. V17-15 is fixed (`_replaying_backfill` guard + `spawn_gap_backfill`), so the safe
  landing now exists. Wiring it on the engine thread remains unsafe (second concurrent writer racing
  the connector-loop `update()` on ring/guard state).

## 3. AUD-4 — `LiveConnector` Protocol contract docstrings not added

- **Gap:** the call-site fixes landed (V17-07/09/15), but `connectors/base.py:53-92`
  (`call`/`spawn`/`disconnect`) still lack the §4c CONTRACT text — the central place implementers
  read the rules. Recurrence risk: a future connector author re-introduces a timeout-≠-did-not-happen
  or call-from-loop-thread bug with nothing in the Protocol to stop them.
- **Ready to paste:** the three docstring blocks are written verbatim in `v17_audit_results.md` §4c
  (timeout does NOT cancel the in-flight coroutine → treat as unknown/reconcile; NEVER call from the
  loop thread; disconnect is best-effort, streams may still emit after it returns).

## 4. Stream-supervisor state machine — now triplicated (DRY)

- **Gap:** `_run_stream_supervisor` is reimplemented three times — `okx.py:708`, `venue.py:356`,
  `okx_provider.py:462`. The V17-07 fix (adding a supervisor to the previously-bare
  `_stream_account`/`_stream_positions`) replicated the ~100-line state machine a third time. Extract
  to one shared helper. Was a LOW-batch item; the V17-07 fix worsened it.

## 5. Alert egress remains log-only  *(already documented as ARCH-4 F/U-10)*

- **Gap:** a pluggable sink seam exists (`live_trading_system.py:668`) but routes only to the ERROR
  log route — a 3am halt reaches nobody. Pairs naturally with the ARCH-4 Layer-2 durable halt record
  and the FastAPI control-plane milestone (see memory `fastapi-application-layer-plan`). Listed here
  for completeness; the substantive home is the FastAPI milestone, not a v1.7 fix.

## 6. D-03a note absent from `CONVENTIONS.md`  *(doc-consistency)*

- **Gap:** AUD-6 §6d specified updating the dual-validator (D-03a) paragraph in
  `.planning/codebase/CONVENTIONS.md` — its cited authoritative home. The substance (V17-16 fixed:
  `add_event` fail-closed + OKX preflight; `TradingInterface` deleted) is carried in CLAUDE.md's
  D-03a note (W4-09), but the CONVENTIONS.md-specific paragraph was never applied. Low-severity;
  ready-to-paste replacement text is in `v17_audit_results.md` §6d.

## 7. `_relink_bracket` bare `matched["id"]` subscript  *(minor robustness)*

- **Gap:** `venue_reconciler.py:411` does `str(matched["id"])` with no guard — `KeyError` if a
  fallback-matched resting order carries no `id`. Fail-loud at restart, **not** a silent money bug.
  Add a guard / typed error. Was a LOW-batch item.

---

**Disposition provenance:** full 39-row FIXED/OPEN table produced by the milestone-close
disposition sweep (2026-07-07); the four source roadmap docs are archived at
`.planning/milestones/v1.7-review/`.

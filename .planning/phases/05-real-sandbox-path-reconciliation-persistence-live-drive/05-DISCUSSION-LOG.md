# Phase 5: Real/Sandbox Path + Reconciliation + Persistence Live-Drive - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-07-02
**Phase:** 5-real-sandbox-path-reconciliation-persistence-live-drive
**Areas discussed:** Halt semantics, Restart/external reconciliation, Operator alerting, Scope & DoD,
Store durability, Partial-fill terminal policy, Reconciliation cadence, Phase-4 review carry-over (WR-04),
RES-01 resilience hardening

---

## Halt semantics (RECON-01/03)

Grounded in a framework survey first: nautilus-trader (installed) = auto-correct within precision
tolerance → else "terminate immediately to prevent operation in degraded state"; freqtrade/Hummingbot =
self-heal toward exchange, no drift-halt. User confirmed the conservative nautilus posture.

| Question | Options | Selected |
|----------|---------|----------|
| Halt scope | Halt whole engine / Freeze drifting symbol | Halt whole engine ✓ |
| On halt | Freeze in place (nautilus) / Cancel orders+freeze / Flatten | Freeze in place ✓ |
| Tolerance | Precision-based epsilon (nautilus) / Absolute floor OR % / You decide | Precision-based epsilon ✓ |

**Notes:** User leaned option 1 (whole-engine halt) for the first version after seeing that it matches
nautilus's terminal fallback. → D-01/D-02.

---

## Restart / external reconciliation (RECON-05)

| Question | Options | Selected |
|----------|---------|----------|
| Restart conflict | Venue wins within band, halt beyond / Venue always wins, adopt all / Halt on ANY disagreement | Venue wins within band, halt beyond ✓ |
| Manual/external live actions | Adopt-and-continue (self-heal) / Adopt cancels, halt on external fills / Strict: any external halts | Adopt-and-continue ✓ |
| Brackets on restart | Re-adopt from venue / Cancel+re-declare / Halt if in-flight | Re-adopt from venue ✓ |

**Notes:** User asked "will this reconcile a manually closed order?" — led to the distinction between a
manual *cancel* (adopts cleanly) vs a manual *position close* (an external fill). User chose
adopt-and-continue so manual intervention self-heals rather than halting. Bracket re-adopt confirmed with
the per-bracket halt-and-alert fallback when a leg can't be confidently re-linked. → D-03/D-04/D-05.

---

## Operator alerting (RES-01)

| Question | Options | Selected |
|----------|---------|----------|
| Alert egress | Log+ErrorEvent now, pluggable sink for later / Log+ErrorEvent only / External notifier now | Log+ErrorEvent + pluggable sink ✓ |
| Distinct HALTED status | Yes — distinct HALTED status / No — log/event enough / You decide | Yes — distinct HALTED status ✓ |

**Notes:** Landscape noted (freqtrade ships Telegram/webhook first-class; nautilus leaves delivery to
infra). External push deferred post-milestone behind the sink seam. → D-06/D-07.

---

## Scope & DoD (RECON-04/06, RUN-01)

Control-plane deferral resolved after a "when/where/why would I need this?" clarification — explained the
headless-worker control-plane rationale and that sandbox validation drives the worker directly.

| Question | Options | Selected |
|----------|---------|----------|
| Control plane (LISTEN/NOTIFY + FastAPI) | Defer both to app-layer plan / Build channel now, defer FastAPI / Build channel + FastAPI now | Defer both ✓ |
| DoD evidence | Offline gate + opt-in live-sandbox suite / + manual runbook / fixtures + runbook only | Offline gate + opt-in live-sandbox suite ✓ |

**Notes:** User: "yes let's defer both. i'll design this part later." Sandbox validation is
local/interactive, so no out-of-process channel needed for the DoD. → D-08/D-09.

---

## Store durability (RECON-04)

User asked pros/cons and noted they store equity per bar in backtest — "shouldn't i do the same for
live?" Clarified the split between restart-correctness (orders/positions) and observability (equity
curve), and that per-bar equity should ride the async path to avoid Pitfall 9.

| Question | Options | Selected |
|----------|---------|----------|
| Working set | Split paths (Approach A) / All sync every bar (Approach B) / You decide | Split paths ✓ |
| Signals | Persist best-effort (async) / Persist sync-durable / Defer in-memory | Persist best-effort (async) ✓ |

**Notes:** Yes to per-bar live equity — but on the async/best-effort writer, not the sync-critical path.
→ D-10/D-11.

---

## Partial-fill terminal policy (RECON-02)

| Question | Options | Selected |
|----------|---------|----------|
| Cancel of a partial | Keep partial, cancel remainder → CANCELLED / Treat as error-halt / You decide | Keep partial → CANCELLED ✓ |
| Stuck partial | No engine timeout / Engine-imposed timeout | No engine timeout ✓ |

**Notes:** Resume-mid-partial on restart follows the venue-authoritative rule (D-03). → D-12/D-13.

---

## Reconciliation cadence (RECON-01; Phase-2 D-11 data-flow)

Second question re-asked with a concrete two-thread timeline example (partial fill on the async thread vs
the queue drain on the engine thread) showing the phantom-drift race (Pitfall 8).

| Question | Options | Selected |
|----------|---------|----------|
| VenueAccount ingestion | Push stream + REST pull for snapshot/gap / Pull-only / You decide | Push stream + REST pull ✓ |
| Drift compare + halt runs | Engine thread — on fill + on bar / Async thread immediate / Periodic timer | Engine thread — on fill + on bar ✓ |

**Notes:** User asked for an example — the phantom-drift race (venue-cache 0.4 vs engine 0.0 before the
queue drains) made the engine-thread choice clear. → D-14/D-15.

---

## Phase-4 code-review carry-over (WR-01/02/04)

User flagged "the WR warning surfaced during the phase 4 code review." Reviewed 04-REVIEW.md: three
deferrals — WR-01 (live daemon records no metrics; keys TIME, feed emits BAR), WR-02 structural
(coincidental parity config), WR-04 (paper replay under publish-and-continue vs backtest fail-fast).

| Question | Options | Selected |
|----------|---------|----------|
| WR-04 error policy | Split: replay=fail-fast, live=publish-and-continue / Document divergence / Both fail-fast | Split ✓ |

**Notes:** WR-01 resolved-by-decision (Area 5 per-bar equity = key metrics on BAR — D-16); WR-02
structural folded as a shared-parity-config cleanup (D-18); WR-04 split (D-17). → D-16/D-17/D-18.

---

## RES-01 resilience hardening

| Question | Options | Selected |
|----------|---------|----------|
| While stream disconnected | Pause new orders, resume after reconcile / Keep trading on cached state / You decide | Pause new orders, resume after reconcile ✓ |
| Connector failure policy | Classify + bounded retry → HALT on exhaustion/fatal / Retry forever / You decide | Classify + bounded retry → HALT ✓ |

**Notes:** Don't trade when you can't see the venue; transient errors retry with backoff, fatal/exhausted
escalate to HALTED + alert. → D-19/D-20.

---

## Claude's Discretion

Deferred to the plan-time research sprint (not user-owned): exact drift thresholds / precision-epsilon
numbers; reconnect debounce + retry ceiling; OKX partial-fill field cadence + fill-ID semantics;
write-through transaction boundary (keep-only-measured); rate-limit bucket accounting across ccxt+native;
bracket re-link mechanics; VenueAccount cache data structures + push mechanism.

## Deferred Ideas

- Postgres LISTEN/NOTIFY channel + FastAPI wrapper → FastAPI application-layer plan (D-08).
- External alert push (Telegram/webhook/email) → post-milestone, into the D-06 sink seam.
- Real-money execution → gated stretch beyond the DoD.
- Faster on-timer drift backstop (engine-thread-marshalled) → post-v1.
- Strategy-level partial-fill aging/timeout → strategy concern.
- Async/buffered write-through → keep-only-measured.
- ROADMAP + REQUIREMENTS doc-sync (stale RUN-01 + PAPER-01/02/04) → fold into Phase-5 planning (D-18).
- Reviewed-not-folded: margin-equity WR-01 valuation gap; single-pass-portfolio-valuation.

---

# Plan 05-13 (WR-05 correlation-state remediation) — Discussion Log

**Date:** 2026-07-04
**Phase:** 05-real-sandbox-path-reconciliation-persistence-live-drive (reopened)
**Areas discussed:** Release-hook placement, Dedup-ring structure/capacity, Late-echo safety
**Requirements locked upstream:** R1–R3 + zero-backtest-impact gate (05-SPEC.md) — not re-decided.

---

## Release-hook placement (WR05-D1)

| Option | Description | Selected |
|--------|-------------|----------|
| (a) OkxExchange / VenueCorrelationIndex self-managed | Track cumulative-filled per venue_id in the index; self-release on cumulative == quantity. Live-isolated, zero backtest touch; "duplicates" the fully-filled check. | ✓ |
| (b) ReconcileManager terminal transition | Single terminalization authority; but shared engine-thread code that also runs backtest → needs an injected release-callback (None/no-op in backtest), inverting the order→execution dependency. | |

**User's choice:** (a), refined — after asking "what's the *most correct* option, does it need a read-class like portfolios, and what's the risk?"
**Notes:** User initially leaned (b) to avoid duplication. Boundary analysis flipped it: (b) is a cross-domain write (queue-only contract + EventType ban forbid the clean routes), and release is a WRITE to the exchange's own memory — NOT a `PortfolioReadModel`-style read seam. The "duplication" folds into R1's `VenueCorrelationIndex` (per-venue_id counter). Risk (counter drift → entry never released) mitigated: same trades feed both, cleanup-only concern, never affects money correctness; non-fill terminals are the already-carved R4 residual.

---

## Dedup-ring structure/capacity (WR05-D2)

| Option | Description | Selected |
|--------|-------------|----------|
| deque(maxlen)+set, cap 10000 | O(1) membership via set, FIFO eviction via deque — mirrors LiveBarFeed deque-ring precedent; DB venue_trade_id backstop for evicted ids. | ✓ |
| OrderedDict as LRU, cap 10000 | Single-structure LRU (move_to_end / popitem). Less code, but not the codebase precedent. | |

**User's choice:** deque(maxlen)+set, cap 10000.
**Notes:** Capacity configurable; in-memory ring only needs to cover the reconnect re-send window.

---

## Late-echo safety (WR05-D3)

| Option | Description | Selected |
|--------|-------------|----------|
| Drain buffer → emit → then evict | Drain pending-fills buffer for the venue_id and emit those FillEvents before dropping entries; mint/emit outside the lock; idempotent release. | ✓ |
| Evict immediately, DB dedup backstop | Drop entries on terminal, rely on DB dedup; risks dropping a genuinely-late buffered fill (the WR-02 failure mode). | |

**User's choice:** Drain buffer, emit, then evict.
**Notes:** Matches the existing `_submit_order`/`adopt` re-drain-outside-lock pattern; guarantees no WR-02 regression.

## Claude's Discretion (Plan 05-13)
- Exact home/type of the cumulative-filled counter inside `VenueCorrelationIndex` + its Decimal-equality guard (WR05-D1).
- Config key/surface for the ring capacity (WR05-D2).
- Whether `register/resolve/adopt/release/mark_seen` lock internally or expose the lock (R1 detail; keep WR-03 guarantees).

## Deferred Ideas (Plan 05-13 → R4 / future phase)
- Non-fill terminal release (partial-then-cancel / expire / reject-without-fill) mid-session.
- Out-of-band (web-UI) cancel coverage.
- Native OKX OCO/algo orders; multi-venue.

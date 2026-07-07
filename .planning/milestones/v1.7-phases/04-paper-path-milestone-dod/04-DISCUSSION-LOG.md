# Phase 4: Paper Path (milestone DoD) - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-07-02
**Phase:** 4-paper-path-milestone-dod
**Areas discussed:** Parity harness design, apply_costs extraction boundary, RUN-01 topology scope, COV-01 / FL-13 coverage scope

---

## Parity harness design (the DoD gate)

The discussion opened by clarifying that the byte-exact DoD gate must be an **offline replay of the
fixed golden dataset** — real-time OKX data can never reproduce the frozen oracle (different prices,
different dates). Two tracks were separated: (1) the byte/numeric parity gate = offline golden
replay; (2) a real-time OKX paper run = a separate, non-byte-exact "it trades live" validation.

The user then relaxed the anchor: "byte parity is not important since I'll probably change the
backtest loop as well." Three notions were distinguished:

| Notion | Description | Selected |
|--------|-------------|----------|
| #1 Backtest-inert gate | Adding live code doesn't disturb the backtest (stays 134/`46189…`) | ✓ kept (unrelated) |
| #2 Paper ≡ frozen golden artifact | Pin live-paper to the committed `tests/golden/` numbers | ✗ dropped |
| #3 Paper ≡ backtest, same data | Two paths produce identical trades/equity side-by-side, exact | ✓ kept |

**User's choice:** Drop #2, keep #3 — same data, exact equality. "I believe we'll get the same
results anyway with the live mechanism."

Sub-decisions:
- **Replay entry:** a fake/replay provider generating the same `BarEvent`s an `OkxDataProvider`
  would (through `set_bar_sink` → `LiveBarFeed.update()`), NOT the `TimeGenerator` pull path. Chosen
  to exercise the real live mechanism.
- **Drive model:** synchronous in-thread (deterministic, offline). Async-through-real-loop deferred
  to a Phase-5 live smoke test.

**Notes:** Revises PAPER-04 / LX-11 — flagged for ROADMAP + REQUIREMENTS update. Transitive property
noted: the oracle test still pins backtest to `46189…`, so paper==backtest==`46189…` holds today,
but the parity test needs no edit when the loop is reworked + oracle re-frozen.

---

## apply_costs extraction boundary → dissolved (reuse SimulatedExchange)

Presented as: extract `apply_costs` (pure cost core) + decide how much a paper adapter shares with
`SimulatedExchange`. The user challenged the premise: "can't I simply use the `SimulatedExchange`
for the live paper as well? they have the same task in the end, to simulate what a real exchange
would do."

| Option | Description | Selected |
|--------|-------------|----------|
| Separate PaperExchange + shared apply_costs | Build a new adapter, extract the cost core to avoid drift | ✗ |
| Shared base class | `MatchingExchangeBase` both subclass | ✗ |
| Reuse `SimulatedExchange` as-is | It already implements `AbstractExchange`; one impl, no drift | ✓ |

**User's choice:** Reuse `SimulatedExchange` as-is. Verified no blocker: zero backtest-only coupling,
clean DI, feed-agnostic routing, already half-wired in `LiveTradingSystem`.

**Notes:** Collapses PAPER-01/PAPER-02 — `apply_costs` extraction DROPPED (no second impl to keep in
sync). Revises LX-06 ("reuse `MatchingEngine`, not the whole `SimulatedExchange` class") — flagged
for ROADMAP + REQUIREMENTS. Paper exchange stays account-free (backtest-identical); `SimulatedAccount`
lives portfolio-side.

---

## RUN-01 topology scope

| Option | Description | Selected |
|--------|-------------|----------|
| Decide + seam only, run in-thread | Document topology, defer all build to Phase 5 | |
| Build the worker process now | Full worker + Postgres LISTEN/NOTIFY end-to-end | |
| Build worker, defer LISTEN/NOTIFY | Runnable worker + lifecycle now; channel later | ✓ |

**User's choice:** Option 3, scoped per Claude's suggestion — "build the runnable worker, defer the
channel." Phase 4 builds a standalone worker entrypoint + start/stop lifecycle (runnable against the
replay provider AND the real `OkxDataProvider`); defers the Postgres `LISTEN/NOTIFY` channel +
FastAPI integration to Phase 5.

**Notes:** Revises the RUN-01 "Postgres LISTEN/NOTIFY as the default channel [in Phase 4]" framing —
channel → Phase 5. The parity gate does not depend on the worker (runs in-test, synchronous).

---

## COV-01 / FL-13 coverage scope

**User's choice:** Real-`OkxDataProvider` live-smoke path is **manual/opt-in**; automated
real-connector coverage deferred to Phase 5.

FL-13 scope agreed for Phase 4: parity gate = anchor E2E coverage; lifecycle/command-surface tests
(`start`/`stop`/`get_status`); fixtures = synthetic replay provider from golden CSV (the mock
connector); real-OKX smoke test network-gated + `slow` + not in CI; `filterwarnings=["error"]` green.

**Notes:** Keeps Phase-4 CI deterministic + offline; Phase 5 owns real-connector test infra.

---

## Claude's Discretion

- Exact `Bar`/`ClosedBar` construction in the replay provider from golden CSV rows.
- Exact seed/clock threading points in the live composition root.
- Worker entrypoint file location/name and precise start/stop/status shape.
- Whether the parity test reuses `_oracle_harness` directly or via a thin wrapper.
- Whether the manual live smoke test is a `pytest -m slow` opt-in or a small script.

## Deferred Ideas

- Real `PaperExchange` subclass for venue realism (partial fills, rejections, OKX fee/lot-tick) —
  post-v1.7; subclass `SimulatedExchange` then.
- Postgres `LISTEN/NOTIFY` channel + FastAPI integration — Phase 5 / FastAPI milestone.
- Driving the parity replay through the real async connector loop — Phase 5 live smoke.
- Unify the backtest loop to bar-direct — the rework D-01 is designed to survive; post-v1.7.
- Reviewed, not folded: `margin-equity-double-counts-notional-wr01.md`,
  `single-pass-portfolio-valuation.md` — valuation concerns that cancel across both parity paths.

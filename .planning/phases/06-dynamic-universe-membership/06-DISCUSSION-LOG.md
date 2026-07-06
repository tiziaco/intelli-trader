# Phase 6: Dynamic Universe Membership - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-07-06
**Phase:** 6-dynamic-universe-membership
**Areas discussed:** Remove policy, Poll trigger, Seam shape, Change-propagation seam, Add scope, Venue-bounded selection

---

## Q1 — Remove policy (open position on remove)

| Option | Description | Selected |
|--------|-------------|----------|
| Orphan, keep stream, no backstop | Position stays open + subscribed until flat; block new entries; pure hands-off | |
| Orphan, keep stream, with backstop | As above + force-close after N bars | |
| Force-close | Emit market exit at removal time, then detach | |
| Configurable (default orphan) | Force-close + orphan behind a flag; default orphan-and-track | ✓ |

**User's choice:** Configurable, default orphan-and-track.
**Notes:** Orphaning implies keeping the WS subscription + ring alive until the position is flat
(else SLTP/exit can never fire). Optional force-close-after-N-bars backstop discussed but not
locked — left to plan-time discretion.

---

## Q2 — Poll trigger (what drives a membership re-evaluation)

| Option | Description | Selected |
|--------|-------------|----------|
| Clock-timer TIME route | Real timer fires TimeEvents on a cadence decoupled from bars (Phase-3 D-05 reserved) | ✓ |
| Bar-driven poll | Check membership on closed-bar arrival; simpler, coupled to bar cadence | |
| External command | Add/remove only via explicit engine command; no autonomous poll | |

**User's choice:** Clock-timer TIME route.
**Notes:** Wires the dormant TIME route Phase 3 D-05 reserved for exactly this. Framework-idiomatic
(Nautilus clock timers / LEAN scheduled selection).

---

## Q3 — Seam shape (where selection logic lives / how Universe changes)

| Option | Description | Selected |
|--------|-------------|----------|
| You decide at plan time | Lock the propose/dispose principle; defer class split | |
| Pure select + orchestrator disposes | membership.py select()->set; LiveTradingSystem diffs + side effects | |
| Universe owns mutation | Universe grows add/remove; diff inside Universe.apply() | ✓ |

**User's choice:** Universe owns mutation.
**Notes:** Resolved to `Universe.apply(desired) -> UniverseDelta` — the diff happens inside
`apply` (it holds current members, receives desired). Universe stays queue-free; side effects
(subscribe/warmup/close) live in event consumers, preserving propose/dispose separation.

---

## Change-propagation seam (how a membership change reaches the provider — Axis 1)

| Option | Description | Selected |
|--------|-------------|----------|
| A — Provider pulls from Universe | Read-model + explicit sync; couples provider→universe, cuts against queue-only rule | |
| B/C — Push a change event | `UniverseUpdateEvent` carries the delta; provider is a pure consumer | ✓ |

**User's choice:** Push a change event (B/C).
**Notes:** Most idiomatic for this codebase's queue-only cross-domain contract. Framework
convergence (LEAN `SecurityChanges`, Nautilus `DataEngine` subscription registry) confirmed the
no-duplication model: one membership owner (Universe), a diff, and a data-layer subscription
registry that follows it. Event named **`UniverseUpdateEvent`** (msgspec `Event` subclass, NOT a
dataclass; `type` is a `ClassVar[EventType]`), carrying `added`/`removed` delta. Diff happens
inside `Universe.apply()`; poll handler emits. Distinct from the existing `ScreenerEvent`
("propose" vs this "dispose").

---

## Q4 — Add scope (how far the ADD path goes for live OKX)

| Option | Description | Selected |
|--------|-------------|----------|
| Lean — seam + warmup, defer live re-subscribe | Demonstrate subscribe/unsubscribe on replay provider; defer real OKX WS | |
| Full — real live OKX dynamic subscribe/unsubscribe | Extend OkxDataProvider with mid-run subscribe/unsubscribe, sourced from universe | ✓ |
| You decide at plan time | Lock seam+warmup+remove-policy; let research assess live re-subscribe | |

**User's choice:** Full (revised up from an initial lean recommendation).
**Notes:** User pushed back on the lean default — correctly. The code itself earmarks this:
`_OKX_STREAM_SYMBOL = "BTC/USDC"` carries the comment "the pair becomes configurable via the
universe subsystem in the next phase" (= Phase 6). The demo provides a second tradeable pair
(ETH/USDC) to prove dynamic add/remove live. Key nuance surfaced: **data subscription** is
live-testable on the demo (market-data, any listed symbol, not gated by MiCA/price-floor), while
**order settlement** of dynamic symbols stays paper/replay-verified per the Phase-5 demo
constraint. No data duplication: the provider is a pure `UniverseUpdateEvent` consumer owning only
a mechanical subscription registry.

---

## Q4b — Venue-bounded selection

| Option | Description | Selected |
|--------|-------------|----------|
| Bound selection by venue markets map | Reuse `OkxExchange.validate_symbol()` / `connector.client.markets` | ✓ |

**User's choice:** Bound by the venue markets map.
**Notes:** The "allowed tickers list from the venue" the user recalled — it already exists
(`load_markets()` populates `client.markets`, the source of truth `validate_symbol` consults).
Universe selection may only propose OKX-listed symbols.

---

## Claude's Discretion

- Exact class/method split of the lean selection source (`UniverseSelectionModel` in
  `membership.py`) vs the poll handler; whether the poll handler is new or grows onto
  `ScreenersHandler`.
- `UniverseDelta` shape + exact event field types (`tuple[str, ...]` recommended).
- Timer mechanism + default poll cadence; remove-policy flag home + optional force-close backstop.
- `subscribe`/`unsubscribe` coroutine lifecycle, OKX snapshot-on-subscribe gating, rate-limit
  across N channels.
- `validate_symbol` call site (poll handler vs a selection-side guard) and backtest/paper behavior
  when no live markets map exists.

## Deferred Ideas

- Full ranked production screener — v2.
- Burst-coalescing multi-symbol `BarEvent` (D-04 reserved seam) — not needed now.
- Live order-settlement of dynamically-added symbols (and live force-close settlement) — blocked
  by EEA demo constraints; verified on paper/replay in Phase 6, live follow-on when a flat/non-EEA
  account is available.
- Force-close-after-N-bars backstop — discussed, not locked.

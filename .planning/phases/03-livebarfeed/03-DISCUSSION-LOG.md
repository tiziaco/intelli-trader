# Phase 3: LiveBarFeed - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-07-01
**Phase:** 3-livebarfeed
**Areas discussed:** Provider→Feed seam, TimeGenerator replacement / emission model, Gap & correction policy, Capacity & warmup depth

---

## Provider→Feed seam — ingestion signature

| Option | Description | Selected |
|--------|-------------|----------|
| `update(ClosedBar dict)` | Sink calls `feed.update(closed_bar_dict)`; feed constructs the Bar internally from the Decimal-valued dict | ✓ |
| `update(Bar)` | A thin adapter constructs a `Bar`, then calls `feed.update(bar)` | |
| `update(symbol, tf, bar)` | Explicit routing args | |

**User's choice:** `update(ClosedBar dict)` (→ D-01)
**Notes:** Phase-2 `OkxDataProvider.set_bar_sink` + `ClosedBar` already establish push-callback + Decimal-at-edge; feed owns Bar construction (Phase-2 D-05). Seam mechanism was already substantially built in Phase 2.

---

## Emission model / TimeGenerator replacement (FEED-05)

### Q1 — what drives emission when `update()` runs

| Option | Description | Selected |
|--------|-------------|----------|
| `update()` emits directly | Bar arrival IS the event; feed puts event on queue itself | ✓ |
| `update()` stages, engine drains | Feed mutates ring only; separate engine step emits | |

**User's choice:** Option 1 — emit directly (→ D-02). Follow-up: "will it include all closed bars for all tickers subscribed?"

### Q2 — BarEvent payload cardinality

| Option | Description | Selected |
|--------|-------------|----------|
| Single-ticker now, coalesce-seam later | One BarEvent per arriving closed bar; reserve seam for Phase-6 coalescing | ✓ |
| Coalesce the burst now | Buffer per-timestamp, emit one multi-symbol BarEvent | |
| Single-ticker, no future seam | Simplest, revisit in Phase 6 | |

**User's choice:** Single-ticker now, coalesce-seam later (→ D-04)
**Notes:** User asked about queue-overload risk and recalled batch arrival "from Binance." Checked legacy `binance_stream.py` — confirmed per-symbol burst arrival + `_closed == 5` coalescing hack (flagged laggy by the legacy author). Queue-overload ruled out (closed bars ~once per period per symbol; forming pushes gated at provider).

### Q3 — route ordering: TimeEvent-first (Option A) vs bar-direct (Option B)

| Option | Description | Selected |
|--------|-------------|----------|
| Option A — emit TimeEvent, reuse `generate_bar_event` | Max parity; `_routes` literal byte-identical to backtest | |
| Option B — bar-direct to BAR route | Framework norm (Nautilus/LEAN/backtrader); live skips TIME route | ✓ |

**User's choice:** Option B — bar-direct (→ D-03, D-05)
**Notes:** User asked for concrete examples of both + "what do other frameworks do." Read nautilus `handle_bar` → `on_bar` (bar-direct; clock/timers are a separate orthogonal channel). User observed the backtest `TimeEvent`-per-loop pull is extra indirection and proposed unifying to B; asked how screening (TIME-before-BAR seam) is handled under B. Resolved: screening becomes a decoupled poll cadence (Nautilus/LEAN model; Phase-6 "Lean poll seam"), TIME route preserved-but-dormant. User accepted "don't touch backtest now" — backtest unification deferred to a todo.

---

## Gap & correction policy (FEED-04)

### Q1 — after-the-fact bar-correction reaction

| Option | Description | Selected |
|--------|-------------|----------|
| Forward-only + log | Reject/log a revision, never rewind indicator state | ✓ |
| Re-warm from ring buffer | Rebuild state with the corrected bar | |
| Forward-only now, re-warm seam later | Ship forward-only, shape a re-warm seam | |

**User's choice:** Forward-only + log (→ D-06, D-07)
**Notes:** User asked "what do other frameworks do." Read nautilus `data/engine.pyx` — revisions honored only for the *latest* bar; historical revisions warn-and-drop; no re-warm. `confirm==1` gate means no forming-bar-revise case. User then asked "even with option 1, don't I still need revision logic?" — clarified: detection/classification taxonomy (dup/revision/gap/stale) is required regardless (part of FEED-04, cheap); only the *reaction* is forward-only+log. Locked with that framing.

### Q2 — reconnect recovery

| Option | Description | Selected |
|--------|-------------|----------|
| Gap-driven, no special debounce | Next-bar gap branch handles it passively | |
| Explicit backfill-on-reconnect | Proactively check + backfill on socket resume | ✓ (refined) |

**User's choice:** Proactive backfill-on-reconnect, boundary-gated (→ D-08)
**Notes:** User reasoned "backfill on reconnect, or at least check if I need to — if the outage is lower than the min timeframe then ok, but if bars are missing, backfill the spaces." Refined the "outage < timeframe" heuristic to an exact completed-bar-boundary check (a short outage can straddle a bar close). Composes with resumed stream via the duplicate branch.

---

## Capacity & warmup depth (FEED-01/03)

### Q1 — ring capacity

| Option | Description | Selected |
|--------|-------------|----------|
| Same `cache_capacity()` derivation as backtest | Purely derived, one source of truth | ✓ |
| Fixed generous constant | Hardcode a large maxlen | |

**User's choice:** Same `cache_capacity()` derivation (→ D-09)

### Q2 — warmup depth K

| Option | Description | Selected |
|--------|-------------|----------|
| Derive K from capacity | K = `cache_capacity()` | |
| Capacity + safety margin | K = `cache_capacity()` + buffer | ✓ |
| Configurable override | Default + per-run override | |

**User's choice:** Capacity + safety margin (→ D-10)

### Q3 — multi-timeframe handling

| Option | Description | Selected |
|--------|-------------|----------|
| Base-tf stream + pull-resample (backtest parity) | Single base BarEvent stream; higher tf via `window()` resample | ✓ |
| Native per-tf tagged events (Nautilus) | Per-tf subscriptions, timeframe-tagged events, dispatch on tag | |
| Base timeframe + consolidate-up now | Build the consolidator here | |

**User's choice:** Base-tf stream + pull-resample (→ D-11)
**Notes:** User picked multi-key initially, then asked "what happens with 5m + 15m — 2 different events? what do frameworks do?" Confirmed `Bar`/`BarEvent` carry NO timeframe field today; backtest is single-base-stream + pull-resample. Frameworks (Nautilus `BarType`, LEAN, backtrader) tag-and-dispatch per timeframe. User asked "architecturally, what's most correct/robust, and what happens to multi-tf strategies?" Verdict given: native tagged (B) is architecturally superior/more robust but only coherent if backtest adopts it too (else parity breaks) → deferred; Option A keeps live≡backtest and multi-tf strategies work via pull-resample exactly as backtest. User: "lock what you proposed."

---

## Claude's Discretion (deferred to plan-time)

- Exact `Bar` construction path from `ClosedBar` inside `update()`.
- Exact warmup safety-margin value (D-10).
- Exact asyncio-thread → `queue.Queue` put mechanism (D-02/D-19).
- Whether per-`(symbol, timeframe)` ring dict and monotonic-guard `L` tracking share one structure.

## Deferred Ideas

- **Unify backtest loop to direct bar generation** — `.planning/todos/unify-backtest-direct-bar-generation.md` (created this session; resolves the D-03 asymmetry).
- **Native tagged multi-timeframe** — `.planning/todos/native-tagged-multi-timeframe.md` (created this session; the D-11 architectural alternative).
- **Burst-coalescing multi-symbol BarEvent** — Phase 6 (D-04 seam reserved).
- **Phase-6 screening/poll cadence** wiring the dormant TIME route (D-05).
- **RES-01 reconnect/backoff hardening** — Phase 5.
- Reviewed-not-folded: `multi-timeframe-consolidator.md` (backtest half of multi-tf; deferred with its live counterpart).

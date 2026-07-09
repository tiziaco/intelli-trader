---
status: scheduled
created: "2026-07-07"
source: surfaced in v1.7 Phase 7 07-REVIEW.md CR-01 discussion (StrategyCommandEvent vs PairStrategy 2-ticker contract)
tags: [strategy, pair-strategy, universe, readiness, live-control-plane, operator-command, next-milestone, phase-7-tie-in]
resolves_phase: "P10"
folded_into: "v1.8 STRAT-03 (P10 Strategies Registry) — atomic runtime param reconfiguration; brought in-scope by owner decision 2026-07-09 (was spec §18 'not folded / deferred to ★-trimmable P11')"
---

# PairStrategy live reconfiguration — atomic ordered-pair leg swap (the "correct B" for CR-01)

**Origin:** Surfaced in v1.7 Phase 7 (Live Dynamic-Universe Hardening) while fixing **CR-01**
(`07-REVIEW.md`). CR-01's defect: `StrategiesHandler.on_strategy_command`'s `add_ticker`/`remove_ticker`
verbs mutate a strategy's plain `list[str]` tickers with **set semantics**, which structurally breaks a
`PairStrategy`'s **exact-2, ordered** ticker contract — the next `BAR` raises `ValueError` out of
`_dispatch_pair` (`strategy_handler/strategies_handler.py:325`), aborting `calculate_signals` mid-loop
every bar forever (a self-inflicted error storm with no auto-recovery).

**Phase 7 fix (the floor):** CR-01 is closed with **Option A — refuse `add_ticker`/`remove_ticker`
loudly for any `PairStrategy`** (an `isinstance` guard before the verb branches, logged no-op, no
follow-on poll). A stops the crash and is **forward-compatible**: it blocks nothing here. This todo is
the deferred **Option B done right** — the real operator capability to reconfigure a live pair.

## Why single-leg add/remove is the wrong abstraction for a pair
A `PairStrategy` (`strategy_handler/pair_base.py`) is not "a strategy with two tickers in a list." It is
an **ordered 2-tuple relationship with heavy fitted state**:
- `tickers[0]` = leg A, `tickers[1]` = leg B — **order matters** (long N of A, short β·N of B; `_entry`,
  `pair_base.py:247`). Set-ops (`add`/`remove`) cannot even name *which* leg.
- Per-leg close buffers `_buf_A`/`_buf_B` (`:162-163`), `_pair_bar_count`, and a **β fitted once on the
  specific pair's log-price relationship, then frozen** (`:158-160`).
- `is_pair_ready()` (`:185`) only returns `True` once the buffers hold `beta_warmup + z_lookback` bars
  (**280 for the reference pair**).

Swapping one leg **invalidates the entire statistical object** (β, spread, z-score, both buffers) — it is
a full reset + re-warm of the *new* pair, not a ticker edit. `_run_init()` (`:144`) is already written to
be reconfigure-idempotent (D-10) — the reset seam exists.

## The correct implementation (B2) — atomic ordered-pair swap
Do NOT overload `add_ticker`/`remove_ticker`. Add a dedicated typed command whose unit is the whole pair:

```
PairReconfigureCommand(strategy_name, leg_a, leg_b)      # typed, atomic, ordered — NOT add/remove
  1. Flatten first: emit exits for BOTH current legs; wait for flat before swapping.
     (You cannot hold an open A/B spread and swap B underneath it.) Reuse the
     universe_handler force-close -> detach-on-flat machinery (_on_symbol_removed / on_fill).
  2. Atomic reset: strategy.reconfigure(leg_a, leg_b) -> set tickers, validate(), _run_init()
     (clears _buf_A/_buf_B/_pair_bar_count/β — the existing D-10 idempotent seam).
  3. Membership delta: old leg leaves (unsubscribe if no other member uses it), new leg joins ->
     the existing UniversePollEvent -> UniverseUpdateEvent(added/leaving) path.
  4. Re-warm BOTH new legs through spawn_warmup -> BarsLoaded -> the WR-02 warm-verify gate;
     the pair stays dark (readiness closed) until is_pair_ready() (280 bars each leg).
```

## Why deferred (not done in Phase 7)
- It is a **net-new operator feature**, not a defect fix. Phase 7 is a hardening pass on an oracle-gated
  milestone — growing a control-plane capability under cover of the CR-01 guard is scope creep.
- Step 4 **reuses the exact CR-02 retry + WR-02 warm-readiness machinery Phase 7 delivers** — so B2
  should be built *on top of* Phase 7, not inside it (ordering coupling to gates written the same phase).
- A **naive B** (a `replace_pair` verb that swaps the list + emits a poll) would reintroduce **exactly the
  WR-02 partial-warmup / readiness hazard Phase 7 exists to close** — now with 280-bar warmup *and* an
  open-spread-position transition problem. Half-B is a fresh critical, strictly worse than A.

## When to schedule
Next milestone, once Phase 7's readiness pipeline (CR-02 FAILED-retry + WR-02 warm-verify gate) is
landed and locked. Natural fit alongside any live pair-trading / operator control-plane work.

## Tie-in
- Phase 7 CR-01 guard (`strategy_handler/strategies_handler.py::on_strategy_command`) is the seam this
  extends — it currently *refuses* pair mutation; B2 adds the *correct* mutation path beside it.
- Reuses: `PairStrategy._run_init` (`pair_base.py:144`, D-10 reset), `is_pair_ready` (`:185`),
  `universe_handler` force-close/detach-on-flat, the WR-02 warm-verify gate, and the
  `UniversePollEvent -> added/leaving` membership path.
- Related: `mutable-instrument-refactor.md` (both extend the Phase-7 universe/readiness seams).

# Phase 10 — Mid-Execution Decisions

Decisions resolved by the user during wave execution, after the plans were written.
Binding on all downstream plans. Recorded here so they survive orchestrator context loss.

---

## WD-1 — D-07 re-enable semantics: **re-warm on enable**

**Raised by:** Plan 10-03 (SUMMARY, finding 2) · **Resolved:** wave 1 close · **Binds:** Plan 10-06 (`enable` verb), Plan 10-08 (reconfigure re-warm)

**The conflict.** Plan 10-03's `<action>` mandated the D-07 `is_active` guard be placed *first*
in the `calculate_signals` loop; its Test 3 rationale simultaneously described disabled
indicators as continuing to "keep updating". Those are mutually exclusive — guard-first means
`strategy.update` never runs while disabled, so indicator state **freezes** rather than
advancing. 10-03 implemented the directed guard-first placement (it satisfies the plan's
`<done>` and matches the existing P5-D10c/D14 gap-skip precedent in the same loop), leaving
the consequence open: a re-enabled strategy would otherwise fire from a window containing an
**N-bar hole** spanning the disabled period.

**Decision.** `enable` MUST force a re-warmup before the strategy may emit a signal:

```
enable(strategy) ->
    strategy.is_active = True
    strategy.mark_unwarm()          # force re-warm
    warmup_pipeline.warm(strategy)  # reuse the P7 warmup path
    # first signal only after the window is contiguous
```

**Why.** Never compute a signal from a discontinuous window — indicators that span the gap
(SMA/MACD) would silently produce wrong values, which is exactly the class of defect this
milestone exists to eliminate. The cost is a few bars of latency on enable, which is
acceptable for a control-plane verb.

**Why not the alternatives.**
- *Trade immediately (10-03's raw as-is behavior)*: warmth is monotone so it "works", but
  signals silently span the discontinuity. Rejected on correctness.
- *Keep indicators updating while disabled (gate emission only)*: would revert 10-03's
  directed guard placement, burn hot-path CPU for disabled strategies, and require re-gating
  the backtest oracle. Rejected on scope + cost.

**Implementation note.** This reuses the same warmup pipeline Plan 10-07's `add` verb
requires, so `enable` and `add` should converge on one warm path rather than two.

---

## WD-2 — the unwarm seam lives on `base.Strategy`, over the existing handle reset

**Raised by:** audit finding 10-06 F1 (`mark_unwarm` does not exist) + 10-05 (rehydrate established
no warm/unwarm seam) · **Resolved:** wave 3 close · **Binds:** Plan 10-06 (`enable`), Plan 10-07 (`add`),
Plan 10-08 (reconfigure re-warm)

**Decision.** The unwarm seam is owned by `Strategy` (`base.py`), NOT by `StrategiesHandler`.

**Why — warmth already lives there.** `is_ready` IS base handle-derived warmth (P5-D06/D10b, cited at
`strategies_handler.py:213`); `warmup` is a declared field (`base.py:185`); and `_run_init`
(`base.py:383`) already *"resets handles, runs `init()`, then auto-derives warmup"*, idempotently
(`base.py:712`). `StrategiesHandler.is_warm(symbol)` (`:119`) is an **aggregate read-model that reads
through to the strategies** — it does not own warmth.

**Why NOT the handler.** An `_unwarm: set[str]` on the handler would be a **second source of truth for
warmth that can contradict `is_ready`** — desyncing on rename, removal, or any partial failure. Rejected
as actively wrong, not merely a different taste.

**CRITICAL — `mark_unwarm()` is NOT a boolean flag.** Warmth is *derived* from the indicator handles, so
a `self._warm = False` flag would immediately diverge from `is_ready`. The seam must be a **named
wrapper over the existing handle reset** (what `_run_init` already does), so `is_ready` stays the single
computed truth.

**CRITICAL — the `PairStrategy` arm.** Pair warmth is **NOT handle-derived**. Per
`strategies_handler.py:359-366`, a pair's readiness is its own `is_pair_ready()` (β fittable + z tail =
`beta_warmup` + z-tail bar count), explicitly *"NOT the handle-derived `strategy.warmup`"* — which is 0
for a handle-free `PairStrategy`, making `is_ready` always `True`. **A `mark_unwarm()` that only resets
handles would leave a pair reporting warm INSTANTLY while its spread is still cold, trading on a cold β
— WD-1's exact failure mode re-entering through the pair arm.** The seam MUST cover the pair arm.

**Oracle risk is low but must still be proven.** Touching `base.py` only re-opens the byte-exact gate if
something new is read PER BAR. A `mark_unwarm()` wrapping the existing reset adds no per-bar read
(`_run_init` already runs at construction). Re-run the oracle to prove it; do not assume it.

**Stale comment to fix.** `strategies_handler.py:164-167` currently documents the PRE-WD-1 behavior —
*"enable trades the NEXT bar with no re-warmup; removing it would cost a full 100-bar re-warm."* WD-1
knowingly accepts that 100-bar cost. Rewrite the comment or it becomes the next stale claim someone
trusts.

---

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

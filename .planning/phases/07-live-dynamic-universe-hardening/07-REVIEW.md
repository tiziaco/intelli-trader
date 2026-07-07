---
phase: 07-live-dynamic-universe-hardening
reviewed: 2026-07-07T00:00:00Z
depth: standard
files_reviewed: 3
files_reviewed_list:
  - itrader/price_handler/feed/live_bar_feed.py
  - itrader/strategy_handler/base.py
  - itrader/universe/universe_handler.py
findings:
  critical: 0
  warning: 2
  info: 2
  total: 4
status: issues_found
---

# Phase 07: Code Review Report (gap-closure — CR-01 warmup re-delivery idempotency)

**Reviewed:** 2026-07-07
**Depth:** standard
**Files Reviewed:** 3
**Status:** issues_found

## Summary

Scope was the 5-commit gap-closure slice (738644f4, 794e50ee, ee6af412, 1647ba99, e977a5d0)
implementing CR-01's warmup re-delivery idempotency (Option B / Level 2): a `_last_delivered`
cursor guard in `LiveBarFeed.absorb_warmup`, a per-symbol `_last_bar_time` cursor guard in
`Strategy.update`, and a cadence-gated FAILED-retry + 3-strike warn in `UniverseHandler.on_poll`
/ `on_bars_loaded` / `on_bars_load_failed`. This supersedes the broader 07-09-REVIEW.md scope —
those files remain unchanged except for the specific hunks below.

The three correctness properties the review focus called out as highest-risk all check out:

- **None-guard TypeError risk** (`Strategy.update`): `last_time = self._last_bar_time.get(ticker)`
  then `if last_time is not None and bar.time <= last_time` — the `is not None` short-circuits
  before the comparison, so a never-seen ticker cannot raise `TypeError`. Correct.
- **`evaluate()` replay dependency on `_reset_ticker`**: `_reset_ticker` pops `_last_bar_time[ticker]`
  alongside the other per-symbol dicts, so a second `evaluate(ticker, window)` call is not rejected
  by its own prior replay's cursor. Verified via `tests/unit/strategy/test_update_idempotency_cr01.py`
  and `test_causal_guard.py` (both pass, `poetry run pytest`, 11/11).
- **`UniverseHandler` cadence gate + 3-strike streak**: the first-attempt-allowed case
  (`last_at is None`), the `< interval` vs `>= interval` boundary, and the mid-stream
  success-then-later-failure streak reset (`_reset_rewarm_streak` pops the streak but
  deliberately leaves `_last_rewarm_at` alone, so a much-later failure is not spuriously
  cadence-gated) all trace correctly. Verified via `tests/unit/universe/test_retry_policy_cr01.py`
  and `test_warmup_retry_idempotency_cr01.py` (14/14 pass).
- **Backtest inertness**: none of the three guards are reachable on the backtest hot path with a
  non-trivial effect — `Strategy.update`'s guard is a documented byte-exact no-op given
  strictly-increasing backtest bar times, and `UniverseHandler`/`absorb_warmup` are live-only
  constructs never wired by the backtest composition root.
- **Indentation:** no mixed-indentation was introduced — `base.py` hunks are tab-indented
  (matching the file), `universe_handler.py`/`live_bar_feed.py` hunks are 4-space (matching
  their files).

The remaining findings are all in `absorb_warmup`'s new guard, where the implementation is
narrower than the sibling logic it explicitly claims to mirror, and two minor documentation
staleness points.

## Warnings

### WR-01: `absorb_warmup`'s `==` branch silently swallows a genuine revision, not just a duplicate

**File:** `itrader/price_handler/feed/live_bar_feed.py:343-346`
**Issue:** The new guard treats every `bt == last` bar as a benign duplicate and drops it with
no log:

```python
if bt == last:
    # Duplicate re-delivery (== cursor) — expected/benign overlap on a
    # retry re-warm; drop SILENTLY (no log) so the ring gains no dup.
    continue
```

But the sibling live-path method this guard is explicitly modeled on,
`_duplicate_or_revision` (same file, `:401-421`), does **not** always drop silently on `t == L` —
it builds the incoming `Bar` and compares OHLCV via `_same_ohlcv`: identical values drop at
`debug`, but differing values (a genuine forward-only *revision*, D-07) drop at `warning`. The
inline comment on this commit's guard even mischaracterizes that method as "`==` silent"
unconditionally, which is not accurate.

The gap is not hypothetical: the test added by this same commit,
`tests/unit/price/test_absorb_warmup_idempotency_cr01.py::test_same_timestamp_duplicate_drops_silently`,
builds its "duplicate" bar via `_bar(_START_MS + 2 * _TF_MS)` — i.e. with the default
`close="42100.0"` — while the bar already in the ring at that same timestamp (from
`_warmup_bars(3)`, index 2) carries `close="42102"`. This is a **revision**, not a byte-identical
duplicate, yet the test asserts (and the code delivers) a silent drop with zero warning. A real
venue-side revision arriving during warmup absorption is therefore indistinguishable from a
benign overlap re-fetch — the operator gets no signal that the venue sent conflicting data for an
already-warmed bar.

Functionally this does not corrupt state (the old, already-ringed bar stays canonical either
way, consistent with D-07's "never rewind" contract), so it is not a data-integrity defect — but
it is a real behavior/observability regression relative to the pattern this commit claims to
reuse.

**Fix:**
```python
if bt == last:
    ring = self._ring.get((symbol, timeframe))
    last_bar = ring[-1] if ring else None
    if last_bar is not None and not self._same_ohlcv(last_bar, bar):
        self.logger.warning(
            "Revision dropped for %s at %s during warmup absorb (forward-only, "
            "no state mutation, D-07): last-close=%s incoming-close=%s",
            symbol, str(bt), str(last_bar.close), str(bar.close))
    continue
```
(reusing the existing `_same_ohlcv` static helper already on the class).

### WR-02: `absorb_warmup` has no equivalent to `update()`'s WR-01 off-grid rejection

**File:** `itrader/price_handler/feed/live_bar_feed.py:334-346`
**Issue:** `update()`'s classification tree explicitly rejects an off-grid timestamp — one
strictly between `last` and `last + tf` (see `update()` lines 256-263, "WR-01: ... an off-grid
timestamp ... would set L off the tf-grid and make every subsequent bar spuriously trip the gap
branch"). The new `absorb_warmup` guard only replicates the `<` and `==` legs of the monotonic
contract; it has no `elif` for `last < bt < last + tf`, so such a bar falls straight through to
`ring.append` and unconditionally advances `_last_delivered` to the off-grid value. Per the
documented rationale for the *identical* hazard in `update()`, this would misalign `L` off the
tf-grid and make every subsequent live-path `update()` call for that `(symbol, timeframe)`
spuriously classify as a gap.

Likelihood is low in practice (warmup bars are a bulk REST fetch from the same venue/format as
the live stream, so they are normally on-grid), but the guard is incomplete relative to the
contract it is meant to enforce, and relative to the analogous method in the same class.

**Fix:** Add the same off-grid rejection `absorb_warmup` is missing, mirroring `update()`'s
WR-01 branch (reject with a warning, no ring mutation, no `L` advance) before falling through to
the append path.

## Info

### IN-01: `absorb_warmup` docstring's "the single divergence" claim is now stale

**File:** `itrader/price_handler/feed/live_bar_feed.py:301-304`
**Issue:** The docstring reads: "For each pre-built `Bar` in order it runs the EXACT ring / `L` /
newest-bar logic of `_deliver` ... but DELIBERATELY SKIPS the terminal `_emit` (**the single
divergence**)." After this commit that is no longer accurate — the new `<=` cursor guard (WR-01
and WR-02 above) is a *second* divergence from `_deliver`, which has no monotonic guard of its
own at all (that classification lives in `update()`, one layer up, and is never reached by
`absorb_warmup`). The inline comment on the new guard explains the addition, but the
method-level docstring's "single divergence" framing was not updated to match.

**Fix:** Update the docstring's divergence-count language, e.g. "...now diverges from `_deliver`
in two ways: it never emits, and it applies its own `<=` monotonic cursor guard (CR-01-feed)
before appending."

### IN-02: `_record_rewarm_failure`'s docstring undersells the actual repeat-warn behavior

**File:** `itrader/universe/universe_handler.py:540-556`
**Issue:** The docstring says "At the 3rd consecutive failure a warning surfaces the stuck
symbol + its streak," which reads as a one-time notification. The guard is `if streak >= 3`,
so every consecutive failure at streak 3, 4, 5, ... re-emits the warning (bounded to at most once
per bar interval by the cadence gate in `on_poll`, so not a flood, but not a single notification
either). This is very likely the intended behavior (ongoing visibility for a persistently stuck
symbol) but the docstring wording doesn't match the `>=` semantics.

**Fix:** Reword to "at the 3rd and every subsequent consecutive failure" (or similar) to match
the `>= 3` condition.

---

_Reviewed: 2026-07-07_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_

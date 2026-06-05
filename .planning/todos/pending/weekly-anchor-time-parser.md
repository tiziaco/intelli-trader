---
status: pending
created: "2026-06-05"
source: 03-VERIFICATION.md (WR-01, SC3 disposition)
tags: [time_parser, anchoring, M2-10, deferred]
resolves_phase:
---

# time_parser: correct weekly/DST `check_timeframe` anchoring (+ test)

**Origin:** Phase 03 (M2b) verification, WR-01. Owner accepted the phase with this
deferred (daily-UTC path is correct and is the only timeframe the SMA_MACD golden
dataset exercises).

**Problem:** `_aligned` (`itrader/outils/time_parser.py:127`) anchors to the Unix epoch
via `int(ts.timestamp()) % int(tf.total_seconds()) == 0`. Epoch 1970-01-01 was a
Thursday, so:
- a **weekly** timeframe fires only on Thursday 00:00 UTC (old midnight anchor fired
  on any midnight),
- a **`7h`** (non-day-divisor) timeframe never aligns to midnight.

This contradicts SC3's "anchoring fixed for non-UTC/DST/week-month". The daily 00:00
UTC golden path is byte-identical, so the oracle is unaffected.

**Do:**
1. Decide intended weekly/calendar anchoring semantics (likely midnight-relative or
   exchange-calendar-relative, not epoch-relative) and implement it inside the
   `_aligned` seam — callers should not change.
2. Add `check_timeframe` tests covering weekly and a non-day-divisor timeframe (e.g.
   `7h`), plus a DST-boundary case.
3. Once done, tighten/replace the daily-UTC CAVEAT note in the `_aligned` docstring.

**Notes:** Fits naturally with M5a/M5b timing work (Bar struct, fill realism). Keep the
single-seam discipline (D-06) so the daily oracle stays byte-exact.

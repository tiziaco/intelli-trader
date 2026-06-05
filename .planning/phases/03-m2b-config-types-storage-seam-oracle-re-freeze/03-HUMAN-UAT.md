---
status: resolved
phase: 03-m2b-config-types-storage-seam-oracle-re-freeze
source: [03-VERIFICATION.md, 03-REVIEW.md]
started: "2026-06-05T00:00:00Z"
updated: "2026-06-05T00:00:00Z"
---

## Current Test

[resolved]

## Tests

### 1. Weekly `check_timeframe` epoch-anchor behavior (SC3 disposition)
expected: `check_timeframe` weekly-firing behavior is either (a) confirmed-intended as epoch-anchored (fires on Thursdays), with SC3 "anchoring fixed for...week" accepted as fully met, OR (b) flagged for a docstring note + follow-up to add a weekly test / restore midnight-relative weekly firing.
result: passed — owner chose accept + note + follow-up (2026-06-05). `_aligned` docstring now qualifies the behavioral-oracle claim as daily-UTC-only and documents the weekly epoch-Thursday caveat; follow-up filed at `.planning/todos/pending/weekly-anchor-time-parser.md`. Daily golden oracle is byte-exact and unaffected; weekly anchoring is outside the SMA_MACD golden path.

Detail: `_aligned` at `itrader/outils/time_parser.py:127` uses `int(ts.timestamp()) % int(tf.total_seconds()) == 0`. For daily 00:00 UTC bars this matches the old midnight anchor exactly (golden oracle safe). For weekly timeframes it fires only on Thursdays (epoch 1970-01-01 was a Thursday), whereas the old anchor fired on any midnight. The `to_timedelta` week-support (`1W`/`1w` → `timedelta(weeks=1)`) is unambiguously delivered; only the weekly `check_timeframe` firing change is undocumented. No weekly `check_timeframe` test exists and the docstring asserts "behavioral oracle is unchanged" without the daily-UTC qualifier.

## Summary

total: 1
passed: 1
issues: 0
pending: 0
skipped: 0
blocked: 0

## Gaps

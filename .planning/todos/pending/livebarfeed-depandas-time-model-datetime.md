---
status: deferred
created: "2026-07-07"
source: Phase 07 CR-01 design discussion (tiziaco, 2026-07-07) — scoped OUT of the 07-10 gap-closure
tags: [live, feed, price_handler, pandas, datetime, time-model, refactor, tech-debt, next-milestone, bar-timing-contract]
milestone_target: "next (post-v1.7)"
---

# De-pandas-ify LiveBarFeed's time model (pd.Timestamp → stdlib datetime)

**Origin:** Phase 07 CR-01 design discussion (2026-07-07). While designing the CR-01 fix
(unified monotonic idempotency, Option B), we decided the NEW strategy-layer cursor uses stdlib
`datetime` (no pandas creep), but the FEED cursor stays `pd.Timestamp` for that fix because the
feed's entire time model is pandas-native. Fully migrating the feed off `pd.Timestamp` is a large,
look-ahead-safety-critical refactor — deferred to the next milestone as its own deliberate piece of
work, NOT folded into the money-path CR-01 fix.

## Why the feed is pandas-native today

`Bar.time` is declared `datetime` (`core/bar.py:45`), but inside
`itrader/price_handler/feed/live_bar_feed.py` time is modelled entirely as `pd.Timestamp` /
`pd.Timedelta`:

- Live timestamp built from epoch ms: `t = pd.Timestamp(closed_bar["ts"], unit="ms", tz="UTC")` (`:213`).
- `_last_delivered: dict[tuple[str, str], pd.Timestamp]` (`:100`); the monotonic-guard cursor.
- L-grid arithmetic is Timestamp/Timedelta: `t == L`, `t < L`, `t > L + tf`, `L + tf`, with
  `tf = to_timedelta(...)` (a `pd.Timedelta`).
- REST-backfill range math extracts epoch ms via the pandas-only `.value // _NS_PER_MS` at ~5 sites
  (`:249-250`, `:452-453`, `:505`, `:533-534`).
- **Structural blocker:** the `window()` read-model is a pandas DataFrame with a tz-aware
  `DatetimeIndex`, queried via `resampled.index.searchsorted(pd.Timestamp(cutoff), ...)` (`:654`) and
  it requires tz-aware input (`:650`). The ring feeds that index.

## Scope of the migration (if taken on)

A correct migration must address ALL of the above together, not just `_last_delivered`:
1. Replace `pd.Timestamp` `t` construction + L-grid arithmetic with tz-aware stdlib `datetime` +
   `datetime.timedelta` (or an explicit epoch-ms integer grid).
2. Replace every `.value // _NS_PER_MS` epoch extraction with `int(dt.timestamp() * 1000)` (or carry
   an epoch-ms int alongside).
3. Decide the ring/`window()` read-model: the pandas `DatetimeIndex` is the hard part — either keep a
   pandas index at the read boundary (converting datetime→Timestamp only there) or redesign the
   window read-model. This decision gates whether "datetime everywhere in the feed" is even desirable.
4. Preserve the bar-timing contract and re-run the look-ahead-safety tests + the byte-exact backtest
   oracle (the live feed must stay inert on the backtest path).

## Why deferred

Out of scope for the CR-01 money-path fix; large blast radius across the look-ahead-safety-critical
feed; partial migration (cursor only) would be strictly worse (type inconsistency + conversion
friction). Do it deliberately in the next milestone, or explicitly decide the pandas ring makes a full
migration undesirable and close this as won't-fix. See [[warmup-retry-nonidempotent-tradeable-corrupted-cr01]].

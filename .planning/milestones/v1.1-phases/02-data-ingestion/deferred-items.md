# Phase 02 Data Ingestion — Deferred Items

Items surfaced during execution that a FUTURE phase must address. Not blocking
the current plan's definition of done.

## Known-unreliable volume on SOLUSD / AAVEUSD zero-volume dates

**Source:** Plan 02-01, Task 2 (D-06 volume-check decision, Option 1).

The provider data for SOLUSD (11 dates) and AAVEUSD (35 dates) contains bars with
`Volume == 0`, which we deliberately accept (D-06 relaxed from strictly-positive to
non-negative). These are NOT genuine no-trade days — the OHLC on those dates shows
real intraday movement (e.g. SOLUSD `2024-08-27` open 157.15 / high 159.69 /
low 145.14 / close 146.85, ~9% range), so `volume == 0` is a provider
**missing-data sentinel**, not a true zero. The OHLC prices are real and internally
consistent and are the only field the v1.1 run path consumes (volume is inert on the
run path: strategy/execution/slippage/fee/sizing read no input bar volume).

**Action required for any future volume-using scenario on SOL/AAVE:** treat these
specific dates as suspect and re-verify the volume against an independent source
before freezing — consistent with the hand-verify-once-then-freeze discipline. The
OHLC on those dates is trustworthy; only the `Volume` field on those dates is not.

Counts: ETHUSD 0 / SOLUSD 11 / AAVEUSD 35 / BTCUSD golden 0.

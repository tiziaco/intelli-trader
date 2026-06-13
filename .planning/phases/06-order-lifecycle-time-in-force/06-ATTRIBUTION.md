# Phase 6 — Run-End EXPIRED Re-baseline Attribution (LIFE-01, D-04/D-05/D-11)

**Measured:** 2026-06-13
**Plan:** 06-04 (Task 1 — measure + attribute; owner-gated)
**Posture:** Owner-gated re-baseline. The result change is confined to order STATUS
(`PENDING` → `EXPIRED`); the SMA_MACD oracle stays byte-exact (equity-neutral, D-04).

This report measures and attributes the result change introduced by the Plan 03 run-end
EXPIRE wiring, ahead of the blocking owner sign-off (Plan 06-04 Task 2). **No golden is
frozen by this report** — the `--freeze` of the 3 affected leaves happens ONLY after
explicit owner approval (Task 3).

---

## (a) SMA_MACD Oracle — Byte-Exact Confirmation (D-04)

The integration oracle is **byte-exact** after the Plan 03 wiring — zero drift:

| Quantity | Frozen oracle value | Post-wiring value | Delta |
|----------|--------------------|--------------------|-------|
| `trade_count` | **134** | 134 | 0 (byte-exact) |
| `final_equity` | **46189.87730727451** | 46189.87730727451 | 0.0 (byte-exact) |
| `final_cash` | 46189.87730727451 | 46189.87730727451 | 0.0 (byte-exact) |
| `total_realised_pnl` | 36189.87730727451 | 36189.87730727451 | 0.0 (byte-exact) |

`make test-integration` → **16 passed, 0 failed** (incl. `test_oracle_behavioral_identity`,
`test_oracle_numeric_values` pinning `trade_count=134`, and `test_trade_log_identical_to_golden`).
The frozen oracle golden (`tests/golden/summary.json`) was NOT re-frozen and was NOT touched.

**Why this is byte-exact (D-04 equity-neutrality proof, RESEARCH §Summary/§Runtime State
Inventory):** `total_equity = total_market_value + cash`, and `cash` reads the FULL ledger
balance (`cash_manager.balance`), NEVER `available_balance`. `release()` only pops a
reservation (`_storage.pop_reservation`) and leaves `_balance` untouched. Reservations move
`available_cash` only — a figure `total_equity` never reads and the metric snapshots never
record. Expiring resting orders and releasing their reservations therefore CANNOT move
`final_equity` or `trade_count`. An expired never-filled entry is not a trade; expiring SL/TP
brackets on an open position moves neither cash nor the marked position. The status change
(`PENDING` → `EXPIRED`) is **oracle-dark** — the oracle asserts trades + equity, not order
statuses.

---

## (b) Per-Leaf Disposition Delta — The Exactly-3 Blast Radius (D-11)

A full `make test` run: **3 failed, 992 passed**. The 3 failures are EXACTLY the 3 target
e2e leaves, each diffing on `golden/orders.csv` status `PENDING` → `EXPIRED` (fresh side
shows `EXPIRED`, committed golden still shows `PENDING`). All other 55 e2e leaves stayed
green unchanged. An independent grep confirms ONLY these 3 golden `orders.csv` files carry a
`,PENDING,` row; every other golden `orders.csv` is all-terminal (FILLED / CANCELLED /
REJECTED) and is status-blind to the sweep.

| Leaf | Order(s) flipping `PENDING`→`EXPIRED` | Why it now expires |
|------|---------------------------------------|--------------------|
| `tests/e2e/matching/never_fill` | 1 × STANDALONE BTCUSD **LIMIT BUY** @ 80.0, qty 118.75 (the D-05 positive-proof leaf) | A far-below-market standalone buy-limit that provably never fills — it rests for the whole run and is honestly retired EXPIRED at run end. No position, no cash movement. |
| `tests/e2e/sltp/from_decision_held` | 2 × bracket: **SL** (STOP SELL @ 90.0) + **TP** (LIMIT SELL @ 120.0), qty 95 each, on a FILLED MARKET-BUY ENTRY @ 100.0 | The MARKET-BUY ENTRY filled (FILLED, position open); its SL+TP protective brackets never triggered (price stayed between them). At run end there are no more bars, so the brackets can never fire → EXPIRED. The position **stays open** and is marked-to-last-close (D-02). |
| `tests/e2e/sltp/from_fill_held` | 2 × bracket: **SL** (STOP SELL @ 81.0) + **TP** (LIMIT SELL @ 108.0), qty 95 each, on a FILLED MARKET-BUY ENTRY @ 100.0 | Same as `from_decision_held`: a still-open MARKET-BUY position whose SL+TP brackets never triggered → EXPIRED at run end. Position stays open, marked-to-last-close (D-02). |

In every case the ENTRY/standalone order's economic outcome is unchanged — only the terminal
STATUS of the resting order moves from the (now-false) lingering `PENDING` to the honest
terminal `EXPIRED`. This is the COMPLETE D-11 blast radius confirmed against the live run.

---

## (c) Equity-Neutrality Confirmation (D-04)

**No cash / equity / trade figure moved.** Evidence:

- The SMA_MACD oracle is byte-exact (section (a)): `trade_count=134`, `final_equity=46189.87730727451`.
- `test_reservation_inertness` (integration) PASSED: `reserved_balance == 0` after the run,
  reserve never rejects in the golden run, and the trade log is identical to the golden.
- `test_run_end_sweep_then_drain_does_not_cascade` (integration) PASSED: the post-sweep final
  drain emits NO new SIGNAL and NO new ORDER (provably non-cascading, D-08) — so the sweep
  cannot indirectly create or close a position.
- The 3 affected leaves' OTHER goldens are unchanged: only the `orders.csv` status column
  diffs. Their `trades.csv` / `summary.json` / equity goldens are byte-identical (the suite
  reports a diff ONLY on the orders.csv status, and the other artifacts in those leaves did
  not fail). The held positions in the two `sltp/*_held` leaves stay open and are
  marked-to-last-close exactly as before — cash and marked position value are untouched.

The result change is **purely a status correction** (lingering `PENDING` → honest terminal
`EXPIRED`), with zero movement in any money or trade figure.

---

## (d) Determinism + mypy Status (D-06)

- **Determinism:** `make test-integration` PASSED including the reservation-inertness and
  oracle identity gates; the run path is single-threaded and deterministic (seeded RNG 42,
  injected clock), and the sweep iterates portfolios in `get_active_portfolios()` order then
  orders sorted by `order_id` (UUIDv7, monotonic — stable, D-10). Double-run byte-identical.
- **mypy --strict:** `poetry run mypy itrader` → **Success: no issues found in 182 source
  files.** Clean.

---

## Verdict (pending owner sign-off)

The result change is fully measured and attributed: the SMA_MACD oracle is byte-exact
(equity-neutral, D-04), determinism + mypy gates hold (D-06), and EXACTLY the 3 named e2e
leaves (`matching/never_fill`, `sltp/from_decision_held`, `sltp/from_fill_held`) are affected,
each disposition change attributed to a resting order that can never fill (D-11). Ready for
the blocking OWNER SIGN-OFF (Plan 06-04 Task 2) that authorizes the `--freeze` of the 3
re-baselined goldens (Task 3).

**No golden has been frozen by this report.**

---

## Owner Sign-Off

> _Pending — Task 2 blocking owner-gate. The owner-approval block (owner handle + date +
> byte-exact-oracle attribution acknowledgment) is appended here in Task 3 after explicit
> "approved"._

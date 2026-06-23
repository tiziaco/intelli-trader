---
status: diagnosed
trigger: "Spot LONG_ONLY portfolio allows over-selling beyond holdings → net-short inventory mislabeled side=LONG with positive market_value → phantom equity ($100k → $10M)"
created: 2026-06-23
updated: 2026-06-23
goal: find_root_cause_only
---

# Debug Session: spot-long-only-oversell

## Symptoms

**Expected behavior:**
In a SPOT, LONG_ONLY portfolio (no margin, no short-selling enabled), a market SELL
exit should be sized to / clamped by the held position quantity — you cannot sell
more than you own. Selling exactly the holdings flattens the position
(net_quantity → 0) and frees the max_positions slot. Equity stays in the same
order of magnitude as the cash deposited (a $100k spot account cannot become $10M
from BTC price moves over 6 months).

**Actual behavior:**
A market SELL emitted by a LONG_ONLY strategy is sized off the sizing policy
(`FractionOfCash(Decimal("0.95"))` — i.e. 0.95 × CASH), NOT clamped to the held
position quantity. The portfolio repeatedly sells more than it holds. The position
drifts net-short but is still labelled `side=LONG` with a POSITIVE market_value,
and cash is credited from the oversized sells, producing phantom equity.

Final stuck open position (BTCUSDT, from diag_A_pos.py):
- side = LONG
- buy_quantity  = 1.05
- sell_quantity = 65.11
- net_quantity  = 64.06   (computed as abs(buy_quantity - sell_quantity))
- avg_price     = 89,591   current_price = 64,422
- market_value  = +$4,127,043  (booked POSITIVE, long-style)
- portfolio cash $100,000 → $5,881,263 ; equity ≈ $10,008,306

December alone: 62 BUY fills vs 98 SELL fills — the engine accepted ~36 more sells
than it had inventory for, in the first month. After the position gets stuck
net-short, net_quantity never returns to 0, max_positions=1 blocks all re-entry,
and fills freeze.

**Error messages:** None — no exception. Silent accounting corruption (this is
the dangerous part: fail-fast did NOT trip).

**Timeline:** Surfaced 2026-06-23 while analysing perf coverage instrument A in the
W1 benchmark. The over-sell is the root cause of A freezing after January.

**Reproduction (deterministic, isolated — NO margin/short flags set):**
- Strategy: perf coverage instrument A in its PRE-FIX form. Pre-fix source:
  `git show fa250c0:perf/strategies/a_bracketed_momentum.py` — it had a discretionary
  `if crossunder(macd_hist, 0): return self.sell(ticker)` exit. (That branch was
  removed in commit 3657d30 to stop the perf benchmark bleeding; it is the cleanest
  trigger for THIS engine bug, not the bug itself.)
- Config: `sizing_policy = FractionOfCash(Decimal("0.95"))`, `direction = LONG_ONLY`,
  `max_positions = 1`, single $100k portfolio, BTCUSDT only,
  `exchange="csv"`, start_date=2025-12-24, end_date=2026-06-23.
- Reusable A-only single-strategy/single-portfolio scaffolding in scratchpad:
  `/private/tmp/claude-501/-Users-tizianoiacovelli-Desktop-projects-intelli-trader/66004239-46a9-4a1d-b489-2fb451838f38/scratchpad/diag_A_full.py`
  and `.../diag_A_pos.py`.
- Minimal alternative repro: a LONG_ONLY spot strategy with FractionOfCash(0.95)
  sizing that opens a small long, then repeatedly emits `self.sell(ticker)` (a
  market SELL sized off cash) and observe the position go net-short while
  side=LONG with positive market_value. A fast deterministic unit-level repro
  (open 1 unit, then sell 5) is preferable to the multi-minute full backtest.

## Suspected fault areas (investigate; do not assume)

1. **Exit/sell sizing.** A LONG_ONLY market SELL is sized off `FractionOfCash(0.95)`
   of CASH rather than clamped to held quantity. `exit_fraction` defaults to
   Decimal("1") on `Strategy.sell()` and does NOT re-size to the position. Where is
   sell/exit sizing decided? (itrader/order_handler/order_manager + sizing +
   admission). Is sizing an exit off cash the intended contract, or should an exit
   be position-relative?
2. **Admission / direction gate.** The LONG_ONLY direction gate and/or spot
   admission does NOT reject or clamp a SELL exceeding current holdings. In spot you
   cannot sell what you don't own. Should admission reject/clamp the over-sell?
   (Confirmed the over-sell happens even with NO system-wide short/margin flags set.)
3. **Position accounting sign/labeling.** `net_quantity = abs(buy_quantity -
   sell_quantity)` discards the sign; `market_value` is booked POSITIVE for an
   inventory where sell_quantity >> buy_quantity (economically net-short) while
   `side` stays LONG → phantom positive equity. Sign/labeling bug?
   (itrader/portfolio_handler/position/position.py — market_value, net_quantity,
   avg_price, total_market_value/total_equity.)

## CRITICAL CONSTRAINT — oracle gate

This is the CORE engine (itrader/order_handler, itrader/portfolio_handler/position,
sizing/admission), governed by the project's milestone ORACLE GATE: the SMA_MACD
spot oracle must stay byte-exact at **134 trades / final_equity 46189.87730727451**
(`tests/integration/test_backtest_oracle.py`). This session's GOAL is
**root-cause diagnosis + a proposed oracle-safe fix path ONLY** — do NOT apply an
engine accounting change here. Any eventual fix must be re-validated against that
oracle + `tests/e2e` + full suite and is an owner-gated, result-changing decision.
Money policy: Decimal end-to-end, never `Decimal(float)`. Indentation: core handler
modules use TABS, perf/ uses 4 spaces — match the file.

## Current Focus

- hypothesis: CONFIRMED — root cause is the SPOT settlement path having NO
  over-close guard (the guard exists only on the margin path), combined with
  Position.side being immutable-at-open and net_quantity=abs(buy-sell). The first
  oversell is seeded by a SECOND, unguarded exit channel: resting OCO bracket
  children (SL/TP) that survive a discretionary market SELL and fill later,
  bypassing admission entirely.
- next_action: (diagnosis complete) — return ROOT CAUSE FOUND with oracle-safe
  fix path. Do NOT apply an engine accounting change in this session.

## Evidence

- timestamp: 2026-06-23
  checked: itrader/portfolio_handler/position/position.py:90-93,117-127,229
  found: Position.side is set ONCE in open_position() (LONG if BUY else SHORT,
    :229) and is NEVER mutated thereafter. net_quantity = abs(buy_quantity -
    sell_quantity) (:127) — unsigned magnitude, sign discarded. market_value
    (:90-93) dispatches on self.side: side==LONG → +current_price*abs(net_quantity).
  implication: Once a LONG position has sell_quantity > buy_quantity (economically
    net-short), it STILL reports side=LONG, net_quantity>0, market_value>0 → phantom
    positive equity. Confirms suspect area 3 (sign/labeling bug).

- timestamp: 2026-06-23
  checked: itrader/portfolio_handler/position/position_manager.py:201-205,223-234
  found: _should_close_position closes only when abs(net_quantity) <= tolerance.
    Because net_quantity=abs(buy-sell), an over-sell (sell>buy) yields a POSITIVE
    magnitude that never hits tolerance → position never closes, slot never frees.
    _validate_position_consistency (:228) guards `net_quantity < 0` — STRUCTURALLY
    DEAD, since net_quantity is abs() and can never be negative.
  implication: No accounting-side guard catches the over-sell; the "Long position
    cannot have negative net quantity" check can never fire.

- timestamp: 2026-06-23
  checked: itrader/portfolio_handler/portfolio.py:308-338 (_process_transaction_spot)
    vs :340-404 (_process_transaction_margin)
  found: The CR-02 over-close/flip guard (`if not is_increase and
    transaction.quantity > prior_qty: raise InvalidTransactionError`) lives ONLY in
    the MARGIN path (:399-404). The SPOT path (_process_transaction_spot) calls
    position.update_position(transaction) UNCONDITIONALLY — no over-close guard, no
    held-quantity clamp. update_position on a SELL does sell_quantity += qty
    (position.py:261) with no bound.
  implication: THE STRUCTURAL ROOT CAUSE. In spot mode an over-sized SELL fill
    settles silently — no exception, no clamp. This is why fail-fast did NOT trip.

- timestamp: 2026-06-23
  checked: itrader/order_handler/admission/admission_manager.py:474-547
    (_enforce_direction_admission), :768-890 (_resolve_signal_quantity),
    :853-869 (is_reduction + resolve_exit)
  found: For a SIGNAL-routed SELL the admission gate passes only when an open LONG
    exists, and the exit is sized via resolve_exit(abs(net_quantity), exit_fraction)
    → CLAMPED to net_quantity, NOT to cash. So suspect area 1 (exit sized off cash)
    is FALSE for the signal path, and suspect area 2 (admission lets a signal SELL
    exceed holdings) is FALSE in isolation. BUT the clamp uses the CORRUPTED
    net_quantity magnitude (repro_admission_clamp.py: side=LONG, buy=1, sell=5 →
    net_quantity=4 → resolve_exit returns 4), so each subsequent signal exit sells
    `abs(buy-sell)` MORE and GROWS the net-short magnitude (runaway feedback).
  implication: The signal exit clamp is correct in intent but is poisoned by the
    accounting corruption. The corruption must be SEEDED by a non-signal channel.

- timestamp: 2026-06-23
  checked: git show fa250c0:perf/strategies/a_bracketed_momentum.py (pre-fix A)
  found: Strategy A opens with a BRACKET — self.buy(ticker, sl=, tp=) → an OCO
    bracket (resting SL stop child + resting TP limit child) — AND has a
    discretionary market exit self.sell(ticker) on crossunder. Two independent exit
    channels for ONE position.
  implication: The discretionary market SELL flattens/closes the position, but the
    resting SL/TP bracket children are NOT part of that order's OCO and are NOT
    cancelled by it. They remain live in the matching engine.

- timestamp: 2026-06-23
  checked: itrader/execution_handler/matching_engine.py:418-441 (OCO cancels),
    itrader/order_handler/reconcile/reconcile_manager.py:179-... (on_fill mirror)
  found: OCO only cancels the SIBLING within the SAME bracket when one of them
    fills (matching_engine.py:438-441). A resting bracket child that fills routes
    matching_engine → FillEvent → Portfolio.process_transaction DIRECTLY,
    BYPASSING admission (no direction gate, no resolve_exit clamp). reconcile.on_fill
    only reconciles the order MIRROR; it does not cancel a resting bracket when a
    SEPARATE discretionary market SELL flattens the position.
  implication: SEED MECHANISM — after a discretionary SELL flattens the long, the
    orphaned resting SL/TP child fires later as a SELL fill with no held inventory,
    settles through the unguarded spot path, and pushes sell_quantity past
    buy_quantity. From there the side=LONG / net_quantity=abs() / resolve_exit-on-
    corrupted-magnitude feedback loop runs away to the $10M cash cap.

- timestamp: 2026-06-23
  checked: repro_oversell.py (scratchpad) via PYTHONPATH="$PWD" poetry run python
  found: Open BUY 1 @ 89591 → side=LONG, net_quantity=1, market_value=89591,
    cash=10409. Then SELL 5 @ 89591 settles WITH NO EXCEPTION → side=LONG,
    buy_quantity=1, sell_quantity=5, net_quantity=4, market_value=+358364,
    cash=458364, n_open_positions=1. Mark price→64422: market_value still +257688.
  implication: Direct empirical confirmation of silent spot over-sell + phantom
    positive market_value + cash credited from the oversized sell. Matches the
    reported stuck-position numbers exactly.

- timestamp: 2026-06-23
  checked: itrader/portfolio_handler/cash/cash_manager.py:91-92
  found: max_balance = Decimal('10000000.00') (the $10M ceiling the symptom hit).
  implication: The runaway credit grows cash toward $10M until a deposit/credit
    would breach max_balance; explains the ~$10M equity plateau.

## Eliminated

- hypothesis: Suspect area 1 — a LONG_ONLY market SELL is sized off
    FractionOfCash(0.95) of CASH rather than the held quantity (exit sized off cash).
  evidence: admission_manager.py:853-869 routes a SELL-vs-open-LONG through
    is_reduction → resolve_exit(abs(net_quantity), exit_fraction), which clamps to
    net_quantity. resolve_entry (cash sizing) is reached only for a SELL with NO
    open long — which the direction gate (:523-534) rejects for LONG_ONLY. So a
    SIGNAL SELL is position-relative, not cash-relative. The cash-sizing framing in
    the symptom is the OBSERVED EFFECT (the exit clamps to a corrupted, inflated
    net_quantity), not the mechanism.
  timestamp: 2026-06-23

- hypothesis: Suspect area 2 (in isolation) — the admission/direction gate fails to
    reject/clamp a SIGNAL SELL exceeding holdings.
  evidence: For SIGNAL-routed SELLs the gate + resolve_exit DO clamp to
    net_quantity (admission_manager.py). The gate is not the leak for signal orders.
    The actual unguarded over-sell enters via RESTING BRACKET FILLS that bypass
    admission entirely (matching_engine → FillEvent → Portfolio), and via the
    SPOT settlement path lacking the over-close guard. So "admission" is only
    partially in play: the real missing guard is at SETTLEMENT (spot path), not
    admission. Suspect 2 is REFRAMED, not a standalone cause.
  timestamp: 2026-06-23

## Resolution

root_cause: |
  A SPOT position can be over-sold silently because the over-close/flip guard
  (CR-02) exists ONLY on the margin settlement path
  (itrader/portfolio_handler/portfolio.py:399-404 in _process_transaction_margin)
  and is ABSENT from the spot path (_process_transaction_spot, portfolio.py:308-338).
  The spot path applies any SELL fill unconditionally
  (position.update_position → sell_quantity += qty, position/position.py:259-262).

  Two compounding structural defects turn that gap into runaway phantom equity:

  1. POSITION SIGN/LABELING (position/position.py:90-93,117-127,229):
     Position.side is fixed at open and never flips; net_quantity = abs(buy-sell)
     discards the sign; market_value dispatches on the (stale LONG) side and is
     always positive. An economically net-short inventory is reported side=LONG with
     net_quantity>0 and market_value>0. _should_close_position
     (position_manager.py:205) never closes it (abs magnitude never reaches
     tolerance) and the `net_quantity < 0` consistency guard
     (position_manager.py:228) is structurally dead (net_quantity is abs()).

  2. UNGUARDED RESTING-BRACKET EXIT CHANNEL (the SEED):
     A bracketed LONG_ONLY strategy (pre-fix perf instrument A,
     git show fa250c0:perf/strategies/a_bracketed_momentum.py) has TWO exit
     channels — a resting OCO bracket (SL stop + TP limit children) AND a
     discretionary market self.sell(). The discretionary SELL flattens/closes the
     long but does NOT cancel the resting bracket children (OCO only cancels a
     bracket's own sibling, matching_engine.py:438-441; reconcile.on_fill only
     reconciles the order mirror). The orphaned resting child fires later as a SELL
     fill, routes matching_engine → FillEvent → Portfolio.process_transaction
     DIRECTLY (bypassing the admission direction gate + resolve_exit clamp), and
     settles through the unguarded spot path — pushing sell_quantity past
     buy_quantity. Thereafter every SIGNAL exit sizes resolve_exit(abs(net_quantity))
     against the corrupted magnitude, selling MORE each cycle (runaway) until cash
     hits CashManager.max_balance = $10M (cash_manager.py:91-92).

  The signal-path exit sizing (resolve_exit clamp) and direction gate are CORRECT
  in intent; they are poisoned by the corrupted net_quantity. The primary missing
  guard is at SPOT SETTLEMENT (no over-close clamp/reject), with the immutable
  side + abs(net_quantity) accounting making the corruption silent and the orphaned
  resting-bracket fill providing the seed.

fix: |
  (PROPOSED — NOT APPLIED; owner-gated, result-changing, oracle-revalidation required)

  Layered, each independently oracle-relevant:

  A. SETTLEMENT GUARD (primary, smallest) — port the CR-02 over-close guard into
     the SPOT path (_process_transaction_spot): a reducing SELL whose quantity
     exceeds prior held quantity raises InvalidTransactionError (fail-fast) BEFORE
     mutation, exactly as the margin path already does (portfolio.py:399-404). This
     converts silent corruption into a loud abort. ORACLE RISK: the SMA_MACD spot
     oracle (134 trades / 46189.87730727451) uses NON-bracketed exits sized to
     net_quantity (exit_fraction=1, resolve_exit no-op) — it should NEVER over-sell,
     so the guard should be oracle-DARK (never trips on the golden path). MUST be
     verified by running tests/integration/test_backtest_oracle.py — if it stays
     134/46189.87730727451 the guard is oracle-safe.

  B. ORPHANED-BRACKET CANCEL (seed fix) — when a position is flattened/closed by any
     fill (including a discretionary market exit), cancel that ticker's resting
     bracket children. This removes the seed entirely. ORACLE RISK: the golden
     SMA_MACD strategy declares no brackets, so this path is oracle-dark; still
     re-validate.

  C. POSITION SIGN/LABELING HARDENING (defense-in-depth) — make net_quantity
     sign-aware (or add an explicit invariant that side+magnitude cannot represent a
     net-short while labelled LONG), so market_value/equity cannot go phantom-positive
     even if an over-sell slips through. HIGHER ORACLE RISK: touching market_value /
     net_quantity / avg_price is the most likely to drift the byte-exact oracle and
     must be treated as the owner-gated, result-changing change. Prefer A+B (which
     prevent the corrupted state from ever existing) over C for the oracle-safe path.

  RECOMMENDED ORACLE-SAFE PATH: A (settlement guard) + B (orphaned-bracket cancel).
  Both are expected oracle-dark for SMA_MACD (no brackets, no over-sell), so they
  should keep 134/46189.87730727451 byte-exact while making the over-sell impossible
  and loud. C is a deeper accounting change to hold for a separate owner-gated
  decision if net-short support is ever required. ALL must be re-validated against
  tests/integration/test_backtest_oracle.py + tests/e2e + full suite.

verification: |
  (root-cause-only session — fix NOT applied)
  Mechanism confirmed by two deterministic scratchpad repros run via
  PYTHONPATH="$PWD" poetry run python:
  - repro_oversell.py: spot BUY 1 then SELL 5 settles with no exception →
    side=LONG, buy=1, sell=5, net_quantity=4, market_value=+358364, cash credited.
  - repro_admission_clamp.py: resolve_exit(abs(net_quantity=4)) → 4, proving the
    signal exit clamp re-grows the corrupted magnitude (runaway).

files_changed: []

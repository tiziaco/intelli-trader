# Phase 3 — Single-Funnel `realised_pnl` Invariant Audit (D-02)

**Produced:** 2026-06-24 (Task 1, Plan 03-01)
**Status:** LOCKED — establishes, in writing, the single code path through which a
`Position`'s `realised_pnl` changes, so the Phase 3 running accumulator (D-01) can be fed
from that one path and proven byte-identical (D-05).

**No production code changed in this task — audit document only.**

---

## Locked Invariant (one sentence)

> The running realised-PnL accumulator is correct iff it is fed the realised delta
> (`position.realised_pnl - prior_realised`) on **every reducing fill** through **both**
> `Portfolio` settle arms (`_process_transaction_spot` and `_process_transaction_margin`),
> and on **no other path** — because a `Position`'s `realised_pnl` is a pure computed
> property that changes *only* when `Position.update_position` mutates the buy/sell quantity,
> average, or commission fields, which is reached *only* via
> `PositionManager.process_position_update`, which is reached *only* from those two settle arms.

---

## 1. `realised_pnl` is a computed property over mutation-gated backing fields

`Position.realised_pnl` (`itrader/portfolio_handler/position/position.py:175`) is a
`@property` — it stores nothing. It is derived purely from:

| Backing field | Used in `realised_pnl` |
|---------------|------------------------|
| `side` | branch (LONG / SHORT / flat) |
| `avg_bought`, `avg_sold` | `(avg_sold - avg_bought) * qty` |
| `buy_quantity`, `sell_quantity` | the closed quantity + the commission proportion |
| `buy_commission`, `sell_commission` | the commission deductions |

Therefore `realised_pnl` changes **iff** one of those backing fields changes.

**Where those backing fields are mutated** (grep-enumerated over `itrader/`):

- `Position.open_position` (`position.py:221`) — classmethod factory; sets the fields at
  construction (OPEN). On a brand-new LONG, `sell_quantity == 0` → `realised_pnl == Decimal("0")`
  (SHORT symmetric with `buy_quantity == 0`). **Opening a position contributes `0` realised.**
- `Position.update_position` (`position.py:250`) — the **only** post-construction mutator of
  `avg_bought`/`avg_sold`/`buy_quantity`/`sell_quantity`/`buy_commission`/`sell_commission`.
- `Position.close_position` (`position.py:265`) — sets **only** `is_open`, `exit_date`,
  `current_price`. It does **NOT** touch any `realised_pnl` backing field, so it does **not**
  change `realised_pnl` (the realised value is already final once the closing fill ran through
  `update_position`).

**Every other reference to these fields is read-only** (grep `avg_bought|avg_sold|buy_quantity|
sell_quantity|buy_commission|sell_commission|realised_pnl` across `itrader/`):
`portfolio_handler/validators.py` (validation params), `reporting/frames.py` /
`reporting/summary.py` (serialization), `metrics/metrics_manager.py:521` (reads
`portfolio.total_realised_pnl`), `position_manager.py` (re-sum getter), `portfolio.py`
(reads `prior.realised_pnl`). None mutate.

**Conclusion (1):** `realised_pnl` changes only through `Position.update_position`
(`close_position` is realised-PnL-inert; `open_position` contributes `0`).

## 2. `update_position` / `close_position` are reached only via `process_position_update`

`PositionManager.process_position_update` (`position_manager.py:95`) is the **single per-fill
entry**. It dispatches:

- `_create_new_position` (`position_manager.py:117`) → `Position.open_position` (realised `0`).
- `_update_existing_position` (`position_manager.py:155`) → `position.update_position(transaction)`
  (`position_manager.py:180`), then conditionally `_close_position` (`position_manager.py:207`)
  → `position.close_position(...)` (realised-PnL-inert).

Grep confirms `update_position(` and `close_position(` are invoked **only** from
`position_manager.py` (lines 180 and 210 respectively); no test-bypass or other handler calls
them on the run path. `process_position_update` is the single funnel into `update_position`.

**Conclusion (2):** the realised-PnL-changing mutator (`update_position`) is reached **only**
through `PositionManager.process_position_update`.

## 3. `process_position_update` is reached from EXACTLY the two `Portfolio` settle arms

Grep `process_position_update(` across `itrader/` (excluding its own `def`):

- `portfolio.py:361` — inside `_process_transaction_spot`
- `portfolio.py:460` — inside `_process_transaction_margin`

`process_transaction` (`portfolio.py:270`) is the single settle entry; it branches on
`config.trading_rules.enable_margin` to exactly one of those two arms (`portfolio.py:303-306`).
There is no third caller.

**Conclusion (3):** `process_position_update` is reached from **exactly** the two settle arms
`_process_transaction_spot` and `_process_transaction_margin`.

## 4. OPEN / SCALE-IN paths do NOT change `realised_pnl` — only reducing fills do

Both settle arms classify the fill as `is_increase` (a fill moving in the position's own
side — `portfolio.py:331-337` spot, `portfolio.py:419-425` margin):

- **OPEN (no prior position):** `_create_new_position` → `open_position` → on a fresh position
  the opposite-side quantity is `0`, so `realised_pnl == Decimal("0")`. Increment = `0`.
- **SCALE-IN (same-side add):** `update_position` adds to the *own-side* quantity/avg/commission
  only; the opposite-side quantities are unchanged, so the `realised_pnl` formula (which keys
  off the *closing* side's quantity) yields the same value. Increment = `0`.
- **PARTIAL / FULL CLOSE (opposite-side reduce):** `update_position` advances the closing-side
  `sell_quantity`/`avg_sold` (LONG) or `buy_quantity`/`avg_bought` (SHORT), so `realised_pnl`
  advances. **This is the only fill class that changes `realised_pnl`.**

**Conclusion (4):** `realised_pnl` advances **only** on a reducing (closing) fill; OPEN and
SCALE-IN contribute exactly `Decimal("0")`.

---

## 5. CRITICAL — spot-vs-margin two-arm reconciliation (drives Task 2 wiring)

D-02 and the Pattern Map (03-PATTERNS.md) anchor only the **margin** arm's explicit
`realised_increment` variable: `portfolio.py:529` —
`realised_increment = position.realised_pnl - prior_realised`, with `prior_realised` captured
**pre-mutation** at `portfolio.py:406`. The margin arm computes this delta **only in the CLOSE
branch** (the `else:` of `is_increase`, `portfolio.py:488`).

**The spot arm has NO explicit `realised_increment` variable today.** `_process_transaction_spot`
(`portfolio.py:308-375`) captures `prior` (`portfolio.py:328`) and `prior_qty`
(`portfolio.py:329`) for its over-sell guard, mutates via `process_position_update`
(`portfolio.py:361`), and settles cash from `transaction.net_cash_delta` — it never computes a
realised delta.

**The SMA_MACD oracle is a SPOT run** (`enable_margin=False`), so it exercises
`_process_transaction_spot` exclusively. If the accumulator were fed only from the margin arm,
the oracle would feed the accumulator **nothing** and `get_total_realized_pnl` would return a
constant `Decimal('0.00')` — silently wrong, yet the margin-only wiring would still pass
`mypy`/import checks.

**Therefore the accumulator MUST be fed from BOTH arms:**

- **Margin arm:** reuse the existing `realised_increment` (`portfolio.py:529`); add the
  `position_manager.apply_realised_increment(realised_increment)` call on that same CLOSE-branch
  path. Apply ONLY in the close arm (the increase arm's increment is `0` and is never computed
  there).
- **Spot arm:** add a pre/post capture mirroring the margin arm —
  `prior_realised = prior.realised_pnl if prior is not None else Decimal("0")` **before** the
  `process_position_update` mutation, then after the mutation
  `realised_increment = position.realised_pnl - prior_realised` and
  `apply_realised_increment(realised_increment)`. Because OPEN/SCALE-IN yield increment `0`
  (Conclusion 4), applying it **unconditionally** is byte-safe — do NOT gate it behind a branch
  that could skip a partial close.

---

## Invariant statement (locked)

A `Position`'s `realised_pnl` changes **only** through `Position.update_position`, reached
**only** via `PositionManager.process_position_update`, reached **only** from the two
`Portfolio` settle arms `_process_transaction_spot` (`portfolio.py:361`) and
`_process_transaction_margin` (`portfolio.py:460`), and advances **only** on a reducing
(closing) fill. The accumulator is correct iff it is fed
`position.realised_pnl - prior_realised` on every reducing fill through **both** arms, and on
no other path. The Phase 3 equivalence regression test (D-03) + the byte-exact SMA_MACD oracle
+ the determinism double-run are the drift locks for this invariant — no hot-path runtime
re-sum guard is added (it would re-pay the O(positions) cost this phase removes).

---
status: pending
created: "2026-06-16"
source: surfaced in conversation (admission_manager.py WR-01 gate, cash_manager.py WR-04, ROADMAP Phase 4)
tags: [shorts, margin, increase, scale-in, D-09, WR-01, WR-04, deferred, out-of-v1-scope]
resolves_phase:
---

# Enable increasing/scaling into a SHORT position (margin scale-in)

**Origin:** Surfaced while reviewing Phase 3 (`v1.4/phase-3-shorts`). Increasing a short
is currently rejected at admission by design (D-09). This todo captures what the feature
would require — it is **out of v1 scope** and is **NOT** scheduled for Phase 4 (Phase 4 is
liquidation + cross-validation re-baseline, which hardens shorts that already exist, not
scale-in).

**Current behaviour (intentional):** an unsized SELL against an open SHORT is an AUDITED
rejection (`OrderTriggerSource.ADMISSION_INCREASE`), mirroring the long INCREASE gate.

- Gate: `itrader/order_handler/admission/admission_manager.py:537-556` (WR-01, D-09).
  Locked by test `tests/unit/order/test_admission_rules.py::test_short_only_unsized_sell_while_short_is_rejected`.
- Contrast: long increases ARE supported, gated behind the strategy `allow_increase` flag
  (`admission_manager.py:577-591`). Shorts have no such flag — blocked unconditionally.

**Why it is blocked — margin model gaps that must close first:**

1. **WR-01 — settlement-side solvency unchecked.** The margin open/scale-in path feeds
   `assert_funds_invariant` only the *commission*, not the full `aggregate_notional / L`
   being locked. The reservation gate is order-keyed and released on reconciliation, while
   the lock is position-keyed and applied at settlement — so there is no settlement-time
   assertion that the locked margin fits `available_balance`. (See `02-REVIEW.md` WR-01.)

2. **WR-04 — call-order bug in `assert_lock_fits_buying_power`**
   (`itrader/portfolio_handler/.../cash_manager.py:437-469`). The formula intends
   `buying_power = available_balance + own_prior_lock` (credit back the prior lock that is
   about to be re-locked), but `release_margin` pops the prior lock *before* the assertion
   runs, so `own_prior_lock` reads `0`. Conservative today (fails loud / over-strict, not a
   leak) on the cover-only path, but it is exactly the math a scale-in exercises.
   **Carried to Phase 4** (bundled under XVAL-01 owner-gated re-baseline) — see
   `phases/03-shorts-borrow-carry/deferred-items.md` (WR-04) and `ROADMAP.md:220-227`.

3. **Flip / split settlement (CR-02 residual, deferred).** A fill crossing zero or stacking
   opens needs proper aggregate-notional handling; no split path exists today.

4. **Liquidation over multiple opens.** Phase 4 forced-close math must reason about
   aggregate short notional, which presupposes (1)–(3) are correct.

**Do (when scope allows, post-Phase-4 foundation):**
1. Add the settlement-side buying-power assertion for the full locked margin (WR-01),
   not just commission.
2. Fix the WR-04 call order so the prior-lock credit-back actually holds (assert before
   release, or pass the released amount in) — likely landed in Phase 4 already; confirm.
3. Add a `allow_increase`-equivalent gate for shorts and route same-side SELL through
   entry/scale-in sizing instead of the admission rejection.
4. Handle flip/split settlement (CR-02 residual).
5. Cross-validate scale-in + liquidation scenarios against backtesting.py / backtrader.

**Notes:** Keep D-09 as the explicit "blocked until margin seam trustworthy" decision.
Do not lift the admission gate until WR-01/WR-04 + flip settlement are resolved.

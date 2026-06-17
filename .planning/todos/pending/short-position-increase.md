---
status: scheduled
created: "2026-06-16"
source: surfaced in conversation (admission_manager.py WR-01 gate, cash_manager.py WR-04, ROADMAP Phase 4)
tags: [shorts, margin, increase, scale-in, D-09, WR-01, WR-04, scheduled]
resolves_phase: "05.1"
scheduled_note: "2026-06-17 — promoted to v1.4 Phase 5.1 (Short Position Scale-In). WR-01/WR-04 confirmed already fixed in Phase 4 (see below); scope narrowed to the gate-lift + flip-guard test + owner-gated re-baseline."
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

**Why it was blocked — margin model gaps. STATUS UPDATE (2026-06-17): items 1 and 2 are
already RESOLVED in Phase 4; only item 3 (flip/split) remains, and it is being DEFERRED
out of Phase 5.1 by design (see Do list).**

1. **WR-01 — settlement-side solvency.** ✅ **RESOLVED in Phase 4.** A settlement-side
   buying-power assertion for the FULL locked margin now exists: `assert_lock_fits_buying_power`
   (`cash_manager.py:449-490`) is called against `aggregate_notional / leverage` on both the
   increase arm (`portfolio.py:439`) and the partial-close arm (`portfolio.py:460`), not just
   the commission. (Original concern: the path fed `assert_funds_invariant` only the commission.)

2. **WR-04 — call-order in `assert_lock_fits_buying_power`.** ✅ **RESOLVED in Phase 4.** The
   `assert → release → lock` order now holds (`portfolio.py:439-441` and `:460-464`), so the
   add-back (`get_locked_margin_for`, `cash_manager.py:484-485`) reads the TRUE prior lock, not
   `0`. (Original concern: `release_margin` popped the prior lock before the assertion ran.)

3. **Flip / split settlement (CR-02 residual, DEFERRED — stays a fail-loud guard).** A fill crossing zero or stacking
   opens needs proper aggregate-notional handling; no split path exists today.

4. **Liquidation over multiple opens.** Phase 4 forced-close math must reason about
   aggregate short notional, which presupposes (1)–(3) are correct.

**Do — Phase 5.1 scope (2026-06-17):**
1. ✅ ~~Settlement-side buying-power assertion (WR-01)~~ — DONE in Phase 4 (`portfolio.py:439/460`).
2. ✅ ~~WR-04 call order (assert before release)~~ — DONE in Phase 4 (`portfolio.py:439-441/460-464`).
3. **[Phase 5.1]** Add an `allow_increase`-equivalent gate for shorts at
   `admission_manager.py:537-556` (mirror the long gate at `:577-591`) and let the same-side SELL
   fall through to the EXISTING `resolve_entry` arm (`:800-806`) — no new sizing function; settlement
   reuses the existing SCALE-IN branch (`portfolio.py:423-441`).
4. **[DEFERRED — NOT Phase 5.1]** Flip/split settlement (CR-02 residual). Out of scope; the over-cover
   guard (`portfolio.py:399-404`) stays a fail-loud fence. A Phase 5.1 regression test asserts it still
   fires. Reversals, if ever needed, are modelled as explicit close-then-open signals OR a separate
   future owner-gated split-settlement phase.
5. **[Phase 5.1]** Cross-validate short scale-in against backtesting.py 0.6.5 / backtrader 1.9.78.123;
   owner-gated re-baseline.

**Notes:** Keep D-09 as the explicit "blocked until margin seam trustworthy" decision.
Do not lift the admission gate until WR-01/WR-04 + flip settlement are resolved.

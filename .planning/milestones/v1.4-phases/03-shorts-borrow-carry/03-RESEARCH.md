# Phase 3: Shorts & Borrow Carry - Research

**Researched:** 2026-06-15
**Domain:** Brownfield event-driven backtest accounting — first-class short positions + borrow-interest carry on the FRAGILE margin/settlement seam
**Confidence:** HIGH (every cited code location verified against the live codebase this session)

## Summary

This is a **de-risking research pass**, not a design pass. The design space is LOCKED
(CONTEXT.md D-01..D-10); the goal here was to verify every `file:line` the plans will
touch, confirm the current code shape, and surface integration hazards. **All ten cited
code locations were verified and match CONTEXT.md** — with three precise corrections to
line numbers and one structurally important finding about the carry hook.

The single most important finding: **the per-bar carry-accrual hook
(`update_portfolios_market_value` → `update_market_value_of_portfolio`) currently
discards everything except `prices` and stamps `datetime.now(UTC)` (wall clock) for the
position mark — it does NOT thread the bar's business `time` or the injected clock.**
D-02/D-04 require the bar's business time (for the days basis) AND the per-symbol
`borrow_rate` (from the injected `_universe`). Both are available at the handler level
but **neither is currently passed down**. The plans must thread `bar_event.time` and a
`borrow_rate` read through this method — this is the main new wiring, and it sits on the
determinism seam (wall clock here would break the double-run byte-identical gate).

The second key finding: the cover-arm bug (SHORT-02/D-05/D-06) is exactly where CONTEXT
says, but at **`admission_manager.py:703`** (not ~637; 637 is the method's `def`). The
fall-through condition is `signal_event.action is Side.SELL and open_position is not None
and open_position.net_quantity > 0` — a BUY-to-cover on an open short (`net_quantity < 0`)
fails this and falls straight into the entry-sizing arm at :726, flipping the book long.
The fix is the side-agnostic generalization D-05 describes, reusing the proven
`resolve_exit` (which already operates on the magnitude). `Position` already has the
`PositionSide.SHORT` PnL branches (D-08/SHORT-03) — confirmed at `position.py:182-190`
(realised) and `:203-204` (unrealised). The `CashOperationType` enum is **not** in
`reporting/cash_operations.py` (that file is an enum-agnostic duck-typed serializer
needing zero changes) — it lives at **`core/enums/portfolio.py:58`**; the new
`BORROW_INTEREST` member is added there.

**Primary recommendation:** Sequence the FRAGILE-seam touch as: (1) inert data/enum
plumbing first (`Instrument.borrow_rate`, `CashOperationType.BORROW_INTEREST`,
`TradingRules` already done) — all default-off, oracle-dark; (2) the side-agnostic
cover-arm + clamp-to-flat in `_resolve_signal_quantity`; (3) the registration two-flag
gate; (4) the carry-accrual wiring through `update_market_value_of_portfolio` (thread bar
time + universe); (5) the five WR residuals as a final hardening wave on the same locked
paths. Hold SMA_MACD byte-exact (134 / `46189.87730727451`) at every step via the
default-off gate; freeze NOTHING (golden re-baselines only at P4/XVAL-01).

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Registration guard relaxation (SHORT-01) | strategy_handler (`StrategiesHandler.add_strategy`) | config (`TradingRules` flags read) | Registration polices direction admissibility; the two flags it gates on live in config |
| Cover-arm side-agnostic exit + clamp-to-flat (SHORT-02) | order_handler (`AdmissionManager._resolve_signal_quantity`) | order_handler (`sizing_resolver.resolve_exit`) | The order/risk seam resolves quantity from policy vs position; it never matches — it sizes |
| Short PnL (SHORT-03) | portfolio_handler (`Position.realised/unrealised_pnl`) | — | Already first-class; `PositionSide.SHORT` branches exist — no new tier |
| Borrow-interest accrual (CARRY-01) | portfolio_handler (`update_market_value_of_portfolio`) | core (`Instrument.borrow_rate`, `BacktestClock`), universe (resolve `borrow_rate`) | Accrual rides the per-bar mark; reads per-symbol rate via the injected Universe read-model |
| Carry ledger entry (D-03) | portfolio_handler (`CashManager`) | core (`CashOperationType` enum) | Cash debit + audit record is the CashManager's domain |
| WR-01/03/05 (lock/settle/funds invariant) | portfolio_handler (`Portfolio._process_transaction_margin`, `CashManager`) | — | The margin lock/release/settle lifecycle |
| WR-04 (leverage floor) | order_handler (`AdmissionManager._effective_leverage`) | — | The leverage cap is resolved at admission |
| WR-02 (universe-unwired guard) | portfolio_handler (`PortfolioHandler.maintenance_margin`) | core (`StateError`) | The maintenance-margin read dereferences `_universe` |

## Standard Stack

**No new external packages.** Phase 3 is a pure brownfield change inside the existing
event-driven engine. Everything is stdlib + already-installed deps:

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `decimal` (stdlib) | — | Carry formula `days × price × |size| × rate/365`, all PnL | Decimal end-to-end is a LOCKED money policy [CITED: CLAUDE.md Money Policy] |
| `uuid-utils` | 0.16.x | `BORROW_INTEREST` CashOperation `operation_id` (UUIDv7) | Single ID scheme, already wired in `CashManager._create_operation` [VERIFIED: cash_manager.py:12 import] |
| `pytest` | 8.4.x | Component/unit + parked e2e proof | Project test runner [CITED: CLAUDE.md] |
| NautilusTrader | 1.227.0 | **Reference only** (flip-split pattern) — NOT imported into product code | Installed cross-validation/reconciliation oracle [VERIFIED: .venv path] |

**Installation:** None. `make test` / `poetry run pytest` already wired.

### NautilusTrader flip-split — pattern confirmed (D-05/D-06 mirror, reference only)

Verified the installed source confirms the deferred-flip pattern D-06 mirrors:
- `model/position.pyx:86` — `self.side = Position.side_from_order_side(fill.order_side)`:
  the **netting / signed-position** model. Order effect derived from order side vs
  position side, not a policy. This is D-05's principle. [VERIFIED: position.pyx:85-86]
- `execution/engine.pyx:1776` `_will_flip_position` = `is_opposite_side(fill.order_side)
  AND fill.last_qty > position.quantity` — the exact over-cover predicate. [VERIFIED]
- `execution/engine.pyx:1783` `_flip_position` splits the fill into a close-leg
  (`last_qty = position.quantity`, full PnL) + a fresh open-leg for the `difference`,
  splitting commission pro-rata. This is the **deferred** single-order flip (D-06) — Phase
  3 does clamp-to-flat instead and does NOT implement this. [VERIFIED: engine.pyx:1783-1835]

Do NOT reimplement the flip. Phase 3 clamps to flat; the split is a deferred explicit-quantity feature.

## Package Legitimacy Audit

> No external packages are installed in this phase. The Package Legitimacy Gate is **not
> applicable** — every dependency the work touches is already present in `poetry.lock`
> (verified against CLAUDE.md Technology Stack) and used by existing product code. No
> registry query, slopcheck, or postinstall audit is required.

## Architecture Patterns

### Data flow: a short, end to end (per CONTEXT design source §7)

```
SIGNAL (SHORT_ONLY/LONG_SHORT SELL)
  → StrategiesHandler.add_strategy        [SHORT-01: two-flag gate admits the strategy]
  → AdmissionManager._enforce_direction_admission  [already symmetric — admits the short SELL]
  → AdmissionManager._resolve_signal_quantity      [entry-sizing arm — sanctioned short entry]
  → OrderEvent → SimulatedExchange → FillEvent(EXECUTED)
  → PortfolioHandler.on_fill → Portfolio.transact_shares → _process_transaction_margin
       [opens a PositionSide.SHORT position; locks aggregate_notional/L; debits commission]

each subsequent BAR:
  → PortfolioHandler.update_portfolios_market_value(bar_events)
       → mark positions to bar.close
       → [CARRY-01: accrue days × close × |size| × rate/365 on open shorts;
          debit realized cash via a BORROW_INTEREST CashOperation; advance last_accrual]

COVER SIGNAL (BUY on the open short):
  → AdmissionManager._resolve_signal_quantity
       [SHORT-02/D-05: side-agnostic exit — BUY vs short routes through resolve_exit;
        D-06: clamp to |net_quantity| (no auto-flip)]
  → FillEvent → _process_transaction_margin (close arm)
       [releases the lock; settles realized short PnL = |size|×(entry−exit) − commissions]
```

### Pattern 1: Side-agnostic exit detection (D-05 — the cover-arm fix)

**What:** Generalize the long-only exit predicate to "order action opposes the open
position's side." Current code (the bug):

```python
# admission_manager.py:703 (VERIFIED) — long-only; a BUY-cover on a short falls through
if signal_event.action is Side.SELL and open_position is not None and open_position.net_quantity > 0:
    return self.sizing_resolver.resolve_exit(
        open_position.net_quantity, signal_event.exit_fraction,
        signal_event.sizing_policy.step_size,
    )
# else → entry sizing (:726) — flips a short book LONG (the CR-01 hole)
```

**Fix shape (D-05/D-06):** detect a reduction once — `(SELL vs net>0) OR (BUY vs net<0)`
— and pass the **magnitude** `abs(open_position.net_quantity)` to `resolve_exit`.
`resolve_exit` already operates on a magnitude and treats `exit_fraction == 1` as a
structural no-op (`sizing_resolver.py:174-177`, VERIFIED) — so the long path stays
byte-exact (same operands when `net_quantity > 0`, since `abs()` is identity there).
The clamp-to-flat (D-06) is implicit: `resolve_exit` returns at most the full magnitude;
a cover signal carries `exit_fraction` (reduction intent) with no opening basis, so the
excess simply cannot open a long.

**Discretion (CONTEXT):** the precise signature for passing the opposing-side magnitude.
Recommended: pass `abs(open_position.net_quantity)` so `resolve_exit` is unchanged.

### Pattern 2: Carry accrual at the read/cash edge (D-02/D-04/D-08)

**What:** Accrue per-bar, debit realized cash incrementally, keep `Position` PnL clean.
Mirrors P2 D-13 compute-at-the-edge. Carry is a SEPARATE `BORROW_INTEREST` cash debit,
never folded into `Position.realised_pnl` (D-08 — one carry site, clean attribution).

**Where:** inside the per-bar mark. **Integration hazard (see Pitfall 1):** the current
mark loses the bar time. The hook must thread `bar_event.time` (business time) for the
D-04 days basis and read `borrow_rate` from the injected `_universe`.

### Pattern 3: Byte-exact gate via default-off (established)

`allow_short_selling=False` / `enable_margin=False` / `borrow_rate=Decimal("0")` keep
SMA_MACD byte-exact. ALL new behavior is gated and oracle-dark. This is the same
discipline P1/P2 held [VERIFIED: STATE.md plan records, oracle held every phase].

### Anti-Patterns to Avoid
- **Folding carry into `Position.realised_pnl`** — creates a second carry site; D-08 forbids it.
- **Auto-opening a long on over-cover** — D-06 clamps to flat; the flip is deferred.
- **Using `datetime.now(UTC)` for the carry days basis** — breaks determinism (use `bar_event.time`).
- **Editing `reporting/cash_operations.py` for the new op** — it is enum-agnostic (duck-typed); no change needed.
- **Adding a second branch for the BUY-cover** — D-05 is one generalized branch, not a near-duplicate.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Cover/exit quantity sizing | A new BUY-cover sizing branch | `sizing_resolver.resolve_exit` (operates on magnitude, no-op at fraction 1) | Proven, byte-exact, dust-guarded [VERIFIED: sizing_resolver.py:147-186] |
| Short PnL | New short-PnL math | `Position.realised_pnl`/`unrealised_pnl` SHORT branches | Already first-class [VERIFIED: position.py:182-204] |
| Single-order flip economics | Close+open split | Clamp-to-flat (D-06); flip deferred | The Nautilus split is an explicit-quantity feature, out of scope |
| Cash audit serialization for BORROW_INTEREST | A new serializer | `reporting/cash_operations.py` (duck-typed, `op.operation_type.name`) | Enum-agnostic; new member just appears [VERIFIED: cash_operations.py:114-122] |
| Margin lock/release | New container | `CashManager.lock_margin`/`release_margin` (position-keyed) | The P2 lock-and-settle lifecycle [VERIFIED: cash_manager.py:470-519] |

**Key insight:** Almost everything Phase 3 needs already exists from P1/P2 — the work is
*wiring and gating*, not building. The only genuinely new mechanism is the carry accrual,
and even that books through the existing `CashManager` ledger primitives.

## Runtime State Inventory

> Not a rename/refactor phase — but it touches stored money state and a determinism seam,
> so the equivalent integration audit:

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | None — backtest uses in-memory portfolio/cash/order storage; no persisted carry state | None |
| Live service config | None — backtest only; live `PostgreSQLOrderStorage` is a `NotImplementedError` placeholder | None |
| Determinism seam | `update_market_value_of_portfolio` stamps `datetime.now(UTC)` (portfolio.py:586-587) — the carry days basis MUST use `bar_event.time`/`BacktestClock`, not this wall clock | Thread bar business time; do not reuse the wall-clock stamp for accrual |
| Config defaults | `TradingRules.allow_short_selling`/`enable_margin`/`max_leverage` already present (config/portfolio.py:71-81) | None — read by the D-07 guard; do not change defaults |
| Build artifacts | None — no package rename; `mypy --strict` over `itrader` re-runs against new fields | Run `mypy --strict` after `Instrument.borrow_rate` lands |

## Common Pitfalls

### Pitfall 1: The carry hook loses the bar's business time (PRIMARY HAZARD)
**What goes wrong:** `update_portfolios_market_value(bar_events)` extracts only
`bar.close` into a `prices` dict (portfolio_handler.py:427-430) and calls
`portfolio.update_market_value_of_portfolio(prices)` (`:437`), which marks positions with
`datetime.now(UTC)` (portfolio.py:586-587). The D-04 days basis (`this_bar.time −
last_accrual.time`) has **no source** in the current signature.
**Why it happens:** the mark path never needed business time before — only the close price.
**How to avoid:** thread `bar_event.time` (the `BarEvent` carries a business `time` per the
frozen-event contract) into `update_market_value_of_portfolio`, and read `borrow_rate` per
open short from the injected `_universe`. Both are available at the handler level
(`self._universe` is set, portfolio_handler.py:87/304). Do NOT use the wall-clock stamp.
**Warning signs:** a determinism double-run diff; carry amounts that vary run-to-run.

### Pitfall 2: `_universe` is `None` before `set_universe` (WR-02, and a carry hazard)
**What goes wrong:** `PortfolioHandler.maintenance_margin` dereferences
`self._universe.instrument(...)` (portfolio_handler.py:319) with `_universe` defaulting to
`None` (`:87`) — bare `AttributeError` if read with open positions before wiring. The carry
read will hit the **same** unguarded dereference.
**How to avoid:** WR-02 fix — fail loud with a `StateError` (universe-unwired, with
context) when positions exist but the universe is unwired. Apply the same guard at the new
carry read site.
**Warning signs:** `AttributeError: 'NoneType' object has no attribute 'instrument'`.

### Pitfall 3: `borrow_rate` default must be `Decimal("0")`, not `0`
**What goes wrong:** CONTEXT D-01 writes `borrow_rate: Decimal = 0`. A literal `0` is an
`int`; under `mypy --strict` and the Decimal money policy this is wrong — and `0 × ...`
silently re-enters int arithmetic.
**How to avoid:** `borrow_rate: Decimal = Decimal("0")` on the frozen `Instrument`
(core/instrument.py uses 4-space indent). The dataclass is `kw_only=True`, so a defaulted
field needs no ordering gymnastics — but every existing `Instrument(...)` construction
(synthetic test instruments, `derive_instruments`) keeps working since it defaults.
**Warning signs:** `mypy` int/Decimal incompatibility; carry computed as float.

### Pitfall 4: Over-cover settlement re-locks a flipped position (CR-02-residual)
**What goes wrong:** before the clamp, a reducing fill whose quantity exceeds the open
quantity reads `realised_increment` AFTER the full `transaction.quantity` mutated the
position, re-locking margin on a flipped position at the wrong leverage and settling a
wrong cash delta. P2 added a fail-loud guard (`_process_transaction_margin`,
portfolio.py:399-404, VERIFIED `raise InvalidTransactionError`).
**How to avoid:** D-06 clamp-to-flat at admission (`_resolve_signal_quantity`) means the
cover quantity never exceeds `|net_quantity|`, so the P2 guard is never tripped on a
sanctioned cover. Keep the P2 guard as defense-in-depth; the admission clamp is the
primary fix. Do NOT remove the guard.
**Warning signs:** `InvalidTransactionError: Margin close fill exceeds open quantity`.

### Pitfall 5: WR-05 open-commission drift on non-uniform scale-in
**What goes wrong:** the margin close re-credits the open commission via
`fraction * prior_entry_commission` (portfolio.py:452) where `fraction = closed_qty /
prior_qty`. After a non-uniform-commission scale-in (different commission rates across
adds), this quantity-fraction proxy drifts from the actual filled-fraction commission.
**How to avoid:** WR-05 — track the pre-debited open commission as a separate per-lock
accumulator (or settle against the actual filled-fraction commission). Oracle-dark
(margin off on the golden path).
**Warning signs:** round-trip cash delta ≠ realized PnL after a mixed-rate scale-in.

### Pitfall 6: Tab/space indentation hazard on the cross-cutting touch
**What goes wrong:** Phase 3 edits `core/instrument.py` + `config/portfolio.py` (4 spaces)
AND `portfolio_handler/`, `order_handler/`, `strategy_handler/` (tabs). A normalized diff
breaks a tab file.
**How to avoid:** match the file being edited; never normalize [CITED: CLAUDE.md
Conventions]. core/config = 4 spaces; the handlers = tabs.

## Code Examples

### Side-agnostic cover-arm (the SHORT-02/D-05/D-06 fix shape)
```python
# Source: admission_manager.py:703 (current) — generalized per D-05.
# Reduction = order action opposes the open position's side.
if open_position is not None and (
    (signal_event.action is Side.SELL and open_position.net_quantity > 0)
    or (signal_event.action is Side.BUY and open_position.net_quantity < 0)
):
    # D-06 clamp-to-flat: pass the magnitude; resolve_exit returns at most |net|.
    return self.sizing_resolver.resolve_exit(
        abs(open_position.net_quantity),
        signal_event.exit_fraction,
        signal_event.sizing_policy.step_size,
    )
# else: entry sizing (sanctioned short entry on a LONG_SHORT/SHORT_ONLY SELL).
```

### New cash-operation member (D-03)
```python
# Source: core/enums/portfolio.py:58 (CashOperationType) — add one member.
class CashOperationType(Enum):
    ...
    RELEASE_RESERVATION = "RELEASE_RESERVATION"
    BORROW_INTEREST = "BORROW_INTEREST"   # D-03 — per-bar short carry debit
# reporting/cash_operations.py needs NO change: it serializes op.operation_type.name
# (cash_operations.py:122) — enum-agnostic.
```

### Short PnL — already first-class (SHORT-03/D-08, no change needed)
```python
# Source: position.py:182-190 (VERIFIED) — the SHORT realised_pnl branch.
elif self.side == PositionSide.SHORT:
    if self.buy_quantity == 0:
        return Decimal("0")
    return (
        ((self.avg_sold - self.avg_bought) * self.buy_quantity)   # |size| × (entry − exit)
        - ((self.buy_quantity / self.sell_quantity) * self.sell_commission)
        - self.buy_commission
    )
# unrealised SHORT branch: (avg_price - current_price) * net_quantity  (position.py:203-204)
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `LONG_ONLY`-only registration | Two-flag (`allow_short_selling` AND `enable_margin`) gate | This phase (SHORT-01/D-07) | Short strategies admissible; spot byte-exact (both default off) |
| Cover BUY flips book long | Side-agnostic exit + clamp-to-flat | This phase (SHORT-02/D-05/D-06) | CR-01 hole closed |
| No financing cost | Per-bar `BORROW_INTEREST` carry debit | This phase (CARRY-01/D-02/D-03) | Carry visible in equity curve as it accrues |

**Deprecated/outdated:** none — this is additive on the P1/P2 core.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `BarEvent.time` carries the business time usable for the D-04 days basis (per the frozen-event contract) | Pitfall 1 | If `bar_events` time is not threadable here, the carry hook needs a different time source (clock injection) — moderate rework, not a design change |
| A2 | Passing `abs(net_quantity)` to `resolve_exit` keeps the long path byte-exact (since `abs` is identity for `net>0`) | Pattern 1 | If a test catches a repr difference, fall back to a magnitude-preserving call; low risk (abs of a positive Decimal is the same object's value) |
| A3 | A realistic BTCUSD `borrow_rate` for the parked scenarios is oracle-dark (Claude's discretion per CONTEXT) | Validation | None — explicitly the planner's/owner's discretion value; only affects parked (non-frozen) scenarios |

**All other claims are [VERIFIED] against the live codebase this session.**

## Open Questions

1. **Where exactly does `last_accrual` per-position timestamp live?**
   - What we know: D-04 needs `(this_bar.time − last_accrual.time)`; carry is per open short.
   - What's unclear: whether `last_accrual` is stored on `Position`, in `CashManager`, or
     derived from the prior mark. CONTEXT explicitly defers this to planner discretion.
   - Recommendation: store it where the per-bar mark already iterates positions; derive
     `days` from the gap; on the daily grid this is exactly 1. Keep it Decimal-safe.

2. **Per-portfolio vs per-position carry loop placement.**
   - What we know: CONTEXT marks this Claude's/planner's discretion.
   - Recommendation: per-position inside the existing mark loop (each open short reads its
     own `borrow_rate` and `|size|` × `close`), one `BORROW_INTEREST` debit per short per bar.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python 3.13 | All code/tests | ✓ | 3.13.x | — |
| pytest | Component + parked e2e | ✓ | 8.4.x | — |
| mypy | `--strict` gate | ✓ | 2.1.x | — |
| NautilusTrader source | Reference pattern only | ✓ | 1.227.0 (.venv) | — (reference, not imported) |

No external services required (backtest path is offline, in-memory storage).

## Validation Architecture

> `workflow.nyquist_validation` not disabled — section included. The golden master
> **freezes nothing** this phase (re-baseline only at P4/XVAL-01). The e2e scenarios are
> **PARKED** (hand-verified VERIFY note, NOT `--freeze`d), mirroring the existing
> `tests/e2e/levered_long/test_levered_long_scenario.py` PARKED template (VERIFIED — every
> number a hand-computed literal, drives the real SIGNAL→ORDER→FILL→PORTFOLIO path, asserts
> on margin internals, does NOT use the golden-diff harness).

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 8.4.x (folder-derived markers; `filterwarnings=["error"]`, `--strict-markers`, `--strict-config`) |
| Config file | `pyproject.toml [tool.pytest.ini_options]` |
| Quick run command | `poetry run pytest tests/unit/order tests/unit/portfolio -x` |
| Full suite command | `make test` |
| Byte-exact oracle gate | `make test-integration` → 134 trades / `final_equity 46189.87730727451` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| SHORT-01 | Two-flag gate admits SHORT_ONLY/LONG_SHORT; rejects when either flag off | unit | `pytest tests/unit/strategy/test_strategies_handler.py -k short_registration` | ❌ Wave 0 |
| SHORT-02 | BUY-cover reduces/closes short, does NOT flip long (side-agnostic exit) | unit | `pytest tests/unit/order/test_admission_rules.py -k cover_arm` | ❌ Wave 0 (file exists, add case) |
| SHORT-02 | Over-cover clamps to flat (excess does not auto-open long) | unit | `pytest tests/unit/order/test_admission_rules.py -k over_cover_clamp` | ❌ Wave 0 |
| SHORT-03 | Short realised/unrealised PnL = `|size|×(entry−exit)` | unit | `pytest tests/unit/portfolio/test_position.py -k short_pnl` | ❌ Wave 0 (file exists, add case) |
| CARRY-01 | `days × close × |size| × rate/365` accrued per bar; debits realized cash | unit | `pytest tests/unit/portfolio/test_cash_manager.py -k borrow_interest` | ❌ Wave 0 |
| CARRY-01 | `BORROW_INTEREST` op recorded with correct amount + balance_before/after | unit | `pytest tests/unit/portfolio/test_cash_manager.py -k borrow_interest_op` | ❌ Wave 0 |
| CARRY-01 | Days basis = elapsed between bar times (not hardcoded interval) | unit | `pytest tests/unit/portfolio/test_carry.py -k days_basis` | ❌ Wave 0 |
| WR-01 | Settlement-side solvency assertion (lock fits buying power) | unit | `pytest tests/unit/portfolio/test_portfolio_margin.py -k funds_invariant_lock` | ❌ Wave 0 |
| WR-02 | Universe-unwired read with open positions → `StateError` (not `AttributeError`) | unit | `pytest tests/unit/portfolio/test_portfolio_handler.py -k universe_unwired` | ❌ Wave 0 |
| WR-03 | Lock-release symmetry asserted/commented at assembly-failure site | unit | `pytest tests/unit/portfolio/test_cash_manager.py -k release_symmetry` | ❌ Wave 0 |
| WR-04 | `_effective_leverage` floors at `Decimal("1")`; guards zero/sub-1 instr cap | unit | `pytest tests/unit/order/test_admission_rules.py -k leverage_floor` | ❌ Wave 0 (file exists, add case) |
| WR-05 | Per-lock open-commission accumulator (no drift on non-uniform scale-in) | unit | `pytest tests/unit/portfolio/test_portfolio_margin.py -k open_commission_accumulator` | ❌ Wave 0 |

### Parked e2e scenarios (hand-verified, NOT frozen — D-10)
| Scenario | Asserts | File (new) |
|----------|---------|-----------|
| Pure short round-trip | SELL-to-open → BUY-to-cover; realised short PnL = `|size|×(entry−exit) − commissions`; lock released | `tests/e2e/short_roundtrip/test_short_roundtrip_scenario.py` |
| Short-with-carry | Multi-bar held short; per-bar `BORROW_INTEREST` debits; equity = PnL − Σ carry; determinism double-run identical | `tests/e2e/short_carry/test_short_carry_scenario.py` |
| Partial cover | BUY-cover with `exit_fraction < 1` reduces (not closes); remaining short carries on | `tests/e2e/partial_cover/test_partial_cover_scenario.py` |

**Template:** copy the PARKED discipline from `tests/e2e/levered_long/test_levered_long_scenario.py`
— hand-computed literals with arithmetic inline, synthetic instrument (NEVER BTCUSD — the
spot oracle stays byte-exact), drives the real run path, asserts on live read-model/cash/
position state, NO golden-diff harness. Owner-gated human-verify checkpoint, NOT `--freeze`.

### Sampling Rate
- **Per task commit:** `poetry run pytest tests/unit/order tests/unit/portfolio -x`
- **Per wave merge:** `make test`
- **Phase gate:** full suite green + `make test-integration` byte-exact (134 / `46189.87730727451`) + `mypy --strict` clean + determinism double-run byte-identical + parked-scenario human-verify approved.

### Wave 0 Gaps
- [ ] `tests/unit/strategy/test_strategies_handler.py` — SHORT-01 registration gate cases (verify file exists; add if absent)
- [ ] `tests/unit/order/test_admission_rules.py` — cover-arm, over-cover-clamp, leverage-floor cases (file EXISTS — add cases)
- [ ] `tests/unit/portfolio/test_position.py` — short PnL cases (verify; add)
- [ ] `tests/unit/portfolio/test_cash_manager.py` — borrow-interest op + release-symmetry cases
- [ ] `tests/unit/portfolio/test_carry.py` — NEW: days-basis / accrual formula
- [ ] `tests/unit/portfolio/test_portfolio_margin.py` — WR-01 funds invariant, WR-05 accumulator
- [ ] 3 new parked e2e dirs (`short_roundtrip/`, `short_carry/`, `partial_cover/`) with `__init__.py` + `bars.csv` + scenario test, mirroring `levered_long/`

## Security Domain

> `security_enforcement` not configured for this backtest-only accounting phase; no
> external input, network, auth, or untrusted-data surface is touched. The only
> correctness-critical controls are **money integrity** (Decimal end-to-end, no float for
> money) and **determinism** (no new nondeterminism). Both are enforced by the milestone
> gate (mypy `--strict`, double-run byte-identical), not an ASVS category. No applicable
> ASVS authentication/session/access-control/crypto categories for an offline backtest
> module.

## Sources

### Primary (HIGH confidence) — live codebase, verified this session
- `itrader/order_handler/admission/admission_manager.py:410,464,573,703,726` — direction gate (symmetric), `_effective_leverage` (WR-04), cover-arm bug site
- `itrader/order_handler/sizing_resolver.py:147-186` — `resolve_exit` (magnitude no-op, dust guard)
- `itrader/strategy_handler/strategies_handler.py:253` — `LONG_ONLY` registration guard
- `itrader/core/instrument.py:40-83` — frozen `Instrument` (kw_only); `maintenance_margin_rate`/`max_leverage` (borrow_rate added alongside)
- `itrader/config/portfolio.py:66-85` — `TradingRules` (`allow_short_selling`/`enable_margin`/`max_leverage`)
- `itrader/portfolio_handler/portfolio_handler.py:87,304,319,417,437` — `_universe` None default, carry hook, WR-02 site
- `itrader/portfolio_handler/portfolio.py:340-465,586` — `_process_transaction_margin` (WR-01/05, CR-02-residual guard), mark wall-clock site
- `itrader/portfolio_handler/position/position.py:182-204` — SHORT PnL branches (SHORT-03/D-08)
- `itrader/portfolio_handler/cash/cash_manager.py:14,24,385,438,470-519` — CashOperation, reserve/release, lock/release margin
- `itrader/core/enums/portfolio.py:58-69` — `CashOperationType` (where `BORROW_INTEREST` lands)
- `itrader/reporting/cash_operations.py:114-122` — enum-agnostic serializer (no change needed)
- `itrader/universe/universe.py:62-80` — `Universe.instrument(symbol)` resolver
- `.venv/.../nautilus_trader/model/position.pyx:85-86`, `execution/engine.pyx:1776-1835` — netting + flip-split pattern (reference)
- `tests/e2e/levered_long/test_levered_long_scenario.py` — PARKED scenario template

### Secondary
- `.planning/phases/03-shorts-borrow-carry/03-CONTEXT.md` — locked decisions D-01..D-10
- `.planning/phases/02-margin-accounting-leverage/deferred-items.md` — WR-01..05/CR-02-residual table
- `.planning/REQUIREMENTS.md`, `.planning/STATE.md`, `.planning/ROADMAP.md` (via STATE Phase Map)

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — no new packages; all deps verified present
- Architecture / code locations: HIGH — every cited `file:line` opened and confirmed this session
- Pitfalls: HIGH — each pitfall traced to a specific live line (carry hook, `_universe` None, WR sites)
- WR residual sites: HIGH — confirmed exact lines (portfolio.py:399-404/411-412/452, admission:589-594, portfolio_handler:319)
- Carry time-threading (A1): MEDIUM — `BarEvent` carries business time by contract; the threadability into the mark is the one item to confirm at plan time

**Line-number corrections vs CONTEXT (all confirmed, locations valid):**
- `_resolve_signal_quantity` cover-arm: the bug is at **:703** (the predicate); :637 is the `def`.
- `update_portfolios_market_value`: handler method at **:417**; the per-portfolio mark that needs the carry hook + bar-time is `portfolio.update_market_value_of_portfolio` at **portfolio.py:581** (called from :437).
- `realised_pnl`/`unrealised_pnl` SHORT branches: at **position.py:182-190 / 203-204** (CONTEXT cites :169/:195, the property `def`s — branches are inside).
- `CashOperationType` enum: at **core/enums/portfolio.py:58** (NOT in `reporting/cash_operations.py`, which is an enum-agnostic serializer needing no edit).

**Research date:** 2026-06-15
**Valid until:** 2026-07-15 (stable brownfield; codebase is the moving part, not external deps)

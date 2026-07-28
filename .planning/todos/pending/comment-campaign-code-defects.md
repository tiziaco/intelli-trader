---
status: open
created: "2026-07-28"
source: comment-reduction campaign (13 files, 2026-07-28) — defects surfaced while auditing comments against real code; flagged, never fixed (the campaign is comment-only, AST-verified)
tags: [live, okx, safety, halt-vocabulary, config-reachability, liquidation, encapsulation, dead-parameter]
resolves_phase: ""
---

# Code defects surfaced by the comment-reduction campaign

**Origin:** The 2026-07-28 comment-reduction pass over 13 files. Every comment was checked
against the code it described; where the code turned out to be wrong rather than the comment,
it was **flagged and left alone** — that campaign changes no code (`verify.py` asserts the AST
is byte-identical to HEAD after every batch).

All items below were re-verified by grep at HEAD before being written down. Symbol names, not
line numbers — the campaign's single most common finding was decayed line coordinates.

## 1. `TradingRules.liquidation_fee_rate` is unreachable from production (worst of the set)

`SimulatedMarginAccount` prices the liquidation penalty off `instrument.liquidation_fee_rate`
(`portfolio_handler/account/simulated.py`). `Instrument.liquidation_fee_rate` defaults to
`Decimal("0")`. **No production builder ever sets it:**

- `universe/instruments.py::derive_instruments` — builds the field ladder
  (`maintenance_margin_rate`, `max_leverage`, `settles_funding`) and omits `liquidation_fee_rate`
- `execution_handler/exchanges/okx.py::resolve_precision` — omits it
- `universe/universe.py` default-ladder fallback — omits it

So `PortfolioConfig.trading_rules.liquidation_fee_rate` (a real, validated `ge=0` config field,
documented in `core/instrument.py` as the value `Instrument` falls back to) **never reaches an
`Instrument`.** Every production liquidation prices its penalty at zero regardless of config.

**Why the suite is green:** every test that exercises a non-zero rate hand-builds the
`Instrument` and bypasses the builders — `tests/e2e/levered_long_into_liquidation/` constructs
`Instrument(liquidation_fee_rate=_LIQUIDATION_FEE_RATE)` directly, and the unit tests
(`test_liquidation.py`, `test_liquidation_reconcile.py`) set the attribute on a stub. The
penalty maths is proven correct on a value production cannot produce. Textbook false-green:
tested and unreachable.

**Fix:** thread `TradingRules.liquidation_fee_rate` into `derive_instruments` (and decide what
the OKX/default-ladder arms should do), then add a test asserting a configured rate survives
into the built `Instrument` — i.e. cover the wiring, not just the arithmetic.
**Oracle risk:** the spot SMA_MACD oracle never liquidates, so this should be oracle-dark —
confirm before landing.

## 2. `deferred-protective-overflow` is an off-vocabulary halt reason

`SafetyController` defines `_DEFERRED_PROTECTIVE_OVERFLOW_REASON = "deferred-protective-overflow"`
and passes it straight to `self.halt()` from `gate_and_dispatch`. It is **not** a member of
`core/enums/system.py::HaltReason`, which claims in its own docstring: *"Exactly the reasons that
reach `halt()` … one member per live reason, no dead members."*

Either the enum is missing a member or the constant should be `HaltReason.…`.

**Directly continues [[off-vocabulary-halt-reason-baseline-residual-wr04]]** — same defect class
(`baseline-residual`), which that todo fixed for one string in P1 while deferring the
`halt(reason: str) → HaltReason` signature migration. This is a **new** off-vocabulary string
that appeared *after* that todo was written, which is the argument for finishing the migration
rather than patching strings one at a time: nothing structurally prevents the next one.

## 3. `gate_and_dispatch`'s `dispatch_fn` parameter is dead

`SafetyController.gate_and_dispatch` takes a `dispatch_fn` parameter that no caller passes.
`live_runner.py` holds `dispatch_gate=safety.gate_and_dispatch` and calls
`self._dispatch_gate(event)` with **one** argument; all nine test call sites pass the event only.
It always falls through to `self._dispatch_fn`. Dead parameter — delete it, or document why the
override exists.

## 4. `deferred_maxlen` is not operator-tunable

`SafetyController.__init__` takes `deferred_maxlen` (default 1000), but `build_live_system`
passes none and `SafetySettings` (`config/safety.py`, which holds only `throttle` and
`failure_rate`) has no field for it. The only override anywhere is in
`tests/unit/trading_system/test_safety_controller.py`. The deferred-protective-order queue bound
is therefore a hard-coded constant in production despite `SafetySettings` being its obvious home.
Note the overflow path **halts the engine** (item 2), so this bound has real operational weight.

## 5. Mixed key types in the OKX correlation index

`OkxExchange._submit_order` registers with the **raw** `response.get("id")`, while
`adopt_venue_correlation` and `_handle_order_update` both key on `str(venue_id)` (as does the
emitted `OrderAckEvent`). If ccxt ever yields a non-`str` `id`, a submitted order is indexed
under an `int` while the order-status stream looks it up as a `str` → **silent correlation miss
on the CANCELLED/EXPIRED reconcile path**.

Latent today (ccxt normalises `id` to `str`), but the file is internally inconsistent about it
and the failure is silent rather than loud. Fix: normalise once at the boundary.

## 6. `OkxExchange._active_symbols` is never pruned

Added to on every submit and every adopted rehydrated order; nothing removes a symbol on
terminalization; read by the per-resume missed-fill catch-up. The `__init__` prose correctly
says the *correlation index* state is bounded (release-on-terminal + dedup ring) — but
`_active_symbols` sits outside that and grows monotonically for the process lifetime, widening
the catch-up fan-out over a long live session. Over-inclusion is dedup-safe for *correctness*;
this is an unbounded-growth issue, not a correctness one.

## 7. `OkxExchange.unsubscribe` reaches into `StreamSupervisor` privates

The early-return guard reads `self._supervisor._streams_down` and
`self._supervisor._reconnect_attempts` directly. `StreamSupervisor`'s public surface is
`mark_down` / `mark_up` / `reset_budget` / `is_healthy` / `forget` — there is no membership
predicate, which is why the caller cracked the encapsulation. Behaviour is correct and covered
(`test_unsubscribe_stale_supervisor_state_without_task_still_marshals`); this is coupling only.
Fix: add `StreamSupervisor.tracks(stream_name) -> bool`.

## Suggested handling

Items 2–4 are one coherent `SafetyController` cleanup and pair naturally with finishing
[[off-vocabulary-halt-reason-baseline-residual-wr04]]. Items 5–7 are one OKX-exchange cleanup.
Item 1 is independent, is the only one with a real behavioural consequence today, and should be
scoped on its own — it needs an oracle check and a decision about the OKX/default-ladder arms.

**Related:** [[comment-campaign-dead-symbol-citations]] (documentation defects from the same
campaign), [[comment-campaign-untested-safety-claims]] (test gaps from the same campaign).

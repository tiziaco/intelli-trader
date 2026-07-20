---
status: pending
created: "2026-07-20"
source: surfaced by v1.8 Phase 10.1 code review (10.1-REVIEW.md, Critical finding) — verified PRE-EXISTING, deferred out of a behaviour-preserving phase
tags: [strategy, live-control-plane, error-handling, halt, admission, d-10, security-adjacent]
resolves_phase: "future"
folded_into: ""
---

# `add` verb: bare `ValueError` escapes the catch tuple and can latch live trading into HALT

**Origin:** Found by the Phase 10.1 code review. **Not introduced by Phase 10.1** — the catch
tuple was verified byte-identical to its pre-phase form at `e79c18f3`
(`strategies_handler.py:745-752` → `lifecycle/manager.py:392-399`). Phase 10.1 was explicitly
behaviour-preserving and golden-master gated, so fixing it in-phase would have violated that
contract. Deferred here deliberately, not overlooked.

## The defect

`itrader/strategy_handler/lifecycle/manager.py:391-405` — `_add_strategy_verb` wraps
`build_strategy(...)` in a catch tuple of `UnknownStrategyTypeError`, `StrategyConfigError`,
`UnknownParamError`, `MissingParamError`. It **omits `ValueError`**.

But `build_strategy` deliberately propagates, and its `cls(**params)` runs `_apply_params` →
`validate()`, both of which raise **bare** `ValueError`:

- `itrader/strategy_handler/base.py:292` — `raise ValueError("tickers must be a non-empty list[str] (a bare str is rejected)")`
- `itrader/strategy_handler/strategies/SMA_MACD_strategy.py:42` — `raise ValueError("short_window must be < long_window")`

## Why it has teeth

1. `STRATEGY_COMMAND` is **externally admitted** (D-10) — `LiveTradingSystem.add_event` accepts
   externally-originated `STRATEGY_COMMAND` events.
2. The raise violates `_add_strategy_verb`'s own documented never-raise contract (its comment
   says every construction failure is "a loud no-op").
3. In live mode the escape feeds `ErrorPolicy.record_failure` → the failure-rate tripwire →
   `halt()`.
4. Per CLAUDE.md, `HALTED` has **no legal exit except operator `reset_halt()`**.

Net: a payload as ordinary as `{"strategy_type": "SMA_MACD", "tickers": []}` — routine bad
operator input, not an attack — can latch live trading into HALT.

## Evidence it is an omission, not a design choice

The two sibling construction/apply sites **in the same file** both include `ValueError`, and one
carries a comment naming exactly this hazard:

- `manager.py:764-773` (`reconfigure` trial construction) — *"SPECIFIC types (ValueError covers
  `validate()` + the `_apply_params` tickers/enum guards)"*
- `manager.py:824-829` (`reconfigure` apply)

Only the `add` path lacks it.

## Fix sketch

Add `ValueError` to the `_add_strategy_verb` catch tuple, matching the sibling sites. Then:

- Add a regression test driving `add` with `tickers: []` and with `short_window >= long_window`,
  asserting a loud no-op (WARNING logged, nothing registered, nothing persisted) rather than a raise.
- Check whether `TypeError` deserves the same treatment (`cls(**params)` with a bad arity/kind
  would raise it) — the sibling sites do not catch it either, so decide deliberately rather than
  by symmetry alone.

**This changes behaviour** (a currently-raising path becomes a logged no-op), so it needs its own
phase or an explicitly non-golden-master task, and the oracle should be re-confirmed after.

## Related

The same review raised WR-01 (roster drop split across two objects with a raising store `delete`
between `remove()` and `discard_pending`/`recompute_min_timeframe`), WR-04 (`portfolio_read_model:
Any` hiding a `PortfolioId | int` vs `PortfolioId` mismatch in `_strategy_is_flat`), and WR-06
(`min_timeframe` has no production reader in `itrader/` despite two docstrings claiming the price
handler consumes it). All are in `.planning/phases/10.1-strategies-handler-decomposition/10.1-REVIEW.md`.

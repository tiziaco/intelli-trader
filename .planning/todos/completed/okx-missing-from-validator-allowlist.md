---
id: okx-missing-from-validator-allowlist
title: "okx is not in EnhancedOrderValidator.supported_exchanges"
status: pending
severity: high
source: 11.1-REVIEW.md (CR-03)
created: 2026-07-22
---

# `okx` missing from the order-validator allowlist

`EnhancedOrderValidator.supported_exchanges` (`itrader/order_handler/order_validator.py:125`)
is `{"NYSE", "NASDAQ", "BINANCE", "OANDA", "default", "paper"}`. `exchange_for` returns
`"okx"` for live OKX portfolios, so `_validate_exchange_support` emits an
`UNSUPPORTED_EXCHANGE` ERROR and `validate_order_pipeline` short-circuits at PHASE 2 —
no `OrderEvent` is ever emitted for an OKX portfolio. The set has exactly one assignment
tree-wide.

## NOT introduced by phase 11.1 — verified

The pre-phase baseline (commit `6d5f9ff7`) was:

    {"NYSE", "NASDAQ", "BINANCE", "OANDA", "default", "simulated", "csv"}

`okx` was already absent. Phase 11.1 (plan 11.1-06, D-05) renamed the retired
`simulated`/`csv` synonyms onto `paper`, which is exactly what that plan specified.
The code-review finding described this as "the line this phase edited", which is true
of the line but not of the defect — the `okx` gap predates the phase.

## Why nothing is red

No offline test drives a live OKX portfolio through admission; the OKX suites are
credential-gated and skip without `OKX_API_KEY`/`OKX_API_SECRET`/`OKX_API_PASSPHRASE`.

## Fix shape

Add `"okx"` to the set AND to the `@pytest.mark.parametrize` list in
`tests/unit/order/test_order_validator_venue_allowlist.py::test_backtest_venue_names_are_admitted`
in the same commit — plan 11.1-02 built that guard specifically so the allowlist and its
test cannot drift apart. Consider deriving the allowlist from the venue registry instead
of a hand-maintained literal, so a newly registered venue cannot be admission-blocked.

"""The shared SQL spine package (D-01).

A domain-neutral home that every storage concern *composes* — ``SqlBackend`` (Engine +
MetaData, no business logic) plus the cross-dialect ``types`` helpers. The public barrel
surface is assembled here; like ``price_handler/store``, no quarantined SQL-heavy backend
is imported at package level so the backtest import path stays SQL-free.
"""

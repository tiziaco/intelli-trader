"""No-NaN/no-inf metric guard helper (Phase 9, D-05, ROBUST-03).

The ROBUST-03 degenerate-metrics leaves (no_trade / flat / losing, Plan 04) freeze
the ``summary.json`` ``metrics`` block AND assert every metric is finite. Exact
golden-equality alone fails confusingly on NaN (``nan != nan``), so the explicit
finiteness assert is the ROBUST-03 contract (RESEARCH Pitfall 5). The reporting
metric guards (``reporting/metrics.py``) already coerce degenerate cases to 0.0
(and ``profit_factor`` to ``inf`` only for an all-WIN frame, which the leaves
avoid by authoring naturally-finite PnL) — this helper PROVES that contract holds
end-to-end.

Indentation: 4 spaces (matches ``tests/conftest.py`` / the e2e package house style).
"""

import math


def assert_metrics_finite(metrics: dict[str, float]) -> None:
    """Assert every value in ``metrics`` is finite (no NaN, no +/-inf) — D-05.

    Uses stdlib ``math.isfinite`` over the tiny derived-metrics dict
    (sharpe/sortino/cagr/max_drawdown/profit_factor/win_rate). Collects any
    non-finite entries so the failure message names exactly which metric drifted.
    """
    bad = {k: v for k, v in metrics.items() if not math.isfinite(v)}
    assert not bad, (
        f"ROBUST-03: degenerate metrics must be finite (no NaN/inf), got {bad}"
    )

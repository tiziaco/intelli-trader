"""Explicit no-NaN/no-inf metrics assertion over the ROBUST-03 leaves (D-05).

The ROBUST-03 degenerate leaves (no_trade / flat / losing) each FREEZE their
``summary.json`` metrics block, which the harness exact-diffs. But exact golden
equality alone fails CONFUSINGLY on a NaN (``nan != nan``), and a hand-verifier
could silently freeze one. This test makes "no NaN / no inf" the EXPLICIT,
documented ROBUST-03 contract (RESEARCH Pitfall 5): it re-runs each leaf in-process,
extracts the live ``summary["metrics"]`` block, and asserts every value is finite
via ``assert_metrics_finite``.

Why import the harness internals directly (Pitfall 6)
-----------------------------------------------------
``_load_spec`` / ``_build_and_run`` / ``_assemble`` are private to ``conftest.py``,
but ``conftest.py`` IS a real importable module (``tests.e2e.conftest``) -- so we
import the trio directly rather than promoting them to a separate ``_harness.py``,
mirroring ``test_determinism.py``'s import shape. ``_build_and_run``'s return arity
grew in Plan 01 (Task 1, D-01: ``portfolio_ids`` is threaded out), so the unpack
uses ``*rest`` to stay in sync with the extended signature and forwards it straight
into ``_assemble``.

Indentation: 4 spaces (matches ``tests/conftest.py`` / the e2e package house style).
"""

import pathlib

import pytest

from tests.e2e.conftest import _load_spec, _build_and_run, _assemble
from tests.e2e.robust._assert_finite import assert_metrics_finite

_E2E_ROOT = pathlib.Path(__file__).resolve().parents[1]  # tests/e2e/

# Exactly the three ROBUST-03 degenerate-metrics leaves authored in Plan 04. Static
# Path objects -- no filesystem access at parametrize time.
ROBUST03_LEAVES = [
    _E2E_ROOT / "robust" / "no_trade",
    _E2E_ROOT / "robust" / "flat",
    _E2E_ROOT / "robust" / "losing",
]


@pytest.mark.parametrize("leaf_dir", ROBUST03_LEAVES, ids=lambda p: p.name)
def test_metrics_finite(leaf_dir):
    """Run ``leaf_dir`` and assert its derived-metrics block is all-finite (D-05)."""
    scenario_path = leaf_dir / "scenario.py"
    spec = _load_spec(scenario_path)
    # *rest captures the extended _build_and_run arity (D-01 portfolio_ids) so this
    # test stays in sync with the Plan-01 signature extension.
    system, portfolio, *rest = _build_and_run(spec)
    _trades, _equity, summary, *_ = _assemble(spec, system, portfolio, *rest)
    assert_metrics_finite(summary["metrics"])

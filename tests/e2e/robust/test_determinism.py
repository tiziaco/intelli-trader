"""Parametrized in-process double-run determinism test (Phase 9, D-04, ROBUST-04).

Every Phase 9 leaf is run TWICE in-process and the two raw outputs (trades / equity
/ summary incl. metrics) are asserted IDENTICAL to each other. This proves the
engine is reproducible run-to-run (seeded RNG + injected clock — PROJECT determinism
constraint), independent of whether the leaf's golden is correct. It is the
ROBUST-04 contract.

Why import the harness internals directly (Pitfall 6)
-----------------------------------------------------
``_load_spec`` / ``_build_and_run`` / ``_assemble`` are private to ``conftest.py``,
but ``conftest.py`` IS a real importable module (``tests.e2e.conftest``) — so we
import the trio directly rather than promoting them to a separate ``_harness.py``.
``_build_and_run``'s return arity grew in the foundational plan (Task 1, D-01:
``portfolio_ids`` is now threaded out), so the unpack uses ``*rest`` to stay in
sync with the extended signature and forwards it straight into ``_assemble``.

Collection discipline
----------------------
``PHASE9_LEAVES`` is a static list of Path objects, so the file COLLECTS clean even
before the parallel-wave leaves (Plans 02-04) exist — no filesystem access at
parametrize time. At RUN time a leaf whose ``scenario.py`` is not yet authored is
SKIPPED (it will turn green automatically once its wave lands); at this plan's wave
the ``fanout_portfolios`` canary is present and runs for real.

Indentation: 4 spaces (matches ``tests/conftest.py`` / the e2e package house style).
"""

import pathlib

import pandas.testing as pdt
import pytest

from tests.e2e.conftest import _load_spec, _build_and_run, _assemble

_E2E_ROOT = pathlib.Path(__file__).resolve().parents[1]  # tests/e2e/

# The nine Phase 9 leaves (multi-entity + robustness). Static Path objects — no
# filesystem access here, so this file collects clean before the wave leaves exist.
PHASE9_LEAVES = [
    _E2E_ROOT / "multi" / "two_tickers",
    _E2E_ROOT / "multi" / "two_strategies",
    _E2E_ROOT / "multi" / "fanout_portfolios",
    _E2E_ROOT / "multi" / "contended_cash",
    _E2E_ROOT / "robust" / "sparse_bar",
    _E2E_ROOT / "robust" / "union_window",
    _E2E_ROOT / "robust" / "no_trade",
    _E2E_ROOT / "robust" / "flat",
    _E2E_ROOT / "robust" / "losing",
]


@pytest.mark.parametrize("leaf_dir", PHASE9_LEAVES, ids=lambda p: p.name)
def test_double_run_identical(leaf_dir):
    """Run ``leaf_dir`` twice in-process; assert the raw outputs are identical (ROBUST-04)."""
    scenario_path = leaf_dir / "scenario.py"
    if not scenario_path.exists():
        # Not-yet-authored parallel-wave leaf (Plans 02-04): skip until it lands.
        # This file COLLECTS clean today; only the present fanout_portfolios canary
        # runs for real at this plan's wave.
        pytest.skip(f"leaf not yet authored: {leaf_dir.name}")

    def once():
        spec = _load_spec(scenario_path)
        # *rest captures the extended _build_and_run arity (D-01 portfolio_ids) so
        # this test stays in sync with the Task-1 signature extension.
        system, portfolio, *rest = _build_and_run(spec)
        return _assemble(spec, system, portfolio, *rest)

    a = once()
    b = once()
    pdt.assert_frame_equal(a[0], b[0])  # trades
    pdt.assert_frame_equal(a[1], b[1])  # equity
    assert a[2] == b[2]                 # summary dict incl. metrics block

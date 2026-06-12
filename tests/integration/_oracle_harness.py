"""Shared oracle-harness helpers for the integration tests (IN-03).

The repo-root / oracle-generator path constants and the ``importlib`` helper
that loads ``scripts/run_backtest.py`` as a module were copy-pasted near-verbatim
across ``test_backtest_oracle.py`` and ``test_reservation_inertness.py`` (and the
golden pins were re-imported from ``run_backtest.py`` in several places). This
module is the single home for them so the copies cannot drift.

4-space indentation (tests house style).
"""

import importlib.util
import pathlib


# Repo layout: this file lives at <repo>/tests/integration/, so the repo root is
# two parents up. The oracle generator and its output/golden dirs are anchored
# from there — the single source of these paths for the integration suite.
_REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
_RUN_BACKTEST = _REPO_ROOT / "scripts" / "run_backtest.py"
_OUTPUT_DIR = _REPO_ROOT / "output"
_GOLDEN_DIR = _REPO_ROOT / "tests" / "golden"


def load_run_backtest_module(module_name: str = "run_backtest"):
    """Import scripts/run_backtest.py as a module (it is not on the package path).

    ``module_name`` lets callers register the module under distinct names
    (e.g. ``run_backtest`` vs ``run_backtest_inertness``) so two simultaneously
    loaded copies do not collide in ``sys.modules``.

    WR-05: fail loudly with a clear message if the oracle generator moved or
    ``spec_from_file_location`` could not resolve a loader, rather than dying
    with an opaque ``AttributeError`` on ``None``.
    """
    # Local import so a non-pytest importer of this helper does not pay the
    # pytest dependency just to resolve the constants.
    import pytest

    if not _RUN_BACKTEST.exists():
        pytest.fail(f"oracle generator missing: {_RUN_BACKTEST}")
    spec = importlib.util.spec_from_file_location(module_name, _RUN_BACKTEST)
    assert spec is not None and spec.loader is not None, f"cannot load {_RUN_BACKTEST}"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

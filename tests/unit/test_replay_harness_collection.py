"""Collection-safety guard for the relocated replay harness (TEST-01 / D-22 / Wave 0).

The replay harness (``tests/support/replay_harness.py``) defines three ``Test*``-named
NON-test classes — ``TestLiveDataProvider`` / ``TestDataPlugin`` / ``TestRunner``. Under
pytest's default ``python_classes = Test*`` these would be AUTO-COLLECTED as test classes;
each has an ``__init__`` with required args, so collection would emit a
``PytestCollectionWarning`` — a HARD failure under the project's ``filterwarnings=["error"]``.

D-22 opts each class out with ``__test__ = False``. This module proves the opt-out holds
two ways:

1. Directly — every ``Test*`` class in the harness carries ``__test__ is False``.
2. End-to-end — running ``pytest --collect-only`` over the harness file collects ZERO
   items and raises NO collection warning (a fresh subprocess so the assertion is not
   contaminated by the parent session's collected items).

Package-less top-level unit module (no ``__init__.py``), folder-derived ``unit`` marker.
"""

from __future__ import annotations

import inspect
import subprocess
import sys
from pathlib import Path

import tests.support.replay_harness as harness

_HARNESS_PATH = Path(harness.__file__)
_REPO_ROOT = _HARNESS_PATH.parents[2]  # tests/support/replay_harness.py -> repo root


def test_every_test_named_harness_class_opts_out_of_collection() -> None:
    """D-22: every ``Test*``-named class in the harness sets ``__test__ = False``."""
    test_named = [
        name
        for name, obj in inspect.getmembers(harness, inspect.isclass)
        if name.startswith("Test") and obj.__module__ == harness.__name__
    ]
    # The three relocated concretions must all be present (guards a silent rename).
    assert set(test_named) == {"TestLiveDataProvider", "TestDataPlugin", "TestRunner"}, (
        f"unexpected Test*-named harness classes: {sorted(test_named)!r}"
    )
    for name in test_named:
        cls = getattr(harness, name)
        assert cls.__test__ is False, (
            f"{name} must set __test__ = False (D-22) — else pytest collects it as a test "
            "class and the __init__-with-args emits a PytestCollectionWarning, a HARD "
            "failure under filterwarnings=['error']"
        )


def test_pytest_collects_zero_items_from_the_harness_module() -> None:
    """End-to-end (Wave 0): ``pytest --collect-only`` over the harness collects 0 items.

    Runs in a FRESH subprocess under the project config (``filterwarnings=["error"]``): a
    collected ``Test*`` class would raise a ``PytestCollectionWarning``-as-error during
    collection (exit 2), and any collected item would be a non-empty collection (exit 0).
    The clean outcome is pytest's canonical "no tests collected" exit code 5.
    """
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", str(_HARNESS_PATH)],
        cwd=str(_REPO_ROOT),
        capture_output=True,
        text=True,
    )
    combined = result.stdout + result.stderr
    # No collection warning leaked (would be an error under filterwarnings=["error"]).
    assert "PytestCollectionWarning" not in combined, (
        "the harness raised a PytestCollectionWarning — a Test* class is being collected "
        f"(missing __test__ = False?).\n{combined}"
    )
    # Exit 5 == pytest collected ZERO items cleanly (not exit 0 = items collected, not
    # exit 2 = collection error from the warning-as-error).
    assert result.returncode == 5, (
        "expected pytest exit code 5 (no tests collected) from the harness module — got "
        f"{result.returncode}.\n{combined}"
    )

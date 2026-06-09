"""Leaf test for MATCH-04 (bracket OCO full lifecycle).

The ONLY allowed body: delegate to the shared ``run_scenario`` harness with this
leaf's own directory. The harness owns build → run → read → assemble →
diff-what's-frozen (incl. the opt-in ``orders.csv`` snapshot); the leaf adds NO
assert/diff logic of its own.
"""

import pathlib

HERE = pathlib.Path(__file__).resolve().parent


def test_oco_lifecycle(run_scenario):
    run_scenario(HERE)

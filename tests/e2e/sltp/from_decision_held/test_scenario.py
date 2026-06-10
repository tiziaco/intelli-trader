"""Leaf test for SLTP-01/03 (PercentFromDecision held-to-end).

The ONLY allowed body: delegate to the shared ``run_scenario`` harness with this
leaf's own directory. The harness owns build → run → read → assemble →
diff-what's-frozen (incl. the opt-in ``orders.csv`` snapshot); the leaf adds NO
assert/diff logic of its own.
"""

import pathlib

HERE = pathlib.Path(__file__).resolve().parent


def test_from_decision_held(run_scenario):
    run_scenario(HERE)

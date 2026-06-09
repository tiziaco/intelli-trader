"""Leaf test for MATCH-05 (same-bar STOP-beats-LIMIT priority).

The ONLY allowed body: delegate to the shared ``run_scenario`` harness with this
leaf's own directory. The harness owns build → run → read → assemble →
diff-what's-frozen (incl. the opt-in ``orders.csv`` snapshot); the leaf adds NO
assert/diff logic of its own.
"""

import pathlib

HERE = pathlib.Path(__file__).resolve().parent


def test_stop_beats_limit(run_scenario):
    run_scenario(HERE)

"""Leaf test for MATCH-06 gap_past_both_legs (gap past BOTH bracket legs).

The ONLY allowed body: delegate to the shared ``run_scenario`` harness with this
leaf's own directory. The harness owns build -> run -> read -> assemble ->
diff-what's-frozen; the leaf adds NO assert/diff logic of its own.
"""

import pathlib

HERE = pathlib.Path(__file__).resolve().parent


def test_gap_past_both_legs(run_scenario):
    run_scenario(HERE)

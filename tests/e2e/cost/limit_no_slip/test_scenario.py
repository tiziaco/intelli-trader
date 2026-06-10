"""Leaf test for COST-05 (limit-no-slip proof).

The ONLY allowed body: delegate to the shared ``run_scenario`` harness with this
leaf's own directory. The harness owns build -> run -> read -> assemble ->
diff-what's-frozen (incl. the always-on ``commission`` column); the leaf adds NO
assert/diff logic of its own.
"""

import pathlib

HERE = pathlib.Path(__file__).resolve().parent


def test_limit_no_slip(run_scenario):
    run_scenario(HERE)

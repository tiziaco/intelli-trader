"""Leaf test for ADMIT-02 (partial scale-out via exit_fraction < 1).

The ONLY allowed body: delegate to the shared ``run_scenario`` harness with this
leaf's own directory. The harness owns build -> run -> read -> assemble ->
diff-what's-frozen; the leaf adds NO assert/diff logic of its own.
"""

import pathlib

HERE = pathlib.Path(__file__).resolve().parent


def test_scale_out(run_scenario):
    run_scenario(HERE)

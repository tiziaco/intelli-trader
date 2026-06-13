"""Leaf test for the D-07 crafted LIMIT-entry cross-val scenario.

The ONLY allowed body: delegate to the shared ``run_scenario`` harness with this
leaf's own directory. The harness owns build -> run -> read -> assemble ->
diff-what's-frozen; the leaf adds NO assert/diff logic of its own.

PENDING GOLDEN (D-07 owner gate): the frozen ``golden/`` (trades.csv + summary.json)
is written ONLY after explicit owner sign-off (Plan 05-04 Task 3 — the
``checkpoint:human-verify`` blocking-human gate). Until then the diff has no golden to
compare against, so this test is marked ``xfail`` with a strict=False reason. Task 3
freezes the golden AND removes this ``xfail`` marker so the leaf turns green.
"""

import pathlib

import pytest

HERE = pathlib.Path(__file__).resolve().parent

_GOLDEN = HERE / "golden"


@pytest.mark.xfail(
    not (_GOLDEN / "trades.csv").exists(),
    reason="D-07 golden frozen only after owner sign-off (Plan 05-04 Task 3)",
    strict=False,
)
def test_limit_entry_crossval(run_scenario):
    run_scenario(HERE)

"""ACCT-06 static gate: no docstring or comment under ``itrader/execution_handler``
or ``itrader/core`` may assert the phantom invariant that plan 11-08 makes a
portfolio's venue-account id a required/composition-time property.

Why a static gate. ACCT-06 is a PROSE correction with no runtime behaviour to
assert — no test run can cover it. The phantom claim ("plan 11-08 makes the
account id a hard composition-time property") is false: plan 11-08's invariant
is the DISTINCT-account guarantee (``assert_distinct_accounts``), which
explicitly PERMITS a portfolio to name no account. What actually requires a live
order's portfolio to name a provisioned account is the venue-layer ACCT-03
guard, resolved elsewhere. A decision-anchored docstring asserting the phantom is
exactly how the underlying gap survived the last review, so this gate fails loud
if the claim is reintroduced.

The searched literals are assembled from fragments so the phantom phrase never
appears verbatim in this file — the gate cannot be self-invalidated by its own
prose, and (belt-and-braces) the ``tests/`` tree it lives in is not scanned.
"""

from pathlib import Path

import pytest

import itrader

# --- searched literals, assembled from parts (never verbatim here) ------------
_PLAN = "11" + "-08"                       # the plan tag the phantom cites
_MANDATE = "mandat" + "ory"                # the operative phantom token
_PROXIMITY = 180                           # chars around a citation to inspect

_ROOTS = ("execution_handler", "core")


def _normalize(text: str) -> str:
    """Lowercase, strip ``#`` comment markers, and collapse all whitespace.

    Comment markers are stripped so a citation reads the same whether it lives
    in a ``#`` comment or a triple-quoted docstring; whitespace is collapsed so
    a claim split across wrapped lines is still one contiguous string.
    """
    return " ".join(text.replace("#", " ").lower().split())


def _scoped_py_files() -> list[Path]:
    pkg_root = Path(itrader.__file__).resolve().parent
    files: list[Path] = []
    for root in _ROOTS:
        files.extend(sorted((pkg_root / root).rglob("*.py")))
    assert files, "no source files discovered — scope roots may be wrong"
    return files


def test_no_surviving_phantom_invariant_citation() -> None:
    """Near every ``11-08`` citation, the phantom mandate token is absent."""
    offenders: list[str] = []
    for path in _scoped_py_files():
        norm = _normalize(path.read_text(encoding="utf-8"))
        start = 0
        while (idx := norm.find(_PLAN, start)) != -1:
            window = norm[max(0, idx - _PROXIMITY): idx + _PROXIMITY]
            if _MANDATE in window:
                offenders.append(f"{path}: '...{window}...'")
            start = idx + len(_PLAN)
    assert not offenders, (
        "phantom-invariant citation reintroduced — a "
        f"{_PLAN} citation asserts the {_MANDATE} claim:\n" + "\n".join(offenders)
    )


def test_distinct_account_sentence_survives_in_read_model() -> None:
    """The ACCURATE distinct-account sentence must NOT be deleted under an
    ACCT-06 sweep — only its phantom implication was corrected."""
    pkg_root = Path(itrader.__file__).resolve().parent
    norm = _normalize(
        (pkg_root / "core" / "portfolio_read_model.py").read_text(encoding="utf-8"))
    assert "distinct" in norm and _PLAN in norm, (
        "the accurate distinct-account citation was lost from "
        "portfolio_read_model.py — it must be rewritten, not deleted")


def test_gate_would_catch_a_reintroduced_phantom() -> None:
    """Self-check: the proximity+token rule DOES fire on a phantom sample, so a
    passing gate is meaningful rather than vacuous."""
    sample = _normalize(
        f"Plan {_PLAN} owns the composition-time invariant that makes "
        f"account_id {_MANDATE} in live.")
    idx = sample.find(_PLAN)
    window = sample[max(0, idx - _PROXIMITY): idx + _PROXIMITY]
    assert _MANDATE in window

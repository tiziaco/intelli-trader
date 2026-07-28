"""Static gate for the ACCT-04 account-identity coercion disposition (WR-03, RESEARCH §F-3).

WHY A STATIC GATE. Deletion completeness is a STATIC property that no passing test
suite can prove: a test exercises the paths it happens to reach, but "no live-path code
anywhere coerces an unnamed account onto a default key" is a statement about the whole
source tree, not about any one execution. Worse, the one place a live cross-account
misroute would surface end-to-end — ``tests/e2e/test_okx_sandbox_recon.py`` — is
credential-SKIPPED in CI (RESEARCH §Common Pitfalls, Pitfall 5), so a green run proves
NOTHING about it. This gate reads the source directly instead.

WHAT IT PINS (two halves, mirroring ``tests/integration/test_okx_inertness.py``).

(a) NEGATIVE half — no live-path coercion survives. WR-03's asymmetry is that
registration wrote ``(venue, <default>)`` while both reader sides constructed
``(venue, None)`` raw, so an unnamed account's registered key was unreachable by every
reader. Deleting SOME coercions while leaving others does not dissolve that — it
RELOCATES it. So the gate asserts ZERO account-identity coercions remain anywhere under
``itrader/venues/`` or in ``itrader/trading_system/live_trading_system.py``.

(b) POSITIVE half — the backtest single-account identity is STILL present. The kept
uses in ``execution_handler`` / ``backtest_trading_system`` / ``universe_wiring`` (and the
paper lookup in ``live_trading_system``) are load-bearing for the golden oracle: deleting
one changes backtest numbers. Recorded as expected per-file counts so a future sweep that
removes a backtest-identity use fails HERE rather than silently re-baselining the oracle.

HOW IT READS SOURCE — by parsing the file CONTENTS with ``ast`` IN-PROCESS (nothing is
shelled out, so the gate works in any checkout). The AST approach is what lets the negative
half exclude DOCSTRINGS and COMMENTS without excluding whole files: a coercion is a real
``X or <default>`` boolean expression in code, whereas ``itrader/venues/bundles.py``'s
key-discipline docstring MENTIONS the idiom as the governing rule and must be KEPT. A
string literal inside a docstring is an ``ast.Constant`` expression statement, never a
``BoolOp``, so it cannot trip the negative half — and the counts in the positive half are
``ast.Name`` uses, which ignore imports, docstrings and comments alike.

This file lives at the TOP LEVEL of ``tests/unit/`` (no ``__init__.py`` collision hazard,
per MEMORY: two same-named top-level test packages break full-suite collection). Its
folder-derived marker is ``unit``.
"""

from __future__ import annotations

import ast
import pathlib

# The coercion target, built by construction rather than written as one literal token so
# the gate describes what it forbids in prose without reproducing a grep-able idiom in a
# source comment (the ACCT-04 comment-text discipline). Both forms are equivalent: the
# ``registry`` module binds this name to the string on the right.
_COERCION_IDENT = "DEFAULT_ACCOUNT" + "_ID"
_COERCION_DEFAULT_STR = "default"

# Repo root: this file is tests/unit/<name>.py, so the tree root is two parents up.
_ROOT = pathlib.Path(__file__).resolve().parents[2]

# The live root scanned alongside the venues package. compose.py is deliberately NOT
# scanned here: after 11.2-03 it holds no code-level DEFAULT_ACCOUNT_ID at all (only two
# docstring references), so there is nothing for the negative half to protect there.
_LIVE_ROOT = _ROOT / "itrader" / "trading_system" / "live_trading_system.py"
_VENUES_DIR = _ROOT / "itrader" / "venues"

# POSITIVE half — the backtest single-account identity uses, measured at execution time
# (11.2-10). These are the KEPT sites: the backtest "no read-model injected -> default"
# return arm and the backtest (venue, account) pair keys. A sweep that removes one changes
# the golden oracle, so the gate fails if any count drops. Counts are ``ast.Name`` uses,
# which exclude the ``from ... import DEFAULT_ACCOUNT_ID`` line and every docstring mention.
_BACKTEST_IDENTITY_COUNTS = {
    "itrader/execution_handler/execution_handler.py": 6,
    "itrader/trading_system/backtest_trading_system.py": 1,
    "itrader/trading_system/universe_wiring.py": 2,
    # The (COMPUTE_VENUE, DEFAULT_ACCOUNT_ID) paper lookup in the live file (survives
    # D-35) — an account-identity coercion it is NOT, so it is a KEPT use, not a swept one.
    "itrader/trading_system/live_trading_system.py": 1,
}


def _parse(path: pathlib.Path) -> ast.Module:
    """Parse a source file's CONTENTS in-process (nothing shelled out — any checkout)."""
    return ast.parse(path.read_text(), filename=str(path))


def _coercion_count(tree: ast.Module) -> int:
    """Number of real ``X or <default>`` account-identity coercions in CODE.

    Counts a boolean ``or`` whose right operand is either the ``DEFAULT_ACCOUNT_ID`` name
    or the literal ``"default"`` string. Docstrings and comments cannot match: a string in
    a docstring is a bare ``ast.Constant`` expression, never a ``BoolOp`` — which is why
    ``bundles.py``'s key-discipline docstring (kept, on purpose) does not trip this.
    """
    hits = 0
    for node in ast.walk(tree):
        if not (isinstance(node, ast.BoolOp) and isinstance(node.op, ast.Or)):
            continue
        for value in node.values:
            if isinstance(value, ast.Name) and value.id == _COERCION_IDENT:
                hits += 1
            elif isinstance(value, ast.Constant) and value.value == _COERCION_DEFAULT_STR:
                hits += 1
    return hits


def _name_uses(tree: ast.Module) -> int:
    """Number of ``DEFAULT_ACCOUNT_ID`` NAME uses in code (imports/docstrings excluded)."""
    return sum(
        1
        for node in ast.walk(tree)
        if isinstance(node, ast.Name) and node.id == _COERCION_IDENT
    )


def _venue_sources() -> list[pathlib.Path]:
    """Every Python module under ``itrader/venues/`` (the negative-half scan set)."""
    return sorted(_VENUES_DIR.rglob("*.py"))


# --------------------------------------------------------------------------- #
# (a) NEGATIVE half — no live-path account-identity coercion survives
# --------------------------------------------------------------------------- #
def test_no_account_identity_coercion_survives_under_venues() -> None:
    """ACCT-04/WR-03: zero ``X or DEFAULT_ACCOUNT_ID`` coercions anywhere in venues/.

    Every deleted read-side coercion (assemble, the two okx_plugin memo keys, the venue-UID
    guard) is a place the write side and the read side could disagree about the same real
    account. A partial deletion RELOCATES the asymmetry rather than closing it, so the gate
    demands the whole package be clean — not merely the sites the requirement named.
    """
    offenders = {
        str(path.relative_to(_ROOT)): _coercion_count(_parse(path))
        for path in _venue_sources()
    }
    offenders = {rel: n for rel, n in offenders.items() if n}
    assert offenders == {}, (
        "ACCT-04/WR-03 violation: a live-path account-identity coercion returned under "
        f"itrader/venues/ — {offenders}. An unnamed account must RAISE, never be coerced "
        "onto a default key (registration-side and resolution-side defaults are not "
        "symmetric; normalizing in two places is how the exchange registry and the "
        "connector memo end up disagreeing about the same real account)."
    )


def test_no_account_identity_coercion_survives_in_the_live_root() -> None:
    """ACCT-04: the live composition root carries no account-identity coercion either.

    The live root is scanned alongside the venues package because a "repair" coercion is
    just as damaging there. The kept ``(COMPUTE_VENUE, DEFAULT_ACCOUNT_ID)`` paper lookup is
    NOT a coercion (no ``or``), so it is invisible to this half and asserted present by the
    positive half instead.
    """
    assert _coercion_count(_parse(_LIVE_ROOT)) == 0, (
        "ACCT-04 violation: live_trading_system.py grew an `X or DEFAULT_ACCOUNT_ID` "
        "account-identity coercion — the live root must construct the (venue, account_id) "
        "pair from the row's own id, never a default."
    )


def test_the_negative_half_would_catch_a_reintroduced_coercion() -> None:
    """The negative half is not vacuous: a synthetic coercion IS detected.

    Parses a source fragment carrying the exact idiom and asserts the counter fires. This
    proves the gate would redden if a real coercion returned, without mutating any tracked
    file (the plan verifies the same property once by hand against assemble.py + reverts).
    """
    fragment = f"account_id = spec.account_id or {_COERCION_IDENT}\n"
    assert _coercion_count(ast.parse(fragment)) == 1

    string_form = f'account_id = spec.account_id or "{_COERCION_DEFAULT_STR}"\n'
    assert _coercion_count(ast.parse(string_form)) == 1

    # A docstring MENTIONING the idiom (bundles.py's kept key-discipline rule) must NOT
    # trip the gate — it is a Constant expression, never a BoolOp.
    docstring_form = f'"""callers apply spec.account_id or {_COERCION_IDENT} first."""\n'
    assert _coercion_count(ast.parse(docstring_form)) == 0


# --------------------------------------------------------------------------- #
# (b) POSITIVE half — the backtest single-account identity is still present
# --------------------------------------------------------------------------- #
def test_the_backtest_single_account_identity_is_still_present() -> None:
    """ACCT-04: the KEPT backtest-identity uses survive, at their measured counts.

    These are the ``DEFAULT_ACCOUNT_ID`` uses ACCT-04 PRESERVES — the backtest single
    account identity, load-bearing for the golden oracle (134 / 46189.87730727451).
    Deleting one would change backtest numbers under a green suite, so a future sweep that
    removes a backtest-identity use fails HERE rather than silently re-baselining the
    oracle. This is the strictly-stronger positive assertion the inertness gate pairs with
    its forbidden-name list.
    """
    actual = {
        rel: _name_uses(_parse(_ROOT / rel)) for rel in _BACKTEST_IDENTITY_COUNTS
    }
    assert actual == _BACKTEST_IDENTITY_COUNTS, (
        "ACCT-04 violation: a backtest single-account-identity DEFAULT_ACCOUNT_ID use was "
        f"removed (or added). Expected {_BACKTEST_IDENTITY_COUNTS}, got {actual}. These "
        "uses are the backtest identity — deleting one changes the golden oracle; if a use "
        "was added deliberately, update the recorded count."
    )

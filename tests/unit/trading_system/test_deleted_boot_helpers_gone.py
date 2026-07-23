"""Static gate — the six deleted store-derivation boot helpers never return (11.2-07).

11.2-07 deleted the six ``live_trading_system.py`` helpers that derived and minted account
identity at boot; ``VenueAccountManager`` (store-derived) replaces them. This gate fails if
ANY of the six names reappears as a live CODE reference anywhere under ``itrader/`` or
``tests/``.

**Why a static gate, and why it scans SOURCE rather than trusting the suite.** Two of the
53 original references live in ``tests/e2e/test_okx_sandbox_recon.py``, which is
credential-SKIPPED in CI — a green suite proves nothing about it. And
``live_trading_system.py`` is under a mypy ``ignore_errors`` override, so a dead reference
there passes both mypy and the suite silently. A source scan is the only gate that sees
both.

**Why it tokenizes rather than greps.** The deleted names still appear in explanatory
COMMENTS and DOCSTRINGS across the tree (they describe what was removed and why). Those are
not live references. Tokenizing and inspecting only ``NAME`` tokens ignores comments and
string literals, so the gate catches a genuine identifier use (import, call, ``def``,
attribute access) while tolerating the historical prose — exactly the "scope the grep to
code lines" resolution the plan calls for.
"""

from __future__ import annotations

import pathlib
import tokenize

#: The six helpers deleted from ``live_trading_system.py`` in 11.2-07 (Task 1).
_DELETED_NAMES = frozenset({
    "_account_ids_for_spec",
    "_mint_account_rows",
    "_build_account_specs",
    "_attach_venue_accounts",
    "_venue_of",
    "_read_account_secret_ref",
})

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
_SCAN_ROOTS = (_REPO_ROOT / "itrader", _REPO_ROOT / "tests")
_THIS_FILE = pathlib.Path(__file__).resolve()


def _code_name_hits(path: pathlib.Path) -> list[tuple[int, str]]:
    """Every ``NAME`` token in ``path`` that is one of the deleted names (comments/strings skipped)."""
    hits: list[tuple[int, str]] = []
    with path.open("rb") as handle:
        try:
            tokens = list(tokenize.tokenize(handle.readline))
        except (tokenize.TokenError, SyntaxError):
            return hits  # a non-parseable file is out of scope for this gate
    for token in tokens:
        if token.type == tokenize.NAME and token.string in _DELETED_NAMES:
            hits.append((token.start[0], token.string))
    return hits


def test_the_six_deleted_boot_helpers_never_return_as_code() -> None:
    """No live code reference to any of the six deleted boot helpers survives (11.2-07)."""
    offenders: list[str] = []
    for root in _SCAN_ROOTS:
        for path in root.rglob("*.py"):
            if path.resolve() == _THIS_FILE:
                continue  # the gate names them as string literals, not code
            for line_no, name in _code_name_hits(path):
                offenders.append(f"{path.relative_to(_REPO_ROOT)}:{line_no}: {name}")

    assert not offenders, (
        "a deleted 11.2-07 boot helper returned as live code — the store-derived boot "
        "(VenueAccountManager) replaced these; they must not be reintroduced:\n  "
        + "\n  ".join(offenders))

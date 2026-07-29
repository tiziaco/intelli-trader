#!/usr/bin/env python
"""Measure the venue/account redesign source-size yardstick (design §2.3).

The redesign's must-have is a sign, not a style opinion: the successor source must be
strictly smaller than the shape it replaces. That is only checkable if both sides are
counted by the SAME rule, so the rule lives here in code rather than in prose:

  * **raw lines** — every line in the file, exactly what ``grep -c ''`` reports.
  * **code lines** — non-blank lines that are neither comments nor inside ANY docstring
    (module, class *or* function). A comment line is one whose only non-whitespace
    content is a comment; a trailing ``# ...`` on a statement leaves that line code.

Docstring ranges come from ``ast`` (the line span of each docstring node) and comment
positions from ``tokenize`` — never a regex, because a ``#`` inside a string literal and a
triple-quoted expression that is *not* in docstring position both defeat pattern matching
and both occur in this codebase.

Tests are excluded from the metric by construction: the manifest lists source files only.
That exclusion is a requirement, not a convenience — the fix for the root cause of all
four Criticals is *more* test code, so a metric counting tests would reward skipping the
very tests whose absence caused them.

Usage::

    poetry run python scripts/measure_redesign_baseline.py
    poetry run python scripts/measure_redesign_baseline.py --manifest <file>

With no ``--manifest`` the hard-coded 27-file baseline manifest below is measured, and at
the pre-redesign HEAD it must print 27 files / 9,243 raw / 3,886 code. ``--manifest``
takes a newline-delimited list of repo-relative paths (``#`` comments and blank lines
ignored) and is how the successor set is measured in the final stage.
"""

from __future__ import annotations

import argparse
import ast
import io
import pathlib
import sys
import tokenize

# The pre-redesign baseline: the 19 paths named in the requirements' Scope block, plus the
# eight modules the redesign provably rewrites or deletes that Scope did not enumerate
# (the venue-account manager and its TOFU guard, the connector and its stream supervisor,
# and the four account leaves). Hard-coded rather than globbed so the yardstick cannot
# drift as directories gain files.
BASELINE_MANIFEST: tuple[str, ...] = (
    "itrader/trading_system/compose.py",
    "itrader/trading_system/backtest_trading_system.py",
    "itrader/trading_system/live_trading_system.py",
    "itrader/trading_system/venue_spec.py",
    "itrader/trading_system/session_initializer.py",
    "itrader/portfolio_handler/portfolio_factory.py",
    "itrader/connectors/provider.py",
    "itrader/connectors/base.py",
    "itrader/venues/lifecycle.py",
    "itrader/venues/feed_binder.py",
    "itrader/venues/paper_plugin.py",
    "itrader/venues/okx_plugin.py",
    "itrader/venues/assemble.py",
    "itrader/venues/bundle.py",
    "itrader/venues/bundles.py",
    "itrader/venues/registry.py",
    "itrader/storage/venue_store.py",
    "itrader/storage/venue_account_store.py",
    "itrader/storage/portfolio_definition_store.py",
    "itrader/venues/venue_account_manager.py",
    "itrader/venues/venue_uid_guard.py",
    "itrader/connectors/okx.py",
    "itrader/connectors/stream_supervisor.py",
    "itrader/portfolio_handler/account/base.py",
    "itrader/portfolio_handler/account/conformance.py",
    "itrader/portfolio_handler/account/simulated.py",
    "itrader/portfolio_handler/account/venue.py",
)

_DOCSTRING_OWNERS = (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)


def docstring_lines(source: str) -> set[int]:
    """Return every 1-based line number that falls inside a docstring.

    A docstring is a string-constant expression in the FIRST statement position of a
    module, class or function body — the same definition ``ast.get_docstring`` uses. A
    triple-quoted string anywhere else is an expression, and its lines count as code.
    """
    lines: set[int] = set()
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, _DOCSTRING_OWNERS):
            continue
        if not node.body:
            continue
        first = node.body[0]
        if not isinstance(first, ast.Expr):
            continue
        if not isinstance(first.value, ast.Constant) or not isinstance(first.value.value, str):
            continue
        end = first.end_lineno if first.end_lineno is not None else first.lineno
        lines.update(range(first.lineno, end + 1))
    return lines


def comment_lines(source: str) -> set[int]:
    """Return every 1-based line number that is a whole-line comment.

    The token's start column is checked against the text before it: a trailing comment on
    a statement leaves that line code, while an indented ``#`` on its own does not.
    """
    lines: set[int] = set()
    physical = source.splitlines()
    readline = io.StringIO(source).readline
    for token in tokenize.generate_tokens(readline):
        if token.type is not tokenize.COMMENT:
            continue
        row, col = token.start
        if physical[row - 1][:col].strip() == "":
            lines.add(row)
    return lines


def measure(path: pathlib.Path) -> tuple[int, int]:
    """Return ``(raw_lines, code_lines)`` for one source file."""
    source = path.read_text(encoding="utf-8")
    physical = source.splitlines()
    excluded = docstring_lines(source) | comment_lines(source)
    code = sum(
        1
        for number, text in enumerate(physical, start=1)
        if text.strip() and number not in excluded
    )
    return len(physical), code


def read_manifest(path: pathlib.Path) -> tuple[str, ...]:
    """Read a newline-delimited manifest, dropping blank lines and ``#`` comments."""
    entries = []
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            entries.append(stripped)
    return tuple(entries)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--manifest",
        type=pathlib.Path,
        default=None,
        help="file listing repo-relative source paths (default: the baseline manifest)",
    )
    parser.add_argument(
        "--repo-root",
        type=pathlib.Path,
        default=pathlib.Path(__file__).resolve().parent.parent,
        help="repository root the manifest paths are relative to",
    )
    args = parser.parse_args(argv)

    manifest = read_manifest(args.manifest) if args.manifest else BASELINE_MANIFEST
    label = str(args.manifest) if args.manifest else "baseline (hard-coded)"

    missing = [entry for entry in manifest if not (args.repo_root / entry).is_file()]
    if missing:
        print(f"ERROR: {len(missing)} manifest path(s) do not exist:", file=sys.stderr)
        for entry in missing:
            print(f"  {entry}", file=sys.stderr)
        return 1

    rows = [(entry, *measure(args.repo_root / entry)) for entry in manifest]
    raw_total = sum(row[1] for row in rows)
    code_total = sum(row[2] for row in rows)

    print(f"manifest: {label}")
    print(f"{'raw':>7} {'code':>7}  path")
    for entry, raw, code in sorted(rows, key=lambda row: -row[2]):
        print(f"{raw:>7} {code:>7}  {entry}")
    print(f"{'-' * 7} {'-' * 7}")
    print(f"{raw_total:>7} {code_total:>7}  TOTAL over {len(rows)} files")
    print()
    print(f"files: {len(rows)} | raw: {raw_total} | code: {code_total}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

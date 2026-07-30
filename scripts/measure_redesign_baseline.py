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

**The baseline is a frozen NUMBER, not a re-measurement.** Measuring the hard-coded
manifest reproduces 27 files / 9,243 raw / 3,886 code only at the pre-redesign HEAD. Once
the refactor starts relocating code, that manifest necessarily under-reports: a line that
moves from ``live_trading_system.py`` into a new module leaves the measured set without
being deleted. Comparing a mutated tree against the baseline manifest would therefore make
the must-have look satisfied by relocation alone — the exact false-green this script exists
to prevent. The frozen totals are pinned in ``BASELINE_TOTALS`` and the script says so
loudly when the default manifest stops matching them.

The real gate runs against a SUCCESSOR manifest — every file that replaces, absorbs or
renames one of the 27, plus every module the redesign introduces — and is a comparison
against the frozen number:

    poetry run python scripts/measure_redesign_baseline.py \\
        --manifest scripts/redesign_successor_manifest.txt

That form exits non-zero unless the successor code total is strictly below the frozen
baseline, so the must-have is a command with an exit code rather than a judgement call.

**Both sides must count the SAME file set, and the 27 do not.** Several recipes landed in
host files that predate the redesign — ``snapshot()`` and ``build_okx_exchange`` in
``execution_handler/exchanges/okx.py``, ``build_okx_data_provider`` in
``price_handler/providers/okx_provider.py`` — while the modules they replaced
(``account/venue.py``, ``feed_binder.py``, the plugin ``build_*`` methods) WERE among the
27. Those lines were counted leaving and not counted arriving, which is the §3.1 false-green
one level up: not "relocation drops lines from the measured set" but "the measured set never
included the destinations". Measured concretely, the four hosts grew 1,182 -> 1,334 code
lines while the 27-file total appeared to fall 3,886 -> 3,852.

So the yardstick is the EXTENDED set — the 27 plus those four hosts — pinned in
``EXTENDED_BASELINE_TOTALS`` and measured at the same frozen commit. ``BASELINE_TOTALS``
stays untouched as the historical record of what the original Scope block measured.
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
    "itrader/trading_system/backtest/backtest_trading_system.py",
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

# What BASELINE_MANIFEST measured at the pre-redesign HEAD (commit 3a2c7692), as
# (files, raw, code). Pinned as data because it is a historical fact about one commit. It is
# the record of what the requirements' Scope block covered — NOT the gate's comparand; see
# EXTENDED_BASELINE_TOTALS for why.
BASELINE_TOTALS = (27, 9243, 3886)

#: The four host files that ABSORBED redesign code without being in the baseline set. Each
#: took a recipe or contract whose predecessor WAS among the 27, so counting the 27 alone
#: credits the deletion and hides the arrival.
RECIPE_HOSTS: tuple[str, ...] = (
    "itrader/execution_handler/exchanges/base.py",
    "itrader/execution_handler/exchanges/okx.py",
    "itrader/execution_handler/exchanges/simulated.py",
    "itrader/price_handler/providers/okx_provider.py",
)

# The GATE's comparand: BASELINE_MANIFEST + RECIPE_HOSTS, measured at the same frozen
# commit 3a2c7692, as (files, raw, code). Reproduce it with:
#
#   git show 3a2c7692:<path>  for each of the 31 paths, counted by this module's own rule
#
# The successor manifest must therefore also list RECIPE_HOSTS — the gate below asserts it
# does, because an extended baseline compared against a 27-file successor set would be the
# same asymmetry with the sign flipped.
EXTENDED_BASELINE_TOTALS = (31, 11684, 5068)

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
        "--gate",
        action="store_true",
        help="exit non-zero unless the measured code total is strictly below the frozen "
             "baseline (the final must-have check; mid-refactor runs omit it, since the "
             "sign is only required to be negative once the deletions have landed)",
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
    if missing and args.manifest is not None:
        # A supplied manifest names the CURRENT set, so an absent path is a typo or a stale
        # entry, and silently counting it as zero would flatter the total.
        print(f"ERROR: {len(missing)} manifest path(s) do not exist:", file=sys.stderr)
        for entry in missing:
            print(f"  {entry}", file=sys.stderr)
        return 1
    if missing:
        # The hard-coded baseline names a HISTORICAL set, and the redesign deletes from it
        # by design. An absent path here is the intended outcome, not a fault — it
        # contributes zero and is reported so the historical run stays readable.
        print(f"NOTE: {len(missing)} baseline path(s) have since been deleted:")
        for entry in missing:
            print(f"  (deleted) {entry}")
        print()

    rows = [
        (entry, *measure(args.repo_root / entry))
        for entry in manifest
        if (args.repo_root / entry).is_file()
    ]
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

    baseline_files, baseline_raw, baseline_code = BASELINE_TOTALS
    if args.manifest is None:
        if (len(rows), raw_total, code_total) != BASELINE_TOTALS:
            print()
            print(
                "NOTE: the baseline manifest no longer reproduces the frozen totals "
                f"({baseline_files} / {baseline_raw} / {baseline_code}). That is expected "
                "once the refactor relocates code: a line moved into a NEW module leaves "
                "this manifest without being deleted, so this total is NOT the yardstick. "
                "Measure the successor manifest instead.")
        return 0

    # An extended baseline compared against a successor set that omits the recipe hosts is
    # the original asymmetry with its sign flipped, and it would flatter the result by the
    # hosts' entire weight. Refuse BEFORE reporting a delta built that way — a printed
    # number is read and remembered even when the run exits non-zero.
    absent_hosts = [host for host in RECIPE_HOSTS if host not in manifest]
    if absent_hosts:
        print(
            "ERROR: the comparand is the EXTENDED baseline (the 27 Scope files plus the "
            f"recipe hosts), but this manifest omits {len(absent_hosts)} host(s):",
            file=sys.stderr)
        for host in absent_hosts:
            print(f"  {host}", file=sys.stderr)
        print(
            "Both sides must count the same file set — add them, or the delta credits "
            "each deletion without counting where the code went.", file=sys.stderr)
        return 1

    # Compared against the frozen EXTENDED number so both sides count the same file set.
    _, _, extended_code = EXTENDED_BASELINE_TOTALS
    delta = code_total - extended_code
    print(f"frozen baseline code: {extended_code} | delta: {delta:+d}")

    if not args.gate:
        return 0
    if delta >= 0:
        print(
            "GATE FAILED: the successor set is not strictly smaller than the baseline "
            f"({code_total} >= {extended_code}). The refactor must delete more source "
            "than it adds.", file=sys.stderr)
        return 1
    print(f"GATE PASSED: {-delta} fewer code lines than the frozen baseline.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

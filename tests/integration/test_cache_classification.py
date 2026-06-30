"""SC2 grep-matches-inventory check — the Nyquist Wave-0 anchor (Phase 5, plan 05-01).

This is the runnable, drift-proof half of the D-01 dual home: it makes
``docs/CACHE-CLASSIFICATION.md`` the single source of truth for the live cache surface
and cross-checks it against a fresh grep of ``itrader/`` at HEAD. It enforces:

  * the applied-decorator surface is EXACTLY the 3 documented sites
    (``@functools.cache`` bar_feed / ``@functools.lru_cache`` time_parser / ``@cache`` base.py);
  * every ad-hoc ``self._cache`` / position / to_dict cache field maps to a documented site
    (no surprise, undocumented cache);
  * the ``# CACHE-CLASS:`` per-site anchors enumerated in ``itrader/`` equal the live-site
    count the doc declares (D-01 home #2);
  * the doc records the Q7 no-Arrow decision and the ``(d)`` live-retention label.

GREEN at HEAD (Wave-0 RED->GREEN sequence is complete): plan **05-02** placed the
per-site ``# CACHE-CLASS:`` annotations, so the
``test_cache_class_anchors_match_live_inventory`` arm now passes and locks the live
anchor count to the doc inventory. All four arms pass against the committed doc.

Uses pathlib + re only (no subprocess, no third-party import) so it emits no warnings under
``filterwarnings=["error"]`` and never triggers the ``itrader`` import-time singletons.
The inventory is read FROM ``docs/CACHE-CLASSIFICATION.md`` — the doc drives the check.
"""

import re
from pathlib import Path

# This file lives at <repo>/tests/integration/ ; parents[2] is the repo root.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_ITRADER = _REPO_ROOT / "itrader"
_DOC_PATH = _REPO_ROOT / "docs" / "CACHE-CLASSIFICATION.md"

# A site token is a "<path>.py:<line>" reference (relative to itrader/, no prefix).
_SITE_RE = re.compile(r"([A-Za-z0-9_./-]+\.py):(\d+)")
# Applied (not merely mentioned) memoization decorators: a line that STARTS (after
# optional indent) with the decorator '@'. Comment mentions begin with '#' and are excluded.
_DECORATOR_RE = re.compile(r"^[ \t]*@(?:functools\.)?(?:lru_cache|cache)\b")
# Ad-hoc cache fields — require the `self.` receiver so prose/docstring mentions
# (e.g. ``_net_quantity_cache`` inside a sql_storage docstring) are not counted.
_FIELD_RE = re.compile(
    r"self\._cache\b|self\._net_quantity_cache|self\._avg_price_cache|self\._to_dict_static_cache"
)
# The per-site drift anchor that plan 05-02 places on each live definition line.
_ANCHOR_RE = re.compile(r"#\s*CACHE-CLASS:")


def _doc_text() -> str:
    assert _DOC_PATH.is_file(), f"committed map missing: {_DOC_PATH}"
    return _DOC_PATH.read_text(encoding="utf-8")


def _live_inventory() -> dict[str, set[int]]:
    """Parse the doc's machine-readable live-site anchor block into {path: {lines}}.

    This fenced block (NOT the removed/superseded rows) is the canonical list of live
    anchor sites that 05-02 annotates. Making the doc the source of truth means a new
    cache must be added here before the grep arms can pass.
    """
    doc = _doc_text()
    m = re.search(
        r"## Machine-readable live-site anchor inventory.*?```text\n(.*?)```",
        doc,
        re.S,
    )
    assert m, "machine-readable live-site anchor block not found in the committed doc"
    inventory: dict[str, set[int]] = {}
    for line in m.group(1).splitlines():
        token = _SITE_RE.match(line.strip())
        if token:
            inventory.setdefault(token.group(1), set()).add(int(token.group(2)))
    assert inventory, "no live `path:line` sites parsed from the anchor block"
    return inventory


def _rel_to_itrader(path: Path) -> str:
    """itrader/<...>/x.py -> <...>/x.py (the doc's prefix-less token form)."""
    return path.relative_to(_ITRADER).as_posix()


def _scan_itrader(pattern: re.Pattern[str], *, whole_file: bool) -> list[tuple[str, int]]:
    """Return (rel_path, line_no) for every match of `pattern` under itrader/.

    whole_file=True searches the file body (field surface); otherwise matches per-line
    against the line start (decorator / anchor surfaces).
    """
    hits: list[tuple[str, int]] = []
    for py in sorted(_ITRADER.rglob("*.py")):
        rel = _rel_to_itrader(py)
        text = py.read_text(encoding="utf-8")
        if whole_file:
            for i, line in enumerate(text.splitlines(), 1):
                if pattern.search(line):
                    hits.append((rel, i))
        else:
            for i, line in enumerate(text.splitlines(), 1):
                if pattern.match(line):
                    hits.append((rel, i))
    return hits


# --------------------------------------------------------------------------- arm 1+2


def test_applied_decorator_surface_is_exactly_three_documented_sites() -> None:
    """The memoization-decorator surface is exactly #1/#2/#3 and each is in the doc."""
    inventory = _live_inventory()
    applied = _scan_itrader(_DECORATOR_RE, whole_file=False)

    files = {f for f, _ in applied}
    assert len(applied) == 3, (
        f"expected exactly 3 applied memoization decorators (bar_feed/time_parser/base.py), "
        f"found {len(applied)}: {applied}"
    )
    assert files == {
        "price_handler/feed/bar_feed.py",
        "outils/time_parser.py",
        "strategy_handler/base.py",
    }, f"decorator surface drifted from the documented sites: {sorted(files)}"
    for f, _ in applied:
        assert f in inventory, f"undocumented applied-decorator cache site: {f}"


def test_every_cache_field_maps_to_a_documented_site() -> None:
    """No surprise/undocumented ad-hoc `_cache` field exists outside the inventory."""
    inventory = _live_inventory()
    field_files = {f for f, _ in _scan_itrader(_FIELD_RE, whole_file=True)}
    assert field_files, "expected to find ad-hoc cache fields under itrader/"
    undocumented = sorted(f for f in field_files if f not in inventory)
    assert not undocumented, (
        f"cache field(s) present in code but absent from "
        f"docs/CACHE-CLASSIFICATION.md inventory: {undocumented}"
    )


# --------------------------------------------------------------------------- arm 4


def test_doc_records_q7_no_arrow_decision_and_d_label() -> None:
    """The committed map carries the Q7 no-Arrow decision and the (d)-class label."""
    doc = _doc_text()
    assert "(d) live-retention working-set cache" in doc, "(d)-class label missing"
    assert "Q7" in doc, "Q7 decision reference missing"
    assert "Arrow" in doc, "no-Arrow decision text missing"
    assert "classify, do not rewrite or unify" in doc, "scope boundary statement missing"


# --------------------------------------------------------------------------- arm 3 (GREEN)


def test_cache_class_anchors_match_live_inventory() -> None:
    """GREEN at HEAD: one `# CACHE-CLASS:` anchor per live inventoried site.

    Anchors were placed by plan 05-02; the Wave-0 RED->GREEN sequence is complete. This
    arm locks the per-site anchor count to the doc inventory so a dropped or stray anchor
    fails the suite. The other arms in this module also pass against the committed doc.
    """
    inventory = _live_inventory()
    expected = sum(len(lines) for lines in inventory.values())
    anchors = _scan_itrader(_ANCHOR_RE, whole_file=True)

    assert len(anchors) == expected, (
        f"CACHE-CLASS anchor count drifted from the doc inventory "
        f"({len(anchors)}/{expected}). 05-02 placed one anchor per live site; re-sync "
        f"the anchors and docs/CACHE-CLASSIFICATION.md so the counts match."
    )
    for f, _ in anchors:
        assert f in inventory, f"CACHE-CLASS anchor on an undocumented file: {f}"

"""Exact multi-line replacement with assert-exactly-one, applied atomically.

Import from a per-batch script:

    import sys
    sys.path.insert(0, ".claude/skills/comment-reduction/tools")
    import sub

    F = "itrader/<file>.py"
    S = []
    S.append(('''<exact old text>''', '''<new text>'''))
    sub.apply(F, S)

Every pattern must match EXACTLY ONCE. A miss aborts before anything is written, so a
failed batch leaves the file untouched — fix the pattern and re-run the whole batch.

Copy the old text VERBATIM out of the file, including tabs and trailing whitespace on
"blank" lines inside legacy docstrings. When a pattern will not match, dump the exact
bytes rather than guessing:

    python3 -c "
    lines = open('itrader/<file>.py').read().split(chr(10))
    [print(f'{i+1:4d} |{l}|') for i, l in enumerate(lines[700:730], 700)]"
"""
import pathlib


def apply(path, subs):
    p = pathlib.Path(path)
    text = p.read_text()
    for i, (old, new) in enumerate(subs):
        n = text.count(old)
        if n != 1:
            first = old.splitlines()[0][:90] if old.splitlines() else ""
            raise AssertionError(
                f"sub[{i}] matched {n} times (need exactly 1): {first!r}\n"
                f"  nothing written; the file is unchanged")
        text = text.replace(old, new)
    p.write_text(text)
    print(f"applied {len(subs)} subs to {path}")

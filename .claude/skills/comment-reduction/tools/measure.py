"""Prose/code ratio for one or more Python files, or a whole tree.

    python3 measure.py itrader/portfolio_handler/portfolio.py
    python3 measure.py --tree itrader          # repo-wide + densest remaining files

"Prose" = comment lines + every line of a standalone docstring. Blank lines are counted
separately and excluded from both, so `ratio` is prose against real code.
"""
import io
import pathlib
import sys
import tokenize


def measure(path):
    src = pathlib.Path(path).read_text()
    lines = src.split("\n")
    prose = set()
    for t in tokenize.generate_tokens(io.StringIO(src).readline):
        if t.type == tokenize.COMMENT:
            prose.add(t.start[0])
        elif t.type == tokenize.STRING and t.string.lstrip("rbfuRBFU")[:3] in ('"""', "'''"):
            for i in range(t.start[0], t.end[0] + 1):
                prose.add(i)
    empty = {i for i, line in enumerate(lines, 1) if not line.strip()}
    blank = len(empty - prose)
    code = len(lines) - len(prose) - blank
    return len(lines), len(prose), code, blank


def main(argv):
    if argv and argv[0] == "--tree":
        root = pathlib.Path(argv[1] if len(argv) > 1 else "itrader")
        total_prose = total_code = 0
        rows = []
        for p in sorted(root.rglob("*.py")):
            try:
                _, prose, code, _ = measure(p)
            except (SyntaxError, tokenize.TokenError, UnicodeDecodeError):
                continue
            if code < 30:
                continue
            total_prose += prose
            total_code += code
            rows.append((prose / code, prose, code, str(p)))
        ratio = total_prose / total_code if total_code else 0
        print(f"TREE {root}  prose={total_prose}  code={total_code}  ratio={ratio:.2f}\n")
        print("DENSEST:")
        for r, prose, code, f in sorted(rows, reverse=True)[:15]:
            print(f"  {r:5.2f}  prose={prose:5d} code={code:5d}  {f}")
        return

    for path in argv:
        total, prose, code, blank = measure(path)
        ratio = prose / code if code else 0
        print(f"{path}\n  total={total} prose={prose} code={code} blank={blank} "
              f"ratio={ratio:.2f}")


if __name__ == "__main__":
    main(sys.argv[1:])

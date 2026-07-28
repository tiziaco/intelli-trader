"""Prove a comment-reduction pass changed no code, by comparing ASTs against git HEAD.

    python3 verify.py itrader/<file>.py            # vs HEAD
    python3 verify.py itrader/<file>.py --base other/copy.py

Both sides are parsed and every module/class/function docstring is removed, so deleting
or rewriting a docstring is permitted while ANY change to an executable statement is
reported with the offending node.

AST comparison rather than a token stream on purpose: a token-level proof that
placeholder-substitutes docstrings also silently swallows string ANNOTATIONS
(`self.q: "Optional[Queue]" = None`), because they are strings following a colon.
The AST knows the difference.

CAVEAT: docstring removal is invisible here by design. `execution_handler/fee_model/`
reads `self.__doc__.split('\\n')[1]`, so those class docstrings are runtime data indexed
by line — this tool will NOT catch a change to them.

If a reported difference is not attributable to your own edits, replay your batch
scripts against a fresh `git show HEAD:<file>` copy and diff that against the working
tree. A concurrent editor save (organize-imports, formatter) is the usual cause.
Exit status is 1 on any difference.
"""
import argparse
import ast
import subprocess
import sys


def strip_docstrings(tree):
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef,
                             ast.ClassDef)):
            body = node.body
            if (body and isinstance(body[0], ast.Expr)
                    and isinstance(body[0].value, ast.Constant)
                    and isinstance(body[0].value.value, str)):
                node.body = body[1:] or [ast.Pass()]
    return tree


def nodes(src):
    return [ast.dump(n) for n in ast.walk(strip_docstrings(ast.parse(src)))]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("path")
    ap.add_argument("--base", help="compare against this file instead of git HEAD")
    args = ap.parse_args()

    if args.base:
        base_src = open(args.base).read()
        label = args.base
    else:
        proc = subprocess.run(["git", "show", f"HEAD:{args.path}"],
                              capture_output=True, text=True)
        if proc.returncode != 0:
            sys.exit(f"VERIFY ERROR  cannot read HEAD:{args.path} — run from the repo "
                     f"root, not a scratch dir.\n{proc.stderr.strip()}")
        base_src, label = proc.stdout, "HEAD"

    work_src = open(args.path).read()
    a, b = nodes(base_src), nodes(work_src)

    if a == b:
        print(f"VERIFY OK  {args.path}: AST identical to {label} "
              f"({len(a)} nodes; docstring edits permitted; "
              f"lines {base_src.count(chr(10))} -> {work_src.count(chr(10))})")
        return

    print(f"VERIFY FAILED  {args.path}: executable code CHANGED vs {label}")
    import difflib
    shown = 0
    for line in difflib.unified_diff(a, b, lineterm="", n=0):
        if line.startswith(("---", "+++")):
            continue
        print("  " + line[:220])
        shown += 1
        if shown >= 12:
            print("  ... (truncated)")
            break
    sys.exit(1)


if __name__ == "__main__":
    main()

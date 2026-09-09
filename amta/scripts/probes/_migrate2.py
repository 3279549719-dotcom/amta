"""Robust post-move import rewriter (run from repo root).

Two rewrites:
  A) textual:  every `amta.<legacy>` dotted token -> `amta.<pkg>.<legacy>` (idempotent).
  B) AST:      every `from amta import a, b as c` (ImportFrom.module == "amta") moves
               each legacy top-module name into its package; parenthesized multi-line and
               aliases handled exactly by the parser; non-legacy names stay `from amta import`.
Run AFTER file moves (git mv) have placed modules into packages, BEFORE tests.
"""
import ast
import glob
import os
import re

MAPPING = {
    "paths": "common", "metrics": "common", "geometry": "common", "images": "common",
    "config": "common", "pipeline_log": "common", "punctuation_align": "common",
    "workstate": "common", "tickets": "common", "evalkit": "common",
    "artifacts": "stores", "artifact_store": "stores", "artifact_cache": "stores",
    "chat_client": "backends", "koharu_client": "backends", "koharu_blocks": "backends",
    "ocr_engines": "backends", "runner": "backends", "vlm_verify": "backends",
    "guardrails": "guards", "glossary": "guards", "canon_schema": "guards",
    "suggestions": "guards", "term_dict": "guards", "term_replace": "guards",
    "rule_filter": "guards", "pre_scan": "guards", "vlm_filter": "guards",
    "inpaint_strategy": "inpaint", "inpaint_station": "inpaint",
    "local_lama_inpainter": "inpaint", "_lama_ffc": "inpaint",
    "_lama_model": "inpaint", "_lama_util": "inpaint",
    "typeset_engine": "typeset", "typeset_render": "typeset",
    "typeset_station": "typeset", "fonts": "typeset",
    "translate": "translation", "stage3_minimal": "translation",
    "translate_station": "translation",
    "detect_station": "stations", "ocr_station": "stations",
}

def text_pass_a(src):
    for legacy, pkg in MAPPING.items():
        pat = re.compile(r'(?<![\w.])amta\.' + re.escape(legacy) + r'(?![\w])')
        src = pat.sub(lambda m: f"amta.{pkg}.{legacy}", src)
    return src

class ImportFromAmtaTransformer:
    """Rewrite each `from amta import names` node by map; returns new source via edits."""
    def __init__(self, src):
        self.src = src

    def transform(self):
        try:
            tree = ast.parse(self.src)
        except SyntaxError:
            return self.src
        edits = []  # (lineno, oldtext, newtext)
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom):
                continue
            if node.level != 0 or node.module != "amta":
                continue
            # capture exact source span
            seg = ast.get_source_segment(self.src, node)
            if seg is None:
                continue
            # leading indent of first physical line of the import statement must be reapplied
            # (get_source_segment strips leading whitespace).
            phys_first = self.src.splitlines()[node.lineno - 1]
            indent = re.match(r'^\s*', phys_first).group(0)
            t, e = node.lineno, getattr(node, "end_lineno", node.lineno)
            # build new import text
            groups = {}
            keep = []
            # preserve order not vital; keep package ordering stable
            for alias in node.names:
                nm = alias.name
                asname = alias.asname
                if nm in MAPPING:
                    tok = nm if not asname else f"{nm} as {asname}"
                    groups.setdefault(MAPPING[nm], []).append(tok)
                else:
                    tok = nm if not asname else f"{nm} as {asname}"
                    keep.append(tok)
            lines = []
            if keep:
                lines.append("from amta import " + ", ".join(keep))
            for p in sorted(groups):
                lines.append(f"from amta.{p} import " + ", ".join(groups[p]))
            new = indent + ("\n" + indent).join(lines)
            edits.append((t, e, seg, new))
        if not edits:
            return self.src
        # apply edits bottom-up by line ranges (non-overlapping consecutive)
        out_lines = self.src.split("\n")
        # We replace by original line slice counting from 1-based lineno to end_lineno.
        # Build new by collecting unchanged prefix + edited chunks sequentially over offsets.
        pending = []
        lines = self.src.split("\n")
        # Actually replace by concatenating: walk through editing new; simpler use chars offsets is harder.
        # Compute via re-splicing line ranges from bottom to top.
        edited = edits
        edited.sort(key=lambda x: -x[0])
        for (bl, el, seg, new) in edited:
            # multi/single line segment is bl..el inclusive inside split lines
            lines[bl-1:el] = new.split("\n")
        return "\n".join(lines)

def process(path):
    with open(path, encoding="utf-8-sig") as f:
        src = f.read()
    a = text_pass_a(src)
    b = ImportFromAmtaTransformer(a).transform()
    if b != src:
        with open(path, "w", encoding="utf-8") as f:
            f.write(b)
        return True
    return False

def main():
    files = (glob.glob("src/amta/**/*.py", recursive=True)
             + glob.glob("scripts/*.py")
             + glob.glob("scripts/probes/*.py")
             + glob.glob("tests/*.py"))
    changed = 0
    for f in files:
        if "__pycache__" in f or f.endswith("_migrate2.py"):
            continue
        try:
            if process(f):
                changed += 1
        except Exception as ex:  # noqa
            print("ERR", f, repr(ex))
    print("changed files:", changed)

if __name__ == "__main__":
    main()

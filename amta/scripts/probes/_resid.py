"""Throwaway: find ANY residual reference to pre-reorg flat amta.<mod> names,
scanning every .py under src/amta, scripts (incl probes), and tests — even nested —
which my migration globs (scripts/*.py, tests/*.py, src/amta/**/*.py) may have missed."""
import glob, os, re

LEGACY = {  # old flat second-level -> new package
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
    "local_lama_inpainter": "inpaint", "typeset_engine": "typeset",
    "typeset_render": "typeset", "typeset_station": "typeset", "fonts": "typeset",
    "translate": "translation", "stage3_minimal": "translation",
    "translate_station": "translation", "detect_station": "stations", "ocr_station": "stations",
}
# note: _lama_ffc/_lama_model/_lama_util kept short separate below
for m in ("_lama_ffc", "_lama_model", "_lama_util"):
    LEGACY[m] = "inpaint"

def scan_dir(d):
    hits = []
    for p in glob.glob(d + "/**/*.py", recursive=True):
        if "__pycache__" in p:
            continue
        src = open(p, encoding="utf-8-sig").read()
        for lineno, line in enumerate(src.splitlines(), 1):
            s = line.strip()
            if s.startswith("#"):
                continue
            low = line
            # case A: amta.<legacy> dotted (module path) 
            for m in LEGACY:
                pat = re.compile(r'(?<![\w.])amta\.' + re.escape(m) + r'(?![\w])')
                if pat.search(line):
                    hits.append((p, lineno, line.strip(), f"dotted {m}"))
            # case B: from amta import <legacy> or as binding
            im = re.match(r'^\s*from\s+amta\s+import\s+(.+?)(\s*#.*)?$', line)
            if im:
                for tok in im.group(1).replace("(", "").split(","):
                    bare = tok.strip().split(" as ")[0].strip()
                    if bare and bare.startswith("legacy-") is False and bare != "(" and not bare.startswith("from"):
                        if bare in LEGACY and "import " not in bare:
                            hits.append((p, lineno, line.strip(), f"bare-import {bare}"))
    return hits

hits = []
for base in ("src/amta", "scripts", "tests"):
    hits += scan_dir(base)
uniq = {}
for (p, ln, lnText, kind) in hits:
    key = f"{p}:{ln}"
    if key not in uniq:
        uniq[key] = (lnText, kind)
keys = sorted(uniq.keys())
print(f"residual old-flat hits: {len(keys)}")
for k in keys:
    t, kind = uniq[k]
    print(f"{k} :: ({kind}) {t}")

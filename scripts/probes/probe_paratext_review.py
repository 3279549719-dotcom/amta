"""Independent VLM visual/text audit; findings are evidence, never automatic approval."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from PIL import Image

from amta.backends.chat_client import chat
from amta.common.config import get_dashscope_key
from amta.common.paths import read_json, write_json
from amta.stores.artifacts import artifact_paths
from scripts.probes.paratext_layout import image_part, parse_json

PROMPT = """You are independently reviewing a Japanese-to-Chinese manga localization.
Compare source page, clean page, final page, and provided transcription/translation.
Identify actual defects: omitted or duplicated source content, mistranscription or mistranslation,
remaining original text, damaged artwork, overlapping/cropped text, wrong reading direction,
unreadably small fonts. Respect mixed horizontal/vertical source layout, source paragraph hierarchy,
and source typography. Proper names, circle names, emails and websites can remain in Japanese/Latin.
Do not invent issues just to supply feedback. Report specific region IDs and exact evidence.
Return JSON {"text_ok": true, "inpaint_ok": true, "typeset_ok": true,
"issues": [{"region_id":"r00", "kind":"translation", "severity":"major",
"evidence":"...", "suggestion":"..."}], "summary":"..."}.
No code, no markdown. Explain issues in Chinese. Approval is provisional; a human/agent also inspects images.
"""


def review(work: str, src: Path, page: int) -> dict:
    art = ROOT / "workspace" / work / "artifacts"
    paths = artifact_paths(art, f"page_{page}")
    canon, translation, paint, typeset = [read_json(paths[k]) for k in ("canon", "translation", "inpaint", "typeset")]
    raw = src / f"{page}.jpg"
    clean, final = art / paint["clean_image"], art / typeset["final_image"]
    signature = hashlib.sha256(b"".join(p.read_bytes() for p in [raw, clean, final, paths["canon"], paths["translation"]])
                               + PROMPT.encode()).hexdigest()
    out = art / "review" / f"page_{page}.json"
    if out.exists() and read_json(out).get("input_sha256") == signature:
        return read_json(out)
    content = []
    for label, path in [("SOURCE", raw), ("CLEAN", clean), ("FINAL", final)]:
        content += [{"type": "text", "text": label}, image_part(Image.open(path), 2600)]
    content += [{"type": "text", "text": json.dumps({"source": canon["items"],
                                                       "translation": translation["translations"]}, ensure_ascii=False)}]
    response = chat(os.environ.get("DASHSCOPE_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
                    os.environ.get("VISION_MODEL", "qwen3.5-omni-plus"),
                    [{"role": "system", "content": PROMPT}, {"role": "user", "content": content}],
                    api_key=get_dashscope_key(), timeout=240, temperature=0.1, max_tokens=6000)
    result = parse_json(response.get("content", ""))
    result["input_sha256"] = signature
    write_json(out, result)
    return result


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--work-id", required=True)
    ap.add_argument("--src-dir", type=Path, required=True)
    ap.add_argument("--pages", required=True)
    args = ap.parse_args()
    for p in map(int, args.pages.split(",")):
        result = review(args.work_id, args.src_dir, p)
        print(p, json.dumps(result, ensure_ascii=False), flush=True)

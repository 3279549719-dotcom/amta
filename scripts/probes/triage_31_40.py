"""归纳 p31-40 问题：查 translation/inpaint/typeset json。"""
from __future__ import annotations
import json
from pathlib import Path

ROOT = Path(r"E:\manga translator agent")
WORK = ROOT/"workspace"/"touhou-getten-shinchi"
ART = WORK/"artifacts"

for pg in range(31, 41):
    print(f"\n=== p{pg} ===")
    # detection
    det = json.loads((ART/"detection"/f"page_{pg}.json").read_text(encoding="utf-8"))
    blocks = {b["region_id"]: b for b in det.get("blocks", [])}
    # OCR
    ocr_f = ART/"ocr"/f"page_{pg}.json"
    if ocr_f.exists():
        ocr = json.loads(ocr_f.read_text(encoding="utf-8"))
        ocr_texts = {r["region_id"]: r.get("text", "") for r in ocr.get("blocks", [])}
    else:
        ocr_texts = {}
    # translation
    tr_f = ART/"translation"/f"page_{pg}.json"
    if tr_f.exists():
        tr = json.loads(tr_f.read_text(encoding="utf-8"))
        trans = tr.get("translations", {})
    else:
        trans = {}
    # inpaint actions
    ip_f = ART/"inpaint"/f"page_{pg}.json"
    if ip_f.exists():
        ip = json.loads(ip_f.read_text(encoding="utf-8"))
        actions = {a["bbox"][0]: a.get("action", "?") for a in ip.get("actions", [])}
    else:
        actions = {}

    for rid in sorted(blocks.keys()):
        ocr_t = ocr_texts.get(rid, "")
        tr_t = trans.get(rid, "")
        action = "?"
        # find action by region_id
        for a in ip.get("actions", []) if ip_f.exists() else []:
            pass
        status = []
        if ocr_t: status.append(f"ocr='{ocr_t[:20]}'")
        if tr_t: status.append(f"tr='{tr_t[:20]}'")
        if not tr_t and ocr_t: status.append("⚠️ 未翻译")
        print(f"  {rid}: {' | '.join(status) if status else 'no data'}")

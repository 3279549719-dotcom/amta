"""一次性探针：扫 p31-40 译文里的问题字符（爱心类 / ASCII 连续点 / 可疑符号）。"""
import glob
import json
import re

files = sorted(glob.glob(
    r"workspace\touhou-getten-shinchi\artifacts\translation\page_3[1-9].json"
) + glob.glob(
    r"workspace\touhou-getten-shinchi\artifacts\translation\page_40.json"
))

ASCII_DOTS = re.compile(r"\.{2,}")
# 爱心/符号类（含 emoji 平面）
SPECIAL = re.compile(r"[^\u4e00-\u9fff\u3000-\u303f\uff00-\uffefA-Za-z0-9\s，。！？、；：""''（）「」《》…—～~·,.:!?]")

for f in files:
    d = json.load(open(f, encoding="utf-8"))
    pg = d.get("page", "?")
    trans = d.get("translations", d)
    items = trans.items() if isinstance(trans, dict) else enumerate(trans)
    for rid, txt in items:
        if not isinstance(txt, str):
            continue
        flags = []
        if ASCII_DOTS.search(txt):
            flags.append("ASCII_DOTS")
        # 挑出非常见符号字符
        weird = [c for c in SPECIAL.findall(txt)]
        if weird:
            flags.append("SPECIAL=" + "".join(sorted(set(weird))))
        if flags:
            print(pg, rid, flags, repr(txt))

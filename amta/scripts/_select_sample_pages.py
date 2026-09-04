"""分析全量检测数据，挑选 10 页有代表性的样本。"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
with open(ROOT / "output/data/detect_full/results.json", "r", encoding="utf-8") as f:
    data = json.load(f)

pages = [p for p in data["per_page"] if "error" not in p]

# 计算每页的特征
for p in pages:
    p["short_ratio"] = p["short_boxes_le3"] / p["n_boxes"] if p["n_boxes"] else 0
    p["punct_ratio"] = p["punct_only_boxes"] / p["n_boxes"] if p["n_boxes"] else 0

print("=== 全量 42 页特征 ===")
print(f"{'页':>4} {'框数':>4} {'字符':>5} {'均字':>5} {'短框':>4} {'短比':>6} {'标点':>4} {'标比':>6} {'类型'}")
for p in pages:
    ptype = []
    if p["n_boxes"] >= 12:
        ptype.append("对话密集")
    if p["raw_chars"] >= 200:
        ptype.append("长文本")
    if p["short_ratio"] >= 0.25:
        ptype.append("SFX多")
    if p["punct_ratio"] >= 0.15:
        ptype.append("误报多")
    if p["n_boxes"] <= 5:
        ptype.append("稀疏")
    print(f"{p['page']:>4} {p['n_boxes']:>4} {p['raw_chars']:>5} {p['avg_chars_per_box']:>5.1f} "
          f"{p['short_boxes_le3']:>4} {p['short_ratio']:>5.0%} {p['punct_only_boxes']:>4} {p['punct_ratio']:>5.0%} "
          f"{','.join(ptype)}")

# 挑选 10 页有代表性的样本
# 策略：覆盖不同类型，包括困难页（11/14/18）
selected = []

# 1. 困难页（之前 baseline 只检出 3 框的）
hard_pages = [11, 14, 18]
for hp in hard_pages:
    p = next(x for x in pages if x["page"] == hp)
    selected.append((p, "困难页(baseline仅3框)"))

# 2. 对话密集页（框最多的）
dense = sorted([p for p in pages if p["n_boxes"] >= 14], key=lambda x: -x["n_boxes"])[:2]
for p in dense:
    if p["page"] not in [s[0]["page"] for s in selected]:
        selected.append((p, "对话密集"))

# 3. 长文本页（字符最多的）
long_text = sorted([p for p in pages if p["raw_chars"] >= 200], key=lambda x: -x["raw_chars"])[:2]
for p in long_text:
    if p["page"] not in [s[0]["page"] for s in selected]:
        selected.append((p, "长文本"))

# 4. SFX多/误报多页
noisy = sorted([p for p in pages if p["short_ratio"] >= 0.25 or p["punct_ratio"] >= 0.15],
               key=lambda x: -(x["short_ratio"] + x["punct_ratio"]))[:2]
for p in noisy:
    if p["page"] not in [s[0]["page"] for s in selected]:
        selected.append((p, "SFX/误报多"))

# 5. 普通页（中等框数中等字符）
normal = sorted([p for p in pages if 6 <= p["n_boxes"] <= 10 and 80 <= p["raw_chars"] <= 160],
                key=lambda x: abs(x["n_boxes"] - 8))
for p in normal:
    if p["page"] not in [s[0]["page"] for s in selected]:
        selected.append((p, "普通页"))
        break

# 补足到 10 页
if len(selected) < 10:
    for p in pages:
        if p["page"] not in [s[0]["page"] for s in selected]:
            selected.append((p, "补充"))
            if len(selected) >= 10:
                break

selected = selected[:10]
print("\n=== 选中的 10 页样本 ===")
for p, reason in selected:
    print(f"  page_{p['page']:02d}: {p['n_boxes']}框, {p['raw_chars']}字, "
          f"短框{p['short_boxes_le3']}({p['short_ratio']:.0%}), "
          f"标点{p['punct_only_boxes']}({p['punct_ratio']:.0%}) — {reason}")

print(f"\n选中页码: {[s[0]['page'] for s in selected]}")

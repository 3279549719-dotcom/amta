"""提取瓦片化新增框的confidence，对比主链框和误伤框的conf分布。"""
import json, os, glob

DET_DIR = r"E:\manga translator agent\amta\workspace\touhou-tiling-e2e\artifacts\detection"

# 瓦片化新增框的bbox（从报告中提取）
TILING_NEW = [
    (3, [495,845,689,974], "ぽ"),
    (11, [787,286,963,669], "はっ..."),
    (14, [609,1500,658,1614], "いたい!"),
    (14, [398,1577,461,1688], "八意様"),
    (15, [1398,777,1462,887], "はい"),
    (17, [428,2302,495,2469], "おとな..."),
    (17, [1323,528,1387,662], "ご苦労"),
    (19, [794,2451,857,2554], "サグ姉"),
    (22, [1722,413,1863,793], "はっ..."),
    (24, [718,2828,849,2868], "フルフル"),
    (25, [1413,2573,1484,2662], "姉様"),
    (26, [1452,388,1505,689], "私のスタンプ帳せてあげる"),
    (27, [712,375,807,521], "月!?"),
    (32, [1181,2253,1250,2676], "ちょっ、離してください"),
    (32, [781,2843,833,3013], "楽ちん♪"),
    (33, [1670,852,1741,1161], "うわああああああ"),
    (34, [1053,494,1115,634], "戻れー"),
]

def bbox_match(b1, b2, tol=30):
    """判断两个bbox是否匹配（容差30px）"""
    return all(abs(a - b) <= tol for a, b in zip(b1, b2))

print("=== 瓦片化新增框的confidence提取 ===\n")

tiling_confs = []
for page_num, target_bbox, ocr_text in TILING_NEW:
    det_path = os.path.join(DET_DIR, f"page_{page_num}.json")
    if not os.path.exists(det_path):
        print(f"  p{page_num}: detection文件不存在")
        continue
    det = json.load(open(det_path, encoding="utf-8"))
    matched = None
    for b in det.get("blocks", []):
        if bbox_match(b["bbox"], target_bbox):
            matched = b
            break
    if matched:
        conf = matched.get("confidence", 0)
        rid = matched.get("region_id", "?")
        engines = matched.get("source_engines", [])
        is_tiled = "rtdetr-v2-tiled" in engines
        tiling_confs.append(conf)
        print(f"  p{page_num} {rid}: conf={conf:.4f}, engines={engines}, tiled={is_tiled}, OCR='{ocr_text}'")
    else:
        # 打印该页所有框的bbox供调试
        print(f"  p{page_num}: 未匹配到目标bbox {target_bbox}")
        for b in det.get("blocks", []):
            print(f"    候选: {b['region_id']} bbox={[int(x) for x in b['bbox']]} conf={b.get('confidence',0):.3f}")

print(f"\n=== 瓦片化新增框confidence统计 ===")
print(f"  数量: {len(tiling_confs)}")
print(f"  最小: {min(tiling_confs):.4f}")
print(f"  最大: {max(tiling_confs):.4f}")
print(f"  平均: {sum(tiling_confs)/len(tiling_confs):.4f}")
print(f"  <0.8的数量: {sum(1 for c in tiling_confs if c < 0.8)}")
print(f"  <0.75的数量: {sum(1 for c in tiling_confs if c < 0.75)}")
print(f"  <0.7的数量: {sum(1 for c in tiling_confs if c < 0.7)}")

# 对比：主链框的conf分布
print(f"\n=== 主链所有保留框的confidence分布（全40页） ===")
all_confs = []
main_chain_confs = []
tiled_confs = []
for det_file in sorted(glob.glob(os.path.join(DET_DIR, "page_*.json"))):
    det = json.load(open(det_file, encoding="utf-8"))
    for b in det.get("blocks", []):
        conf = b.get("confidence", 0)
        engines = b.get("source_engines", [])
        all_confs.append(conf)
        if "rtdetr-v2-tiled" in engines:
            tiled_confs.append(conf)
        else:
            main_chain_confs.append(conf)

print(f"  总框数: {len(all_confs)}")
print(f"  主链框: {len(main_chain_confs)}, 平均conf={sum(main_chain_confs)/len(main_chain_confs):.4f}, 最小={min(main_chain_confs):.4f}")
print(f"  瓦片框: {len(tiled_confs)}, 平均conf={sum(tiled_confs)/len(tiled_confs):.4f}, 最小={min(tiled_confs):.4f}")

# 被rule_filter误伤的6个框的conf
print(f"\n=== 被误伤的6个真实对话框的confidence ===")
false_positives = [
    (13, "r01", "うおおお!", 0.921),
    (16, "r03", "最初は私も…", 0.964),
    (20, "r00", "月の民は…", 0.913),
    (22, "r08", "大事なのは…", 0.935),
    (33, "r01", "そのとき採れる手段は…", 0.901),
    (41, "r00", "東方Project Fanbook", 0.891),
]
for page, rid, text, conf in false_positives:
    print(f"  p{page} {rid}: conf={conf:.3f}, '{text}'")

# 真杂质的conf
print(f"\n=== 真杂质2个框的confidence ===")
print(f"  p2 t04: conf=0.704, 刻度线")
print(f"  p6 t08: conf=0.789, 纯黑竖条")

print(f"\n=== 关键对比 ===")
print(f"  瓦片化小字平均conf: {sum(tiling_confs)/len(tiling_confs):.4f}")
print(f"  误伤框平均conf: {sum(c for _,_,_,c in false_positives)/len(false_positives):.4f}")
print(f"  真杂质平均conf: {(0.704+0.789)/2:.4f}")
print(f"  瓦片小字conf范围: {min(tiling_confs):.3f} ~ {max(tiling_confs):.3f}")
print(f"  误伤框conf范围: 0.891 ~ 0.964")
print(f"  真杂质conf范围: 0.704 ~ 0.789")

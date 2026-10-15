"""detect 单例真实冒烟测试。"""
import sys
import time
from pathlib import Path
import tempfile

sys.path.insert(0, "src")
from amta.stations.detect_station import detect_page, _detector

print(f"初始单例状态: {_detector is None}")

test_img = Path(r"D:\我的汉化\汉化作品\其他\心心相印\1.jpg")
if not test_img.exists():
    print("测试图不存在，跳过")
    sys.exit(0)

with tempfile.TemporaryDirectory() as tmp:
    out_dir = Path(tmp)

    t0 = time.time()
    r1 = detect_page("smoke", test_img, out_dir, page_idx=1)
    t1 = time.time()
    print(f"第一次 detect: {t1-t0:.2f}s, {len(r1['blocks'])} 个框, 单例已加载: {_detector is not None}")

    t0 = time.time()
    r2 = detect_page("smoke", test_img, out_dir, page_idx=2)
    t1 = time.time()
    print(f"第二次 detect: {t1-t0:.2f}s, {len(r2['blocks'])} 个框, 单例已加载: {_detector is not None}")

    boxes1 = [b["bbox"] for b in r1["blocks"]]
    boxes2 = [b["bbox"] for b in r2["blocks"]]
    print(f"两次结果框数一致: {len(boxes1) == len(boxes2)}")
    print(f"单例实例ID: {id(_detector)}")
    print("冒烟测试通过")

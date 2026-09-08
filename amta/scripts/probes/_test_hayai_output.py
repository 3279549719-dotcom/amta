"""测试hayai OCR的完整返回值，看有没有字符级confidence。"""
import os
import sys

# 代理没开时直连
for k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy"):
    os.environ.pop(k, None)

os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

sys.path.insert(0, "src")

from hayai_ocr import HayaiOcr

model_path = os.environ.get("HAYAI_OCR_MODEL", r"E:\models\hayai-ocr-v2")
print(f"加载模型: {model_path}")
ocr = HayaiOcr(pretrained_model_name_or_path=model_path)
print("模型加载完成\n")

# 用一张已经裁剪好的图片测试
# p13的r01喊叫框（真实文本）
crop_real = r"E:\manga translator agent\amta\workspace\touhou-remove-geo-rules\artifacts\crops\r01.png"
# p6的t08黑竖条（假框/乱码）—— 可能还没裁剪，用其他路径
# 先看crops目录有什么
import glob
crops = sorted(glob.glob(r"E:\manga translator agent\amta\workspace\touhou-remove-geo-rules\artifacts\crops\*.png"))
print(f"crops目录有 {len(crops)} 张图")
for c in crops[:5]:
    print(f"  {os.path.basename(c)}")

if os.path.exists(crop_real):
    test_img = crop_real
else:
    test_img = crops[0] if crops else None

if test_img:
    print(f"\n=== 测试图片: {os.path.basename(test_img)} ===")
    res = ocr(test_img)
    print(f"返回类型: {type(res)}")
    print(f"返回值: {res}")
    if isinstance(res, dict):
        print(f"字典keys: {list(res.keys())}")
        for k, v in res.items():
            print(f"  {k}: {type(v).__name__} = {str(v)[:200]}")
    elif isinstance(res, list):
        print(f"列表长度: {len(res)}")
        for i, item in enumerate(res):
            print(f"  [{i}] type={type(item).__name__}, value={str(item)[:200]}")
            if isinstance(item, dict):
                print(f"      keys: {list(item.keys())}")
else:
    print("没有测试图片")

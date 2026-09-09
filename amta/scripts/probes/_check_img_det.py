"""验证图片尺寸和 detection.json 对应关系。"""
import json
from PIL import Image

for p in [11, 15, 20]:
    img = Image.open(f"output/data/ocr_check_html/{p}.jpg")
    det = json.load(open(f"workspace/exp-q1-tiling-garbled/artifacts/detection/page_{p}_detection.json", encoding="utf-8"))
    btypes = [b["bubble_type"] for b in det["blocks"]]
    print(f"page_{p}: img={img.size}, n_boxes={det['n_boxes']}, bubble_types={btypes}")

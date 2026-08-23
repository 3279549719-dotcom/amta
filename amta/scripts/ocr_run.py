"""在 recall_gt.json 的 101 个 GT 框上跑指定 OCR 引擎。
引擎: local(本地 llama-server :8118) | dashscope(qwen-vl-ocr)
用法: python scripts/ocr_run.py --engine local|dashscope [--pages N]
"""
from __future__ import annotations
import argparse
import base64
import json
import os
import sys
from pathlib import Path

import requests
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "output" / "data"

DASHSCOPE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"


def crop_regions(gt, page_paths, crop_dir):
    """从原图按 GT bbox 裁框。page_paths: {page_num(int): img_path}。返回 (crop_paths, meta)。"""
    if isinstance(gt, (str, Path)):
        gt = json.loads(Path(gt).read_text(encoding="utf-8"))
    crop_dir = Path(crop_dir); crop_dir.mkdir(parents=True, exist_ok=True)
    crops, meta = [], []
    for gkey, regions in gt["pages"].items():
        page_num = int(gkey.split("_")[1])
        src = page_paths.get(page_num)
        if src is None or not Path(src).exists():
            continue
        im = Image.open(src)
        for i, region in enumerate(regions):
            x0, y0, x1, y1 = (int(v) for v in region["bbox"])
            box = (max(0, x0 - 4), max(0, y0 - 4), min(im.width, x1 + 4), min(im.height, y1 + 4))
            fname = f"{gkey}_gt{i:02d}.png"
            crop = im.crop(box)
            p = crop_dir / fname
            crop.save(p)
            crops.append(str(p))
            meta.append({"page": page_num, "crop": str(p), "bbox": region["bbox"],
                         "content": region["content"], "type": region["type"]})
    return crops, meta


def local_ocr_batch(crop_paths, base_url="http://127.0.0.1:8118/v1", model="paddle", concurrency=1):
    """依次送图给 llama-server，OpenAI 兼容 completions。并发固定 1（CPU 单机）。"""
    out = []
    for p in crop_paths:
        ocr = send_one(base_url, model, p)
        out.append({"crop": p, "ocr": ocr})
    return out


def send_one(base_url, model, img_path):
    """llama-server 单张请求契约：{base_url}/completions，解析 choices[0].text。

    注：真实多模态传图通道（本地图如何进 llama-server）由 Task 3 用既有
    ocr_detect.py/baberu_ocr.py 实现填充；此处仅锁定端点与响应解析。
    """
    payload = {"model": model, "prompt": "OCR:", "image": img_path}
    r = requests.post(f"{base_url}/completions", json=payload, timeout=60)
    r.raise_for_status()
    return r.json()["choices"][0]["text"]


def _get_dashscope_key():
    """读 DASHSCOPE_API_KEY：环境变量优先，回退 .env 文件（兼容 DASHSCOPE_KEY 旧名）。绝不打印 key。"""
    for name in ("DASHSCOPE_API_KEY", "DASHSCOPE_KEY"):
        v = os.environ.get(name)
        if v:
            return v
    for env_path in (ROOT / ".env", ROOT.parent / ".env"):
        if env_path.exists():
            for line in env_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line.startswith("DASHSCOPE_API_KEY=") or line.startswith("DASHSCOPE_KEY="):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise RuntimeError("缺少 DASHSCOPE_API_KEY：请在 .env 配置或设置环境变量")


def dashscope_ocr_batch(crop_paths, model="qwen-vl-ocr-latest", concurrency=4):
    """DashScope qwen-vl-ocr：OpenAI 兼容端点，base64 图，纯文本输出。101 张约 ¥0.1、1-3 分钟。"""
    key = _get_dashscope_key()
    out = []
    for p in crop_paths:
        with open(p, "rb") as f:
            b64 = base64.b64encode(f.read()).decode()
        payload = {
            "model": model,
            "messages": [{"role": "user", "content": [
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
                {"type": "text", "text": "OCR"},
            ]}],
        }
        r = requests.post(DASHSCOPE_URL, headers={"Authorization": f"Bearer {key}"}, json=payload, timeout=60)
        r.raise_for_status()
        text = r.json()["choices"][0]["message"]["content"]
        out.append({"crop": p, "ocr": text})
    return out


def main():
    ap = argparse.ArgumentParser(description="在 recall_gt 的 GT 框上跑指定 OCR 引擎")
    ap.add_argument("--engine", choices=["local", "dashscope"], required=True)
    ap.add_argument("--pages", type=int, default=None, help="只处理前 N 页（默认全部）")
    ap.add_argument("--out", default=None, help="preds JSON 输出路径")
    ap.add_argument("--src-dir", default=r"D:\我的汉化\汉化作品\东方\单翼停留之地")
    ap.add_argument("--gt", default=str(DATA / "recall_gt.json"))
    ap.add_argument("--crop-dir", default=str(DATA / "ocr_crops"))
    ap.add_argument("--model", default=None)
    a = ap.parse_args()

    gt = json.loads(Path(a.gt).read_text(encoding="utf-8"))
    if a.pages:
        keys = sorted(gt["pages"].keys(), key=lambda k: int(k.split("_")[1]))[: a.pages]
        gt = {"pages": {k: gt["pages"][k] for k in keys}}

    page_paths = {int(k.split("_")[1]): str(Path(a.src_dir) / f"{int(k.split('_')[1])}.jpg")
                  for k in gt["pages"]}
    crops, meta = crop_regions(gt, page_paths, a.crop_dir)
    print(f"[ocr_run] {len(crops)} crops -> {a.crop_dir}", file=sys.stderr)

    if a.engine == "local":
        preds = local_ocr_batch(crops, model=a.model or "paddle")
    else:
        preds = dashscope_ocr_batch(crops, model=a.model or "qwen-vl-ocr-latest")

    for p in preds:
        print(f"{Path(p['crop']).name}: {p['ocr']}")
    if a.out:
        Path(a.out).parent.mkdir(parents=True, exist_ok=True)
        Path(a.out).write_text(json.dumps(preds, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[ocr_run] preds -> {a.out}", file=sys.stderr)


if __name__ == "__main__":
    main()

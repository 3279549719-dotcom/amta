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

# Windows 控制台默认 GBK，打印日文会 UnicodeEncodeError；统一走 UTF-8 输出
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import requests
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "output" / "data"

DASHSCOPE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"


def crop_regions(gt, page_paths, crop_dir, det_boxes=None):
    """从原图按 detector 可靠坐标裁框，用 GT 内容做比对基准。

    背景（ADR-011）：GT bbox 是 VLM 整页枚举的缩略坐标（x 约 40% 宽），直接裁图全空白
    （「VLM 整页坐标不可靠」坑）。评测锚点改为：裁框用 detector 全尺寸可靠坐标，
    比对用 GT 内容。recall_report 证明 101 条 GT 内容有 99 条被 detector 框覆盖。

    det_boxes: {page_num: [{bbox:[x0,y0,x1,y1], text:str}]} —— 来自 ocr_result.json 的
    manga-ocr（For-Manga 现役输出），坐标为全尺寸可靠。缺省时回退到 GT bbox（仅测试用）。
    返回 (crop_paths, meta)；meta 每条含 {page, crop, bbox, content, type}。
    """
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
        # 内容 → detector 框映射（同一页内按字符重合度对齐 GT 内容与 detector 文本）
        dets = det_boxes.get(page_num, []) if det_boxes else []
        used = [False] * len(dets)
        for i, region in enumerate(regions):
            content = region["content"]
            # 选出与该 GT 内容字符重合度最高的未用 detector 框
            best_j, best_score = -1, 0.6
            for j, d in enumerate(dets):
                if used[j] or not d.get("text"):
                    continue
                sc = _content_overlap(content, d["text"])
                if sc >= best_score:
                    best_score, best_j = sc, j
            if best_j >= 0:
                bbox = dets[best_j]["bbox"]
                used[best_j] = True
            else:
                bbox = region["bbox"]  # 无匹配框：回退 GT bbox（该条计入未检出）
            x0, y0, x1, y1 = (int(v) for v in bbox)
            box = (max(0, x0 - 4), max(0, y0 - 4), min(im.width, x1 + 4), min(im.height, y1 + 4))
            fname = f"{gkey}_gt{i:02d}.png"
            crop = im.crop(box)
            p = crop_dir / fname
            crop.save(p)
            crops.append(str(p))
            meta.append({"page": page_num, "crop": str(p), "bbox": bbox,
                         "content": content, "type": region["type"]})
    return crops, meta


def _content_overlap(a: str, b: str) -> float:
    """字符重合度（归一化后），用于内容级对齐 GT 与 detector 文本。"""
    from difflib import SequenceMatcher
    na, nb = a or "", b or ""
    if not na and not nb:
        return 1.0
    if not na or not nb:
        return 0.0
    return SequenceMatcher(None, na, nb).ratio()


def local_ocr_batch(crop_paths, base_url="http://127.0.0.1:8118/v1", model="paddle", concurrency=1):
    """依次送图给 llama-server，OpenAI 兼容 completions。并发固定 1（CPU 单机）。"""
    out = []
    for p in crop_paths:
        ocr = send_one(base_url, model, p)
        out.append({"crop": p, "ocr": ocr})
    return out


def send_one(base_url, model, img_path):
    """llama-server 单张多模态 OCR 请求：{base_url}/chat/completions + image_url。

    llama.cpp b10582 多模态走 OpenAI 兼容 chat/completions，图作为 image_url(data URI)，
    与 DashScope qwen-vl-ocr 请求格式对称。PaddleOCR-VL 用 'OCR' 文本触发识别。
    解析 choices[0].message.content。单会话单图：每 crop 一次请求。
    """
    import base64 as _b64
    with open(img_path, "rb") as f:
        b64 = _b64.b64encode(f.read()).decode()
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": [
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
            {"type": "text", "text": "OCR"},
        ]}],
    }
    r = requests.post(f"{base_url}/chat/completions", json=payload, timeout=120)
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]


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
    ap.add_argument("--det", default=str(DATA / "ocr_result.json"),
                    help="detector 输出（含全尺寸 bbox），评测坐标源；缺省 ocr_result.json")
    ap.add_argument("--crop-dir", default=str(DATA / "ocr_crops"))
    ap.add_argument("--model", default=None)
    a = ap.parse_args()

    gt = json.loads(Path(a.gt).read_text(encoding="utf-8"))
    if a.pages:
        keys = sorted(gt["pages"].keys(), key=lambda k: int(k.split("_")[1]))[: a.pages]
        gt = {"pages": {k: gt["pages"][k] for k in keys}}

    page_paths = {int(k.split("_")[1]): str(Path(a.src_dir) / f"{int(k.split('_')[1])}.jpg")
                  for k in gt["pages"]}
    # 从 ocr_result.json 取 detector 全尺寸 bbox + 文本，作为评测坐标源（绕过 GT bbox 缩略坐标）
    det_boxes = {}
    if Path(a.det).exists():
        det = json.loads(Path(a.det).read_text(encoding="utf-8"))
        for pkey, pinfo in det.items():
            pnum = int(pkey.split("_")[1])
            eng = (pinfo.get("engines") or {}).get("manga-ocr", [])
            det_boxes[pnum] = [{"bbox": b.get("bbox"), "text": b.get("ocr") or ""} for b in eng]
    crops, meta = crop_regions(gt, page_paths, a.crop_dir, det_boxes=det_boxes)
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

"""Stage 4 Inpainting 速度 A/B 实验脚本。

四组对比:
  baseline : 整页送 Koharu lama-manga (当前方案)
  p0       : 裁剪 text_free 区域送 Koharu (P0 only)
  p1_cpu   : 裁剪 + 本地 big-lama CPU 推理 (P0+P1)
  p1_gpu   : 裁剪 + 本地 big-lama DirectML (可选, 不支持则跳过)

用法:
  python scripts/exp_inpaint_speed.py --mode baseline --pages 11,12,13 --repeat 3
  python scripts/exp_inpaint_speed.py --mode all --pages 11-15 --repeat 3
"""
from __future__ import annotations

import argparse
import io
import json
import sys
import tempfile
import time
from pathlib import Path

from PIL import Image

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(SCRIPT_DIR))

from importlib import import_module  # noqa: E402
mod = import_module("04_inpaint")

from amta.koharu_client import KoharuClient  # noqa: E402
from amta.local_lama_inpainter import LocalLamaInpainter  # noqa: E402

SRC_DIR = Path(r"D:\我的汉化\汉化作品\东方\单翼停留之地")
DET_DIR = ROOT / "workspace" / "touhou-single-wing-fresh" / "artifacts"
OUT_DIR = ROOT / "output" / "tmp" / "inpaint_speed_exp"
PADDING = 64


def parse_pages(spec: str) -> list[int]:
    pages = []
    for part in spec.split(","):
        part = part.strip()
        if "-" in part:
            lo, hi = part.split("-", 1)
            pages.extend(range(int(lo), int(hi) + 1))
        else:
            pages.append(int(part))
    return sorted(set(pages))


def load_page(page_num: int) -> tuple[Path, Path]:
    raw = SRC_DIR / f"{page_num}.jpg"
    det = DET_DIR / f"page_{page_num - 1}_detection.json"
    if not raw.exists():
        raise FileNotFoundError(f"raw not found: {raw}")
    if not det.exists():
        raise FileNotFoundError(f"detection not found: {det}")
    return raw, det


def get_free_boxes(det_path: Path) -> list[dict]:
    det = json.loads(det_path.read_text(encoding="utf-8"))
    blocks = det.get("blocks") or det.get("regions") or []
    return [b for b in blocks if b.get("bubble_type") == "text_free"]


def fill_bubbles(img: Image.Image, det_path: Path) -> None:
    det = json.loads(det_path.read_text(encoding="utf-8"))
    blocks = det.get("blocks") or det.get("regions") or []
    for b in blocks:
        if b.get("bubble_type") == "text_bubble":
            mod._apply_fill_white(img, b["bbox"])


def crop_box(img: Image.Image, bbox: list, padding: int = PADDING):
    x1, y1, x2, y2 = [int(v) for v in bbox]
    x1 = max(0, x1 - padding)
    y1 = max(0, y1 - padding)
    x2 = min(img.width, x2 + padding)
    y2 = min(img.height, y2 + padding)
    crop = img.crop((x1, y1, x2, y2))
    return crop, (x1, y1, x2, y2)


def build_crop_mask(crop_img: Image.Image, bbox: list, crop_origin: tuple, refine: bool = True) -> bytes:
    ox, oy = crop_origin[0], crop_origin[1]
    local_bbox = [bbox[0] - ox, bbox[1] - oy, bbox[2] - ox, bbox[3] - oy]
    return mod._build_mask(crop_img, [local_bbox], pad=4, refine=refine)


def koharu_inpaint(image: Image.Image, mask_bytes: bytes, engine: str = "lama-manga") -> Image.Image | None:
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        image.save(f, format="PNG")
        img_path = Path(f.name)
    try:
        client = KoharuClient()
        client.wait_server(timeout=60)
        client.close_current_project()
        client.create_project("exp-inpaint-crop")
        page_id = client.import_page(img_path)
        client.run_inpaint(page_id, {"segment": mask_bytes, "bubble": mask_bytes}, engine=engine)
        data = client.fetch_inpainted(page_id)
        if data:
            return Image.open(io.BytesIO(data)).convert("RGB")
        return None
    finally:
        img_path.unlink(missing_ok=True)


def run_baseline(page_num: int, repeat: int = 3) -> dict:
    raw, det = load_page(page_num)
    times = []
    for i in range(repeat):
        t0 = time.time()
        out = OUT_DIR / "baseline" / f"page_{page_num}_run{i}_inpaint.json"
        clean = OUT_DIR / "baseline" / "clean"
        out.parent.mkdir(parents=True, exist_ok=True)
        mod.run(
            work_id=f"exp-baseline-p{page_num}-r{i}",
            det_path=det, raw_page=raw, out_path=out,
            clean_dir=clean, refine_mask=True, inpaint_engine="lama-manga",
        )
        times.append(time.time() - t0)
    return {"page": page_num, "mode": "baseline", "times": times,
            "avg": sum(times) / len(times), "n_free": len(get_free_boxes(det))}


def run_p0(page_num: int, repeat: int = 3) -> dict:
    raw, det = load_page(page_num)
    free_boxes = get_free_boxes(det)
    times = []
    for i in range(repeat):
        t0 = time.time()
        img = Image.open(raw).convert("RGB")
        fill_bubbles(img, det)
        for box in free_boxes:
            crop, origin = crop_box(img, box["bbox"])
            mask = build_crop_mask(crop, box["bbox"], origin, refine=True)
            inpainted = koharu_inpaint(crop, mask)
            if inpainted and inpainted.size == crop.size:
                img.paste(inpainted, (origin[0], origin[1]))
        elapsed = time.time() - t0
        times.append(elapsed)
        if i == repeat - 1:
            save_path = OUT_DIR / "p0" / "clean" / f"page_{page_num}_clean.png"
            save_path.parent.mkdir(parents=True, exist_ok=True)
            img.save(save_path)
    return {"page": page_num, "mode": "p0", "times": times,
            "avg": sum(times) / len(times), "n_free": len(free_boxes)}


def run_p1(page_num: int, repeat: int = 3, inpainter: LocalLamaInpainter | None = None,
           mode_name: str = "p1_cpu", refine: bool = True) -> dict:
    raw, det = load_page(page_num)
    free_boxes = get_free_boxes(det)
    if inpainter is None:
        inpainter = LocalLamaInpainter(device="cpu")
    times = []
    for i in range(repeat):
        t0 = time.time()
        img = Image.open(raw).convert("RGB")
        fill_bubbles(img, det)
        for box in free_boxes:
            crop, origin = crop_box(img, box["bbox"])
            mask_bytes = build_crop_mask(crop, box["bbox"], origin, refine=refine)
            mask_img = Image.open(io.BytesIO(mask_bytes)).convert("L")
            inpainted = inpainter.inpaint(crop, mask_img)
            if inpainted and inpainted.size == crop.size:
                img.paste(inpainted, (origin[0], origin[1]))
        elapsed = time.time() - t0
        times.append(elapsed)
        if i == repeat - 1:
            save_path = OUT_DIR / mode_name / "clean" / f"page_{page_num}_clean.png"
            save_path.parent.mkdir(parents=True, exist_ok=True)
            img.save(save_path)
    return {"page": page_num, "mode": mode_name, "times": times,
            "avg": sum(times) / len(times), "n_free": len(free_boxes),
            "model_load_time": inpainter.load_time_s, "refine": refine}


def run_p1_fullpage(page_num: int, repeat: int = 3, inpainter: LocalLamaInpainter | None = None,
                     mode_name: str = "p1_manga", max_width: int = 1024) -> dict:
    """整页推理: 生成整页 mask, 缩小到 max_width 宽, 整页 inpaint, 放大回原尺寸.

    整页推理让模型有更多上下文, 背景修复更准确 (无方框感), 但速度较慢.
    """
    import numpy as np
    from PIL import ImageDraw
    raw, det = load_page(page_num)
    free_boxes = get_free_boxes(det)
    if inpainter is None:
        inpainter = LocalLamaInpainter(device="cpu", model_type="lama-manga")
    times = []
    for i in range(repeat):
        t0 = time.time()
        img = Image.open(raw).convert("RGB")
        fill_bubbles(img, det)

        # 生成整页 mask (所有框外字的 bbox 合并)
        full_mask = Image.new("L", img.size, 0)
        draw = ImageDraw.Draw(full_mask)
        for box in free_boxes:
            x1, y1, x2, y2 = [int(v) for v in box["bbox"]]
            x1 = max(0, x1 - 4); y1 = max(0, y1 - 4)
            x2 = min(img.width, x2 + 4); y2 = min(img.height, y2 + 4)
            draw.rectangle([x1, y1, x2, y2], fill=255)

        # 缩小到 max_width 宽
        scale = max_width / img.width
        new_size = (max_width, int(img.height * scale))
        img_small = img.resize(new_size, Image.LANCZOS)
        mask_small = full_mask.resize(new_size, Image.NEAREST)

        # 整页推理
        inpainted_small = inpainter.inpaint(img_small, mask_small)

        # 放大回原尺寸
        inpainted_full = inpainted_small.resize(img.size, Image.LANCZOS)

        # 只替换 mask 区域
        mask_np = np.array(full_mask) > 127
        orig_np = np.array(img)
        result_np = np.array(inpainted_full)
        orig_np[mask_np] = result_np[mask_np]
        img = Image.fromarray(orig_np)

        elapsed = time.time() - t0
        times.append(elapsed)
        if i == repeat - 1:
            save_path = OUT_DIR / mode_name / "clean" / f"page_{page_num}_clean.png"
            save_path.parent.mkdir(parents=True, exist_ok=True)
            img.save(save_path)
    return {"page": page_num, "mode": mode_name, "times": times,
            "avg": sum(times) / len(times), "n_free": len(free_boxes),
            "model_load_time": inpainter.load_time_s, "fullpage": True,
            "max_width": max_width}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", required=True, choices=["baseline", "p0", "p1_cpu", "p1_rect", "p1_manga", "p1_gpu", "all"])
    ap.add_argument("--pages", default="11-15")
    ap.add_argument("--repeat", type=int, default=3)
    a = ap.parse_args()

    pages = parse_pages(a.pages)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"[exp] pages={pages} repeat={a.repeat} mode={a.mode}")

    results = []
    inpainter = None

    modes = [a.mode] if a.mode != "all" else ["baseline", "p0", "p1_cpu"]

    for mode in modes:
        print(f"\n=== MODE: {mode} ===")
        if mode in ("p1_cpu", "p1_rect", "p1_manga", "p1_gpu") and inpainter is None:
            device = "cpu"  # GPU not supported for TorchScript
            model_type = "lama-manga" if mode == "p1_manga" else "big-lama"
            print(f"[exp] Loading local LaMa model ({device}, {model_type})...")
            inpainter = LocalLamaInpainter(device=device, model_type=model_type)
            print(f"[exp] Model loaded in {inpainter.load_time_s:.1f}s")

        for p in pages:
            print(f"  page {p}...", end=" ", flush=True)
            try:
                if mode == "baseline":
                    r = run_baseline(p, a.repeat)
                elif mode == "p0":
                    r = run_p0(p, a.repeat)
                elif mode == "p1_cpu":
                    r = run_p1(p, a.repeat, inpainter=inpainter, mode_name=mode, refine=True)
                elif mode == "p1_rect":
                    r = run_p1(p, a.repeat, inpainter=inpainter, mode_name=mode, refine=False)
                elif mode == "p1_manga":
                    r = run_p1_fullpage(p, a.repeat, inpainter=inpainter, mode_name=mode)
                else:
                    continue
                results.append(r)
                print(f"avg={r['avg']:.1f}s (free={r['n_free']})")
            except Exception as e:
                print(f"FAIL: {e}")
                results.append({"page": p, "mode": mode, "error": str(e)})

    summary_path = OUT_DIR / f"summary_{a.mode}.json"
    summary_path.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n[exp] Summary saved: {summary_path}")

    # 打印汇总表
    print("\n=== 速度汇总 ===")
    print(f"{'page':>6} {'mode':>10} {'avg(s)':>8} {'free':>5} {'times':>20}")
    for r in results:
        if "error" in r:
            print(f"{r['page']:>6} {r['mode']:>10} {'ERROR':>8}")
        else:
            times_str = ",".join(f"{t:.0f}" for t in r["times"])
            print(f"{r['page']:>6} {r['mode']:>10} {r['avg']:>8.1f} {r['n_free']:>5} {times_str:>20}")

    return 0


if __name__ == "__main__":
    sys.exit(main())

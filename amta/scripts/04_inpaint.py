"""04_inpaint 工位 — detection.json + raw 页 → clean 图 + inpaint 产物(Stage 4)。

用法: python scripts/04_inpaint.py --work-id <id> --det <detection.json> --raw <page图>
      --out <page>_inpaint.json --clean-dir <artifacts/clean> [--dry-run]
策略: bubble_type 分类 → text_bubble 白底直填 / text_free mask+inpaint(koharu lama-manga)。
贴回: fetch_inpainted(WEBP) 整页替换,再重放 fill_white。
断点: --out 存在 → 跳过(00_run_all 调用方决定)。
"""
from __future__ import annotations

import argparse
import io
import sys
import time
from pathlib import Path

import numpy as np  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from amta.inpaint_strategy import FILL_WHITE, INPAINT, SKIP, plan_inpaint  # noqa: E402
from amta.koharu_client import KoharuClient  # noqa: E402
from amta.paths import read_json, write_json  # noqa: E402
from amta.text_mask_refiner import build_rect_mask, refine_text_mask  # noqa: E402
from PIL import Image, ImageChops, ImageDraw  # noqa: E402


def _apply_fill_white(img: Image.Image, bbox: list) -> None:
    x1, y1, x2, y2 = [int(v) for v in bbox]
    ImageDraw.Draw(img).rectangle([x1, y1, x2, y2], fill=(255, 255, 255))


def _build_mask(img: Image.Image, bboxes: list[list], pad: int = 4,
                refine: bool = False) -> bytes:
    """inpaint 区域聚合 mask(PNG 编码): 目标区白(255),其余黑(0)。koharu 约定: 白色=要修复区域。

    refine=False: 矩形 mask (默认, 向后兼容)
    refine=True:  框内传统方法精修像素级 mask (Plan A, 减少背景覆盖 70%+)
    """
    if refine and bboxes:
        img_rgb = np.array(img.convert("RGB"))
        mask_np = refine_text_mask(img_rgb, bboxes, pad=pad)
        mask_img = Image.fromarray(mask_np)
    else:
        mask_np = build_rect_mask(img.size, bboxes, pad=pad)
        mask_img = Image.fromarray(mask_np)
    buf = io.BytesIO()
    mask_img.save(buf, format="PNG")
    return buf.getvalue()


def _pixel_diff_ratio(a: Image.Image, b: Image.Image) -> float:
    """clean vs raw 像素差异比例(>0 证明有擦除发生)。"""
    if a.size != b.size:
        return 1.0
    hist = ImageChops.difference(a.convert("RGB"), b.convert("RGB")).convert("L").histogram()
    changed = sum(hist[1:])
    return round(changed / (a.width * a.height), 4)


def run(work_id: str, det_path: Path, raw_page: Path, out_path: Path,
        clean_dir: Path | None = None, dry_run: bool = False,
        host: str = "127.0.0.1", port: int = 4000,
        refine_mask: bool = False, inpaint_engine: str = "lama-manga") -> dict:
    det = read_json(det_path)
    raw_img = Image.open(raw_page).convert("RGB")
    img = raw_img.copy()
    # detection.json 字段是 blocks(新), 兼容 regions(旧)
    regions = det.get("blocks") or det.get("regions") or []
    plan = plan_inpaint(regions, det.get("image_meta"))

    filled = [p for p in plan if p["action"] == FILL_WHITE]
    inpaint_boxes = [p["bbox"] for p in plan if p["action"] == INPAINT]
    skipped = [p for p in plan if p["action"] == SKIP]

    if not dry_run and (filled or inpaint_boxes):
        if inpaint_boxes:
            client = KoharuClient(host=host, port=port)
            client.wait_server(timeout=60)
            client.close_current_project()
            client.create_project(f"amta-inpaint-{work_id}")
            page_id = client.import_page(raw_page)
            client.run_inpaint(page_id, {"segment": _build_mask(img, inpaint_boxes, refine=refine_mask),
                                         "bubble": _build_mask(img, inpaint_boxes, refine=refine_mask)},
                               engine=inpaint_engine)
            data = client.fetch_inpainted(page_id)
            if data:
                try:
                    inpainted = Image.open(io.BytesIO(data)).convert("RGB")
                    if inpainted.size == img.size:
                        img = inpainted  # 整页替换为 inpaint 结果
                except Exception as e:  # noqa: BLE001
                    print(f"[04_inpaint] WARN inpainted decode failed: {e}")
            else:
                print("[04_inpaint] WARN no inpainted result found")
        for p in filled:  # 贴回后重放涂白(保险)
            _apply_fill_white(img, p["bbox"])
        if clean_dir:
            clean_dir.mkdir(parents=True, exist_ok=True)
            page_key = out_path.stem.removesuffix("_inpaint")
            clean_path = clean_dir / f"{page_key}_clean.png"
            img.save(clean_path)

    doc = {
        "work_id": work_id,
        "page": det.get("page", raw_page.stem),
        "actions": plan,
        "checks": {
            "filled": len(filled),
            "inpainted": len(inpaint_boxes),
            "skipped": len(skipped),
            "size_ok": True,
            "refine_mask": refine_mask,
            "inpaint_engine": inpaint_engine,
            "pixel_diff_ratio": _pixel_diff_ratio(img, raw_img),
        },
        "dry_run": dry_run,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    write_json(out_path, doc)
    return doc


def main() -> int:
    ap = argparse.ArgumentParser(description="04_inpaint 工位")
    ap.add_argument("--work-id", required=True)
    ap.add_argument("--det", required=True, type=Path)
    ap.add_argument("--raw", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--clean-dir", type=Path, default=None)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--refine-mask", action="store_true",
                    help="框内传统方法精修像素级 mask (Plan A, 减少背景覆盖 70%+)")
    ap.add_argument("--engine", default="lama-manga", choices=["lama-manga", "aot-inpainting", "flux2-klein"],
                    help="inpaint 引擎 (默认 lama-manga)")
    a = ap.parse_args()
    doc = run(a.work_id, a.det, a.raw, a.out, clean_dir=a.clean_dir, dry_run=a.dry_run,
              refine_mask=a.refine_mask, inpaint_engine=a.engine)
    print(f"[04_inpaint] {doc['page']}: filled={doc['checks']['filled']} "
          f"inpainted={doc['checks']['inpainted']} skipped={doc['checks']['skipped']} "
          f"refine={doc['checks']['refine_mask']} engine={doc['checks']['inpaint_engine']} "
          f"diff={doc['checks']['pixel_diff_ratio']} -> {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

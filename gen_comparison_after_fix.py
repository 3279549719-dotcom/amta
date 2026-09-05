"""临时脚本：生成 p11-15 修复前后对比图（原图 vs 修复后 final）。

用法：cd "E:\manga translator agent" && python gen_comparison_after_fix.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "amta" / "src"))

from PIL import Image

ORIG_DIR = Path(r"D:\我的汉化\汉化作品\东方\单翼停留之地")
FINAL_DIR = Path("amta/workspace/touhou-e2e-orchestrator/artifacts/final")
OUT_DIR = Path("amta/output/comparison_after_fix")
OUT_DIR.mkdir(parents=True, exist_ok=True)

# page 11 = 10.jpg (off-by-one)
PAGE_TO_FILE = {11: "10.jpg", 12: "11.jpg", 13: "12.jpg", 14: "13.jpg", 15: "14.jpg"}


def main():
    for page in range(11, 16):
        orig_path = ORIG_DIR / PAGE_TO_FILE[page]
        final_path = FINAL_DIR / f"page_{page}_final.png"

        if not orig_path.exists() or not final_path.exists():
            print(f"SKIP p{page}: missing files")
            continue

        orig = Image.open(orig_path).convert("RGB")
        final = Image.open(final_path).convert("RGB")

        # 统一高度
        target_h = 1200
        orig_w = int(orig.width * target_h / orig.height)
        final_w = int(final.width * target_h / final.height)
        orig = orig.resize((orig_w, target_h), Image.LANCZOS)
        final = final.resize((final_w, target_h), Image.LANCZOS)

        # 并排
        gap = 20
        canvas = Image.new("RGB", (orig_w + final_w + gap, target_h + 40), "white")
        canvas.paste(orig, (0, 40))
        canvas.paste(final, (orig_w + gap, 40))

        # 标签
        from PIL import ImageDraw, ImageFont
        draw = ImageDraw.Draw(canvas)
        try:
            font = ImageFont.truetype("C:/Windows/Fonts/msyh.ttc", 20)
        except Exception:
            font = ImageFont.load_default()
        draw.text((10, 8), f"p{page} 原图", fill="black", font=font)
        draw.text((orig_w + gap + 10, 8), f"p{page} 修复后", fill="black", font=font)

        out_path = OUT_DIR / f"page_{page}_comparison.jpg"
        canvas.save(out_path, "JPEG", quality=85)
        print(f"  已生成: {out_path} ({canvas.width}x{canvas.height})")

    print("\n=== 对比图生成完成 ===")


if __name__ == "__main__":
    main()

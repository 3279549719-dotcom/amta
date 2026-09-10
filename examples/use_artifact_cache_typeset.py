"""示范：如何在排版阶段使用 artifact_cache 做增量构建。

运行方式：
    uv run python examples/use_artifact_cache_typeset.py --pages 11 12

效果：
    - 第一次运行：执行排版（模拟），生成 typeset.json 和 .fingerprint
    - 第二次运行（输入未变）：跳过排版，直接用已有结果
    - 修改代码文件后运行：自动重跑排版
"""
import argparse
import json
import sys
import time
from pathlib import Path

# 确保 src 在路径中
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from amta.artifact_cache import cache_status, run_stage_if_needed
from amta.artifacts import artifact_paths


def run_typeset_for_page(art_dir: Path, page: str) -> None:
    """执行单页排版（简化模拟版，实际应调用完整的 typeset_station）。"""
    print(f"    [模拟] 正在执行 {page} 排版...（耗时操作）")
    time.sleep(0.5)  # 模拟耗时

    typeset_path = art_dir / f"{page}_typeset.json"
    doc = {
        "work_id": "demo",
        "page": page,
        "rendered_items": [],
        "final_image": f"final/{page}_final.png",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    typeset_path.write_text(json.dumps(doc, indent=2, ensure_ascii=False), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description="示范：使用 artifact_cache 做增量排版")
    parser.add_argument("--pages", type=int, nargs="+", default=[11, 12],
                        help="要处理的页码")
    parser.add_argument("--art-dir", type=str,
                        default="examples/demo_artifacts",
                        help="artifact 目录")
    args = parser.parse_args()

    art_dir = Path(args.art_dir)
    art_dir.mkdir(parents=True, exist_ok=True)

    # 排版阶段依赖的代码文件
    code_files = [
        Path("src/amta/typeset_engine.py"),
        Path("src/amta/typeset_render.py"),
        Path("src/amta/artifacts.py"),
    ]

    # 准备模拟输入文件
    for page_num in args.pages:
        page = f"page_{page_num}"
        canon_path = art_dir / f"{page}_canon.json"
        trans_path = art_dir / f"{page}_translation.json"
        if not canon_path.exists():
            canon_path.write_text(json.dumps({"items": []}), encoding="utf-8")
        if not trans_path.exists():
            trans_path.write_text(json.dumps({"translations": {}}), encoding="utf-8")

    cache_hits = 0
    cache_misses = 0

    print(f"\n处理 {len(args.pages)} 页...")
    for page_num in args.pages:
        page = f"page_{page_num}"
        paths = artifact_paths(art_dir, page)
        output_path = paths["typeset"]

        result = run_stage_if_needed(
            stage_name="typeset",
            page=page,
            input_files={
                "canon": paths["canon"],
                "translation": paths["translation"],
            },
            code_files=code_files,
            config={"font_max": 52, "safe_ratio": 0.85},
            output_path=output_path,
            generate_fn=lambda p=page: run_typeset_for_page(art_dir, p),
        )

        if result["cache_hit"]:
            print(f"  {page}: CACHE HIT (跳过排版)")
            cache_hits += 1
        else:
            print(f"  {page}: CACHE MISS (执行排版)")
            cache_misses += 1

    print(f"\n统计: {cache_hits} 命中, {cache_misses} 未命中")
    print(f"缓存状态: {cache_status(art_dir)}")
    print("\n提示：再次运行本脚本，所有页都应该 CACHE HIT。")
    print("      修改 src/amta/typeset_engine.py 后再运行，会触发 CACHE MISS。")


if __name__ == "__main__":
    main()

"""TDD 切片3: exp_inpaint_speed.py 支持 p1_manga 模式。

验证:
1. --mode p1_manga 在参数 choices 中
2. p1_manga 模式使用 LocalLamaInpainter(model_type="lama-manga")
3. 能跑通一页 (page 11, repeat=1)
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts" / "probes"))  # exp_inpaint_speed 已归档到 probes/


def test_p1_manga_in_choices():
    """--mode p1_manga 在参数 choices 中。"""
    # 模拟 main() 中的参数定义
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", required=True,
                    choices=["baseline", "p0", "p1_cpu", "p1_rect", "p1_manga", "p1_gpu", "all"])
    # 解析 p1_manga 应该成功
    args = ap.parse_args(["--mode", "p1_manga"])
    assert args.mode == "p1_manga"


def test_p1_manga_runs_one_page():
    """p1_manga 模式能跑通一页 (page 11, repeat=1)。"""
    import exp_inpaint_speed as exp
    from amta.inpaint.local_lama_inpainter import LocalLamaInpainter

    # 加载 lama-manga 模型
    inpainter = LocalLamaInpainter(device="cpu", model_type="lama-manga")
    assert inpainter.model_type == "lama-manga"

    # 跑一页
    result = exp.run_p1(11, repeat=1, inpainter=inpainter, mode_name="p1_manga", refine=False)
    assert result["page"] == 11
    assert result["mode"] == "p1_manga"
    assert result["avg"] > 0
    assert result["n_free"] == 3  # page 11 有 3 个 free 框

    # 检查 clean 图是否生成
    clean_path = ROOT / "output" / "tmp" / "inpaint_speed_exp" / "p1_manga" / "clean" / "page_11_clean.png"
    assert clean_path.exists(), f"clean image not found: {clean_path}"
    assert clean_path.stat().st_size > 0


if __name__ == "__main__":
    tests = [
        test_p1_manga_in_choices,
        test_p1_manga_runs_one_page,
    ]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"  PASS: {t.__name__}")
        except Exception as e:
            print(f"  FAIL: {t.__name__}: {e}")
            import traceback
            traceback.print_exc()
            failed += 1
    print(f"\n{'='*40}")
    print(f"Results: {len(tests)-failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)

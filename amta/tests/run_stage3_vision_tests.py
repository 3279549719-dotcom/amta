"""轻量测试运行器 — 不依赖 pytest，运行 test_stage3_planner_vision.py。

用法: python tests/run_stage3_vision_tests.py
"""
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import test_stage3_planner_vision as test_mod


def run_tests():
    funcs = sorted((n, getattr(test_mod, n)) for n in dir(test_mod)
                   if n.startswith("test_") and callable(getattr(test_mod, n)))
    passed = failed = 0
    errors = []
    for name, func in funcs:
        try:
            func()
            passed += 1
            print(f"  PASS  {name}")
        except Exception as e:  # noqa: BLE001
            failed += 1
            errors.append((name, traceback.format_exc()))
            print(f"  FAIL  {name}: {e}")
    print(f"\n{'='*60}\nResults: {passed} passed, {failed} failed, {passed+failed} total")
    for name, tb in errors:
        print(f"\n--- {name} ---\n{tb}")
    return failed == 0


if __name__ == "__main__":
    sys.exit(0 if run_tests() else 1)

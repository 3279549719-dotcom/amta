"""测试桥：`from _00_run_all import run`（00_run_all.py 数字前缀无法按名 import）。

按文件路径加载真实脚本 scripts/00_run_all.py 并转导出 run/main。
"""
import importlib.util
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "_00_run_all_impl", Path(__file__).with_name("00_run_all.py"))
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

run = _mod.run
main = _mod.main

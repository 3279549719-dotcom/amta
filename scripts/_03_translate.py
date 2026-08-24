"""测试桥：`from _03_translate import run`（03_translate.py 数字前缀无法按名 import）。

tests/test_translate.py 用 `from _03_translate import run` 复用同一实现；
本文件按文件路径加载真实脚本 scripts/03_translate.py 并转导出 run/main。
"""
import importlib.util
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "_03_translate_impl", Path(__file__).with_name("03_translate.py")
)
assert _spec is not None and _spec.loader is not None
_impl = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(_impl)

run = _impl.run
main = _impl.main

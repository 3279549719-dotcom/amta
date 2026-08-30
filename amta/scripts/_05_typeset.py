"""测试桥：`from _05_typeset import run`（05_typeset.py 数字前缀无法按名 import）。

tests 用 exec 加载同一实现。
"""
import importlib.util
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "_05_typeset_impl", Path(__file__).with_name("05_typeset.py")
)
assert _spec is not None and _spec.loader is not None
_impl = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(_impl)

run = _impl.run
main = _impl.main

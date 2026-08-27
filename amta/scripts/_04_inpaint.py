"""测试桥：`from _04_inpaint import run`（04_inpaint.py 数字前缀无法按名 import）。"""
import importlib.util
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "_04_inpaint_impl", Path(__file__).with_name("04_inpaint.py")
)
assert _spec is not None and _spec.loader is not None
_impl = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(_impl)

run = _impl.run
main = _impl.main

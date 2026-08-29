"""轻量测试运行器 — 运行 test_translate.py 回归测试。"""
import sys
import traceback
import tempfile
import shutil
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import test_translate as test_mod


class MonkeyPatch:
    def __init__(self):
        self._undo = []
    def setattr(self, *args):
        if len(args) == 3:
            target, name, value = args
            old = getattr(target, name)
            self._undo.append((target, name, old))
            setattr(target, name, value)
        elif len(args) == 2:
            path, value = args
            parts = path.split(".")
            module_path = ".".join(parts[:-1])
            attr_name = parts[-1]
            import importlib
            target = importlib.import_module(module_path)
            old = getattr(target, attr_name)
            self._undo.append((target, attr_name, old))
            setattr(target, attr_name, value)
    def undo(self):
        for target, name, old in reversed(self._undo):
            setattr(target, name, old)


def run_tests():
    import inspect
    test_funcs = [(name, getattr(test_mod, name)) for name in dir(test_mod)
                  if name.startswith("test_") and callable(getattr(test_mod, name))]
    test_funcs.sort(key=lambda x: x[0])

    passed = 0
    failed = 0
    errors = []

    for name, func in test_funcs:
        sig = inspect.signature(func)
        params = list(sig.parameters.keys())
        kwargs = {}
        tmp_dir = None
        if "tmp_path" in params:
            tmp_dir = Path(tempfile.mkdtemp())
            kwargs["tmp_path"] = tmp_dir
        if "monkeypatch" in params:
            kwargs["monkeypatch"] = MonkeyPatch()

        try:
            func(**kwargs)
            passed += 1
            print(f"  PASS  {name}")
        except Exception as e:
            failed += 1
            tb = traceback.format_exc()
            errors.append((name, str(e), tb))
            print(f"  FAIL  {name}: {e}")
        finally:
            if "monkeypatch" in kwargs:
                kwargs["monkeypatch"].undo()
            if tmp_dir:
                shutil.rmtree(tmp_dir, ignore_errors=True)

    print(f"\n{'='*60}")
    print(f"Regression: {passed} passed, {failed} failed, {passed+failed} total")
    if errors:
        for name, err, tb in errors:
            print(f"\n--- {name} ---")
            print(tb)
    return failed == 0


if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)

"""fastcheck — 编码期快速校验（Level 1，秒级，不连 koharu）。

组合：
  1. compileall（src + scripts 语法门）
  2. ruff lint（代码风格/未使用导入）
  3. pyright type check（类型错误）
  4. 确定性单测（tests/，纯数据，不依赖引擎/网络）

等价于 `npm run check` + lint + typecheck + `npm run test`，合并为一条命令。
退出码：0 = 全过；非 0 = 有失败。
"""
from __future__ import annotations

import compileall
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _run(cmd: list[str], label: str) -> int:
    print(f"== [fastcheck] {label} ==")
    r = subprocess.call(cmd, cwd=str(ROOT))
    print(f"== {label}: {'OK' if r == 0 else 'FAIL'} ==")
    return r


def _compile() -> int:
    ok = compileall.compile_dir(str(ROOT / "src"), quiet=1, force=True)
    ok = compileall.compile_dir(str(ROOT / "scripts"), quiet=1, force=True) and ok
    return 0 if ok else 1


def _lint() -> int:
    py = shutil.which("ruff") or shutil.which("py") or sys.executable
    if py.endswith("ruff.exe") or Path(py).name == "ruff":
        return _run([py, "check", "src", "scripts", "tests"], "ruff lint")
    # ruff 作为 python 模块
    return _run([sys.executable, "-m", "ruff", "check", "src", "scripts", "tests"], "ruff lint")


def _typecheck() -> int:
    pyright = shutil.which("pyright")
    if not pyright:
        print("== [fastcheck] pyright 未安装，跳过 type check ==")
        return 0
    return _run([pyright, "src"], "pyright type check")


def _test() -> int:
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    return subprocess.call(
        [sys.executable, "-m", "unittest", "discover", "-s", str(ROOT / "tests"), "-v"],
        cwd=str(ROOT),
        env=env,
    )


def main() -> int:
    c = _compile()
    lint_rc = _lint()
    t = _typecheck()
    u = _test()
    fails = [name for name, rc in (("compile", c), ("lint", lint_rc), ("typecheck", t), ("unit tests", u)) if rc]
    if fails:
        print(f"== [fastcheck] FAIL: {', '.join(fails)} ==")
        return 1
    print("== [fastcheck] ALL PASS ==")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

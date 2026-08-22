"""fastcheck — 编码期快速校验（Level 1，秒级，不连 koharu）。

组合：
  1. compileall（src + scripts 语法门）
  2. 确定性单测（tests/，纯数据，不依赖引擎/网络）

等价于 `npm run check` + `npm run test`，但合并为一条命令、更适合编辑后随手跑。
退出码：0 = 全过；非 0 = 有失败。
"""
from __future__ import annotations

import compileall
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _compile() -> int:
    ok = compileall.compile_dir(str(ROOT / "src"), quiet=1, force=True)
    ok = compileall.compile_dir(str(ROOT / "scripts"), quiet=1, force=True) and ok
    return 0 if ok else 1


def _test() -> int:
    env = {**__import__("os").environ, "PYTHONDONTWRITEBYTECODE": "1"}
    return subprocess.call(
        [sys.executable, "-m", "unittest", "discover", "-s", str(ROOT / "tests"), "-v"],
        cwd=str(ROOT),
        env=env,
    )


def main() -> int:
    print("== [fastcheck] compile ==")
    c = _compile()
    print(f"== compile: {'OK' if c == 0 else 'FAIL'} ==")
    print("== [fastcheck] unit tests ==")
    t = _test()
    print(f"== unit tests: {'OK' if t == 0 else 'FAIL'} ==")
    return c if c else t


if __name__ == "__main__":
    raise SystemExit(main())

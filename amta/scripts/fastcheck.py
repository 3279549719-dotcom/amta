"""fastcheck — 编码期快速校验（Level 1，秒级，不连 koharu）。

组合：
  1. compileall（src + scripts 语法门）
  2. ruff lint（代码风格/未使用导入）
  3. pyright type check（类型错误）
  4. 确定性单测（tests/，纯数据，不依赖引擎/网络）
  5. depguard（依赖膨胀守卫：未声明/未使用第三方依赖拦截，ADR-015）

等价于 `npm run check` + lint + typecheck + `npm run test` + depguard，
合并为一条命令。退出码：0 = 全过；非 0 = 有失败。
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
    """跑 tests/ 单测。tests/ 是 pytest 风格（模块级 test_* 函数 + tmp_path/monkeypatch fixtures）；
    `unittest discover` 只收 TestCase 类会静默跳过模块级函数（曾致 translate/workstate 测试不跑却报 PASS，L19/L20）。
    Windows 下 pytest 尾部 PermissionError: pytest-current 是 tmp_path teardown 噪音（L19），
    结果以汇总行 "N passed" 判定，不以 exit code 判定。
    """
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    # --basetemp 规避 Windows 下 pytest 默认 basetemp 的 pytest-current symlink teardown
    # PermissionError（L19）：指定显式目录后 pytest 不建该 symlink，正常输出 "N passed" 汇总并退出 0。
    basetemp = ROOT / "output" / "logs" / ".pytest-basetemp"
    r = subprocess.run(
        [sys.executable, "-m", "pytest", str(ROOT / "tests"), "-q", "--basetemp", str(basetemp)],
        cwd=str(ROOT), env=env, capture_output=True, text=True,
    )
    out = (r.stdout or "") + (r.stderr or "")
    print(out[-2000:])
    import re as _re
    m = _re.search(r"(\d+) passed", out)
    failed = _re.search(r"(\d+) failed", out)
    if m and not failed:
        print(f"== [fastcheck] pytest: {m.group(1)} passed ==")
        return 0
    print(f"== [fastcheck] pytest 无通过汇总（exit {r.returncode}）==")
    return 1


def _depguard() -> int:
    """依赖膨胀守卫（ADR-015）：拦截未声明/未使用的第三方依赖。"""
    return _run([sys.executable, str(ROOT / "scripts" / "depguard.py")], "depguard (依赖膨胀守卫)")


def _memory_lint() -> int:
    """记忆机制活性门（ADR-025）：staleness/幽灵路径/注入预算。strict：FAIL → 1。"""
    return _run([sys.executable, str(ROOT / "scripts" / "memory_lint.py"), "--strict"], "memory lint (ADR-025)")


def _memory_gc() -> int:
    """记忆地产 GC 活性检查：dry-run 验证 GC 可用、不真改文件（腐坏由 CLAUDE.md 协议在收尾时真跑清理）。"""
    return _run([sys.executable, str(ROOT / "scripts" / "memory_gc.py"), "--dry-run"], "memory gc (dry-run)")


def _memory_inject() -> int:
    """DSH 记忆推送层活性：重新生成 amta/CLAUDE.local.md（agent-instructions 自动注入的本地 overlay）。

    写模式：幂等重跑，只刷新 .gitignore 已覆盖（*.local）的生成文件，不碰 docs/ 权威源。
    既验证记忆包可构建，又保证每轮验证后注入包保持新鲜。"""
    return _run([sys.executable, str(ROOT / "scripts" / "memory_inject.py")], "memory inject (CLAUDE.local.md)")


def main() -> int:
    c = _compile()
    lint_rc = _lint()
    t = _typecheck()
    u = _test()
    d = _depguard()
    m = _memory_lint()
    g = _memory_gc()
    inj = _memory_inject()
    fails = [name for name, rc in (("compile", c), ("lint", lint_rc), ("typecheck", t), ("unit tests", u), ("depguard", d), ("memory lint", m), ("memory gc", g), ("memory inject", inj)) if rc]
    if fails:
        print(f"== [fastcheck] FAIL: {', '.join(fails)} ==")
        return 1
    print("== [fastcheck] ALL PASS ==")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

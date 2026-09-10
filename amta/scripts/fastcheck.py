"""fastcheck — 机械质检（分层：--quick 秒级 / 默认完整 8 步）。

两种模式（2026-09-10 分层，避免 pre-commit 与 /finish 重复跑 pytest）：
  --quick  秒级快检（pre-commit 钩子用）：compileall + ruff lint + pyright
  默认     完整 8 步（/finish 收尾用）：quick 三步 + pytest + depguard + mem-lint/gc/inject

退出码：0 = 全过；非 0 = 有失败。
"""
from __future__ import annotations

import argparse
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
    if py.lower().endswith("ruff.exe") or Path(py).name.lower() == "ruff":
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
    # PermissionError（L19）：指定显式目录后 pytest 不建该 symlink。
    # 每次用 pid 唯一目录（2026-09-10 修复）：固定目录一旦权限损坏（WinError 5 僵尸目录，
    # 连 icacls/rd 都删不掉），teardown 失败会让每个文件首个用例后的全部用例 ERROR
    # （436 passed 退化为 253 passed+183 ERROR）；唯一目录跑完即弃，坏目录无法再污染。
    basetemp = ROOT / "output" / "logs" / f".pytest-bt-{os.getpid()}"
    r = subprocess.run(
        [sys.executable, "-m", "pytest", str(ROOT / "tests"), "-q", "--basetemp", str(basetemp)],
        cwd=str(ROOT), env=env, capture_output=True, text=True,
    )
    out = (r.stdout or "") + (r.stderr or "")
    shutil.rmtree(basetemp, ignore_errors=True)  # best-effort: 删不掉不影响（下次换 pid 新目录）
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
    """依赖膨胀守卫（ADR-015）：拦截未声明/未使用第三方依赖。"""
    return _run([sys.executable, str(ROOT / "scripts" / "depguard.py")], "depguard (依赖膨胀守卫)")


def _memory_lint() -> int:
    """记忆机制活性门（ADR-025）：staleness/幽灵路径/注入预算。strict：FAIL → 1。"""
    return _run([sys.executable, str(ROOT / "scripts" / "memory.py"), "lint", "--strict"], "memory lint (ADR-025)")


def _memory_gc() -> int:
    """记忆地产 GC 活性检查：dry-run 验证 GC 可用、不真改文件（腐坏由 CLAUDE.md 协议在收尾时真跑清理）。"""
    return _run([sys.executable, str(ROOT / "scripts" / "memory.py"), "gc", "--dry-run"], "memory gc (dry-run)")


def _memory_inject() -> int:
    """DSH 记忆推送层活性：重新生成 amta/CLAUDE.local.md（agent-instructions 自动注入的本地 overlay）。

    写模式：幂等重跑，只刷新 .gitignore 已覆盖（*.local）的生成文件，不碰 docs/ 权威源。
    既验证记忆包可构建，又保证每轮验证后注入包保持新鲜。"""
    return _run([sys.executable, str(ROOT / "scripts" / "memory.py"), "inject"], "memory inject (CLAUDE.local.md)")


def main() -> int:
    ap = argparse.ArgumentParser(description="amta fastcheck 机械质检")
    ap.add_argument("--quick", action="store_true",
                    help="only compile/lint/typecheck (seconds, used by pre-commit); full 8-step is for /finish")
    args = ap.parse_args()

    c = _compile()
    lint_rc = _lint()
    t = _typecheck()
    checks: list[tuple[str, int]] = [
        ("compile", c),
        ("lint", lint_rc),
        ("typecheck", t),
    ]
    if not args.quick:
        u = _test()
        d = _depguard()
        m = _memory_lint()
        g = _memory_gc()
        inj = _memory_inject()
        checks.extend([
            ("unit tests", u),
            ("depguard", d),
            ("memory lint", m),
            ("memory gc", g),
            ("memory inject", inj),
        ])
    else:
        print("== [fastcheck] --quick: skip pytest/depguard/memory (full run at /finish) ==")
    fails = [name for name, rc in checks if rc]
    if fails:
        print(f"== [fastcheck] FAIL: {', '.join(fails)} ==")
        return 1
    print("== [fastcheck] QUICK PASS ==" if args.quick else "== [fastcheck] ALL PASS ==")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

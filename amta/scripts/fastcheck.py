"""fastcheck — 编码期快速校验（Level 1，秒级，默认不连 koharu）。

组合：
  1. compileall（src + scripts 语法门）
  2. ruff lint（代码风格/未使用导入）
  3. pyright type check（类型错误）
  4. 确定性单测（tests/，纯数据，不依赖引擎/网络）
  5. depguard（依赖膨胀守卫：未声明/未使用第三方依赖拦截，ADR-015）

可选 L5 端到端门：`--with-e2e` 追加探测 koharu :4000 —
  可达 → 跑 scripts/smoke_test.py（连通引擎→建项目→传图→检测→读场景→关项目，必须 PASS）；
  不可达且本次改动涉及引擎面（koharu_client/koharu_blocks/pipeline/runner/smoke_test）→ FAIL
  （堵"引擎改动没验证就提交"的洞，ADR-030）；不可达且不涉及引擎面 → SKIPPED（不算失败）。

等价于 `npm run check` + lint + typecheck + `npm run test` + depguard [+ e2e]，
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


def _port_open(host: str, port: int, timeout: float = 2.0) -> bool:
    """探测 TCP 端口（stdlib only）。"""
    import socket

    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _changed_files() -> set[str]:
    """收集本次改动文件：工作区（未暂存 + 已暂存）+ main...HEAD（已提交）。git 不可用/出错时返回空集。"""
    changed: set[str] = set()
    if not shutil.which("git"):
        return changed
    for cmd in (
        ["git", "diff", "--name-only", "HEAD"],
        ["git", "diff", "--cached", "--name-only"],
        ["git", "diff", "--name-only", "main...HEAD"],
    ):
        try:
            r = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True, timeout=30)
        except (OSError, subprocess.SubprocessError):
            continue
        if r.returncode == 0:
            changed.update(p.strip() for p in r.stdout.splitlines() if p.strip())
    return changed


# L5 引擎面判定：只认 src/ 与 scripts/ 下的代码改动。纯文档（.dsh/docs/ADR）不算引擎面，
# 避免引擎未启动时文档改动被误判 FAIL（L6 review 首跑实测发现）。token 匹配文件名。
ENGINE_SURFACE_TOKENS = ("koharu", "pipeline", "runner", "smoke")


def _engine_surface_changed() -> list[str]:
    """本次改动中触及引擎面的代码文件（L5 判定用）。"""
    changed = []
    for p in _changed_files():
        parts = Path(p).parts
        if "src" not in parts and "scripts" not in parts:
            continue  # 非代码目录（docs/.dsh/ADR）不算引擎面
        if any(tok in Path(p).name for tok in ENGINE_SURFACE_TOKENS):
            changed.append(p)
    return sorted(changed)


def _smoke() -> int:
    """L5 端到端门（--with-e2e）：koharu 可达 → 跑 smoke_test.py 必须 PASS；
    不可达且改引擎面 → FAIL（堵"引擎改动没验证就提交"）；不可达且不涉引擎面 → SKIPPED(0)。"""
    if not _port_open("127.0.0.1", 4000):
        touched = _engine_surface_changed()
        if touched:
            print(f"== [fastcheck] e2e FAIL: koharu :4000 未启动，但本次改动涉及引擎面：{', '.join(touched)} ==")
            print("== [fastcheck] 请先 `npm start` 启动 koharu，再重跑 `fastcheck.py --with-e2e` 完成 L5 验证 ==")
            return 1
        print("== [fastcheck] e2e SKIPPED: koharu :4000 未启动，且本次改动不涉及引擎面（L5 无需跑）==")
        return 0
    print("== [fastcheck] e2e: koharu :4000 可达，跑 smoke_test.py ==")
    uv = shutil.which("uv")
    if uv:
        cmd = [uv, "run", "python", str(ROOT / "scripts" / "smoke_test.py")]
    else:
        cmd = [sys.executable, str(ROOT / "scripts" / "smoke_test.py")]
    return _run(cmd, "e2e smoke (koharu 通路)")


def main() -> int:
    with_e2e = "--with-e2e" in sys.argv[1:]
    c = _compile()
    lint_rc = _lint()
    t = _typecheck()
    u = _test()
    d = _depguard()
    m = _memory_lint()
    g = _memory_gc()
    inj = _memory_inject()
    checks: list[tuple[str, int]] = [
        ("compile", c),
        ("lint", lint_rc),
        ("typecheck", t),
        ("unit tests", u),
        ("depguard", d),
        ("memory lint", m),
        ("memory gc", g),
        ("memory inject", inj),
    ]
    if with_e2e:
        checks.append(("e2e smoke", _smoke()))
    fails = [name for name, rc in checks if rc]
    if fails:
        print(f"== [fastcheck] FAIL: {', '.join(fails)} ==")
        return 1
    print("== [fastcheck] ALL PASS ==")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

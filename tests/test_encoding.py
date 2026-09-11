"""test_encoding — Windows 编码收口的回归测试（2026-09-10 事故驱动）。

两个真实事故：
1. `import amta` 后 CLI 的 stdout 仍是宿主 locale（cp936/gbk），而 DSH/管道按 UTF-8 读
   → 所有中文输出到达 agent 侧变成 `�ؼ���` 乱码 → agent 放弃深接口改用 read/grep。
2. `subprocess.run(..., text=True)` 不解码失败会**静默返回 stdout=None**（不抛异常），
   且默认用 locale 解码 → 中文 commit message 直接炸掉 `state.py bootstrap`。

本文件锁定这两条不变量：
- 包导入即归一化 stdio 为 UTF-8（收口点在 `amta/__init__.py`，新脚本自动继承）
- 跨进程文本一律走 `run_text` / `run_text_or`，不再依赖宿主 locale，也永不返回 None
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from amta.common.encoding import run_text, run_text_or

REPO_ROOT = Path(__file__).resolve().parent.parent


def _child_env() -> dict[str, str]:
    """子进程环境：强制回到 locale 模式，模拟真实 `uv run python scripts/x.py` 现场。"""
    env = dict(os.environ)
    env["PYTHONPATH"] = str(REPO_ROOT / "src")
    env["PYTHONUTF8"] = "0"
    env["PYTHONIOENCODING"] = ""
    return env


class TestStdioChokePoint:
    """包导入即生效的 stdio 归一化。"""

    def test_import_amta_makes_stdout_utf8(self):
        """import amta 之后，中文必须以 UTF-8 字节穿出管道（而不是 locale 编码）。"""
        code = "import amta, sys; sys.stdout.write('中文测试')"
        proc = subprocess.run(
            [sys.executable, "-c", code], capture_output=True, env=_child_env(), check=False,
        )
        assert proc.returncode == 0, proc.stderr
        assert proc.stdout.decode("utf-8") == "中文测试"

    def test_without_import_amta_stdout_is_locale(self):
        """反证：不加 import，宿主 locale 会把中文写成非 UTF-8 字节。

        这条是上面那条的对照——如果哪天宿主默认变成 UTF-8，本测试会失败，
        提醒我们"收口点已无意义"，而不是让它假装还在保护什么。
        """
        code = "import sys; sys.stdout.write('中文测试')"
        proc = subprocess.run(
            [sys.executable, "-c", code], capture_output=True, env=_child_env(), check=False,
        )
        assert proc.returncode == 0, proc.stderr
        if sys.platform == "win32" and (proc.stdout.decode("utf-8", errors="replace") == "中文测试"):
            pytest.skip("宿主已是 UTF-8 默认，对照条件不成立")


class TestRunText:
    """run_text：跨进程文本读取的唯一入口。"""

    def test_decodes_utf8_child_output(self):
        """子进程输出 UTF-8 时原样读回。"""
        code = "import sys; sys.stdout.reconfigure(encoding='utf-8'); sys.stdout.write('中文 OK')"
        result = run_text([sys.executable, "-c", code])
        assert result.returncode == 0
        assert result.stdout == "中文 OK"

    def test_undecodable_bytes_do_not_crash_or_return_none(self):
        """无法解码的字节必须降级为替换字符，绝不崩、绝不返回 None。"""
        code = "import sys; sys.stdout.buffer.write(b'\\xff\\xfe bad')"
        result = run_text([sys.executable, "-c", code])
        assert result.returncode == 0
        assert result.stdout is not None
        assert "bad" in result.stdout

    def test_never_returns_none_stdout(self):
        """stdout 为 None 的历史事故（AttributeError: 'NoneType'）不再可能。"""
        result = run_text([sys.executable, "-c", "pass"])
        assert isinstance(result.stdout, str)
        assert isinstance(result.stderr, str)

    def test_check_raises_called_process_error(self):
        """check=True 保持 subprocess 语义。"""
        with pytest.raises(subprocess.CalledProcessError):
            run_text([sys.executable, "-c", "import sys; sys.exit(3)"], check=True)


class TestRunTextOr:
    """run_text_or：失败即降级为默认值，调用方不再写 try/except 样板。"""

    def test_returns_stdout_on_success(self):
        assert run_text_or([sys.executable, "-c", "print('hi')"]).strip() == "hi"

    def test_returns_default_on_nonzero_exit(self):
        assert run_text_or([sys.executable, "-c", "import sys; sys.exit(1)"], default="") == ""

    def test_returns_default_when_command_missing(self):
        assert run_text_or(["definitely-not-a-real-binary-xyz"], default="unknown") == "unknown"

    def test_returns_default_on_timeout(self):
        code = "import time; time.sleep(5)"
        assert run_text_or([sys.executable, "-c", code], timeout=0.2, default="timeout") == "timeout"


# ------------------------------------------------- 系统守卫：不许再长出裸 text=True
#
# 为什么加这条（2026-09-11 实测）：
# 同一个坑在这一天**第三次复发**——新写的 `tests/test_artifact_cli.py` 里
# `subprocess.run(..., text=True)` 读中文 stderr，解码在线程里炸掉、stderr 静默变
# None，断言 `result.stderr.lower()` 抛 AttributeError，全量门 501 passed → 1 failed。
#
# 前两次（state.py bootstrap、run_text 收口）都是**逐点修复**，所以坑又长回来了。
# 这条守卫把「逐点修」升级为「系统性拦截」：直接扫源码，发现裸 text=True 就红。

# 允许保留的白名单：这些调用**只读 ASCII**（git config 值、本机路径），
# 不接触中文，改造它们的收益为负（引入 amta 依赖反而扩大耦合面）。
_ALLOWED_BARE_TEXT_TRUE = {
    # 只读 git config（ASCII 路径/布尔值）
    ("tests/test_lessons_guard.py", "subprocess.run"),
    ("tests/test_state_manager.py", "subprocess.run"),
    ("tests/test_ralph_context.py", "subprocess.run"),
    # hook 脚本：调用方是 CC 方言的 hook 运行时，输出是 JSON（ASCII）
    ("scripts/hook_pretooluse.py", "subprocess.run"),
    ("scripts/hook_sessionstart.py", "subprocess.run"),
    # fastcheck 的 pytest 调用：输出含中文，但它自己解析 "N passed"（ASCII 正则）
    ("scripts/fastcheck.py", "subprocess.run"),
}

_BARE_TEXT_TRUE_OWNERS = {"subprocess.run", "subprocess.Popen", "_sp.run", "sp.run"}


def _bare_text_true_calls(path: Path) -> list[tuple[int, str]]:
    """AST 找出「有 text=True 但没有 encoding=」的 subprocess 调用。

    用 AST 而不是正则：正则会被 docstring 里描述这个坑的**说明文字**误伤
    （本仓库已经因为"把提及当成引用"假红过两次，见 test_reference_integrity）。
    """
    import ast

    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError):
        return []

    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        # 归一化被调用者名字：subprocess.run / _sp.run / sp.run
        if isinstance(fn, ast.Attribute):
            name = fn.attr
            owner = getattr(fn.value, "id", "") or getattr(fn.value, "attr", "")
            dotted = f"{owner}.{name}" if owner else name
        elif isinstance(fn, ast.Name):
            dotted = fn.id
        else:
            continue
        if dotted not in _BARE_TEXT_TRUE_OWNERS:
            continue
        kwargs = {k.arg for k in node.keywords if k.arg}
        if "text" not in kwargs and "universal_newlines" not in kwargs:
            continue
        if "encoding" in kwargs:
            continue
        found.append((node.lineno, dotted))
    return found


class TestNoBareTextTrueInLiveCode:
    """活代码里不许出现「text=True 但没有 encoding=」——那是 Windows 上的静默炸弹。"""

    def _scan(self) -> list[str]:
        offenders: list[str] = []
        for base in ("src", "scripts", "tests"):
            for path in (REPO_ROOT / base).rglob("*.py"):
                if "__pycache__" in path.parts or ".venv" in path.parts:
                    continue
                rel = path.relative_to(REPO_ROOT).as_posix()
                for lineno, dotted in _bare_text_true_calls(path):
                    if (rel, dotted) in _ALLOWED_BARE_TEXT_TRUE:
                        continue
                    offenders.append(f"{rel}:{lineno} → {dotted}(text=True) 缺 encoding=")
        return offenders

    def test_no_bare_text_true(self):
        offenders = self._scan()
        assert not offenders, (
            "发现裸 `text=True`（缺 encoding=）：Windows 上按 cp936 解码中文会在线程内\n"
            "抛 UnicodeDecodeError 并被吞掉，导致 stdout/stderr **静默变成 None**，\n"
            "下游 `.lower()` / `.strip()` 抛 AttributeError（2026-09-11 实测复发）。\n"
            "修法：改用 `amta.common.encoding.run_text` / `run_text_or`，\n"
            "或就地加 `encoding=\"utf-8\", errors=\"replace\"`。\n  " + "\n  ".join(offenders)
        )

    def test_scanner_actually_detects_violations(self, tmp_path):
        """守卫必须真的能红——用一个人造违规文件证明扫描器不是空转。"""
        bad = tmp_path / "bad_module.py"
        bad.write_text(
            "import subprocess\n"
            "def f():\n"
            "    return subprocess.run(['git', 'log'], capture_output=True, text=True)\n",
            encoding="utf-8",
        )
        assert _bare_text_true_calls(bad), "扫描器没能识别人造违规——守卫是空转的"

    def test_scanner_accepts_compliant_call(self, tmp_path):
        """对照组：带 encoding= 的调用不该被报。"""
        good = tmp_path / "good_module.py"
        good.write_text(
            "import subprocess\n"
            "def f():\n"
            "    return subprocess.run(['git', 'log'], capture_output=True,\n"
            "                          text=True, encoding='utf-8', errors='replace')\n",
            encoding="utf-8",
        )
        assert not _bare_text_true_calls(good), "带 encoding= 的合规调用被误报"

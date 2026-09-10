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

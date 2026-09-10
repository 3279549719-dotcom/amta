"""encoding — Windows 编码收口：跨边界文本只在这里处理一次。

两类边界，两个入口：

1. **进程内**（`force_utf8_stdio`）：stdout/stderr 固定输出 UTF-8 字节。
   Windows 上 Python 对管道默认用宿主 locale（cp936/gbk）编码，而 DSH/管道按 UTF-8 读
   → 中文输出到达 agent 侧变成 `�ؼ���`，agent 读不懂就只能退回 read/grep 这类原始工具。

2. **跨进程**（`run_text` / `run_text_or`）：不再用 `subprocess.run(text=True)`。
   它有两个致命行为：按宿主 locale 解码（读不了中文 commit），以及解码失败时
   **在 reader thread 里静默把 stdout 变成 None 而不抛异常**。这里改为抓字节 +
   显式 UTF-8 解码（`errors="replace"`），返回类型永远是 `str`。

为什么必须收口成一处：2026-09-10 的现场是同一 bug 的两副面孔——
`memory/tools.py` 已经手动加了 `encoding="utf-8"`，而 `common/state_manager.py` 没加，
于是 `state.py bootstrap` 一调用就 `AttributeError: 'NoneType' has no attribute 'strip'`。
修复只该存在一处。

契约：子进程必须输出 UTF-8（git / python / 本仓库脚本都满足）。
"""
from __future__ import annotations

import io
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

__all__ = ["TextResult", "force_utf8_stdio", "run_text", "run_text_or"]


@dataclass(frozen=True)
class TextResult:
    """跨进程文本读取结果：stdout/stderr 永远是 str，永远不是 None。"""

    returncode: int
    stdout: str
    stderr: str
    cmd: tuple[str, ...] = field(default=())


def _decode(raw: bytes | None) -> str:
    """字节 → str。None 变空串，非法序列降级为替换字符（绝不抛、绝不 None）。"""
    if not raw:
        return ""
    return raw.decode("utf-8", errors="replace")


def run_text(
    cmd: list[str] | tuple[str, ...],
    *,
    cwd: Path | str | None = None,
    timeout: float | None = None,
    check: bool = False,
    env: dict[str, str] | None = None,
) -> TextResult:
    """跑命令并返回 UTF-8 解码后的文本结果。

    Args:
        cmd: 命令与参数。
        cwd: 工作目录。None 表示继承当前目录。
        timeout: 秒；超时抛 `subprocess.TimeoutExpired`。
        check: True 时非零退出抛 `subprocess.CalledProcessError`（与 subprocess 同语义）。
        env: 环境变量。None 表示继承。

    Returns:
        TextResult: returncode / stdout / stderr / cmd。

    Raises:
        OSError: 命令不存在等。
        subprocess.TimeoutExpired: 超时。
        subprocess.CalledProcessError: check=True 且退出码非零。
    """
    argv = [str(part) for part in cmd]
    proc = subprocess.run(
        argv,
        cwd=None if cwd is None else str(cwd),
        env=env,
        capture_output=True,
        timeout=timeout,
    )
    result = TextResult(
        returncode=proc.returncode,
        stdout=_decode(proc.stdout),
        stderr=_decode(proc.stderr),
        cmd=tuple(argv),
    )
    if check and result.returncode != 0:
        raise subprocess.CalledProcessError(
            result.returncode, argv, output=result.stdout, stderr=result.stderr,
        )
    return result


def run_text_or(
    cmd: list[str] | tuple[str, ...],
    *,
    cwd: Path | str | None = None,
    timeout: float | None = None,
    default: str = "",
) -> str:
    """跑命令，成功返回 stdout，否则返回 `default`（调用方不再写 try/except 样板）。

    失败包括：命令不存在、超时、退出码非零。只读探针场景（读 git 状态）用它，
    失败不应该是致命的——状态读取失败降级即可，不能让整个 CLI 崩掉。
    """
    try:
        result = run_text(cmd, cwd=cwd, timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return default
    return result.stdout if result.returncode == 0 else default


def force_utf8_stdio() -> bool:
    """把 stdout/stderr 固定为 UTF-8（已是 UTF-8 则不动）。

    这是包级收口点，由 `amta/__init__.py` 在导入时调用，因此**新增脚本自动继承**，
    不依赖任何人记得写那三行 `reconfigure`。对不支持 reconfigure 的流
    （pytest 替换的捕获流、已关闭的流）静默跳过。

    Returns:
        bool: 是否真的改动过至少一个流（便于测试与诊断）。
    """
    changed = False
    for stream in (sys.stdout, sys.stderr):
        if stream is None:
            continue
        try:
            current = (getattr(stream, "encoding", None) or "").lower().replace("-", "")
            if current == "utf8":
                continue
            cast(Any, stream).reconfigure(encoding="utf-8", errors="replace")
            changed = True
        except (AttributeError, ValueError, OSError, io.UnsupportedOperation):
            continue
    return changed

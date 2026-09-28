"""GUI 启动时的控制台 / 日志加固（根因修复）。

背景
----
流水线在后台线程里同步 ``print()``，uvicorn 也往 stdout 写访问日志。
Windows 控制台一旦被鼠标点进"标记模式"（QuickEdit 选中文字），**所有**
往 stdout 的写都会阻塞；于是后台线程僵在某句 ``print`` 上，表现为 typeset
永远不开始、网页一直转圈。主线程写访问日志时也会一起卡死。

修法（防御纵深，不依赖用户"别点终端"）：
  1. stdout/stderr 改成"以日志文件为主"：同步写文件（文件写不会像控制台那样
     冻住），屏幕回显丢进有界队列，由后台守护线程慢慢刷。控制台就算冻死，
     丢的只是屏幕回显，流水线不反压。
  2. Windows 下关掉控制台的 QuickEdit，从根上避免"点一下就冻结输出"。
"""
from __future__ import annotations

import os
import queue
import sys
import threading
import time
from pathlib import Path

from amta.common.paths import ROOT

_LOG_DIR = ROOT / "logs"
# 控制台冻死时，最多在队列里攒这么多行回显；之后丢弃，防止内存无限涨。
_MAX_QUEUED_LINES = 2000


def _disable_windows_quick_edit() -> None:
    """关掉控制台 QuickEdit：鼠标点进去选文字不再冻结 stdout。非 Windows 直接返回。"""
    if os.name != "nt":
        return
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32
        STD_INPUT_HANDLE = -10
        ENABLE_QUICK_EDIT_MODE = 0x0040
        ENABLE_EXTENDED_FLAGS = 0x0080  # 改 QuickEdit 必须先开扩展标志
        handle = kernel32.GetStdHandle(STD_INPUT_HANDLE)
        mode = ctypes.c_uint32()
        if not kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            return
        new_mode = (mode.value & ~ENABLE_QUICK_EDIT_MODE) | ENABLE_EXTENDED_FLAGS
        kernel32.SetConsoleMode(handle, new_mode)
    except Exception:
        # 没有控制台（detached / 输出已被重定向）就跳过
        pass


def install_gui_console() -> Path:
    """在 uvicorn 启动前调用：加固 stdout/stderr，返回本次日志文件路径。

    - 所有 stdout/stderr 内容实时写入 ``logs/gui-<时间戳>.log``。
    - 同时尽力镜像到原控制台，但回显放在后台线程里，控制台卡死不影响流水线。
    """
    _LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_path = _LOG_DIR / f"gui-{time.strftime('%Y%m%d-%H%M%S')}.log"
    # 行缓冲：每条 print 立刻落盘，崩溃也不丢现场
    log_file = log_path.open("a", encoding="utf-8", buffering=1)
    lock = threading.Lock()
    out_q: "queue.Queue[str]" = queue.Queue(maxsize=_MAX_QUEUED_LINES)
    err_q: "queue.Queue[str]" = queue.Queue(maxsize=_MAX_QUEUED_LINES)
    stop = threading.Event()

    def _pump(q: "queue.Queue[str]", console) -> None:
        while not stop.is_set():
            try:
                s = q.get(timeout=0.25)
            except queue.Empty:
                continue
            try:
                console.write(s)
                console.flush()
            except Exception:
                # 控制台已关闭 / 被冻结：丢弃回显，绝不反压流水线
                pass

    threading.Thread(
        target=_pump, args=(out_q, sys.__stdout__), name="gui-log-pump-out", daemon=True
    ).start()
    threading.Thread(
        target=_pump, args=(err_q, sys.__stderr__), name="gui-log-pump-err", daemon=True
    ).start()

    class _Tee:
        """同步写日志文件，异步镜像到原控制台；文件写是唯一持久路径。"""

        def __init__(self, q: "queue.Queue[str]") -> None:
            self._q = q

        def write(self, s: str) -> int:
            with lock:
                try:
                    log_file.write(s)
                except Exception:
                    pass
            if s:
                try:
                    self._q.put_nowait(s)
                except queue.Full:
                    pass  # 控制台冻死：丢回显，保流水线
            return len(s)

        def flush(self) -> None:
            with lock:
                try:
                    log_file.flush()
                except Exception:
                    pass

        def isatty(self) -> bool:
            return False  # 不是 tty，避免某些库走交互分支

    sys.stdout = _Tee(out_q)  # type: ignore[assignment]
    sys.stderr = _Tee(err_q)  # type: ignore[assignment]
    _disable_windows_quick_edit()
    return log_path

"""Touhou Manga Translator GUI — 本地 Web 服务器启动脚本。

用法：
  uv run python scripts/run_gui.py [--port 8000] [--host 127.0.0.1] [--no-browser]
"""
from __future__ import annotations

import argparse
import sys
import threading
import time
import webbrowser
from pathlib import Path

# 把 src/ 加入 path（与 run_pipeline.py 一致）
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

# 先加固控制台输出：把 print / uvicorn 日志导向日志文件，避免 Windows 控制台
# 被点进"标记模式"时整条流水线阻塞在某个 print 上。必须在 uvicorn 之前装。
from amta.gui.console import install_gui_console  # noqa: E402

_log_path = install_gui_console()
print(f"[Touhou Manga Translator] logs -> {_log_path}")

import uvicorn


def main() -> int:
    ap = argparse.ArgumentParser(description="Touhou Manga Translator GUI")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--no-browser", action="store_true", help="don't open browser")
    args = ap.parse_args()

    url = f"http://{args.host}:{args.port}"

    if not args.no_browser:
        def _open() -> None:
            time.sleep(1.5)
            webbrowser.open(url)
        threading.Thread(target=_open, daemon=True).start()

    print(f"[Touhou Manga Translator] starting on {url}")
    print("[Touhou Manga Translator] press Ctrl+C to stop")
    uvicorn.run("amta.gui.server:app", host=args.host, port=args.port, reload=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

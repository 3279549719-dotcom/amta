"""项目路径与公共 IO 工具 — 消除各脚本重复的 ROOT/OUTPUT/DATA 样板。"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent.parent.parent  # amta/ 仓库根（src/amta/common/paths.py → 上溯四级）
OUTPUT = ROOT / "output"
DATA = OUTPUT / "data"
REPORTS = OUTPUT / "reports"
CROPS = OUTPUT / "crops"


def ensure_output() -> None:
    """确保 output/ 下常用目录存在。"""
    for d in (OUTPUT, DATA, REPORTS, CROPS):
        d.mkdir(parents=True, exist_ok=True)


def ensure_utf8_stdio() -> None:
    """Windows 控制台默认 GBK：强制 UTF-8 输出，避免打印日文/中文 UnicodeEncodeError。"""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="replace")


def read_json(path: Path | str) -> Any:
    """读 UTF-8 JSON。"""
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path: Path | str, data: Any) -> Path:
    """写 UTF-8 JSON（自动建父目录），返回落盘路径。"""
    dest = Path(path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return dest

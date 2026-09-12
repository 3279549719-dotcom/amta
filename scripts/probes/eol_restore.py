"""从 HEAD 恢复文件的行尾风格，只保留指定的内容改动。

起因：edit/write 工具会把 LF 文件翻成 CRLF，一次 1 行改动会膨胀成整文件 diff。
项目 .gitattributes 是 `* -text` + core.autocrlf=true，所以行尾不被 git 归一化，
必须自己还原。

用法：python scripts/probes/eol_restore.py <相对路径>
"""

from __future__ import annotations

import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

import amta  # noqa: F401  # UTF-8 收口点：本脚本输出中文，不 import amta 就是乱码


def head_bytes(rel: str) -> bytes:
    return subprocess.run(
        ["git", "show", f"HEAD:{rel}"], cwd=ROOT, capture_output=True, check=True
    ).stdout


def detect_eol(data: bytes) -> bytes:
    crlf = data.count(b"\r\n")
    lf = data.count(b"\n") - crlf
    return b"\r\n" if crlf > lf else b"\n"


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__)
        return 2
    rel = argv[1].replace("\\", "/")
    path = ROOT / rel
    old = head_bytes(rel)
    eol = detect_eol(old)
    cur = path.read_bytes()
    # 归一化到 LF -> 按原风格重排
    text = cur.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    if eol == b"\r\n":
        text = text.replace(b"\n", b"\r\n")
    if text != cur:
        path.write_bytes(text)
        label = "CRLF" if eol == b"\r\n" else "LF"
        print(f"{rel}: 行尾已还原为 {label}")
    else:
        print(f"{rel}: 行尾本来就是对的，无需改动")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

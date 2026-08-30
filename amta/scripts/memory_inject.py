"""memory_inject — SessionStart hook：把记忆包打到 stdout（CC 原生注入为上下文）。

协议（code.claude.com/docs/en/hooks）：SessionStart 的 plain stdout 直接入上下文；
stdin 是事件 JSON（含 source: startup/resume/clear/compact/fork）。
纪律：① 恒 exit 0（绝不阻塞会话启动）；② 必须消费完 stdin；
     ③ source=compact 出瘦包（≤0.5KB），其余全量包（≤1.5KB）；④ 空地产也要有合法输出。
手动测试：echo '{"source":"startup"}' | python scripts/memory_inject.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from amta.memory.estate import build_pack, estate_root


def main() -> int:
    raw = ""
    if not sys.stdin.isatty():
        raw = sys.stdin.read()
    source = "startup"
    try:
        payload = json.loads(raw) if raw.strip() else {}
        source = payload.get("source", "startup") or "startup"
    except (json.JSONDecodeError, ValueError):
        source = "startup"  # 坏 JSON 不升级为故障：给默认包
    if source not in ("startup", "resume", "clear", "compact", "fork"):
        source = "startup"
    try:
        pack = build_pack(estate_root(), source=source)
    except Exception:  # noqa: BLE001 — hook 纪律：地产读取任何异常都不阻塞会话
        pack = "=== AMTA 记忆包 (degraded) ===\n异常先 memory_grep 再动手"
    print(pack)
    return 0  # hook 纪律：任何情况下不阻塞会话


if __name__ == "__main__":
    raise SystemExit(main())

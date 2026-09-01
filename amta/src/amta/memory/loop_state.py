"""loop_state — 循环接续状态（自主循环的记账本）。

机器可读 JSON（默认 repo 根 loop_state.json），由循环/会话每步自动更新；
注入包只吐一行摘要（estate.build_pack 调用本模块）；独立进程 harness 读同一文件（B 可复用）。

字段约定（全部可空字符串）：
  mission        当前任务一句话（如「检测调优 p14/18」）
  current_step   进行到哪（如「对比 V2 实验」）
  next_action    下一步做什么（如「调 conf 阈值并重跑 eval」）
  last_verified  上一步的验证结果（如「0 漏洞，12 框」）
  escalation     升级点（需要人/异常；可空）
  updated_at     最后更新时间（ISO 字符串，由 update() 维护）

写路径 update() 原子替换（先写临时文件再 os.replace），避免半截状态被注入读到。
"""
from __future__ import annotations

import datetime
import json
import os
from pathlib import Path

ORDER = (
    ("任务", "mission"),
    ("步", "current_step"),
    ("下一步", "next_action"),
    ("验证", "last_verified"),
    ("升级", "escalation"),
)


def path(root: Path) -> Path:
    """状态文件位置（默认 repo 根 loop_state.json）。"""
    return root / "loop_state.json"


def load(root: Path) -> dict:
    """读取状态；文件缺失/损坏一律返回 {}（不抛，注入纪律）。"""
    p = path(root)
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def summarize(state: dict) -> str:
    """把状态压成一行摘要，供注入包/接续读取。无字段返回（无状态）。"""
    parts = [f"{label}：{state.get(key)}" for label, key in ORDER if state.get(key)]
    if state.get("updated_at"):
        parts.append(f"更新 {state['updated_at']}")
    return " | ".join(parts) if parts else "（无状态）"


def update(root: Path, **fields: str | None) -> dict:
    """合并字段并落盘（原子替换）。显式传 None 的字段跳过；updated_at 恒更新。"""
    state = load(root)
    for key, value in fields.items():
        if value is not None:
            state[key] = value
    state["updated_at"] = datetime.datetime.now().isoformat(timespec="minutes")
    target = path(root)
    tmp = target.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, target)
    return state

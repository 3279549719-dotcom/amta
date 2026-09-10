"""loop_state — 循环接续状态（自主循环的记账本，schema v2）。

机器可读 JSON（默认 repo 根 loop_state.json），由循环/会话每步自动更新；
注入包只吐一行摘要（estate.build_pack 调用本模块）；独立进程 harness 读同一文件。

字段约定：
  mission        当前大目标（mission-runner 模式下 = 顶层目标 + 范围/授权，见 ADR-028）
  plan           可选：任务拆解清单 list[{chunk_id, desc, acceptance, done}]。
                 mission 级喂入：首轮 agent 自拆，后续每轮推进一个 chunk，
                 plan 全 done 才判完成。schema v2 新增。
  current_step   进行到哪（最近完成的一步 / 一个 chunk 成果）
  next_action    下一步做什么（mission 模式 = 下一个 chunk 的自续指引）
  last_verified  上一步的验证结果
  escalation     升级点（需要人 / 异常；可空）
  resume_req     可选：agent 声明「下一 chunk 真需跨轮连续推理」，请求 --session-id resume
                 （按需例外，默认留空，不主动用）
  status         可选：BLOCKED = 需人裁决、循环应停止；空 / 缺省 = 正常
  updated_at     最后更新时间（ISO 字符串）

写路径 update() / plan_add() / plan_done() 一律原子替换（先写临时文件再 os.replace），
避免半截状态被注入读到。schema v2 向后兼容 v0：旧状态无 plan/resume_req 字段照常读写。
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
CHUNK_KEYS = ("chunk_id", "desc", "acceptance", "done")


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


def plan_list(state: dict) -> list[dict]:
    """取 plan 数组（畸形/缺失一律回 []，不抛）。"""
    plan = state.get("plan")
    if not isinstance(plan, list):
        return []
    return [c for c in plan if isinstance(c, dict)]


def plan_progress(state: dict) -> str | None:
    """plan 进度段（如「计划 2/5」）；无 plan 返回 None（summarize 不显示）。"""
    plan = plan_list(state)
    if not plan:
        return None
    done = sum(1 for c in plan if c.get("done"))
    return f"计划 {done}/{len(plan)}"


def summarize(state: dict) -> str:
    """把状态压成一行摘要，供注入包/接续读取。无字段返回（无状态）。"""
    parts = [f"{label}：{state.get(key)}" for label, key in ORDER if state.get(key)]
    prog = plan_progress(state)
    if prog:
        parts.append(prog)
    if state.get("updated_at"):
        parts.append(f"更新 {state['updated_at']}")
    return " | ".join(parts) if parts else "（无状态）"


def _write(root: Path, state: dict) -> dict:
    """原子落盘（临时文件 + os.replace），updated_at 恒刷新。"""
    state["updated_at"] = datetime.datetime.now().isoformat(timespec="minutes")
    target = path(root)
    tmp = target.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, target)
    return state


def update(root: Path, **fields: str | None) -> dict:
    """合并标量字段并落盘（原子替换）。显式传 None 的字段跳过；updated_at 恒更新。"""
    state = load(root)
    for key, value in fields.items():
        if value is not None:
            state[key] = value
    return _write(root, state)


def plan_add(root: Path, chunk_id: str, desc: str, acceptance: str = "") -> dict:
    """向 plan 追加一个 chunk（done=False）。同 chunk_id 已存在则跳过（幂等）。"""
    state = load(root)
    plan = plan_list(state)
    if any(c.get("chunk_id") == chunk_id for c in plan):
        return state
    plan.append({"chunk_id": chunk_id, "desc": desc, "acceptance": acceptance, "done": False})
    state["plan"] = plan
    return _write(root, state)


def plan_done(root: Path, chunk_id: str) -> dict:
    """把指定 chunk 标记 done=True（不存在则静默不改）。"""
    state = load(root)
    plan = plan_list(state)
    for c in plan:
        if c.get("chunk_id") == chunk_id:
            c["done"] = True
    state["plan"] = plan
    return _write(root, state)


def plan_reset(root: Path) -> dict:
    """清空全部 plan（用于推翻首轮拆解、重新拆）。"""
    state = load(root)
    state["plan"] = []
    return _write(root, state)

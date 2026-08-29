"""ADR-016 真 function calling 工具机 — 从 translate.py 拆出的深模块。

唯一归属：
- TERM_BUDGET/GET_CONTEXT_BUDGET/VISION_BUDGET/MAX_TOOL_ROUNDS  预算常量（真拦截）
- TOOLS_SCHEMA  DeepSeek OpenAI 兼容 tools 声明
- build_tools_context  预取式上下文（旧 ADR-016 预取，向后兼容）
- execute_tool  真工具执行器（lookup_term/get_context）
- run_tool_loop 真工具循环（模型请求→执行→回传→继续，预算/轮次拦截）

translate_with_retry 与 scripts/repair_failed.py 共用的 function-calling 层；
从 translate 拆出后，repair_failed 不再依赖整个 translate 模块（Leverage：一个实现喂两个调用方）。
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from amta.metrics import norm

# ADR-016 Tools Contract：预算常量（真拦截——超限拒绝服务，非死常量）
TERM_BUDGET = 10          # 每页 lookup_term 调用预算
GET_CONTEXT_BUDGET = 3    # 每页 get_context 调用预算
VISION_BUDGET = 2         # 每页 vision 调用预算（第一版未接线，预留）
MAX_TOOL_ROUNDS = 6       # 单批工具循环轮次上限（防死循环）

# 真 function calling 工具声明（DeepSeek OpenAI 兼容 tools 格式）
TOOLS_SCHEMA = [
    {
        "type": "function",
        "function": {
            "name": "lookup_term",
            "description": "查询本子已确认的术语/角色译名（如 豊姫→丰姬）。翻译中遇到专有名词、角色名、作品术语不确定译法时调用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "term": {"type": "string", "description": "要查询的日文术语或角色名原文"}
                },
                "required": ["term"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_context",
            "description": "获取前几页的译文（保持风格/术语一致）。翻译当前页前可调用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "pages": {"type": "integer", "description": "回溯页数，最多 3"}
                },
                "required": [],
            },
        },
    },
]


def build_tools_context(canon: list[dict], work_state: dict,
                        prev_pages: list[dict] | None = None,
                        open_questions: list[dict] | None = None) -> str:
    """预取式 Tools 上下文（ADR-016）：当前页相关术语 + 前页译文显式注入。

    lookup_term/get_context 为本地文件读（免费），按 TERM_BUDGET 限条防 prompt 膨胀。
    """
    parts = []
    terms = work_state.get("terms", {})
    cur_text = " ".join(r["text"] for r in canon)
    rel = {k: v for k, v in terms.items()
           if norm(k) and (norm(k) in norm(cur_text) or norm(cur_text) in norm(k))}
    if rel:
        parts.append(f"工具查得·本页相关术语(最多{TERM_BUDGET}条):")
        for k, v in list(rel.items())[:TERM_BUDGET]:
            parts.append(f"- {k} = {v.get('translation', '?')} (status={v.get('status', '?')})")
    if prev_pages:
        parts.append("工具查得·前页译文:")
        parts.extend(f"[{p.get('page', '?')}] {p.get('translated', '')}" for p in prev_pages[-3:])
    return "\n".join(parts)


def execute_tool(name: str, args: dict, work_state: dict,
                 prev_pages: list[dict] | None = None,
                 state_dir: Path | str | None = None) -> str:
    """真工具执行器：lookup_term 查 work_state 术语/角色；get_context 读前页译文。

    返回给模型的文本结果（本地文件读，免费）；预算拦截由调用方（工具循环）负责。
    """
    ws = work_state or {}
    if name == "lookup_term":
        term = str(args.get("term", "")).strip()
        if not term:
            return "参数缺失：请提供 term"
        hit: dict[str, Any] | None = None
        for pool, kind in ((ws.get("terms", {}), "术语"), (ws.get("characters", {}), "角色")):
            for k, v in pool.items():
                if k == term or norm(k) == norm(term):
                    hit = {**v, "kind": kind, "key": k}
                    break
            if hit:
                break
        if not hit:
            return f"未找到术语「{term}」的已确认译名（可基于上下文自行判断）"
        trans = hit.get("translation") or hit.get("canon_translation") or "?"
        status = hit.get("status", "?")
        src = hit.get("source", "?")
        return f"{hit['kind']}「{hit['key']}」= {trans}（status={status}，来源 {src}）"
    if name == "get_context":
        pages = max(1, min(int(args.get("pages") or 3), 3))
        return _build_semantic_context(pages, work_state or {}, prev_pages, state_dir)
    return f"未知工具：{name}"


# Lesson 03 实践：get_context 语义化传递的常量
CATEGORY_LABELS = {
    "dialogue_bubble": "对话",
    "overlay_text": "覆盖文字",
    "sfx": "拟声",
}
MAX_REGIONS_PER_PAGE = 15
MAX_RELATIONSHIPS = 3
MAX_TERMS = 5


def _build_semantic_context(pages: int, work_state: dict,
                             prev_pages: list[dict] | None,
                             state_dir: Path | str | None) -> str:
    """构建带语义标注的前页上下文（Lesson 03 实践）。

    优先读 artifacts/ 下的单页 canon+translation（带 category 标注），
    回退到汇总 translation.json / prev_pages 参数。
    附加 work_state 的 relationships（最多3条，confirmed优先）和相关术语（最多5条）。
    """
    parts: list[str] = []

    # 1. 尝试读单页 canon+translation（带 category 标注）
    page_blocks = _read_page_blocks_from_artifacts(state_dir, pages)
    if page_blocks:
        parts.append("前页上下文：")
        for page_num, regions, _src_texts in page_blocks:
            parts.append(f"--- 第{page_num}页（共{len(regions)}条）---")
            for rid, label, translation in regions[:MAX_REGIONS_PER_PAGE]:
                short_id = rid.split("_")[-1] if "_" in rid else rid
                parts.append(f"[{label}] {short_id}: {translation}")
    else:
        # 回退：旧的汇总 translation.json / prev_pages 方式
        fallback = _read_fallback_context(state_dir, prev_pages, pages)
        if fallback:
            parts.append(fallback)

    if not parts:
        return "暂无前页译文"

    # 2. 附加 relationships（最多3条，confirmed优先，inferred标低置信度）
    rel_lines = _format_relationships(work_state.get("relationships", []))
    if rel_lines:
        parts.append("\n已确认角色关系：")
        parts.extend(rel_lines)

    # 3. 附加前页相关术语（最多5条，norm模糊匹配）
    all_src_texts = []
    for _, _, src_texts in page_blocks:
        all_src_texts.extend(src_texts)
    term_lines = _format_relevant_terms(work_state.get("terms", {}), all_src_texts)
    if term_lines:
        parts.append("\n前页相关术语：")
        parts.extend(term_lines)

    return "\n".join(parts)


def _read_page_blocks_from_artifacts(state_dir, pages: int) -> list[tuple[int, list[tuple[str, str, str]], list[str]]]:
    """从 artifacts/ 目录读单页 canon+translation，返回 [(page_num, [(rid, label, translation)], src_texts)]。

    空列表表示没有找到任何单页文件（调用方应回退）。
    canon 不存在但 translation 存在时，用默认 label "文本"。
    """
    if state_dir is None:
        return []
    artifacts_dir = Path(state_dir).parent / "artifacts"
    if not artifacts_dir.exists():
        return []

    # 找所有 page_N_translation.json 文件（canon 可能不存在，但 translation 一定有）
    trans_files = sorted(
        artifacts_dir.glob("page_*_translation.json"),
        key=lambda p: int(p.stem.split("_")[1]) if p.stem.split("_")[1].isdigit() else 0,
    )
    if not trans_files:
        return []

    # 取最后 N 页
    selected = trans_files[-pages:]
    blocks = []
    for trans_path in selected:
        # 解析页码
        m = re.match(r"page_(\d+)_translation", trans_path.name)
        if not m:
            continue
        page_num = int(m.group(1))

        # 读 translation
        try:
            trans_doc = json.loads(trans_path.read_text(encoding="utf-8"))
            translations = trans_doc.get("translations", {})
        except (json.JSONDecodeError, OSError):
            continue
        if not translations:
            continue

        # 读 canon（可能不存在）
        canon_path = artifacts_dir / f"page_{page_num}_canon.json"
        canon_map: dict[str, dict] = {}
        src_texts = []
        if canon_path.exists():
            try:
                canon_list = json.loads(canon_path.read_text(encoding="utf-8"))
                if isinstance(canon_list, list):
                    for item in canon_list:
                        if isinstance(item, dict) and item.get("region_id"):
                            canon_map[item["region_id"]] = item
                            if item.get("text"):
                                src_texts.append(item["text"])
            except (json.JSONDecodeError, OSError):
                pass

        # 按 translation 的 key 顺序组装 region（canon 可能没有所有 region）
        regions = []
        for rid, translation in translations.items():
            if not translation:
                continue
            canon_item = canon_map.get(rid, {})
            category = canon_item.get("category", "")
            label = CATEGORY_LABELS.get(category, "文本")
            regions.append((rid, label, translation))

        if regions:
            blocks.append((page_num, regions, src_texts))

    return blocks


def _read_fallback_context(state_dir, prev_pages, pages: int) -> str:
    """回退：旧的汇总 translation.json / prev_pages 方式（无 category 标注）。"""
    candidates: list[Path] = []
    if state_dir is not None:
        sdir = Path(state_dir)
        candidates = [sdir.parent / "artifacts" / "translation.json",
                      sdir / "translation.json"]
    for p in candidates:
        if p.exists():
            try:
                doc = json.loads(p.read_text(encoding="utf-8"))
                trans = doc.get("translations", {})
                by_page: dict[str, list[str]] = {}
                for rid, t in trans.items():
                    m = re.match(r"page_(\d+)", str(rid))
                    pg = m.group(1) if m else "?"
                    by_page.setdefault(pg, []).append(f"[{rid}] {t}")
                ordered = sorted(by_page.items(), key=lambda kv: kv[0])
                selected = ordered[-pages:]
                if selected:
                    return "前页译文：\n" + "\n\n".join("\n".join(v) for _, v in selected)
            except (json.JSONDecodeError, OSError):
                pass
    if prev_pages:
        lines = [f"[{h.get('page', '?')}] {h.get('translated', '')}" for h in prev_pages[-pages:]]
        return "前页译文：\n" + "\n".join(lines)
    return ""


def _format_relationships(relationships: list[dict]) -> list[str]:
    """格式化 relationships，最多 MAX_RELATIONSHIPS 条，confirmed 优先，inferred 标低置信度。"""
    if not relationships:
        return []

    # 按 status 排序：confirmed 优先，然后 inferred，然后其他
    status_order = {"confirmed": 0, "inferred": 1, "candidate": 2, "observed": 3}
    sorted_rels = sorted(
        relationships,
        key=lambda r: status_order.get(r.get("status", ""), 99),
    )
    selected = sorted_rels[:MAX_RELATIONSHIPS]

    lines = []
    for rel in selected:
        frm = rel.get("from", "?")
        to = rel.get("to", "?")
        kind = rel.get("kind", "?")
        status = rel.get("status", "?")
        source = rel.get("source", "?")
        confidence_tag = "" if status == "confirmed" else "（推断，低置信度）"
        lines.append(f"- {frm} → {to}：{kind}（来源：{source}）{confidence_tag}")
    return lines


def _format_relevant_terms(terms: dict, src_texts: list[str]) -> list[str]:
    """筛选前页原文中出现的术语（norm 模糊匹配），最多 MAX_TERMS 条。"""
    if not terms or not src_texts:
        return []

    combined_text = " ".join(src_texts)
    relevant = []
    for term, info in terms.items():
        if not isinstance(info, dict):
            continue
        if info.get("status") != "confirmed":
            continue
        # norm 模糊匹配：和 build_tools_context 同样的逻辑
        if norm(term) and (norm(term) in norm(combined_text) or norm(combined_text) in norm(term)):
            translation = info.get("translation") or info.get("canon_translation") or "?"
            status = info.get("status", "?")
            relevant.append(f"- {term} = {translation}（status={status}）")
            if len(relevant) >= MAX_TERMS:
                break
    return relevant


def run_tool_loop(llm, messages, budgets, *, work_state: dict | None = None,
                  prev_pages: list[dict] | None = None,
                  state_dir: Path | str | None = None,
                  tools: list[dict] | None = None) -> str:
    """真工具循环：模型请求工具 → execute_tool 执行 → 结果回传，直到纯文本输出。

    预算（budgets: {工具名: 剩余次数}）超限拒绝服务；轮次超 MAX_TOOL_ROUNDS 强制终止。
    llm 兼容两种签名：(messages) -> str（旧测试）或 (messages, tools) -> dict（chat_with_tools）。
    translate_with_retry 与 scripts/repair_failed.py 共用（原为两处重复实现）。
    """
    raw = ""
    for _round in range(MAX_TOOL_ROUNDS):
        if tools:
            resp = llm(messages, tools=tools)
        else:
            resp = llm(messages)
        if isinstance(resp, str):
            return resp
        calls = resp.get("tool_calls") or []
        content_text = resp.get("content") or ""
        if not calls:
            return content_text
        messages.append({"role": "assistant", "content": content_text or None,
                         "tool_calls": calls})
        for call in calls:
            fn = call.get("function", {})
            name = fn.get("name", "")
            try:
                args = json.loads(fn.get("arguments") or "{}")
            except json.JSONDecodeError:
                args = {}
            if budgets.get(name, 0) <= 0:
                result = f"工具「{name}」本次调用预算已耗尽，请基于现有信息继续翻译"
            else:
                budgets[name] -= 1
                result = execute_tool(name, args, work_state or {}, prev_pages, state_dir)
            messages.append({"role": "tool", "tool_call_id": call.get("id", ""),
                             "content": result})
    return raw

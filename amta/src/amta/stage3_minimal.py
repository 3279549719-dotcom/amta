"""Stage 3 Minimal Translation — 1 LLM call per page, zero tools, zero loops.

Architecture (2026-09-09 VLM refine 移除后):
  1. Code-side prefetch: term injection + context (前页译文 + 术语 + 关系)
  2. Plain-text batch translate (temp=0.3): one call, JSON array, 长度严格校验
  3. Deterministic post-process: residue + glossary check

历史（已移除）:
- VLM full-page refine (2026-08-31 ~ 2026-09-09): OCR correction + bubble types +
  scene + invalid/duplicate。移除原因见 archive/vlm_refine_stage3_2026-09-09.py。
- 重试/二分/长度比护栏/无句末标点重试 (2026-09-08 移除): 数组契约已加固。

SDD rulings baked in:
- page→file mapping is SYSTEMICALLY off-by-one (pipeline page N = file N+1.jpg);
  raw_image_path MUST be passed explicitly by the caller (no auto-detection here).
- page_key requires int (artifacts contract): canon page normalized via _page_to_key.
- Empty region list short-circuits before any LLM call.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Callable

from amta import artifacts, guardrails, workstate
from amta.artifact_store import ArtifactStore
from amta.canon_schema import validate_canon
from amta.metrics import norm
from amta.translate import (extract_relevant_terms, get_chat_config, text_chat,
                            translate_plain)

# === Semantic context builder (moved from translate_tools.py, sole consumer here) ===
_CATEGORY_LABELS = {
    "dialogue_bubble": "对话",
    "overlay_text": "覆盖文字",
    "sfx": "拟声",
}
_MAX_REGIONS_PER_PAGE = 15
_MAX_RELATIONSHIPS = 3
_MAX_TERMS = 5


def build_semantic_context(pages: int, work_state: dict,
                           prev_pages: list[dict] | None,
                           state_dir: Path | str | None) -> str:
    """构建带语义标注的前页上下文。

    优先读 artifacts/ 下的单页 canon+translation（带 category 标注），
    回退到汇总 translation.json / prev_pages 参数。
    附加 work_state 的 relationships（最多3条，confirmed优先）和相关术语（最多5条）。
    """
    parts: list[str] = []

    page_blocks = _read_page_blocks_from_artifacts(state_dir, pages)
    if page_blocks:
        parts.append("前页上下文：")
        for page_num, regions, _src_texts in page_blocks:
            parts.append(f"--- 第{page_num}页（共{min(len(regions), _MAX_REGIONS_PER_PAGE)}条）---")
            for rid, label, translation in regions[:_MAX_REGIONS_PER_PAGE]:
                short_id = rid.split("_")[-1] if "_" in rid else rid
                parts.append(f"[{label}] {short_id}: {translation}")
    else:
        fallback = _read_fallback_context(state_dir, prev_pages, pages)
        if fallback:
            parts.append(fallback)

    if not parts:
        return "暂无前页译文"

    rel_lines = _format_relationships(work_state.get("relationships", []))
    if rel_lines:
        parts.append("\n已确认角色关系：")
        parts.extend(rel_lines)

    all_src_texts = []
    for _, _, src_texts in page_blocks:
        all_src_texts.extend(src_texts)
    term_lines = _format_relevant_terms(work_state.get("terms", {}), all_src_texts)
    if term_lines:
        parts.append("\n前页相关术语：")
        parts.extend(term_lines)

    return "\n".join(parts)


def _read_page_blocks_from_artifacts(state_dir, pages: int) -> list[tuple[int, list[tuple[str, str, str]], list[str]]]:
    """从 artifacts/ 目录读单页 canon+translation。空列表→调用方回退。"""
    if state_dir is None:
        return []
    artifacts_dir = Path(state_dir) / "artifacts"
    if not artifacts_dir.exists():
        return []

    store = ArtifactStore(artifacts_dir)
    page_keys = store.pages("translation")
    if not page_keys:
        return []

    selected = page_keys[-pages:]
    blocks = []
    for page_key in selected:
        m = re.match(r"page_(\d+)$", page_key)
        if not m:
            continue
        page_num = int(m.group(1))
        trans_path = store.resolve("translation", page_key)
        if trans_path is None:
            continue

        try:
            trans_doc = json.loads(trans_path.read_text(encoding="utf-8"))
            translations = trans_doc.get("translations", {})
        except (json.JSONDecodeError, OSError):
            continue
        if not translations:
            continue

        canon_path = store.resolve("canon", page_key)
        canon_map: dict[str, dict] = {}
        src_texts = []
        if canon_path is not None:
            try:
                canon_doc = json.loads(canon_path.read_text(encoding="utf-8"))
                # canon 落盘 doc 信封（schema 2.1, {"items":[...]}）；旧裸 list 兼容读
                canon_list = canon_doc.get("items") if isinstance(canon_doc, dict) else canon_doc
                if isinstance(canon_list, list):
                    for item in canon_list:
                        if isinstance(item, dict) and item.get("region_id"):
                            canon_map[item["region_id"]] = item
                            txt = item.get("baberu_text") or item.get("text")
                            if txt:
                                src_texts.append(txt)
            except (json.JSONDecodeError, OSError):
                pass

        regions = []
        for rid, translation in translations.items():
            if not translation:
                continue
            canon_item = canon_map.get(rid, {})
            category = canon_item.get("category", "")
            label = _CATEGORY_LABELS.get(category, "文本")
            regions.append((rid, label, translation))

        if regions:
            blocks.append((page_num, regions, src_texts))

    return blocks


def _read_fallback_context(state_dir, prev_pages, pages: int) -> str:
    """回退：旧的汇总 translation.json / prev_pages 方式（无 category 标注）。"""
    candidates: list[Path] = []
    if state_dir is not None:
        sdir = Path(state_dir)
        candidates = [sdir / "artifacts" / "translation.json",
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
    """格式化 relationships，confirmed 优先，inferred 标低置信度。"""
    if not relationships:
        return []

    status_order = {"confirmed": 0, "inferred": 1, "candidate": 2, "observed": 3}
    sorted_rels = sorted(
        relationships,
        key=lambda r: status_order.get(r.get("status", ""), 99),
    )
    selected = sorted_rels[:_MAX_RELATIONSHIPS]

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
    """筛选前页原文中出现的术语（norm 模糊匹配），最多 _MAX_TERMS 条。"""
    if not terms or not src_texts:
        return []

    combined_text = " ".join(src_texts)
    relevant = []
    for term, info in terms.items():
        if not isinstance(info, dict):
            continue
        if info.get("status") != "confirmed":
            continue
        if norm(term) and (norm(term) in norm(combined_text) or norm(combined_text) in norm(term)):
            translation = info.get("translation") or info.get("canon_translation") or "?"
            status = info.get("status", "?")
            relevant.append(f"- {term} = {translation}（status={status}）")
            if len(relevant) >= _MAX_TERMS:
                break
    return relevant


def build_prefetch_context(canon: list[dict], work_state: dict,
                           state_dir: Path | None) -> dict[str, Any]:
    """Code-side prefetch: 术语预替换 + glossary 注入 + 前页上下文构建。

    VLM refine 移除后（2026-09-09）：不再有 invalid_ids / duplicate_map /
    ocr_refinements / scene，canon 直接进入术语替换和翻译。
    """
    refined = [dict(r) for r in canon]

    # === Direct term pre-replacement (mechanical guardrail) ===
    # Replace locked terminology (from pre-scan) with Chinese translations
    # BEFORE glossary injection. This makes glossary injection a no-op
    # (Japanese terms no longer in cur_text) and ensures LLM translates
    # a 日中混合文 where terms are already correct. Zero retry, zero repair.
    _locked = {}
    for _k, _v in work_state.get("terms", {}).items():
        if _v.get("status") == "confirmed" and _v.get("translation"):
            _locked[_k] = _v["translation"]
    if _locked and refined:
        from amta.term_replace import replace_in_canon
        refined = replace_in_canon(refined, _locked)
    # === End term pre-replacement ===

    cur_text = " ".join(r.get("baberu_text") or r.get("text") or "" for r in refined)
    relevant = extract_relevant_terms(cur_text, work_state.get("terms", {}))
    system_parts = []
    if relevant:
        term_lines = ["相关术语（必须使用以下译名）："]
        for term, meta in relevant.items():
            trans = meta.get("translation") or meta.get("canon_translation") or "?"
            term_lines.append(f"- {term} → {trans}")
        system_parts.append("\n".join(term_lines))
    system_extra = "\n\n".join(system_parts)

    context_prefix = ""
    if state_dir:
        try:
            ctx = build_semantic_context(3, work_state, None, state_dir)
            if ctx and ctx != "暂无前页译文":
                context_prefix = ctx
        except Exception:
            pass

    return {
        "refined_canon": refined,
        "system_extra": system_extra,
        "context_prefix": context_prefix,
    }


def _page_to_key(raw: Any) -> str:
    """canon page 字段 → artifacts.page_key（page_key 契约要求 int）。"""
    if isinstance(raw, bool):
        return ""
    if isinstance(raw, int):
        return artifacts.page_key(raw)
    m = re.search(r"\d+", str(raw))
    return artifacts.page_key(int(m.group())) if m else ""


def translate_page_minimal(work_id: str, canon, *,
                           raw_image_path: Path | str | None = None,
                           state_dir: Path | str | None = None,
                           page: str | None = None,
                           llm_text: Callable | None = None,
                           context_enabled: bool = True) -> dict:
    """Minimal translation entry: prefetch → plain translate → post-process.

    VLM refine 已移除（2026-09-09）：不再接受 vlm_enabled / llm_vlm 参数，
    不再做视觉 LLM 调用。raw_image_path 参数保留为接口兼容但不再使用。
    """
    if isinstance(canon, dict):
        canon_items = canon.get("items", [])
    else:
        canon_items = list(canon)
    problems = validate_canon(canon_items)
    if problems:
        raise ValueError(f"canon input schema failed: {'; '.join(problems[:5])}")

    ws = workstate.load_state(work_id) if work_id else {}
    env_page = page or (_page_to_key(canon_items[0]["page"]) if canon_items else "")

    if llm_text is None:
        cfg = get_chat_config()

        def _default_text(messages, tools=None):
            return text_chat(cfg["base_url"], cfg["model"], messages,
                             api_key=cfg["api_key"], temperature=0.3)
        llm_text = _default_text

    ctx = build_prefetch_context(canon_items, ws, Path(state_dir) if state_dir else None)

    translations: dict[str, str] = {}
    if ctx["refined_canon"]:
        translations = translate_plain(
            ctx["refined_canon"], llm_text,
            system_extra=ctx["system_extra"],
            context_prefix=ctx["context_prefix"],
            context_enabled=context_enabled,
        )

    result: dict[str, str] = {}
    for r in canon_items:
        rid = r["region_id"]
        if rid in translations:
            result[rid] = translations[rid]
        else:
            result[rid] = ""

    # P2 机械标点对齐：已禁用（2026-09-06 grill-with-docs 决策）。
    # 原文标点必须保留，LLM 自然添加的中文标点有助于排版断列，删标点机制自毁。

    residue = guardrails.japanese_residue_check(list(result.values()))
    # glossary_violations 已停用: 纯机械检查出违规也无法触发重翻/修正, 无实际价值
    violations: list[str] = []

    out = artifacts.stamp({
        "translations": result,
        "residue": residue,
        "glossary_violations": violations,
    }, work_id or "", env_page)
    return out

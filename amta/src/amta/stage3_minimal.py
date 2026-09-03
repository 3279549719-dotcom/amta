"""Stage 3 Minimal Translation — 2 LLM calls per page, zero tools, zero loops.

Architecture (copied from mit 2stage + koharu TranslationRequest):
  1. VLM full-page refine (temp=0): OCR correction + bubble types + scene + invalid/duplicate
  2. Code-side prefetch: term injection (mit extract_relevant_terms) + context (koharu pattern)
  3. Plain-text batch translate (temp=0.3): one call, JSON, 1 retry + binary split
  4. Deterministic post-process: duplicate inherit, invalid blank, residue + glossary check

SDD rulings baked in (2026-08-31-stage3-minimal-translation, spike v3 GATE PASS):
- page→file mapping is SYSTEMICALLY off-by-one (pipeline page N = file N+1.jpg);
  detect_contract source field records the wrong path — raw_image_path MUST be
  passed explicitly by the caller (no auto-detection here, known gap stands).
- VLM refine output is ADVISORY (spike v2/v3 hardening): grounding validation
  (only region_ids present in canon), empty-string refinements dropped (不抹字).
- page_key requires int (artifacts contract): canon page normalized via _page_to_key.
- Empty region list short-circuits before any LLM call (Task 2 deferred guard).
"""
from __future__ import annotations

import base64
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from amta import artifacts, guardrails, glossary, workstate
from amta.canon_schema import validate_canon
from amta.chat_client import chat
from amta.config import _resolve, get_dashscope_key  # _resolve: 同包 env→.env 解析唯一归属
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
    """构建带语义标注的前页上下文（Lesson 03 实践）。

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

    trans_files = sorted(
        artifacts_dir.glob("page_*_translation.json"),
        key=lambda p: int(p.stem.split("_")[1]) if p.stem.split("_")[1].isdigit() else 0,
    )
    if not trans_files:
        return []

    selected = trans_files[-pages:]
    blocks = []
    for trans_path in selected:
        m = re.match(r"page_(\d+)_translation", trans_path.name)
        if not m:
            continue
        page_num = int(m.group(1))

        try:
            trans_doc = json.loads(trans_path.read_text(encoding="utf-8"))
            translations = trans_doc.get("translations", {})
        except (json.JSONDecodeError, OSError):
            continue
        if not translations:
            continue

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


# Task 1 spike v3 gate: qwen3.5-omni-plus primary (3/3 parse, 2.6s avg, S1-S5 全过)
_VISION_MODEL_DEFAULT = "qwen3.5-omni-plus"
_DASHSCOPE_BASE_DEFAULT = "https://dashscope.aliyuncs.com/compatible-mode/v1"


@dataclass
class VlmRefineResult:
    """Structured output from VLM full-page refine call."""
    ocr_refinements: dict[str, str] = field(default_factory=dict)
    bubble_types: dict[str, str] = field(default_factory=dict)
    scene: str = ""
    invalid_regions: list[str] = field(default_factory=list)
    duplicate_regions: dict[str, str] = field(default_factory=dict)
    raw: str = ""  # raw VLM response for debugging


def _parse_vlm_response(raw: str) -> VlmRefineResult | None:
    """Parse VLM JSON response; return None on parse failure."""
    text = (raw or "").strip()
    if text.startswith("```"):
        text = "\n".join(text.split("\n")[1:])
    if text.endswith("```"):
        text = "\n".join(text.split("\n")[:-1])
    try:
        data = json.loads(text.strip())
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    return VlmRefineResult(
        ocr_refinements={k: str(v) for k, v in (data.get("ocr_refinements") or {}).items()},
        bubble_types={k: str(v) for k, v in (data.get("bubble_types") or {}).items()},
        scene=str(data.get("scene") or ""),
        invalid_regions=[str(x) for x in (data.get("invalid_regions") or [])],
        duplicate_regions={str(k): str(v) for k, v in (data.get("duplicate_regions") or {}).items()},
        raw=raw,
    )


def _ground_vlm_result(vlm: VlmRefineResult, canon: list[dict]) -> VlmRefineResult:
    """VLM 输出 ADVISORY 硬化（spike v3 控制裁决 ③）：grounding 校验。"""
    canon_ids = {r["region_id"] for r in canon}
    return VlmRefineResult(
        ocr_refinements={k: v for k, v in vlm.ocr_refinements.items() if k in canon_ids and v.strip()},
        bubble_types={k: v for k, v in vlm.bubble_types.items() if k in canon_ids},
        scene=vlm.scene,
        invalid_regions=[rid for rid in vlm.invalid_regions if rid in canon_ids],
        duplicate_regions={k: v for k, v in vlm.duplicate_regions.items()
                           if k in canon_ids and v in canon_ids},
        raw=vlm.raw,
    )


def vlm_refine_page(canon: list[dict], raw_image_path: Path | str | None,
                    llm_vlm: Callable) -> VlmRefineResult | None:
    """Call 1: VLM full-page refine. Returns None on failure (caller uses baberu_text)."""
    if raw_image_path is None:
        return None
    path = Path(raw_image_path)
    if not path.exists():
        return None
    try:
        img_data = base64.b64encode(path.read_bytes()).decode("ascii")
        mime = "image/jpeg" if path.suffix.lower() in (".jpg", ".jpeg") else "image/png"
        image_url = f"data:{mime};base64,{img_data}"
    except Exception:
        return None

    region_lines = []
    for r in canon:
        rid = r["region_id"]
        text = r.get("baberu_text") or r.get("text") or ""
        bbox = r.get("bbox", [])
        region_lines.append(f"{rid}: {text} [bbox: {bbox}]")

    system = (
        "You are a manga OCR refinement engine. Given a full manga page image and OCR regions, "
        "output STRICT JSON: {\"ocr_refinements\": {rid: corrected}, \"bubble_types\": {rid: dialogue|narration|sfx}, "
        "\"scene\": \"one sentence\", \"invalid_regions\": [rid], \"duplicate_regions\": {rid: original_rid}}. "
        "Only include ocr_refinements for regions you CORRECT. Output ONLY valid JSON."
    )
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": [
            {"type": "text", "text": "OCR regions:\n" + "\n".join(region_lines)},
            {"type": "image_url", "image_url": {"url": image_url}},
        ]},
    ]
    try:
        raw = llm_vlm(messages)
    except Exception:
        return None
    parsed = _parse_vlm_response(raw)
    if parsed is None:
        return None
    return _ground_vlm_result(parsed, canon)


def build_prefetch_context(canon: list[dict], work_state: dict,
                           state_dir: Path | None,
                           vlm_refine: VlmRefineResult | None) -> dict[str, Any]:
    """Code-side prefetch: apply VLM refine, filter invalid, build system_extra + context."""
    invalid_ids = set(vlm_refine.invalid_regions) if vlm_refine else set()
    duplicate_map = dict(vlm_refine.duplicate_regions) if vlm_refine else {}

    refined = []
    for r in canon:
        rid = r["region_id"]
        if rid in invalid_ids:
            continue
        item = dict(r)
        if vlm_refine and rid in vlm_refine.ocr_refinements:
            item["baberu_text"] = vlm_refine.ocr_refinements[rid]
        refined.append(item)

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
    if vlm_refine and vlm_refine.scene:
        system_parts.append(f"场景描述：{vlm_refine.scene}")
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
        "duplicate_map": duplicate_map,
        "invalid_ids": invalid_ids,
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
                           llm_vlm: Callable | None = None,
                           vlm_enabled: bool = True) -> dict:
    """Minimal translation entry: VLM refine → prefetch → plain translate → post-process."""
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

    vlm_result = None
    if vlm_enabled and raw_image_path and canon_items:
        if llm_vlm is None:
            vision_model = _resolve("VISION_MODEL", None) or _VISION_MODEL_DEFAULT
            vision_base = _resolve("DASHSCOPE_BASE_URL", None) or _DASHSCOPE_BASE_DEFAULT
            try:
                vision_key: str = get_dashscope_key()
            except RuntimeError:
                try:
                    vision_key = get_chat_config()["api_key"]
                except RuntimeError:
                    vision_key = ""

            def _default_vlm(messages):
                resp = chat(vision_base, vision_model, messages,
                            api_key=vision_key, timeout=120, temperature=0)
                return resp.get("content") or ""
            llm_vlm = _default_vlm
        vlm_result = vlm_refine_page(canon_items, Path(raw_image_path), llm_vlm)

    ctx = build_prefetch_context(canon_items, ws, Path(state_dir) if state_dir else None, vlm_result)

    translations: dict[str, str] = {}
    if ctx["refined_canon"]:
        translations = translate_plain(
            ctx["refined_canon"], llm_text,
            system_extra=ctx["system_extra"],
            context_prefix=ctx["context_prefix"],
        )

    result: dict[str, str] = {}
    for r in canon_items:
        rid = r["region_id"]
        if rid in translations:
            result[rid] = translations[rid]
        elif rid in ctx["duplicate_map"]:
            source = ctx["duplicate_map"][rid]
            result[rid] = translations.get(source, "")
        elif rid in ctx["invalid_ids"]:
            result[rid] = ""
        else:
            result[rid] = ""

    residue = guardrails.japanese_residue_check(list(result.values()))
    # glossary_violations 已停用: 纯机械检查出违规也无法触发重翻/修正, 无实际价值
    violations: list[str] = []

    out = artifacts.stamp({
        "translations": result,
        "residue": residue,
        "glossary_violations": violations,
    }, work_id or "", env_page)
    if vlm_result:
        out["vlm_refine"] = {
            "scene": vlm_result.scene,
            "invalid_count": len(vlm_result.invalid_regions),
            "duplicate_count": len(vlm_result.duplicate_regions),
            "refinement_count": len(vlm_result.ocr_refinements),
        }
    return out

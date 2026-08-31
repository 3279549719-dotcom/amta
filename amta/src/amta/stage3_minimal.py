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
from amta.translate import (extract_relevant_terms, get_chat_config, text_chat,
                            translate_plain)
from amta.translate_tools import build_semantic_context

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
    # strip markdown fences
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
    """VLM 输出 ADVISORY 硬化（spike v3 控制裁决 ③）：grounding 校验。

    - ocr_refinements：只留 canon 中存在的 region_id，且修正文本非空（空串=抹字，丢弃）
    - invalid_regions / duplicate_regions：同规则（duplicate 的指向也须在 canon 内）
    - bubble_types：同样只留 canon id（下游虽未消费，防未来幻觉 id 流入）
    """
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
    """Call 1: VLM full-page refine. Returns None on failure (caller uses baberu_text).

    llm_vlm signature: (messages) -> str (must handle image content in messages).
    输出经 _ground_vlm_result 硬化后返回；raw_image_path 须由调用方显式传入
    （page→file off-by-one，source 字段不可信，此处不做自动探测）。
    """
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
    """Code-side prefetch: apply VLM refine, filter invalid, build system_extra + context.

    Returns dict with keys:
      refined_canon: list of region dicts (invalid filtered, OCR corrected)
      system_extra: str (glossary terms + scene description)
      context_prefix: str (prior-page context, from build_semantic_context)
      duplicate_map: dict {duplicate_rid: original_rid}
      invalid_ids: set of filtered-out region_ids
    """
    invalid_ids = set(vlm_refine.invalid_regions) if vlm_refine else set()
    duplicate_map = dict(vlm_refine.duplicate_regions) if vlm_refine else {}

    # Apply OCR refinements + filter invalid
    refined = []
    for r in canon:
        rid = r["region_id"]
        if rid in invalid_ids:
            continue
        item = dict(r)
        if vlm_refine and rid in vlm_refine.ocr_refinements:
            item["baberu_text"] = vlm_refine.ocr_refinements[rid]
        refined.append(item)

    # System extra: glossary terms + scene
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

    # Context prefix: prior pages (koharu TranslationRequest context pattern)
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
    """canon page 字段 → artifacts.page_key（page_key 契约要求 int）。

    容忍 "11" / "page_11" / 11 / 11.0 之外的意外类型：不可解析返回 ""（信封 page 留空），
    绝不让 str 漏进 artifacts.page_key 造成 TypeError（SDD 控制裁决 ①）。
    """
    if isinstance(raw, bool):  # bool 是 int 子类，防御性排除
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
    """Minimal translation entry: VLM refine → prefetch → plain translate → post-process.

    Returns TranslationArtifact-compatible dict (schema_version "2.1").
    raw_image_path 须显式传入（off-by-one 已知缺口，不自动探测）；空区域列表零 LLM 调用。
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

    # Default LLM closures (production path)
    if llm_text is None:
        cfg = get_chat_config()

        def _default_text(messages, tools=None):
            return text_chat(cfg["base_url"], cfg["model"], messages, api_key=cfg["api_key"])
        llm_text = _default_text

    # Call 1: VLM refine
    vlm_result = None
    if vlm_enabled and raw_image_path:
        if llm_vlm is None:
            vision_model = _resolve("VISION_MODEL", None) or _VISION_MODEL_DEFAULT
            vision_base = _resolve("DASHSCOPE_BASE_URL", None) or _DASHSCOPE_BASE_DEFAULT
            try:
                # .env 键名为 DASHSCOPE_KEY（非 DASHSCOPE_API_KEY）——get_dashscope_key 双名兼容
                vision_key: str = get_dashscope_key()
            except RuntimeError:
                try:
                    vision_key = get_chat_config()["api_key"]
                except RuntimeError:
                    vision_key = ""

            def _default_vlm(messages):
                resp = chat(vision_base, vision_model, messages, api_key=vision_key, timeout=120)
                return resp.get("content") or ""
            llm_vlm = _default_vlm
        vlm_result = vlm_refine_page(canon_items, Path(raw_image_path), llm_vlm)

    # Code-side prefetch
    ctx = build_prefetch_context(canon_items, ws, Path(state_dir) if state_dir else None, vlm_result)

    # Call 2: plain-text batch translate（空区域列表短路：零 LLM 调用）
    translations: dict[str, str] = {}
    if ctx["refined_canon"]:
        translations = translate_plain(
            ctx["refined_canon"], llm_text,
            system_extra=ctx["system_extra"],
            context_prefix=ctx["context_prefix"],
        )

    # Post-process: duplicate inheritance + invalid blanking
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

    # Deterministic guardrails (record only, no retry)
    residue = guardrails.japanese_residue_check(list(result.values()))
    violations = glossary.check_glossary(canon_items, result, ws)

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

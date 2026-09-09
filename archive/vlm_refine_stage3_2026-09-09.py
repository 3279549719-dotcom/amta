"""[ARCHIVED 2026-09-09] VLM full-page refine — Stage 3 翻译第一步。

移除原因：用户决策 VLM refine 不再需要。OCR confidence 过滤（Q3）已能拦假框，
乱码→空（Q8）已在翻译 prompt 层处理，bubble_type 分类职责在 ADR-030 后不再
影响 inpaint 决策。VLM refine 增加一次视觉 LLM 调用（~2.6s/页），收益不足以
覆盖成本和复杂度。

归档内容：从 stage3_minimal.py 中移除的 VLM refine 全部代码，包括：
- VlmRefineResult dataclass
- _parse_vlm_response / _ground_vlm_result
- vlm_refine_page（视觉 LLM 调用）
- build_prefetch_context 中与 vlm_refine 交互的部分
- translate_page_minimal 中 VLM 调用与输出字段
- 配置常量 _VISION_MODEL_DEFAULT / _DASHSCOPE_BASE_DEFAULT

恢复方式：将本文件中的类/函数合并回 stage3_minimal.py，并在 translate_page_minimal
中恢复调用即可。
"""
from __future__ import annotations

import base64
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from amta.chat_client import chat
from amta.config import _resolve, get_dashscope_key


# === 配置常量 ===
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
    """VLM 输出 ADVISORY 硬化：grounding 校验（只保留 canon 中存在的 region_id）。"""
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


# === build_prefetch_context 中与 vlm_refine 交互的部分（原始版本） ===
# 移除后新版本不再接受 vlm_refine 参数，invalid_ids/duplicate_map 恒为空。
#
# def build_prefetch_context(canon, work_state, state_dir, vlm_refine):
#     invalid_ids = set(vlm_refine.invalid_regions) if vlm_refine else set()
#     duplicate_map = dict(vlm_refine.duplicate_regions) if vlm_refine else {}
#     refined = []
#     for r in canon:
#         rid = r["region_id"]
#         if rid in invalid_ids:
#             continue
#         item = dict(r)
#         if vlm_refine and rid in vlm_refine.ocr_refinements:
#             item["baberu_text"] = vlm_refine.ocr_refinements[rid]
#         refined.append(item)
#     # ... 术语替换 + 上下文构建（保留）
#     if vlm_refine and vlm_refine.scene:
#         system_parts.append(f"场景描述：{vlm_refine.scene}")
#     return {"refined_canon": refined, "system_extra": ..., "context_prefix": ...,
#             "duplicate_map": duplicate_map, "invalid_ids": invalid_ids}


# === translate_page_minimal 中 VLM 调用部分（原始版本） ===
# 移除后新版本不再接受 vlm_enabled / llm_vlm 参数，直接进入 prefetch → translate。
#
# vlm_result = None
# if vlm_enabled and raw_image_path and canon_items:
#     if llm_vlm is None:
#         vision_model = _resolve("VISION_MODEL", None) or _VISION_MODEL_DEFAULT
#         vision_base = _resolve("DASHSCOPE_BASE_URL", None) or _DASHSCOPE_BASE_DEFAULT
#         vision_key = get_dashscope_key()  # 或 fallback 到 chat api_key
#         def _default_vlm(messages):
#             resp = chat(vision_base, vision_model, messages,
#                        api_key=vision_key, timeout=120, temperature=0)
#             return resp.get("content") or ""
#         llm_vlm = _default_vlm
#     vlm_result = vlm_refine_page(canon_items, Path(raw_image_path), llm_vlm)
#
# ctx = build_prefetch_context(canon_items, ws, state_dir, vlm_result)
# ...
# if vlm_result:
#     out["vlm_refine"] = {
#         "scene": vlm_result.scene,
#         "invalid_count": len(vlm_result.invalid_regions),
#         "duplicate_count": len(vlm_result.duplicate_regions),
#         "refinement_count": len(vlm_result.ocr_refinements),
#     }
